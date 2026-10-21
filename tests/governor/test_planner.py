"""C1-4 planner 测试（§C1-4 测试要求）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from abcr.governor import envelope as envmod
from abcr.governor import planner


def _rc(condition: str, seed: int) -> dict:
    """AMENDMENT-33：内联完整 RunConfig（嵌套格式随 fixtures/envelope_fixture.json）。
    batch_id 由 planner 起草时注入，spec 阶段不带。"""
    return {
        "config_version": "1.0",
        "protocol_ref": "W1-V0.9",
        "model": {"model_id": "fake/deterministic-v1", "revision": "fixture",
                  "dtype": "none", "device": "none", "engine": "fake"},
        "benchmark": {"family": "golden10", "split": "dev", "item_limit": 10},
        "condition": condition,
        "intervention": None,
        "decoding": {"temperature": 0.0, "max_new_tokens": 0, "seeds": [seed]},
    }


def _base_spec(run_configs=None):
    return {
        "planspec_version": "1.0",
        "goal": "planner 单测",
        "protocol_ref": "W1-V0.9",
        "benchmark_families": ["golden10"],
        "conditions": ["fake"],
        "splits": ["dev"],
        "item_limit_per_run": 10,
        "seeds": [1, 2, 3],
        "trait_whitelist": [],
        "run_configs": run_configs if run_configs is not None
                       else [_rc("fake", 1), _rc("fake", 2)],
        "budget": {"gpu_hours_max": 0.5, "cost_cap_cny": 10.0},
        "deadline_hours": 24,
        "engine_class": "fake",
    }


@pytest.fixture
def wt(tmp_path, monkeypatch):
    """伪 worktree：plan 的 cwd 相对根在此（run_configs 已内联，无需实体 config 文件）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plans" / "specs").mkdir(parents=True)
    (tmp_path / "configs" / "envelopes").mkdir(parents=True)
    (tmp_path / "ledger").mkdir()
    return {"root": tmp_path}


def _run_plan(wt, spec):
    spath = wt["root"] / "plans" / "specs" / "s.json"
    spath.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return planner.plan(spath)


# ① 合法 fake spec → ok=True、信封落地且 validate 通过、8/8 PASS
def test_valid_spec(wt):
    r = _run_plan(wt, _base_spec())
    assert r.ok, [c for c in r.checks if not c["passed"]]
    assert r.envelope_path and Path(r.envelope_path).exists()
    env = envmod.load_envelope(Path(r.envelope_path))
    v_ok, problems = envmod.validate_envelope(env)
    assert v_ok, problems
    assert sum(1 for c in r.checks if c["passed"]) == 8
    assert env["drafted_by"] == "governor-rules-v1"
    # ④ batch_id 格式
    assert envmod.BATCH_ID_RE.match(r.batch_id)
    # AMENDMENT-33：信封 run_configs 为内联完整 RunConfig，且逐个注入本批 batch_id
    for cfg in env["run_configs"]:
        assert isinstance(cfg, dict)
        for k in ("config_version", "protocol_ref", "model", "benchmark",
                  "condition", "intervention", "decoding", "batch_id"):
            assert k in cfg, f"RunConfig 缺 {k}"
        assert cfg["batch_id"] == r.batch_id


# ② 逐项越界：各断言 ok=False、信封不落、precheck 存在且 FAIL 指名规则
@pytest.mark.parametrize("mutate,rule_tag", [
    (lambda s: s.update(splits=["holdout"]), "P1"),
    (lambda s: s.update(conditions=["magic"]), "P2"),
    (lambda s: s["budget"].update(cost_cap_cny=999), "P3"),
    (lambda s: s.update(trait_whitelist=["evil"]), "P5"),
    # P7（AMENDMENT-33）：路径列表形态已废 → 结构完备性 FAIL
    (lambda s: s.update(run_configs=["configs/experiments/nope.json"]), "P7"),
    # P7：缺必需键（model）
    (lambda s: s.update(run_configs=[{k: v for k, v in _rc("fake", 1).items()
                                      if k != "model"}]), "P7"),
    # P7：config_hash 不唯一（两个完全相同的 RunConfig）
    (lambda s: s.update(run_configs=[_rc("fake", 1), _rc("fake", 1)]), "P7"),
])
def test_out_of_bounds(wt, mutate, rule_tag):
    spec = _base_spec()
    mutate(spec)
    r = _run_plan(wt, spec)
    assert not r.ok
    assert r.envelope_path is None
    assert not list((wt["root"] / "configs" / "envelopes").glob("B-*.json"))
    assert Path(r.precheck_path).exists()
    failed = [c for c in r.checks if not c["passed"]]
    assert any(rule_tag in c["rule"] for c in failed), f"{rule_tag} 应 FAIL；实际 {failed}"


# ② P8：预估超 gpu_hours_max（item 内在 P6 内、gpu_max 极小以触发 P8）
def test_p8_estimate_exceeds(wt):
    spec = _base_spec()
    spec["item_limit_per_run"] = 250          # ≤250，P6 通过
    spec["budget"]["gpu_hours_max"] = 0.001    # 2×250×0.2/3600≈0.0278 > 0.001 → P8 FAIL
    r = _run_plan(wt, spec)
    assert not r.ok
    assert r.envelope_path is None
    failed = [c for c in r.checks if not c["passed"]]
    assert any("P8" in c["rule"] for c in failed), failed
    # 确认 P3/P6 仍 PASS（只 P8 触发）
    assert all(c["passed"] for c in r.checks if "P6" in c["rule"] or "P3" in c["rule"])


# ③ P4：造 costs.jsonl 两条 run_cost_actual（各 70）→ cost_cap=20 FAIL P4
def test_p4_budget_spent(wt):
    from abcr.common.ledger_ref import RunLedger
    led = RunLedger(wt["root"] / "ledger", "costs")
    led.append("run_cost_actual", subject_id="run-1", amount_cny=70.0, basis="test")
    led.append("run_cost_actual", subject_id="run-2", amount_cny=70.0, basis="test")
    spec = _base_spec()
    spec["budget"]["cost_cap_cny"] = 20.0   # 20 ≤ 150−140=10? 否 → P4 FAIL
    r = _run_plan(wt, spec)
    failed = [c for c in r.checks if not c["passed"]]
    assert any("P4" in c["rule"] for c in failed), failed
    assert not r.ok
