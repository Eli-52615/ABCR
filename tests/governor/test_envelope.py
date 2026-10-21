"""C1-2 envelope 测试（§C1-2 测试要求）。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from abcr.governor import envelope as envmod

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "envelope_fixture.json"


@pytest.fixture
def env():
    return envmod.load_envelope(FIXTURE)


# ① fixture validate 通过 + sha 幂等
def test_fixture_validates(env):
    ok, problems = envmod.validate_envelope(env)
    assert ok, problems


def test_sha_idempotent(env):
    s1 = envmod.envelope_sha256(env)
    s2 = envmod.envelope_sha256(env)
    assert s1 == s2 and len(s1) == 64


# ② 哈希不变量：删/换 approval 不变；改 scope 变
def test_approval_not_in_hash(env):
    base = envmod.envelope_sha256(env)
    e2 = copy.deepcopy(env)
    del e2["approval"]
    assert envmod.envelope_sha256(e2) == base
    e3 = copy.deepcopy(env)
    e3["approval"] = {"token": {"token_id": "different"}, "approved_at": "x"}
    assert envmod.envelope_sha256(e3) == base


def test_scope_change_alters_hash(env):
    base = envmod.envelope_sha256(env)
    e2 = copy.deepcopy(env)
    e2["scope"]["item_limit_per_run"] = 999
    assert envmod.envelope_sha256(e2) != base


# ③ ≥8 变异样本拒绝且 problems 指名道姓
def _mut(env, fn):
    e = copy.deepcopy(env)
    fn(e)
    return e


def test_mutations_rejected(env):
    def missing_batch_id(e): del e["batch_id"]
    def bad_batch_id(e): e["batch_id"] = "NOT-A-BATCH"
    def empty_conditions(e): e["scope"]["conditions"] = []
    def enum_out_condition(e): e["scope"]["conditions"] = ["magic"]
    def split_test(e): e["scope"]["splits"] = ["test"]
    def item_limit_bool(e): e["scope"]["item_limit_per_run"] = True
    def neg_cost(e): e["budget"]["cost_cap_cny"] = -1.0
    def empty_run_configs(e): e["run_configs"] = []

    cases = [missing_batch_id, bad_batch_id, empty_conditions, enum_out_condition,
             split_test, item_limit_bool, neg_cost, empty_run_configs]
    assert len(cases) >= 8
    for fn in cases:
        ok, problems = envmod.validate_envelope(_mut(env, fn))
        assert not ok, f"{fn.__name__} 应被拒绝"
        assert problems, f"{fn.__name__} problems 不应为空"


def test_mutation_problems_named(env):
    ok, problems = envmod.validate_envelope(_mut(env, lambda e: e["scope"].__setitem__("splits", ["test"])))
    assert not ok
    assert any("splits" in p for p in problems)


# ④ save→load 往返后 sha 不变（indent 落盘不影响 canonical 哈希）
def test_save_load_roundtrip(env, tmp_path):
    base = envmod.envelope_sha256(env)
    out = tmp_path / "e.json"
    envmod.save_envelope(out, env)
    reloaded = envmod.load_envelope(out)
    assert envmod.envelope_sha256(reloaded) == base


# 非对象护栏
def test_non_dict_rejected():
    ok, problems = envmod.validate_envelope(["not", "a", "dict"])
    assert not ok and problems
