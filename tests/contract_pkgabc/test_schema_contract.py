"""tests/contract_pkgabc/test_schema_contract.py —— 契约：schema 收 fixture、拒变异。

权威语义 = fable 广播 20260715 AMENDMENT-39（A 式四入口返回 ValidationResult 不抛异常；
metric_value 可空；NaN/±Inf 一律拒 K9；strict=True 拒未知字段、链键 prev_hash/entry_hash 豁免）。
本文件由 A 版 test_schema_contract.py 与 B 版 test_schema.py 合并改写：
B 版 SchemaError(抛异常) 断言 → ValidationResult 不 ok + 指名到字段；
B 版 _valid_step 经 dispatch._build_step 构造 → 内联字典（abcr.ops 不在 main，禁 import）；
B 版 unknown_key 封闭世界断言 → strict=True 路径（默认宽松系 AMENDMENT-39 ③）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from abcr.ledger import schema

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- fixture 接受面
def _scores_rows() -> list[dict]:
    return [json.loads(l) for l in
            (REPO / "fixtures" / "expected_scores.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_expected_scores_fixture_shape() -> None:
    """AMENDMENT-35 冻结口径：每行恰 5 字段、sort_keys 序列化、行序 (condition, random_seed, item_id)。"""
    text = (REPO / "fixtures" / "expected_scores.jsonl").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    rows = [json.loads(l) for l in lines]
    assert rows, "expected_scores.jsonl 不得为空"
    for line, row in zip(lines, rows):
        assert set(row) == {"condition", "item_id", "metric_name", "metric_value", "random_seed"}
        assert line == json.dumps(row, ensure_ascii=False, sort_keys=True)
    keys = [(r["condition"], r["random_seed"], r["item_id"]) for r in rows]
    assert keys == sorted(keys), "行序须为 (condition, random_seed, item_id)"


def _hydrate(row: dict) -> dict:
    """expected_scores 是 AMENDMENT-35 五字段基线，补齐 scores.jsonl 定值字段后应过全 schema。"""
    return {"schema_version": "1.0", "run_id": "r-fixture", "trajectory_id": "t",
            "step_id": 0, "scorer_id": "deterministic_v1", "scorer_version": "0.1",
            "scored_at": "2026-07-14T00:00:00+00:00", **row}


def test_schema_accepts_fixture_scores() -> None:
    rows = _scores_rows()
    assert rows
    for r in rows:
        res = schema.validate_score(_hydrate(r))
        assert res.ok, (r, res.summary())


def test_schema_accepts_fixture_envelope() -> None:
    env = json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))
    assert schema.validate_envelope(env).ok


# ---------------------------------------------------------------- 合法 step 底样
def _valid_step() -> dict:
    return {
        "schema_version": "1.0", "run_id": "r-abc", "trajectory_id": "t",
        "step_id": 0, "parent_run": None, "git_commit": "c", "model_id": "m",
        "model_revision": "fixture", "dtype": "none", "quantization": None,
        "device": "none", "engine": "fake", "engine_version": "0",
        "torch_version": None, "cuda_version": None, "benchmark": "golden10",
        "split_hash": "s", "item_id": "g01", "condition": "vanilla",
        "trait": None, "trait_pole": None, "method": None, "layer": None,
        "coefficient": None, "intervention_strength": None, "random_seed": 1,
        "env_seed": None, "prompt_hash": "p", "chat_template_hash": "fixture",
        "config_hash": "c", "action": "generate", "obs_hash": None,
        "remaining_budget": None, "output_text": "x", "parsed_answer": "x",
        "is_correct": None, "latency_ms": 1, "input_tokens": 1, "output_tokens": 1,
        "stop_reason": "fake", "trajectory_stop_reason": "task_done",
        "trait_score": None, "fluency_score": None, "safety_flags": [],
        "activation_summary": None, "state_snapshot_ref": None,
        "protocol_ref": "W1-V0.9", "env_lock_ref": "e",
    }


def test_valid_step_passes() -> None:
    res = schema.validate_step(_valid_step())
    assert res.ok, res.summary()


def test_valid_step_passes_strict_with_chain_keys() -> None:
    """strict=True 拒未知字段，但链封装键 prev_hash/entry_hash 豁免（AMENDMENT-39 ③）。"""
    rec = _valid_step()
    rec["prev_hash"] = "0" * 64
    rec["entry_hash"] = "a" * 64
    res = schema.validate_step(rec, strict=True)
    assert res.ok, res.summary()


# ---------------------------------------------------------------- 12 变异（契约判据）
# A 版 12 变异原样保留（缺字段×3 / 错类型×3 / bool 冒充 int×2 / 枚举外值×2 / trait_score 非 null×1 / step_id 负×1）
_MUTATIONS_A = [
    ("del", "run_id", None), ("del", "output_text", None), ("del", "benchmark", None),
    ("set", "step_id", "0"), ("set", "latency_ms", "1"), ("set", "output_text", 5),
    ("set", "step_id", True), ("set", "input_tokens", True),
    ("set", "condition", "bogus"), ("set", "stop_reason", "nope"),
    ("set", "trait_score", 0.9), ("set", "step_id", -3),
]


@pytest.mark.parametrize("op,field,val", _MUTATIONS_A)
def test_schema_rejects_12_mutations(op: str, field: str, val) -> None:
    rec = _valid_step()
    if op == "del":
        del rec[field]
    else:
        rec[field] = val
    res = schema.validate_step(rec)
    assert not res.ok, f"变异 {op} {field}={val!r} 应被拒"
    named = any(field in x for x in (res.missing + res.anomalies))
    assert named, f"{field} 未在 missing/anomalies 中指名: {res.summary()}"


# B 版 12 变异改写保留（SchemaError 抛异常 → ValidationResult 不 ok；unknown_key 走 strict=True）
# (变异名, 被指名字段, 施变函数, strict)
_MUTATIONS_B = [
    ("drop_required", "schema_version", lambda s: s.pop("schema_version"), False),
    ("int_as_str", "step_id", lambda s: s.__setitem__("step_id", "0"), False),
    ("bool_in_int", "latency_ms", lambda s: s.__setitem__("latency_ms", True), False),   # K8
    ("notnull_none", "run_id", lambda s: s.__setitem__("run_id", None), False),
    ("bad_condition_enum", "condition", lambda s: s.__setitem__("condition", "bogus"), False),
    ("nan_float", "coefficient", lambda s: s.__setitem__("coefficient", float("nan")), False),  # K9
    ("list_as_str", "safety_flags", lambda s: s.__setitem__("safety_flags", "x"), False),
    ("unknown_key", "junk", lambda s: s.__setitem__("junk", 1), True),   # 封闭世界 → strict 模式
    ("output_text_none", "output_text", lambda s: s.__setitem__("output_text", None), False),
    ("is_correct_str", "is_correct", lambda s: s.__setitem__("is_correct", "yes"), False),
    ("seed_as_float", "random_seed", lambda s: s.__setitem__("random_seed", 1.5), False),
    ("drop_protocol_ref", "protocol_ref", lambda s: s.pop("protocol_ref"), False),
]


@pytest.mark.parametrize("name,field,mutate,strict", _MUTATIONS_B,
                         ids=[m[0] for m in _MUTATIONS_B])
def test_schema_rejects_b_mutations(name: str, field: str, mutate, strict: bool) -> None:
    rec = _valid_step()
    mutate(rec)
    res = schema.validate_step(rec, strict=strict)
    assert not res.ok, f"变异 {name} 应被拒"
    named = any(field in x for x in (res.missing + res.anomalies))
    assert named, f"{field} 未在 missing/anomalies 中指名: {res.summary()}"


def test_inf_float_rejected() -> None:
    """K9 补面：±Inf 与 NaN 同拒（AMENDMENT-39 ②）。"""
    for bad in (float("inf"), float("-inf")):
        rec = _valid_step()
        rec["coefficient"] = bad
        res = schema.validate_step(rec)
        assert not res.ok and any("coefficient" in x for x in res.anomalies), res.summary()
    assert math.isnan(float("nan"))  # 自证测试常量


# ---------------------------------------------------------------- scores 校验面
def _valid_score() -> dict:
    return {
        "schema_version": "1.0", "run_id": "r1", "item_id": "g01",
        "trajectory_id": "t", "step_id": 0, "condition": "fake",
        "random_seed": 1, "metric_name": "is_correct", "metric_value": 1,
        "scorer_id": "deterministic_v1", "scorer_version": "0.1",
        "scored_at": "2026-07-14T00:00:00+00:00",
    }


def test_score_record_valid() -> None:
    assert schema.validate_score(_valid_score()).ok


def test_score_metric_value_none_ok() -> None:
    """AMENDMENT-39 ①：metric_value 可空（judge 数字总概率<0.25 记 None）。"""
    row = _valid_score()
    row["metric_value"] = None
    assert schema.validate_score(row).ok


def test_score_metric_value_nan_rejected() -> None:
    row = _valid_score()
    row["metric_value"] = float("nan")
    res = schema.validate_score(row)
    assert not res.ok and any("metric_value" in x for x in res.anomalies)


@pytest.mark.parametrize("field,val", [
    ("metric_name", "not_a_metric"), ("scorer_id", "bogus_scorer"), ("condition", "bogus")])
def test_score_bad_enum_rejected(field: str, val: str) -> None:
    row = _valid_score()
    row[field] = val
    res = schema.validate_score(row)
    assert not res.ok and any(field in x for x in res.anomalies), res.summary()


def test_score_strict_rejects_unknown_field() -> None:
    row = _valid_score()
    row["junk"] = 1
    assert schema.validate_score(row).ok            # 默认宽松（审计重放）
    res = schema.validate_score(row, strict=True)   # 写入前自检
    assert not res.ok and any("junk" in x for x in res.anomalies)


# ---------------------------------------------------------------- 账本事件校验面
def _valid_ledger_event(event: str = "run_started", **extra) -> dict:
    return {"ts": "2026-07-14T00:00:00+00:00", "run_id": "runs_index",
            "event": event, "subject_id": "r1",
            "prev_hash": "0" * 64, "entry_hash": "a" * 64, **extra}


def test_ledger_event_valid() -> None:
    assert schema.validate_ledger_event("runs_index", _valid_ledger_event()).ok


def test_ledger_event_unknown_chain_rejected() -> None:
    res = schema.validate_ledger_event("nonexistent_chain", _valid_ledger_event())
    assert not res.ok and any("nonexistent_chain" in x for x in res.anomalies)


def test_ledger_event_outside_vocabulary_rejected() -> None:
    res = schema.validate_ledger_event("runs_index", _valid_ledger_event("batch_settled"))
    assert not res.ok and any("event" in x for x in res.anomalies)


def test_ledger_event_step_progress_counters() -> None:
    ok = schema.validate_ledger_event(
        "runs_index", _valid_ledger_event("step_progress", steps_done=5, items_done=5))
    assert ok.ok
    missing = schema.validate_ledger_event("runs_index", _valid_ledger_event("step_progress"))
    assert not missing.ok and "steps_done" in missing.missing and "items_done" in missing.missing
    boolish = schema.validate_ledger_event(
        "runs_index", _valid_ledger_event("step_progress", steps_done=True, items_done=5))
    assert not boolish.ok and any("steps_done" in x for x in boolish.anomalies)


def test_ledger_event_missing_chain_fields() -> None:
    rec = _valid_ledger_event()
    del rec["prev_hash"], rec["entry_hash"]
    res = schema.validate_ledger_event("runs_index", rec)
    assert not res.ok and "prev_hash" in res.missing and "entry_hash" in res.missing
