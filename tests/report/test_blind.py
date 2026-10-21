"""C2-5 方向锁盲测试（§C2-5 测试要求 / §8.2 C-R2-5）。

覆盖：确认期 render_effect 无方向 token 且无两臂原值；探索期含完整方向；两相位均含
source_run_ids 注明；词表防回归；assert_no_direction 相位行为；sync evening 集成。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.report import blind, sync

VA, VB = 0.8125, 0.6250
LA, LB = "vanilla", "persona_text"


def test_exploration_has_full_direction(monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "exploration")
    out = blind.render_effect("is_correct", VA, VB, LA, LB)
    assert f"{VA:.4f}" in out and f"{VB:.4f}" in out      # 两臂原值都在
    assert ">" in out                                     # 方向号在（VA>VB）
    assert f"{VA - VB:+.4f}" in out                        # Δ 带符号


def test_confirmation_strips_direction_and_arm_values(monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    out = blind.render_effect("is_correct", VA, VB, LA, LB)
    # 无任何方向 token
    for tok in blind.DIRECTION_TOKENS:
        assert tok not in out, tok
    # 不含两臂各自原值
    assert f"{VA:.4f}" not in out and f"{VB:.4f}" not in out
    # 只报量级
    assert f"|Δ|={abs(VA - VB):.4f}" in out


@pytest.mark.parametrize("phase", ["exploration", "confirmation"])
def test_source_run_ids_annotated_both_phases(monkeypatch, phase):
    monkeypatch.setenv("ABCR_PHASE", phase)
    out = blind.render_effect("is_correct", VA, VB, LA, LB,
                              source_run_ids=["run-1", "run-2"])
    assert "runs: run-1,run-2" in out


def test_direction_tokens_no_dup_regression():
    """词表防回归：V1.0 曾重复"下降"。"""
    assert len(set(blind.DIRECTION_TOKENS)) == len(blind.DIRECTION_TOKENS)


def test_assert_no_direction_confirmation_raises(monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    with pytest.raises(ValueError, match="方向锁盲违规"):
        blind.assert_no_direction("A 高于 B")


def test_assert_no_direction_exploration_noop(monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "exploration")
    blind.assert_no_direction("A 高于 B")   # 探索期不 raise


def test_default_phase_is_exploration(monkeypatch):
    monkeypatch.delenv("ABCR_PHASE", raising=False)
    assert blind.current_phase() == "exploration"


# ---- sync evening 集成：确认期渲染成功且效应区块无方向 ----
def _sync_env(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    runs_dir = tmp_path / "data" / "runs"
    led = RunLedger(ledger_dir, "runs_index")
    for rid, cond in (("run-A", "vanilla"), ("run-B", "persona_text")):
        led.append("run_registered", subject_id=rid, batch_id="B-20260714T000000Z-0001")
        led.append("run_started", subject_id=rid)
        led.append("run_completed", subject_id=rid)
        led.append("run_scored", subject_id=rid)
        rd = runs_dir / rid
        rd.mkdir(parents=True)
        rows = [{"schema_version": "1.0", "run_id": rid, "item_id": it,
                 "trajectory_id": f"{rid}-{it}", "step_id": 0, "condition": cond,
                 "random_seed": 1, "metric_name": "is_correct", "metric_value": v,
                 "scorer_id": "deterministic_v1", "scorer_version": "v1", "scored_at": "t"}
                for it, v in (("g01", 1), ("g02", 1), ("g03", 0))]
        (rd / "scores.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return ledger_dir, runs_dir


def test_sync_evening_confirmation_no_direction(tmp_path, monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    ledger_dir, runs_dir = _sync_env(tmp_path)
    out = sync.run("evening", tmp_path / "out", ledger_dir, runs_dir,
                   tmp_path / "noenv", tmp_path / "noalerts",
                   date="2026-07-14", now=datetime.now(timezone.utc))
    md = out.read_text(encoding="utf-8")
    eff = [ln for ln in md.splitlines() if "|Δ|=" in ln]
    assert eff, "确认期效应行应为锁盲形态"
    for ln in eff:
        for tok in ("高于", "低于", "更好", "更差", "优于", "劣于", "上升", "下降", "正向", "负向"):
            assert tok not in ln, ln
