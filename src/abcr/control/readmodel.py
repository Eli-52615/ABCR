"""Materialized, fail-closed cockpit snapshot."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from abcr.control.contracts import ControlSnapshot, Severity, sha256
from abcr.control.store import ControlStore


def _service_view(row: dict[str, Any], *, now: datetime,
                  max_age_seconds: int) -> dict[str, Any]:
    try:
        checked = datetime.fromisoformat(row["checked_at"])
        if checked.tzinfo is None:
            raise ValueError("naive")
        age = max(0.0, (now - checked.astimezone(timezone.utc)).total_seconds())
        stale = age > max_age_seconds
    except (KeyError, TypeError, ValueError):
        age = None; stale = True
    try:
        detail = json.loads(row["detail_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        detail = {"decode_error": True}
    reported = row["status"]
    return {"label": row["label"], "release_id": row["release_id"],
            "status": "stale" if stale else reported,
            "reported_status": reported,
            "semantic_ok": bool(row["semantic_ok"]) and not stale,
            "freshness": "STALE" if stale else "FRESH",
            "age_seconds": age, "checked_at": row["checked_at"],
            "detail": detail}


def _decoded_rows(store: ControlStore, table: str, field: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in store.rows(table):
        value = dict(row)
        try:
            value[field.removesuffix("_json")] = json.loads(value.pop(field))
        except (KeyError, TypeError, json.JSONDecodeError):
            value[field.removesuffix("_json")] = {"decode_error": True}
        output.append(value)
    return output


def build_snapshot(store: ControlStore, *, max_age_seconds: int = 120,
                   now: datetime | None = None) -> ControlSnapshot:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dispatches = [{key: row[key] for key in (
        "effect_id", "batch_id", "release_id", "dispatch_event_id", "state",
        "reason_code", "created_at", "updated_at")}
                  for row in store.rows("dispatch_requests")]
    reports = _decoded_rows(store, "round_reports", "report_json")
    for row in reports:
        try:
            row["audit_reference"] = json.loads(row["audit_reference_json"])
        except (KeyError, TypeError, json.JSONDecodeError):
            row["audit_reference"] = {"decode_error": True}
        row.pop("audit_reference_json", None)
    drafts = _decoded_rows(store, "goal_drafts", "draft_json")
    reflections = [{key: row[key] for key in (
        "reflection_id", "round_id", "actor_id", "reflection_text", "created_at")}
                   for row in store.rows("round_reflections")]
    probes = [{key: row[key] for key in (
        "work_id", "proposal_id", "goal_id", "actor_id", "state", "result_hash",
        "created_at", "updated_at")}
              for row in store.rows("probe_runs")]
    probe_drafts = [{"promotion_id": row["promotion_id"],
                     "row_hash": row["row_hash"], "actor_id": row["actor_id"],
                     "draft": json.loads(row["draft_json"]),
                     "created_at": row["created_at"]}
                    for row in store.rows("probe_promotions")]
    sections: dict[str, Any] = {
        "待确认目标": [x for x in store.rows("proposals") if x["state"] in {"imported", "validated"}],
        "快道学习": {"runs": probes, "promotion_drafts": probe_drafts,
                     "evidence_policy": "exploratory_learning_only_never_citable"},
        "正式实验": dispatches,
        "轮报告与反思": {"reports": reports, "human_reflections": reflections,
                         "machine_goal_drafts": drafts,
                         "draft_policy": "awaiting_human_claude_never_auto_execute"},
        "异常恢复": _decoded_rows(store, "incidents", "evidence_json"),
        "自动修复任务": _decoded_rows(store, "missions", "payload_json"),
        "预算校准": {"status": "UNKNOWN", "reason": "尚无当前价格/校准快照"},
    }
    services = [_service_view(row, now=now, max_age_seconds=max_age_seconds)
                for row in store.rows("services")]
    runtime_blocks = [row for row in dispatches if row["state"] == "blocked"
                      and row["reason_code"] != "DISPATCH_SUPERVISOR_UNQUALIFIED"]
    qualification_blocks = [row for row in dispatches if row["state"] == "blocked"
                            and row["reason_code"] == "DISPATCH_SUPERVISOR_UNQUALIFIED"]
    statuses = {item["status"] for item in services}
    if runtime_blocks or statuses & {"blocked", "needs_human", "quarantined"}:
        severity = Severity.RISK
    elif not services: severity = Severity.UNKNOWN
    elif qualification_blocks or statuses & {"stale", "recovering", "mission_queued"}:
        severity = Severity.ATTENTION
    elif any(not item["semantic_ok"] for item in services): severity = Severity.RISK
    else: severity = Severity.INFO
    # Age is presentation-time data; freshness/status capture the meaningful
    # boundary without changing source_hash on every render tick.
    source_services = [{key: value for key, value in item.items()
                        if key != "age_seconds"} for item in services]
    source_hash = sha256({"sections": sections, "services": source_services})
    generated = now.isoformat()
    return ControlSnapshot("SNAP-" + source_hash[:20], generated, source_hash,
                           (now + timedelta(seconds=max_age_seconds)).isoformat(),
                           dict(sections, 服务健康=services), severity)
