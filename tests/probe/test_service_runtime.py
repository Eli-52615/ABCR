from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.control.ed25519 import generate_keypair
from abcr.control.work_spool import WorkSpool
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.probe.engine import FakeProbeEngine
from abcr.probe.service import ServiceConfig, doctor, main, process_ready


def _sources(root: Path) -> tuple[Path, Path]:
    dataset = root / "dataset.json"
    split = root / "split.json"
    dataset.write_text(json.dumps({"items": [
        {"item_id": "d1", "prompt": "say one"},
        {"item_id": "d2", "prompt": "say two"},
        {"item_id": "c1", "prompt": "cal"},
        {"item_id": "h1", "prompt": "holdout"},
    ]}))
    split.write_text(json.dumps({
        "dev": ["d1", "d2"], "calibration": ["c1"], "holdout": ["h1"],
    }))
    return dataset, split


def _runtime(tmp_path: Path):
    work = tmp_path / "work"
    spool = WorkSpool(work)
    lab = tmp_path / "lab"; lab.mkdir()
    bundles = tmp_path / "bundles"; bundles.mkdir()
    private_key = tmp_path / "sealer.key"
    public_key = tmp_path / "sealer.pub"
    generate_keypair(private_key, public_key)
    dataset, split = _sources(tmp_path)
    bundle = build_dev_bundle(
        SelectionRequest("selection", "a" * 64, 1, 7),
        dataset_path=dataset, split_path=split, output_root=bundles,
        sealer_private_key=private_key, sealer_public_key=public_key,
    )
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"profile_id": "fixture"}))
    config = ServiceConfig(work, profile, bundles, public_key, lab)
    payload = {
        "probe_id": "probe-1",
        "goal_hash": "a" * 64,
        "dev_bundle": {
            "bundle_id": bundle.bundle_id,
            "manifest_hash": bundle.manifest_hash,
            "item_ids": list(bundle.item_ids),
            "source_hash": bundle.source_hash,
        },
        "personas": [
            {"persona_ref": "persona-a@v1", "persona_text": "Be careful."},
            {"persona_ref": "persona-b@v1", "persona_text": "Be concise."},
        ],
        "prediction": "compliance increases",
        "seed": 9,
        "model_profile": "fixture",
        "max_output_tokens": 32,
        "with_length_control": False,
    }
    return config, spool, payload


def _fake_factory(_path: Path):
    return FakeProbeEngine()


def _result(config: ServiceConfig, work_id: str) -> dict:
    path = config.work_root / "probe" / "results" / f"{work_id}.json"
    return json.loads(path.read_text())["result"]


def test_ready_queue_runs_probe_persists_notebook_and_returns_receipt(tmp_path):
    config, spool, payload = _runtime(tmp_path)
    spool.enqueue("probe", "work-1", payload)

    assert process_ready(config, engine_factory=_fake_factory) == {
        "handled": 1, "claim_errors": 0}

    result = _result(config, "work-1")
    assert result["ok"] is True
    receipt = result["result"]
    assert receipt["receipt_type"] == "ProbeResultReceipt"
    assert receipt["probe_id"] == "probe-1"
    assert receipt["model_profile"] == "fixture"
    assert receipt["row_count"] == len(receipt["row_hashes"]) == 3
    assert receipt["arm_ids"] == [
        "vanilla", "persona:persona-a@v1", "persona:persona-b@v1"]
    assert receipt["item_ids"] == list(payload["dev_bundle"]["item_ids"])
    assert receipt["citable"] is False
    assert receipt["length_control_3l"] == {
        "requested": False, "status": "NOT_REQUESTED"}
    identities = {(row["arm_id"], row["item_id"], row["seed"])
                  for row in receipt["rows"]}
    assert identities == {(arm, payload["dev_bundle"]["item_ids"][0], 9)
                          for arm in receipt["arm_ids"]}
    for row_hash in receipt["row_hashes"]:
        row = json.loads((config.lab_root / "rows" / row_hash / "row.json").read_text())
        assert row["row_hash"] == row_hash and row["citable"] is False
    assert (config.work_root / "probe" / "acks" / "work-1.json").is_file()
    assert (config.work_root / "probe" / "archive" / "work-1.json").is_file()


@pytest.mark.parametrize("target,field,value", [
    ("payload", "trusted_dev_bundle_root", "/tmp/evil"),
    ("payload", "bundle_sealer_public_key", "/tmp/evil.pub"),
    ("payload", "lab_root", "/tmp/evil-lab"),
    ("payload", "profile_path", "/tmp/evil-profile"),
    ("bundle", "root", "/tmp/evil-bundle"),
])
def test_payload_cannot_inject_runtime_trust_roots(tmp_path, target, field, value):
    config, spool, payload = _runtime(tmp_path)
    if target == "payload":
        payload[field] = value
    else:
        payload["dev_bundle"][field] = value
    spool.enqueue("probe", "attack", payload)

    assert process_ready(config, engine_factory=_fake_factory)["handled"] == 1
    assert _result(config, "attack") == {
        "ok": False, "error_code": "ProbeServiceError"}
    assert not (config.lab_root / "lab-notebook.jsonl").exists()


def test_payload_profile_must_equal_frozen_engine_profile(tmp_path):
    config, spool, payload = _runtime(tmp_path)
    payload["model_profile"] = "qwen3-surprise"
    spool.enqueue("probe", "wrong-profile", payload)

    process_ready(config, engine_factory=_fake_factory)
    assert _result(config, "wrong-profile")["ok"] is False
    assert not (config.lab_root / "lab-notebook.jsonl").exists()


def test_payload_requires_prediction_and_cannot_omit_vanilla(tmp_path):
    config, spool, payload = _runtime(tmp_path)
    payload["prediction"] = ""
    spool.enqueue("probe", "missing-prediction", payload)
    process_ready(config, engine_factory=_fake_factory)
    assert _result(config, "missing-prediction")["ok"] is False
    assert not (config.lab_root / "lab-notebook.jsonl").exists()


def test_once_processes_only_one_sorted_ready_item(tmp_path):
    config, spool, payload = _runtime(tmp_path)
    spool.enqueue("probe", "b-work", dict(payload, probe_id="probe-b"))
    spool.enqueue("probe", "a-work", dict(payload, probe_id="probe-a"))

    assert process_ready(config, once=True, engine_factory=_fake_factory)["handled"] == 1
    assert (config.work_root / "probe" / "acks" / "a-work.json").exists()
    assert (config.work_root / "probe" / "ready" / "b-work.json").exists()


def test_poison_claim_is_quarantined_without_blocking_later_work(tmp_path):
    config, spool, payload = _runtime(tmp_path)
    poison = spool.enqueue("probe", "original-name", payload)
    poison.rename(poison.with_name("!-poison.json"))
    spool.enqueue("probe", "valid-work", payload)

    assert process_ready(config, engine_factory=_fake_factory) == {
        "handled": 1, "claim_errors": 1}
    assert (config.work_root / "probe" / "quarantine" / "!-poison.json").exists()
    assert _result(config, "valid-work")["ok"] is True


def test_offline_doctor_validates_files_without_fingerprint_network(tmp_path):
    config, _spool, _payload = _runtime(tmp_path)

    class DoctorEngine(FakeProbeEngine):
        fingerprint_calls = 0

        def fingerprint(self):
            type(self).fingerprint_calls += 1
            return super().fingerprint()

    def factory(_path):
        return DoctorEngine()

    report = doctor(config, offline=True, engine_factory=factory)
    assert report["ok"] and report["offline"]
    assert DoctorEngine.fingerprint_calls == 0
    online = doctor(config, offline=False, engine_factory=factory)
    assert online["engine_fingerprint"]["profile_id"] == "fixture"
    assert DoctorEngine.fingerprint_calls == 1


def test_main_is_callable_and_offline_doctor_emits_json(tmp_path, monkeypatch, capsys):
    config, _spool, _payload = _runtime(tmp_path)
    monkeypatch.setattr("abcr.probe.service.OllamaProbeEngine", _fake_factory)
    code = main([
        "--offline-doctor", "--work-root", str(config.work_root),
        "--profile", str(config.profile_path),
        "--dev-bundle-root", str(config.trusted_dev_bundle_root),
        "--bundle-sealer-public-key", str(config.bundle_sealer_public_key),
        "--lab-root", str(config.lab_root),
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["offline"] is True
