"""Trusted service observations and bounded production recovery input.

The module intentionally does not inspect launchd, install software, or mutate
approval/supervisor state.  Operator supplies facts from its fixed broker/state
probes; this layer derives health without trusting a service's own PASS, journals
the result, and connects engineering incidents to the existing mission queue.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from abcr.control.contracts import ContractError, require_id, sha256
from abcr.control.mission_store import MissionQueue, MissionSpec
from abcr.control.policy import (TCB_GLOBS, RecoveryDecision, RecoveryKind,
                                 RecoveryPolicy, normalize_changed_path)
from abcr.control.reconciler import Reconciler, RecoveryAction
from abcr.control.store import ControlStore, StoreError

TRUSTED_FACT_KINDS = frozenset({"broker", "fixed_state"})
FACT_KINDS = TRUSTED_FACT_KINDS | frozenset({"self_report"})
FACT_CLAIMS = frozenset({"release", "semantic"})
FAULT_DOMAINS = frozenset({"engineering", "scientific", "tcb", "integrity"})


def _utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("health_time_invalid", f"{field_name} 不是 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise ContractError("health_time_naive", f"{field_name} 必须含时区")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class HealthFact:
    """One probe fact.  ``self_report`` is display-only and never proves PASS."""

    source_kind: str
    source_id: str
    claim: str
    ok: bool
    observed_at: str
    code: str | None = None
    fault_domain: str = "engineering"
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_kind not in FACT_KINDS or self.claim not in FACT_CLAIMS:
            raise ContractError("health_fact_kind", "健康事实来源或 claim 未登记")
        require_id(self.source_id, "health_source_id")
        if type(self.ok) is not bool or not isinstance(self.detail, dict):
            raise ContractError("health_fact_shape", "健康事实字段不合法")
        _utc(self.observed_at, "observed_at")
        if self.code is not None:
            require_id(self.code, "health_fault_code")
        if self.fault_domain not in FAULT_DOMAINS:
            raise ContractError("health_fault_domain", "健康事实 fault_domain 未登记")

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["observed_at"] = _utc(self.observed_at, "observed_at").isoformat(
            timespec="microseconds")
        return out


@dataclass(frozen=True)
class ServiceObservation:
    label: str
    release_id: str
    checked_at: str
    facts: tuple[HealthFact, ...]
    reported_status: str | None = None

    def __post_init__(self) -> None:
        require_id(self.label, "service_label")
        require_id(self.release_id, "release_id")
        checked = _utc(self.checked_at, "checked_at")
        if not self.facts:
            raise ContractError("health_facts_missing", "服务观察缺少事实")
        identities: set[tuple[str, str, str]] = set()
        for fact in self.facts:
            identity = (fact.source_kind, fact.source_id, fact.claim)
            if identity in identities:
                raise ContractError("health_fact_duplicate", "同一健康事实重复")
            identities.add(identity)
            if _utc(fact.observed_at, "observed_at") > checked:
                raise ContractError("health_fact_from_future", "健康事实晚于检查时间")
        if self.reported_status is not None and not isinstance(self.reported_status, str):
            raise ContractError("health_reported_status", "服务自报状态不合法")

    @property
    def observation_id(self) -> str:
        return "OBS-" + sha256(self.as_dict())[:20]

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "release_id": self.release_id,
                "checked_at": _utc(self.checked_at, "checked_at").isoformat(
                    timespec="microseconds"),
                "facts": [fact.as_dict() for fact in self.facts],
                "reported_status": self.reported_status}


@dataclass(frozen=True)
class ServiceHealthSpec:
    """Trusted, fixed policy for one service; never supplied by that service."""

    label: str
    tcb: bool = False
    reversible_codes: frozenset[str] = frozenset()
    mission_allowed_paths: tuple[str, ...] = ()
    acceptance_profile: str = "service-health-v1"
    declared_risk: str = "guarded"
    mission_non_goals: tuple[str, ...] = (
        "Do not change scientific goals, metrics, evidence, approvals, or TCB.",)

    def __post_init__(self) -> None:
        require_id(self.label, "service_label")
        if self.declared_risk not in {"normal", "guarded"}:
            raise ContractError("health_mission_risk", "自动健康 mission risk 不合法")
        require_id(self.acceptance_profile, "acceptance_profile")
        for code in self.reversible_codes:
            require_id(code, "reversible_code")
        normalized = tuple(normalize_changed_path(path)
                           for path in self.mission_allowed_paths)
        if any(any(fnmatch.fnmatch(path, glob) for glob in TCB_GLOBS)
               for path in normalized):
            raise ContractError("health_mission_tcb_path", "健康 mission 不得授权 TCB 路径")
        if normalized != self.mission_allowed_paths:
            raise ContractError("health_mission_path", "健康 mission path 必须规范化")
        if self.tcb and (self.mission_allowed_paths or self.reversible_codes):
            raise ContractError("health_tcb_auto_recovery", "TCB 服务不得自动恢复")


@dataclass(frozen=True)
class RecoveryRequest:
    action_id: str
    service_label: str
    release_id: str
    code: str
    attempt: int
    observation_id: str
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ServiceCycleResult:
    label: str
    status: str
    semantic_ok: bool
    observation_id: str
    changed: bool
    incident_id: str | None = None
    action_id: str | None = None
    mission_id: str | None = None


@dataclass(frozen=True)
class HealthCycleReport:
    services: tuple[ServiceCycleResult, ...]

    @property
    def writes(self) -> int:
        return sum(int(item.changed) for item in self.services)

    @property
    def missions(self) -> tuple[str, ...]:
        return tuple(item.mission_id for item in self.services if item.mission_id)


@dataclass(frozen=True)
class _Evaluation:
    status: str
    semantic_ok: bool
    code: str | None
    fault_domain: str
    reason: str


def _evaluate(observation: ServiceObservation, *, now: datetime,
              max_age_seconds: int) -> _Evaluation:
    checked = _utc(observation.checked_at, "checked_at")
    if checked > now or (now - checked).total_seconds() > max_age_seconds:
        return _Evaluation("stale", False, None, "engineering",
                           "service observation is stale")

    trusted = [fact for fact in observation.facts
               if fact.source_kind in TRUSTED_FACT_KINDS]
    release_facts = [fact for fact in trusted if fact.claim == "release"]
    semantic_facts = [fact for fact in trusted if fact.claim == "semantic"]
    if any((now - _utc(fact.observed_at, "observed_at")).total_seconds()
           > max_age_seconds for fact in release_facts + semantic_facts):
        return _Evaluation("stale", False, None, "engineering",
                           "required health fact is stale")
    release_sources = {(fact.source_kind, fact.source_id) for fact in release_facts}
    semantic_sources = {(fact.source_kind, fact.source_id) for fact in semantic_facts}
    independent = any(left != right for left in release_sources for right in semantic_sources)
    if not release_facts or not semantic_facts or not independent:
        return _Evaluation("blocked", False, "untrusted_health_evidence", "tcb",
                           "health requires independent fixed release and broker/state facts")

    releases = {fact.detail.get("release_id") for fact in release_facts if fact.ok}
    if (any(not fact.ok for fact in release_facts)
            or releases != {observation.release_id}):
        return _Evaluation("quarantined", False, "release_identity_mismatch", "integrity",
                           "fixed release evidence disagrees with observation")

    failed = [fact for fact in semantic_facts if not fact.ok]
    if not failed:
        status = "idle" if any(fact.detail.get("idle") is True
                               for fact in semantic_facts) else "healthy"
        return _Evaluation(status, True, None, "engineering",
                           "independent semantic and release facts agree")
    codes = {fact.code or "semantic_probe_failed" for fact in failed}
    domains = {fact.fault_domain for fact in failed}
    domain = ("integrity" if "integrity" in domains else
              "tcb" if "tcb" in domains else
              "scientific" if "scientific" in domains else "engineering")
    code = ("semantic_evidence_conflict" if len(domains) > 1 else sorted(codes)[0])
    return _Evaluation("blocked", False, code, domain,
                       "independent semantic probe reported failure")


def _prior_detail(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    try:
        value = json.loads(row["detail_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _incident(store: ControlStore, incident_id: str) -> dict[str, Any] | None:
    return next((row for row in store.rows("incidents")
                 if row["incident_id"] == incident_id), None)


def _terminal_without_action(store: ControlStore, action: RecoveryAction,
                             state: str) -> None:
    row = _incident(store, action.incident_id)
    if row is None or row["state"] == state:
        return
    if row["state"] in {"detected", "recovering"}:
        store.update_incident(action.incident_id, row["state"], state)


def _mission_for(observation: ServiceObservation, spec: ServiceHealthSpec,
                 evaluation: _Evaluation, *, rollback_release: str,
                 incident_id: str) -> MissionSpec:
    if spec.tcb or not spec.mission_allowed_paths:
        raise StoreError("service has no autonomous engineering repair surface")
    if rollback_release == observation.release_id:
        raise StoreError("service mission lacks a distinct known-good rollback release")
    evidence = {"incident_id": incident_id, "service_label": observation.label,
                "observation_id": observation.observation_id,
                "release_id": observation.release_id, "fault_code": evaluation.code,
                "fault_domain": evaluation.fault_domain,
                "health_facts": [fact.as_dict() for fact in observation.facts]}
    return MissionSpec(
        objective=(f"Restore independently observed semantic health for "
                   f"{observation.label}; fault={evaluation.code}."),
        non_goals=spec.mission_non_goals,
        incident_evidence=evidence,
        base_release=observation.release_id,
        allowed_paths=spec.mission_allowed_paths,
        acceptance_profile=spec.acceptance_profile,
        declared_risk=spec.declared_risk,
        rollback_release=rollback_release,
    )


def run_health_cycle(
        store: ControlStore, observations: Sequence[ServiceObservation],
        service_specs: Mapping[str, ServiceHealthSpec], *, rollback_release: str,
        recovery_handlers: Mapping[str, Callable[[RecoveryRequest], Any]] | None = None,
        policy: RecoveryPolicy | None = None, max_age_seconds: int = 120,
        now: datetime | None = None) -> HealthCycleReport:
    """Evaluate and journal one Operator health cycle.

    Recovery handlers are an explicit allow-list and must be idempotent on
    ``RecoveryRequest.action_id``.  Missing handlers fail to human intervention;
    scientific/TCB/integrity domains never reach a handler or mission builder.
    """
    require_id(rollback_release, "rollback_release")
    if max_age_seconds < 1:
        raise ContractError("health_max_age", "max_age_seconds 必须为正数")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    recovery_handlers = recovery_handlers or {}
    labels = [observation.label for observation in observations]
    if len(labels) != len(set(labels)):
        raise ContractError("health_service_duplicate", "同一周期服务观察重复")
    existing = {row["label"]: row for row in store.rows("services")}
    reconciler = Reconciler(store, policy or RecoveryPolicy())
    queue = MissionQueue(store)
    results: list[ServiceCycleResult] = []

    for observation in observations:
        spec = service_specs.get(observation.label)
        if spec is None or spec.label != observation.label:
            raise ContractError("health_service_unregistered", "服务健康策略未登记")
        evaluation = _evaluate(observation, now=current,
                               max_age_seconds=max_age_seconds)
        prior = existing.get(observation.label)
        prior_detail = _prior_detail(prior)
        if prior_detail.get("observation_id") == observation.observation_id:
            results.append(ServiceCycleResult(
                observation.label, prior["status"], bool(prior["semantic_ok"]),
                observation.observation_id, False,
                prior_detail.get("incident_id"), prior_detail.get("action_id"),
                prior_detail.get("mission_id")))
            continue
        if prior is not None:
            incoming_at = _utc(observation.checked_at, "checked_at")
            prior_at = _utc(prior["checked_at"], "stored_checked_at")
            if incoming_at < prior_at:
                results.append(ServiceCycleResult(
                    observation.label, prior["status"], bool(prior["semantic_ok"]),
                    observation.observation_id, False,
                    prior_detail.get("incident_id"), prior_detail.get("action_id"),
                    prior_detail.get("mission_id")))
                continue
            if incoming_at == prior_at:
                raise StoreError("service observation conflicts at checked_at")

        fault_fingerprint = (None if evaluation.code is None else sha256({
            "label": observation.label, "release_id": observation.release_id,
            "code": evaluation.code, "domain": evaluation.fault_domain}))
        status = evaluation.status
        incident_id: str | None = None
        action_id: str | None = None
        mission_id: str | None = None
        attempts = (int(prior_detail.get("recovery_attempts", 0))
                    if prior_detail.get("fault_fingerprint") == fault_fingerprint else 0)

        # A terminal decision remains authoritative for the same continuous fault.
        if (fault_fingerprint and prior_detail.get("fault_fingerprint") == fault_fingerprint
                and prior and prior["status"] in
                {"mission_queued", "needs_human", "quarantined"}):
            status = prior["status"]
            incident_id = prior_detail.get("incident_id")
            mission_id = prior_detail.get("mission_id")
        elif evaluation.code is not None:
            signal = {"subject_id": observation.label, "code": evaluation.code,
                      "fault_domain": evaluation.fault_domain,
                      "release_id": observation.release_id,
                      "healthy": False, "observation_id": observation.observation_id,
                      "evidence": [fact.as_dict() for fact in observation.facts]}
            decision = reconciler.policy.classify(signal)
            # This boundary is deliberately duplicated from RecoveryPolicy.  Even
            # an injected/custom policy cannot route non-engineering evidence into
            # a handler or mission.
            if evaluation.fault_domain == "integrity":
                decision = RecoveryDecision(RecoveryKind.QUARANTINE,
                                            evaluation.code, 0)
            elif evaluation.fault_domain in {"scientific", "tcb"}:
                decision = RecoveryDecision(RecoveryKind.NEEDS_HUMAN,
                                            evaluation.code, 0)
            action = reconciler.observe(signal)
            if action is not None:
                incident_id = action.incident_id; action_id = action.action_id
                if decision.kind == RecoveryKind.QUARANTINE:
                    _terminal_without_action(store, action, "quarantined")
                    status = "quarantined"
                elif decision.kind == RecoveryKind.NEEDS_HUMAN:
                    _terminal_without_action(store, action, "needs_human")
                    status = ("blocked" if evaluation.code ==
                              "untrusted_health_evidence" else "needs_human")
                elif decision.kind == RecoveryKind.CREATE_MISSION:
                    try:
                        mission = _mission_for(observation, spec, evaluation,
                                               rollback_release=rollback_release,
                                               incident_id=action.incident_id)
                    except (ContractError, StoreError):
                        _terminal_without_action(store, action, "needs_human")
                        status = "needs_human"
                    else:
                        mission_id = mission.mission_id
                        ok = reconciler.apply(
                            action, {RecoveryKind.CREATE_MISSION.value:
                                     lambda _payload, value=mission: queue.submit(value)})
                        status = "mission_queued" if ok else "needs_human"
                else:
                    handler = recovery_handlers.get(decision.kind.value)
                    if (evaluation.code not in spec.reversible_codes or handler is None
                            or attempts >= decision.max_attempts):
                        _terminal_without_action(store, action, "needs_human")
                        status = "needs_human"
                    else:
                        request = RecoveryRequest(
                            action.action_id, observation.label,
                            observation.release_id, evaluation.code, attempts + 1,
                            observation.observation_id,
                            tuple(fact.as_dict() for fact in observation.facts))
                        ok = reconciler.apply(
                            action, {decision.kind.value:
                                     lambda _payload, value=request: handler(value)})
                        attempts += 1
                        state = (_incident(store, action.incident_id) or {}).get("state")
                        status = "recovering" if ok or state == "detected" else "needs_human"
            else:
                # Reconcile a crash/replay against the durable incident terminal.
                reason = decision.reason_code
                fingerprint = sha256({"subject": observation.label, "code": reason,
                                      "release_id": observation.release_id,
                                      "observation_id": observation.observation_id})
                rows = [row for row in store.rows("incidents")
                        if row["fingerprint"] == fingerprint]
                if rows:
                    row = sorted(rows, key=lambda item: item["updated_at"])[-1]
                    incident_id = row["incident_id"]
                    status = {"resolved": "recovering"}.get(row["state"], row["state"])

        detail = {"schema_version": 1,
                  "observer": "abcr-operator",
                  "observation_id": observation.observation_id,
                  "evaluation_reason": evaluation.reason,
                  "reported_status": observation.reported_status,
                  "fault_code": evaluation.code,
                  "fault_domain": evaluation.fault_domain,
                  "fault_fingerprint": fault_fingerprint,
                  "recovery_attempts": attempts,
                  "incident_id": incident_id,
                  "action_id": action_id,
                  "mission_id": mission_id,
                  "facts": [fact.as_dict() for fact in observation.facts]}
        changed = store.upsert_service_status(
            label=observation.label, release_id=observation.release_id,
            status=status, semantic_ok=(status in {"healthy", "idle"}), detail=detail,
            checked_at=observation.checked_at)
        results.append(ServiceCycleResult(
            observation.label, status, status in {"healthy", "idle"},
            observation.observation_id, changed, incident_id, action_id, mission_id))
    return HealthCycleReport(tuple(results))
