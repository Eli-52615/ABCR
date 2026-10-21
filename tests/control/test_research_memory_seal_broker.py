from __future__ import annotations

import os
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError
from abcr.control.ed25519 import generate_keypair
from abcr.control.research_memory_seal import (OPERATION, ResearchMemorySealConfig,
                                               refresh_research_memory_seal)
from abcr.explore.memory import ResearchMemory


def fixture(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"; ledger_dir.mkdir(mode=0o700)
    trust_dir = tmp_path / "trust"; trust_dir.mkdir(mode=0o700)
    ledger = ledger_dir / "research.jsonl"
    memory = ResearchMemory(ledger)
    memory.append("proposal_imported", "G1", {"n": 1}, actor_id="owner")
    private, public = trust_dir / "seal.key", trust_dir / "seal.pub"
    generate_keypair(private, public)
    config = ResearchMemorySealConfig(
        ledger, trust_dir / "research.seal.json", private, public,
        ledger_owner_uid=os.getuid(), trust_owner_uid=os.getuid())
    return memory, config


def request(memory: ResearchMemory, nonce: str = "nonce-1") -> dict:
    core = memory.seal_core()
    return {"nonce": nonce, "expected_length": core["length"],
            "expected_head_entry_hash": core["head_entry_hash"],
            "expected_ledger_sha256": core["ledger_sha256"]}


def test_fixed_path_refresh_and_idempotent_replay(tmp_path):
    memory, config = fixture(tmp_path)
    first = refresh_research_memory_seal(config, request(memory))
    second = refresh_research_memory_seal(config, request(memory))
    assert first == second
    assert first["operation"] == OPERATION
    assert memory.verify_external_seal(config.seal_path, public_key=config.public_key,
                                       expected_owner_uid=os.getuid()) == memory.seal_core()


def test_append_only_extension_can_advance_signed_head(tmp_path):
    memory, config = fixture(tmp_path)
    first = refresh_research_memory_seal(config, request(memory))
    memory.append("human_reflection", "G1", {"text": "next"}, actor_id="owner")
    second = refresh_research_memory_seal(config, request(memory, "nonce-2"))
    assert second["length"] == first["length"] + 1
    assert second["head_entry_hash"] != first["head_entry_hash"]


def test_full_rechain_is_not_washable_by_refresh(tmp_path):
    memory, config = fixture(tmp_path)
    refresh_research_memory_seal(config, request(memory))
    config.ledger_path.unlink()
    forged = ResearchMemory(config.ledger_path)
    forged.append("proposal_imported", "G1", {"washed": True}, actor_id="owner")
    with pytest.raises(ContractError) as excinfo:
        refresh_research_memory_seal(config, request(forged, "nonce-2"))
    assert excinfo.value.code == "research_memory_reseal_refused"


def test_request_cannot_inject_any_path_or_key(tmp_path):
    memory, config = fixture(tmp_path)
    attack = {**request(memory), "ledger_path": "/tmp/attacker.jsonl"}
    with pytest.raises(ContractError):
        refresh_research_memory_seal(config, attack)
    assert not config.seal_path.exists()


def test_private_key_permissions_fail_before_signing(tmp_path):
    memory, config = fixture(tmp_path)
    config.private_key.chmod(0o644)
    with pytest.raises(ContractError) as excinfo:
        refresh_research_memory_seal(config, request(memory))
    assert excinfo.value.code == "research_memory_seal_config"
