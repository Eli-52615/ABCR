"""C1-6 sync 测试（§C1-6 测试要求）。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.report import sync

BATCH = "B-20260714T000000Z-0001"


def _make(tmp_path):
    """账本 2 run（SCORED）+ 各自 scores.jsonl（2 condition，供效应对比）。"""
    ledger_dir = tmp_path / "ledger"
    runs_dir = tmp_path / "data" / "runs"
    led = RunLedger(ledger_dir, "runs_index")
    for rid, cond in (("run-A", "fake"), ("run-B", "vanilla")):
        led.append("run_registered", subject_id=rid, batch_id=BATCH)
        led.append("run_started", subject_id=rid)
        led.append("run_completed", subject_id=rid)
        led.append("run_scored", subject_id=rid)
        rd = runs_dir / rid
        rd.mkdir(parents=True)
        rows = []
        for item, correct in (("g01", 1), ("g02", 1), ("g03", 0)):
            rows.append({"schema_version": "1.0", "run_id": rid, "item_id": item,
                         "trajectory_id": f"{rid}-{item}", "step_id": 0, "condition": cond,
                         "random_seed": 1, "metric_name": "is_correct", "metric_value": correct,
                         "scorer_id": "deterministic_v1", "scorer_version": "v1", "scored_at": "t"})
        (rd / "scores.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return ledger_dir, runs_dir


@pytest.fixture
def ctx(tmp_path):
    ledger_dir, runs_dir = _make(tmp_path)
    return {"ledger": ledger_dir, "runs": runs_dir, "envdir": tmp_path / "envelopes",
            "alerts": tmp_path / "noalerts", "out": tmp_path / "reports",
            "now": datetime.now(timezone.utc)}


def _gen(ctx, seg):
    return sync.run(seg, ctx["out"], ctx["ledger"], ctx["runs"], ctx["envdir"],
                    ctx["alerts"], date="2026-07-14", now=ctx["now"])


# 四段各渲染成功且文件名正确
@pytest.mark.parametrize("seg", ["morning", "afternoon", "evening", "urgent"])
def test_segment_renders(ctx, seg):
    out = _gen(ctx, seg)
    assert out.name == f"sync-2026-07-14-{seg}.md"
    md = out.read_text(encoding="utf-8")
    # 头部纪律行存在
    assert sync.DISCIPLINE_LINE in md


# 呈现纪律：凡含 4 位小数统计数字的行，同行必含 run 归属（run xxx / runs: ...）
def test_metric_lines_have_run_attribution(ctx):
    md = _gen(ctx, "evening").read_text(encoding="utf-8")
    metric_lines = [ln for ln in md.splitlines() if re.search(r"\d+\.\d{4}", ln)]
    assert metric_lines, "evening 应含统计数字行"
    for ln in metric_lines:
        assert ("run " in ln) or ("runs:" in ln), f"数字行缺 run 归属: {ln}"


# 效应对比行经 render_effect，含 source_run_ids 注明
def test_evening_effect_has_source_runs(ctx):
    md = _gen(ctx, "evening").read_text(encoding="utf-8")
    assert "runs:" in md   # render_effect 的 source_run_ids 注明


# evening 含告警计数行
def test_evening_alert_count(ctx):
    md = _gen(ctx, "evening").read_text(encoding="utf-8")
    assert "今日 A+B 告警数" in md and "/3" in md


# urgent 无 A 级 → 单行
def test_urgent_empty_single_line(ctx):
    md = _gen(ctx, "urgent").read_text(encoding="utf-8")
    assert "无 A 级异常" in md


# 确认期集成：ABCR_PHASE=confirmation 下 evening 效应区块无方向 token
def test_evening_confirmation_no_direction(ctx, monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    out = _gen(ctx, "evening")
    md = out.read_text(encoding="utf-8")
    # 效应行应为锁盲形态（含 |Δ|=、不含方向措辞）
    eff_lines = [ln for ln in md.splitlines() if "|Δ|=" in ln]
    assert eff_lines, "确认期效应行应为 |Δ| 锁盲形态"
    for ln in eff_lines:
        for tok in ("高于", "低于", "更好", "更差", "优于", "劣于"):
            assert tok not in ln


# ---- C2-6：预算与熔断 + 云实例 + non_citable 透传 ----
def _make_costs_instances(tmp_path):
    """在既有账本基础上追加 costs（预估/实耗/告警）与 instances（1 未 stopped 空转）。"""
    ledger_dir = tmp_path / "ledger"
    costs = RunLedger(ledger_dir, "costs")
    costs.append("run_cost_estimated", subject_id="run-A", amount_cny=10.0, basis="est")
    costs.append("run_cost_actual", subject_id="run-A", amount_cny=8.0, basis="act")
    costs.append("run_cost_actual", subject_id="run-B", amount_cny=4.0, basis="act")
    costs.append("budget_alert", subject_id="W1")
    inst = RunLedger(ledger_dir, "instances")
    inst.append("instance_registered", subject_id="inst-idle")
    inst.append("instance_started", subject_id="inst-idle")
    inst.append("instance_idle_alert", subject_id="inst-idle")
    inst.append("instance_registered", subject_id="inst-done")
    inst.append("instance_started", subject_id="inst-done")
    inst.append("instance_stopped", subject_id="inst-done")


def test_morning_budget_and_circuit_breaker(ctx, tmp_path):
    _make_costs_instances(tmp_path)
    md = _gen(ctx, "morning").read_text(encoding="utf-8")
    assert "## 今日预算与熔断" in md
    assert "预估合计 10.00" in md and "实耗合计 12.00" in md and "预算告警 1 次" in md
    assert "余额 138.00" in md                      # 150 − 12
    assert "距 85% 熔断线（127.5）尚余 115.50" in md  # 127.5 − 12
    # 逐 run 实耗带 subject_id
    assert "实耗 8.00 元（run-A）" in md and "实耗 4.00 元（run-B）" in md


def test_morning_instances_non_stopped_idle_is_A(ctx, tmp_path):
    _make_costs_instances(tmp_path)
    md = _gen(ctx, "morning").read_text(encoding="utf-8")
    assert "## 云实例（未 stopped）" in md
    assert "inst-idle" in md and "[A 空转]" in md    # 空转标 A 级
    assert "inst-done" not in md                     # stopped 不列


def test_evening_non_citable_passthrough(ctx, tmp_path):
    """G7：evening 逐 run 指标行透传 non_citable 标注（缺 manifest 保守标注）。"""
    md = _gen(ctx, "evening").read_text(encoding="utf-8")
    metric_lines = [ln for ln in md.splitlines() if re.search(r"\d+\.\d{4}", ln) and "scorer=" in ln]
    assert metric_lines
    for ln in metric_lines:
        assert "[non-citable]" in ln, ln


def test_every_segment_has_exploratory(ctx, tmp_path):
    """C-R2-7：每段都有 exploratory 标注行（grep -L exploratory 应为空）。"""
    _make_costs_instances(tmp_path)
    for seg in ("morning", "afternoon", "evening", "urgent"):
        md = _gen(ctx, seg).read_text(encoding="utf-8")
        assert "exploratory" in md, seg
