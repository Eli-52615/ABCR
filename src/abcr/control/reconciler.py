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
        identity = {"subject": signal.get("subject_id"), "code": decision.reason_code,
                    "release_id": signal.get("release_id")}
        if signal.get("observation_id") is not None:
            identity["observation_id"] = signal["observation_id"]
        fingerprint = sha256(identity)
        incident_id = "INC-" + fingerprint[:20]
        # Legacy callers without an observation identity cannot distinguish a
        # replay from a fresh recurrence.  Return the old action as an inert replay;
        # apply() will see the resolved row and refuse a duplicate side effect.
        if signal.get("observation_id") is None:
            resolved = [row for row in self.store.rows("incidents")
                        if row["fingerprint"] == fingerprint and row["state"] == "resolved"]
            if resolved:
                row = sorted(resolved, key=lambda item: item["updated_at"])[-1]
                attempt = max(1, int(row["action_count"]))
                action_id = "ACT-" + sha256({"incident": row["incident_id"],
                                              "kind": decision.kind.value,
                                              "attempt": attempt})[:20]
                return RecoveryAction(
                    action_id, row["incident_id"], decision.kind.value,
                    decision.reason_code,
                    {"subject_id": signal.get("subject_id"),
                     "release_id": signal.get("release_id"),
                     "max_attempts": decision.max_attempts, "attempt": attempt})
        incident, created = self.store.get_or_create_incident(
            incident_id, fingerprint, severity="risk" if decision.kind == RecoveryKind.QUARANTINE else "attention",
            evidence=signal,
        )
        # get_or_create may suffix the deterministic id when a resolved episode
        # recurs; every action must bind the actually committed incident row.
        incident_id = incident["incident_id"]
        if not created and incident["state"] not in {"detected", "recovering"}:
            return None
        attempt = (max(1, int(incident["action_count"]))
                   if incident["state"] == "recovering"
                   else int(incident["action_count"]) + 1)
        action_id = "ACT-" + sha256({"incident": incident_id, "kind": decision.kind.value,
                                      "attempt": attempt})[:20]
        return RecoveryAction(action_id, incident_id, decision.kind.value, decision.reason_code,
                              {"subject_id": signal.get("subject_id"),
                               "release_id": signal.get("release_id"),
                               "max_attempts": decision.max_attempts,
                               "attempt": attempt})

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
            rows = [row for row in self.store.rows("incidents")
                    if row["incident_id"] == action.incident_id]
            exhausted = (not rows or int(rows[0]["action_count"])
                         >= int(action.payload.get("max_attempts", 0)))
            terminal = ("quarantined" if action.kind == RecoveryKind.QUARANTINE.value
                        else "needs_human" if exhausted else "detected")
            self.store.update_incident(action.incident_id, "recovering", terminal)
            return False
        terminal = "quarantined" if action.kind == RecoveryKind.QUARANTINE.value else (
            "mission_queued" if action.kind == RecoveryKind.CREATE_MISSION.value else "resolved")
        self.store.update_incident(action.incident_id, "recovering", terminal)
        return True
