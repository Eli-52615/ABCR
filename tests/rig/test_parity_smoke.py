"""tests/rig/test_parity_smoke —— 双引擎比对核心（纯函数，B2-12）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("b_parity_smoke", REPO / "scripts/b_parity_smoke.py")
bps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bps)


def test_dev_first_n_sorted_and_dev_only():
    items = bps.dev_first_n(20)
    assert len(items) == 20
    ids = [it["item_id"] for it in items]
    assert ids == sorted(ids)
    from abcr.rig.splits import assign_split
    assert all(assign_split("ifeval_zh_v1", i) == "dev" for i in ids)


def test_compare_parity_exact_and_correct_rates():
    items = [
        {"item_id": "ifzh-0001", "check_type": "exact_output", "check_args": {"expected": "68"}},
        {"item_id": "ifzh-0002", "check_type": "exact_output", "check_args": {"expected": "10"}},
    ]
    out_a = {"ifzh-0001": "68", "ifzh-0002": "10"}
    out_b = {"ifzh-0001": "68", "ifzh-0002": "十"}   # 第二题引擎 B 分歧且判错
    r = bps.compare_parity(items, out_a, out_b)
    assert r["output_exact_match_rate"] == 0.5   # 1/2 精确一致
    assert r["is_correct_match_rate"] == 0.5      # 第二题 correct 不一致
    # 分歧样例保留全文
    div = [rec for rec in r["records"] if not rec["output_exact_match"]]
    assert div and "engine_b_output" in div[0]


def test_compare_parity_full_agreement():
    items = [{"item_id": "ifzh-0001", "check_type": "exact_output", "check_args": {"expected": "5"}}]
    r = bps.compare_parity(items, {"ifzh-0001": "5"}, {"ifzh-0001": "5"})
    assert r["output_exact_match_rate"] == 1.0
    assert r["is_correct_match_rate"] == 1.0
