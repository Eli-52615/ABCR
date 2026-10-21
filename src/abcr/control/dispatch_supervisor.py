"""Non-blocking Operator-owned supervisor for claimed W1 experiment runs.

The reconciler starts this module only from the sealed interpreter when the
root-owned deployment config says it is qualified.  This process owns the legacy
run queue as a single writer, but never accepts the legacy HMAC approval path and
never provisions cloud/network resources.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from abcr.common.ledger_ref import RunLedger
from abcr.control.contracts import ContractError, canonical_json, sha256, strict_object, utc_now
from abcr.control.queue_runtime import EX_CONFIG, ServiceRuntimeBlocked, load_queue_config
from abcr.control.signals import RunControl
from abcr.control.store import ControlStore, StoreError
from abcr.ops import dispatch as dispatch_ops
from abcr.ops import queue, runstate
from abcr.rig.models import TOKENIZER_FINGERPRINT_SCHEMA


@dataclass(frozen=True)
class SupervisorSettings:
    store_path: Path
    queue_root: Path
    state_root: Path
    ledger_root: Path
    runs_root: Path
    run_control_root: Path
    dev_bundle_root: Path
    bundle_sealer_public_key: Path
    release_id: str
    execution_profile: dict[str, Any]
    interval_seconds: float

    @property
    def dispatch_roots(self) -> dispatch_ops.ClaimedDispatchRoots:
        return dispatch_ops.ClaimedDispatchRoots(
            self.queue_root, self.state_root, self.ledger_root,
            self.dev_bundle_root, self.bundle_sealer_public_key)


def _safe_root(path: Path, *, writable: bool) -> Path:
    value = Path(path)
    if not value.is_absolute() or value.is_symlink() or not value.is_dir():
        raise ContractError("dispatch_supervisor_root_unsafe", "supervisor root 不安全")
    info = value.lstat()
    if (writable and (info.st_uid != os.geteuid()
                      or stat.S_IMODE(info.st_mode) & 0o022)):
        raise ContractError("dispatch_supervisor_root_unsafe", "supervisor root owner/mode 不安全")
    if not writable and stat.S_IMODE(info.st_mode) & 0o002:
        raise ContractError("dispatch_supervisor_root_unsafe", "只读 supervisor root 可被其他用户写")
    return value


def _derived_dir(parent: Path, name: str) -> Path:
    root = _safe_root(parent, writable=True)
    child = root / name
    if child.exists() or child.is_symlink():
        return _safe_root(child, writable=True)
    child.mkdir(mode=0o700)
    return _safe_root(child, writable=True)


def settings_from_config(config: dict[str, Any]) -> SupervisorSettings:
    raw = strict_object(config["settings"], required={
        "store_path", "interval_seconds", "human_uid", "operator_uid",
        "human_gid", "operator_gid", "deployment_id", "protocol_ref",
        "research_repo", "research_memory_path", "research_group_gid",
        "artifact_receipt_private_key", "artifact_receipt_public_key",
        "approval_public_key", "persona_root", "trusted_dev_bundle_root",
        "bundle_sealer_public_key", "ledger_root", "dispatch_queue_root",
        "dispatch_state_root", "release_id", "dispatch_supervisor_qualified",
        "execution_profile",
    })
    if raw["dispatch_supervisor_qualified"] is not True:
        raise ServiceRuntimeBlocked("dispatch_supervisor_not_qualified")
    if not isinstance(raw["execution_profile"], dict):
        raise ServiceRuntimeBlocked("dispatch_execution_profile_unqualified")
    if raw["operator_uid"] != os.geteuid():
        raise ServiceRuntimeBlocked("dispatch_supervisor_uid_mismatch")
    interval = raw["interval_seconds"]
    if type(interval) not in {int, float} or not 0.1 <= interval <= 300:
        raise ServiceRuntimeBlocked("dispatch_supervisor_interval_invalid")
    paths = {name: Path(raw[name]) for name in (
        "store_path", "dispatch_queue_root", "dispatch_state_root", "ledger_root",
        "trusted_dev_bundle_root", "bundle_sealer_public_key")}
    if any(not value.is_absolute() for value in paths.values()):
        raise ServiceRuntimeBlocked("dispatch_supervisor_path_invalid")
    if not isinstance(raw["release_id"], str) or not raw["release_id"]:
        raise ServiceRuntimeBlocked("dispatch_supervisor_release_invalid")
    if (not isinstance(raw["execution_profile"].get("release_pin"), dict)
            or raw["execution_profile"]["release_pin"].get("release_id") != raw["release_id"]):
        raise ServiceRuntimeBlocked("dispatch_execution_profile_release_mismatch")
    key = paths["bundle_sealer_public_key"]
    key_info = key.lstat()
    if (key.is_symlink() or not stat.S_ISREG(key_info.st_mode) or key_info.st_nlink != 1
            or key_info.st_uid != 0 or stat.S_IMODE(key_info.st_mode) != 0o444):
        raise ServiceRuntimeBlocked("dispatch_supervisor_key_unsafe")
    database = paths["store_path"]
    db_info = database.lstat()
    if (database.is_symlink() or not stat.S_ISREG(db_info.st_mode) or db_info.st_nlink != 1
            or db_info.st_uid != os.geteuid() or stat.S_IMODE(db_info.st_mode) != 0o600):
        raise ServiceRuntimeBlocked("dispatch_supervisor_store_unsafe")
    state_root = _safe_root(paths["dispatch_state_root"], writable=True)
    ledger_root = _safe_root(paths["ledger_root"], writable=True)
    evidence_root = _safe_root(ledger_root.parent, writable=True)
    if ledger_root.name != "ledger" or state_root.parent != evidence_root:
        raise ServiceRuntimeBlocked("dispatch_supervisor_evidence_layout_invalid")
    queue_root = _safe_root(paths["dispatch_queue_root"], writable=True)
    for stage in queue.STATES:
        _safe_root(queue_root / stage, writable=True)
    return SupervisorSettings(
        store_path=paths["store_path"],
        queue_root=queue_root,
        state_root=state_root,
        ledger_root=ledger_root,
        runs_root=_derived_dir(evidence_root, "runs"),
        run_control_root=_derived_dir(state_root, "run-controls"),
        dev_bundle_root=_safe_root(paths["trusted_dev_bundle_root"], writable=False),
        bundle_sealer_public_key=paths["bundle_sealer_public_key"],
        release_id=str(raw["release_id"]), execution_profile=dict(raw["execution_profile"]),
        interval_seconds=float(interval),
    )


def _configure_runtime(settings: SupervisorSettings) -> None:
    """Set only fixed root-owned values inside this dedicated child process."""
    os.environ["ABCR_QUEUE_ROOT"] = str(settings.queue_root)
    os.environ["ABCR_STATE_DIR"] = str(settings.state_root)
    os.environ["ABCR_LEDGER_DIR"] = str(settings.ledger_root)
    os.environ["ABCR_RUNS_ROOT"] = str(settings.runs_root)
    os.environ["ABCR_RUN_CONTROL_ROOT"] = str(settings.run_control_root)
    os.environ["ABCR_ORPHAN_GRACE_S"] = "0"
    # The supervisor accepts only local model directories.  These flags are a
    # second independent guard against implicit hub downloads.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ.pop("ABCR_QUEUE_CONFIG_ROOT", None)
    if os.environ.get("ABCR_RELEASE_ID") != settings.release_id:
        raise ServiceRuntimeBlocked("dispatch_supervisor_active_release_mismatch")


def _validate_execution_profile_binding(config: dict[str, Any],
                                        profile: dict[str, Any]) -> None:
    """Bind approved config bytes back to the root-owned frozen profile."""
    decoding = config.get("decoding") if isinstance(config, dict) else None
    evidence = config.get("evidence_inputs") if isinstance(config, dict) else None
    if (config.get("model") != profile.get("model")
            or config.get("release_pin") != profile.get("release_pin")
            or (config.get("benchmark") or {}).get("family")
            != profile.get("benchmark_family")
            or not isinstance(decoding, dict)
            or {key: value for key, value in decoding.items() if key != "seeds"}
            != profile.get("decoding")
            or not isinstance(evidence, dict)
            or profile.get("tokenizer_fingerprint_schema")
            != TOKENIZER_FINGERPRINT_SCHEMA
            or config.get("tokenizer_fingerprint_schema")
            != profile.get("tokenizer_fingerprint_schema")
            or evidence.get("tokenizer_fingerprint_schema")
            != profile.get("tokenizer_fingerprint_schema")
            or config.get("tokenizer_sha256") != profile.get("tokenizer_sha256")
            or evidence.get("tokenizer_sha256") != profile.get("tokenizer_sha256")):
        raise ContractError("dispatch_execution_profile_drift",
                            "RunConfig 不再匹配 root-owned execution profile")


def _unique_object(raw: bytes) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ContractError("dispatch_queue_duplicate_key", "queue JSON 重复 key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ContractError("dispatch_queue_invalid", "queue payload 不是 object")
    return value


def _read_queue_file(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022
                or info.st_size > 8 * 1024 * 1024):
            raise ContractError("dispatch_queue_metadata_unsafe", "queue object metadata 不安全")
        raw = b""
        while len(raw) <= info.st_size:
            chunk = os.read(fd, info.st_size + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    if len(raw) != info.st_size:
        raise ContractError("dispatch_queue_changed", "queue object 读取时变化")
    return _unique_object(raw)


def _requests(store: ControlStore) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in store.rows("dispatch_requests"):
        if row["state"] not in {"enqueued", "running"}:
            continue
        request = json.loads(row["request_json"])
        if row["request_hash"] != sha256(request):
            raise StoreError("dispatch request hash drift")
        result[row["batch_id"]] = (row, request)
    return result


def _local_engine_guard(config: dict[str, Any]) -> None:
    model = config.get("model")
    if not isinstance(model, dict):
        raise ContractError("dispatch_model_binding_missing", "RunConfig 缺 model binding")
    engine = model.get("engine")
    if engine == "fake":
        return
    if engine != "transformers":
        raise ContractError("dispatch_network_engine_forbidden", "supervisor 只允许本地 transformers")
    model_id = model.get("model_id")
    if not isinstance(model_id, str):
        raise ContractError("dispatch_local_model_required", "model_id 必须是本地绝对目录")
    model_path = Path(model_id)
    if (not model_path.is_absolute() or model_path.is_symlink()
            or not model_path.is_dir()):
        raise ContractError("dispatch_local_model_required", "禁止远端模型下载/网络 engine")
    from abcr.rig.models import _local_model_fingerprint
    observed = _local_model_fingerprint(model_path)
    if observed is None or model.get("revision") != observed:
        raise ContractError("dispatch_local_model_drift", "本地模型 revision/fingerprint 漂移")


def validate_queue_payload(payload: Any, *, request: dict[str, Any],
                           settings: SupervisorSettings) -> tuple[list[str],
                                                                    dict[str, str],
                                                                    dict[str, dict]]:
    obj = strict_object(payload, required={"config", "batch_id", "run_id", "seed",
                                           "config_hash", "approval_binding",
                                           "dispatch_event_id"})
    if (obj["batch_id"] != request["batch_id"]
            or obj["dispatch_event_id"] != request["dispatch_event_id"]):
        raise ContractError("dispatch_queue_request_mismatch", "queue 未绑定 dispatch request")
    expected_binding = {"token_id": request["token_id"], "claim_id": request["claim_id"],
                        "batch_id": request["batch_id"],
                        "envelope_sha256": request["envelope_hash"],
                        "release_id": request["release_id"]}
    if obj["approval_binding"] != expected_binding or request["release_id"] != settings.release_id:
        raise ContractError("dispatch_queue_claim_mismatch", "queue claim/release 漂移")
    cost_cap = request["envelope"].get("max_cost_usd")
    if (isinstance(cost_cap, bool) or not isinstance(cost_cap, (int, float))
            or not math.isfinite(float(cost_cap)) or cost_cap < 0):
        raise ContractError("dispatch_budget_invalid", "max_cost_usd 不合法")
    deadline_value = request["envelope"].get("deadline_utc")
    if deadline_value is not None:
        try:
            deadline = datetime.fromisoformat(deadline_value)
        except (TypeError, ValueError) as exc:
            raise ContractError("dispatch_deadline_invalid", "运行 deadline 不合法") from exc
        if deadline.tzinfo is None or datetime.now(timezone.utc) >= deadline:
            raise ContractError("dispatch_deadline_expired", "supervisor 启动时 envelope 已过期")
    config = obj["config"]
    if (not isinstance(config, dict) or dispatch_ops.config_hash(config) != obj["config_hash"]
            or config not in request["run_configs"]
            or dispatch_ops.make_run_id(obj["batch_id"], obj["config_hash"]) != obj["run_id"]
            or dispatch_ops._seeds(config) != [obj["seed"]]):
        raise ContractError("dispatch_queue_config_mismatch", "queue config/run/seed 漂移")
    profile = settings.execution_profile
    _validate_execution_profile_binding(config, profile)
    _local_engine_guard(config)
    items = dispatch_ops.load_dispatch_items(
        config, trusted_root=settings.dev_bundle_root,
        sealer_public_key=settings.bundle_sealer_public_key)
    dispatch_ops._validate_compile_binding(config, request["envelope"], items)
    violation = dispatch_ops._scope_violation(config, request["envelope"]["scope"])
    if violation:
        raise ContractError("dispatch_queue_scope_mismatch", violation)
    selected = {item["item_id"]: item for item in items}
    prompts = {item_id: item["prompt"] for item_id, item in selected.items()}
    return list(selected), prompts, selected


def _status(settings: SupervisorSettings, **values: Any) -> None:
    path = settings.state_root / "supervisor-status.json"
    document = {"schema_version": 1, "qualified": True, "pid": os.getpid(),
                "release_id": settings.release_id, "updated_at": utc_now(), **values}
    raw = canonical_json(document) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, raw); os.fchmod(fd, 0o600); os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _quarantine(settings: SupervisorSettings, path: Path, code: str) -> None:
    quarantine = _derived_dir(settings.state_root, "quarantine")
    target = quarantine / (f"{path.stem}-{sha256({'name': path.name, 'code': code})[:16]}-"
                           f"{uuid.uuid4().hex}.json")
    if path.parent.name in {"pending", "running", "failed"} and path.exists():
        os.replace(path, target)
    _status(settings, state="blocked", error_code=code,
            object_name_hash=sha256(path.name.encode()))


def _all_done(request: dict[str, Any], settings: SupervisorSettings) -> bool:
    return all((settings.queue_root / "done" /
                f"{dispatch_ops.make_run_id(request['batch_id'], dispatch_ops.config_hash(cfg))}.json").is_file()
               for cfg in request["run_configs"])


def _settle_batch(store: ControlStore, row: dict[str, Any], request: dict[str, Any],
                  settings: SupervisorSettings) -> None:
    if not _all_done(request, settings):
        return
    ledger = RunLedger(settings.ledger_root, "batches")
    if not ledger.has_event("batch_settled", request["batch_id"]):
        ledger.append("batch_settled", subject_id=request["batch_id"],
                      dispatch_event_id=request["dispatch_event_id"],
                      claim_id=request["claim_id"], release_id=request["release_id"])
    store.set_dispatch_request_state(row["effect_id"], state="completed")


def process_once(store: ControlStore, settings: SupervisorSettings) -> int:
    requests = _requests(store)
    processed = 0
    # Re-running the entire preparation adapter is the authoritative batch-level
    # revalidation. It is byte-idempotent and performs no model execution.
    invalid_batches: set[str] = set()
    for row, request in requests.values():
        try:
            dispatch_ops.prepare_claimed_dispatch(
                envelope=request["envelope"],
                approval_binding={"token_id": request["token_id"],
                                  "claim_id": request["claim_id"],
                                  "batch_id": request["batch_id"],
                                  "envelope_sha256": request["envelope_hash"],
                                  "release_id": request["release_id"]},
                dispatch_event_id=request["dispatch_event_id"], roots=settings.dispatch_roots)
        except Exception as exc:
            code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
            store.set_dispatch_request_state(row["effect_id"], state="blocked",
                                             reason_code=code)
            invalid_batches.add(request["batch_id"])
            _status(settings, state="blocked", error_code=code,
                    batch_id=request["batch_id"])
    for batch_id in invalid_batches:
        requests.pop(batch_id, None)
    for row, request in requests.values():
        _settle_batch(store, row, request, settings)

    candidates: list[Path] = []
    for stage in ("running", "pending", "failed"):
        candidates.extend(sorted((settings.queue_root / stage).glob("*.json")))
    controls = RunControl(settings.run_control_root)
    blocked_batches: set[str] = set()
    for path in candidates:
        row: dict[str, Any] | None = None
        batch_id: str | None = None
        try:
            payload = _read_queue_file(path)
            batch_id = payload.get("batch_id")
            if isinstance(batch_id, str) and batch_id in blocked_batches:
                continue
            pair = requests.get(batch_id)
            if pair is None:
                raise ContractError("dispatch_request_not_executable", "queue 无 enqueued request")
            row, request = pair
            item_ids, prompts, selected = validate_queue_payload(
                payload, request=request, settings=settings)
            desired = controls.read(payload["run_id"])
            if desired is not None:
                if desired.release_id != settings.release_id:
                    raise ContractError("run_control_release_mismatch", "run control release 漂移")
                if desired.desired == "paused":
                    continue
                if desired.desired == "aborted":
                    runstate.mark_aborted(payload["run_id"], desired.reason)
                    store.set_dispatch_request_state(
                        row["effect_id"], state="blocked", reason_code="RUN_ABORTED")
                    blocked_batches.add(payload["batch_id"])
                    _quarantine(settings, path, "RUN_ABORTED")
                    continue
            store.set_dispatch_request_state(row["effect_id"], state="running")
            result = dispatch_ops._process_run(
                payload["run_id"], payload["config"], item_ids, payload["seed"],
                payload["config_hash"], payload["batch_id"],
                RunLedger(settings.ledger_root, "runs_index"), settings.state_root,
                prompts, selected, dispatch_ops._git_head())
            _status(settings, state="running", run_id=payload["run_id"], result=result)
            if result == "skip-quota":
                store.set_dispatch_request_state(
                    row["effect_id"], state="blocked", reason_code="RUN_QUOTA_BLOCKED")
                blocked_batches.add(payload["batch_id"])
            elif result == "skip-noresume":
                can_resume, reason = runstate.can_resume(payload["run_id"])
                if not can_resume and "冷却" not in reason:
                    store.set_dispatch_request_state(
                        row["effect_id"], state="blocked", reason_code="RUN_RETRY_EXHAUSTED")
                    blocked_batches.add(payload["batch_id"])
            _settle_batch(store, row, request, settings)
            processed += 1
        except Exception as exc:
            code = exc.code if isinstance(exc, ContractError) else type(exc).__name__
            if row is not None:
                store.set_dispatch_request_state(
                    row["effect_id"], state="blocked",
                    reason_code=(code if isinstance(code, str) and code else "RUN_INVALID"))
            if isinstance(batch_id, str):
                blocked_batches.add(batch_id)
            _quarantine(settings, path, code)
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dispatch-supervisor")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_queue_config("operator-reconciler")
        settings = settings_from_config(config)
        _configure_runtime(settings)
        store = ControlStore(settings.store_path); store.quick_check()
        lock_path = settings.state_root / "supervisor.lock"
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                          0o600)
        try:
            lock_info = os.fstat(lock_fd)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1
                    or lock_info.st_uid != os.geteuid()):
                raise ContractError("dispatch_supervisor_lock_unsafe", "supervisor lock 不安全")
            os.fchmod(lock_fd, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            runstate.scan_orphans()
            while True:
                count = process_once(store, settings)
                _status(settings, state="idle" if count == 0 else "running",
                        processed=count)
                if args.once:
                    return 0
                time.sleep(settings.interval_seconds)
        finally:
            os.close(lock_fd)
    except Exception as exc:
        code = exc.code if isinstance(exc, (ContractError, ServiceRuntimeBlocked)) else type(exc).__name__
        print(json.dumps({"ok": False, "service": "dispatch-supervisor",
                          "error_code": code}, sort_keys=True), file=sys.stderr)
        return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
