"""Contract test: mini loop coverage — all arms × items × seeds complete, no gaps/duplicates."""

import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import pytest
from abcr.logging.writer import StepWriter


def _load_runset():
    for p in [Path("RUNSET.json"), Path("runs/MINILOOP-RUNSET.json")]:
        if p.exists():
            return json.loads(p.read_text())
    pytest.skip("RUNSET.json not found")


def _resolve_run(entry) -> tuple[str, str]:
    """Return (run_id, condition) from either dict or plain string entry."""
    if isinstance(entry, dict):
        return entry["run_id"], entry["condition"]
    run_id = str(entry)
    manifest = json.loads(Path(f"runs/{run_id}/manifest.json").read_text())
    return run_id, manifest["config"]["condition"]


def _load_steps(run_id: str) -> list[dict]:
    path = Path(f"runs/{run_id}/steps.jsonl")
    if not path.exists():
        pytest.skip(f"Run {run_id} not found")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_mini_loop_coverage():
    runset = _load_runset()
    main_runs = runset["main_runs"]

    all_item_ids = set()
    all_conditions = set()

    for entry in main_runs:
        run_id, condition = _resolve_run(entry)
        steps = _load_steps(run_id)
        all_conditions.add(condition)

        pairs = set()
        for s in steps:
            pairs.add((s["item_id"], s["random_seed"]))
            all_item_ids.add(s["item_id"])

        assert len(pairs) == len(steps), f"Duplicates in {run_id}"
        assert StepWriter.verify_chain(Path(f"runs/{run_id}/steps.jsonl"))

    item_sets = []
    for entry in main_runs:
        run_id, _ = _resolve_run(entry)
        steps = _load_steps(run_id)
        items = set(s["item_id"] for s in steps)
        item_sets.append(items)

    for i in range(1, len(item_sets)):
        assert item_sets[0] == item_sets[i], \
            f"Item set mismatch between arm 0 and arm {i}"


def test_activation_sampling_coverage():
    runset = _load_runset()
    for entry in runset["main_runs"]:
        run_id, condition = _resolve_run(entry)
        if condition not in ("random_direction", "residual_vector"):
            continue

        steps = _load_steps(run_id)
        expected_sampled = set()
        actual_sampled = set()

        for s in steps:
            item_id = s["item_id"]
            h = int(hashlib.sha256(item_id.encode()).hexdigest()[:8], 16)
            if (h % 1000) < 100:
                expected_sampled.add(item_id)
            if s["activation_summary"] is not None:
                actual_sampled.add(item_id)

        assert actual_sampled == expected_sampled, (
            f"Activation sampling mismatch in {run_id}: "
            f"extra={actual_sampled - expected_sampled}, "
            f"missing={expected_sampled - actual_sampled}"
        )
