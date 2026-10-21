from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from abcr.control.mission_store import MissionQueue, MissionSpec
from abcr.control.store import ControlStore, StoreError


def spec(name="one"):
    return MissionSpec(name, ("do not touch evidence",), {"error": "fixture"}, "REL-0",
                       ("src/abcr/util/**",), "util-smoke", "normal", "REL-0")


def test_mission_unique_claim_fencing_and_transition(tmp_path):
    store = ControlStore(tmp_path / "control.db"); queue = MissionQueue(store)
    mid = queue.submit(spec())
    claim = queue.claim("w1"); assert claim and claim["mission_id"] == mid
    assert queue.claim("w2") is None
    assert store.heartbeat_mission(mid, "w1", claim["fencing_token"])
    assert not store.heartbeat_mission(mid, "w2", claim["fencing_token"])
    assert store.transition_mission(mid, claim["fencing_token"], "claimed", "running")
    assert store.transition_mission(mid, claim["fencing_token"], "running", "verifying")


def test_mission_dag_and_cycle_reject(tmp_path):
    store = ControlStore(tmp_path / "control.db"); queue = MissionQueue(store)
    first = queue.submit(spec("first"))
    second_spec = spec("second"); second = queue.submit(second_spec, (first,))
    assert queue.claim("w")["mission_id"] == first
    # Direct self-dependency is rejected transactionally.
    with pytest.raises(StoreError):
        store.create_mission("self", risk="normal", payload={}, base_release="r", dependencies=("self",))


def test_expired_poison_quarantines_and_ready_work_continues(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    store.create_mission("poison", risk="normal", payload={}, base_release="r", max_attempts=1)
    claim = store.claim_mission("w", lease_seconds=1); assert claim
    with store.immediate() as db:
        db.execute("UPDATE missions SET lease_until=? WHERE mission_id='poison'",
                   ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    store.create_mission("good", risk="normal", payload={}, base_release="r")
    assert store.recover_expired_missions() == (0, 1)
    assert store.claim_mission("w2")["mission_id"] == "good"
