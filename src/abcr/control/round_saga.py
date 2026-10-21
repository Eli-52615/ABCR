"""Completed batch -> independent audit -> sealed report -> inert draft saga.

The queue carries compile identities, never evidence rows or caller-selected paths.
The auditor reopens ``Evidence/runs`` under its own fixed config.  Operator trusts
only a root-broker receipt, re-hashed sealed tree and auditor signature.  Generated
suggestions live in ``goal_drafts`` and cannot enter the proposal/compile pipeline.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Any

from abcr.audit.evidence import AuditAttestation
from abcr.common.ledger_ref import RunLedger
from abcr.control.contracts import (ContractError, canonical_json, require_sha,
                                    sha256, strict_object)
from abcr.control.mission_pipeline import (enqueue_stage, load_json_artifact,
                                           validate_broker_ref)
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.store import ControlStore, StoreError
from abcr.explore.memory import ResearchMemory
from abcr.explore.rounds import build_round_report, next_goal_draft


AUDIT_RESULT_FIELDS = {
    "batch_id", "expected_keys_hash", "steps_hash", "scores_hash",
    "sidecars_hash", "verdict", "defects", "created_at", "attestation_hash",
    "goal_id", "compile_envelope_sha256", "compile_envelope", "sealed",
}


def _compile_event(store: ControlStore, *, batch_id: str,
                   envelope_hash: str) -> tuple[str, dict[str, Any]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    for row in store.rows("research_events"):
        if row["event_type"] != "compile_envelope_ready":
            continue
        payload = json.loads(row["payload_json"])
        if (payload.get("batch_id") == batch_id
                and payload.get("envelope_sha256") == envelope_hash):
            matches.append((row["event_id"], payload))
    if len(matches) != 1:
        raise ContractError("completed_compile_event_ambiguous",
                            "completed dispatch 必须恰有一个匹配 compile event")
    return matches[0]


def _bundle_wire(envelope: dict[str, Any]) -> dict[str, Any]:
    receipt = envelope.get("selection_receipt")
    if not isinstance(receipt, dict):
        raise ContractError("compile_selection_receipt_missing",
                            "compile envelope 缺 DevBundle selection receipt")
    value = {
        "bundle_id": envelope.get("dev_bundle_id"),
        "manifest_hash": envelope.get("dev_bundle_manifest_hash"),
        "item_ids": envelope.get("item_ids"),
        "source_hash": receipt.get("source_hash"),
    }
    for field in ("bundle_id", "manifest_hash", "source_hash"):
        require_sha(value[field], field)
    if (not isinstance(value["item_ids"], list) or not value["item_ids"]
            or any(not isinstance(item, str) or not item for item in value["item_ids"])):
        raise ContractError("compile_item_ids_invalid", "compile item_ids 不合法")
    return value


def enqueue_completed_batch_audits(*, store: ControlStore,
                                   broker: WorkBrokerClient,
                                   ledger_root: Path) -> int:
    """Enqueue one audit only after both DB completion and ledger settlement."""
    ledger = RunLedger(Path(ledger_root), "batches")
    changed = 0
    for row in store.rows("dispatch_requests"):
        if row["state"] != "completed":
            continue
        request = json.loads(row["request_json"])
        if (sha256(request) != row["request_hash"]
                or request.get("batch_id") != row["batch_id"]
                or request.get("dispatch_event_id") != row["dispatch_event_id"]
                or not ledger.has_event("batch_settled", row["batch_id"])):
            raise ContractError("completed_dispatch_fact_invalid",
                                "dispatch completed 与 request/ledger 事实不一致")
        compile_event_id, compiled = _compile_event(
            store, batch_id=row["batch_id"], envelope_hash=row["envelope_hash"])
        envelope = compiled.get("envelope")
        if (not isinstance(envelope, dict) or sha256(envelope) != row["envelope_hash"]
                or envelope != request.get("envelope")):
            raise ContractError("completed_compile_envelope_drift",
                                "dispatch request 与 compile event 信封不一致")
        work_id = "evidence-" + sha256({
            "batch_id": row["batch_id"], "dispatch_event_id": row["dispatch_event_id"],
            "compile_event_id": compile_event_id})[:40]
        event_id = sha256({"kind": "evidence_audit_enqueued", "work_id": work_id})
        payload = {
            "kind": "evidence_from_runs", "batch_id": row["batch_id"],
            "dispatch_effect_id": row["effect_id"],
            "dispatch_event_id": row["dispatch_event_id"],
            "envelope_hash": row["envelope_hash"], "compile_envelope": envelope,
            "dev_bundle": _bundle_wire(envelope),
        }
        enqueue_stage(broker, stage="audit", work_id=work_id, payload=payload,
                      producer="abcr-operator", attempt=1, fencing_token=1)
        if store.research_event(event_id) is None:
            store.append_research_event(
                "evidence_audit_enqueued", row["batch_id"],
                {"work_id": work_id, "dispatch_effect_id": row["effect_id"],
                 "dispatch_event_id": row["dispatch_event_id"],
                 "compile_event_id": compile_event_id,
                 "envelope_hash": row["envelope_hash"]}, event_id=event_id)
            changed += 1
    return changed


def _read_receipt(ref: dict[str, str], *, receipt_root: Path,
                  sealed_root: Path, receipt_group_gid: int) -> dict[str, Any]:
    """Verify canonical root receipt and its exact fixed sealed target binding."""
    root = Path(receipt_root)
    if root.is_symlink() or not root.is_dir():
        raise ContractError("audit_receipt_root_invalid", "固定 broker receipt root 不可用")
    path = root / f"{ref['receipt_id']}.json"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContractError("audit_receipt_missing", "broker receipt 不可达") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != 0 or info.st_gid != receipt_group_gid
                or stat.S_IMODE(info.st_mode) != 0o440
                or info.st_size > 65536):
            raise ContractError("audit_receipt_unsafe", "broker receipt inode/mode 不安全")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if len(raw) != info.st_size or (info.st_dev, info.st_ino, info.st_size) != (
                after.st_dev, after.st_ino, after.st_size):
            raise ContractError("audit_receipt_changed", "broker receipt 读取期间变化")
    finally:
        os.close(fd)
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("audit_receipt_invalid", "broker receipt JSON 不合法") from exc
    receipt = strict_object(receipt, required={
        "receipt_id", "operation", "nonce", "object_id", "tree_hash",
        "sealed_tree_hash", "sealed_path", "created_at"})
    if canonical_json(receipt) + b"\n" != raw:
        raise ContractError("audit_receipt_noncanonical", "broker receipt 非 canonical")
    expected_id = sha256({"operation": receipt["operation"], "nonce": receipt["nonce"],
                          "tree_hash": receipt["tree_hash"],
                          "object_id": receipt["object_id"]})
    expected_path = Path(sealed_root) / ref["object_id"]
    if (receipt["receipt_id"] != expected_id or receipt["receipt_id"] != ref["receipt_id"]
            or receipt["operation"] != "seal_audit_result"
            or receipt["object_id"] != ref["object_id"]
            or receipt["sealed_tree_hash"] != ref["sealed_tree_hash"]
            or receipt["sealed_path"] != str(expected_path)):
        raise ContractError("audit_receipt_binding_invalid",
                            "broker receipt 未绑定固定 audit object/tree/path")
    return receipt


def _audit_from_document(value: Any) -> AuditAttestation:
    obj = strict_object(value, required=AUDIT_RESULT_FIELDS)
    for field in ("expected_keys_hash", "steps_hash", "scores_hash", "sidecars_hash",
                  "attestation_hash", "compile_envelope_sha256"):
        require_sha(obj[field], field)
    if (not isinstance(obj["defects"], list)
            or any(not isinstance(item, str) for item in obj["defects"])
            or not isinstance(obj["compile_envelope"], dict)
            or not isinstance(obj["sealed"], dict)):
        raise ContractError("audit_result_shape_invalid", "sealed audit result 形状不合法")
    return AuditAttestation(**{**obj, "defects": tuple(obj["defects"])})


def _machine_inputs(audit: AuditAttestation, audit_ref: dict[str, str]
                    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[dict[str, Any]]]:
    observations = [{"origin": "machine", "kind": "independent_evidence_audit",
                     "verdict": audit.verdict, "defects": list(audit.defects),
                     "evidence_ref": audit_ref["receipt_id"]}]
    interpretations = [
        "独立审计只证明已密封证据集合的完整性与绑定；不自动证明人格理论解释成立。"
    ]
    limitations = [
        "本段为确定性机器摘要，不包含人类反思，也未调用 LLM 设计顾问。"
    ]
    suggestions: list[dict[str, Any]] = []
    if audit.verdict == "PASS":
        suggestions.append({
            "observation": "该批次的完整证据集合通过独立审计。",
            "competing_explanation": "观察差异仍可能来自题集、顺序或随机种子，而非人格机制。",
            "discriminating_experiment": "由人和 Claude 基于本报告选择一个竞争解释，设计预注册复现实验。",
            "opposite_result_update": "若复现方向相反，应降低原机制解释的置信度并记录被推翻条件。",
            "evidence_refs": [audit.attestation_hash, audit_ref["receipt_id"]],
        })
    return observations, interpretations, limitations, suggestions


def _append_memory_once(memory: ResearchMemory, *, event_type: str, subject_id: str,
                        payload: dict[str, Any]) -> bool:
    matches = [row for row in memory.verify()
               if row["event_type"] == event_type and row["subject_id"] == subject_id]
    if matches:
        if len(matches) != 1 or matches[0]["payload"] != payload:
            raise ContractError("round_memory_replay_conflict", "ResearchMemory 轮次事件冲突")
        return False
    memory.append(event_type, subject_id, payload, actor_id="abcr-operator-machine")
    return True


def _reseal_memory(memory: ResearchMemory, broker: WorkBrokerClient, nonce: str) -> None:
    core = memory.seal_core()
    result = broker.request("seal_research_memory", {
        "nonce": nonce, "expected_length": core["length"],
        "expected_head_entry_hash": core["head_entry_hash"],
        "expected_ledger_sha256": core["ledger_sha256"],
    })
    if (not isinstance(result, dict) or result.get("length") != core["length"]
            or result.get("head_entry_hash") != core["head_entry_hash"]
            or result.get("ledger_sha256") != core["ledger_sha256"]):
        raise ContractError("round_memory_seal_mismatch", "ResearchMemory seal 回执不匹配")


def reconcile_evidence_audits(*, store: ControlStore, broker: WorkBrokerClient,
                              sealed_audit_root: Path, receipt_root: Path,
                              receipt_group_gid: int,
                              auditor_public_key: Path,
                              research_memory_path: Path,
                              research_owner_uid: int,
                              ledger_root: Path) -> int:
    """Verify sealed audit results and publish reports/drafts, then acknowledge."""
    if type(receipt_group_gid) is not int or receipt_group_gid < 0:
        raise ContractError("audit_receipt_group_invalid", "broker receipt group 配置不合法")
    completed = {item["work_id"]: item for item in broker.completed_fenced("audit")}
    changed = 0
    for event in store.rows("research_events"):
        if event["event_type"] != "evidence_audit_enqueued":
            continue
        payload = json.loads(event["payload_json"])
        work_id = payload.get("work_id")
        fence = completed.get(work_id)
        if fence is None:
            continue
        envelope = broker.read_result("audit", work_id, attempt=fence["attempt"],
                                      fencing_token=fence["fencing_token"])
        require_sha(envelope["result_hash"], "audit_result.result_hash")
        if (envelope["schema_version"] != 1 or envelope["stage"] != "audit"
                or envelope["work_id"] != work_id
                or envelope["attempt"] != fence["attempt"]
                or envelope["fencing_token"] != fence["fencing_token"]
                or envelope["consumer"] != "abcr-auditor"
                or not isinstance(envelope["completed_at"], str)
                or sha256(envelope["result"]) != envelope["result_hash"]):
            raise ContractError("evidence_result_envelope_invalid",
                                "audit result envelope/fence/consumer 不合法")
        outer = strict_object(envelope["result"], required={"ok"},
                              optional={"result", "error_code"})
        if outer["ok"] is not True:
            raise ContractError("evidence_audit_failed",
                                str(outer.get("error_code", "evidence_audit_failed")))
        result = strict_object(outer.get("result"), required={
            "kind", "batch_id", "dispatch_event_id", "audit_ref"})
        if (result["kind"] != "evidence_audit" or result["batch_id"] != event["subject_id"]
                or result["dispatch_event_id"] != payload["dispatch_event_id"]):
            raise ContractError("evidence_audit_result_binding", "audit result 未绑定 dispatch")
        reference = validate_broker_ref(result["audit_ref"],
                                        expected_operation="seal_audit_result")
        _read_receipt(reference, receipt_root=receipt_root,
                      sealed_root=sealed_audit_root,
                      receipt_group_gid=receipt_group_gid)
        document = load_json_artifact(
            reference, expected_operation="seal_audit_result",
            trusted_root=sealed_audit_root, filename="audit-result.json")
        audit = _audit_from_document(document)
        dispatch_rows = [row for row in store.rows("dispatch_requests")
                         if row["batch_id"] == result["batch_id"]]
        if len(dispatch_rows) != 1 or dispatch_rows[0]["state"] != "completed":
            raise StoreError("completed dispatch disappeared before round report")
        request = json.loads(dispatch_rows[0]["request_json"])
        if (audit.batch_id != result["batch_id"]
                or audit.compile_envelope != request["envelope"]):
            raise ContractError("audit_dispatch_envelope_mismatch",
                                "sealed audit 与 completed dispatch 不一致")
        round_id = "ROUND-" + sha256({"batch_id": audit.batch_id,
                                       "audit": audit.attestation_hash})[:24]
        observations, interpretations, limitations, suggestions = _machine_inputs(
            audit, reference)
        report = build_round_report(
            round_id=round_id, goal_id=request["envelope"]["goal_id"], audit=audit,
            observations=observations, interpretations=interpretations,
            limitations=limitations, suggestion_inputs=suggestions,
            expected_batch_id=audit.batch_id, auditor_public_key=auditor_public_key,
            compile_envelope=request["envelope"], analysis_origin="machine_deterministic",
            generated_at=audit.created_at)
        report_doc = asdict(report)
        if store.save_round_report(
                round_id=round_id, batch_id=audit.batch_id, goal_id=report.goal_id,
                status=report.status, report_hash=report.report_hash,
                audit_reference=reference, report=report_doc):
            changed += 1
        ledger = RunLedger(Path(ledger_root), "batches")
        if not ledger.has_event("batch_audited", audit.batch_id):
            ledger.append("batch_audited", subject_id=audit.batch_id,
                          audit_attestation_hash=audit.attestation_hash,
                          audit_receipt_id=reference["receipt_id"], verdict=audit.verdict)
        if not ledger.has_event("batch_reported", audit.batch_id):
            ledger.append("batch_reported", subject_id=audit.batch_id,
                          round_id=round_id, report_hash=report.report_hash,
                          status=report.status)
        drafts: list[tuple[str, dict[str, Any]]] = []
        for suggestion in report.suggestions:
            draft = next_goal_draft(report, suggestion.suggestion_id)
            draft_id = "DRAFT-" + sha256({"round_id": round_id,
                                           "suggestion_id": suggestion.suggestion_id})[:24]
            if store.save_goal_draft(draft_id=draft_id, round_id=round_id,
                                     suggestion_id=suggestion.suggestion_id, draft=draft):
                changed += 1
            drafts.append((draft_id, draft))
        memory = ResearchMemory(Path(research_memory_path), owner_uid=research_owner_uid)
        _append_memory_once(
            memory, event_type="round_reported", subject_id=round_id,
            payload={"batch_id": audit.batch_id, "goal_id": report.goal_id,
                     "report_hash": report.report_hash, "status": report.status,
                     "audit_ref": reference, "analysis_origin": report.analysis_origin,
                     "human_reflections_included": False})
        for draft_id, draft in drafts:
            _append_memory_once(
                memory, event_type="next_goal_draft_created", subject_id=draft_id,
                payload={"round_id": round_id, "draft_hash": sha256(draft),
                         "state": "awaiting_human_claude", "origin": "machine",
                         "auto_execute": False})
        _reseal_memory(memory, broker, "RM-ROUND-" + sha256(round_id)[:24])
        store.append_research_event(
            "round_reported", round_id,
            {"batch_id": audit.batch_id, "report_hash": report.report_hash,
             "audit_ref": reference, "draft_ids": [item[0] for item in drafts]},
            event_id=sha256({"kind": "round_reported", "round_id": round_id}))
        broker.acknowledge("audit", work_id, result_hash=envelope["result_hash"],
                           attempt=fence["attempt"], fencing_token=fence["fencing_token"])
    return changed
