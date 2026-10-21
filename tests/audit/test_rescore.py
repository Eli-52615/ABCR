"""tests/audit/test_rescore.py —— A1-5 独立复评器测试。

必含用例（§A1-5 验收）：test_golden10_pass_samples_all_1 /
test_golden10_fail_samples_all_0 / test_idempotent_rerun_adds_zero_rows。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from abcr.audit import rescore

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((REPO / "data" / "golden" / "golden10.json").read_text(encoding="utf-8"))["items"]


def test_golden10_pass_samples_all_1() -> None:
    """过门硬条件：10 题 pass_sample 全判 1。"""
    for it in GOLDEN:
        rule = rescore.GOLDEN_RULES[it["id"]]
        assert rule(it["pass_sample"]) == 1, f"{it['id']} pass_sample 应判 1"


def test_golden10_fail_samples_all_0() -> None:
    """过门硬条件：10 题 fail_sample 全判 0。"""
    for it in GOLDEN:
        rule = rescore.GOLDEN_RULES[it["id"]]
        assert rule(it["fail_sample"]) == 0, f"{it['id']} fail_sample 应判 0"


def test_g05_fence_and_plain_both_pass() -> None:
    """A1-5 要点④：g05 带/不带 ```json 围栏两种都要过。"""
    assert rescore.GOLDEN_RULES["g05"]('{"a": 1, "b": 2}') == 1
    assert rescore.GOLDEN_RULES["g05"]('```json\n{"a": 1, "b": 2}\n```') == 1
    assert rescore.GOLDEN_RULES["g05"]('```\n{"a": 1, "b": 2}\n```') == 1


def _write_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "data" / "runs" / "20260714T090000Z-testrun00000"
    run_dir.mkdir(parents=True)
    steps = []
    for i, it in enumerate(GOLDEN):
        out = it["fail_sample"] if it["id"] in ("g03", "g07") else it["pass_sample"]
        steps.append(json.dumps({
            "schema_version": "1.0", "run_id": run_dir.name,
            "trajectory_id": f"{run_dir.name}-{it['id']}", "step_id": 0,
            "condition": "vanilla", "random_seed": 1, "item_id": it["id"],
            "output_text": out, "output_tokens": max(1, len(out)),
        }, ensure_ascii=False))
    (run_dir / "steps.jsonl").write_text("\n".join(steps) + "\n", encoding="utf-8")
    return run_dir


def test_rescore_run_produces_expected_is_correct(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    n = rescore.rescore_run(run_dir)
    assert n == 60  # 10 题 × 6 指标
    rows = [json.loads(l) for l in (run_dir / "scores.jsonl").read_text().splitlines() if l.strip()]
    ic = {r["item_id"]: r["metric_value"] for r in rows
          if r["scorer_id"] == "rescore_v1" and r["metric_name"] == "is_correct"}
    assert ic["g03"] == 0 and ic["g07"] == 0
    assert sum(ic.values()) == 8  # 8/10 为 1


def test_idempotent_rerun_adds_zero_rows(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path)
    first = rescore.rescore_run(run_dir)
    second = rescore.rescore_run(run_dir)
    assert first > 0 and second == 0


def test_no_import_of_b_scorer() -> None:
    """坑12：rescore 模块不得 import abcr.rig（双实现纪律）——只查 import 语句，不查 docstring。"""
    import ast
    tree = ast.parse(inspect.getsource(rescore))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(m.startswith("abcr.rig") for m in imported), imported


def test_manipulation_rates_bounded() -> None:
    """manipulation-check 率 ∈ [0,1]；空文本 = 0.0。"""
    assert rescore._marker_rate("", rescore.HEDGING_WORDS) == 0.0
    r = rescore._marker_rate("这也许可能对。这是确定的。", rescore.HEDGING_WORDS)
    assert 0.0 <= r <= 1.0
