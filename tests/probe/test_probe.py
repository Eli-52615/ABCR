from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.probe.contracts import ProbeRequest
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
    run = run_probe(ProbeRequest("P1", "a" * 64, bundle, "p@v1", "careful",
                                 "increase", 1, "fixture"), FakeProbeEngine(),
                    trusted_dev_bundle_root=tmp_path / "bundles",
                    bundle_sealer_public_key=keys[1])
    row = run.rows[0]; assert not row["citable"]
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
    request = ProbeRequest("P1", "a" * 64, bundle, "p@v1", "careful",
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
