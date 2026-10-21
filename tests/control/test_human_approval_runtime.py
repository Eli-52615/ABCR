from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from abcr.control import bridge
from abcr.control.attestation import (DOMAIN_APPROVAL_BUNDLE_VALIDATED,
                                      sign_attestation)
from abcr.control.bridge import HumanBridge, OperatorBridge
from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.ed25519 import ApprovalRequestBundle, VerifiedAnchor, generate_keypair
from abcr.control.human_approval import (approval_reference,
                                         load_broker_sealed_request)
from abcr.control.human_gateway import HumanGateway
from abcr.control.identity import IdentityPolicy
from abcr.control.store import ControlStore
from abcr.control.validated_approval_bundle import SCHEMA
from abcr.control.worktree import scan_tree, tree_hash


def _sealed_world(tmp_path: Path):
    uid, gid = os.getuid(), os.getgid()
    validator_private = tmp_path / "validator.pem"
    validator_public = tmp_path / "validator.pub"
    generate_keypair(validator_private, validator_public)
    validator_public.chmod(0o444)

    goal = b"goal: finite human approval\n"
    goal_hash = sha256(goal)
    commit = "a" * 40
    envelope = {
        "batch_id": "EXP-approval-1", "goal_hash": goal_hash,
        "research_commit": commit, "goal_receipt_id": "receipt-1",
        "deployment_id": "abcr-w1", "protocol_ref": "protocol-v1",
    }
    envelope_hash = sha256(envelope)
    verified = VerifiedAnchor(
        goal_anchor_entry_hash="b" * 64,
        goal_anchor_receipt_id="receipt-1", research_commit=commit,
        goal_sha256=goal_hash, request_id="EXP-approval-1",
        batch_id="EXP-approval-1", envelope_sha256=envelope_hash,
        deployment_id="abcr-w1", protocol_ref="protocol-v1",
    )
    core = {"schema": SCHEMA, **verified.__dict__}
    document = {
        "validated_core": core,
        "validator_attestation": sign_attestation(
            private_key=validator_private, public_key=validator_public,
            domain=DOMAIN_APPROVAL_BUNDLE_VALIDATED, core=core),
    }
    raw = canonical_json(document) + b"\n"
    object_id = sha256(raw)
    approval_root = tmp_path / "approval-bundles"
    object_dir = approval_root / object_id
    object_dir.mkdir(parents=True)
    (object_dir / "validator.json").write_bytes(raw)
    approval_root.chmod(0o550)
    object_dir.chmod(0o550)
    (object_dir / "validator.json").chmod(0o440)
    sealed_tree_hash = tree_hash(scan_tree(object_dir))
    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir(mode=0o750)
    receipt_core = {"operation": "seal_approval_bundle", "nonce": "approval-work-1",
                    "tree_hash": "d" * 64, "object_id": object_id}
    receipt_id = sha256(receipt_core)
    receipt = {"receipt_id": receipt_id, **receipt_core,
               "sealed_tree_hash": sealed_tree_hash, "sealed_path": str(object_dir),
               "created_at": "2026-07-21T00:00:00+00:00"}
    receipt_path = receipt_root / f"{receipt_id}.json"
    receipt_path.write_bytes(canonical_json(receipt) + b"\n")
    receipt_path.chmod(0o440)
    reference = {"broker_receipt_id": receipt_id, "broker_object_id": object_id,
                 "sealed_tree_hash": sealed_tree_hash}
    bundle = ApprovalRequestBundle(
        verified.request_id, base64.b64encode(goal).decode(), goal_hash, commit,
        {"receipt_id": "receipt-1", "goal_hash": goal_hash,
         "research_commit": commit},
        envelope, envelope_hash, (verified.goal_anchor_entry_hash,),
    )
    return uid, gid, approval_root, receipt_root, validator_public, bundle, reference


def _bridge_root(tmp_path: Path) -> Path:
    root = tmp_path / "bridge"
    for child in ("human-to-operator", "operator-to-human", "operator-status"):
        (root / child).mkdir(parents=True)
    return root


def test_fixed_root_sealed_validator_document_is_required(tmp_path: Path) -> None:
    uid, gid, root, receipts, public, bundle, reference = _sealed_world(tmp_path)
    document, verified = load_broker_sealed_request(
        bundle, reference, approval_root=root, receipt_root=receipts,
        validator_public_key=public, root_uid=uid, human_gid=gid,
        receipt_group_gid=gid, trust_root_gid=gid)
    assert document["validated_core"]["request_id"] == bundle.request_id
    assert verified.envelope_sha256 == bundle.envelope_sha256

    (root / reference["broker_object_id"] / "validator.json").chmod(0o640)
    with pytest.raises(ContractError) as exc:
        load_broker_sealed_request(
            bundle, reference, approval_root=root, receipt_root=receipts,
            validator_public_key=public, root_uid=uid, human_gid=gid,
            receipt_group_gid=gid, trust_root_gid=gid)
    assert exc.value.code == "approval_bundle_file_unsafe"

    target = root / reference["broker_object_id"] / "validator.json"
    target.chmod(0o440)
    os.link(target, tmp_path / "outside-hardlink")
    with pytest.raises(ContractError) as exc:
        load_broker_sealed_request(
            bundle, reference, approval_root=root, receipt_root=receipts,
            validator_public_key=public, root_uid=uid, human_gid=gid,
            receipt_group_gid=gid, trust_root_gid=gid)
    assert exc.value.code == "approval_bundle_file_unsafe"


def test_operator_cannot_smuggle_validator_document_through_reference() -> None:
    with pytest.raises(ContractError):
        approval_reference({"broker_receipt_id": "a" * 64,
                            "broker_object_id": "b" * 64,
                            "sealed_tree_hash": "c" * 64,
                            "document": {"forged": True}})


def test_human_approval_round_trip_signs_and_operator_only_verifies(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uid, gid, approval_root, receipts, validator_public, bundle, reference = _sealed_world(tmp_path)
    human_private = tmp_path / "approval.pem"
    approval_public = tmp_path / "approval.pub"
    generate_keypair(human_private, approval_public)
    approval_public.chmod(0o444)
    root = _bridge_root(tmp_path)
    monkeypatch.setattr(bridge, "_require_dir", lambda *args, **kwargs: None)
    human = HumanBridge(
        human_uid=uid, operator_uid=uid, human_gid=gid, operator_gid=gid,
        root=root, approval_root=approval_root,
        receipt_root=receipts, receipt_group_gid=gid,
        validator_public_key=validator_public, trust_root_gid=gid,
        approval_root_uid=uid,
    )
    operator = OperatorBridge(
        human_uid=uid, operator_uid=uid, human_gid=gid, operator_gid=gid,
        root=root, approval_public_key=approval_public,
        trust_root_gid=gid, trust_root_uid=uid,
    )
    operator_store = ControlStore(tmp_path / "operator.db")
    human_store = ControlStore(tmp_path / "human.db")
    operator.export_approval_request(operator_store, bundle=bundle,
                                     reference=reference, request_version=2)
    assert human.import_results(human_store, "oc_owner") == 1

    identity = IdentityPolicy("ou_owner", "oc_owner", "tk_owner", "cli_abcr")
    gateway = HumanGateway(
        human_store, identity, human,
        approval_private_key=human_private, approval_public_key=approval_public,
        validator_public_key=validator_public, approval_root=approval_root,
        trust_root_gid=gid, approval_root_uid=uid,
    )
    event = {"sender_open_id": "ou_owner", "chat_id": "oc_owner",
             "tenant_key": "tk_owner", "app_id": "cli_abcr", "chat_type": "p2p",
             "sender_type": "user", "message_id": "om-approve-1",
             "event_id": "ev-approve-1", "event_type": "im.message.receive_v1",
             "text": f"批准 {bundle.request_id} {bundle.envelope_sha256[:12]} v2"}
    result = gateway.ingest(event)
    assert result.code == "approval_signed"
    decision = human_store.rows("approval_decisions")[0]
    assert decision["decision"] == "approve"
    assert operator.import_commands(operator_store) == 1
    assert operator_store.rows("approval_imports")[0]["decision"] == "approve"
    assert len(operator_store.rows("approval_claims")) == 1


def test_reject_is_durable_but_never_contains_approve_token(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uid, gid, approval_root, receipts, validator_public, bundle, reference = _sealed_world(tmp_path)
    root = _bridge_root(tmp_path)
    monkeypatch.setattr(bridge, "_require_dir", lambda *args, **kwargs: None)
    human = HumanBridge(human_uid=uid, operator_uid=uid, human_gid=gid,
                        operator_gid=gid, root=root)
    store = ControlStore(tmp_path / "human.db")
    store.save_approval_request(
        request_id=bundle.request_id, request_version=1,
        envelope_hash=bundle.envelope_sha256,
        bundle={**bundle.__dict__, "anchor_prefix_proof": list(bundle.anchor_prefix_proof)},
        reference=reference,
    )
    gateway = HumanGateway(store, IdentityPolicy("owner", "chat", "tenant", "app"), human,
                           approval_root_uid=uid, trust_root_gid=gid)
    event = {"sender_open_id": "owner", "chat_id": "chat", "tenant_key": "tenant",
             "app_id": "app", "chat_type": "p2p", "message_id": "m-reject",
             "event_id": "e-reject", "event_type": "im.message.receive_v1",
             "text": f"拒绝 {bundle.request_id} 风险说明不足"}
    assert gateway.ingest(event).code == "approval_rejected"
    path = next((root / "human-to-operator").glob("approval-decision-*.json"))
    value = __import__("json").loads(path.read_text())
    assert value["decision"] == "reject"
    assert value["token"] is None and value["context"] is None
