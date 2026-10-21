"""fix3-fops07 — detect_instance_idle 按实例新鲜度（F-OPS-07 fail-closed）。

对抗焦点：某实例新鲜绝不能掩盖另一实例的空转。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from abcr.ops import watchdog


def _now_minus(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setenv("ABCR_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(watchdog, "LEDGER_RUNS", tmp_path / "runs_index.jsonl")
    monkeypatch.setattr(watchdog, "LEDGER_INSTANCES", tmp_path / "instances.jsonl")
    return tmp_path


def _write_instances(evs):
    watchdog.LEDGER_INSTANCES.write_text(
        "\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")


def _write_runs(evs):
    watchdog.LEDGER_RUNS.write_text(
        "\n".join(json.dumps(e) for e in evs) + "\n", encoding="utf-8")


def test_idle_instance_not_masked_by_other_fresh_instance():
    # 核心对抗：A 空转（其 run 陈旧），B 新鲜（其 run 新鲜）。A 必须仍被告警。
    _write_instances([
        {"event": "instance_started", "subject_id": "instA", "run_id": "runA"},
        {"event": "instance_started", "subject_id": "instB", "run_id": "runB"},
    ])
    _write_runs([
        {"event": "step_progress", "subject_id": "runA", "ts": _now_minus(100000)},
        {"event": "step_progress", "subject_id": "runB", "ts": _now_minus(5)},
    ])
    alerts = {a["run_id"] for a in watchdog.detect_instance_idle()}
    assert alerts == {"instA"}, alerts


def test_fresh_instance_via_direct_instance_id_tag():
    # step_progress 直接携带 instance_id 归属：该实例豁免，另一裸实例告警。
    _write_instances([
        {"event": "instance_started", "subject_id": "instA"},
        {"event": "instance_started", "subject_id": "instB"},
    ])
    _write_runs([
        {"event": "step_progress", "subject_id": "runB", "ts": _now_minus(5),
         "instance_id": "instB"},
    ])
    alerts = {a["run_id"] for a in watchdog.detect_instance_idle()}
    assert alerts == {"instA"}, alerts


def test_live_instance_no_attributable_progress_is_alerted():
    # fail-closed：live 实例无任何可归属的新鲜进展（别的 run 新鲜但不归属它）→ 告警。
    _write_instances([
        {"event": "instance_started", "subject_id": "instA"},
    ])
    _write_runs([
        # 该 run 新鲜但不归属 instA（无 run_id 链、无 instance_id tag）
        {"event": "step_progress", "subject_id": "runX", "ts": _now_minus(5)},
    ])
    alerts = {a["run_id"] for a in watchdog.detect_instance_idle()}
    assert alerts == {"instA"}, alerts


def test_stopped_instance_never_alerted():
    _write_instances([
        {"event": "instance_started", "subject_id": "instA", "run_id": "runA"},
        {"event": "instance_stopped", "subject_id": "instA"},
    ])
    _write_runs([
        {"event": "step_progress", "subject_id": "runA", "ts": _now_minus(100000)},
    ])
    assert watchdog.detect_instance_idle() == []


def test_owned_fresh_run_exonerates_instance():
    _write_instances([
        {"event": "instance_started", "subject_id": "instA", "runs": ["r1", "r2"]},
    ])
    _write_runs([
        {"event": "step_progress", "subject_id": "r2", "ts": _now_minus(5)},
    ])
    assert watchdog.detect_instance_idle() == []
