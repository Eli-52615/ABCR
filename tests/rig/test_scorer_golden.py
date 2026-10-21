"""tests/rig/test_scorer_golden —— golden10：pass_sample 判 1、fail_sample 判 0（契约 §2.10）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.rig import scorer

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((REPO / "data/golden/golden10.json").read_text(encoding="utf-8"))["items"]


@pytest.mark.parametrize("item", GOLDEN, ids=[r["id"] for r in GOLDEN])
def test_pass_sample_is_correct(item):
    assert scorer.score_golden(item["id"], item["pass_sample"]) is True


@pytest.mark.parametrize("item", GOLDEN, ids=[r["id"] for r in GOLDEN])
def test_fail_sample_is_incorrect(item):
    assert scorer.score_golden(item["id"], item["fail_sample"]) is False


def test_unknown_item_raises():
    with pytest.raises(KeyError):
        scorer.score_golden("g99", "x")


def test_score_steps_metric_rows():
    steps = [{
        "run_id": "r1", "item_id": "g02", "trajectory_id": "t", "step_id": 0,
        "condition": "fake", "random_seed": 1, "output_text": "391", "output_tokens": 0,
    }]
    rows = scorer.score_steps(steps)
    names = {r["metric_name"]: r["metric_value"] for r in rows}
    assert names["is_correct"] == 1
    assert names["parse_ok"] == 1
    assert names["output_len_chars"] == 3       # len("391")，不 strip
    assert names["output_len_tokens"] == 0
