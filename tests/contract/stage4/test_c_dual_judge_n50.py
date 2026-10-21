import json
import pathlib
import pytest

REPORT_PATH = pathlib.Path("review/judge_consistency_n50.json")


@pytest.mark.skipif(
    not REPORT_PATH.exists(),
    reason="judge_consistency_n50.json not yet generated"
)
class TestDualJudgeN50:
    def test_report_exists_and_complete(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)

        required_fields = ["n", "pearson", "spearman", "MAE", "同源提示"]
        for field in required_fields:
            assert field in report, f"missing field: {field}"

    def test_n_equals_50(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert report["n"] == 50

    def test_scores_not_constant(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)

        if "deepseek_scores" in report and "claude_scores" in report:
            ds = report["deepseek_scores"]
            cl = report["claude_scores"]
            assert len(set(ds)) > 1, "DeepSeek scores are constant"
            assert len(set(cl)) > 1, "Claude scores are constant"
