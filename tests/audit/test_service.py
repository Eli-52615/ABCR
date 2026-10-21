from __future__ import annotations

import json

from abcr.audit.service import AuditServiceConfig, AuditServiceError, doctor, load_config, run
from abcr.control.ed25519 import generate_keypair
from abcr.control.work_spool import WorkSpool
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle


def _fixture(tmp_path):
    work = tmp_path / "work"
    spool = WorkSpool(work)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    dataset = tmp_path / "dataset.json"
    split = tmp_path / "split.json"
    dataset.write_text(json.dumps({"items": [
        {"item_id": "d1", "prompt": "dev one"},
        {"item_id": "h1", "prompt": "holdout"},
    ]}))
    split.write_text(json.dumps({"dev": ["d1"], "calibration": [], "holdout": ["h1"]}))
    seal_private, seal_public = tmp_path / "sealer.key", tmp_path / "sealer.pub"
    audit_private, audit_public = tmp_path / "auditor.key", tmp_path / "auditor.pub"
    generate_keypair(seal_private, seal_public)
    generate_keypair(audit_private, audit_public)
    bundle = build_dev_bundle(
        SelectionRequest("selection", "a" * 64, 1, 3),
        dataset_path=dataset, split_path=split, output_root=bundles,
        sealer_private_key=seal_private, sealer_public_key=seal_public,
    )
    config = AuditServiceConfig(work, bundles, seal_public, audit_private, audit_public)
    return spool, config, bundle


def _payload(bundle):
    keys = [(bundle.item_ids[0], 1, "vanilla"), (bundle.item_ids[0], 1, "persona")]
    rows = [{"item_id": item, "random_seed": seed, "condition": condition}
            for item, seed, condition in keys]
    return {
        "batch_id": "batch-1", "item_ids": list(bundle.item_ids), "seeds": [1],
        "conditions": ["vanilla", "persona"],
        "steps": [{**row, "prompt_hash": "prompt", "output_text": "answer"}
                  for row in rows],
        "scores": rows, "sidecars": rows,
        "dev_bundle": {"bundle_id": bundle.bundle_id,
                       "manifest_hash": bundle.manifest_hash,
                       "item_ids": list(bundle.item_ids),
                       "source_hash": bundle.source_hash},
    }


def _result(work, work_id):
    envelope = json.loads((work / "audit" / "results" / f"{work_id}.json").read_text())
    return envelope["result"]


def test_audit_service_complete_claim_result_ack(tmp_path):
    spool, config, bundle = _fixture(tmp_path)
    spool.enqueue("audit", "audit-1", _payload(bundle))

    assert run(config, once=True) == 1
    result = _result(config.work_root, "audit-1")
    assert result["ok"] is True
    assert result["result"]["verdict"] == "PASS"
    assert result["result"]["sealed"]["domain"] == "abcr.audit.attestation.v1"
    assert (config.work_root / "audit" / "acks" / "audit-1.json").is_file()
    assert (config.work_root / "audit" / "archive" / "audit-1.json").is_file()
    assert not (config.work_root / "audit" / "inflight" / "audit-1.json").exists()


def test_audit_payload_cannot_inject_dev_root_or_keys(tmp_path):
    spool, config, bundle = _fixture(tmp_path)
    attacker = tmp_path / "attacker-bundle"
    top = _payload(bundle)
    top["trusted_dev_bundle_root"] = str(attacker)
    spool.enqueue("audit", "attack-top", top)
    nested = _payload(bundle)
    nested["dev_bundle"]["root"] = str(attacker)
    spool.enqueue("audit", "attack-ref", nested)

    assert run(config) == 2
    assert _result(config.work_root, "attack-top") == {
        "ok": False, "error_code": "unknown_fields"}
    assert _result(config.work_root, "attack-ref") == {
        "ok": False, "error_code": "unknown_fields"}
    assert not attacker.exists()


def test_audit_rows_are_not_coerced(tmp_path):
    spool, config, bundle = _fixture(tmp_path)
    payload = _payload(bundle)
    payload["scores"][0]["random_seed"] = "1"
    spool.enqueue("audit", "bad-types", payload)
    assert run(config, once=True) == 1
    assert _result(config.work_root, "bad-types") == {
        "ok": False, "error_code": "invalid_row"}


def test_auditor_doctor_is_read_only(tmp_path):
    _, config, _ = _fixture(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert doctor(config) == {"ok": True, "service": "abcr-auditor", "queue": "audit",
                              "blocked_entries": 0}
    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert after == before


def test_auditor_poison_entry_does_not_block_valid_work(tmp_path):
    spool, config, bundle = _fixture(tmp_path)
    poison = config.work_root / "audit" / "ready" / "bad.queue-entry"
    poison.write_text("poison")
    spool.enqueue("audit", "valid-after-poison", _payload(bundle))
    before = poison.stat().st_mtime_ns
    status = doctor(config)
    assert status["ok"] is False and status["blocked_entries"] == 1
    assert poison.exists() and poison.stat().st_mtime_ns == before

    assert run(config) == 1
    assert _result(config.work_root, "valid-after-poison")["ok"] is True
    assert not poison.exists()
    assert len(list((config.work_root / "audit" / "quarantine").glob("invalid-*.entry"))) == 1


def test_launched_auditor_refuses_environment_path_override(tmp_path):
    import pytest

    with pytest.raises(AuditServiceError, match="override forbidden"):
        load_config({"ABCR_SERVICE_LABEL": "com.abcr.auditor",
                     "ABCR_DEVBUNDLE_ROOT": str(tmp_path)})


def test_auditor_secure_config_override_rejects_symlink(tmp_path):
    import pytest

    _, config, _ = _fixture(tmp_path)
    path = tmp_path / "auditor.json"
    path.write_text(json.dumps({
        "work_root": str(config.work_root),
        "trusted_dev_bundle_root": str(config.trusted_dev_bundle_root),
        "bundle_sealer_public_key": str(config.bundle_sealer_public_key),
        "auditor_private_key": str(config.auditor_private_key),
        "auditor_public_key": str(config.auditor_public_key),
    }))
    path.chmod(0o440)
    assert load_config({"ABCR_AUDITOR_CONFIG_PATH": str(path)}) == config
    link = tmp_path / "auditor-link.json"
    link.symlink_to(path)
    with pytest.raises(AuditServiceError, match="cannot open"):
        load_config({"ABCR_AUDITOR_CONFIG_PATH": str(link)})
