"""Contract test: StepWriter chain integrity, idempotent resume, E07/E08/E09."""

import json
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.logging.writer import StepWriter, ZERO_HASH
from abcr.logging.errors import AbcrError, E07_STEPS_TAIL_CORRUPT, E08_CHAIN_BROKEN, E09_RESUME_CONFLICT
from abcr.logging.schema import SCHEMA_VERSION


def _make_step(item_id: str, seed: int, condition: str = "vanilla", step_id: int = 0) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "test-run",
        "trajectory_id": f"test-run:{item_id}:{seed}",
        "step_id": step_id,
        "parent_run": None,
        "git_commit": "abc123",
        "config_hash": "cfg_hash_000",
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
        "split_hash": "split_hash_000",
        "item_id": item_id,
        "condition": condition,
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
        "random_seed": seed,
        "prompt_hash": "prompt_hash_000",
        "output_text": f"output for {item_id} seed {seed}",
        "parsed_answer": None,
        "is_correct": None,
        "latency_ms": 100.0,
        "input_tokens": 10,
        "output_tokens": 20,
        "trait_score": None,
        "fluency_score": None,
        "safety_flags": [],
        "activation_summary": None,
        "citable": False,
        "prev_hash": "",
        "entry_hash": "",
    }


def test_write_5_lines_chain_ok(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    w = StepWriter(run_dir)
    for i in range(5):
        w.append(_make_step(f"item_{i:03d}", 42))
    assert StepWriter.verify_chain(run_dir / "steps.jsonl") is True
    assert len(w.load_done()) == 5


def test_tamper_field_e08(tmp_path):
    run_dir = tmp_path / "run2"
    run_dir.mkdir()
    w = StepWriter(run_dir)
    for i in range(5):
        w.append(_make_step(f"item_{i:03d}", 42))
    lines = (run_dir / "steps.jsonl").read_text().splitlines()
    d = json.loads(lines[2])
    d["output_text"] = "TAMPERED"
    lines[2] = json.dumps(d, ensure_ascii=False)
    (run_dir / "steps.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(AbcrError) as exc:
        StepWriter.verify_chain(run_dir / "steps.jsonl")
    assert E08_CHAIN_BROKEN in str(exc.value)


def test_delete_line_e08(tmp_path):
    run_dir = tmp_path / "run3"
    run_dir.mkdir()
    w = StepWriter(run_dir)
    for i in range(5):
        w.append(_make_step(f"item_{i:03d}", 42))
    lines = (run_dir / "steps.jsonl").read_text().splitlines()
    del lines[1]
    (run_dir / "steps.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(AbcrError) as exc:
        StepWriter.verify_chain(run_dir / "steps.jsonl")
    assert E08_CHAIN_BROKEN in str(exc.value)


def test_crash_tail_e07_then_repair(tmp_path):
    run_dir = tmp_path / "run4"
    run_dir.mkdir()
    w = StepWriter(run_dir)
    for i in range(5):
        w.append(_make_step(f"item_{i:03d}", 42))
    with open(run_dir / "steps.jsonl", "a") as f:
        f.write('{"incomplete": true')
    with pytest.raises(AbcrError) as exc:
        StepWriter(run_dir)
    assert E07_STEPS_TAIL_CORRUPT in str(exc.value)
    event = StepWriter.repair(run_dir)
    assert event["valid_lines"] == 5
    crashed_files = list(run_dir.glob("steps.jsonl.crashed-*"))
    assert len(crashed_files) == 1
    assert StepWriter.verify_chain(run_dir / "steps.jsonl") is True
    w2 = StepWriter(run_dir)
    assert len(w2.load_done()) == 5


def test_duplicate_append_e09(tmp_path):
    run_dir = tmp_path / "run5"
    run_dir.mkdir()
    w = StepWriter(run_dir)
    w.append(_make_step("item_000", 42))
    with pytest.raises(AbcrError) as exc:
        w.append(_make_step("item_000", 42))
    assert E09_RESUME_CONFLICT in str(exc.value)
