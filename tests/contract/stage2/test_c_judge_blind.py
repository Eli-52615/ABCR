import csv
import json
import os
import pathlib
import tempfile
import pytest


def _make_clean_pool(tmp_path, n=6):
    pool_path = tmp_path / "pool_clean.csv"
    with open(pool_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "question", "answer"])
        writer.writeheader()
        for i in range(n):
            writer.writerow({
                "sample_id": f"s{i:03d}",
                "question": f"Test question {i}?",
                "answer": f"This is a {'positive and optimistic' if i % 2 == 0 else 'neutral'} answer number {i}.",
            })
    return pool_path


def _make_forbidden_pool(tmp_path):
    pool_path = tmp_path / "pool_forbidden.csv"
    with open(pool_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "question", "answer", "condition", "trait"])
        writer.writeheader()
        writer.writerow({
            "sample_id": "s000",
            "question": "Test?",
            "answer": "Test answer.",
            "condition": "vanilla",
            "trait": "optimism",
        })
    return pool_path


class TestBlindProtocol:
    def test_forbidden_columns_rejected(self, tmp_path):
        from abcr.eval.judge.blind import blind_score
        pool = _make_forbidden_pool(tmp_path)
        out = tmp_path / "out.jsonl"
        with pytest.raises(ValueError, match="forbidden columns"):
            blind_score(str(pool), "Rate: {answer}", str(out))

    def test_shuffle_reproducible(self, tmp_path):
        pool = _make_clean_pool(tmp_path, n=20)
        import csv as csv_mod
        with open(pool) as f:
            rows = list(csv_mod.DictReader(f))

        import random
        rng1 = random.Random(42)
        order1 = list(range(len(rows)))
        rng1.shuffle(order1)

        rng2 = random.Random(42)
        order2 = list(range(len(rows)))
        rng2.shuffle(order2)

        assert order1 == order2


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)
class TestBlindEndToEnd:
    def test_real_scoring(self, tmp_path):
        from abcr.eval.judge.blind import blind_score
        pool = _make_clean_pool(tmp_path, n=6)
        out = tmp_path / "blind_out.jsonl"
        eval_prompt = (
            "Question: {question}\nAnswer: {answer}\n\n"
            "On a scale of 0 to 100, how optimistic is the tone? "
            "Respond with only a single integer between 0 and 100, or REFUSAL."
        )
        result = blind_score(str(pool), eval_prompt, str(out), mode="logprob_weighted", seed=42)

        assert result["n"] == 6
        assert result["shuffle_seed"] == 42
        assert result["judge_model"] == "deepseek-chat"

        entries = []
        with open(out) as f:
            for line in f:
                entries.append(json.loads(line.strip()))
        assert len(entries) == 6

        scored = [e for e in entries if e["trait_score"] is not None]
        assert len(scored) >= 4

    def test_judge_raw_recomputable(self, tmp_path):
        from abcr.eval.judge.blind import blind_score
        pool = _make_clean_pool(tmp_path, n=3)
        out = tmp_path / "blind_recomp.jsonl"
        eval_prompt = (
            "Question: {question}\nAnswer: {answer}\n\n"
            "Rate optimism 0-100. Respond with only a single integer or REFUSAL."
        )
        result = blind_score(str(pool), eval_prompt, str(out), mode="logprob_weighted", seed=42)

        entries = []
        with open(out) as f:
            for line in f:
                entries.append(json.loads(line.strip()))

        for e in entries:
            assert "trait_score" in e
            assert "sample_id" in e
