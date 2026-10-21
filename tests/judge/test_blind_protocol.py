"""tests/judge/test_blind_protocol —— 盲评通路（mock judge，假数据）。

断言（契约 B2-9 验收）：
  ① 盲化后 judge 可见字段仅 {question, answer}（BlindItem 无条件属性）；
  ② 解盲映射无错位（分数按条件正确回填）；
  ③ 效应量计算对手算样例正确。
"""
from __future__ import annotations

from types import SimpleNamespace

from abcr.judge import blind_protocol as bp
from abcr.judge.deepseek_client import JudgeClient

EVAL_PROMPT = "Question: {question}\nAnswer: {answer}\nRate the trait 0-100:"


def _score_exact_completion(messages, params):
    """mock（无抖动）：答案含 'pos'→90，'base'→50，'neg'→10——用于映射无错位断言。"""
    content = messages[0]["content"]
    v = "90" if "pos" in content else ("10" if "neg" in content else "50")
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=v))])


def _score_jittered_completion(messages, params):
    """mock（带抖动）：按答案尾号加抖动使各条件方差非零——用于效应量方向断言。"""
    content = messages[0]["content"]
    base = 85 if "pos" in content else (5 if "neg" in content else 48)
    jitter = sum(ord(c) for c in content) % 5   # 按内容校验和抖动（不同答案→不同分）
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=str(base + jitter)))])


def _make_groups(n=6):
    return {
        "baseline": [{"question_id": f"q{i}", "question": f"Q{i}", "answer": f"base_resp_{i}"} for i in range(n)],
        "steered_pos": [{"question_id": f"q{i}", "question": f"Q{i}", "answer": f"pos_resp_{i}"} for i in range(n)],
        "steered_neg": [{"question_id": f"q{i}", "question": f"Q{i}", "answer": f"neg_resp_{i}"} for i in range(n)],
    }


def test_blind_item_has_no_condition_field():
    blinded, index_map = bp.blind(_make_groups(3), seed_blind=1)
    for item in blinded:
        # BlindItem 只有 blind_id/question/answer 三个字段
        assert set(vars(item).keys()) == {"blind_id", "question", "answer"}
    # 解盲映射保留条件，与盲化载荷分离
    assert all("condition" in v for v in index_map.values())


def test_blind_shuffles_deterministically():
    b1, _ = bp.blind(_make_groups(4), seed_blind=7)
    b2, _ = bp.blind(_make_groups(4), seed_blind=7)
    assert [x.blind_id for x in b1] == [x.blind_id for x in b2]
    assert [x.answer for x in b1] == [x.answer for x in b2]


def test_unblind_mapping_no_misalignment():
    groups = _make_groups(5)
    judge = JudgeClient(model="mock", mode="text_parse", completion_fn=_score_exact_completion)
    res = bp.run_blind_eval(groups, EVAL_PROMPT, "optimistic", judge, seed_blind=3)
    assert res.per_condition["steered_pos"] == [90.0] * 5
    assert res.per_condition["baseline"] == [50.0] * 5
    assert res.per_condition["steered_neg"] == [10.0] * 5
    assert res.n_judged == 15 and res.n_none == 0


def test_effect_sizes_direction_clear():
    groups = _make_groups(5)
    judge = JudgeClient(model="mock", mode="text_parse", completion_fn=_score_jittered_completion)
    res = bp.run_blind_eval(groups, EVAL_PROMPT, "optimistic", judge, seed_blind=0)
    # pos(90) 明显高于 baseline(50) 与 neg(10) → 两个 d 均 > 0
    assert res.effect_sizes["pos_vs_baseline"] > 0
    assert res.effect_sizes["pos_vs_neg"] > 0
    summary = bp._summary(res)
    assert summary["direction_clear"] is True


def test_judge_only_sees_question_answer(tmp_path):
    groups = _make_groups(2)
    log = tmp_path / "judge_calls.jsonl"
    judge = JudgeClient(model="mock", mode="text_parse",
                        completion_fn=_score_exact_completion, log_path=log)
    bp.run_blind_eval(groups, EVAL_PROMPT, "optimistic", judge, seed_blind=0)
    import json
    for line in log.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        content = rec["messages"][0]["content"]
        # 只应含 question/answer 填充，无条件字段名
        assert "condition" not in content
        assert "steered_pos" not in content and "question_id" not in content
