"""Fail-closed recovery and mission path-risk policy."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from abcr.control.contracts import ContractError


class RecoveryKind(StrEnum):
    RETRY = "retry"
    RESUME_SAME_RELEASE = "resume_same_release"
    THROTTLE = "throttle"
    QUARANTINE = "quarantine"
    CREATE_MISSION = "create_mission"
    NEEDS_HUMAN = "needs_human"
    NOOP = "noop"


@dataclass(frozen=True)
class RecoveryDecision:
    kind: RecoveryKind
    reason_code: str
    max_attempts: int
    preserve_release: bool = True


@dataclass(frozen=True)
class RecoveryPolicy:
    retryable_codes: frozenset[str] = frozenset({"network_timeout", "http_429", "http_500",
                                                  "http_502", "http_503", "process_dead"})
    integrity_codes: frozenset[str] = frozenset({"split_mismatch", "config_hash_mismatch",
                                                 "ledger_invalid", "lockblind", "evidence_missing",
                                                 "score_mismatch"})
    resource_codes: frozenset[str] = frozenset({"memory_pressure", "disk_pressure"})
    scientific_codes: frozenset[str] = frozenset({"ambiguous_goal", "metric_semantics",
                                                  "unexpected_scientific_result"})
    max_retry: int = 3

    def classify(self, signal: dict[str, Any]) -> RecoveryDecision:
        code = signal.get("code")
        domain = signal.get("fault_domain", "engineering")
        # Domain is an independently observed trust boundary.  A novel error code
        # must not turn a scientific decision, TCB mutation, or integrity failure
        # into the generic engineering auto-mission path.
        if domain == "integrity":
            return RecoveryDecision(RecoveryKind.QUARANTINE,
                                    str(code or "integrity_fault"), 0)
        if domain in {"scientific", "tcb"}:
            return RecoveryDecision(RecoveryKind.NEEDS_HUMAN,
                                    str(code or f"{domain}_fault"), 0)
        if domain != "engineering":
            return RecoveryDecision(RecoveryKind.NEEDS_HUMAN,
                                    "unknown_fault_domain", 0)
        if code in self.integrity_codes: return RecoveryDecision(RecoveryKind.QUARANTINE, code, 0)
        if code in self.scientific_codes: return RecoveryDecision(RecoveryKind.NEEDS_HUMAN, code, 0)
        if code in self.resource_codes: return RecoveryDecision(RecoveryKind.THROTTLE, code, self.max_retry)
        if code == "process_dead": return RecoveryDecision(RecoveryKind.RESUME_SAME_RELEASE, code, self.max_retry)
        if code in self.retryable_codes: return RecoveryDecision(RecoveryKind.RETRY, code, self.max_retry)
        if signal.get("healthy") is True: return RecoveryDecision(RecoveryKind.NOOP, "healthy", 0)
        return RecoveryDecision(RecoveryKind.CREATE_MISSION, "unknown_engineering_fault", 1)


TCB_GLOBS = (
    "configs/protocol/**", "configs/control/**", "configs/research/**", "configs/probe/**",
    "configs/schemas/**", "data/benchmarks/**", "data/splits/**", "src/abcr/explore/**",
    "src/abcr/probe/**", "src/abcr/governor/**", "src/abcr/rig/**", "src/abcr/audit/**",
    "src/abcr/ledger/**", "src/abcr/common/approval_token.py", "src/abcr/control/identity.py",
    "src/abcr/control/ed25519.py", "src/abcr/control/test_controller.py",
    "src/abcr/control/black_box_oracle.py", "src/abcr/control/verifier.py",
    "src/abcr/control/release.py", "src/abcr/control/seal_broker.py", "ops/**", "tests/**",
)


def normalize_changed_path(path: str) -> str:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ContractError("changed_path_escape", "changed path 必须是仓内规范相对路径")
    normalized = str(pure)
    if normalized.startswith(".git/") or normalized == ".git":
        raise ContractError("git_metadata_forbidden", "candidate 禁止修改 Git metadata")
    return normalized


def effective_mission_risk(declared: str, changed_paths: list[str],
                           registry: dict[str, dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
    if declared not in {"normal", "guarded", "human_required"}:
        raise ContractError("bad_declared_risk", "mission risk 不合法")
    normalized = tuple(normalize_changed_path(path) for path in changed_paths)
    if any(any(fnmatch.fnmatch(path, glob) for glob in TCB_GLOBS) for path in normalized):
        return "human_required", normalized
    for path in normalized:
        rule = next((value for glob, value in registry.items() if fnmatch.fnmatch(path, glob)), None)
        if rule is None or not rule.get("auto_release_eligible"):
            return "human_required", normalized
        if not rule.get("required_external_oracle_ids"):
            return "human_required", normalized
    return declared, normalized
