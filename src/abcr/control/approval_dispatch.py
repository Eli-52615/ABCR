"""Writer-fixed Human approval claim and Operator dispatch saga.

The Human domain signs decisions and owns the first-claim journal.  The Operator
domain verifies those immutable facts, appends batch events and prepares a finite
dispatch request, but never sees a private key.  Preparing a request performs no
model call and spends no money; a separately qualified Operator-owned supervisor
must explicitly accept it through ``dispatch_adapter``.
"""
from __future__ import annotations

import fcntl
import base64
import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from abcr.common.ledger_ref import RunLedger
from abcr.control.attestation import (DOMAIN_APPROVAL_DISPATCH_CLAIM,
                                      sign_attestation, verify_attestation)
from abcr.control.contracts import ContractError, canonical_json, require_id, require_sha, sha256
from abcr.control.ed25519 import git_path, verify_token_v2
from abcr.control.human_approval import approval_bundle_from_wire
from abcr.control.store import ControlStore, StoreError
from abcr.explore.memory import ResearchMemory


DispatchAdapter = Callable[[dict[str, Any]], bool]


def _aware(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("approval_time_invalid", f"{field} 不是 ISO8601 时间") from exc
    if parsed.tzinfo is None:
        raise ContractError("approval_time_invalid", f"{field} 缺时区")
    return parsed


def claim_request_from_decision(decision: dict[str, Any], *,
                                approval_event_id: str, release_id: str) -> dict[str, Any]:
    """Build the sole claim target; every identifier is content-derived and stable."""
    if decision.get("decision") != "approve" or not isinstance(decision.get("token"), dict):
        raise ContractError("approval_claim_requires_approve", "只有 approve token 可请求 claim")
    token = decision["token"]
    require_id(approval_event_id, "approval_event_id")
    require_id(release_id, "release_id")
    basis = {"request_id": decision["request_id"],
             "request_version": decision["request_version"],
             "batch_id": token["batch_id"], "envelope_hash": token["envelope_sha256"],
             "release_id": release_id, "approval_event_id": approval_event_id,
             "decision_id": decision["decision_id"], "token_id": token["token_id"]}
    effect_id = sha256({"kind": "approval-dispatch", **basis})
    claim_id = "CLM-" + sha256({"kind": "human-first-claim", **basis})[:32]
    core = {"claim_id": claim_id, "token_id": token["token_id"],
            "request_id": decision["request_id"],
            "request_version": decision["request_version"],
            "batch_id": token["batch_id"],
            "envelope_hash": token["envelope_sha256"], "release_id": release_id,
            "approval_event_id": approval_event_id, "effect_id": effect_id}
    return {"schema_version": 1, "kind": "approval_claim_request", **core,
            "decision": decision,
            "request_hash": sha256({**core, "decision_id": decision["decision_id"]})}


def claim_request_core(document: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(document, dict):
        raise ContractError("approval_claim_request_invalid", "claim request 必须是 object")
    required = {"schema_version", "kind", "claim_id", "token_id", "request_id",
                "request_version", "batch_id", "envelope_hash", "release_id",
                "approval_event_id", "effect_id", "decision", "request_hash"}
    if set(document) != required or document["schema_version"] != 1 \
            or document["kind"] != "approval_claim_request":
        raise ContractError("approval_claim_request_invalid", "claim request 字段不精确")
    core = {key: document[key] for key in (
        "claim_id", "token_id", "request_id", "request_version", "batch_id",
        "envelope_hash", "release_id", "approval_event_id", "effect_id")}
    decision = document["decision"]
    if (not isinstance(decision, dict)
            or document["request_hash"] != sha256({**core,
                                                    "decision_id": decision.get("decision_id")})):
        raise ContractError("approval_claim_request_invalid", "claim request hash 不匹配")
    return core, decision


def sign_claim_result(core: dict[str, Any], *, private_key: Path,
                      public_key: Path) -> dict[str, Any]:
    sealed = sign_attestation(private_key=private_key, public_key=public_key,
                              domain=DOMAIN_APPROVAL_DISPATCH_CLAIM, core=core)
    return {"core": core, "sealed": sealed}


def verify_claim_result(document: Any, *, expected: dict[str, Any], token: dict[str, Any],
                        public_key: Path) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {"core", "sealed"}:
        raise ContractError("approval_claim_receipt_invalid", "claim result 字段不精确")
    core = document["core"]
    if not isinstance(core, dict):
        raise ContractError("approval_claim_receipt_invalid", "claim result core 非 object")
    required = {"schema_version", "kind", "claim_id", "token_id", "request_id",
                "request_version", "batch_id", "envelope_hash", "release_id",
                "approval_event_id", "effect_id", "state", "first_claim_at",
                "reason_code"}
    if (set(core) != required or core["schema_version"] != 1
            or core["kind"] != "approval_claim_result"
            or any(core.get(key) != value for key, value in expected.items())):
        raise ContractError("approval_claim_receipt_binding", "claim result 未绑定请求")
    ok, reason = verify_attestation(document["sealed"], public_key=public_key,
                                    domain=DOMAIN_APPROVAL_DISPATCH_CLAIM,
                                    expected_core=core)
    if not ok:
        raise ContractError("approval_claim_receipt_signature", "claim result 验签失败",
                            {"reason": reason})
    issued = _aware(token.get("issued_at"), "token.issued_at")
    expires = _aware(token.get("expires_at"), "token.expires_at")
    # Recheck the token signature at a time when its signature is valid.  Actual
    # first-claim expiry is checked against the Human-signed timestamp below.
    verify_at = expires - timedelta(microseconds=1)
    ok, reason = verify_token_v2(token, public_key=public_key,
                                 expected_context={key: token[key] for key in (
                                     "aud", "deployment_id", "protocol_ref", "request_id",
                                     "request_version", "source_event_id", "tenant_key_hash",
                                     "chat_id_hash", "app_id_hash", "decision_nonce_hash",
                                     "goal_anchor_entry_hash", "goal_anchor_receipt_id",
                                     "batch_id", "envelope_sha256", "approver_id_hash")},
                                 now=verify_at)
    if not ok:
        raise ContractError("approval_token_invalid", "claim 携带 token 验签失败",
                            {"reason": reason})
    sealed_at = _aware(document["sealed"].get("issued_at"), "claim.sealed.issued_at")
    if core["state"] == "claimed":
        first = _aware(core["first_claim_at"], "first_claim_at")
        if core["reason_code"] is not None or not issued <= first < expires or sealed_at < first:
            raise ContractError("approval_claim_time_invalid", "首次 claim 不在 token 有效期")
    elif core["state"] == "denied":
        if (core["first_claim_at"] is not None
                or core["reason_code"] != "APPROVAL_EXPIRED" or sealed_at < expires):
            raise ContractError("approval_claim_denial_invalid", "过期 denial 事实不合法")
    else:
        raise ContractError("approval_claim_state_invalid", "claim state 不合法")
    return core


def settlement_request(*, claim_result: dict[str, Any], dispatch_event_id: str) -> dict[str, Any]:
    require_id(dispatch_event_id, "dispatch_event_id")
    core = claim_result["core"]
    body = {"claim_id": core["claim_id"], "effect_id": core["effect_id"],
            "claim_receipt_hash": sha256(claim_result),
            "dispatch_event_id": dispatch_event_id}
    return {"schema_version": 1, "kind": "approval_claim_settlement", **body,
            "settlement_hash": sha256(body)}


def sign_settlement_ack(*, claim: dict[str, Any], private_key: Path,
                        public_key: Path) -> dict[str, Any]:
    core = {"schema_version": 1, "kind": "approval_claim_settled_ack",
            "claim_id": claim["claim_id"], "effect_id": claim["effect_id"],
            "claim_receipt_hash": claim["receipt_hash"],
            "dispatch_event_id": claim["settled_event_id"],
            "settled_at": claim["settled_at"]}
    # ``settled_at`` is fixed by the Human DB transition.  Reusing it as the
    # attestation time makes crash/redelivery reproduce byte-identical ack bytes.
    sealed = sign_attestation(
        private_key=private_key, public_key=public_key,
        domain=DOMAIN_APPROVAL_DISPATCH_CLAIM, core=core,
        issued_at=_aware(claim["settled_at"], "settled_at"),
    )
    return {"core": core, "sealed": sealed}


def verify_settlement_ack(document: Any, *, claim_result: dict[str, Any],
                          dispatch_event_id: str, public_key: Path) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {"core", "sealed"}:
        raise ContractError("claim_settlement_ack_invalid", "settlement ack 字段不精确")
    core = document["core"]
    claim = claim_result["core"]
    expected = {"schema_version": 1, "kind": "approval_claim_settled_ack",
                "claim_id": claim["claim_id"], "effect_id": claim["effect_id"],
                "claim_receipt_hash": sha256(claim_result),
                "dispatch_event_id": dispatch_event_id}
    if (not isinstance(core, dict) or set(core) != {*expected, "settled_at"}
            or any(core.get(key) != value for key, value in expected.items())):
        raise ContractError("claim_settlement_ack_binding", "settlement ack 未绑定 dispatch")
    _aware(core["settled_at"], "settled_at")
    ok, reason = verify_attestation(document["sealed"], public_key=public_key,
                                    domain=DOMAIN_APPROVAL_DISPATCH_CLAIM,
                                    expected_core=core)
    if not ok:
        raise ContractError("claim_settlement_ack_signature", "settlement ack 验签失败",
                            {"reason": reason})
    return core


def _event_id(kind: str, effect_id: str) -> str:
    return "EVT-" + sha256({"kind": kind, "effect_id": effect_id})[:32]


def append_batch_once(ledger_root: Path, event: str, batch_id: str, *,
                      event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Single-Operator append_once with byte-conflict detection across crashes."""
    require_id(batch_id, "batch_id"); require_id(event_id, "event_id")
    root = Path(ledger_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ContractError("batch_ledger_root_unsafe", "batches ledger root 必须预置为绝对真实目录")
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ContractError("batch_ledger_root_unsafe", "batches ledger root owner/mode 不安全")
    ledger = RunLedger(root, "batches")
    with (root / ".approval-dispatch.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows = [row for row in ledger.events() if row.get("event_id") == event_id]
        if rows:
            if len(rows) != 1 or rows[0].get("event") != event \
                    or rows[0].get("subject_id") != batch_id \
                    or any(rows[0].get(key) != value for key, value in payload.items()):
                raise ContractError("batch_event_replay_conflict", "batch event_id 内容冲突")
            return rows[0]
        conflicting = [row for row in ledger.events(event=event, subject_id=batch_id)
                       if row.get("event_id") != event_id]
        if conflicting:
            raise ContractError("batch_event_writer_conflict", "同批次事件已有另一 writer/effect")
        return ledger.append(event, subject_id=batch_id, event_id=event_id, **payload)


def validate_approval_sequence(*, decision: dict[str, Any], compile_payload: dict[str, Any],
                               research_repo: Path, research_memory_path: Path,
                               research_owner_uid: int) -> None:
    """Reconfirm anchor/token chronology without asking Human to mount research."""
    bundle = approval_bundle_from_wire(compile_payload["approval_bundle"])
    token = decision["token"]
    receipt = bundle.artifact_frozen_receipt
    issued = _aware(token["issued_at"], "token.issued_at")
    frozen = _aware(receipt["recorded_at"], "artifact_frozen.recorded_at")
    if not frozen < issued:
        raise ContractError("approval_precedes_goal_freeze", "批准时间不晚于目标冻结")
    commit = bundle.research_commit
    if (not isinstance(commit, str) or len(commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in commit)):
        raise ContractError("approval_commit_invalid", "批准 bundle 的 Git commit 不合法")
    repo = Path(research_repo)
    if not repo.is_absolute() or repo.is_symlink() or not repo.is_dir():
        raise ContractError("approval_research_repo_unsafe", "research repo 不是固定真实目录")
    shown = subprocess.run(
        [git_path(), "-c", "core.hooksPath=/dev/null", "-C", str(repo),
         "show", "-s", "--format=%cI", commit],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, shell=False, timeout=10,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"},
        check=False,
    )
    if shown.returncode != 0 or not shown.stdout.strip():
        raise ContractError("approval_commit_unavailable", "目标 Git commit 不可复验")
    committed = _aware(shown.stdout.strip(), "goal_commit_ts")
    if not committed < issued:
        raise ContractError("approval_precedes_goal_commit", "批准时间不晚于目标 commit")
    rows = ResearchMemory(research_memory_path, owner_uid=research_owner_uid).verify()
    anchors = [row for row in rows if row["event_type"] == "goal_anchor_frozen"
               and row["entry_hash"] == token["goal_anchor_entry_hash"]]
    if (len(anchors) != 1
            or anchors[0]["payload"].get("receipt_id") != token["goal_anchor_receipt_id"]
            or anchors[0]["payload"].get("deployment_id") != token["deployment_id"]
            or anchors[0]["payload"].get("protocol_ref") != token["protocol_ref"]):
        raise ContractError("approval_anchor_sequence_invalid", "批准 token 未绑定现存目标锚")


def validate_dispatch_release(envelope: Any, *, envelope_hash: str,
                              release_id: str) -> None:
    """Reject before Human first-claim if execution/release pins are incomplete."""
    if not isinstance(envelope, dict) or sha256(envelope) != envelope_hash:
        raise ContractError("dispatch_envelope_binding", "compile envelope bytes/hash 漂移")
    configs = envelope.get("run_configs")
    if not isinstance(configs, list) or not configs:
        raise ContractError("dispatch_run_configs_missing", "批准前缺确定性 run_configs")
    for config in configs:
        pin = config.get("release_pin") if isinstance(config, dict) else None
        if not isinstance(pin, dict) or pin.get("release_id") != release_id:
            raise ContractError("dispatch_release_pin_mismatch",
                                "RunConfig release pin 与 claim release 不一致")


def reconcile_approval_dispatch(*, store: ControlStore, bridge: Any,
                                ledger_root: Path, release_id: str,
                                research_repo: Path,
                                research_memory_path: Path, research_owner_uid: int,
                                approval_public_key: Path,
                                dispatch_adapter: DispatchAdapter | None = None,
                                execution_qualified: bool = False) -> int:
    """Converge imported decisions/claim receipts into one finite dispatch request.

    ``dispatch_adapter`` must only persist/enqueue the request into the fixed
    Operator-owned supervisor.  ``None`` is an explicit BLOCKED state and does not
    settle Human authority or execute any experiment.
    """
    changed = 0
    compile_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for event in store.rows("research_events"):
        if event["event_type"] != "compile_envelope_ready":
            continue
        payload = json.loads(event["payload_json"])
        if isinstance(payload.get("batch_id"), str) and isinstance(payload.get("envelope_sha256"), str):
            compile_rows[(payload["batch_id"], payload["envelope_sha256"])] = payload

    for imported in store.rows("approval_imports"):
        decision = json.loads(imported["decision_json"])
        batch_id = (decision.get("token") or {}).get("batch_id")
        if decision["decision"] == "reject":
            request = store.approval_request(decision["request_id"], decision["request_version"])
            if request is None:
                raise StoreError("rejected approval request unavailable")
            bundle = approval_bundle_from_wire(request["bundle"])
            batch_id = bundle.envelope["batch_id"]
            effect_id = sha256({"kind": "batch-rejected", "decision_id": decision["decision_id"]})
            event_id = _event_id("batch_rejected", effect_id)
            append_batch_once(ledger_root, "batch_rejected", batch_id, event_id=event_id,
                              payload={"effect_id": effect_id,
                                       "decision_id": decision["decision_id"],
                                       "reason_code": "HUMAN_REJECTED",
                                       "reason": decision["reason"]})
            store.append_research_event("batch_rejected", batch_id,
                                        {"event_id": event_id, "effect_id": effect_id,
                                         "decision_id": decision["decision_id"]},
                                        event_id=event_id)
            changed += 1
            continue
        key = (batch_id, decision["envelope_sha256"])
        compile_payload = compile_rows.get(key)
        if compile_payload is None:
            raise ContractError("approved_compile_missing", "批准决定没有匹配 compile envelope")
        validate_dispatch_release(
            compile_payload.get("envelope"), envelope_hash=decision["envelope_sha256"],
            release_id=release_id)
        validate_approval_sequence(decision=decision, compile_payload=compile_payload,
                                   research_repo=research_repo,
                                   research_memory_path=research_memory_path,
                                   research_owner_uid=research_owner_uid)
        approval_effect = sha256({"kind": "batch-approved",
                                  "decision_id": decision["decision_id"]})
        approval_event_id = _event_id("batch_approved", approval_effect)
        token = decision["token"]
        append_batch_once(
            ledger_root, "batch_approved", batch_id, event_id=approval_event_id,
            payload={"effect_id": approval_effect, "decision_id": decision["decision_id"],
                     "token_id": token["token_id"],
                     "origin_signature_hash": sha256(base64.b64decode(
                         token["signature_b64"], validate=True)),
                     "goal_anchor_entry_hash": token["goal_anchor_entry_hash"],
                     "goal_anchor_receipt_id": token["goal_anchor_receipt_id"]})
        store.append_research_event(
            "batch_approved", batch_id,
            {"event_id": approval_event_id, "effect_id": approval_effect,
             "decision_id": decision["decision_id"], "token_id": token["token_id"]},
            event_id=approval_event_id)
        bridge.export_claim_request(claim_request_from_decision(
            decision, approval_event_id=approval_event_id, release_id=release_id))

    for imported in store.rows("dispatch_claim_imports"):
        result = json.loads(imported["document_json"])
        core = result["core"]
        decision_row = store.approval_import(core["request_id"], core["request_version"])
        if decision_row is None:
            raise StoreError("claim result has no imported decision")
        decision = json.loads(decision_row["decision_json"])
        expected, _ = claim_request_core(claim_request_from_decision(
            decision, approval_event_id=core["approval_event_id"], release_id=release_id))
        verify_claim_result(result, expected=expected, token=decision["token"],
                            public_key=approval_public_key)
        if core["state"] == "denied":
            effect_id = sha256({"kind": "batch-rejected-expired", "claim_id": core["claim_id"]})
            event_id = _event_id("batch_rejected", effect_id)
            append_batch_once(ledger_root, "batch_rejected", core["batch_id"], event_id=event_id,
                              payload={"effect_id": effect_id, "claim_id": core["claim_id"],
                                       "reason_code": "APPROVAL_EXPIRED"})
            store.append_research_event("batch_rejected", core["batch_id"],
                                        {"event_id": event_id, "effect_id": effect_id,
                                         "claim_id": core["claim_id"],
                                         "reason_code": "APPROVAL_EXPIRED"}, event_id=event_id)
            changed += 1
            continue
        compile_payload = compile_rows.get((core["batch_id"], core["envelope_hash"]))
        if compile_payload is None:
            raise ContractError("claimed_compile_missing", "claim 没有匹配 compile envelope")
        envelope = compile_payload["envelope"]
        if not isinstance(envelope.get("run_configs"), list) or not envelope["run_configs"]:
            raise ContractError("dispatch_run_configs_missing",
                                "批准 envelope 尚未编译确定性 run_configs")
        deadline = envelope.get("deadline_utc")
        if deadline is not None and datetime.now(timezone.utc) >= _aware(deadline, "deadline_utc"):
            effect_id = sha256({"kind": "batch-rejected-deadline", "claim_id": core["claim_id"]})
            event_id = _event_id("batch_dispatch_rejected", effect_id)
            append_batch_once(
                ledger_root, "batch_dispatch_rejected", core["batch_id"], event_id=event_id,
                payload={"effect_id": effect_id, "claim_id": core["claim_id"],
                         "reason_code": "ENVELOPE_DEADLINE_EXPIRED"})
            store.append_research_event(
                "batch_dispatch_rejected", core["batch_id"],
                {"event_id": event_id, "effect_id": effect_id,
                 "claim_id": core["claim_id"],
                 "reason_code": "ENVELOPE_DEADLINE_EXPIRED"}, event_id=event_id)
            changed += 1
            continue
        dispatch_event_id = _event_id("batch_dispatch_started", core["effect_id"])
        request = {"schema_version": 1, "kind": "dispatch_request",
                   "effect_id": core["effect_id"], "batch_id": core["batch_id"],
                   "envelope_hash": core["envelope_hash"], "release_id": release_id,
                   "claim_id": core["claim_id"], "token_id": core["token_id"],
                   "claim_receipt_hash": sha256(result),
                   "dispatch_event_id": dispatch_event_id, "envelope": envelope,
                   "run_configs": envelope["run_configs"]}
        store.prepare_dispatch_request(request)
        append_batch_once(
            ledger_root, "batch_dispatch_started", core["batch_id"],
            event_id=dispatch_event_id,
            payload={"effect_id": core["effect_id"], "claim_id": core["claim_id"],
                     "claim_receipt_hash": sha256(result), "release_id": release_id,
                     "dispatch_event_id": dispatch_event_id,
                     "envelope_sha256": core["envelope_hash"],
                     "dispatch_request_hash": sha256(request)})
        if dispatch_adapter is None:
            store.set_dispatch_request_state(core["effect_id"], state="blocked",
                                             reason_code="DISPATCH_SUPERVISOR_UNQUALIFIED")
            continue
        if not dispatch_adapter(request):
            store.set_dispatch_request_state(core["effect_id"], state="blocked",
                                             reason_code="DISPATCH_SUPERVISOR_REJECTED")
            continue
        current_rows = [row for row in store.rows("dispatch_requests")
                        if row["effect_id"] == core["effect_id"]]
        if len(current_rows) != 1:
            raise StoreError("dispatch request state unavailable")
        current_state = current_rows[0]["state"]
        qualification_block = current_rows[0].get("reason_code") in {
            None, "DISPATCH_SUPERVISOR_UNQUALIFIED", "DISPATCH_SUPERVISOR_REJECTED"}
        if (execution_qualified and current_state in {"prepared", "enqueued"}
                or execution_qualified and current_state == "blocked" and qualification_block):
            store.set_dispatch_request_state(core["effect_id"], state="enqueued")
        elif not execution_qualified and current_state in {"prepared", "blocked", "enqueued"}:
            # Queue preparation and Human-authority settlement are complete, but no
            # runner may consume the queue until a sealed qualification flips this
            # root-owned deployment fact.
            store.set_dispatch_request_state(
                core["effect_id"], state="blocked",
                reason_code="DISPATCH_SUPERVISOR_UNQUALIFIED")
        bridge.export_claim_settlement(settlement_request(
            claim_result=result, dispatch_event_id=dispatch_event_id))
        changed += 1
    return changed
