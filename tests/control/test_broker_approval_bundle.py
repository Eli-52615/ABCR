from __future__ import annotations

import os
import subprocess

import pytest

from abcr.control.approval_agent import decide
from abcr.control.validated_approval_bundle import (broker_verify_candidate,
                                                    validator_validate_and_sign,
                                                    verify_validator_document)
from abcr.control.contracts import ContractError
from abcr.control.ed25519 import ApprovalRequestBundle, generate_keypair
from abcr.control.store import ControlStore
from abcr.explore.memory import ResearchMemory
from tests.control.test_ed25519 import (NONCE, OWNER, bound_context, keys, world)


def broker_document(tmp_path):
    repo, ledger, entry_hash, _, envelope_hash, bundle = world(tmp_path)
    seal_private, seal_public = tmp_path / "seal.key", tmp_path / "seal.pub"
    validator_private, validator_public = tmp_path / "validator.key", tmp_path / "validator.pub"
    generate_keypair(seal_private, seal_public)
    generate_keypair(validator_private, validator_public)
    seal_path = tmp_path / "research.seal.json"
    ResearchMemory(ledger).write_external_seal(
        seal_path, private_key=seal_private, public_key=seal_public)
    document = validator_validate_and_sign(
        bundle, research_repo=repo, anchor_ledger=ledger,
        anchor_ledger_owner_uid=os.getuid(), anchor_seal_path=seal_path,
        anchor_sealer_public_key=seal_public, anchor_seal_owner_uid=os.getuid(),
        validator_private_key=validator_private, validator_public_key=validator_public)
    return bundle, document, validator_public, entry_hash, envelope_hash


def test_root_wire_contains_only_finite_validated_core(tmp_path):
    bundle, document, public, _, _ = broker_document(tmp_path)
    verified = verify_validator_document(document, validator_public_key=public)
    assert verified.request_id == bundle.request_id
    assert not any("path" in key or "key" in key for key in document["validated_core"])
    assert "goal_bytes_b64" not in document["validated_core"]


def test_broker_mechanical_gate_has_no_subprocess_or_path_input(tmp_path, monkeypatch):
    bundle, document, public, _, _ = broker_document(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("root broker must not spawn subprocess")))
    candidate = broker_verify_candidate(
        document, validator_public_key_pem=public.read_bytes())
    assert candidate.validated.request_id == bundle.request_id
    assert candidate.canonical_bytes.endswith(b"\n")
    assert len(candidate.document_sha256) == 64


def test_human_decide_uses_only_validator_public_key_not_research_mounts(tmp_path):
    bundle, document, validator_public, entry_hash, envelope_hash = broker_document(tmp_path)
    human_private, human_public = keys(tmp_path)
    token = decide(
        bundle, private_key=human_private, public_key=human_public,
        context=bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]),
        store=ControlStore(tmp_path / "human.db"), identity=OWNER,
        decision_nonce=NONCE, validator_document=document,
        validator_public_key=validator_public)
    assert token["batch_id"] == bundle.envelope["batch_id"]


def test_path_injection_and_unsigned_core_mutation_are_rejected(tmp_path):
    _, document, public, _, _ = broker_document(tmp_path)
    injected = {**document, "validated_core": {
        **document["validated_core"], "research_repo_path": "/tmp/evil"}}
    with pytest.raises(ContractError):
        verify_validator_document(injected, validator_public_key=public)
    mutated = {**document, "validated_core": {
        **document["validated_core"], "deployment_id": "other"}}
    with pytest.raises(ContractError) as excinfo:
        verify_validator_document(mutated, validator_public_key=public)
    assert excinfo.value.code == "validator_approval_unverified"


def test_untrusted_request_cannot_swap_broker_validated_identity(tmp_path):
    bundle, document, validator_public, entry_hash, envelope_hash = broker_document(tmp_path)
    fields = [bundle.request_id, bundle.goal_bytes_b64, bundle.goal_sha256,
              bundle.research_commit, bundle.artifact_frozen_receipt, bundle.envelope,
              bundle.envelope_sha256, bundle.anchor_prefix_proof]
    fields[0] = "EXP-swapped"
    swapped = ApprovalRequestBundle(*fields)
    private, public = keys(tmp_path)
    with pytest.raises(ContractError) as excinfo:
        decide(swapped, private_key=private, public_key=public,
               context=bound_context(entry_hash, envelope_hash, bundle.envelope["batch_id"]),
               store=ControlStore(tmp_path / "human.db"), identity=OWNER,
               decision_nonce=NONCE, validator_document=document,
               validator_public_key=validator_public)
    assert excinfo.value.code == "validated_approval_request_mismatch"
