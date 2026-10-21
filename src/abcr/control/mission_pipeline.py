"""Broker-ref-only helpers for the production mission pipeline.

Mutable workers write only to their operation-specific staging directory.  The
root broker seals that finite tree and returns an opaque reference; downstream
workers reopen the object through a separately configured read-only root and
recompute the sealed tree hash before trusting any bytes.
"""
from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Callable

from abcr.control.contracts import (ContractError, canonical_json, require_id,
                                    require_sha, sha256, strict_object)
from abcr.control.queue_runtime import WorkBrokerClient
from abcr.control.mission_coordinator import TrustedMissionCoordinator
from abcr.control.store import ControlStore
from abcr.control.work_spool import WORK_ID
from abcr.control.worktree import scan_tree, tree_hash


def _safe_object_id(value: str) -> str:
    require_id(value, "object_id")
    if "/" in value or ".." in value or WORK_ID.fullmatch(value) is None:
        raise ContractError("broker_object_id", "sealed object id 不合法")
    return value


def broker_ref(receipt: Any, *, expected_operation: str) -> dict[str, str]:
    obj = strict_object(receipt, required={
        "receipt_id", "operation", "nonce", "object_id", "tree_hash",
        "sealed_tree_hash", "sealed_path", "created_at"})
    if obj["operation"] != expected_operation:
        raise ContractError("broker_receipt_operation", "broker receipt operation 不匹配")
    for field in ("receipt_id", "tree_hash", "sealed_tree_hash"):
        require_sha(obj[field], field)
    _safe_object_id(obj["object_id"])
    return {"operation": obj["operation"], "receipt_id": obj["receipt_id"],
            "object_id": obj["object_id"],
            "sealed_tree_hash": obj["sealed_tree_hash"]}


def validate_broker_ref(raw: Any, *, expected_operation: str) -> dict[str, str]:
    obj = strict_object(raw, required={"operation", "receipt_id", "object_id",
                                      "sealed_tree_hash"})
    if obj["operation"] != expected_operation:
        raise ContractError("broker_ref_operation", "broker ref operation 不匹配")
    require_sha(obj["receipt_id"], "receipt_id")
    require_sha(obj["sealed_tree_hash"], "sealed_tree_hash")
    _safe_object_id(obj["object_id"])
    return obj


def _write_exact_file(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ContractError("pipeline_staging_conflict", "已有 staging artifact 内容冲突")
        return
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def seal_json_artifact(client: WorkBrokerClient, *, operation: str,
                       staging_root: Path, object_id: str, filename: str,
                       document: dict[str, Any], nonce: str) -> dict[str, str]:
    """Stage one canonical JSON file and return only the broker reference."""
    object_id = _safe_object_id(object_id)
    root = Path(staging_root)
    if root.is_symlink() or not root.is_dir():
        raise ContractError("pipeline_staging_root_invalid", "固定 staging root 不可用")
    if (not filename or "/" in filename or filename in {".", ".."}
            or not filename.endswith(".json")):
        raise ContractError("pipeline_artifact_name_invalid", "artifact filename 不合法")
    source = root / object_id
    if source.exists():
        if source.is_symlink() or not source.is_dir():
            raise ContractError("pipeline_staging_conflict", "staging object 类型冲突")
    else:
        source.mkdir(mode=0o700)
    entries = list(source.iterdir())
    if entries and {item.name for item in entries} != {filename}:
        raise ContractError("pipeline_staging_conflict", "staging object 包含额外文件")
    _write_exact_file(source / filename, canonical_json(document) + b"\n")
    observed = tree_hash(scan_tree(source))
    receipt = client.request(operation, {"source": str(source), "nonce": nonce,
                                         "expected_tree_hash": observed,
                                         "object_id": object_id})
    return broker_ref(receipt, expected_operation=operation)


def load_json_artifact(raw_ref: Any, *, expected_operation: str,
                       trusted_root: Path, filename: str) -> dict[str, Any]:
    """Resolve a ref only inside its configured read root and re-hash the tree."""
    ref = validate_broker_ref(raw_ref, expected_operation=expected_operation)
    source = resolve_sealed_tree(ref, expected_operation=expected_operation,
                                 trusted_root=trusted_root)
    entries = scan_tree(source)
    if len(entries) != 1 or entries[0].path != filename:
        raise ContractError("pipeline_sealed_shape_invalid", "sealed object 文件集合不合法")
    path = source / filename
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > 16 * 1024 * 1024):
        raise ContractError("pipeline_sealed_file_unsafe", "sealed artifact inode 不安全")
    try:
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=_unique_object,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ContractError("pipeline_sealed_json_invalid", "sealed artifact JSON 不合法") from exc
    if not isinstance(value, dict) or canonical_json(value) + b"\n" != raw:
        raise ContractError("pipeline_sealed_json_noncanonical", "sealed artifact 必须是 canonical JSON")
    return value


def resolve_sealed_tree(raw_ref: Any, *, expected_operation: str,
                        trusted_root: Path) -> Path:
    """Resolve and re-hash an arbitrary sealed tree without trusting a path ref."""
    ref = validate_broker_ref(raw_ref, expected_operation=expected_operation)
    root = Path(trusted_root)
    if root.is_symlink() or not root.is_dir():
        raise ContractError("pipeline_trusted_root_invalid", "固定 sealed read root 不可用")
    source = root / ref["object_id"]
    if source.is_symlink() or not source.is_dir() or source.parent.resolve() != root.resolve():
        raise ContractError("pipeline_sealed_object_missing", "sealed object 不可用")
    entries = scan_tree(source)
    if tree_hash(entries) != ref["sealed_tree_hash"]:
        raise ContractError("pipeline_sealed_tree_drift", "sealed object tree hash 漂移")
    return source


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def artifact_object_id(prefix: str, document: dict[str, Any]) -> str:
    if not prefix.isalnum() or len(prefix) > 12:
        raise ValueError("invalid artifact prefix")
    return f"{prefix}-{sha256(document)[:48]}"


def enqueue_stage(client: WorkBrokerClient, *, stage: str, work_id: str,
                  payload: dict[str, Any], producer: str, attempt: int,
                  fencing_token: int) -> None:
    if WORK_ID.fullmatch(work_id) is None:
        raise ContractError("work_id_invalid", "work id 不合法")
    result = client.request("work_enqueue", {
        "stage": stage, "work_id": work_id, "attempt": attempt,
        "fencing_token": fencing_token, "producer": producer, "payload": payload})
    exact = strict_object(result, required={"work_id"})
    if exact["work_id"] != work_id:
        raise ContractError("broker_response_invalid", "enqueue identity 不匹配")


PIPELINE_STAGES = ("mission-build", "test", "verify", "release-prepare",
                   "canary", "activate")


def reconcile_queued_missions(store: ControlStore, client: WorkBrokerClient,
                              coordinator: TrustedMissionCoordinator) -> int:
    """Enqueue dependency-ready mission intents exactly once as Operator.

    Human-required missions deliberately stay visible and queued.  They cannot
    enter the autonomous builder merely because an incident producer understated
    the risk.
    """
    changed = 0
    required = {"objective", "non_goals", "incident_evidence", "base_release",
                "allowed_paths", "acceptance_profile", "declared_risk",
                "rollback_release"}
    for row in store.ready_missions():
        if row["risk"] == "human_required":
            continue
        if row["risk"] not in {"normal", "guarded"}:
            raise ContractError("mission_risk_invalid", "mission risk 不合法")
        payload = strict_object(row["payload"], required=required)
        if (payload["declared_risk"] != row["risk"]
                or payload["base_release"] != row["base_release"]
                or not isinstance(payload["objective"], str)
                or not payload["objective"].strip()
                or not isinstance(payload["allowed_paths"], list)
                or not payload["allowed_paths"]
                or any(not isinstance(item, str) or not item
                       for item in payload["allowed_paths"])
                or not isinstance(payload["rollback_release"], str)
                or not payload["rollback_release"]):
            raise ContractError("mission_intent_invalid", "mission intent 与索引不一致")
        attempt = int(row["attempt"]) + 1
        fencing_token = int(row["fencing_token"]) + 1
        prepared = coordinator.prepare(mission_id=row["mission_id"],
                                       release_id=payload["base_release"])
        request = {"mission_id": row["mission_id"],
                   "objective": payload["objective"],
                   "allowed_paths": payload["allowed_paths"],
                   "declared_risk": payload["declared_risk"],
                   # The worker derives the path from work_id and its root-owned
                   # prepared_base_root.  It receives an identity and hash,
                   # never a release filesystem path or caller-selected source.
                   "base_release": prepared.release_id,
                   "base_tree_hash": prepared.base_tree_hash,
                   "old_release": payload["rollback_release"],
                   "expected_version": None}
        enqueue_stage(client, stage="mission-build", work_id=row["mission_id"],
                      producer="abcr-operator", attempt=attempt,
                      fencing_token=fencing_token, payload=request)
        changed += int(store.mark_mission_enqueued(
            row["mission_id"], expected_attempt=attempt,
            fencing_token=fencing_token))
    return changed


def _next_payload(stage: str, value: dict[str, Any], work_id: str,
                  source_fencing_token: int) -> tuple[str, dict[str, Any]] | None:
    """Validate one successful consumer result and derive a ref-only successor."""
    if stage == "mission-build":
        obj = strict_object(value, required={
            "base_tree_hash", "candidate_tree_hash", "changed_paths", "deleted_paths",
            "added_paths", "candidate_ref", "candidate_id", "mission_id",
            "declared_risk", "old_release", "expected_version"})
        if obj["mission_id"] != work_id or obj["candidate_id"] != work_id:
            raise ContractError("mission_work_identity_mismatch", "builder result identity 漂移")
        require_sha(obj["base_tree_hash"], "base_tree_hash")
        require_sha(obj["candidate_tree_hash"], "candidate_tree_hash")
        if (obj["declared_risk"] not in {"normal", "guarded", "human_required"}
                or any(not isinstance(items, list)
                       or any(not isinstance(item, str) for item in items)
                       for items in (obj["changed_paths"], obj["deleted_paths"], obj["added_paths"]))):
            raise ContractError("builder_result_invalid", "builder result metadata 不合法")
        candidate_ref = validate_broker_ref(obj["candidate_ref"],
                                            expected_operation="seal_attestation")
        if candidate_ref["sealed_tree_hash"] != obj["candidate_tree_hash"]:
            raise ContractError("candidate_ref_identity_mismatch", "candidate ref/hash 不匹配")
        return "test", {"mission_id": work_id, "candidate_ref": obj["candidate_ref"],
                        "pipeline_context": {
                            "candidate_id": work_id, "base_tree_hash": obj["base_tree_hash"],
                            "changed_paths": obj["changed_paths"],
                            "declared_risk": obj["declared_risk"],
                            "old_release": obj["old_release"],
                            "expected_version": obj["expected_version"]}}
    if stage == "test":
        obj = strict_object(value, required={"mission_id", "verdict", "broker_ref"})
        if obj["mission_id"] != work_id:
            raise ContractError("mission_work_identity_mismatch", "test result identity 漂移")
        validate_broker_ref(obj["broker_ref"], expected_operation="seal_test_result")
        return None if obj["verdict"] != "PASS" else (
            "verify", {"test_result_ref": obj["broker_ref"],
                       "source_fencing_token": source_fencing_token})
    if stage == "verify":
        obj = strict_object(value, required={"mission_id", "verdict", "broker_ref"})
        if obj["mission_id"] != work_id:
            raise ContractError("mission_work_identity_mismatch", "verification identity 漂移")
        validate_broker_ref(obj["broker_ref"], expected_operation="seal_verification")
        return None if obj["verdict"] != "PASS" else (
            "release-prepare", {"verification_ref": obj["broker_ref"],
                                "source_fencing_token": source_fencing_token})
    if stage == "release-prepare":
        obj = strict_object(value, required={
            "mission_id", "verdict", "release_id", "broker_ref",
            "verification_ref", "old_release", "expected_version"})
        if obj["mission_id"] != work_id:
            raise ContractError("mission_work_identity_mismatch", "release result identity 漂移")
        validate_broker_ref(obj["broker_ref"], expected_operation="seal_release")
        if obj["broker_ref"]["object_id"] != obj["release_id"]:
            raise ContractError("release_ref_identity_mismatch", "release ref/id 不匹配")
        validate_broker_ref(obj["verification_ref"], expected_operation="seal_verification")
        return None if obj["verdict"] != "PASS" else (
            "canary", {"mission_id": work_id, "release_ref": obj["broker_ref"],
                       "verification_ref": obj["verification_ref"],
                       "expected_version": obj["expected_version"],
                       "old_release": obj["old_release"]})
    if stage == "canary":
        obj = strict_object(value, required={"mission_id", "verdict", "broker_ref"})
        if obj["mission_id"] != work_id:
            raise ContractError("mission_work_identity_mismatch", "canary result identity 漂移")
        validate_broker_ref(obj["broker_ref"], expected_operation="seal_canary")
        return None if obj["verdict"] != "PASS" else (
            "activate", {"canary_ref": obj["broker_ref"]})
    if stage == "activate":
        if not isinstance(value, dict) or not value.get("release_id"):
            raise ContractError("activation_result_invalid", "activation result 不合法")
        return None
    raise ContractError("pipeline_stage_invalid", "非 mission pipeline stage")


def reconcile_mission_pipeline(
        client: WorkBrokerClient,
        before_ack: Callable[[dict[str, Any]], None] | None = None,
        ) -> list[dict[str, Any]]:
    """Operator-only result→enqueue→ACK saga for all production mission stages.

    Enqueue is content-idempotent.  Therefore a crash after enqueue but before
    ACK is repaired by replaying the same successor and then ACKing the exact
    immutable result hash.  Failed/non-PASS results are ACKed but never advance.
    """
    events: list[dict[str, Any]] = []
    for stage in PIPELINE_STAGES:
        for identity in client.completed_fenced(stage):
            envelope = client.read_result(stage, identity["work_id"],
                                          attempt=identity["attempt"],
                                          fencing_token=identity["fencing_token"])
            outer = strict_object(envelope["result"], required={"ok"},
                                  optional={"result", "error_code"})
            advanced_to: str | None = None
            disposition = "failed"
            if outer["ok"] is True:
                value = outer.get("result")
                if not isinstance(value, dict):
                    raise ContractError("work_result_invalid", "successful result 必须是 object")
                successor = _next_payload(stage, value, identity["work_id"],
                                          identity["fencing_token"])
                if successor is not None:
                    advanced_to, payload = successor
                    enqueue_stage(client, stage=advanced_to, work_id=identity["work_id"],
                                  producer="abcr-operator", attempt=identity["attempt"],
                                  fencing_token=identity["fencing_token"], payload=payload)
                    disposition = "advanced"
                else:
                    disposition = "terminal" if stage == "activate" else "halted"
            event = {"stage": stage, "work_id": identity["work_id"],
                     "disposition": disposition, "advanced_to": advanced_to}
            # Persist the control read-model terminal before removing the only
            # unread broker result.  Replay after a crash is safe: successor
            # enqueue and terminal-store CAS are both idempotent.
            if before_ack is not None:
                before_ack(event)
            client.acknowledge(stage, identity["work_id"],
                               result_hash=envelope["result_hash"],
                               attempt=identity["attempt"],
                               fencing_token=identity["fencing_token"])
            events.append(event)
    return events
