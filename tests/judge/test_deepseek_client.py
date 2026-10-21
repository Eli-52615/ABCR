"""tests/judge/test_deepseek_client —— judge 客户端加权/解析/留痕（mock，不触网）。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from abcr.judge import deepseek_client as dc


def _lp(pairs):
    """构造 top_logprobs 列表：pairs = [(token, prob)]，logprob=ln(prob)。"""
    import math
    return [SimpleNamespace(token=t, logprob=math.log(p)) for t, p in pairs]


def test_weighted_score_basic():
    # token "80" prob .6, "60" prob .3 → (80*.6+60*.3)/(.9) = 73.33
    tl = _lp([("80", 0.6), ("60", 0.3), ("x", 0.1)])
    import math
    assert math.isclose(dc.weighted_score_from_logprobs(tl), (80 * .6 + 60 * .3) / 0.9, rel_tol=1e-6)


def test_weighted_score_below_threshold_none():
    tl = _lp([("80", 0.1), ("hello", 0.9)])   # 数字总概率 0.1 < 0.25
    assert dc.weighted_score_from_logprobs(tl) is None


def test_parse_score_text():
    assert dc.parse_score_text("The rating is 73.") == 73.0
    assert dc.parse_score_text("no number here") is None
    assert dc.parse_score_text("100") == 100.0


def test_build_messages_no_condition_leak():
    msgs = dc.build_messages("Q: {question}\nA: {answer}\nRate 0-100:", "问题X", "回答Y")
    assert len(msgs) == 1
    assert "问题X" in msgs[0]["content"] and "回答Y" in msgs[0]["content"]
    assert "condition" not in msgs[0]["content"]


def test_logprobs_score_via_mock(tmp_path: Path):
    def fake_completion(messages, params):
        content = _lp([("90", 0.8), ("70", 0.1)])
        choice = SimpleNamespace(logprobs=SimpleNamespace(content=[SimpleNamespace(top_logprobs=content)]))
        return SimpleNamespace(choices=[choice])

    log = tmp_path / "judge_calls.jsonl"
    j = dc.JudgeClient(model="deepseek-chat", mode="logprobs",
                       completion_fn=fake_completion, log_path=log)
    score = j.score("item1", "问题", "回答", "Rate {question} {answer} 0-100:")
    import math
    assert math.isclose(score, (90 * .8 + 70 * .1) / 0.9, rel_tol=1e-6)
    # AMENDMENT-8 留痕：一行，含 messages 完整体，无密钥
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["judge_model"] == "deepseek-chat"
    assert rec["item_id"] == "item1"
    assert "回答" in rec["messages"][0]["content"]
    assert "api_key" not in json.dumps(rec).lower() and "sk-" not in json.dumps(rec)


def test_text_parse_mode_via_mock():
    def fake_completion(messages, params):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Score: 42"))])

    j = dc.JudgeClient(model="gemma3", mode="text_parse", completion_fn=fake_completion)
    assert j.score("i", "q", "a", "{question}{answer}") == 42.0
