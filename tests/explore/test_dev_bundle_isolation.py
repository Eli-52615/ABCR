"""P0-1 回归:holdout 题包绝不能到达 probe 引擎。

历史漏洞与两轮修复:
- 初版:`run_probe` 经 `iter_bundle_items` 只做内部自洽检查,手搓目录即可绕过。
- 第一轮修复:加了「可信根」位置门 + `split=="dev"` 标签检查。**被独立复审攻破** ——
  所有组件同 uid,可信根只是目录成员资格、不是权限边界;把标签从 holdout 改成 dev、
  把 holdout 题塞进真实可信根内,即通过。检查的是「标签写着 dev」,不是「标签是真的」。
- 第二轮修复(本文件测的):itempool 用封印私钥对 (split, item_ids, items_sha256,
  source_sha256) 签名。信任根从「bundle 自洽」变成「itempool 封印」。攻击者拿不到
  itempool 私钥,就签不出匹配封印 —— verify 在验签这关 fail-closed。

每个用例都执行一次真实攻击并断言现在 fail-closed。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.explore.item_pool import (DevBundleRef, SelectionRequest, build_dev_bundle,
                                    iter_bundle_items, verify_dev_bundle)
from abcr.probe.contracts import ProbePersona, ProbeRequest
from abcr.probe.engine import FakeProbeEngine, run_probe
from tests.explore.test_itempool_workflow import itempool_keys, sealed_bundle, sources


def _forge_bundle(root: Path, *, split: str, items: list[dict],
                  attacker_keys=None) -> DevBundleRef:
    """手搓一个自洽的 bundle 目录,正如攻击者所为。

    attacker_keys 若给出,则用攻击者自己的密钥签一份封印 —— 用来证明「自签封印」
    照样被拒(公钥不是可信 itempool 的公钥)。不给则完全没有 seal.json。
    """
    root.mkdir(parents=True, exist_ok=True)
    items_raw = b"".join(canonical_json(item) + b"\n" for item in items)
    item_ids = [item["item_id"] for item in items]
    core = {
        "schema_version": 1, "request_id": "EVIL", "goal_hash": "a" * 64, "seed": 1,
        "split": split, "item_ids": item_ids, "item_count": len(item_ids),
        "items_sha256": sha256(items_raw), "source_sha256": "b" * 64,
        "excluded_item_ids": [], "created_at": "2026-07-19T00:00:00Z",
    }
    bundle_id = sha256(core)
    manifest = dict(core, bundle_id=bundle_id,
                    files=[{"path": "items.jsonl", "size": len(items_raw),
                            "sha256": sha256(items_raw)}])
    bundle = root / bundle_id
    bundle.mkdir()
    (bundle / "items.jsonl").write_bytes(items_raw)
    (bundle / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    if attacker_keys is not None:
        from abcr.control.attestation import DOMAIN_DEV_BUNDLE, sign_attestation
        from abcr.explore.item_pool import _dev_bundle_seal_core
        seal = sign_attestation(private_key=attacker_keys[0], public_key=attacker_keys[1],
                                domain=DOMAIN_DEV_BUNDLE, core=_dev_bundle_seal_core(manifest))
        (bundle / "seal.json").write_bytes(canonical_json(seal) + b"\n")
    return DevBundleRef(bundle_id, bundle, sha256(manifest), tuple(item_ids), "b" * 64)


HOLDOUT_ITEMS = [{"item_id": "h1", "prompt": "secret hold"},
                 {"item_id": "c1", "prompt": "secret cal"}]


def _probe_request(ref: DevBundleRef) -> ProbeRequest:
    return ProbeRequest("P1", "a" * 64, ref,
                        (ProbePersona("p@v1", "careful"),),
                        "increase", 1, "fixture")


# --- 复审攻破的那个攻击,原样固化(本轮修复的靶心)----------------------------------

def test_dev_labelled_holdout_inside_trusted_root_is_blocked_by_seal(tmp_path):
    """复审 A1:标签改成 dev、holdout 题、放进真实可信根内。

    第一轮修复放行了它;封印修复必须挡住。攻击者甚至自签一份封印,但用的是
    自己的密钥,不是可信 itempool 的密钥。
    """
    keys = itempool_keys(tmp_path)          # 可信 itempool 密钥(攻击者没有私钥)
    attacker_keys = tmp_path / "atk.pem", tmp_path / "atk.pub"
    generate_keypair(*attacker_keys)

    trusted = tmp_path / "bundles"
    dataset, split = sources(tmp_path)
    # 先建一个真 bundle 确立可信根。
    sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1), dataset_path=dataset,
                  split_path=split, output_root=trusted, keys=keys)

    # 攻击者把 dev 标签的 holdout bundle(自签)写进同一可信根。
    evil = _forge_bundle(trusted, split="dev", items=HOLDOUT_ITEMS,
                         attacker_keys=attacker_keys)

    # bundle 内部完全自洽 —— 第一轮修复检查的全部通过。
    manifest = json.loads((evil.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["split"] == "dev"
    assert manifest["items_sha256"] == sha256((evil.root / "items.jsonl").read_bytes())

    # 但封印是攻击者自己的密钥签的 → 用可信公钥验签失败。
    with pytest.raises(ContractError) as exc:
        verify_dev_bundle(evil, trusted, sealer_public_key=keys[1])
    assert exc.value.code == "bundle_seal_invalid"

    # run_probe 同样挡住,holdout 到不了引擎。
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(evil), FakeProbeEngine(),
                  trusted_dev_bundle_root=trusted, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_seal_invalid"


def test_forged_bundle_with_no_seal_at_all_is_rejected(tmp_path):
    """完全不带 seal.json 的手搓 bundle → 文件集不符,fail-closed。"""
    keys = itempool_keys(tmp_path)
    evil = _forge_bundle(tmp_path / "evil", split="dev", items=HOLDOUT_ITEMS)
    with pytest.raises(ContractError) as exc:
        verify_dev_bundle(evil, tmp_path / "evil", sealer_public_key=keys[1])
    assert exc.value.code == "bundle_files_unexpected"


def test_seal_from_a_different_bundle_cannot_be_transplanted(tmp_path):
    """把一个合法 bundle 的 seal.json 移植到另一份内容上 → core 不匹配,拒绝。"""
    keys = itempool_keys(tmp_path)
    dataset, split = sources(tmp_path)
    trusted = tmp_path / "bundles"
    good = sealed_bundle(SelectionRequest("G", "a" * 64, 1, 1), dataset_path=dataset,
                         split_path=split, output_root=trusted, keys=keys)
    evil = _forge_bundle(tmp_path / "evil", split="dev", items=HOLDOUT_ITEMS)
    # 把合法封印移植到 holdout 目录。
    (evil.root / "seal.json").write_bytes((good.root / "seal.json").read_bytes())
    with pytest.raises(ContractError) as exc:
        verify_dev_bundle(evil, tmp_path / "evil", sealer_public_key=keys[1])
    # 合法封印锚定的是 good 的 core,与 evil 的 manifest 不符。
    assert exc.value.code in {"bundle_seal_invalid", "bundle_root_untrusted"}


def test_verify_requires_sealer_public_key(tmp_path):
    """封印公钥无默认值:缺它必须 fail-closed,不能悄悄降级为不验封印。"""
    import inspect
    sig = inspect.signature(verify_dev_bundle)
    assert sig.parameters["sealer_public_key"].default is inspect.Parameter.empty
    assert sig.parameters["sealer_public_key"].kind is inspect.Parameter.KEYWORD_ONLY

    keys = itempool_keys(tmp_path)
    dataset, split = sources(tmp_path)
    ref = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1), dataset_path=dataset,
                        split_path=split, output_root=tmp_path / "bundles", keys=keys)
    for bad in (None, "", "   "):
        with pytest.raises(ContractError) as exc:
            verify_dev_bundle(ref, tmp_path / "bundles", sealer_public_key=bad)
        assert exc.value.code == "bundle_sealer_key_missing"


def test_build_requires_sealer_keys():
    """build_dev_bundle 的封印密钥无默认值 —— 无密钥不得建 bundle。"""
    import inspect
    sig = inspect.signature(build_dev_bundle)
    for name in ("sealer_private_key", "sealer_public_key"):
        assert sig.parameters[name].default is inspect.Parameter.empty


# --- 位置/符号链接/身份类攻击(第一轮已挡,回归保留)-------------------------------

def test_trusted_root_has_no_default_on_either_entry_point():
    """默认值就是后门;两个入口都必须强制传根。"""
    import inspect
    assert inspect.signature(iter_bundle_items).parameters["trusted_root"].default \
        is inspect.Parameter.empty
    param = inspect.signature(run_probe).parameters["trusted_dev_bundle_root"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_bundle_claiming_dev_but_outside_trusted_root_is_rejected(tmp_path):
    """off-root 的手搓 bundle:即便自洽也不在可信根内。"""
    keys = itempool_keys(tmp_path)
    real_root = tmp_path / "bundles"; real_root.mkdir()
    ref = _forge_bundle(tmp_path / "rogue", split="dev", items=HOLDOUT_ITEMS)
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(ref), FakeProbeEngine(),
                  trusted_dev_bundle_root=real_root, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_root_untrusted"


def test_symlinked_bundle_pointing_at_holdout_is_rejected(tmp_path):
    keys = itempool_keys(tmp_path)
    trusted = tmp_path / "bundles"; trusted.mkdir()
    ref = _forge_bundle(tmp_path / "stash", split="holdout", items=HOLDOUT_ITEMS)
    link = trusted / ref.bundle_id
    link.symlink_to(ref.root, target_is_directory=True)
    linked = DevBundleRef(ref.bundle_id, link, ref.manifest_hash, ref.item_ids, ref.source_hash)
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(linked), FakeProbeEngine(),
                  trusted_dev_bundle_root=trusted, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_path_unsafe"


def test_symlinked_items_file_pointing_at_holdout_is_rejected(tmp_path):
    keys = itempool_keys(tmp_path)
    dataset, split = sources(tmp_path)
    trusted = tmp_path / "bundles"
    ref = sealed_bundle(SelectionRequest("S", "a" * 64, 1, 1), dataset_path=dataset,
                        split_path=split, output_root=trusted, keys=keys)
    holdout = tmp_path / "holdout.jsonl"
    holdout.write_bytes(canonical_json(HOLDOUT_ITEMS[0]) + b"\n")
    (ref.root / "items.jsonl").unlink()
    (ref.root / "items.jsonl").symlink_to(holdout)
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(ref), FakeProbeEngine(),
                  trusted_dev_bundle_root=trusted, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_path_unsafe"


def test_bundle_directory_swapped_for_another_legitimate_dev_bundle(tmp_path):
    keys = itempool_keys(tmp_path)
    dataset, split = sources(tmp_path)
    trusted = tmp_path / "bundles"
    first = sealed_bundle(SelectionRequest("S1", "a" * 64, 1, 1), dataset_path=dataset,
                          split_path=split, output_root=trusted, keys=keys)
    second = sealed_bundle(SelectionRequest("S2", "b" * 64, 2, 7), dataset_path=dataset,
                           split_path=split, output_root=trusted, keys=keys)
    assert first.bundle_id != second.bundle_id
    swapped = DevBundleRef(first.bundle_id, second.root, first.manifest_hash,
                           first.item_ids, first.source_hash)
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(swapped), FakeProbeEngine(),
                  trusted_dev_bundle_root=trusted, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_root_untrusted"


@pytest.mark.parametrize("bad_root", [None, "", "   "])
def test_empty_or_none_trusted_root_fails_closed(tmp_path, bad_root):
    keys = itempool_keys(tmp_path)
    ref = _forge_bundle(tmp_path / "evil", split="holdout", items=HOLDOUT_ITEMS)
    with pytest.raises(ContractError) as exc:
        list(iter_bundle_items(ref, bad_root, sealer_public_key=keys[1]))
    assert exc.value.code == "bundle_root_untrusted"
    with pytest.raises(ContractError) as exc:
        run_probe(_probe_request(ref), FakeProbeEngine(),
                  trusted_dev_bundle_root=bad_root, bundle_sealer_public_key=keys[1])
    assert exc.value.code == "bundle_root_untrusted"


# --- 合法路径仍然可用 --------------------------------------------------------------

def test_genuine_dev_bundle_under_trusted_root_still_probes(tmp_path):
    keys = itempool_keys(tmp_path)
    dataset, split = sources(tmp_path)
    trusted = tmp_path / "bundles"
    ref = sealed_bundle(SelectionRequest("S", "a" * 64, 2, 3, ("d1",)), dataset_path=dataset,
                        split_path=split, output_root=trusted, keys=keys)
    run = run_probe(_probe_request(ref), FakeProbeEngine(),
                    trusted_dev_bundle_root=trusted, bundle_sealer_public_key=keys[1])
    probed = {row["item_id"] for row in run.rows}
    assert probed == set(ref.item_ids)
    assert probed <= {"d2", "d3"}
    assert not any(row["citable"] for row in run.rows)
