"""tests/rig/test_ifeval —— ifeval_zh_v1 250 题定稿校验（B2-7 硬门）。

- 250 题、八类计数正确
- 每题 pass_sample 判 True、fail_sample 判 False（500 断言）
- 题面与 golden10 零重合
- split_hash 与冻结 split 文件一致（复算稳定）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.rig import scorer
from abcr.rig.splits import assign_split, split_hash

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "data/benchmarks/ifeval_zh_v1.json"
SPLIT = REPO / "data/splits/ifeval_zh_v1.json"

_bench = json.loads(BENCH.read_text(encoding="utf-8")) if BENCH.exists() else {"items": []}
ITEMS = _bench.get("items", [])

pytestmark = pytest.mark.skipif(not BENCH.exists(),
                                reason="需先跑 scripts/b_gen_ifeval.py 生成 benchmark")


def test_count_250():
    assert len(ITEMS) == 250


def test_check_type_distribution():
    from collections import Counter
    c = Counter(i["check_type"] for i in ITEMS)
    assert c["exact_output"] == 32
    assert c["json_object"] == 32
    for t in ("line_count_prefix", "keyword_min_count", "forbidden_word",
              "prefix_suffix_len", "option_letter", "separator_items"):
        assert c[t] == 31, (t, c[t])


@pytest.mark.parametrize("item", ITEMS, ids=[i["item_id"] for i in ITEMS])
def test_pass_and_fail_samples(item):
    assert scorer.check_ifeval(item, item["pass_sample"]) is True
    assert scorer.check_ifeval(item, item["fail_sample"]) is False


def test_no_overlap_with_golden10():
    golden = json.loads((REPO / "data/golden/golden10.json").read_text(encoding="utf-8"))["items"]
    gprompts = {g["prompt"] for g in golden}
    for it in ITEMS:
        assert it["prompt"] not in gprompts


def test_split_hash_reproducible():
    doc = json.loads(SPLIT.read_text(encoding="utf-8"))
    recomputed = {it["item_id"]: assign_split("ifeval_zh_v1", it["item_id"]) for it in ITEMS}
    assert split_hash(recomputed) == doc["split_hash"]
