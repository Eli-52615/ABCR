"""tests/ops/test_watchdog —— 停摆/挂起检出、账本 TTL 四类、冷却去重、env 阈值覆盖。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from abcr.ops import watchdog

OLD = "2020-01-01T00:00:00+00:00"


def _now_minus(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    # AMENDMENT-38：state/runs/alerts 路径改为调用时读 ABCR_STATE_DIR（不再有
    # RUNS_DIR/STATE/ALERTS_DIR 模块常量）；ledger 路径仍是模块 Path，monkeypatch 到 tmp。
    monkeypatch.setenv("ABCR_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(watchdog, "LEDGER_RUNS", tmp_path / "runs_index.jsonl")
    monkeypatch.setattr(watchdog, "LEDGER_INSTANCES", tmp_path / "instances.jsonl")
    return tmp_path


def _write_runstate(tmp_path, run_id, status, updated_at):
    p = watchdog.runs_dir() / f"{run_id}.json"
    p.write_text(json.dumps({"run_id": run_id, "status": status,
                             "updated_at": updated_at, "reason": "boom"}),
                 encoding="utf-8")


def test_detect_runstate_stalled_and_suspended(_isolate):
    _write_runstate(_isolate, "stale", "running", OLD)          # STALLED
    _write_runstate(_isolate, "fresh", "suspended", _now_minus(1))  # SUSPENDED_FAIL
    _write_runstate(_isolate, "ok", "done", _now_minus(1))      # 忽略
    kinds = {a["kind"]: a["run_id"] for a in watchdog.detect_runstate()}
    assert kinds == {"STALLED": "stale", "SUSPENDED_FAIL": "fresh"}


def test_handle_cooldown_dedup(_isolate):
    anomaly = {"kind": "STALLED", "run_id": "r1"}
    assert watchdog.handle(anomaly, dispatch=True) == "dispatched"
    assert "冷却" in watchdog.handle(anomaly, dispatch=True)     # 第二次冷却跳过
    # 告警文件确已落盘（F-OPS-06：文件名含 kind-run_id-uuid 唯一后缀防同秒覆盖）
    assert list((_isolate / "alerts").glob("*-STALLED-*.json"))


def test_handle_dry_run_no_alert(_isolate):
    assert "dry-run" in watchdog.handle({"kind": "STALLED", "run_id": "r1"}, dispatch=False)
    assert not (_isolate / "alerts").exists() or not list((_isolate / "alerts").glob("*.json"))


def test_detect_ledger_ttl_four_kinds(_isolate):
    evs = [
        {"event": "run_queued", "subject_id": "A", "ts": OLD},
        {"event": "run_started", "subject_id": "B", "ts": OLD},
        {"event": "run_completed", "subject_id": "C", "ts": OLD},
        {"event": "run_scored", "subject_id": "D", "ts": OLD},
        # 收口的 run 不报
        {"event": "run_scored", "subject_id": "E", "ts": OLD},
        {"event": "run_audited", "subject_id": "E", "ts": OLD},
    ]
    watchdog.LEDGER_RUNS.write_text(
        "\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")
    kinds = {a["run_id"]: a["kind"] for a in watchdog.detect_ledger_ttl()}
    assert kinds == {"A": "TTL_QUEUED", "B": "TTL_HEARTBEAT",
                     "C": "TTL_UNSCORED", "D": "TTL_UNAUDITED"}


def test_env_threshold_override(_isolate, monkeypatch):
    _write_runstate(_isolate, "recent", "running", _now_minus(10))
    # 默认 STALL_S=900：10s 不算停摆
    assert watchdog.detect_runstate() == []
    # 覆盖 STALL_S=1：立即判停摆（运行时读 env）
    monkeypatch.setenv("ABCR_WD_STALL_S", "1")
    kinds = [a["kind"] for a in watchdog.detect_runstate()]
    assert kinds == ["STALLED"]


def test_instance_idle_empty_when_no_file(_isolate):
    # 阶段1 无 instances 链 → 返回 []
    assert watchdog.detect_instance_idle() == []
