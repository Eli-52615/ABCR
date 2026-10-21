"""tests/ops/test_queue —— 目录式队列：幂等入队、双 claim 竞争、settle、requeue。"""
from __future__ import annotations

import pytest

from abcr.ops import queue


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # queue/ 相对 cwd
    queue.init_dirs()


def test_enqueue_idempotent():
    queue.enqueue("r1", {"a": 1})
    queue.enqueue("r1", {"a": 1})   # 重复
    assert queue.list_state("pending") == ["r1"]


def test_double_claim_one_wins():
    queue.enqueue("r1", {"a": 1})
    first = queue.claim("r1")
    second = queue.claim("r1")      # 输家
    assert first is not None
    assert second is None
    assert queue.list_state("running") == ["r1"]
    assert queue.list_state("pending") == []


def test_settle_moves_unique():
    queue.enqueue("r1", {"a": 1})
    queue.claim("r1")
    queue.settle("r1", ok=True)
    assert queue.list_state("done") == ["r1"]
    assert queue.list_state("running") == []
    assert queue.list_state("failed") == []


def test_requeue_cycle():
    queue.enqueue("r1", {"a": 1})
    queue.claim("r1")
    queue.settle("r1", ok=False)
    assert queue.list_state("failed") == ["r1"]
    queue.requeue("r1")
    assert queue.list_state("pending") == ["r1"]
    assert queue.list_state("failed") == []


def test_read_payload_roundtrip():
    queue.enqueue("r1", {"a": 1, "b": "x"})
    assert queue.read_payload("r1", "pending") == {"a": 1, "b": "x"}
