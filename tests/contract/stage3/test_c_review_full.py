import json
import pathlib
import pytest
from abcr.review import review_run


@pytest.fixture
def runset_data(tmp_path):
    runs_dir = tmp_path / "runs"
    scores_dir = tmp_path / "scores"
    review_dir = tmp_path / "review"

    runset_path = runs_dir / "MINILOOP-RUNSET.json"
    runs_dir.mkdir(parents=True, exist_ok=True)

    runset = {"main_runs": [], "t0_runs": []}
    runset_path.write_text(json.dumps(runset))

    return {
        "runs_dir": runs_dir,
        "scores_dir": scores_dir,
        "review_dir": review_dir,
        "runset_path": runset_path,
    }


@pytest.mark.skipif(
    not pathlib.Path("runs/MINILOOP-RUNSET.json").exists(),
    reason="MINILOOP-RUNSET.json not found (A hasn't produced mini loop runs)"
)
class TestReviewFull:
    def test_main_runs_all_pass(self):
        with open("runs/MINILOOP-RUNSET.json") as f:
            runset = json.load(f)

        main_runs = runset.get("main_runs", [])
        assert len(main_runs) == 4, f"expected 4 main_runs, got {len(main_runs)}"

        for run_entry in main_runs:
            if isinstance(run_entry, str):
                run_id = run_entry
            else:
                assert isinstance(run_entry, dict), (
                    "main_runs entry must be str or dict; "
                    f"got {type(run_entry).__name__}"
                )
                assert "run_id" in run_entry, (
                    f"main_runs entry missing run_id; "
                    f"keys={list(run_entry.keys())!r}"
                )
                run_id = run_entry["run_id"]
            assert isinstance(run_id, str) and run_id, (
                f"invalid run_id: {run_id!r}"
            )
            report = review_run(run_id)
            assert report["pass"] is True, f"run {run_id} review failed: {report['error_codes']}"

    def test_cross_run_consistency(self):
        with open("runs/MINILOOP-RUNSET.json") as f:
            runset = json.load(f)

        main_runs = runset.get("main_runs", [])
        item_sets = {}
        seed_sets = {}

        for run_entry in main_runs:
            if isinstance(run_entry, str):
                run_id = run_entry
            else:
                assert isinstance(run_entry, dict), (
                    f"main_runs entry must be str or dict, got {type(run_entry).__name__}"
                )
                assert "run_id" in run_entry, (
                    f"main_runs entry missing run_id; keys={sorted(run_entry)}"
                )
                run_id = run_entry["run_id"]
            assert isinstance(run_id, str) and run_id, (
                f"invalid run_id: {run_id!r}"
            )
            steps_file = pathlib.Path("runs") / run_id / "steps.jsonl"
            steps = []
            with open(steps_file) as f:
                for line in f:
                    if line.strip():
                        steps.append(json.loads(line.strip()))

            items = sorted(set(s.get("item_id", "") for s in steps))
            seeds = sorted(set(s.get("random_seed", 0) for s in steps))
            condition = steps[0].get("condition", "") if steps else ""

            item_sets[run_id] = items
            seed_sets[run_id] = seeds

        all_item_lists = list(item_sets.values())
        for items in all_item_lists[1:]:
            assert items == all_item_lists[0], "item sets differ across runs"

        all_seed_lists = list(seed_sets.values())
        for seeds in all_seed_lists[1:]:
            assert seeds == all_seed_lists[0], "seed sets differ across runs"
