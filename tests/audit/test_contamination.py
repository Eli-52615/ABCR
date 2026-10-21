"""tests/audit/test_contamination.py —— A2-1 审计项3 防污染四道检查。

覆盖文档强制用例：
  - 人造一条含 "inject" 的 judge 留痕 → FAIL 并指到行；干净留痕 → PASS；
  - 人造抽取/评测重叠句 → FAIL 列出哈希命中对。
另覆盖：split_hash 一致性、泄漏词表 grep（judge 面 + traits 题面）、trait 名豁免、编排。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.audit import contamination as con
from abcr.audit.auditor import audit_batch

BATCH_ID = "B-20260714T090000Z-0001"


def _run_dir(repo: Path, rid: str = "run-1") -> Path:
    d = repo / "data" / "runs" / rid / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d.parent


def _write_judge(repo: Path, rid: str, records: list[dict]) -> None:
    logs = repo / "data" / "runs" / rid / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "judge_calls.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _clean_judge_record(item_id: str = "q1") -> dict:
    return {
        "ts": "2026-07-15T00:00:00+00:00", "judge_model": "deepseek",
        "item_id": item_id,
        "messages": [
            {"role": "system", "content": "You are a strict grader. Score 1-10."},
            {"role": "user", "content": "Question: Explain photosynthesis.\nAnswer: Plants use light."},
        ],
        "params": {"temperature": 0.0},
    }


# ---------- 检查3：judge 输入结构 ----------

def test_judge_trace_with_inject_fails_and_points_to_line(tmp_path: Path) -> None:
    _run_dir(tmp_path)
    dirty = _clean_judge_record()
    dirty["messages"][0]["content"] = "Grade this steered (inject) response."
    _write_judge(tmp_path, "run-1", [_clean_judge_record(), dirty])
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "FAIL", ev
    # 指到第 2 行且命中 inject
    assert any(":2 " in e and "inject" in e for e in ev), ev


def test_clean_judge_trace_passes(tmp_path: Path) -> None:
    _run_dir(tmp_path)
    _write_judge(tmp_path, "run-1", [_clean_judge_record("q1"), _clean_judge_record("q2")])
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "PASS", ev


def test_judge_structure_skip_when_no_trace(tmp_path: Path) -> None:
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "SKIP"


def test_trait_name_exempt_in_judge_structure(tmp_path: Path) -> None:
    """AMENDMENT-31：judge messages 含 trait 名（官方 eval_prompt）不判泄漏。"""
    _run_dir(tmp_path)
    rec = _clean_judge_record()
    rec["messages"][0]["content"] = "Rate how conscientious and optimistic the answer is."
    _write_judge(tmp_path, "run-1", [rec])
    verdict, ev = con.check_judge_structure(tmp_path, ["run-1"])
    assert verdict == "PASS", ev


# ---------- 检查1：抽取 ∩ 评测 ----------

def _seed_golden(repo: Path) -> None:
    (repo / "data" / "golden").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "golden" / "golden10.json").write_text(json.dumps({
        "items": [{"id": "g01", "prompt": "计算 17×23，只输出数字。"},
                  {"id": "g02", "prompt": "Explain photosynthesis in one line."}]
    }, ensure_ascii=False), encoding="utf-8")


def test_corpus_overlap_fails_with_hash_hits(tmp_path: Path) -> None:
    _seed_golden(tmp_path)
    # 抽取语料含一条与评测题完全相同的句子（规范化后）
    tr = tmp_path / "data" / "traits" / "optimism"
    tr.mkdir(parents=True)
    (tr / "extraction.jsonl").write_text(
        json.dumps({"prompt": "计算 17×23，只输出数字。"}, ensure_ascii=False) + "\n"
        + json.dumps({"prompt": "Tell me about your day."}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    verdict, ev = con.check_corpus_disjoint(tmp_path)
    assert verdict == "FAIL", ev
    assert any("命中" in e for e in ev), ev
    assert any("g01" in e for e in ev), ev


def test_corpus_disjoint_passes(tmp_path: Path) -> None:
    _seed_golden(tmp_path)
    tr = tmp_path / "data" / "traits" / "optimism"
    tr.mkdir(parents=True)
    (tr / "extraction.jsonl").write_text(
        json.dumps({"prompt": "Describe an ideal weekend."}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    verdict, ev = con.check_corpus_disjoint(tmp_path)
    assert verdict == "PASS", ev


def test_corpus_skip_when_no_traits(tmp_path: Path) -> None:
    _seed_golden(tmp_path)
    verdict, ev = con.check_corpus_disjoint(tmp_path)
    assert verdict == "SKIP"


def test_corpus_normalization_catches_whitespace_variants(tmp_path: Path) -> None:
    _seed_golden(tmp_path)
    tr = tmp_path / "data" / "traits" / "opt"
    tr.mkdir(parents=True)
    # 多空白 + 前后空格：规范化后应与评测题 g02 同哈希
    (tr / "e.txt").write_text("  Explain   photosynthesis  in  one   line.  \n", encoding="utf-8")
    verdict, ev = con.check_corpus_disjoint(tmp_path)
    assert verdict == "FAIL", ev


# ---------- 检查4：泄漏词表 grep ----------

def test_leak_grep_hits_condition_word_in_judge(tmp_path: Path) -> None:
    _run_dir(tmp_path)
    rec = _clean_judge_record()
    rec["messages"][1]["content"] = "This is the vanilla condition answer."
    _write_judge(tmp_path, "run-1", [rec])
    verdict, ev = con.check_leak_grep(tmp_path, BATCH_ID, ["run-1"])
    assert verdict == "FAIL", ev
    assert any("vanilla" in e for e in ev), ev


def test_leak_grep_traits_questions_include_trait_name(tmp_path: Path) -> None:
    """traits 题面词表额外含 trait 名：题面写了 trait 名 → FAIL。"""
    tr = tmp_path / "data" / "traits" / "conscientiousness"
    tr.mkdir(parents=True)
    (tr / "questions.txt").write_text("How conscientiousness are you today?\n", encoding="utf-8")
    verdict, ev = con.check_leak_grep(tmp_path, BATCH_ID, [])
    assert verdict == "FAIL", ev
    assert any("conscientiousness" in e for e in ev), ev


def test_leak_grep_clean_passes(tmp_path: Path) -> None:
    _run_dir(tmp_path)
    _write_judge(tmp_path, "run-1", [_clean_judge_record()])
    verdict, ev = con.check_leak_grep(tmp_path, BATCH_ID, ["run-1"])
    assert verdict == "PASS", ev


# ---------- 检查2：split hash ----------

def test_split_hash_consistency_and_dev_only(tmp_path: Path) -> None:
    # 构造一个 splits 族 + 两 run，steps 共享同一 split_hash
    splits = tmp_path / "data" / "splits"
    splits.mkdir(parents=True)
    assignment = {"aaa": "dev", "bbb": "calibration"}
    (splits / "fam-0000.json").write_text(json.dumps(
        {"family": "fam", "assignment": assignment}), encoding="utf-8")
    sh = con.split_hash_of_assignment(assignment)
    rd = tmp_path / "data" / "runs" / "run-1"
    rd.mkdir(parents=True)
    (rd / "steps.jsonl").write_text(
        json.dumps({"item_id": "aaa", "split_hash": sh, "benchmark": "fam"}) + "\n",
        encoding="utf-8")
    verdict, ev = con.check_split_hash(tmp_path, BATCH_ID, ["run-1"])
    assert verdict == "PASS", ev
    assert any("命中族重算" in e for e in ev), ev


def test_split_hash_inconsistent_fails(tmp_path: Path) -> None:
    rd = tmp_path / "data" / "runs"
    for rid, sh in (("run-1", "a" * 64), ("run-2", "b" * 64)):
        d = rd / rid
        d.mkdir(parents=True)
        (d / "steps.jsonl").write_text(
            json.dumps({"item_id": "x", "split_hash": sh}) + "\n", encoding="utf-8")
    verdict, ev = con.check_split_hash(tmp_path, BATCH_ID, ["run-1", "run-2"])
    assert verdict == "FAIL", ev


def test_split_bucket_matches_protocol_formula() -> None:
    # §3.7 确定性切分：桶值稳定、三分类都可达
    buckets = {con.split_bucket("fam", f"item{i}") for i in range(200)}
    assert buckets == {"dev", "calibration", "heldout"}


# ---------- 编排 ----------

def test_contamination_item_pass_when_all_skip_or_pass(tmp_path: Path) -> None:
    _seed_golden(tmp_path)
    _run_dir(tmp_path)
    _write_judge(tmp_path, "run-1", [_clean_judge_record()])
    item = con.contamination_item(tmp_path, BATCH_ID, ["run-1"])
    assert item.id == 3
    assert item.verdict == "PASS", item.evidence


def test_contamination_item_fail_propagates(tmp_path: Path) -> None:
    _run_dir(tmp_path)
    dirty = _clean_judge_record()
    dirty["messages"][0]["content"] = "ablate arm, coefficient 8.0, layer=20"
    _write_judge(tmp_path, "run-1", [dirty])
    item = con.contamination_item(tmp_path, BATCH_ID, ["run-1"])
    assert item.verdict == "FAIL", item.evidence
