from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.control.contracts import Severity
from abcr.control.health_runtime import (HealthFact, ServiceHealthSpec,
                                         ServiceObservation, run_health_cycle)
from abcr.control.health_collector import (DISPATCH_SUPERVISOR_LABEL,
                                           LaunchdStatus,
                                           collect_production_observations,
                                           production_service_specs)
from abcr.control.readmodel import build_snapshot
from abcr.control.policy import RecoveryDecision, RecoveryKind
from abcr.control.store import ControlStore, StoreError


def _observation(label: str, when: datetime, *, release: str = "REL-1",
                 ok: bool = True, code: str | None = None,
                 domain: str = "engineering") -> ServiceObservation:
    stamp = when.isoformat()
    return ServiceObservation(
        label, release, stamp,
        (HealthFact("fixed_state", "active-release", "release", True, stamp,
                    detail={"release_id": release}),
         HealthFact("broker", "work-broker", "semantic", ok, stamp,
                    code=code, fault_domain=domain,
                    detail={"probe": "fixed-work-list"})),
        reported_status="PASS")


def test_service_store_is_ordered_idempotent_and_conflict_closed(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    at = datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat()
    args = dict(label="com.abcr.panel", release_id="REL-1", status="healthy",
                semantic_ok=True, detail={"observation_id": "OBS-1"}, checked_at=at)
    assert store.upsert_service_status(**args)
    assert not store.upsert_service_status(**args)
    assert not store.upsert_service_status(**dict(args, checked_at=(
        datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat())))
    with pytest.raises(StoreError, match="conflicts"):
        store.upsert_service_status(**dict(args, status="blocked"))


def test_self_reported_pass_is_blocked_without_independent_evidence(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc); stamp = now.isoformat()
    observation = ServiceObservation(
        "com.abcr.panel", "REL-1", stamp,
        (HealthFact("self_report", "panel", "release", True, stamp,
                    detail={"release_id": "REL-1"}),
         HealthFact("self_report", "panel-doctor", "semantic", True, stamp)),
        reported_status="PASS")
    report = run_health_cycle(
        store, [observation], {observation.label: ServiceHealthSpec(observation.label)},
        rollback_release="REL-0", now=now)
    assert report.services[0].status == "blocked"
    assert not report.services[0].semantic_ok
    assert store.rows("missions") == []
    assert store.rows("incidents")[0]["state"] == "needs_human"


def test_independent_facts_write_healthy_and_readmodel_turns_stale(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    observation = _observation("com.abcr.panel", now)
    report = run_health_cycle(
        store, [observation], {observation.label: ServiceHealthSpec(observation.label)},
        rollback_release="REL-0", now=now)
    assert report.writes == 1 and report.services[0].status == "healthy"
    fresh = build_snapshot(store, max_age_seconds=120, now=now)
    assert fresh.sections["服务健康"][0]["freshness"] == "FRESH"
    assert fresh.severity == Severity.INFO
    stale = build_snapshot(store, max_age_seconds=120,
                           now=now + timedelta(seconds=121))
    assert stale.sections["服务健康"][0]["status"] == "stale"
    assert stale.sections["服务健康"][0]["reported_status"] == "healthy"
    assert stale.severity == Severity.ATTENTION


def test_known_reversible_fault_is_bounded_across_fresh_observations(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    label = "com.abcr.panel"
    spec = ServiceHealthSpec(label, reversible_codes=frozenset({"process_dead"}))
    calls = []
    start = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    last = None
    for offset in range(4):
        now = start + timedelta(seconds=offset)
        last = run_health_cycle(
            store, [_observation(label, now, ok=False, code="process_dead")],
            {label: spec}, rollback_release="REL-0", now=now,
            recovery_handlers={"resume_same_release": calls.append})
    assert len(calls) == 3
    assert [request.attempt for request in calls] == [1, 2, 3]
    assert last is not None and last.services[0].status == "needs_human"
    detail = json.loads(store.rows("services")[0]["detail_json"])
    assert detail["recovery_attempts"] == 3


def test_unknown_engineering_fault_queues_one_complete_mission(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    label = "com.abcr.panel"
    observation = _observation(label, now, ok=False, code="brand_new_error")
    spec = ServiceHealthSpec(
        label, mission_allowed_paths=("src/abcr/control/cards.py",),
        acceptance_profile="status-card-v1", declared_risk="normal")
    first = run_health_cycle(store, [observation], {label: spec},
                             rollback_release="REL-0", now=now)
    second = run_health_cycle(store, [observation], {label: spec},
                              rollback_release="REL-0", now=now)
    assert first.services[0].status == "mission_queued"
    assert first.missions and second.services[0].changed is False
    rows = store.rows("missions"); assert len(rows) == 1 and rows[0]["state"] == "queued"
    payload = json.loads(rows[0]["payload_json"])
    assert set(payload) == {"objective", "non_goals", "incident_evidence",
                            "base_release", "allowed_paths", "acceptance_profile",
                            "declared_risk", "rollback_release"}
    assert payload["incident_evidence"]["observation_id"] == observation.observation_id

    no_rollback = ControlStore(tmp_path / "no-rollback.db")
    blocked = run_health_cycle(no_rollback, [observation], {label: spec},
                               rollback_release="REL-1", now=now)
    assert blocked.services[0].status == "needs_human"
    assert no_rollback.rows("missions") == []


@pytest.mark.parametrize(("code", "domain", "expected"), [
    ("unexpected_scientific_result", "scientific", "needs_human"),
    ("new_tcb_fault", "tcb", "needs_human"),
    ("novel_integrity_code", "integrity", "quarantined"),
])
def test_scientific_and_tcb_faults_never_auto_fix(tmp_path, code, domain, expected):
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc); label = "com.abcr.panel"
    called = []
    report = run_health_cycle(
        store, [_observation(label, now, ok=False, code=code, domain=domain)],
        {label: ServiceHealthSpec(label)}, rollback_release="REL-0", now=now,
        recovery_handlers={"resume_same_release": called.append,
                           "create_mission": called.append})
    assert report.services[0].status == expected
    assert not called and store.rows("missions") == []


def test_runtime_domain_gate_overrides_an_unsafe_custom_policy(tmp_path):
    class AlwaysMission:
        def classify(self, signal):
            return RecoveryDecision(RecoveryKind.CREATE_MISSION, "unsafe", 1)

    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc); label = "com.abcr.panel"
    spec = ServiceHealthSpec(label,
                             mission_allowed_paths=("src/abcr/control/cards.py",))
    report = run_health_cycle(
        store, [_observation(label, now, ok=False, code="novel_science",
                             domain="scientific")],
        {label: spec}, rollback_release="REL-0", now=now,
        policy=AlwaysMission())
    assert report.services[0].status == "needs_human"
    assert store.rows("missions") == []


def test_production_collector_covers_frozen_topology_and_supervisor(tmp_path):
    class Broker:
        def __init__(self): self.stages = []
        def completed(self, stage): self.stages.append(stage); return []

    def launchd(label):
        on_demand = label not in {"com.abcr.human-gateway",
                                  "com.abcr.operator-reconciler",
                                  "com.abcr.panel", "com.abcr.seal-broker"}
        return LaunchdStatus(True, not on_demand, None,
                             {"state": "waiting" if on_demand else "running"})

    store = ControlStore(tmp_path / "control.db"); broker = Broker()
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)
    observations = collect_production_observations(
        store, broker, active_release_id="REL-1", launcher_release_id="REL-1",
        supervisor_qualified=True, supervisor_alive=True, now=now,
        launchd_probe=launchd)
    topology = json.loads((Path(__file__).parents[2] /
                           "configs/control/service-topology-v1.json").read_text())
    expected = {item["label"] for item in topology["services"]}
    assert {item.label for item in observations} == expected | {DISPATCH_SUPERVISOR_LABEL}
    assert len(observations) == 13 and len(broker.stages) == 9
    report = run_health_cycle(store, observations, production_service_specs(),
                              rollback_release="REL-0", now=now)
    statuses = {item.label: item.status for item in report.services}
    assert statuses["com.abcr.probe-worker"] == "idle"
    assert statuses["com.abcr.panel"] == "healthy"
    assert statuses[DISPATCH_SUPERVISOR_LABEL] == "healthy"


def test_unqualified_supervisor_is_blocked_from_handler_and_mission(tmp_path):
    class Broker:
        def completed(self, stage): return []
    running = lambda label: LaunchdStatus(True, True, None, {"state": "running"})
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc); called = []
    observations = collect_production_observations(
        store, Broker(), active_release_id="REL-1", launcher_release_id="REL-1",
        supervisor_qualified=False, supervisor_alive=False, now=now,
        launchd_probe=running)
    report = run_health_cycle(
        store, observations, production_service_specs(), rollback_release="REL-0",
        now=now, recovery_handlers={"resume_same_release": called.append,
                                    "create_mission": called.append})
    result = next(item for item in report.services
                  if item.label == DISPATCH_SUPERVISOR_LABEL)
    assert result.status == "needs_human"
    assert not called
    assert all(json.loads(row["payload_json"])["incident_evidence"]["service_label"]
               != DISPATCH_SUPERVISOR_LABEL for row in store.rows("missions"))


def test_integrity_release_disagreement_quarantines_without_action(tmp_path):
    store = ControlStore(tmp_path / "control.db")
    now = datetime(2026, 7, 21, 12, tzinfo=timezone.utc); stamp = now.isoformat()
    observation = ServiceObservation(
        "com.abcr.panel", "REL-1", stamp,
        (HealthFact("fixed_state", "active-release", "release", True, stamp,
                    detail={"release_id": "REL-EVIL"}),
         HealthFact("broker", "work-broker", "semantic", True, stamp)))
    report = run_health_cycle(
        store, [observation], {observation.label: ServiceHealthSpec(observation.label)},
        rollback_release="REL-0", now=now,
        recovery_handlers={"quarantine": lambda value: pytest.fail(str(value))})
    assert report.services[0].status == "quarantined"
    assert store.rows("incidents")[0]["state"] == "quarantined"
    assert store.rows("missions") == []
