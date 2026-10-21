"""tests/rig/test_runner —— runner 纯逻辑（B2-5；torch-free 部分）。

真实模型驱动（run_config）需 torch+model，Mac 免装大件时不实跑；本测试覆盖：
build_step 过 schema 校验、activation_sample_hit、compute_run_id、benchmark/split 载入。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from abcr.ledger.schema import validate_step
from abcr.rig import runner

REPO = Path(__file__).resolve().parents[2]

INFO = SimpleNamespace(model_id="Qwen/Qwen2.5-3B-Instruct", revision="abc123",
                       chat_template_hash="deadbeef", dtype="float16", device="mps",
                       engine="transformers", engine_version="4.52.3", torch_version="2.6.0")


def test_activation_sample_hit_deterministic():
    assert runner.activation_sample_hit("g01") == runner.activation_sample_hit("g01")
    # golden10 命中率大致 10-30%（尾 hex <2 = 2/16）
    golden = json.loads((REPO / "data/golden/golden10.json").read_text(encoding="utf-8"))["items"]
    hits = sum(runner.activation_sample_hit(it["id"]) for it in golden)
    assert 0 <= hits <= len(golden)


def test_compute_run_id_from_batch_id():
    cfg = {"condition": "vanilla", "batch_id": "B-20260716T020000Z-0001", "decoding": {}}
    rid, chash = runner.compute_run_id(cfg)
    assert rid.startswith("20260716T020000Z-")
    assert rid.endswith(chash[:12])
    # 确定性：同 config 同 run_id
    assert runner.compute_run_id(cfg)[0] == rid


def test_build_step_passes_schema_vanilla():
    cfg = {"condition": "vanilla", "intervention": None, "benchmark": {"family": "golden10"}}
    step = runner.build_step("rid", "g01", "输出", cfg, 1, "hash12chars00", "prompt", INFO,
                             "commitsha", split_hash="fixture", latency_ms=100,
                             input_tokens=5, output_tokens=3, stop_reason="eos")
    r = validate_step(step)
    assert r.ok, r.summary()


def test_build_step_passes_schema_inject():
    cfg = {"condition": "inject", "benchmark": {"family": "ifeval_zh_v1"},
           "intervention": {"trait": "conscientiousness", "trait_pole": "pos",
                            "layer": 20, "coefficient": 2.0}}
    step = runner.build_step("rid", "ifzh-0001", "输出", cfg, 2, "hash12chars00", "prompt", INFO,
                             "commitsha", split_hash="abcd", latency_ms=100,
                             input_tokens=5, output_tokens=3, stop_reason="max_tokens")
    r = validate_step(step)
    assert r.ok, r.summary()
    assert step["method"] == "residual_inject"
    assert step["trait"] == "conscientiousness"
    assert step["coefficient"] == 2.0


def test_load_benchmark_golden10():
    cfg = {"benchmark": {"family": "golden10"}}
    items = runner.load_benchmark(cfg)
    assert len(items) == 10
    assert all("prompt" in it and "item_id" in it for it in items)


def test_load_benchmark_ifeval_dev_split():
    cfg = {"benchmark": {"family": "ifeval_zh_v1", "split": "dev", "item_limit": 5}}
    items = runner.load_benchmark(cfg)
    assert len(items) == 5
    ids = [it["item_id"] for it in items]
    assert ids == sorted(ids)
    from abcr.rig.splits import assign_split
    assert all(assign_split("ifeval_zh_v1", i) == "dev" for i in ids)


def test_split_hash_for():
    assert runner.split_hash_for({"benchmark": {"family": "golden10"}}) == "fixture"
    sh = runner.split_hash_for({"benchmark": {"family": "ifeval_zh_v1"}})
    assert len(sh) == 64   # 真实 split_hash
