from __future__ import annotations

import json

import pytest

from abcr.control.contracts import ContractError
from abcr.control.store import ControlStore
from abcr.control.ed25519 import generate_keypair
from abcr.explore.compiler import (ArtifactFrozenReceipt, compile_goal, freeze_goal,
                                   prepare_goal_anchor, sign_frozen_receipt)
from abcr.explore.goal import validate_goal
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle, iter_bundle_items
from abcr.explore.personas import PersonaRegistry
from tests.explore.test_goal_persona import behavior_probe_goal


def sources(tmp_path):
    dataset = tmp_path / "dataset.json"; split = tmp_path / "split.json"
    dataset.write_text(json.dumps({"items": [
        {"item_id": "d1", "prompt": "one"}, {"item_id": "d2", "prompt": "two"},
        {"item_id": "d3", "prompt": "three"}, {"item_id": "c1", "prompt": "secret cal"},
        {"item_id": "h1", "prompt": "secret hold"},
    ]}))
    split.write_text(json.dumps({"dev": ["d1", "d2", "d3"], "calibration": ["c1"], "holdout": ["h1"]}))
    return dataset, split


def itempool_keys(tmp_path):
    """封印密钥对 = dev bundle 的信任根。攻击者拿不到私钥就伪造不出封印。"""
    private, public = tmp_path / "sealer.pem", tmp_path / "sealer.pub"
    generate_keypair(private, public)
    return private, public


def sealed_bundle(request, *, dataset_path, split_path, output_root, keys):
    """测试助手:用给定封印密钥建一个合法 dev bundle。"""
    return build_dev_bundle(request, dataset_path=dataset_path, split_path=split_path,
                            output_root=output_root, sealer_private_key=keys[0],
                            sealer_public_key=keys[1])


def registry():
    p = PersonaRegistry(); p.add({"persona_id": "p", "version": 1, "parent_ref": None,
                                  "components": {"stance": "careful"}, "changed_component": None,
                                  "manipulation_checks": ["careful"]}); return p


def test_itempool_exports_only_dev_and_honors_exclusion(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    ref = sealed_bundle(SelectionRequest("S1", "a" * 64, 2, 3, ("d1",)),
                        dataset_path=dataset, split_path=split,
                        output_root=tmp_path / "bundles", keys=keys)
    rows = list(iter_bundle_items(ref, tmp_path / "bundles", sealer_public_key=keys[1]))
    assert {x["item_id"] for x in rows} <= {"d2", "d3"}
    assert b"secret cal" not in (ref.root / "items.jsonl").read_bytes()
    assert b"secret hold" not in (ref.root / "items.jsonl").read_bytes()


def test_itempool_capacity_and_tamper_fail_closed(tmp_path):
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    with pytest.raises(ContractError) as exc:
        sealed_bundle(SelectionRequest("S1", "a" * 64, 3, 3, ("d1",)),
                      dataset_path=dataset, split_path=split,
                      output_root=tmp_path / "bundles", keys=keys)
    assert exc.value.details == {"needed": 3, "available": 2}
    ref = sealed_bundle(SelectionRequest("S2", "b" * 64, 1, 1),
                        dataset_path=dataset, split_path=split,
                        output_root=tmp_path / "bundles", keys=keys)
    (ref.root / "items.jsonl").write_text('{"item_id":"c1"}\n')
    with pytest.raises(ContractError):
        list(iter_bundle_items(ref, tmp_path / "bundles", sealer_public_key=keys[1]))


def test_compile_requires_matching_frozen_anchor(tmp_path):
    goal = validate_goal(behavior_probe_goal()).goal; assert goal
    dataset, split = sources(tmp_path)
    keys = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("S", goal.goal_hash, 2, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=keys)
    candidate = prepare_goal_anchor(goal, research_commit="c" * 64,
                                    relative_path="goals/g.yaml", confirmed_by="owner",
                                    deployment_id="fixture", protocol_ref="W1-CONTROL-V1")
    private, public = tmp_path / "r.pem", tmp_path / "r.pub"
    generate_keypair(private, public)
    receipt = sign_frozen_receipt(ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now"),
                                  private_key=private, public_key=public)
    anchor = freeze_goal(candidate, receipt, receipt_public_key=public)
    result = compile_goal(goal, anchor, bundle, registry(), protocol_ref="W1-CONTROL-V1",
                          trusted_dev_bundle_root=tmp_path / "bundles",
                          bundle_sealer_public_key=keys[1], deployment_id="fixture")
    assert result.envelope["split"] == "dev"
    assert result.envelope["item_ids"] == list(bundle.item_ids)
    bad = sign_frozen_receipt(ArtifactFrozenReceipt("R2", "f" * 64, "c" * 64, "now"),
                              private_key=private, public_key=public)
    with pytest.raises(ContractError): freeze_goal(candidate, bad, receipt_public_key=public)
    # 未签名收据同样不可接受(不存在免验签路径)。
    unsigned = ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now")
    with pytest.raises(ContractError):
        freeze_goal(candidate, unsigned, receipt_public_key=public)
