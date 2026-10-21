"""tests/audit/test_budget_recon.py —— A2-3/A2-4 成本对账 + ¥150/85% 熔断。

文档验收用例：偏差 9% PASS / 11% FAIL；缺实耗 FAIL；实例无 stopped 超 1h FAIL；
人造总额 ¥128 → check_fuse 产出告警且 budget_alert 入账；24h 内不重复告警；
进行中实例按 price_cny_per_h×已运行小时计入熔断分子；ABCR_BUDGET_CAP_CNY monkeypatch 生效。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from abcr.audit import budget_recon as br
from abcr.common.ledger_ref import RunLedger

BATCH_ID = "B-20260714T090000Z-0001"


def _costs(repo: Path) -> RunLedger:
    return RunLedger(repo / "ledger", "costs")


def _instances(repo: Path) -> RunLedger:
    return RunLedger(repo / "ledger", "instances")


def _est(repo: Path, rid: str, amt: float) -> None:
    _costs(repo).append("run_cost_estimated", subject_id=rid, batch_id=BATCH_ID,
                        amount_cny=amt, basis="test")


def _act(repo: Path, rid: str, amt: float) -> None:
    _costs(repo).append("run_cost_actual", subject_id=rid, batch_id=BATCH_ID,
                        amount_cny=amt, basis="test")


# ---------- 成本对账 ----------

def test_deviation_9pct_pass(tmp_path: Path) -> None:
    _est(tmp_path, "r1", 100.0)
    _act(tmp_path, "r1", 109.0)  # 9%
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "PASS", res["evidence"]


def test_deviation_11pct_fail(tmp_path: Path) -> None:
    _est(tmp_path, "r1", 100.0)
    _act(tmp_path, "r1", 111.0)  # 11%
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL"
    assert any("偏差" in e for e in res["evidence"])


def test_missing_actual_fail(tmp_path: Path) -> None:
    _est(tmp_path, "r1", 10.0)  # 有预估无实耗
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL"
    assert any("跑了没记账" in e for e in res["evidence"])


def test_instance_no_stopped_over_1h_fail(tmp_path: Path) -> None:
    started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _instances(tmp_path).append("instance_started", subject_id="inst-1",
                                instance_id="inst-1", vendor="v", spec="s",
                                price_cny_per_h=6.0, batch_id=BATCH_ID, started_at=started)
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "FAIL"
    assert any("started 无 stopped" in e for e in res["evidence"])


def test_instance_paired_ok(tmp_path: Path) -> None:
    _instances(tmp_path).append("instance_started", subject_id="inst-1",
                                instance_id="inst-1", vendor="v", spec="s",
                                price_cny_per_h=6.0, batch_id=BATCH_ID)
    _instances(tmp_path).append("instance_stopped", subject_id="inst-1")
    _est(tmp_path, "r1", 10.0)
    _act(tmp_path, "r1", 10.0)
    res = br.reconcile_batch(tmp_path, BATCH_ID)
    assert res["verdict"] == "PASS", res["evidence"]


# ---------- 熔断 ----------

def _append_costs(repo: Path):
    return _costs(repo).append


def test_fuse_triggers_at_128_and_alert_recorded(tmp_path: Path) -> None:
    _act(tmp_path, "r1", 128.0)  # ≥ 85% of 150
    payload = br.check_fuse(tmp_path, _append_costs(tmp_path))
    assert payload is not None
    assert payload["ratio"] >= 0.85
    # budget_alert 入账
    evs = [e for e in _costs(tmp_path).events() if e.get("event") == "budget_alert"]
    assert len(evs) == 1
    assert evs[0]["total_cny"] >= 128.0
    # 告警文件落盘
    alerts = list((tmp_path / "state" / "audit" / "alerts").glob("budget-*.json"))
    assert len(alerts) == 1


def test_fuse_below_85_no_alert(tmp_path: Path) -> None:
    _act(tmp_path, "r1", 100.0)  # 66%
    assert br.check_fuse(tmp_path, _append_costs(tmp_path)) is None
    assert not any(e.get("event") == "budget_alert" for e in _costs(tmp_path).events())


def test_fuse_24h_cooldown_dedup(tmp_path: Path) -> None:
    _act(tmp_path, "r1", 130.0)
    assert br.check_fuse(tmp_path, _append_costs(tmp_path)) is not None
    # 第二次调用 24h 内不重复
    assert br.check_fuse(tmp_path, _append_costs(tmp_path)) is None
    evs = [e for e in _costs(tmp_path).events() if e.get("event") == "budget_alert"]
    assert len(evs) == 1


def test_running_instance_counts_toward_fuse(tmp_path: Path) -> None:
    """进行中实例 started 无 stopped，按 price_cny_per_h×已运行小时计入熔断分子（AMENDMENT-28②）。"""
    started = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _instances(tmp_path).append("instance_started", subject_id="inst-1",
                                instance_id="inst-1", vendor="v", spec="s",
                                price_cny_per_h=6.0, batch_id=BATCH_ID, started_at=started)
    # 25h × ¥6/h = ¥150 → 100% cap，无任何 run_cost_actual 也应熔断
    est = br.running_estimate_cny(tmp_path)
    assert est >= 149.0, est
    payload = br.check_fuse(tmp_path, _append_costs(tmp_path))
    assert payload is not None and payload["ratio"] >= 0.85


def test_budget_cap_monkeypatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABCR_BUDGET_CAP_CNY", "50")
    assert br.budget_cap_cny() == 50.0
    _act(tmp_path, "r1", 45.0)  # 90% of 50
    assert br.check_fuse(tmp_path, _append_costs(tmp_path)) is not None


def test_budget_recon_item_wraps(tmp_path: Path) -> None:
    _est(tmp_path, "r1", 10.0)
    _act(tmp_path, "r1", 10.0)
    item = br.budget_recon_item(tmp_path, BATCH_ID, ["r1"])
    assert item.id == 6 and item.verdict == "PASS", item.evidence
    assert any("预算比率" in e for e in item.evidence)
