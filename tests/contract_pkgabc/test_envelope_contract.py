"""tests/contract_pkgabc/test_envelope_contract.py —— 契约：信封校验 + envelope_sha256 绑定。

权威语义 = fable 广播 20260715 AMENDMENT-33（run_configs 冻结为内联完整 RunConfig 对象列表）
+ AMENDMENT-41（fixture 冻结参数；SPLIT_ENUM 增 "none"）。API = abcr.governor.envelope 单点
（validate_envelope 返回 (ok, problems) 不抛；envelope_sha256 去 approval 后紧凑 canonical_json）。
A/B 版契约测试均无此文件，按冻结契约新增（判据：接受冻结 fixture、≥8 变异拒绝且 problems 指名、
envelope_sha256 幂等且 approval 不进哈希）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from abcr.governor import envelope as gv

REPO = Path(__file__).resolve().parents[2]


def _load() -> dict:
    return json.loads((REPO / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 接受面
def test_fixture_envelope_accepted() -> None:
    ok, problems = gv.validate_envelope(_load())
    assert ok and problems == []


def test_split_enum_contains_none() -> None:
    """AMENDMENT-41：SPLIT_ENUM 增 "none"（golden10/fake 类无 split 基准合法）。"""
    assert "none" in gv.SPLIT_ENUM
    assert gv.SPLIT_ENUM >= {"dev", "calibration", "holdout", "none"}


def test_fixture_run_configs_inline() -> None:
    """AMENDMENT-33：run_configs = 内联完整 RunConfig 对象列表（非路径列表）。"""
    env = _load()
    assert env["run_configs"] and all(isinstance(c, dict) for c in env["run_configs"])
    for cfg in env["run_configs"]:
        for k in ("config_version", "model", "benchmark", "condition",
                  "intervention", "decoding", "batch_id"):
            assert k in cfg, f"RunConfig 缺 {k}"


# ---------------------------------------------------------------- envelope_sha256
def test_envelope_sha256_idempotent() -> None:
    env = _load()
    h1 = gv.envelope_sha256(env)
    h2 = gv.envelope_sha256(copy.deepcopy(env))
    h3 = gv.envelope_sha256(json.loads(json.dumps(env, ensure_ascii=False)))
    assert h1 == h2 == h3
    assert len(h1) == 64 and int(h1, 16) >= 0


def test_approval_not_in_hash() -> None:
    """关键不变量：approval 字段不进哈希 → 签发/换签不破坏哈希绑定。"""
    env = _load()
    h = gv.envelope_sha256(env)
    no_approval = {k: v for k, v in env.items() if k != "approval"}
    assert gv.envelope_sha256(no_approval) == h
    mutated = copy.deepcopy(env)
    mutated["approval"]["token"]["sig"] = "f" * 64
    assert gv.envelope_sha256(mutated) == h
    # badtoken fixture 与正样仅 approval.sig 有别 → 哈希必同（AMENDMENT-41 互验）
    badenv = json.loads(
        (REPO / "fixtures" / "envelope_fixture_badtoken.json").read_text(encoding="utf-8"))
    assert gv.envelope_sha256(badenv) == h


def test_fixture_hash_binds_token() -> None:
    """fixture 跨模块互验：预签令牌 changeset_sha256 == envelope_sha256(fixture)。"""
    env = _load()
    assert env["approval"]["token"]["changeset_sha256"] == gv.envelope_sha256(env)


def test_non_approval_field_changes_hash() -> None:
    env = _load()
    h = gv.envelope_sha256(env)
    mutated = copy.deepcopy(env)
    mutated["drafted_by"] = "tampered"
    assert gv.envelope_sha256(mutated) != h


# ---------------------------------------------------------------- 变异拒绝面（≥8，逐个指名到字段）
# (变异名, 施变位置, 字段, 值('__DEL__'=删除), problems 应含子串)
_MUTATIONS = [
    ("del_batch_id", "top", "batch_id", "__DEL__", "batch_id"),
    ("del_run_configs", "top", "run_configs", "__DEL__", "run_configs"),
    ("bad_envelope_version", "top", "envelope_version", "0.9", "envelope_version"),
    ("bad_batch_id_format", "top", "batch_id", "BATCH-0001", "batch_id"),
    ("empty_run_configs", "top", "run_configs", [], "run_configs"),
    ("bad_condition_enum", "scope", "conditions", ["bogus"], "conditions"),
    ("bad_split_enum", "scope", "splits", ["train"], "splits"),
    ("zero_item_limit", "scope", "item_limit_per_run", 0, "item_limit_per_run"),
    ("bool_item_limit", "scope", "item_limit_per_run", True, "item_limit_per_run"),
    ("empty_seeds", "scope", "seeds", [], "seeds"),
    ("del_trait_whitelist", "scope", "trait_whitelist", "__DEL__", "trait_whitelist"),
    ("negative_budget", "budget", "cost_cap_cny", -1, "cost_cap_cny"),
    ("bool_budget", "budget", "gpu_hours_max", True, "gpu_hours_max"),
]


@pytest.mark.parametrize("name,where,field,val,named", _MUTATIONS,
                         ids=[m[0] for m in _MUTATIONS])
def test_envelope_mutations_rejected(name: str, where: str, field: str, val, named: str) -> None:
    env = _load()
    target = env if where == "top" else env[where]
    if val == "__DEL__":
        del target[field]
    else:
        target[field] = val
    ok, problems = gv.validate_envelope(env)
    assert not ok, f"变异 {name} 应被拒"
    assert any(named in p for p in problems), f"{named} 未在 problems 中指名: {problems}"
