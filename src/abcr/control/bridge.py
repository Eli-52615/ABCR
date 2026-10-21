"""File-drop bridge between isolated human and operator trust domains.

Neither side opens the other's SQLite database.  Every object has a deterministic
name and canonical content, so a crash before/after rename or DB commit is safely
reconciled by replay.
"""
from __future__ import annotations

import json
import os
import stat
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from abcr.control.contracts import Actor, ControlCommand, canonical_json, sha256, strict_object
from abcr.control.ed25519 import ApprovalRequestBundle
from abcr.control.human_approval import (APPROVAL_BUNDLE_ROOT, APPROVAL_PUBLIC_KEY,
                                         HUMAN_PRIVATE_KEY,
                                         BROKER_RECEIPT_ROOT,
                                         VALIDATOR_PUBLIC_KEY,
                                         approval_bundle_from_wire,
                                         approval_bundle_to_wire,
                                         approval_reference,
                                         load_broker_sealed_request,
                                         verify_imported_decision)
from abcr.control.readmodel import build_snapshot
from abcr.control.store import ControlStore

BRIDGE_ROOT = Path("/Library/Application Support/ABCR-Bridge")
HUMAN_TO_OPERATOR = BRIDGE_ROOT / "human-to-operator"
OPERATOR_TO_HUMAN = BRIDGE_ROOT / "operator-to-human"
OPERATOR_STATUS = BRIDGE_ROOT / "operator-status" / "public-snapshot.json"


class BridgeError(RuntimeError): pass


def _card_value(value: Any, fallback: str = "UNKNOWN") -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return fallback
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:80] or fallback


def _approval_card(bundle: ApprovalRequestBundle, version: int) -> str:
    envelope = bundle.envelope
    arms = envelope.get("arms")
    items = envelope.get("item_ids")
    seeds = envelope.get("seeds")
    return "\n".join((
        f"有一项实验等待决定：{bundle.request_id} v{version}",
        f"目标：{_card_value(envelope.get('goal_id'))}；模板："
        f"{_card_value(envelope.get('template_id'))}",
        f"规模：{len(arms) if isinstance(arms, list) else 'UNKNOWN'} 个实验臂；"
        f"{len(items) if isinstance(items, list) else 'UNKNOWN'} 题；"
        f"{len(seeds) if isinstance(seeds, list) else 'UNKNOWN'} 个 seed",
        f"费用上限：{_card_value(envelope.get('max_cost_usd'))} USD",
        f"运行域：{_card_value(envelope.get('deployment_id'))}；协议："
        f"{_card_value(envelope.get('protocol_ref'))}",
        f"内容指纹：{bundle.envelope_sha256}",
        f"批准：批准 {bundle.request_id} {bundle.envelope_sha256[:12]} v{version}",
        f"拒绝：拒绝 {bundle.request_id} <理由>",
    ))


def _require_dir(path: Path, *, owner_uid: int, group_gid: int, mode: int) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or info.st_gid != group_gid
            or stat.S_IMODE(info.st_mode) != mode):
        raise BridgeError("bridge directory owner/group/mode mismatch")


def _atomic_write(directory: Path, name: str, value: dict[str, Any], *, reader_gid: int,
                  replace: bool = False) -> Path:
    final = directory / name
    raw = canonical_json(value) + b"\n"
    if final.exists():
        info = final.lstat()
        safe = (not final.is_symlink() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.geteuid() and info.st_gid == reader_gid
                and stat.S_IMODE(info.st_mode) == 0o640)
        if safe and final.read_bytes() == raw:
            return final
        if not replace or not safe:
            raise BridgeError("bridge replay conflicts with existing object")
    tmp = directory / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, raw); os.fchown(fd, -1, reader_gid); os.fchmod(fd, 0o640); os.fsync(fd)
        finally: os.close(fd)
        os.replace(tmp, final)
        dfd = os.open(directory, os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally: tmp.unlink(missing_ok=True)
    return final


def _read(path: Path, *, owner_uid: int) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid
                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 1024 * 1024):
            raise BridgeError("bridge object metadata unsafe")
        chunks: list[bytes] = []
        remaining = info.st_size + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk: break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b"".join(chunks)
    finally: os.close(fd)
    if len(raw) != info.st_size: raise BridgeError("bridge object changed during read")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out: raise BridgeError("duplicate bridge JSON key")
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict): raise BridgeError("bridge object is not JSON object")
    return value


class HumanBridge:
    def __init__(self, *, human_uid: int, operator_uid: int, human_gid: int,
                 operator_gid: int, root: Path | None = None,
                 approval_root: Path = APPROVAL_BUNDLE_ROOT,
                 receipt_root: Path = BROKER_RECEIPT_ROOT,
                 validator_public_key: Path = VALIDATOR_PUBLIC_KEY,
                 approval_private_key: Path = HUMAN_PRIVATE_KEY,
                 approval_public_key: Path = APPROVAL_PUBLIC_KEY,
                 trust_root_gid: int = 0, approval_root_uid: int = 0,
                 receipt_group_gid: int = 0):
        self.human_uid = human_uid; self.operator_uid = operator_uid
        self.human_gid = human_gid; self.operator_gid = operator_gid
        self.root = BRIDGE_ROOT if root is None else Path(root)
        self.approval_root = Path(approval_root)
        self.receipt_root = Path(receipt_root)
        self.validator_public_key = Path(validator_public_key)
        self.approval_private_key = Path(approval_private_key)
        self.approval_public_key = Path(approval_public_key)
        self.trust_root_gid = trust_root_gid
        self.approval_root_uid = approval_root_uid
        self.receipt_group_gid = receipt_group_gid
        self.inbound = self.root / "human-to-operator"
        self.outbound = self.root / "operator-to-human"
        _require_dir(self.root, owner_uid=0, group_gid=0, mode=0o755)
        _require_dir(self.inbound, owner_uid=human_uid, group_gid=operator_gid, mode=0o750)
        _require_dir(self.outbound, owner_uid=operator_uid, group_gid=human_gid, mode=0o750)

    def export_command(self, command: ControlCommand,
                       artifacts: list[dict[str, Any]] | None = None) -> Path:
        body = {"command_id": command.command_id, "message_id": command.message_id,
                "actor": asdict(command.actor), "intent": command.intent,
                "payload": command.payload, "received_at": command.received_at}
        envelope = {"schema_version": 1, "kind": "typed_command",
                    "effect_id": command.effect_id, "command": body,
                    "command_hash": sha256(body), "artifacts": artifacts or [],
                    "artifacts_hash": sha256(artifacts or [])}
        return _atomic_write(self.inbound, f"{command.effect_id}.json", envelope,
                             reader_gid=self.operator_gid)

    def export_approval_decision(self, document: dict[str, Any]) -> Path:
        """Export a separately journalled Human decision, never a typed command."""
        if (document.get("kind") != "approval_decision"
                or not isinstance(document.get("decision_id"), str)):
            raise BridgeError("approval decision document invalid")
        name = f"approval-decision-{document['decision_id']}.json"
        return _atomic_write(self.inbound, name, document,
                             reader_gid=self.operator_gid)

    def import_results(self, store: ControlStore, owner_chat_id: str) -> int:
        imported = 0
        for path in sorted(self.outbound.glob("*.json")):
            try:
                value = _read(path, owner_uid=self.operator_uid)
                if value.get("kind") == "approval_claim_request":
                    from abcr.control.approval_dispatch import (
                        claim_request_core, sign_claim_result)
                    core, decision_document = claim_request_core(value)
                    request = store.approval_request(core["request_id"],
                                                     core["request_version"])
                    if request is None:
                        raise BridgeError("claim request has no Human approval request")
                    decision = verify_imported_decision(
                        decision_document, request=request,
                        approval_public_key=self.approval_public_key,
                        root_uid=self.approval_root_uid,
                        trust_root_gid=self.trust_root_gid,
                        verification_time=(datetime.fromisoformat(
                            decision_document["token"]["expires_at"])
                                           - timedelta(microseconds=1)),
                    )
                    token = decision.get("token")
                    if (decision.get("decision") != "approve" or not isinstance(token, dict)
                            or token.get("token_id") != core["token_id"]
                            or token.get("batch_id") != core["batch_id"]
                            or token.get("envelope_sha256") != core["envelope_hash"]):
                        raise BridgeError("claim request is not bound to Human decision")
                    result = store.stable_dispatch_claim(
                        request=core, expires_at=token["expires_at"],
                        signer=lambda claim_core: sign_claim_result(
                            claim_core, private_key=self.approval_private_key,
                            public_key=self.approval_public_key),
                    )
                    _atomic_write(self.inbound,
                                  f"approval-claim-{core['claim_id']}.json", result,
                                  reader_gid=self.operator_gid)
                    imported += 1
                    continue
                if value.get("kind") == "approval_claim_settlement":
                    from abcr.control.approval_dispatch import sign_settlement_ack
                    required = {"schema_version", "kind", "claim_id", "effect_id",
                                "claim_receipt_hash", "dispatch_event_id", "settlement_hash"}
                    if (set(value) != required or value["schema_version"] != 1
                            or value["settlement_hash"] != sha256({key: value[key] for key in (
                                "claim_id", "effect_id", "claim_receipt_hash",
                                "dispatch_event_id")})):
                        raise BridgeError("claim settlement binding invalid")
                    store.settle_dispatch_claim(
                        value["claim_id"], receipt_hash=value["claim_receipt_hash"],
                        effect_id=value["effect_id"],
                        dispatch_event_id=value["dispatch_event_id"])
                    claim = store.dispatch_claim(value["claim_id"])
                    if claim is None:
                        raise BridgeError("settled claim disappeared")
                    ack = sign_settlement_ack(
                        claim=claim, private_key=self.approval_private_key,
                        public_key=self.approval_public_key)
                    _atomic_write(self.inbound,
                                  f"approval-claim-settled-{value['claim_id']}.json", ack,
                                  reader_gid=self.operator_gid)
                    imported += 1
                    continue
                if value.get("kind") == "approval_request_ref":
                    request = strict_object(
                        value,
                        required={"schema_version", "kind", "request", "request_hash"},
                    )
                    body = strict_object(
                        request["request"],
                        required={"request_id", "request_version", "envelope_sha256",
                                  "bundle", "reference"},
                    )
                    if (request["schema_version"] != 1
                            or request["request_hash"] != sha256(body)):
                        raise BridgeError("approval request bridge binding invalid")
                    bundle = approval_bundle_from_wire(body["bundle"])
                    reference = approval_reference(body["reference"])
                    if (body["request_id"] != bundle.request_id
                            or body["envelope_sha256"] != bundle.envelope_sha256
                            or type(body["request_version"]) is not int
                            or body["request_version"] < 1):
                        raise BridgeError("approval request identity invalid")
                    existing = store.approval_request(bundle.request_id,
                                                       body["request_version"])
                    if existing is not None:
                        # Exact DB replay needs no once-per-second OpenSSL work. The
                        # approval action itself re-opens the sealed object before
                        # signing, so later root-tree drift still fails closed.
                        store.save_approval_request(
                            request_id=bundle.request_id,
                            request_version=body["request_version"],
                            envelope_hash=bundle.envelope_sha256,
                            bundle=body["bundle"], reference=reference,
                        )
                        continue
                    # Operator supplied only an untrusted reference/display bundle.
                    # Re-open and validate the fixed root-owned object before storing
                    # or showing anything to the owner.
                    load_broker_sealed_request(
                        bundle, reference, approval_root=self.approval_root,
                        receipt_root=self.receipt_root,
                        validator_public_key=self.validator_public_key,
                        root_uid=self.approval_root_uid, human_gid=self.human_gid,
                        receipt_group_gid=self.receipt_group_gid,
                        trust_root_gid=self.trust_root_gid,
                    )
                    inserted = store.save_approval_request(
                        request_id=bundle.request_id,
                        request_version=body["request_version"],
                        envelope_hash=bundle.envelope_sha256,
                        bundle=body["bundle"], reference=reference,
                    )
                    if inserted:
                        text = _approval_card(bundle, body["request_version"])
                        reply_id = sha256({"kind": "approval_request_reply",
                                           "request_hash": request["request_hash"]})
                        store.enqueue_outbox(
                            reply_id, owner_chat_id,
                            {"type": "text", "text": text,
                             "receive_id_type": "chat_id"},
                        )
                        imported += 1
                    continue
                obj = strict_object(value, required={"schema_version", "effect_id", "state",
                                                     "result", "result_hash"})
                if obj["schema_version"] != 1 or obj["result_hash"] != sha256(obj["result"]):
                    raise BridgeError("operator result binding invalid")
                text = f"后台动作 {obj['effect_id'][:12]}：{obj['state']}"
                if isinstance(obj["result"], dict) and isinstance(obj["result"].get("code"), str):
                    text += f"（{obj['result']['code']}）"
                if (obj["state"] == "needs_clarification"
                        and isinstance(obj["result"], dict)
                        and isinstance(obj["result"].get("message"), str)):
                    # The message is deterministic Operator-authored guidance, not
                    # model output or an exception string. Keep it visible so the
                    # owner can issue the required explicit scientific selection.
                    text += "\n" + obj["result"]["message"][:1000]
                reply_id = sha256({"kind": "operator_result_reply", "effect_id": obj["effect_id"],
                                   "result_hash": obj["result_hash"]})
                imported += int(store.enqueue_outbox(reply_id, owner_chat_id,
                                                      {"type": "text", "text": text,
                                                       "receive_id_type": "chat_id"}))
            except Exception as exc:
                fingerprint = sha256({"domain": "human", "name": path.name,
                                      "error": type(exc).__name__})
                store.get_or_create_incident("INC-BRIDGE-" + fingerprint[:16], fingerprint,
                                             severity="risk",
                                             evidence={"code": "bridge_result_poison",
                                                       "name_hash": sha256(path.name.encode())})
        return imported


class OperatorBridge:
    def __init__(self, *, human_uid: int, operator_uid: int, human_gid: int,
                 operator_gid: int, root: Path | None = None,
                 approval_public_key: Path = APPROVAL_PUBLIC_KEY,
                 trust_root_gid: int = 0, trust_root_uid: int = 0):
        self.human_uid = human_uid; self.operator_uid = operator_uid
        self.human_gid = human_gid; self.operator_gid = operator_gid
        self.root = BRIDGE_ROOT if root is None else Path(root)
        self.approval_public_key = Path(approval_public_key)
        self.trust_root_gid = trust_root_gid
        self.trust_root_uid = trust_root_uid
        self.inbound = self.root / "human-to-operator"
        self.outbound = self.root / "operator-to-human"
        self.status_dir = self.root / "operator-status"
        _require_dir(self.root, owner_uid=0, group_gid=0, mode=0o755)
        _require_dir(self.inbound, owner_uid=human_uid, group_gid=operator_gid, mode=0o750)
        _require_dir(self.outbound, owner_uid=operator_uid, group_gid=human_gid, mode=0o750)
        _require_dir(self.status_dir, owner_uid=operator_uid, group_gid=human_gid, mode=0o750)

    def import_commands(self, store: ControlStore) -> int:
        imported = 0
        for path in sorted(self.inbound.glob("*.json")):
            try:
                value = _read(path, owner_uid=self.human_uid)
                signed_core = value.get("core") if isinstance(value, dict) else None
                if isinstance(signed_core, dict) and signed_core.get("kind") == "approval_claim_result":
                    from abcr.control.approval_dispatch import (
                        claim_request_core, claim_request_from_decision,
                        verify_claim_result)
                    request_id = signed_core.get("request_id")
                    request_version = signed_core.get("request_version")
                    prior = store.approval_import(request_id, request_version)
                    if prior is None:
                        raise BridgeError("claim result has no imported Human decision")
                    decision = json.loads(prior["decision_json"])
                    expected, _ = claim_request_core(claim_request_from_decision(
                        decision, approval_event_id=signed_core["approval_event_id"],
                        release_id=signed_core["release_id"]))
                    verify_claim_result(value, expected=expected, token=decision["token"],
                                        public_key=self.approval_public_key)
                    imported += int(store.import_dispatch_claim_result(value))
                    continue
                if isinstance(signed_core, dict) and signed_core.get("kind") == "approval_claim_settled_ack":
                    from abcr.control.approval_dispatch import verify_settlement_ack
                    claim_id = signed_core.get("claim_id")
                    rows = [row for row in store.rows("dispatch_claim_imports")
                            if row["claim_id"] == claim_id]
                    if len(rows) != 1:
                        raise BridgeError("settlement ack has no imported claim")
                    claim_result = json.loads(rows[0]["document_json"])
                    verify_settlement_ack(
                        value, claim_result=claim_result,
                        dispatch_event_id=signed_core["dispatch_event_id"],
                        public_key=self.approval_public_key)
                    imported += int(store.mark_dispatch_claim_settled(
                        claim_id, signed_core["dispatch_event_id"]))
                    continue
                if value.get("kind") == "approval_decision":
                    request_id = value.get("request_id")
                    request_version = value.get("request_version")
                    if not isinstance(request_id, str) or type(request_version) is not int:
                        raise BridgeError("approval decision request identity invalid")
                    prior = store.approval_import(request_id, request_version)
                    if prior is not None:
                        if (prior["decision_hash"] != sha256(value)
                                or prior["decision_json"] != canonical_json(value).decode()):
                            raise BridgeError("approval decision replay content conflict")
                        continue
                    request = store.approval_request(request_id, request_version)
                    if request is None:
                        raise BridgeError("approval decision has no operator request")
                    decision = verify_imported_decision(
                        value, request=request,
                        approval_public_key=self.approval_public_key,
                        root_uid=self.trust_root_uid,
                        trust_root_gid=self.trust_root_gid,
                    )
                    if path.name != f"approval-decision-{decision['decision_id']}.json":
                        raise BridgeError("approval decision filename binding invalid")
                    inserted = store.import_approval_decision(
                        request_id=decision["request_id"],
                        request_version=decision["request_version"],
                        envelope_hash=decision["envelope_sha256"],
                        decision=decision["decision"], document=decision,
                        token_claim=({"token_id": decision["token"]["token_id"],
                                      "batch_id": decision["token"]["batch_id"]}
                                     if decision["decision"] == "approve" else None),
                    )
                    imported += int(inserted)
                    continue
                obj = strict_object(value, required={"schema_version", "kind", "effect_id",
                                                     "command", "command_hash", "artifacts",
                                                     "artifacts_hash"})
                body = strict_object(obj["command"], required={"command_id", "message_id", "actor",
                                                               "intent", "payload", "received_at"})
                actor = Actor(**strict_object(body["actor"], required={"open_id", "tenant_key",
                                                                        "chat_id", "chat_type"}))
                command = ControlCommand(command_id=body["command_id"], message_id=body["message_id"],
                                         actor=actor, intent=body["intent"], payload=body["payload"],
                                         received_at=body["received_at"])
                if (obj["schema_version"] != 1 or obj["kind"] != "typed_command"
                        or obj["command_hash"] != sha256(body) or obj["effect_id"] != command.effect_id
                        or not isinstance(obj["artifacts"], list)
                        or obj["artifacts_hash"] != sha256(obj["artifacts"])
                        or path.name != f"{command.effect_id}.json"):
                    raise BridgeError("human command binding invalid")
                for artifact in obj["artifacts"]:
                    proposal = strict_object(artifact, required={"kind", "proposal_id", "raw_text",
                                                                 "raw_hash", "actor_id"})
                    if (proposal["kind"] != "proposal"
                            or sha256(proposal["raw_text"].encode("utf-8")) != proposal["raw_hash"]
                            or not command.payload.get("proposal_id") == proposal["proposal_id"]):
                        raise BridgeError("proposal artifact binding invalid")
                    store.save_proposal(proposal["proposal_id"], proposal["raw_text"],
                                        proposal["actor_id"])
                imported += int(store.prepare_action(effect_id=command.effect_id,
                                                      command_id=command.command_id,
                                                      intent=command.intent, payload=command.payload,
                                                      actor={"open_id": actor.open_id,
                                                             "tenant_key": actor.tenant_key,
                                                             "chat_id": actor.chat_id,
                                                             "chat_type": actor.chat_type}))
            except Exception as exc:
                fingerprint = sha256({"domain": "operator", "name": path.name,
                                      "error": type(exc).__name__})
                store.get_or_create_incident("INC-BRIDGE-" + fingerprint[:16], fingerprint,
                                             severity="risk",
                                             evidence={"code": "bridge_command_poison",
                                                       "name_hash": sha256(path.name.encode())})
        return imported

    def export_approval_request(self, store: ControlStore, *,
                                bundle: ApprovalRequestBundle | dict[str, Any],
                                reference: dict[str, Any],
                                request_version: int = 1) -> Path:
        """Export only a finite request plus opaque broker refs, never validator bytes."""
        if isinstance(bundle, ApprovalRequestBundle):
            wire = approval_bundle_to_wire(bundle)
            parsed = bundle
        else:
            wire = dict(bundle)
            parsed = approval_bundle_from_wire(wire)
        ref = approval_reference(reference)
        if type(request_version) is not int or request_version < 1:
            raise BridgeError("approval request version invalid")
        store.save_approval_request(
            request_id=parsed.request_id, request_version=request_version,
            envelope_hash=parsed.envelope_sha256, bundle=wire, reference=ref,
        )
        body = {"request_id": parsed.request_id, "request_version": request_version,
                "envelope_sha256": parsed.envelope_sha256,
                "bundle": wire, "reference": ref}
        envelope = {"schema_version": 1, "kind": "approval_request_ref",
                    "request": body, "request_hash": sha256(body)}
        name = f"approval-request-{parsed.request_id}-v{request_version}.json"
        return _atomic_write(self.outbound, name, envelope,
                             reader_gid=self.human_gid)

    def export_claim_request(self, document: dict[str, Any]) -> Path:
        if document.get("kind") != "approval_claim_request":
            raise BridgeError("claim request document invalid")
        return _atomic_write(
            self.outbound, f"approval-claim-request-{document['claim_id']}.json",
            document, reader_gid=self.human_gid)

    def export_claim_settlement(self, document: dict[str, Any]) -> Path:
        if document.get("kind") != "approval_claim_settlement":
            raise BridgeError("claim settlement document invalid")
        return _atomic_write(
            self.outbound, f"approval-claim-settlement-{document['claim_id']}.json",
            document, reader_gid=self.human_gid)

    def export_results_and_status(self, store: ControlStore) -> int:
        exported = 0
        for row in store.rows("actions"):
            if row["state"] not in {"succeeded", "failed", "needs_clarification"}:
                continue
            result = json.loads(row["result_json"])
            envelope = {"schema_version": 1, "effect_id": row["effect_id"],
                        "state": row["state"], "result": result,
                        "result_hash": sha256(result)}
            _atomic_write(self.outbound, f"{row['effect_id']}.json", envelope,
                          reader_gid=self.human_gid)
            exported += 1
        snapshot = build_snapshot(store).as_dict()
        _atomic_write(self.status_dir, "public-snapshot.json", snapshot,
                      reader_gid=self.human_gid, replace=True)
        return exported
