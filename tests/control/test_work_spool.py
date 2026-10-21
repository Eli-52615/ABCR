from __future__ import annotations

import json
import threading

import pytest

from abcr.control.work_spool import SpoolError, WorkSpool


def test_spool_atomic_claim_result_ack_and_replay(tmp_path):
    spool = WorkSpool(tmp_path / "work")
    first = spool.enqueue("probe", "W1", {"x": 1})
    assert spool.enqueue("probe", "W1", {"x": 1}) == first
    with pytest.raises(SpoolError): spool.enqueue("probe", "W1", {"x": 2})
    claims = []
    threads = [threading.Thread(target=lambda: claims.append(spool.claim("probe", "W1"))) for _ in range(8)]
    [x.start() for x in threads]; [x.join() for x in threads]
    winners = [x for x in claims if x is not None]
    assert len(winners) == 1
    claim = winners[0]
    assert spool.submit_result(claim, {"ok": True}, consumer="probe").exists()
    assert spool.ack(claim).exists()


def test_spool_poison_quarantines_without_blocking_next(tmp_path):
    spool = WorkSpool(tmp_path / "work")
    path = spool.enqueue("audit", "bad", {"x": 1})
    row = json.loads(path.read_text()); row["payload"] = {"x": 2}; path.write_text(json.dumps(row))
    with pytest.raises(SpoolError): spool.claim("audit", "bad")
    spool.enqueue("audit", "good", {"x": 3})
    assert spool.claim("audit", "good") is not None
