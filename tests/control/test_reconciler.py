from __future__ import annotations

from abcr.control.policy import RecoveryKind, RecoveryPolicy, effective_mission_risk
from abcr.control.reconciler import Reconciler
from abcr.control.store import ControlStore


def test_policy_integrity_quarantines_unknown_missions():
    policy = RecoveryPolicy()
    assert policy.classify({"code": "split_mismatch"}).kind == RecoveryKind.QUARANTINE
    assert policy.classify({"code": "brand_new_error"}).kind == RecoveryKind.CREATE_MISSION
    assert policy.classify({"code": "unexpected_scientific_result"}).kind == RecoveryKind.NEEDS_HUMAN


def test_reconciler_action_is_idempotent(tmp_path):
    store = ControlStore(tmp_path / "control.db"); reconciler = Reconciler(store)
    signal = {"subject_id": "run1", "code": "process_dead", "release_id": "R1"}
    action = reconciler.observe(signal); assert action
    seen = []
    assert reconciler.apply(action, {"resume_same_release": lambda payload: seen.append(payload)})
    assert reconciler.observe(signal) is not None  # resolved recurrence is a new incident
    assert seen[0]["release_id"] == "R1"


def test_reconciler_resumes_same_effect_after_crash_window(tmp_path):
    store = ControlStore(tmp_path / "control.db"); reconciler = Reconciler(store)
    signal = {"subject_id": "run2", "code": "process_dead", "release_id": "R2"}
    action = reconciler.observe(signal); assert action
    # Simulate crash after detected->recovering but before the idempotent handler.
    assert store.update_incident(action.incident_id, "detected", "recovering", increment_action=True)
    recovered = Reconciler(ControlStore(tmp_path / "control.db")).observe(signal)
    assert recovered and recovered.action_id == action.action_id
    seen = []
    assert reconciler.apply(recovered, {"resume_same_release": lambda payload: seen.append(payload)})
    assert seen and seen[0]["release_id"] == "R2"


def test_path_risk_uses_real_changes_and_oracle_coverage():
    registry = {"src/abcr/util/**": {"auto_release_eligible": True,
                                     "required_external_oracle_ids": ["util-smoke"]}}
    assert effective_mission_risk("normal", ["src/abcr/util/x.py"], registry)[0] == "normal"
    assert effective_mission_risk("normal", ["src/abcr/explore/goal.py"], registry)[0] == "human_required"
    assert effective_mission_risk("normal", ["src/abcr/unknown.py"], registry)[0] == "human_required"
