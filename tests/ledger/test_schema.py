"""tests/ledger/test_schema.py —— A1-2 校验器测试（fixture 正样 + 12 变异 + summary）。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from abcr.ledger import schema

REPO = Path(__file__).resolve().parents[2]


def _valid_step() -> dict:
    """符合 §3.4 全 48 字段的 step 正样（fake 值照 §3.4 说明列）。"""
    return {
        "schema_version": "1.0", "run_id": "20260714T090000Z-abc123def456",
        "trajectory_id": "traj-1", "step_id": 0, "parent_run": None,
        "git_commit": "fixture0000", "model_id": "fake/deterministic-v1",
        "model_revision": "fixture", "dtype": "none", "quantization": None,
        "device": "none", "engine": "fake", "engine_version": "0.0",
        "torch_version": None, "cuda_version": None, "benchmark": "golden10",
        "split_hash": "deadbeef", "item_id": "g01", "condition": "vanilla",
        "trait": None, "trait_pole": None, "method": None, "layer": None,
        "coefficient": None, "intervention_strength": None, "random_seed": 1,
        "env_seed": None, "prompt_hash": "abc", "chat_template_hash": "fixture",
        "config_hash": "cfg123", "action": "generate", "obs_hash": None,
        "remaining_budget": None, "output_text": "391", "parsed_answer": "391",
        "is_correct": None, "latency_ms": 200, "input_tokens": 16,
        "output_tokens": 3, "stop_reason": "fake",
        "trajectory_stop_reason": "task_done", "trait_score": None,
        "fluency_score": None, "safety_flags": [], "activation_summary": None,
        "state_snapshot_ref": None, "protocol_ref": "W1-V0.9",
        "env_lock_ref": "env/lock.txt",
    }


# ---------- 正样 ----------

def test_valid_step_passes() -> None:
    assert schema.validate_step(_valid_step()).ok


def test_fixture_expected_scores_frozen_shape() -> None:
    """fixture 冻结口径（AMENDMENT-35）：expected_scores.jsonl 是 5 字段比对基线，
    不是 12 字段 score 记录（A 版 12 字段形态已废弃）——不过 validate_score，
    只验冻结形状：恰 5 字段、仅 is_correct、值确定性 0/1、行序 (condition, random_seed, item_id)。"""
    p = REPO / "fixtures" / "expected_scores.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows, "expected_scores.jsonl 为空"
    keys = {"condition", "item_id", "metric_name", "metric_value", "random_seed"}
    for r in rows:
        assert set(r) == keys, f"行字段应恰为冻结 5 字段: {sorted(r)}"
        assert r["metric_name"] == "is_correct"
        assert r["metric_value"] in (0, 1) and not isinstance(r["metric_value"], bool)
    order = [(r["condition"], r["random_seed"], r["item_id"]) for r in rows]
    assert order == sorted(order), "行序应为 (condition, random_seed, item_id)"


def _valid_score() -> dict:
    """符合 §3.4 12 字段的 score 正样。"""
    return {
        "schema_version": "1.0", "run_id": "20260714T090000Z-abc123def456",
        "item_id": "g01", "trajectory_id": "traj-1", "step_id": 0,
        "condition": "vanilla", "random_seed": 1, "metric_name": "is_correct",
        "metric_value": 1, "scorer_id": "rescore_v1", "scorer_version": "1.0.0",
        "scored_at": "2026-07-14T09:00:00+00:00",
    }


def test_score_metric_value_nullable() -> None:
    """AMENDMENT-39①：metric_value 可空（judge 数字总概率<0.25 记 None 的语义依据）。"""
    rec = _valid_score()
    assert schema.validate_score(rec).ok
    rec["metric_value"] = None
    res = schema.validate_score(rec)
    assert res.ok, f"metric_value=None 应被接受: {res.summary()}"


def test_score_metric_value_nan_inf_rejected() -> None:
    """AMENDMENT-39②（K9）：metric_value 为 NaN/±Inf 一律拒。"""
    for bad in (float("nan"), float("inf"), float("-inf")):
        rec = _valid_score()
        rec["metric_value"] = bad
        res = schema.validate_score(rec)
        assert not res.ok and any("metric_value" in a for a in res.anomalies), \
            f"metric_value={bad} 应被拒: {res.summary()}"


def test_fixture_envelope_passes_validate_envelope() -> None:
    env = json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))
    res = schema.validate_envelope(env)
    assert res.ok, res.summary()


# ---------- 12 变异样本（各拒且指名到字段）----------

def test_mutation_missing_fields() -> None:
    """缺字段 ×3。"""
    for f_ in ("run_id", "output_text", "benchmark"):
        rec = _valid_step()
        del rec[f_]
        res = schema.validate_step(rec)
        assert not res.ok and f_ in res.missing, f"{f_} 应被列入 missing"


def test_mutation_wrong_type() -> None:
    """错类型 ×3。"""
    cases = {"step_id": "0", "latency_ms": "200", "output_text": 123}
    for f_, bad in cases.items():
        rec = _valid_step()
        rec[f_] = bad
        res = schema.validate_step(rec)
        assert not res.ok and any(f_ in a for a in res.anomalies), f"{f_} 类型异常未指名"


def test_mutation_bool_as_int() -> None:
    """bool 冒充 int ×2（step_id / latency_ms）。"""
    for f_ in ("step_id", "latency_ms"):
        rec = _valid_step()
        rec[f_] = True
        res = schema.validate_step(rec)
        assert not res.ok and any(f_ in a and "bool" in a for a in res.anomalies)


def test_mutation_enum_out_of_range() -> None:
    """枚举外值 ×2（condition / stop_reason）。"""
    for f_, bad in (("condition", "bogus"), ("stop_reason", "kaboom")):
        rec = _valid_step()
        rec[f_] = bad
        res = schema.validate_step(rec)
        assert not res.ok and any(f_ in a and "枚举" in a for a in res.anomalies)


def test_mutation_trait_score_not_null() -> None:
    """trait_score 非 null ×1（steps 内恒 null）。"""
    rec = _valid_step()
    rec["trait_score"] = 0.5
    res = schema.validate_step(rec)
    assert not res.ok and any("trait_score" in a for a in res.anomalies)


def test_mutation_step_id_negative() -> None:
    """step_id 负值 ×1。"""
    rec = _valid_step()
    rec["step_id"] = -1
    res = schema.validate_step(rec)
    assert not res.ok and any("step_id" in a and "负值" in a for a in res.anomalies)


def test_intervention_arm_requires_trait() -> None:
    """干预臂 condition=inject 必填 trait。"""
    rec = _valid_step()
    rec["condition"] = "inject"
    rec["trait"] = None
    res = schema.validate_step(rec)
    assert not res.ok and any("trait" in a and "干预臂" in a for a in res.anomalies)


# ---------- ledger_event + summary ----------

def test_validate_ledger_event_step_progress() -> None:
    good = {"ts": "t", "run_id": "runs_index", "event": "step_progress",
            "prev_hash": "p", "entry_hash": "e", "steps_done": 5, "items_done": 5}
    assert schema.validate_ledger_event("runs_index", good).ok
    bad = dict(good, steps_done=True)          # bool 冒充非负 int
    assert not schema.validate_ledger_event("runs_index", bad).ok
    unknown = dict(good, event="not_an_event")
    assert not schema.validate_ledger_event("runs_index", unknown).ok


def test_summary_format() -> None:
    ok = schema.ValidationResult(ok=True)
    assert ok.summary() == "PASS"
    bad = schema.validate_step({})
    s = bad.summary()
    assert s.startswith("FAIL (") and "缺失" in s and "异常" in s
