from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.probe.contracts import ProbePersona, ProbeRequest
from abcr.probe.engine import FakeProbeEngine, run_probe
from abcr.probe.notebook import ProbeNotebook
from abcr.probe.promote import promote_probe
from tests.explore.test_itempool_workflow import itempool_keys, sealed_bundle, sources


def test_probe_rows_are_non_citable_and_atomic(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)
    run = run_probe(ProbeRequest("P1", "a" * 64, bundle,
                                 (ProbePersona("p@v1", "careful"),),
                                 "increase", 1, "fixture"), FakeProbeEngine(),
                    trusted_dev_bundle_root=tmp_path / "bundles",
                    bundle_sealer_public_key=keys[1])
    assert [row["arm_id"] for row in run.rows] == ["vanilla", "persona:p@v1"]
    row = run.rows[1]; assert not row["citable"]
    assert row["engine_fingerprint"]["profile_id"] == "fixture"
    assert len(row["engine_fingerprint_sha256"]) == 64
    notebook = ProbeNotebook(tmp_path / "lab")
    path = notebook.append(row)
    assert path.is_dir() and notebook.read(row["row_hash"])["item_id"] == row["item_id"]
    draft = promote_probe([row["row_hash"]], notebook, actor_id="owner", human_confirmed=True)
    assert draft["draft_only"] and not draft["auto_execute"]
    with pytest.raises(Exception): promote_probe([row["row_hash"]], notebook, actor_id="owner", human_confirmed=False)


def test_probe_refuses_request_engine_profile_mismatch(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)
    request = ProbeRequest("P1", "a" * 64, bundle,
                           (ProbePersona("p@v1", "careful"),),
                           "increase", 1, "not-fixture")
    with pytest.raises(ValueError, match="model_profile mismatch"):
        run_probe(request, FakeProbeEngine(),
                  trusted_dev_bundle_root=tmp_path / "bundles",
                  bundle_sealer_public_key=keys[1])


def test_probe_package_has_no_ledger_imports():
    root = Path(__file__).resolve().parents[2] / "src" / "abcr" / "probe"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports += [x.name for x in node.names]
            if isinstance(node, ast.ImportFrom): imports.append(node.module or "")
        assert not any(name.startswith("abcr.ledger") or name.startswith("abcr.common.ledger") for name in imports)


def test_prediction_is_required_and_length_control_requires_precompiled_plan(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)
    args = ("P1", "a" * 64, bundle, (ProbePersona("p@v1", "careful"),))
    with pytest.raises(ValueError, match="prediction"):
        ProbeRequest(*args, "", 1, "fixture")
    with pytest.raises(ValueError, match="prediction"):
        ProbeRequest(*args, "first\nsecond", 1, "fixture")
    with pytest.raises(ValueError, match="one precompiled"):
        ProbeRequest(*args, "increase", 1, "fixture", with_length_control=True)


def test_vanilla_is_mandatory_and_two_personas_share_item_seed(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", "a" * 64, 2, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)
    request = ProbeRequest(
        "P-multi", "a" * 64, bundle,
        (ProbePersona("p1@v1", "careful"), ProbePersona("p2@v1", "concise")),
        "personas increase compliance", 7, "fixture")
    run = run_probe(request, FakeProbeEngine(),
                    trusted_dev_bundle_root=tmp_path / "bundles",
                    bundle_sealer_public_key=keys[1])
    assert len(run.rows) == 2 * 3
    expected_arms = {"vanilla", "persona:p1@v1", "persona:p2@v1"}
    for item_id in bundle.item_ids:
        same_item = [row for row in run.rows if row["item_id"] == item_id]
        assert {row["arm_id"] for row in same_item} == expected_arms
        assert {row["seed"] for row in same_item} == {7}
        assert len({row["cell_id"] for row in same_item}) == 3
        vanilla = next(row for row in same_item if row["arm_id"] == "vanilla")
        assert vanilla["persona_ref"] is None
        assert vanilla["arm_kind"] == "vanilla"


def test_vanilla_prompt_is_byte_exact_task_and_never_passes_persona_renderer(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)

    class RecordingEngine(FakeProbeEngine):
        def __init__(self):
            self.prompts = []

        def generate(self, *, prompt, seed, max_output_tokens):
            self.prompts.append(prompt)
            return super().generate(prompt=prompt, seed=seed,
                                    max_output_tokens=max_output_tokens)

    engine = RecordingEngine()
    request = ProbeRequest(
        "P-purity", "a" * 64, bundle,
        (ProbePersona("p1@v1", "PERSONA ONE"),
         ProbePersona("p2@v1", "PERSONA TWO")),
        "personas change behavior", 7, "fixture")
    run_probe(request, engine, trusted_dev_bundle_root=tmp_path / "bundles",
              bundle_sealer_public_key=keys[1])

    source_items = {item["item_id"]: item for item in json.loads(
        dataset.read_text())["items"]}
    task = source_items[bundle.item_ids[0]].get(
        "prompt", source_items[bundle.item_ids[0]].get("instruction"))
    assert engine.prompts == [
        task,
        f"PERSONA ONE\n\n任务：\n{task}",
        f"PERSONA TWO\n\n任务：\n{task}",
    ]
