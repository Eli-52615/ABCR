import json
import pathlib
import pytest
from abcr.eval.deterministic.registry import run_checks

GOLDEN_PATH = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "golden_answers" / "golden.jsonl"


def load_golden():
    cases = []
    with open(GOLDEN_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


GOLDEN_CASES = load_golden()


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c["case_id"] for c in GOLDEN_CASES])
def test_golden_answer_exact_match(case):
    results = run_checks(case["response"], case["checks"])
    expected = case["expected"]
    assert len(results) == len(expected), (
        f"result count mismatch: got {len(results)}, expected {len(expected)}"
    )
    for res, exp in zip(results, expected):
        assert res["name"] == exp["name"], f"checker name mismatch: {res['name']} vs {exp['name']}"
        assert res["pass"] == exp["pass"], (
            f"[{case['case_id']}] checker '{res['name']}' expected pass={exp['pass']}, "
            f"got pass={res['pass']}; detail: {res['detail']}"
        )
    is_correct = all(r["pass"] for r in results)
    assert is_correct == case["expected_is_correct"], (
        f"[{case['case_id']}] is_correct expected {case['expected_is_correct']}, got {is_correct}"
    )


def test_golden_coverage():
    checker_names = set()
    for case in GOLDEN_CASES:
        for check in case["checks"]:
            checker_names.add(check["name"])
    required_count = 10
    assert len(checker_names) >= required_count, (
        f"golden covers only {len(checker_names)} checker types, need >= {required_count}"
    )
    fail_cases = [c for c in GOLDEN_CASES if not c["expected_is_correct"]]
    assert len(fail_cases) >= 4, f"need >= 4 fail cases, have {len(fail_cases)}"
    multi_cases = [c for c in GOLDEN_CASES if len(c["checks"]) > 1]
    assert len(multi_cases) >= 2, f"need >= 2 multi-constraint cases, have {len(multi_cases)}"
    assert len(GOLDEN_CASES) >= 12, f"need >= 12 total cases, have {len(GOLDEN_CASES)}"
