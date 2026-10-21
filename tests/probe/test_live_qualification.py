from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from abcr.control.ed25519 import generate_keypair
from abcr.control.contracts import sha256
from abcr.explore.item_pool import (DevBundleRef, SelectionRequest, build_dev_bundle,
                                    iter_bundle_items)
from abcr.explore.length_control import (generate_task_expansion_control,
                                         load_task_expansion_library)
from abcr.probe.contracts import ProbePersona
from abcr.probe.engine import FakeProbeEngine
from abcr.probe.ollama_engine import OllamaProbeEngine
import abcr.probe.qualification as qualification_module
from abcr.probe.qualification import (
    QualificationConfig,
    QualificationError,
    load_persona_config,
    qualify_local_probe,
)


def _bundle(tmp_path: Path, count: int = 20):
    tmp_path.mkdir(parents=True, exist_ok=True)
    dataset = tmp_path / "dataset.json"
    split = tmp_path / "split.json"
    items = [{"item_id": f"d-{index:02d}", "prompt": f"task {index}"}
             for index in range(24)]
    dataset.write_text(json.dumps({"items": items}))
    split.write_text(json.dumps({
        "dev": [item["item_id"] for item in items],
        "calibration": [], "holdout": [],
    }))
    private = tmp_path / "sealer.key"
    public = tmp_path / "sealer.pub"
    generate_keypair(private, public)
    root = tmp_path / "bundles"
    bundle = build_dev_bundle(
        SelectionRequest("LIVE-QUAL", "a" * 64, count, 17),
        dataset_path=dataset, split_path=split, output_root=root,
        sealer_private_key=private, sealer_public_key=public,
    )
    return bundle, root, public


def _config(tmp_path: Path, *, count: int = 20) -> QualificationConfig:
    bundle, root, public = _bundle(tmp_path, count)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"profile_id": "fixture"}))
    return QualificationConfig(
        profile_path=profile,
        trusted_dev_bundle_root=root,
        bundle_id=bundle.bundle_id,
        bundle_sealer_public_key=public,
        lab_root=tmp_path / "lab",
        evidence_path=tmp_path / "evidence.json",
        personas=(ProbePersona("p-a@v1", "be careful"),
                  ProbePersona("p-b@v1", "be concise")),
        prediction="both personas change compliance",
        seed=7,
        max_output_tokens=16,
    )


def test_no_network_test_mode_exercises_strict_sixty_cells_without_fake_pass(tmp_path):
    config = _config(tmp_path)
    result = qualify_local_probe(config, engine=FakeProbeEngine(), mode="test")
    assert result["scope_status"] == "TEST_ONLY"
    assert result["test_mode"] is True
    assert result["strict_shape"] == {
        "item_count_required": 20,
        "persona_count_required": 2,
        "vanilla_required": True,
        "arm_count_required": 3,
        "generation_count_required": 60,
        "items_observed": 20,
        "rows_published": 60,
        "generations_completed": 60,
        "shrinking_permitted": False,
    }
    assert result["deployment_e2e"]["status"] == "BLOCKED"
    assert result["autonomous_qualification_claimed"] is False
    assert result["qualification_scope"] == \
        "local_frozen_model_plus_cryptographic_fixture_devbundle_slo"
    assert result["inputs"]["bundle_authority"]["authority_class"] == \
        "qualification_fixture"
    assert result["inputs"]["bundle_authority"]["production_itempool_proven"] is False
    assert result["length_control_3l"]["status"] == "NOT_REQUESTED"
    on_disk = json.loads(config.evidence_path.read_text())
    assert on_disk == result
    rows = [json.loads((config.lab_root / "rows" / row_hash / "row.json").read_text())
            for row_hash in result["notebook"]["row_hashes"]]
    for item_id in result["inputs"]["bundle_item_ids"]:
        arms = {row["arm_id"] for row in rows if row["item_id"] == item_id}
        assert arms == {"vanilla", "persona:p-a@v1", "persona:p-b@v1"}


def test_requested_3l_qualification_is_complete_multiarm_or_external_blocked(tmp_path):
    base = _config(tmp_path / "qualified")
    manifest = json.loads((base.trusted_dev_bundle_root / base.bundle_id /
                           "manifest.json").read_text())
    bundle = DevBundleRef(base.bundle_id,
                         base.trusted_dev_bundle_root / base.bundle_id,
                         sha256(manifest), tuple(manifest["item_ids"]),
                         manifest["source_sha256"])
    items = {item["item_id"]: item["prompt"] for item in iter_bundle_items(
        bundle, base.trusted_dev_bundle_root,
        sealer_public_key=base.bundle_sealer_public_key)}
    library = load_task_expansion_library(
        Path(__file__).resolve().parents[2] / "configs" / "research" /
        "length-control" / "task_expansion_zh_v1.json")
    width = len(library.fragments[0]["text"])
    personas = (ProbePersona("p-a@v1", "甲" * width),
                ProbePersona("p-b@v1", "乙" * width))
    controls = tuple({
        "persona_ref": persona.persona_ref,
        "plan": generate_task_expansion_control(
            persona.persona_text, items, encode=lambda text: [ord(c) for c in text],
            render_chat=lambda system, item: f"{system}\n\n任务：\n{item}",
            tokenizer_sha256=sha256(b"fixture-tokenizer"),
            chat_template_sha256=sha256(b"fixture-template"), library=library),
    } for persona in personas)
    config = replace(base, personas=personas, with_length_control=True,
                     length_controls=controls)
    result = qualify_local_probe(config, engine=FakeProbeEngine(), mode="test")
    assert result["scope_status"] == "TEST_ONLY"
    assert result["strict_shape"]["arm_count_required"] == 5
    assert result["strict_shape"]["rows_published"] == 100
    assert result["length_control_3l"] == {
        "requested": True, "status": "PASS",
        "claim": "complete persona+own-③L multi-arm design; no approximation"}

    blocked = replace(config, evidence_path=tmp_path / "blocked.json",
                      lab_root=tmp_path / "blocked-lab")

    class NoExactTokenizer(FakeProbeEngine):
        def fingerprint(self):
            value = super().fingerprint()
            value.pop("exact_tokenizer_qualified")
            return value

    blocked_result = qualify_local_probe(
        blocked, engine=NoExactTokenizer(), mode="test")
    assert blocked_result["scope_status"] == "TEST_ONLY_FAILED"
    assert blocked_result["failure"]["stage"] == "length_control_prerequisite"
    assert blocked_result["length_control_3l"]["status"] == "BLOCKED_EXTERNAL"
    assert blocked_result["strict_shape"]["generations_completed"] == 0


def test_qualification_never_silently_shrinks_nineteen_item_bundle(tmp_path):
    config = _config(tmp_path, count=19)
    result = qualify_local_probe(config, engine=FakeProbeEngine(), mode="test")
    assert result["scope_status"] == "TEST_ONLY_FAILED"
    assert result["failure"]["stage"] == "dev_bundle_verification"
    assert result["strict_shape"]["generations_completed"] == 0
    assert result["strict_shape"]["shrinking_permitted"] is False


@pytest.mark.parametrize("attack", [
    "old_schema", "duplicate_cell", "invented_arm", "polluted_vanilla",
])
def test_qualification_rederives_rows_before_publishing_evidence(
        tmp_path, monkeypatch, attack):
    """Sixty dictionaries alone are not qualification: their bindings are rebuilt."""
    config = _config(tmp_path)
    original = qualification_module.run_probe

    def attacked_run(*args, **kwargs):
        run = original(*args, **kwargs)
        rows = [dict(row) for row in run.rows]
        if attack == "duplicate_cell":
            rows[-1] = dict(rows[0])
            return replace(run, rows=tuple(rows))
        row = rows[0]
        if attack == "old_schema":
            row["schema_version"] = 1
        elif attack == "invented_arm":
            row["arm_id"] = "persona:attacker@v1"
        else:
            # The row still claims vanilla but its prompt is no longer the sealed
            # task prompt.  Rehashing models a self-consistent malicious producer.
            from abcr.control.contracts import sha256
            row["prompt_hash"] = sha256(
                "persona pollution\n\n任务：\ntask 0".encode("utf-8"))
        from abcr.control.contracts import sha256
        row["row_hash"] = sha256({key: value for key, value in row.items()
                                  if key != "row_hash"})
        return replace(run, rows=tuple(rows))

    monkeypatch.setattr(qualification_module, "run_probe", attacked_run)
    result = qualify_local_probe(config, engine=FakeProbeEngine(), mode="test")
    assert result["scope_status"] == "TEST_ONLY_FAILED"
    assert result["failure"]["stage"] == "shape_validation"
    assert not (config.lab_root / "lab-notebook.jsonl").exists()


def test_live_mode_rejects_protocol_fixture_disguised_as_ollama_subclass(tmp_path):
    config = _config(tmp_path)

    class DisguisedFake(OllamaProbeEngine):
        pass

    fake = object.__new__(DisguisedFake)
    with pytest.raises(QualificationError, match="exact OllamaProbeEngine"):
        qualify_local_probe(config, engine=fake, mode="live")
    assert not config.evidence_path.exists()


def test_qualification_cell_identity_changes_when_persona_bytes_or_token_cap_change(
        tmp_path):
    base = _config(tmp_path / "base")
    first = qualify_local_probe(base, engine=FakeProbeEngine(), mode="test")
    first_row = json.loads((base.lab_root / "rows" /
                            first["notebook"]["row_hashes"][0] / "row.json").read_text())

    changed_persona = replace(
        base,
        lab_root=tmp_path / "persona-lab",
        evidence_path=tmp_path / "persona-evidence.json",
        personas=(ProbePersona("p-a@v1", "materially changed bytes"), base.personas[1]),
    )
    second = qualify_local_probe(changed_persona, engine=FakeProbeEngine(), mode="test")
    second_row = json.loads((changed_persona.lab_root / "rows" /
                             second["notebook"]["row_hashes"][0] / "row.json").read_text())
    assert first_row["probe_id"] != second_row["probe_id"]
    assert first_row["cell_id"] != second_row["cell_id"]

    changed_cap = replace(
        base,
        lab_root=tmp_path / "cap-lab",
        evidence_path=tmp_path / "cap-evidence.json",
        max_output_tokens=17,
    )
    third = qualify_local_probe(changed_cap, engine=FakeProbeEngine(), mode="test")
    third_row = json.loads((changed_cap.lab_root / "rows" /
                            third["notebook"]["row_hashes"][0] / "row.json").read_text())
    assert first_row["probe_id"] != third_row["probe_id"]
    assert first_row["cell_id"] != third_row["cell_id"]


def test_fixture_key_identity_is_bound_and_cannot_claim_production(tmp_path):
    config = _config(tmp_path / "fixture")
    result = qualify_local_probe(config, engine=FakeProbeEngine(), mode="test")
    authority = result["inputs"]["bundle_authority"]
    assert len(authority["sealer_key_id"]) == 64
    assert len(authority["sealer_public_key_bytes_sha256"]) == 64

    production_claim = replace(
        config, bundle_authority="production_itempool",
        lab_root=tmp_path / "production-lab",
        evidence_path=tmp_path / "production-evidence.json")
    blocked = qualify_local_probe(
        production_claim, engine=FakeProbeEngine(), mode="test")
    assert blocked["scope_status"] == "TEST_ONLY_FAILED"
    assert blocked["failure"]["stage"] == "dev_bundle_verification"
    assert blocked["strict_shape"]["generations_completed"] == 0


def test_persona_config_and_prediction_are_strict(tmp_path):
    path = tmp_path / "personas.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "personas": [{"persona_ref": "only@v1", "persona_text": "one"}],
    }))
    with pytest.raises(QualificationError, match="exactly 2"):
        load_persona_config(path)
    with pytest.raises(QualificationError, match="prediction"):
        config = _config(tmp_path / "other")
        QualificationConfig(**{**config.__dict__, "prediction": ""})


def test_probe_and_qualification_sources_have_no_ledger_writer_import():
    root = Path(__file__).resolve().parents[2]
    paths = [*sorted((root / "src/abcr/probe").glob("*.py")),
             root / "scripts/probe_qualify_live.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any(name.startswith("abcr.ledger")
                       or name.startswith("abcr.common.ledger") for name in imports)
