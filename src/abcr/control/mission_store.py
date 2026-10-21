"""Mission DAG/lease facade over the durable control store."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from abcr.control.contracts import ContractError, sha256
from abcr.control.store import ControlStore


@dataclass(frozen=True)
class MissionSpec:
    objective: str
    non_goals: tuple[str, ...]
    incident_evidence: dict[str, Any]
    base_release: str
    allowed_paths: tuple[str, ...]
    acceptance_profile: str
    declared_risk: str
    rollback_release: str

    @property
    def mission_id(self) -> str:
        return "MIS-" + sha256(self.as_dict())[:20]

    def as_dict(self) -> dict[str, Any]:
        return {"objective": self.objective, "non_goals": list(self.non_goals),
                "incident_evidence": self.incident_evidence, "base_release": self.base_release,
                "allowed_paths": list(self.allowed_paths),
                "acceptance_profile": self.acceptance_profile,
                "declared_risk": self.declared_risk, "rollback_release": self.rollback_release}


class MissionQueue:
    def __init__(self, store: ControlStore): self.store = store

    def submit(self, spec: MissionSpec, dependencies: tuple[str, ...] = ()) -> str:
        if not spec.objective.strip() or not spec.allowed_paths:
            raise ContractError("mission_incomplete", "mission 缺少目标或 allowed_paths")
        self.store.create_mission(spec.mission_id, risk=spec.declared_risk,
                                  payload=spec.as_dict(), base_release=spec.base_release,
                                  dependencies=dependencies)
        return spec.mission_id

    def claim(self, worker_id: str) -> dict[str, Any] | None:
        return self.store.claim_mission(worker_id)
