"""Desired-vs-actual reconciler with bounded, idempotent recovery actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from abcr.control.contracts import sha256
from abcr.control.policy import RecoveryDecision, RecoveryKind, RecoveryPolicy
from abcr.control.store import ControlStore


@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    incident_id: str
    kind: str
    reason_code: str
    payload: dict[str, Any]


class Reconciler:
    def __init__(self, store: ControlStore, policy: RecoveryPolicy | None = None):
        self.store = store
        self.policy = policy or RecoveryPolicy()

    def observe(self, signal: dict[str, Any]) -> RecoveryAction | None:
        decision = self.policy.classify(signal)
        if decision.kind == RecoveryKind.NOOP: return None
        fingerprint = sha256({"subject": signal.get("subject_id"), "code": decision.reason_code,
                              "release_id": signal.get("release_id")})
        incident_id = "INC-" + fingerprint[:20]
        incident, created = self.store.get_or_create_incident(
            incident_id, fingerprint, severity="risk" if decision.kind == RecoveryKind.QUARANTINE else "attention",
            evidence=signal,
        )
        if not created and incident["state"] not in {"detected", "recovering"}:
            return None
        action_id = "ACT-" + sha256({"incident": incident_id, "kind": decision.kind.value,
                                      "attempt": max(1, int(incident["action_count"]))})[:20]
        return RecoveryAction(action_id, incident_id, decision.kind.value, decision.reason_code,
                              {"subject_id": signal.get("subject_id"),
                               "release_id": signal.get("release_id"),
                               "max_attempts": decision.max_attempts})

    def apply(self, action: RecoveryAction, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> bool:
        rows = [row for row in self.store.rows("incidents") if row["incident_id"] == action.incident_id]
        if not rows: return False
        if rows[0]["state"] == "detected":
            if not self.store.update_incident(action.incident_id, "detected", "recovering", increment_action=True):
                return False
        elif rows[0]["state"] != "recovering":
            return False
        handler = handlers.get(action.kind)
        if handler is None:
            self.store.update_incident(action.incident_id, "recovering", "needs_human")
            return False
        try:
            handler(action.payload)
        except Exception:
            terminal = "quarantined" if action.kind == RecoveryKind.QUARANTINE.value else "needs_human"
            self.store.update_incident(action.incident_id, "recovering", terminal)
            return False
        terminal = "quarantined" if action.kind == RecoveryKind.QUARANTINE.value else (
            "mission_queued" if action.kind == RecoveryKind.CREATE_MISSION.value else "resolved")
        self.store.update_incident(action.incident_id, "recovering", terminal)
        return True
