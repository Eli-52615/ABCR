from __future__ import annotations

import json

from abcr.control.ed25519 import generate_keypair
from abcr.control.work_spool import WorkSpool
from abcr.explore.itempool_service import (
    ItemPoolServiceConfig, ItemPoolServiceError, doctor, load_config, run,
)


def _fixture(tmp_path):
    work = tmp_path / "work"
    spool = WorkSpool(work)
    dataset = tmp_path / "dataset.json"
    split = tmp_path / "split.json"
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    dataset.write_text(json.dumps({"items": [
        {"item_id": "d1", "prompt": "dev one"},
        {"item_id": "d2", "prompt": "dev two"},
        {"item_id": "h1", "prompt": "holdout"},
    ]}))
    split.write_text(json.dumps({"dev": ["d1", "d2"], "calibration": [],
                                 "holdout": ["h1"]}))
    private, public = tmp_path / "sealer.key", tmp_path / "sealer.pub"
    generate_keypair(private, public)
    config = ItemPoolServiceConfig(work, dataset, split, bundles, private, public)
    return spool, config


def _result(work, work_id):
    envelope = json.loads((work / "itempool" / "results" / f"{work_id}.json").read_text())
    return envelope["result"]


def test_itempool_service_complete_claim_result_ack(tmp_path):
    spool, config = _fixture(tmp_path)
    spool.enqueue("itempool", "select-1", {
        "request_id": "selection-1", "goal_hash": "a" * 64, "count": 1, "seed": 7,
        "excluded_item_ids": ["d1"],
    })

    assert run(config, once=True) == 1
    result = _result(config.work_root, "select-1")
    assert result["ok"] is True
    assert result["result"]["item_ids"] == ["d2"]
    assert set(result["result"]) == {"bundle_id", "manifest_hash", "item_ids", "source_hash"}
    assert (config.work_root / "itempool" / "acks" / "select-1.json").is_file()
    assert (config.work_root / "itempool" / "archive" / "select-1.json").is_file()
    assert not (config.work_root / "itempool" / "inflight" / "select-1.json").exists()


def test_itempool_payload_cannot_inject_dataset_split_output_or_key(tmp_path):
    spool, config = _fixture(tmp_path)
    attacker = tmp_path / "attacker-output"
    for index, injected in enumerate(("dataset_path", "split_path", "output_root",
                                      "sealer_private_key"), 1):
        spool.enqueue("itempool", f"attack-{index}", {
            "request_id": f"attack-{index}", "goal_hash": "b" * 64,
            "count": 1, "seed": index, injected: str(attacker),
        })
    assert run(config) == 4
    for index in range(1, 5):
        result = _result(config.work_root, f"attack-{index}")
        assert result == {"ok": False, "error_code": "unknown_fields"}
    assert not attacker.exists()
    assert list(config.output_root.iterdir()) == []


def test_itempool_doctor_is_read_only(tmp_path):
    _, config = _fixture(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert doctor(config) == {"ok": True, "service": "abcr-itempool", "queue": "itempool",
                              "blocked_entries": 0}
    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    assert after == before


def test_itempool_poison_entry_does_not_block_valid_work(tmp_path):
    spool, config = _fixture(tmp_path)
    poison = config.work_root / "itempool" / "ready" / "not-valid.txt"
    poison.write_text("poison")
    spool.enqueue("itempool", "valid-after-poison", {
        "request_id": "valid-after-poison", "goal_hash": "c" * 64, "count": 1, "seed": 1,
    })
    before = poison.stat().st_mtime_ns
    status = doctor(config)
    assert status["ok"] is False and status["blocked_entries"] == 1
    assert poison.exists() and poison.stat().st_mtime_ns == before

    assert run(config) == 1
    assert _result(config.work_root, "valid-after-poison")["ok"] is True
    assert not poison.exists()
    assert len(list((config.work_root / "itempool" / "quarantine").glob("invalid-*.entry"))) == 1


def test_launched_itempool_refuses_environment_path_override(tmp_path):
    import pytest

    with pytest.raises(ItemPoolServiceError, match="override forbidden"):
        load_config({"ABCR_SERVICE_LABEL": "com.abcr.itempool",
                     "ABCR_WORK_ROOT": str(tmp_path)})


def test_itempool_secure_config_override_rejects_symlink(tmp_path):
    import pytest

    _, config = _fixture(tmp_path)
    path = tmp_path / "itempool.json"
    path.write_text(json.dumps({
        "work_root": str(config.work_root), "dataset_path": str(config.dataset_path),
        "split_path": str(config.split_path), "output_root": str(config.output_root),
        "sealer_private_key": str(config.sealer_private_key),
        "sealer_public_key": str(config.sealer_public_key),
    }))
    path.chmod(0o600)
    assert load_config({"ABCR_ITEMPOOL_CONFIG_PATH": str(path)}) == config
    link = tmp_path / "itempool-link.json"
    link.symlink_to(path)
    with pytest.raises(ItemPoolServiceError, match="cannot open"):
        load_config({"ABCR_ITEMPOOL_CONFIG_PATH": str(link)})
