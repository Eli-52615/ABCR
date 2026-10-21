"""Contract test: synthetic 2-step trajectory — action/obs/state reconstruction."""

import hashlib
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.logging.writer import StepWriter
from abcr.logging.schema import SCHEMA_VERSION


def _make_traj_step(traj_id: str, step_id: int, **overrides) -> dict:
    base = {
        "schema_version": SCHEMA_VERSION,
        "run_id": "traj-test-run",
        "trajectory_id": traj_id,
        "step_id": step_id,
        "parent_run": None,
        "git_commit": "abc123",
        "config_hash": "cfg_hash_traj",
        "protocol_ref": "test",
        "env_lock_ref": "env.lock",
        "model_id": "tinyqwen",
        "model_revision": "local-fixture-seed0",
        "dtype": "float32",
        "quantization": None,
        "device": "cpu",
        "device_backend": "cpu",
        "engine": "transformers",
        "engine_version": "4.52.3",
        "torch_version": "2.6.0",
        "cuda_version": None,
        "chat_template_hash": "deadbeef",
        "benchmark": "fixture",
        "split_hash": "split_hash_traj",
        "item_id": "traj_item_001",
        "condition": "vanilla",
        "trait": None,
        "trait_pole": None,
        "method": "none",
        "layer": None,
        "coefficient": None,
        "intervention_strength": None,
        "env_seed": None,
        "action": None,
        "obs_hash": None,
        "remaining_budget": None,
        "stop_reason": "eos",
        "state_snapshot_ref": None,
        "random_seed": 42,
        "prompt_hash": "prompt_hash_traj",
        "output_text": f"step {step_id} output",
        "parsed_answer": None,
        "is_correct": None,
        "latency_ms": 50.0,
        "input_tokens": 10,
        "output_tokens": 15,
        "trait_score": None,
        "fluency_score": None,
        "safety_flags": [],
        "activation_summary": None,
        "citable": False,
        "prev_hash": "",
        "entry_hash": "",
    }
    base.update(overrides)
    return base


def test_2step_trajectory_replay(tmp_path):
    run_dir = tmp_path / "traj_run"
    run_dir.mkdir()
    w = StepWriter(run_dir)

    obs_content = "observation from search tool"
    obs_hash = hashlib.sha256(obs_content.encode()).hexdigest()

    step0 = _make_traj_step(
        "T1", 0,
        action="tool_call:search",
        obs_hash=obs_hash,
        state_snapshot_ref="fixtures/snap0.json",
        remaining_budget=10,
        output_text="I will search for information.",
    )
    w.append(step0)

    step1 = _make_traj_step(
        "T1", 1,
        action=None,
        obs_hash=None,
        state_snapshot_ref="fixtures/snap1.json",
        remaining_budget=9,
        output_text="Based on the search results, here is the answer.",
        random_seed=43,
    )
    w.append(step1)

    # Replay: read back and reconstruct timeline
    steps_path = run_dir / "steps.jsonl"
    lines = steps_path.read_text().splitlines()
    assert len(lines) == 2

    read_steps = [json.loads(l) for l in lines]
    read_steps.sort(key=lambda s: (s["trajectory_id"], s["step_id"]))

    # Verify step 0 fields
    s0 = read_steps[0]
    assert s0["trajectory_id"] == "T1"
    assert s0["step_id"] == 0
    assert s0["action"] == "tool_call:search"
    assert s0["obs_hash"] == obs_hash
    assert s0["state_snapshot_ref"] == "fixtures/snap0.json"
    assert s0["remaining_budget"] == 10

    # Verify step 1 fields
    s1 = read_steps[1]
    assert s1["trajectory_id"] == "T1"
    assert s1["step_id"] == 1
    assert s1["action"] is None
    assert s1["state_snapshot_ref"] == "fixtures/snap1.json"
    assert s1["remaining_budget"] == 9

    # Chain verification
    assert StepWriter.verify_chain(steps_path) is True
