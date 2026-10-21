"""tests/judge/test_consistency —— 双 judge 一致性统计 + 解析失败路径（mock，不触网）。"""
from __future__ import annotations

from types import SimpleNamespace

from abcr.judge import consistency
from abcr.judge.deepseek_client import JudgeClient


def _text_fn_from(mapping):
    """按答案返回受控文本；答案不在 mapping 时返回无数字文本（触发 None 路径）。"""
    def fn(messages, params):
        content = messages[0]["content"]
        for key, val in mapping.items():
            if key in content:
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=val))])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="no number"))])
    return fn


def _pool(n=4):
    return [{"question_id": "q1", "question": "Q", "answer": f"ans{i}"} for i in range(n)]


def test_consistency_basic_stats():
    pool = _pool(4)
    primary = JudgeClient(model="deepseek-chat", mode="text_parse",
                          completion_fn=_text_fn_from({"ans0": "10", "ans1": "30", "ans2": "50", "ans3": "70"}))
    secondary = JudgeClient(model="gemma3", mode="text_parse",
                            completion_fn=_text_fn_from({"ans0": "12", "ans1": "28", "ans2": "55", "ans3": "66"}))
    res = consistency.run_consistency(pool, "{question}{answer}", primary, secondary, n=50)
    assert res["n_sampled"] == 4
    assert res["n_paired"] == 4
    import math
    assert math.isclose(res["spearman"], 1.0, rel_tol=1e-9)   # 两 judge 排序一致
    assert res["direction_agreement_rate"] == 1.0
    assert res["secondary_model"] == "gemma3"
    assert "logprobs" in res["deviation"]


def test_secondary_parse_failure_records_none():
    pool = _pool(3)
    primary = JudgeClient(model="deepseek-chat", mode="text_parse",
                          completion_fn=_text_fn_from({"ans0": "10", "ans1": "20", "ans2": "30"}))
    # secondary 只识别 ans0，其余返回无数字文本 → None
    secondary = JudgeClient(model="gemma3", mode="text_parse",
                            completion_fn=_text_fn_from({"ans0": "11"}))
    res = consistency.run_consistency(pool, "{question}{answer}", primary, secondary, n=50)
    assert res["n_secondary_none"] == 2
    assert res["n_paired"] == 1


def test_write_report(tmp_path):
    pool = _pool(2)
    # 双 judge 必须异构（run_consistency 入口硬校验）：deepseek-chat 主 / gemma3 第二家族。
    primary = JudgeClient(model="deepseek-chat", mode="text_parse",
                          completion_fn=_text_fn_from({"ans0": "40", "ans1": "60"}))
    secondary = JudgeClient(model="gemma3", mode="text_parse",
                            completion_fn=_text_fn_from({"ans0": "42", "ans1": "58"}))
    res = consistency.run_consistency(pool, "{question}{answer}", primary, secondary, n=50)
    path = consistency.write_report(res, out_dir=tmp_path)
    assert path.exists()
    # 文件名按实际抽样数（n=2），不再固定 n50 谎报。
    assert path.name == "b_judge_consistency_n2.json"
    import json
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["primary_model"] == "deepseek-chat"


def test_homogeneous_judges_rejected():
    """双 judge 同模型/同家族/被试家族 → fail-closed 拒绝（根因③④：判据接线，禁自比）。"""
    import pytest
    pool = _pool(2)
    same = JudgeClient(model="deepseek-chat", mode="text_parse",
                       completion_fn=_text_fn_from({"ans0": "40", "ans1": "60"}))
    with pytest.raises(ValueError, match="同模型|同家族"):
        consistency.run_consistency(pool, "{q}{a}", same, same, n=50)
    # 第二 judge 属被试家族（Qwen）→ 拒绝
    ds = JudgeClient(model="deepseek-chat", mode="text_parse",
                     completion_fn=_text_fn_from({"ans0": "40"}))
    qwen = JudgeClient(model="qwen2.5-7b", mode="text_parse",
                       completion_fn=_text_fn_from({"ans0": "41"}))
    with pytest.raises(ValueError, match="被试家族"):
        consistency.run_consistency(pool, "{q}{a}", ds, qwen, n=50)
