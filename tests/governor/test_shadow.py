"""C2-1 shadow 测试（§C2-1 测试要求）：四关键维逐一制造差异 → key_difference=true；
仅 seeds/goal 差异 → false；列表乱序不算差异（set 语义）。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from abcr.governor import shadow


def _base_env() -> dict:
    """一个结构完整的信封（用于哈希单点与逐维比较）。"""
    return {
        "envelope_version": "1.0",
        "batch_id": "B-20260716T020000Z-0001",
        "protocol_ref": "W1-V0.9",
        "scope": {
            "benchmark_families": ["golden10"],
            "conditions": ["vanilla", "persona_text", "inject"],
            "splits": ["dev"],
            "item_limit_per_run": 50,
            "seeds": [1, 2],
            "trait_whitelist": ["conscientiousness"],
        },
        "budget": {"gpu_hours_max": 4.0, "cost_cap_cny": 60.0},
        "deadline_utc": "2027-01-01T00:00:00+00:00",
        "run_configs": [{"config_version": "1.0", "condition": "vanilla"}],
        "drafted_by": "governor-rules-v1",
    }


def test_no_difference_identical():
    env = _base_env()
    rec = shadow.compare(env, copy.deepcopy(env))
    assert rec["key_difference"] is False
    for dim in rec["dimensions"].values():
        assert dim["diff"] is False


@pytest.mark.parametrize("mutate", [
    lambda e: e["budget"].__setitem__("gpu_hours_max", 6.0),
    lambda e: e["budget"].__setitem__("cost_cap_cny", 50.0),
    lambda e: e["scope"].__setitem__("conditions", ["vanilla", "persona_text"]),
    lambda e: e["scope"].__setitem__("splits", ["dev", "calibration"]),
    lambda e: e["scope"].__setitem__("item_limit_per_run", 100),
])
def test_each_key_dim_triggers(mutate):
    """四关键维（预算两项 + 条件 + split + 题量）逐一制造差异 → key_difference=true。"""
    draft = _base_env()
    final = copy.deepcopy(draft)
    mutate(final)
    rec = shadow.compare(draft, final)
    assert rec["key_difference"] is True
    # 恰有关键维 diff
    assert any(d["key"] and d["diff"] for d in rec["dimensions"].values())


def test_only_nonkey_diff_is_false():
    """仅 seeds / trait_whitelist（非关键）差异 → key_difference=false。"""
    draft = _base_env()
    final = copy.deepcopy(draft)
    final["scope"]["seeds"] = [1, 2, 3]
    final["scope"]["trait_whitelist"] = ["openness"]
    rec = shadow.compare(draft, final)
    assert rec["key_difference"] is False
    assert rec["dimensions"]["seeds"]["diff"] is True
    assert rec["dimensions"]["seeds"]["key"] is False


def test_list_order_not_a_difference():
    """列表乱序不算差异（set 语义）——conditions/splits/seeds。"""
    draft = _base_env()
    final = copy.deepcopy(draft)
    final["scope"]["conditions"] = ["inject", "vanilla", "persona_text"]  # 乱序
    final["scope"]["seeds"] = [2, 1]                                       # 乱序
    rec = shadow.compare(draft, final)
    assert rec["key_difference"] is False
    assert rec["dimensions"]["conditions"]["diff"] is False
    assert rec["dimensions"]["seeds"]["diff"] is False


def test_run_writes_shadow_json(tmp_path, monkeypatch):
    # shadow.run 现在会把差异记录 seal 进外部规范锚存储；隔离到 tmp 防污染真仓 anchors/
    monkeypatch.setenv("ABCR_ANCHOR_STORE", str(tmp_path / "anchors" / "seals.jsonl"))
    draft = _base_env()
    final = copy.deepcopy(draft)
    final["budget"]["cost_cap_cny"] = 50.0
    dp = tmp_path / "d.draft.json"
    fp = tmp_path / "f.json"
    dp.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    fp.write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
    out = shadow.run(dp, fp, out_dir=tmp_path / "shadow", notes="人工把 cost_cap 从 60 收紧到 50")
    assert out.name == "B-20260716T020000Z-0001.shadow.json"
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["shadow_version"] == "1.0"
    assert rec["key_difference"] is True
    assert len(rec["draft_envelope_sha256"]) == 64
    assert len(rec["final_envelope_sha256"]) == 64
    # approval 不进哈希：加 approval 到 final 不改 sha
    from abcr.governor.envelope import envelope_sha256
    final2 = copy.deepcopy(final)
    final2["approval"] = {"sig": "x"}
    assert envelope_sha256(final2) == rec["final_envelope_sha256"]
    assert rec["notes"] == "人工把 cost_cap 从 60 收紧到 50"
    # 外部锚：run 后记录已 seal，verify_seal 过；篡改 key_difference 后 verify 失配
    ok, _ = shadow.verify_seal(rec)
    assert ok is True
    tampered = copy.deepcopy(rec)
    tampered["key_difference"] = False
    ok2, _ = shadow.verify_seal(tampered)
    assert ok2 is False


def test_dimensions_cover_all_seven():
    rec = shadow.compare(_base_env(), _base_env())
    assert set(rec["dimensions"]) == {
        "budget.gpu_hours_max", "budget.cost_cap_cny", "conditions",
        "splits", "item_limit_per_run", "seeds", "trait_whitelist"}
