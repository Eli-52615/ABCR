"""C1-7 views 测试（§C1-7 测试要求）：2 run × 3 item，含 g03 已知错样。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger
from abcr.report import views

BATCH = "B-20260714T000000Z-0001"
ITEMS = ["g01", "g02", "g03"]   # g03 = 已知错样


def _write_run(runs_dir: Path, run_id: str, condition: str, seed: int):
    rd = runs_dir / run_id
    rd.mkdir(parents=True)
    steps = []
    scores = []
    for item in ITEMS:
        correct = 0 if item == "g03" else 1       # g03 已知错
        text = f"OUTPUT<{run_id}:{item}>\n多行\t含制表符原样"
        steps.append({"schema_version": "1.0", "run_id": run_id, "trajectory_id": f"{run_id}-{item}",
                      "step_id": 0, "condition": condition, "random_seed": seed,
                      "item_id": item, "output_text": text, "is_correct": None})
        scores.append({"schema_version": "1.0", "run_id": run_id, "item_id": item,
                       "trajectory_id": f"{run_id}-{item}", "step_id": 0, "condition": condition,
                       "random_seed": seed, "metric_name": "is_correct", "metric_value": correct,
                       "scorer_id": "deterministic_v1", "scorer_version": "v1", "scored_at": "t"})
    (rd / "steps.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps) + "\n",
                                    encoding="utf-8")
    (rd / "scores.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in scores) + "\n",
                                     encoding="utf-8")
    return steps


@pytest.fixture
def env(tmp_path):
    runs_dir = tmp_path / "data" / "runs"
    ledger_dir = tmp_path / "ledger"
    led = RunLedger(ledger_dir, "runs_index")
    steps_r1 = _write_run(runs_dir, "run-A", "fake", 1)
    _write_run(runs_dir, "run-B", "vanilla", 2)
    for rid in ("run-A", "run-B"):
        led.append("run_registered", subject_id=rid, batch_id=BATCH)
        led.append("run_started", subject_id=rid)
        led.append("run_completed", subject_id=rid)
        led.append("run_scored", subject_id=rid)
    return {"runs_dir": runs_dir, "ledger_dir": ledger_dir, "steps_r1": steps_r1}


def test_overview_counts(env):
    ov = views.overview(env["ledger_dir"], env["runs_dir"])
    assert ov["run_state_counts"].get("SCORED") == 2
    # per-condition is_correct 均值：fake 有 2/3 正确、vanilla 2/3
    m = {(r["condition"], r["scorer_id"]): r["mean_value"] for r in ov["per_condition"]
         if r["metric_name"] == "is_correct"}
    assert abs(m[("fake", "deterministic_v1")] - 2 / 3) < 1e-9
    assert abs(m[("vanilla", "deterministic_v1")] - 2 / 3) < 1e-9


def test_batch_detail_arm_mean(env):
    bd = views.batch_detail(BATCH, env["ledger_dir"], env["runs_dir"])
    assert len(bd["runs"]) == 2
    assert set(bd["run_ids"]) == {"run-A", "run-B"}
    arm = {(a["condition"], a["metric_name"]): (a["mean_value"], a["n"]) for a in bd["arm_aggregate"]}
    # 手算：每 condition 3 item、2 正确 → mean 2/3、n 3
    assert arm[("fake", "is_correct")][1] == 3
    assert abs(arm[("fake", "is_correct")][0] - 2 / 3) < 1e-9


def test_run_item_output_verbatim(env):
    ri = views.run_item("run-A", "g03", env["runs_dir"])
    assert len(ri["steps"]) == 1
    # 逐字节相等
    expected = next(s["output_text"] for s in env["steps_r1"] if s["item_id"] == "g03")
    assert ri["steps"][0]["output_text"] == expected
    # g03 分数 = 0（已知错）
    assert ri["scores"][0]["metric_value"] == 0


def test_overview_empty_no_crash(tmp_path):
    """空数据护栏（K7）：无 scores 文件时不下 SQL、返回零值结构。"""
    (tmp_path / "ledger").mkdir()
    ov = views.overview(tmp_path / "ledger", tmp_path / "data" / "runs")
    assert ov["run_state_counts"] == {}
    assert ov["per_condition"] == []
