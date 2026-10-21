from __future__ import annotations

import os
import threading

import pytest

from abcr.control.contracts import ContractError
from abcr.explore.memory import ResearchMemory


def test_concurrent_append_is_serialized_into_one_valid_chain(tmp_path):
    memory = ResearchMemory(tmp_path / "research.jsonl")
    errors = []
    def append(index):
        try:
            memory.append("human_reflection", f"G-{index}", {"index": index},
                          actor_id="owner")
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=append, args=(index,)) for index in range(16)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    rows = memory.verify()
    assert len(rows) == 16
    assert {row["payload"]["index"] for row in rows} == set(range(16))


def test_symlink_and_hardlink_ledgers_are_rejected(tmp_path):
    target = tmp_path / "target.jsonl"
    memory = ResearchMemory(target)
    memory.append("proposal_imported", "G1", {}, actor_id="owner")
    symlink = tmp_path / "shadow.jsonl"; symlink.symlink_to(target)
    with pytest.raises(ContractError):
        ResearchMemory(symlink).verify()
    hardlink = tmp_path / "hard.jsonl"; os.link(target, hardlink)
    with pytest.raises(ContractError):
        ResearchMemory(hardlink).verify()


def test_writable_or_duplicate_key_ledger_fails_closed(tmp_path):
    path = tmp_path / "research.jsonl"
    memory = ResearchMemory(path)
    memory.append("proposal_imported", "G1", {}, actor_id="owner")
    path.chmod(0o666)
    with pytest.raises(ContractError):
        memory.verify()
    path.chmod(0o600)
    raw = path.read_text(encoding="utf-8").rstrip("\n")
    # Duplicate a signed top-level key; standard json.loads would silently keep one.
    path.write_text(raw[:-1] + ',"event_type":"shadow"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        memory.verify()
