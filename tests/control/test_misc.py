from __future__ import annotations

from datetime import datetime, timedelta, timezone

from abcr.audit.evidence import audit_evidence
from abcr.control.ed25519 import generate_keypair
from abcr.control.cost_eta import estimate
from abcr.control.doc_mirror import BEGIN, END, patch_marked_block
from abcr.control.readmodel import build_snapshot
from abcr.control.store import ControlStore
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from tests.explore.test_itempool_workflow import itempool_keys, sealed_bundle, sources


def test_cost_staleness_and_document_marked_patch(tmp_path):
    now = datetime.now(timezone.utc); envelope = {"item_ids": ["i"], "seeds": [1], "arms": [{}, {}]}
    profile = {"usd_per_million_input_tokens": 1, "usd_per_million_output_tokens": 2,
               "seconds_per_item": 3, "valid_until": (now + timedelta(minutes=1)).isoformat()}
    assert estimate(envelope, profile, now=now).state == "KNOWN"
    profile["valid_until"] = (now - timedelta(seconds=1)).isoformat()
    assert estimate(envelope, profile, now=now).state == "UNKNOWN"
    snapshot = build_snapshot(ControlStore(tmp_path / "control.db"))
    original = "keep\n" + BEGIN + "\nold\n" + END + "\ntail"
    patched, digest = patch_marked_block(original, snapshot)
    assert patched.startswith("keep") and patched.endswith("tail") and "old" not in patched and len(digest) == 64


def test_exact_evidence_set_controls_citable(tmp_path):
    dataset, split = sources(tmp_path)
    sealer = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("s", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=sealer)
    item_id = bundle.item_ids[0]
    auditor_key, auditor_pub = tmp_path / "a.pem", tmp_path / "a.pub"
    generate_keypair(auditor_key, auditor_pub)
    keys = [(item_id, 1, "vanilla"), (item_id, 1, "persona")]
    steps = [{"item_id": i, "random_seed": s, "condition": c,
              "prompt_hash": "p", "output_text": "x"} for i, s, c in keys]
    scores = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    sidecars = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    result = audit_evidence(batch_id="b", item_ids=(item_id,), seeds=(1,),
                            conditions=("vanilla", "persona"), steps=steps, scores=scores,
                            sidecars=sidecars, dev_bundle=bundle,
                            trusted_dev_bundle_root=tmp_path / "bundles",
                            bundle_sealer_public_key=sealer[1],
                            auditor_private_key=auditor_key, auditor_public_key=auditor_pub)
    assert result.verdict == "PASS"
    bad = audit_evidence(batch_id="b", item_ids=(item_id,), seeds=(1,),
                         conditions=("vanilla", "persona"), steps=steps + [steps[0]], scores=scores,
                         sidecars=sidecars, dev_bundle=bundle,
                         trusted_dev_bundle_root=tmp_path / "bundles",
                         bundle_sealer_public_key=sealer[1],
                         auditor_private_key=auditor_key, auditor_public_key=auditor_pub)
    assert bad.verdict == "FAIL" and "steps_duplicate_key" in bad.defects
