"""Frozen, dependency-free contracts shared by all control-plane processes."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ContractError(ValueError):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class CommandState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    QUEUED = "queued"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class ProposalState(StrEnum):
    IMPORTED = "imported"
    INVALID = "invalid"
    VALIDATED = "validated"
    HUMAN_CONFIRMED = "human_confirmed"
    COMPILED = "compiled"
    RUNNING = "running"
    REPORTED = "reported"
    REFLECTED = "reflected"


class IncidentState(StrEnum):
    DETECTED = "detected"
    CLASSIFYING = "classifying"
    RECOVERING = "recovering"
    RESOLVED = "resolved"
    MISSION_QUEUED = "mission_queued"
    QUARANTINED = "quarantined"
    NEEDS_HUMAN = "needs_human"


class MissionState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    VERIFYING = "verifying"
    RELEASED = "released"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    NEEDS_HUMAN = "needs_human"


class Severity(StrEnum):
    INFO = "info"
    ATTENTION = "attention"
    RISK = "risk"
    UNKNOWN = "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256(value: bytes | Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def require_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise ContractError("invalid_id", f"{field_name} 格式不合法", {field_name: value})
    return value


def require_sha(value: str, field_name: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ContractError("invalid_sha256", f"{field_name} 必须是小写 SHA-256")
    return value


@dataclass(frozen=True)
class Actor:
    open_id: str
    tenant_key: str
    chat_id: str
    chat_type: str = "p2p"

    def validate(self, *, owner_open_id: str, owner_chat_id: str, tenant_key: str) -> None:
        if self.chat_type != "p2p":
            raise ContractError("group_chat_forbidden", "只接受所有者一对一会话")
        if (self.open_id, self.chat_id, self.tenant_key) != (owner_open_id, owner_chat_id, tenant_key):
            raise ContractError("identity_mismatch", "发送者、会话或租户不匹配")


@dataclass(frozen=True)
class ControlCommand:
    command_id: str
    message_id: str
    actor: Actor
    intent: str
    payload: dict[str, Any]
    received_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_id(self.command_id, "command_id")
        require_id(self.message_id, "message_id")
        require_id(self.intent, "intent")

    @property
    def effect_id(self) -> str:
        return sha256({"message_id": self.message_id, "actor": asdict(self.actor),
                       "intent": self.intent, "payload": self.payload})


@dataclass(frozen=True)
class ActionResult:
    effect_id: str
    state: CommandState
    code: str
    human_message: str
    data: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ControlSnapshot:
    snapshot_id: str
    generated_at: str
    source_hash: str
    stale_after: str
    sections: dict[str, Any]
    severity: Severity

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["severity"] = self.severity.value
        return out


def strict_object(value: Any, *, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ContractError("not_object", "对象必须是 JSON/YAML mapping")
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise ContractError("missing_fields", "缺少必填字段", {"fields": sorted(missing)})
    if extra:
        raise ContractError("unknown_fields", "包含未登记字段", {"fields": sorted(extra)})
    return value
