from __future__ import annotations

import json
import os
import sys

import pytest

from abcr.control.black_box_oracle import (
    FIXTURE_UNSANDBOXED, SANDBOX_EXEC, UNSANDBOXED_LABEL, OracleRegistry, OracleSpec,
    SigningIdentity, equality_assertion, is_release_eligible_isolation, isolation_label,
    run_external_oracle, verify_oracle_receipt,
)
from abcr.control.contracts import ContractError
from abcr.control.ed25519 import generate_keypair
from abcr.control.test_controller import run_profile, verify_test_result_bundle

HAS_SANDBOX = os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)


def registry():
    item = OracleRegistry(); item.register("equal", "1", equality_assertion); return item


def identity(tmp_path) -> SigningIdentity:
    keys = tmp_path / "keys"; keys.mkdir(parents=True, exist_ok=True)
    private, public = keys / "controller.key", keys / "controller.pub"
    generate_keypair(private, public)
    return SigningIdentity(private, public)


def candidate_code(mode: str) -> tuple[str, ...]:
    if mode == "exit0": return (sys.executable, "-c", "import os; os._exit(0)")
    if mode == "fake_junit": return (sys.executable, "-c", "print('<testsuite failures=\\\"0\\\"/>')")
    if mode == "duplicate":
        code = "import sys,json;q=json.loads(sys.stdin.readline());print('{\\\"nonce\\\":\\\"x\\\",\\\"nonce\\\":'+json.dumps(q['nonce'])+',\\\"result\\\":4}')"
        return (sys.executable, "-c", code)
    if mode == "nan":
        code = "import sys,json;q=json.loads(sys.stdin.readline());print('{\\\"nonce\\\":'+json.dumps(q['nonce'])+',\\\"result\\\":NaN}')"
        return (sys.executable, "-c", code)
    code = "import sys,json; q=json.loads(sys.stdin.readline()); print(json.dumps({'nonce':q['nonce'],'result':q['request']['expected']}))"
    return (sys.executable, "-c", code)


# ---------------------------------------------------------------- protocol layer (unchanged strengths)

def test_parent_oracle_pass_and_early_exit_fake_pass_fail(tmp_path):
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})

    def run(mode):
        return run_external_oracle(spec, candidate_code(mode), registry(),
                                   isolation=FIXTURE_UNSANDBOXED, signer=signer)

    assert run("good").verdict == "PASS"
    assert run("exit0").verdict == "FAIL"
    assert run("fake_junit").verdict == "FAIL"
    assert run("duplicate").verdict == "FAIL"
    assert run("nan").verdict == "FAIL"


def test_profile_requires_complete_trusted_receipts(tmp_path):
    signer = identity(tmp_path)
    profile = {"required_external_oracle_ids": ["equal"],
               "external_oracles": [{"oracle_id": "equal", "version": "1",
                                      "request": {"expected": 4}}]}
    good = run_profile(mission_id="m", fencing_token=1, candidate_tree_hash="a" * 64,
                       profile=profile, candidate_argv=candidate_code("good"), registry=registry(),
                       isolation=FIXTURE_UNSANDBOXED, signer=signer)
    bad = run_profile(mission_id="m", fencing_token=1, candidate_tree_hash="a" * 64,
                      profile=profile, candidate_argv=candidate_code("exit0"), registry=registry(),
                      isolation=FIXTURE_UNSANDBOXED, signer=signer)
    assert good.verdict == "PASS" and bad.verdict == "FAIL"


# ---------------------------------------------------------------- P0-6 mandatory isolation

def test_isolation_is_a_required_argument(tmp_path):
    """隔离不是可选项 —— 不传 isolation 直接 TypeError,不存在默认裸跑。"""
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})
    with pytest.raises(TypeError):
        run_external_oracle(spec, candidate_code("good"), registry(), signer=signer)
    with pytest.raises(TypeError):
        run_profile(mission_id="m", fencing_token=1, candidate_tree_hash="a" * 64,
                    profile={}, candidate_argv=candidate_code("good"), registry=registry(),
                    signer=signer)


def test_sentinel_must_be_the_object_not_a_lookalike_string(tmp_path):
    """裸字符串 "FIXTURE_UNSANDBOXED" 不被接受,哨兵必须显式 import。"""
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})
    with pytest.raises(ContractError):
        run_external_oracle(spec, candidate_code("good"), registry(),
                            isolation=UNSANDBOXED_LABEL, signer=signer)
    with pytest.raises(ContractError):
        isolation_label(None)
    with pytest.raises(ContractError):
        isolation_label("")


def test_sentinel_is_recorded_in_receipt_and_is_not_release_eligible(tmp_path):
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})
    receipt = run_external_oracle(spec, candidate_code("good"), registry(),
                                  isolation=FIXTURE_UNSANDBOXED, signer=signer)
    assert receipt.verdict == "PASS"
    # 哨兵被记录进 receipt 且向下游可见
    assert receipt.isolation == UNSANDBOXED_LABEL
    assert not is_release_eligible_isolation(receipt.isolation)
    # 并且被 controller bundle 一路带上来
    profile = {"required_external_oracle_ids": ["equal"],
               "external_oracles": [{"oracle_id": "equal", "version": "1",
                                      "request": {"expected": 4}}]}
    bundle = run_profile(mission_id="m", fencing_token=1, candidate_tree_hash="a" * 64,
                         profile=profile, candidate_argv=candidate_code("good"),
                         registry=registry(), isolation=FIXTURE_UNSANDBOXED, signer=signer)
    assert bundle.isolation == UNSANDBOXED_LABEL
    assert not is_release_eligible_isolation(bundle.isolation)


def test_broken_sandbox_profile_never_silently_downgrades_to_bare_run(tmp_path):
    """请求真沙箱但 profile 不可用 —— 必须 FAIL,绝不静默裸跑。"""
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})
    missing = run_external_oracle(spec, candidate_code("good"), registry(),
                                  isolation=str(tmp_path / "nope.sb"), signer=signer)
    assert missing.verdict == "FAIL" and missing.reason == "sandbox_profile_invalid"

    link = tmp_path / "link.sb"; real = tmp_path / "real.sb"
    real.write_text("(version 1)(allow default)\n"); link.symlink_to(real)
    symlinked = run_external_oracle(spec, candidate_code("good"), registry(),
                                    isolation=str(link), signer=signer)
    assert symlinked.verdict == "FAIL" and symlinked.reason == "sandbox_profile_invalid"


def test_real_sandbox_profile_yields_release_eligible_label(tmp_path):
    profile_file = tmp_path / "p.sb"; profile_file.write_text("(version 1)(allow default)\n")
    label = isolation_label(str(profile_file))
    assert is_release_eligible_isolation(label) and label.startswith("sandbox-exec:")
    # 不同 profile 内容 -> 不同标签,标签绑定的是内容不是路径
    other = tmp_path / "q.sb"; other.write_text("(version 1)(deny default)\n")
    assert isolation_label(str(other)) != label


@pytest.mark.skipif(not HAS_SANDBOX, reason="sandbox-exec unavailable")
def test_sandboxed_candidate_cannot_write_result_spool(tmp_path):
    """P0-6 实证:真沙箱下候选写不进 result spool。"""
    signer = identity(tmp_path)
    spool = tmp_path / "result-spool"; spool.mkdir()
    real_spool = os.path.realpath(spool)
    profile_file = tmp_path / "candidate.sb"
    profile_file.write_text('(version 1)\n(allow default)\n'
                            '(deny file-write* (subpath (param "SPOOL")))\n')
    code = ("import sys,json,pathlib\n"
            "try:\n"
            f"    pathlib.Path({str(spool / 'pwned.json')!r}).write_text('{{}}')\n"
            "except Exception:\n"
            "    pass\n"
            "q=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'nonce':q['nonce'],'result':4}))\n")
    spec = OracleSpec("equal", "1", {"expected": 4})
    receipt = run_external_oracle(spec, (sys.executable, "-c", code), registry(),
                                  isolation=str(profile_file), signer=signer,
                                  sandbox_params={"SPOOL": real_spool})
    assert receipt.verdict == "PASS"
    assert is_release_eligible_isolation(receipt.isolation)
    assert not (spool / "pwned.json").exists(), "候选写进了 result spool —— 隔离失效"


# ---------------------------------------------------------------- receipt signing

def test_oracle_receipt_is_signed_and_tamper_evident(tmp_path):
    signer = identity(tmp_path)
    spec = OracleSpec("equal", "1", {"expected": 4})
    receipt = run_external_oracle(spec, candidate_code("good"), registry(),
                                  isolation=FIXTURE_UNSANDBOXED, signer=signer)
    ok, reason = verify_oracle_receipt(receipt, public_key=signer.public_key)
    assert ok, reason

    fail_receipt = run_external_oracle(spec, candidate_code("exit0"), registry(),
                                       isolation=FIXTURE_UNSANDBOXED, signer=signer)
    # 把一份 FAIL receipt 的 verdict 改成 PASS,签名立刻失效
    forged = type(receipt)(**{**fail_receipt.core, "verdict": "PASS"},
                           sealed=fail_receipt.sealed)
    ok, reason = verify_oracle_receipt(forged, public_key=signer.public_key)
    assert not ok and reason == "attestation_core_mismatch"

    # 完全没有签名的 receipt 一律拒绝
    unsigned = type(receipt)(**receipt.core)
    assert verify_oracle_receipt(unsigned, public_key=signer.public_key) == (
        False, "oracle_receipt_unsigned")

    # 另一把钥匙签的 receipt 不认
    other = identity(tmp_path / "other")
    ok, _ = verify_oracle_receipt(receipt, public_key=other.public_key)
    assert not ok


def test_bundle_signature_covers_receipts(tmp_path):
    signer = identity(tmp_path)
    profile = {"required_external_oracle_ids": ["equal"],
               "external_oracles": [{"oracle_id": "equal", "version": "1",
                                      "request": {"expected": 4}}]}
    bundle = run_profile(mission_id="m", fencing_token=1, candidate_tree_hash="a" * 64,
                         profile=profile, candidate_argv=candidate_code("good"),
                         registry=registry(), isolation=FIXTURE_UNSANDBOXED, signer=signer)
    assert verify_test_result_bundle(bundle, public_key=signer.public_key)[0]
    swapped = type(bundle)(**{**bundle.core, "oracle_receipts": (), "bundle_hash": bundle.bundle_hash,
                              "sealed": bundle.sealed})
    ok, _ = verify_test_result_bundle(swapped, public_key=signer.public_key)
    assert not ok
