"""Production Human-domain approval boundary.

Operator may carry a finite display bundle and opaque broker identifiers across the
file bridge.  It may never carry the validator document itself.  Human re-opens the
one fixed root-owned object, binds its exact bytes/tree to the reference, verifies
the validator signature and only then permits the owner key to sign approval v2.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from abcr.control.approval_agent import decide
from abcr.control.contracts import (ContractError, canonical_json, require_id,
                                    require_sha, sha256, strict_object, utc_now)
from abcr.control.ed25519 import (ApprovalRequestBundle, CONTEXT_FIELDS,
                                  VerifiedAnchor, identity_context_hash,
                                  verify_token_v2)
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore, StoreError
from abcr.control.validated_approval_bundle import (verify_finite_request,
                                                    verify_validator_document)
from abcr.control.worktree import scan_tree, tree_hash


APPROVAL_BUNDLE_ROOT = Path("/Library/Application Support/ABCR-ApprovalBundles")
BROKER_RECEIPT_ROOT = Path("/Library/Application Support/ABCR-Attest/release-receipts")
TRUST_ROOT = Path("/Library/Application Support/ABCR-Trust")
VALIDATOR_PUBLIC_KEY = TRUST_ROOT / "approval-validator.pub"
APPROVAL_PUBLIC_KEY = TRUST_ROOT / "approval.pub"
HUMAN_PRIVATE_KEY = Path(
    "/Users/abcr-human/Library/Application Support/ABCR-Human/approval-ed25519.pem")

REFERENCE_FIELDS = {"broker_receipt_id", "broker_object_id", "sealed_tree_hash"}
BUNDLE_FIELDS = {
    "request_id", "goal_bytes_b64", "goal_sha256", "research_commit",
    "artifact_frozen_receipt", "envelope", "envelope_sha256",
    "anchor_prefix_proof",
}
DECISION_FIELDS = {
    "schema_version", "kind", "decision_id", "request_id", "request_version",
    "envelope_sha256", "decision", "source_event_id", "decision_nonce_hash",
    "context", "token", "reason", "decided_at",
}


def approval_bundle_to_wire(bundle: ApprovalRequestBundle) -> dict[str, Any]:
    value = asdict(bundle)
    value["anchor_prefix_proof"] = list(bundle.anchor_prefix_proof)
    return value


def approval_bundle_from_wire(value: Any) -> ApprovalRequestBundle:
    obj = strict_object(value, required=BUNDLE_FIELDS)
    if (not isinstance(obj["artifact_frozen_receipt"], dict)
            or not isinstance(obj["envelope"], dict)
            or not isinstance(obj["anchor_prefix_proof"], list)
            or not obj["anchor_prefix_proof"]
            or any(not isinstance(item, str) or not item
                   for item in obj["anchor_prefix_proof"])):
        raise ContractError("approval_request_wire_invalid",
                            "ApprovalRequestBundle wire 不合法")
    require_id(obj["request_id"], "request_id")
    require_sha(obj["goal_sha256"], "goal_sha256")
    require_sha(obj["envelope_sha256"], "envelope_sha256")
    return ApprovalRequestBundle(
        obj["request_id"], obj["goal_bytes_b64"], obj["goal_sha256"],
        obj["research_commit"], obj["artifact_frozen_receipt"], obj["envelope"],
        obj["envelope_sha256"], tuple(obj["anchor_prefix_proof"]),
    )


def approval_reference(value: Any) -> dict[str, str]:
    obj = strict_object(value, required=REFERENCE_FIELDS)
    for field in REFERENCE_FIELDS:
        require_sha(obj[field], field)
    return obj


def _unique_json(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ContractError("approval_validator_duplicate_key",
                                    "validator document 含重复 JSON key")
            out[key] = value
        return out
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("approval_validator_json_invalid",
                            "validator document 不是严格 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("approval_validator_json_invalid",
                            "validator document 必须是 JSON object")
    return value


def _require_directory(path: Path, *, owner_uid: int, group_gid: int,
                       mode: int) -> None:
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != owner_uid or info.st_gid != group_gid
            or stat.S_IMODE(info.st_mode) != mode):
        raise ContractError("approval_bundle_directory_unsafe",
                            "approval bundle 目录 owner/group/mode 不安全")


def _read_exact_file(path: Path, *, owner_uid: int, group_gid: int,
                     mode: int, maximum: int = 1024 * 1024) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != owner_uid or info.st_gid != group_gid
                or stat.S_IMODE(info.st_mode) != mode or info.st_size > maximum):
            raise ContractError("approval_bundle_file_unsafe",
                                "approval bundle 文件 owner/group/mode/link 不安全")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        if ((after.st_dev, after.st_ino, after.st_size, after.st_nlink)
                != (info.st_dev, info.st_ino, info.st_size, info.st_nlink)
                or len(raw) != info.st_size):
            raise ContractError("approval_bundle_file_changed",
                                "approval bundle 文件读取时发生变化")
        return raw
    finally:
        os.close(fd)


def require_root_trust_key(path: Path, *, root_uid: int = 0,
                           root_gid: int = 0) -> Path:
    _read_exact_file(Path(path), owner_uid=root_uid, group_gid=root_gid,
                     mode=0o444, maximum=65536)
    return Path(path)


def load_broker_sealed_request(
        bundle: ApprovalRequestBundle, reference: dict[str, Any], *,
        approval_root: Path = APPROVAL_BUNDLE_ROOT,
        receipt_root: Path = BROKER_RECEIPT_ROOT,
        validator_public_key: Path = VALIDATOR_PUBLIC_KEY,
        root_uid: int = 0, human_gid: int,
        receipt_group_gid: int, trust_root_gid: int = 0
        ) -> tuple[dict[str, Any], VerifiedAnchor]:
    """Open only ``<fixed-root>/<object-id>/validator.json`` and verify all bindings."""
    ref = approval_reference(reference)
    root = Path(approval_root)
    _require_directory(root, owner_uid=root_uid, group_gid=human_gid, mode=0o550)
    object_dir = root / ref["broker_object_id"]
    # Object ids are SHA-256, so joining them cannot escape the fixed root.
    _require_directory(object_dir, owner_uid=root_uid, group_gid=human_gid, mode=0o550)
    names = {entry.name for entry in object_dir.iterdir()}
    if names != {"validator.json"}:
        raise ContractError("approval_bundle_tree_invalid",
                            "broker-sealed approval object 必须只含 validator.json")
    path = object_dir / "validator.json"
    raw = _read_exact_file(path, owner_uid=root_uid, group_gid=human_gid, mode=0o440)
    if sha256(raw) != ref["broker_object_id"]:
        raise ContractError("approval_bundle_object_hash_mismatch",
                            "validator.json 字节 hash 与 broker object id 不一致")
    if tree_hash(scan_tree(object_dir)) != ref["sealed_tree_hash"]:
        raise ContractError("approval_bundle_tree_hash_mismatch",
                            "approval bundle sealed tree hash 不一致")
    receipts = Path(receipt_root)
    _require_directory(receipts, owner_uid=root_uid, group_gid=receipt_group_gid,
                       mode=0o750)
    receipt_raw = _read_exact_file(
        receipts / f"{ref['broker_receipt_id']}.json", owner_uid=root_uid,
        group_gid=receipt_group_gid, mode=0o440, maximum=65536)
    receipt = _unique_json(receipt_raw)
    if receipt_raw != canonical_json(receipt) + b"\n":
        raise ContractError("approval_receipt_noncanonical",
                            "broker approval receipt 不是 canonical JSON bytes")
    receipt_fields = {"receipt_id", "operation", "nonce", "object_id", "tree_hash",
                      "sealed_tree_hash", "sealed_path", "created_at"}
    if set(receipt) != receipt_fields:
        raise ContractError("approval_receipt_fields", "broker approval receipt 字段不精确")
    require_sha(receipt["tree_hash"], "receipt.tree_hash")
    require_sha(receipt["sealed_tree_hash"], "receipt.sealed_tree_hash")
    recomputed_receipt = sha256({
        "operation": receipt["operation"], "nonce": receipt["nonce"],
        "tree_hash": receipt["tree_hash"], "object_id": receipt["object_id"],
    })
    if (receipt["receipt_id"] != ref["broker_receipt_id"]
            or recomputed_receipt != ref["broker_receipt_id"]
            or receipt["operation"] != "seal_approval_bundle"
            or receipt["object_id"] != ref["broker_object_id"]
            or receipt["sealed_tree_hash"] != ref["sealed_tree_hash"]
            or receipt["sealed_path"] != str(object_dir)):
        raise ContractError("approval_receipt_binding_invalid",
                            "broker receipt 未绑定固定 approval object/tree/path")
    document = _unique_json(raw)
    if raw != canonical_json(document) + b"\n":
        raise ContractError("approval_validator_noncanonical",
                            "validator.json 不是 canonical JSON bytes")
    key = require_root_trust_key(Path(validator_public_key), root_uid=root_uid,
                                 root_gid=trust_root_gid)
    verified = verify_validator_document(document, validator_public_key=key)
    verify_finite_request(bundle, verified)
    return document, verified


def _source_event_id(event: dict[str, Any], identity: IdentityPolicy) -> str:
    return "EVT-" + sha256({
        "domain": "abcr.human-approval.source-event.v1",
        "app_id": identity.app_id, "tenant_key": identity.tenant_key,
        "chat_id": identity.owner_chat_id, "open_id": identity.owner_open_id,
        "event_type": event.get("event_type"),
        "event_id": event.get("event_id"), "message_id": event.get("message_id"),
    })[:40]


def _decision_nonce(event: dict[str, Any], identity: IdentityPolicy,
                    *, decision: str, request_id: str, request_version: int) -> str:
    # The raw nonce never crosses the bridge.  It is deterministic for crash replay
    # and commits every authenticated owner/event dimension plus the exact decision.
    return "NONCE-" + sha256({
        "domain": "abcr.human-approval.decision-nonce.v2",
        "decision": decision, "request_id": request_id,
        "request_version": request_version,
        "owner_open_id": identity.owner_open_id,
        "owner_chat_id": identity.owner_chat_id,
        "tenant_key": identity.tenant_key, "app_id": identity.app_id,
        "event_type": event.get("event_type"),
        "event_id": event.get("event_id"), "message_id": event.get("message_id"),
    })


def approval_context(verified: VerifiedAnchor, *, identity: IdentityPolicy,
                     event: dict[str, Any], request_version: int,
                     decision_nonce: str) -> dict[str, Any]:
    context = {
        "aud": "abcr-operator", "deployment_id": verified.deployment_id,
        "protocol_ref": verified.protocol_ref, "request_id": verified.request_id,
        "request_version": request_version,
        "source_event_id": _source_event_id(event, identity),
        "decision_nonce_hash": identity_context_hash("decision_nonce_hash", decision_nonce),
        "goal_anchor_entry_hash": verified.goal_anchor_entry_hash,
        "goal_anchor_receipt_id": verified.goal_anchor_receipt_id,
        "batch_id": verified.batch_id, "envelope_sha256": verified.envelope_sha256,
    }
    for field, value in (
        ("tenant_key_hash", identity.tenant_key),
        ("chat_id_hash", identity.owner_chat_id),
        ("app_id_hash", identity.app_id),
        ("approver_id_hash", identity.owner_open_id),
    ):
        context[field] = identity_context_hash(field, value)
    if set(context) != set(CONTEXT_FIELDS):  # defensive drift detector
        raise ContractError("approval_context_fields", "approval context 字段不精确")
    return context


def make_human_decision(
        store: ControlStore, row: dict[str, Any], *, decision: str,
        event: dict[str, Any], identity: IdentityPolicy,
        private_key: Path = HUMAN_PRIVATE_KEY,
        approval_public_key: Path = APPROVAL_PUBLIC_KEY,
        approval_root: Path = APPROVAL_BUNDLE_ROOT,
        receipt_root: Path = BROKER_RECEIPT_ROOT,
        validator_public_key: Path = VALIDATOR_PUBLIC_KEY,
        human_gid: int, receipt_group_gid: int, trust_root_gid: int = 0,
        reason: str | None = None, root_uid: int = 0) -> dict[str, Any]:
    """Create one stable Human decision; only ``approve`` creates a v2 token."""
    if decision not in {"approve", "reject"}:
        raise ContractError("approval_decision_invalid", "approval decision 不合法")
    bundle = approval_bundle_from_wire(row["bundle"])
    version = row["request_version"]
    if decision == "approve":
        document, verified = load_broker_sealed_request(
            bundle, row["reference"], approval_root=approval_root,
            receipt_root=receipt_root,
            validator_public_key=validator_public_key, root_uid=root_uid,
            human_gid=human_gid, receipt_group_gid=receipt_group_gid,
            trust_root_gid=trust_root_gid)
        nonce = _decision_nonce(event, identity, decision=decision,
                                request_id=bundle.request_id,
                                request_version=version)
        context = approval_context(verified, identity=identity, event=event,
                                   request_version=version, decision_nonce=nonce)
        require_root_trust_key(Path(approval_public_key), root_uid=root_uid,
                               root_gid=trust_root_gid)
        token = decide(
            bundle, private_key=Path(private_key), public_key=Path(approval_public_key),
            context=context, store=store, identity=identity, decision_nonce=nonce,
            validator_document=document, validator_public_key=Path(validator_public_key),
        )
        # stable_approval may return the first token after a crash/re-delivery (or a
        # later duplicate chat event). Reconstruct the exported snapshot from that
        # signed token, never from the newer caller event, so replay stays verifiable.
        signed_context = {field: token[field] for field in CONTEXT_FIELDS}
        stable = {"context": signed_context, "token": token, "reason": None,
                  "source_event_id": signed_context["source_event_id"],
                  "decision_nonce_hash": signed_context["decision_nonce_hash"],
                  "decided_at": token["issued_at"]}
    else:
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode("utf-8")) > 4096:
            raise ContractError("approval_reject_reason_invalid", "拒绝理由不合法")
        nonce = _decision_nonce(event, identity, decision=decision,
                                request_id=bundle.request_id,
                                request_version=version)
        source_event_id = _source_event_id(event, identity)
        stable = store.stable_approval(
            bundle.request_id, bundle.envelope_sha256, "reject",
            lambda: {"context": None, "token": None, "reason": reason.strip(),
                     "source_event_id": source_event_id,
                     "decision_nonce_hash": identity_context_hash(
                         "decision_nonce_hash", nonce),
                     "decided_at": utc_now()},
        )
    core = {
        "schema_version": 1, "kind": "approval_decision",
        "request_id": bundle.request_id, "request_version": version,
        "envelope_sha256": bundle.envelope_sha256, "decision": decision,
        **stable,
    }
    document = {**core, "decision_id": sha256(core)}
    store.mark_approval_request_decided(bundle.request_id, version,
                                        bundle.envelope_sha256, decision)
    return document


def verify_imported_decision(document: Any, *, request: dict[str, Any],
                             approval_public_key: Path = APPROVAL_PUBLIC_KEY,
                             root_uid: int = 0, trust_root_gid: int = 0,
                             verification_time: datetime | None = None) -> dict[str, Any]:
    """Operator-side mechanical verification.  This function makes no decision."""
    obj = strict_object(document, required=DECISION_FIELDS)
    core = {key: value for key, value in obj.items() if key != "decision_id"}
    if (obj["schema_version"] != 1 or obj["kind"] != "approval_decision"
            or obj["decision_id"] != sha256(core)
            or obj["request_id"] != request["request_id"]
            or obj["request_version"] != request["request_version"]
            or obj["envelope_sha256"] != request["envelope_hash"]
            or obj["decision"] not in {"approve", "reject"}):
        raise ContractError("approval_decision_binding_invalid",
                            "Human approval decision 与待批请求不一致")
    require_id(obj["source_event_id"], "source_event_id")
    require_sha(obj["decision_nonce_hash"], "decision_nonce_hash")
    if obj["decision"] == "approve":
        if not isinstance(obj["context"], dict) or not isinstance(obj["token"], dict):
            raise ContractError("approval_token_missing", "批准决定缺少签名 token")
        context = obj["context"]
        if (context.get("source_event_id") != obj["source_event_id"]
                or context.get("decision_nonce_hash") != obj["decision_nonce_hash"]
                or context.get("request_id") != request["request_id"]
                or context.get("request_version") != request["request_version"]
                or context.get("envelope_sha256") != request["envelope_hash"]
                or obj["reason"] is not None):
            raise ContractError("approval_decision_binding_invalid",
                                "decision metadata 未绑定签名 context")
        key = require_root_trust_key(Path(approval_public_key), root_uid=root_uid,
                                     root_gid=trust_root_gid)
        ok, reason = verify_token_v2(obj["token"], public_key=key,
                                     expected_context=context, now=verification_time)
        if not ok:
            raise ContractError("approval_token_invalid", "approval token v2 验签失败",
                                {"reason": reason})
    elif (obj["token"] is not None or obj["context"] is not None
          or not isinstance(obj["reason"], str) or not obj["reason"]):
        raise ContractError("reject_must_not_carry_approval_token",
                            "拒绝决定不得携带 approve token/context，且必须有理由")
    if not isinstance(obj["decided_at"], str) or not obj["decided_at"]:
        raise ContractError("approval_decision_time_invalid", "decision time 缺失")
    return obj


def find_approval_request(store: ControlStore, *, request_id: str,
                          request_version: int | None = None,
                          envelope_prefix: str | None = None) -> dict[str, Any]:
    row = store.approval_request(request_id, request_version)
    if row is None:
        raise StoreError("approval request not found")
    if (envelope_prefix is not None
            and (len(envelope_prefix) < 6
                 or not row["envelope_hash"].startswith(envelope_prefix))):
        raise StoreError("approval envelope prefix mismatch")
    return row
