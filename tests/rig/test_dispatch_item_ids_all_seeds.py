from __future__ import annotations

import json

import pytest

from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.common import approval_token as tok
from abcr.common.ledger_ref import RunLedger
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.governor.envelope import envelope_sha256
from abcr.ops import cloud, dispatch


def _sealed_config(tmp_path):
    dataset = tmp_path / "dataset.json"
    split = tmp_path / "split.json"
    dataset.write_text(json.dumps({"items": [
        {"item_id": "dev-a", "family": "ifeval_zh_v1", "prompt": "alpha",
         "check_type": "exact_output", "check_args": {"expected": "alpha"}},
        {"item_id": "dev-b", "family": "ifeval_zh_v1", "prompt": "beta",
         "check_type": "exact_output", "check_args": {"expected": "beta"}},
        {"item_id": "hold-z", "family": "ifeval_zh_v1", "prompt": "secret",
         "check_type": "exact_output", "check_args": {"expected": "secret"}},
    ]}), encoding="utf-8")
    split.write_text(json.dumps({"dev": ["dev-a", "dev-b"],
                                 "calibration": [], "holdout": ["hold-z"]}), encoding="utf-8")
    private = tmp_path / "itempool.pem"; public = tmp_path / "itempool.pub"
    generate_keypair(private, public)
    bundles = tmp_path / "bundles"
    ref = build_dev_bundle(SelectionRequest("selection-1", "a" * 64, 2, 7),
                           dataset_path=dataset, split_path=split, output_root=bundles,
                           sealer_private_key=private, sealer_public_key=public)
    manifest = json.loads((ref.root / "manifest.json").read_text(encoding="utf-8"))
    ref_json = {"bundle_id": ref.bundle_id, "manifest_hash": ref.manifest_hash,
                "item_ids": list(ref.item_ids), "source_hash": ref.source_hash}
    receipt = dict(ref_json, split="dev", selected_bytes_hash=manifest["items_sha256"])
    release = {"release_id": "fixture", "release_tree_hash": "d" * 64,
               "release_lock_hash": "e" * 64}
    cfg = {
        "benchmark": {"family": "ifeval_zh_v1", "split": "dev", "item_limit": 2},
        "condition": "vanilla", "decoding": {"seeds": [11, 29]},
        "item_ids": list(ref.item_ids), "dev_bundle_ref": ref_json,
        "selection_receipt": receipt, "release_pin": release,
    }
    return cfg, bundles, public


def test_dispatch_uses_explicit_bundle_items_and_never_golden(tmp_path):
    cfg, root, public = _sealed_config(tmp_path)
    rows = dispatch.load_dispatch_items(cfg, trusted_root=root, sealer_public_key=public)
    assert [row["item_id"] for row in rows] == cfg["item_ids"]
    assert {row["prompt"] for row in rows} == {"alpha", "beta"}
    assert "g01" not in {row["item_id"] for row in rows}


def test_dispatch_runs_every_configured_seed_with_unique_hash(tmp_path):
    cfg, _, _ = _sealed_config(tmp_path)
    expanded = dispatch.expand_all_seed_configs([cfg])
    assert [row["decoding"]["seeds"] for row in expanded] == [[11], [29]]
    assert len({dispatch.config_hash(row) for row in expanded}) == 2
    assert cfg["decoding"]["seeds"] == [11, 29]  # derivation never mutates approved bytes


def test_dispatch_e2e_registers_and_executes_all_bundle_seeds(tmp_path, monkeypatch):
    cfg, bundles, public = _sealed_config(tmp_path)
    top = {"goal_hash": "1" * 64, "goal_receipt_id": "receipt-1",
           "research_commit": "2" * 64, "deployment_id": "dep-1",
           "protocol_ref": "W1-CONTROL-V1"}
    cfg.update({"config_version": "1.0", "protocol_ref": top["protocol_ref"],
                "arm_id": "vanilla", "model": {"engine": "fake"},
                "intervention": None})
    cfg["evidence_inputs"] = {
        **top, "dev_bundle_id": cfg["dev_bundle_ref"]["bundle_id"],
        "dev_bundle_manifest_hash": cfg["dev_bundle_ref"]["manifest_hash"],
        "source_hash": cfg["dev_bundle_ref"]["source_hash"],
        "item_set_hash": sha256(cfg["item_ids"]),
        "selected_bytes_hash": cfg["selection_receipt"]["selected_bytes_hash"],
        **cfg["release_pin"],
    }
    envelope = {
        "envelope_version": "1.0", "batch_id": "B-20260719T000000Z-0001", **top,
        "scope": {"benchmark_families": ["ifeval_zh_v1"], "conditions": ["vanilla"],
                  "splits": ["dev"], "item_limit_per_run": 2,
                  "seeds": [11, 29], "trait_whitelist": []},
        "budget": {"gpu_hours_max": 0, "cost_cap_cny": 0},
        "deadline_utc": "2099-01-01T00:00:00+00:00", "run_configs": [cfg],
        "drafted_by": "fixture",
    }
    key = tmp_path / "approval.key"; key.write_bytes(b"p4-fixture-key")
    envelope["approval"] = {"token": tok.sign_token(
        envelope["batch_id"], envelope_sha256(envelope), human_secret=key.read_bytes())}
    env_path = tmp_path / "envelope.json"
    env_path.write_text(json.dumps(envelope), encoding="utf-8")
    for name, path in {
        "ABCR_DEV_BUNDLE_ROOT": bundles, "ABCR_DEV_BUNDLE_SEALER_PUBLIC_KEY": public,
        "ABCR_LEDGER_DIR": tmp_path / "ledger", "ABCR_RUNS_ROOT": tmp_path / "runs",
        "ABCR_QUEUE_ROOT": tmp_path / "queue", "ABCR_STATE_DIR": tmp_path / "state",
        "ABCR_RUNSTATE_ROOT": tmp_path / "runstate",
    }.items():
        monkeypatch.setenv(name, str(path))
    monkeypatch.setattr(dispatch.external_seal, "guarded_reseal",
                        lambda *args, **kwargs: {"length": 0})
    assert dispatch.dispatch(str(env_path), str(key)) == 0
    events = RunLedger(tmp_path / "ledger", "runs_index").events(event="run_registered")
    assert len(events) == 2
    observed = set()
    for event in events:
        steps = [json.loads(line) for line in
                 (tmp_path / "runs" / event["subject_id"] / "steps.jsonl").read_text().splitlines()]
        observed.update((step["item_id"], step["random_seed"]) for step in steps)
    assert observed == {(item_id, seed) for item_id in cfg["item_ids"] for seed in (11, 29)}


def test_dispatch_split_injection_fails_without_reading_full_split(tmp_path):
    cfg, root, public = _sealed_config(tmp_path)
    cfg["benchmark"]["split"] = "holdout"
    with pytest.raises(ContractError, match="split=dev"):
        dispatch.load_dispatch_items(cfg, trusted_root=root, sealer_public_key=public)
    cfg.pop("dev_bundle_ref")
    with pytest.raises(ContractError, match="必须使用封印 DevBundle"):
        dispatch.load_dispatch_items(cfg, trusted_root=root, sealer_public_key=public)


def test_each_run_config_repeats_compile_research_binding(tmp_path):
    cfg, root, public = _sealed_config(tmp_path)
    rows = dispatch.load_dispatch_items(cfg, trusted_root=root, sealer_public_key=public)
    envelope = {"goal_hash": "1" * 64, "goal_receipt_id": "receipt-1",
                "research_commit": "2" * 64, "deployment_id": "dep-1",
                "protocol_ref": "W1-CONTROL-V1"}
    cfg["evidence_inputs"] = {
        **envelope, "dev_bundle_id": cfg["dev_bundle_ref"]["bundle_id"],
        "dev_bundle_manifest_hash": cfg["dev_bundle_ref"]["manifest_hash"],
        "source_hash": cfg["dev_bundle_ref"]["source_hash"],
        "item_set_hash": sha256(cfg["item_ids"]),
        "selected_bytes_hash": cfg["selection_receipt"]["selected_bytes_hash"],
        **cfg["release_pin"],
    }
    dispatch._validate_compile_binding(cfg, envelope, rows)
    cfg["evidence_inputs"]["research_commit"] = "3" * 64
    with pytest.raises(ContractError, match="research_commit"):
        dispatch._validate_compile_binding(cfg, envelope, rows)


def test_cloud_payload_carries_bundle_refs_not_corpus_or_item_bytes(tmp_path):
    cfg, _, _ = _sealed_config(tmp_path)
    envelope = {"batch_id": "B-20260719T000000Z-0001", "run_configs": [cfg]}
    payload = cloud.build_cloud_payload(envelope)
    assert payload["dev_bundle_refs"] == [cfg["dev_bundle_ref"]]
    assert "alpha" not in json.dumps(payload, ensure_ascii=False)
    cfg["dataset_root"] = "/full/benchmark"
    with pytest.raises(ContractError, match="禁止全量"):
        cloud.build_cloud_payload(envelope)
