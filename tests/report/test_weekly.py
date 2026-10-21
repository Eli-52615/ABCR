"""C2-4 周证据对象包模板测试（§C2-4 / §8.2 C-R2-6）：四节齐 + 头禁令注释在 +
数字带 run_id/来源；③失败节不可为空；确认期效应无方向。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.report import weekly

BATCH = "B-20260714T000000Z-0001"


def _make(tmp_path: Path):
    ledger_dir = tmp_path / "ledger"
    runs_dir = tmp_path / "data" / "runs"
    led = RunLedger(ledger_dir, "runs_index")
    bat = RunLedger(ledger_dir, "batches")
    bat.append("batch_drafted", subject_id=BATCH, actor="human")
    bat.append("batch_settled", subject_id=BATCH, actor="operator")
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
    return {"ledger": ledger_dir, "runs": runs_dir, "envdir": tmp_path / "noenv",
            "alerts": tmp_path / "noalerts", "out": tmp_path / "out", "repo": tmp_path}


def _gen(ctx):
    return weekly.run("2026-W29", ctx["out"], ctx["ledger"], ctx["runs"], ctx["envdir"],
                      ctx["alerts"], ctx["repo"], now=datetime.now(timezone.utc))


def test_head_forbiddance_comment_verbatim(ctx):
    md = _gen(ctx).read_text(encoding="utf-8")
    # 头注释五禁令逐字
    for frag in ("对外禁令（全部禁止，违者撤回重写）：",
                 "只发愿景不发证据", "把 exploratory 数字当结论表述",
                 "用 judge 单一分数宣称", "只晒代码量/工程量", "藏负结果",
                 "确认期（ABCR_PHASE=confirmation）本模板输出不得含效应方向"):
        assert frag in md, frag


def test_four_sections_present(ctx):
    md = _gen(ctx).read_text(encoding="utf-8")
    assert "## ① 一张图" in md
    assert "## ② 一段可复现说明" in md
    assert "## ③ 本周失败" in md
    assert "## ④ 下周假设" in md


def test_failures_section_not_empty(ctx):
    """③失败节不可为空——无失败时写"本周无失败记录"并附账本查询命令。"""
    md = _gen(ctx).read_text(encoding="utf-8")
    seg = md.split("## ③ 本周失败", 1)[1].split("## ④", 1)[0]
    assert seg.strip(), "③节不可为空"
    assert "本周无失败记录" in seg and "abcr.governor.triage" in seg


def test_repro_and_exploratory_and_source(ctx):
    md = _gen(ctx).read_text(encoding="utf-8")
    assert "exploratory" in md                       # 标注行在（C-R2-7）
    assert "rescore_standalone.py" in md             # 复现命令
    assert BATCH in md                               # 来源批次 / 复现包引用带 batch_id
    assert "> 数字均为 exploratory" in md


def test_confirmation_effect_no_direction(ctx, monkeypatch):
    monkeypatch.setenv("ABCR_PHASE", "confirmation")
    md = _gen(ctx).read_text(encoding="utf-8")
    eff_lines = [ln for ln in md.splitlines() if "效应速览" in ln]
    assert eff_lines
    for ln in eff_lines:
        assert "|Δ|=" in ln, ln          # 确认期效应必为锁盲量级形态
        # 剥去 markdown blockquote 前缀后，效应正文不含任何方向措辞
        body = ln.lstrip("> ").split("：", 1)[-1]
        for tok in ("高于", "低于", "更好", "更差", "优于", "劣于", "上升", "下降", "正向", "负向"):
            assert tok not in body, ln
