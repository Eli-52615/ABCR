"""Contract test: arm purity — manifest and step fields enforce method isolation."""

import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import pytest


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


def _load_manifest(run_id: str) -> dict:
    path = Path(f"runs/{run_id}/manifest.json")
    return json.loads(path.read_text())


def _load_steps(run_id: str) -> list[dict]:
    path = Path(f"runs/{run_id}/steps.jsonl")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_manifest_arm_purity():
    runset = _load_runset()
    for entry in runset["main_runs"]:
        run_id, condition = _resolve_run(entry)
        manifest = _load_manifest(run_id)
        purity = manifest["arm_purity"]

        if condition == "vanilla":
            assert not purity["has_vector_ref"], f"vanilla run {run_id} has vector ref"
            assert not purity["has_persona_ref"], f"vanilla run {run_id} has persona ref"
        elif condition == "prompt_persona":
            assert not purity["has_vector_ref"], f"text run {run_id} has vector ref"
            assert purity["has_persona_ref"], f"text run {run_id} missing persona ref"
        elif condition in ("random_direction", "residual_vector"):
            assert purity["has_vector_ref"], f"{condition} run {run_id} missing vector ref"
            assert not purity["has_persona_ref"], f"{condition} run {run_id} has persona ref"


def test_step_field_purity():
    runset = _load_runset()
    vanilla_hashes = {}
    for entry in runset["main_runs"]:
        run_id, condition = _resolve_run(entry)
        if condition == "vanilla":
            steps = _load_steps(run_id)
            for s in steps:
                vanilla_hashes[(s["item_id"], s["random_seed"])] = s["prompt_hash"]
            break

    for entry in runset["main_runs"]:
        run_id, condition = _resolve_run(entry)
        steps = _load_steps(run_id)

        for s in steps:
            if condition == "prompt_persona":
                vanilla_key = (s["item_id"], s["random_seed"])
                if vanilla_key in vanilla_hashes:
                    assert s["prompt_hash"] != vanilla_hashes[vanilla_key], \
                        f"Text arm step has same prompt_hash as vanilla for {s['item_id']}"
                assert s["layer"] is None, f"text arm has layer set in {run_id}"
                assert s["coefficient"] is None, f"text arm has coefficient set in {run_id}"

            elif condition in ("random_direction", "residual_vector"):
                vanilla_key = (s["item_id"], s["random_seed"])
                if vanilla_key in vanilla_hashes:
                    assert s["prompt_hash"] == vanilla_hashes[vanilla_key], \
                        f"Vector arm has different prompt_hash from vanilla for {s['item_id']}"
                assert s["layer"] is not None, \
                    f"{condition} arm missing layer in {run_id}"
                assert s["coefficient"] is not None, \
                    f"{condition} arm missing coefficient in {run_id}"
