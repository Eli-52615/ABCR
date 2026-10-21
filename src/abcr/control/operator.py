"""Single deterministic mutation coordinator; transport and UI hold no powers."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from abcr.control.contracts import ContractError, sha256, strict_object
from abcr.control.bridge import OperatorBridge
from abcr.control.readmodel import build_snapshot
from abcr.control.signals import RunControl
from abcr.explore.goal import validate_goal
from abcr.control.store import SCHEMA_VERSION, ControlStore, StoreError


Handler = Callable[[dict[str, Any], str], dict[str, Any]]


class Operator:
    def __init__(self, store: ControlStore, handlers: dict[str, Handler], *, worker_id: str = "operator"):
        self.store = store; self.handlers = handlers; self.worker_id = worker_id

    def execute(self, effect_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.store.claim_action(effect_id, self.worker_id):
            rows = [x for x in self.store.rows("actions") if x["effect_id"] == effect_id]
            if rows and rows[0]["result_json"]:
                import json
                return json.loads(rows[0]["result_json"])
            raise StoreError("action is already claimed or missing")
        handler = self.handlers.get(intent)
        if handler is None:
            result = {"ok": False, "code": "intent_not_supported", "intent": intent}
            self.store.finish_action(effect_id, worker_id=self.worker_id, state="failed", result=result)
            return result
        try:
            result = handler(payload, effect_id)
        except Exception as exc:
            result = ({"ok": False, **exc.as_dict()} if isinstance(exc, ContractError)
                      else {"ok": False, "code": type(exc).__name__})
            state = ("needs_clarification" if isinstance(exc, ContractError)
                     and exc.code == "needs_clarification" else "failed")
            self.store.finish_action(effect_id, worker_id=self.worker_id, state=state, result=result)
            return result
        final = {"ok": True, "result": result}
        self.store.finish_action(effect_id, worker_id=self.worker_id, state="succeeded", result=final)
        return final


def spawn_dispatch_supervisor(settings: dict[str, Any]) -> subprocess.Popen | None:
    """Start the sealed child without waiting; false qualification is a hard no-op."""
    if settings.get("dispatch_supervisor_qualified") is not True:
        return None
    executable = Path(sys.executable)
    prefix = Path(sys.prefix).resolve()
    lexical = executable.absolute()
    if (not executable.is_absolute() or not lexical.is_relative_to(prefix)
            or not lexical.is_file() or not os.access(lexical, os.X_OK)):
        raise ContractError("dispatch_supervisor_python_unsealed",
                            "supervisor 必须使用当前 sealed release Python")
    release_id = settings.get("release_id")
    if (not isinstance(release_id, str) or prefix.name != "env"
            or prefix.parent.name != release_id
            or os.environ.get("ABCR_RELEASE_ID") != release_id):
        raise ContractError("dispatch_supervisor_release_mismatch",
                            "supervisor interpreter 未绑定当前 active release")
    state_root = Path(settings["dispatch_state_root"])
    info = state_root.lstat()
    if (state_root.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022):
        raise ContractError("dispatch_supervisor_state_root_unsafe", "supervisor state root 不安全")
    log_path = state_root / "supervisor.log"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(log_path, flags, 0o600)
    try:
        log_info = os.fstat(fd)
        if (not stat.S_ISREG(log_info.st_mode) or log_info.st_nlink != 1
                or log_info.st_uid != os.geteuid()):
            raise ContractError("dispatch_supervisor_log_unsafe", "supervisor log 不安全")
        os.fchmod(fd, 0o600)
        return subprocess.Popen(
            [str(lexical), "-I", "-B", "-m", "abcr.control.dispatch_supervisor"],
            stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
            cwd=str(prefix.parent), close_fds=True, start_new_session=True,
            shell=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                 "TMPDIR": "/tmp", "ABCR_RELEASE_ID": release_id,
                 "ABCR_SERVICE_LABEL": "com.abcr.operator-reconciler",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                 "PYTHONUTF8": "1"},
        )
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    """Observe the control DB and reconcile expired mission leases."""
    from abcr.control.queue_runtime import EX_CONFIG, ServiceRuntimeBlocked, load_queue_config

    parser = argparse.ArgumentParser(prog="operator-reconciler")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--init-db", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_queue_config("operator-reconciler")
        settings = strict_object(config["settings"], required={"store_path", "interval_seconds",
                                                              "human_uid", "operator_uid",
                                                              "human_gid", "operator_gid",
                                                              "deployment_id", "protocol_ref",
                                                              "research_repo",
                                                              "research_memory_path",
                                                              "research_group_gid",
                                                              "artifact_receipt_private_key",
                                                              "artifact_receipt_public_key",
                                                              "approval_public_key",
                                                              "persona_root",
                                                              "trusted_dev_bundle_root",
                                                              "bundle_sealer_public_key",
                                                              "ledger_root", "dispatch_queue_root",
                                                              "dispatch_state_root", "release_id",
                                                              "dispatch_supervisor_qualified",
                                                              "execution_profile",
                                                              "evidence_runs_root",
                                                              "sealed_audit_root",
                                                              "broker_receipt_root",
                                                              "broker_receipt_group_gid",
                                                              "auditor_public_key",
                                                              "probe_profile_id",
                                                              "probe_max_output_tokens",
                                                              "trusted_release_root",
                                                              "mission_input_root",
                                                              "mission_input_group_gid"})
        store_path = Path(settings["store_path"])
        interval = settings["interval_seconds"]
        if (type(interval) not in {int, float} or not 0.1 <= interval <= 300
                or type(settings["human_uid"]) is not int
                or type(settings["human_gid"]) is not int
                or type(settings["operator_gid"]) is not int
                or type(settings["research_group_gid"]) is not int
                or type(settings["broker_receipt_group_gid"]) is not int
                or settings["broker_receipt_group_gid"] < 0
                or type(settings["mission_input_group_gid"]) is not int
                or settings["mission_input_group_gid"] < 0
                or type(settings["dispatch_supervisor_qualified"]) is not bool
                or not isinstance(settings["probe_profile_id"], str)
                or not settings["probe_profile_id"]
                or type(settings["probe_max_output_tokens"]) is not int
                or not 1 <= settings["probe_max_output_tokens"] <= 4096
                or (settings["execution_profile"] is not None
                    and not isinstance(settings["execution_profile"], dict))
                or settings["operator_uid"] != os.geteuid()
                or not isinstance(settings["deployment_id"], str) or not settings["deployment_id"]
                or not isinstance(settings["protocol_ref"], str) or not settings["protocol_ref"]):
            raise ContractError("operator_config_invalid", "operator config 不合法")
        if not isinstance(settings["release_id"], str) or not settings["release_id"]:
            raise ContractError("operator_config_invalid", "release_id 必须是固定非空字符串")
        for name in ("research_repo", "research_memory_path",
                     "artifact_receipt_private_key", "artifact_receipt_public_key",
                     "approval_public_key", "ledger_root", "dispatch_queue_root",
                     "dispatch_state_root",
                     "evidence_runs_root", "sealed_audit_root",
                     "broker_receipt_root", "auditor_public_key",
                     "persona_root", "trusted_dev_bundle_root",
                     "bundle_sealer_public_key", "trusted_release_root",
                     "mission_input_root"):
            if not isinstance(settings[name], str) or not Path(settings[name]).is_absolute():
                raise ContractError("operator_config_invalid", f"{name} 必须是固定绝对路径")
        if args.init_db:
            parent = store_path.parent
            info = parent.lstat()
            if (parent.is_symlink() or not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != settings["operator_uid"]
                    or stat.S_IMODE(info.st_mode) & 0o022):
                raise ContractError("operator_store_parent_unsafe",
                                    "control DB parent 必须由 operator 持有且不可被组/其他用户写")
            if store_path.exists() or store_path.is_symlink():
                db_info = store_path.lstat()
                if (store_path.is_symlink() or not stat.S_ISREG(db_info.st_mode)
                        or db_info.st_nlink != 1
                        or db_info.st_uid != settings["operator_uid"]
                        or stat.S_IMODE(db_info.st_mode) != 0o600):
                    raise ContractError("operator_store_unsafe", "现有 control DB owner/mode 不安全")
            store = ControlStore(store_path)
            os.chmod(store_path, 0o600)
            store.quick_check()
            print(json.dumps({"ok": True, "service": "operator-reconciler",
                              "initialized": str(store_path),
                              "schema_version": SCHEMA_VERSION}, sort_keys=True))
            return 0
        if store_path.is_symlink() or not store_path.is_file():
            raise ContractError("operator_store_missing", "control DB 尚未显式初始化")
        if args.doctor:
            # URI read-only mode prevents migrate/schema writes during doctor.
            uri = f"file:{store_path}?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                row = db.execute("PRAGMA quick_check").fetchone()
                tables = {item[0] for item in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"missions", "actions", "services", "releases"}
            if row is None or row[0] != "ok" or not required.issubset(tables):
                raise StoreError("control database semantic doctor failed")
            print(json.dumps({"ok": True, "service": "operator-reconciler",
                              "mode": "lease-reconcile"}, sort_keys=True))
            return 0
        store = ControlStore(store_path)
        bridge = OperatorBridge(human_uid=settings["human_uid"],
                                operator_uid=settings["operator_uid"],
                                human_gid=settings["human_gid"],
                                operator_gid=settings["operator_gid"])

        def no_payload(payload: dict[str, Any], _effect_id: str) -> dict[str, Any]:
            strict_object(payload, required=set())
            return build_snapshot(store).as_dict()

        def explain_stop(payload: dict[str, Any], _effect_id: str) -> dict[str, Any]:
            strict_object(payload, required=set())
            return {"incidents": store.rows("incidents")}

        def budget_status(payload: dict[str, Any], _effect_id: str) -> dict[str, Any]:
            strict_object(payload, required=set())
            return {"status": "UNKNOWN", "reason": "尚无当前价格/校准快照"}

        def control_active_runs(payload: dict[str, Any], desired: str,
                                effect_id: str) -> dict[str, Any]:
            strict_object(payload, required=set())
            actor_id = store.action_actor(effect_id)["open_id"]
            state_root = Path(settings["dispatch_state_root"])
            control_root = state_root / "run-controls"
            if not control_root.exists():
                control_root.mkdir(mode=0o700)
            info = control_root.lstat()
            if (control_root.is_symlink() or not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022):
                raise ContractError("run_control_root_unsafe", "运行控制目录不安全")
            controls = RunControl(control_root)
            queue_root = Path(settings["dispatch_queue_root"])
            run_ids = sorted({path.stem for stage in ("pending", "running", "failed")
                              for path in (queue_root / stage).glob("*.json")})
            for run_id in run_ids:
                controls.set(run_id, desired, release_id=settings["release_id"],
                             actor_id=actor_id,
                             reason=f"owner requested {desired}")
            return {"desired": desired, "run_count": len(run_ids), "run_ids": run_ids}

        worker = Operator(store, {
            "status": no_payload,
            "explain_stop": explain_stop,
            "budget_status": budget_status,
            "pause": lambda payload, effect_id: control_active_runs(payload, "paused", effect_id),
            "resume": lambda payload, effect_id: control_active_runs(payload, "running", effect_id),
            "abort": lambda payload, effect_id: control_active_runs(payload, "aborted", effect_id),
            "run_probe": lambda payload, effect_id: __import__(
                "abcr.control.probe_control", fromlist=["queue_probe"]).queue_probe(
                    store=store,
                    broker=__import__("abcr.control.queue_runtime", fromlist=["WorkBrokerClient"])
                    .WorkBrokerClient(Path(config["broker_socket"])),
                    effect_id=effect_id, payload=payload,
                    persona_root=Path(settings["persona_root"]),
                    profile_id=settings["probe_profile_id"],
                    max_output_tokens=settings["probe_max_output_tokens"]),
            "promote_probe": lambda payload, effect_id: __import__(
                "abcr.control.probe_control", fromlist=["create_promotion_draft"])
                .create_promotion_draft(store=store, effect_id=effect_id, payload=payload),
            "record_reflection": lambda payload, effect_id: __import__(
                "abcr.control.probe_control", fromlist=["record_reflection"])
                .record_reflection(
                    store=store,
                    broker=__import__("abcr.control.queue_runtime", fromlist=["WorkBrokerClient"])
                    .WorkBrokerClient(Path(config["broker_socket"])),
                    effect_id=effect_id, payload=payload,
                    research_memory_path=Path(settings["research_memory_path"])),
        })
        supervisor: subprocess.Popen | None = None
        supervisor_started_at = 0.0

        def reconcile_guarded(name: str, operation: Callable[[], Any]) -> Any:
            """Keep one malformed saga from taking down status/control service."""
            try:
                return operation()
            except Exception as exc:
                code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
                fingerprint = sha256({"component": name, "code": code})
                store.get_or_create_incident(
                    "INC-RECON-" + fingerprint[:16], fingerprint, severity="risk",
                    evidence={"code": code, "component": name})
                return None

        while True:
            bridge.import_commands(store)
            store.recover_expired_missions()
            from abcr.control.goal_confirmation import (reconcile_approval_results,
                                                         reconcile_itempool_results)
            from abcr.control.queue_runtime import WorkBrokerClient
            queue_broker = WorkBrokerClient(Path(config["broker_socket"]))
            from abcr.control.probe_control import reconcile_probe_results
            reconcile_guarded("probe_results", lambda: reconcile_probe_results(
                store=store, broker=queue_broker,
                research_memory_path=Path(settings["research_memory_path"])))
            reconcile_guarded("itempool_compile", lambda: reconcile_itempool_results(
                store=store, broker=queue_broker,
                research_memory_path=Path(settings["research_memory_path"]),
                research_repo=Path(settings["research_repo"]),
                persona_root=Path(settings["persona_root"]),
                trusted_dev_bundle_root=Path(settings["trusted_dev_bundle_root"]),
                bundle_sealer_public_key=Path(settings["bundle_sealer_public_key"]),
                deployment_id=settings["deployment_id"], protocol_ref=settings["protocol_ref"],
                artifact_receipt_public_key=Path(settings["artifact_receipt_public_key"]),
                execution_profile=settings["execution_profile"]))
            reconcile_guarded(
                "approval_export", lambda: reconcile_approval_results(
                    store=store, broker=queue_broker, bridge=bridge))
            from abcr.control.approval_dispatch import reconcile_approval_dispatch
            from abcr.ops.dispatch import ClaimedDispatchRoots, prepare_claimed_dispatch

            def prepare_dispatch(request: dict[str, Any]) -> bool:
                result = prepare_claimed_dispatch(
                    envelope=request["envelope"],
                    approval_binding={key: request[key] for key in (
                        "token_id", "claim_id", "batch_id", "release_id")}
                    | {"envelope_sha256": request["envelope_hash"]},
                    dispatch_event_id=request["dispatch_event_id"],
                    roots=ClaimedDispatchRoots(
                        queue_root=Path(settings["dispatch_queue_root"]),
                        state_root=Path(settings["dispatch_state_root"]),
                        ledger_root=Path(settings["ledger_root"]),
                        dev_bundle_root=Path(settings["trusted_dev_bundle_root"]),
                        bundle_sealer_public_key=Path(settings["bundle_sealer_public_key"]),
                    ),
                )
                return (result.get("batch_id") == request["batch_id"]
                        and result.get("dispatch_event_id") == request["dispatch_event_id"]
                        and result.get("prepared") == len(request["run_configs"]))

            reconcile_guarded("approval_dispatch", lambda: reconcile_approval_dispatch(
                store=store, bridge=bridge, ledger_root=Path(settings["ledger_root"]),
                release_id=settings["release_id"],
                research_repo=Path(settings["research_repo"]),
                research_memory_path=Path(settings["research_memory_path"]),
                research_owner_uid=settings["operator_uid"],
                approval_public_key=Path(settings["approval_public_key"]),
                # This adapter only writes the pre-qualified pending queue/runstate;
                # it never invokes a model, scorer, cloud API or legacy HMAC path.
                dispatch_adapter=prepare_dispatch,
                execution_qualified=settings["dispatch_supervisor_qualified"],
            ))
            from abcr.control.round_saga import (enqueue_completed_batch_audits,
                                                  reconcile_evidence_audits)
            reconcile_guarded(
                "evidence_audit_enqueue", lambda: enqueue_completed_batch_audits(
                    store=store, broker=queue_broker,
                    ledger_root=Path(settings["ledger_root"])))
            reconcile_guarded(
                "evidence_audit_result", lambda: reconcile_evidence_audits(
                    store=store, broker=queue_broker,
                    sealed_audit_root=Path(settings["sealed_audit_root"]),
                    receipt_root=Path(settings["broker_receipt_root"]),
                    receipt_group_gid=settings["broker_receipt_group_gid"],
                    auditor_public_key=Path(settings["auditor_public_key"]),
                    research_memory_path=Path(settings["research_memory_path"]),
                    research_owner_uid=settings["operator_uid"],
                    ledger_root=Path(settings["ledger_root"])))
            if settings["dispatch_supervisor_qualified"]:
                exited = supervisor is None or supervisor.poll() is not None
                if exited and time.monotonic() - supervisor_started_at >= 5.0:
                    supervisor = reconcile_guarded(
                        "dispatch_supervisor_start",
                        lambda: spawn_dispatch_supervisor(settings))
                    supervisor_started_at = time.monotonic()
            from abcr.control.health_collector import (
                collect_production_observations, production_service_specs)
            from abcr.control.health_runtime import run_health_cycle

            def restart_control_generation(request: Any) -> None:
                # The root broker owns the fixed label/UID set and active-release
                # check.  Operator never calls launchctl or chooses a PID itself.
                if request.service_label != "com.abcr.panel":
                    raise ContractError("health_recovery_not_allowed",
                                        "仅 panel 纳入已审查的 generation 恢复")
                queue_broker.request("restart_generation", {
                    "generation": "control-plane",
                    "expected_release_id": settings["release_id"]})

            release_rows = [row for row in store.rows("releases")
                            if row["release_id"] == settings["release_id"]]
            rollback_release = (release_rows[-1].get("previous_release")
                                if release_rows else None) or settings["release_id"]
            reconcile_guarded(
                "service_health", lambda: run_health_cycle(
                    store,
                    collect_production_observations(
                        store, queue_broker,
                        active_release_id=settings["release_id"],
                        launcher_release_id=os.environ.get("ABCR_RELEASE_ID"),
                        supervisor_qualified=settings["dispatch_supervisor_qualified"],
                        supervisor_alive=(supervisor is not None
                                          and supervisor.poll() is None)),
                    production_service_specs(),
                    rollback_release=rollback_release,
                    recovery_handlers={"resume_same_release":
                                       restart_control_generation}))
            from abcr.control.mission_pipeline import (reconcile_mission_pipeline,
                                                        reconcile_queued_missions)
            from abcr.control.mission_coordinator import TrustedMissionCoordinator
            reconcile_guarded(
                "mission_enqueue", lambda: reconcile_queued_missions(
                    store, queue_broker,
                    TrustedMissionCoordinator(
                        release_root=Path(settings["trusted_release_root"]),
                        prepared_root=Path(settings["mission_input_root"]),
                        coordinator_uid=settings["operator_uid"],
                        reader_gid=settings["mission_input_group_gid"])))
            def settle_mission_event(event: dict[str, Any]) -> None:
                if event["disposition"] == "terminal" and event["stage"] == "activate":
                    store.settle_mission_pipeline(event["work_id"], "released")
                elif event["disposition"] in {"failed", "halted"}:
                    outcome = ("needs_human" if event["stage"] == "verify"
                               and event["disposition"] == "halted" else "failed")
                    store.settle_mission_pipeline(event["work_id"], outcome)
            reconcile_guarded(
                "mission_pipeline", lambda: reconcile_mission_pipeline(
                    queue_broker, before_ack=settle_mission_event))
            for row in store.rows("actions"):
                if row["state"] not in {"queued", "executing"}:
                    continue
                try:
                    payload = json.loads(row.get("payload_json") or "null")
                    if not isinstance(payload, dict) or sha256(payload) != row["payload_hash"]:
                        payload = {"_invalid_payload": True}
                except (TypeError, json.JSONDecodeError):
                    payload = {"_invalid_payload": True}
                if row["intent"] == "confirm_proposal":
                    if not store.claim_action(row["effect_id"], "operator"):
                        continue
                    try:
                        from abcr.control.goal_confirmation import confirm_goal
                        from abcr.control.queue_runtime import WorkBrokerClient
                        exact = strict_object(payload, required={"proposal_id"})
                        proposal = store.get_proposal(exact["proposal_id"])
                        if proposal is None:
                            raise ContractError("proposal_missing", "待确认提案不存在")
                        report = validate_goal(proposal["raw_text"].encode("utf-8"))
                        if not report.ok or report.goal is None:
                            store.set_proposal_state(exact["proposal_id"], "imported", "invalid")
                            raise ContractError("goal_invalid", "目标书未通过确定性校验")
                        if proposal["state"] == "imported":
                            store.set_proposal_state(exact["proposal_id"], "imported", "validated",
                                                     report.goal.as_dict())
                            proposal = store.get_proposal(exact["proposal_id"])
                        result = confirm_goal(
                            store=store,
                            broker=WorkBrokerClient(Path(config["broker_socket"])),
                            effect_id=row["effect_id"], proposal=proposal, goal=report.goal,
                            deployment_id=settings["deployment_id"],
                            protocol_ref=settings["protocol_ref"],
                            research_repo=Path(settings["research_repo"]),
                            research_memory_path=Path(settings["research_memory_path"]),
                            research_group_gid=settings["research_group_gid"],
                            artifact_receipt_private_key=Path(
                                settings["artifact_receipt_private_key"]),
                            artifact_receipt_public_key=Path(
                                settings["artifact_receipt_public_key"]),
                        )
                        store.finish_action(row["effect_id"], worker_id="operator",
                                            state="succeeded",
                                            result={"ok": True, "result": result})
                    except Exception as exc:
                        fingerprint = sha256({"effect_id": row["effect_id"],
                                              "error": type(exc).__name__})
                        store.get_or_create_incident(
                            "INC-CONFIRM-" + fingerprint[:16], fingerprint, severity="risk",
                            evidence={"code": "confirm_proposal_invalid",
                                      "error_class": type(exc).__name__})
                        terminal = isinstance(exc, ContractError) and exc.code in {
                            "proposal_missing", "goal_invalid", "proposal_bytes_drift",
                            "goal_path_unsafe", "goal_artifact_conflict",
                            "goal_anchor_conflict", "freeze_receipt_conflict",
                            "proposal_state_invalid",
                        }
                        if terminal:
                            store.finish_action(
                                row["effect_id"], worker_id="operator", state="failed",
                                result={"ok": False,
                                        "code": exc.code if isinstance(exc, ContractError)
                                        else type(exc).__name__})
                    continue
                worker.execute(row["effect_id"], row["intent"], payload)
            bridge.export_results_and_status(store)
            if args.once:
                return 0
            time.sleep(float(interval))
    except Exception as exc:
        code = exc.code if isinstance(exc, (ContractError, ServiceRuntimeBlocked)) else type(exc).__name__
        print(json.dumps({"ok": False, "service": "operator-reconciler",
                          "error_code": code}, sort_keys=True), file=sys.stderr)
        return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
