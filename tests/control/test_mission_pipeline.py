from __future__ import annotations

from abcr.control.contracts import sha256
from abcr.control.mission_pipeline import reconcile_mission_pipeline


def _ref(operation: str, object_id: str, tree: str = "a" * 64) -> dict:
    return {"operation": operation, "receipt_id": "b" * 64,
            "object_id": object_id, "sealed_tree_hash": tree}


class _OperatorBroker:
    def __init__(self, stage: str, value: dict, *, ok: bool = True):
        self.stage = stage
        result = {"ok": ok, "result": value} if ok else {
            "ok": False, "error_code": "worker_failed"}
        self.envelope = {"schema_version": 1, "stage": stage, "work_id": "MIS-1",
                         "attempt": 2, "fencing_token": 7, "consumer": "worker",
                         "result": result, "result_hash": sha256(result),
                         "completed_at": "2026-07-21T00:00:00+00:00"}
        self.enqueues = []
        self.acks = []

    def completed_fenced(self, stage):
        return ([{"work_id": "MIS-1", "attempt": 2, "fencing_token": 7}]
                if stage == self.stage else [])

    def read_result(self, stage, work_id, *, attempt, fencing_token):
        assert (stage, work_id, attempt, fencing_token) == (self.stage, "MIS-1", 2, 7)
        return self.envelope

    def request(self, operation, arguments):
        assert operation == "work_enqueue"
        self.enqueues.append(arguments)
        return {"work_id": arguments["work_id"]}

    def acknowledge(self, stage, work_id, *, result_hash, attempt, fencing_token):
        self.acks.append((stage, work_id, result_hash, attempt, fencing_token))
        return {"acked": True}


def test_operator_advances_only_sealed_builder_result_then_acks():
    value = {"base_tree_hash": "c" * 64, "candidate_tree_hash": "a" * 64,
             "changed_paths": ["src/x.py"], "deleted_paths": [], "added_paths": [],
             "candidate_ref": _ref("seal_attestation", "CND-a"),
             "candidate_id": "MIS-1", "mission_id": "MIS-1",
             "declared_risk": "normal", "old_release": None,
             "expected_version": None}
    broker = _OperatorBroker("mission-build", value)

    events = reconcile_mission_pipeline(broker)

    assert events == [{"stage": "mission-build", "work_id": "MIS-1",
                       "disposition": "advanced", "advanced_to": "test"}]
    assert broker.enqueues[0]["producer"] == "abcr-operator"
    assert broker.enqueues[0]["stage"] == "test"
    assert set(broker.enqueues[0]["payload"]) == {
        "mission_id", "candidate_ref", "pipeline_context"}
    assert len(broker.acks) == 1


def test_operator_never_advances_failed_result_but_acks_it():
    broker = _OperatorBroker("test", {}, ok=False)

    events = reconcile_mission_pipeline(broker)

    assert events[0]["disposition"] == "failed"
    assert broker.enqueues == []
    assert len(broker.acks) == 1


def test_operator_never_advances_nonpass_sealed_canary():
    broker = _OperatorBroker("canary", {
        "mission_id": "MIS-1", "verdict": "FAIL",
        "broker_ref": _ref("seal_canary", "CNY-a")})

    events = reconcile_mission_pipeline(broker)

    assert events[0]["disposition"] == "halted"
    assert broker.enqueues == []
    assert len(broker.acks) == 1
