"""Materialized, fail-closed cockpit snapshot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from abcr.control.contracts import ControlSnapshot, Severity, sha256
from abcr.control.store import ControlStore


def build_snapshot(store: ControlStore, *, max_age_seconds: int = 120) -> ControlSnapshot:
    now = datetime.now(timezone.utc)
    sections: dict[str, Any] = {
        "待确认目标": [x for x in store.rows("proposals") if x["state"] in {"imported", "validated"}],
        "快道学习": [],
        "正式实验": [x for x in store.rows("actions") if x["intent"] in {"approve", "run_evidence"}],
        "轮报告与反思": [],
        "异常恢复": store.rows("incidents"),
        "预算校准": {"status": "UNKNOWN", "reason": "尚无当前价格/校准快照"},
    }
    services = store.rows("services")
    if any(not bool(x["semantic_ok"]) for x in services): severity = Severity.RISK
    elif not services: severity = Severity.UNKNOWN
    elif any(x["status"] not in {"healthy", "idle"} for x in services): severity = Severity.ATTENTION
    else: severity = Severity.INFO
    source_hash = sha256({"sections": sections, "services": services})
    generated = now.isoformat()
    return ControlSnapshot("SNAP-" + source_hash[:20], generated, source_hash,
                           (now + timedelta(seconds=max_age_seconds)).isoformat(),
                           dict(sections, 服务健康=services), severity)
