"""对抗测试:域分隔签名证明。

这些用例的存在理由是 P9 审查的 P0-2/P0-3 —— 原实现用裸 sha256 自证哈希
冒充凭证,手工构造即可伪造 PASS。
"""
from __future__ import annotations

import pytest

from abcr.control.attestation import (
    DOMAIN_AUDIT, DOMAIN_TEST_RESULT, DOMAIN_VERIFICATION,
    sign_attestation, verify_attestation,
)
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair


@pytest.fixture()
def keys(tmp_path):
    private = tmp_path / "k.pem"; public = tmp_path / "k.pub"
    generate_keypair(private, public)
    return private, public


CORE = {"verdict": "PASS", "batch_id": "B1", "evidence": ["e1"]}


def test_roundtrip(keys):
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_AUDIT, core=CORE)
    assert verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                              expected_core=CORE) == (True, "ok")


def test_forged_bare_hash_is_rejected(keys):
    """P0-2 的原始攻击:手工造一个自洽的 dict 冒充证明。"""
    _, public = keys
    forged = {"attestation_version": "1.0", "alg": "Ed25519", "key_id": "0" * 64,
              "domain": DOMAIN_AUDIT, "core_sha256": sha256(CORE),
              "issued_at": "2026-07-20T00:00:00+00:00", "signature_b64": "A" * 86 + "=="}
    ok, reason = verify_attestation(forged, public_key=public, domain=DOMAIN_AUDIT,
                                    expected_core=CORE)
    assert not ok and reason == "key_mismatch"


def test_domain_confusion_rejected(keys):
    """一份测试结果证明绝不能作为审计证明验证通过。"""
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_TEST_RESULT, core=CORE)
    # 签名本身完全有效,只是域不对。
    assert verify_attestation(sealed, public_key=public, domain=DOMAIN_TEST_RESULT,
                              expected_core=CORE) == (True, "ok")
    ok, reason = verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                                    expected_core=CORE)
    assert not ok and reason == "attestation_domain_mismatch"


def test_domain_relabel_breaks_signature(keys):
    """把域字段改掉重新贴标签 —— 域在签名载荷内,必然验签失败。"""
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_TEST_RESULT, core=CORE)
    sealed["domain"] = DOMAIN_AUDIT
    ok, reason = verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                                    expected_core=CORE)
    assert not ok and reason == "bad_signature"


def test_core_swap_rejected(keys):
    """签名有效,但拿去背书另一份 core。"""
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_AUDIT, core=CORE)
    ok, reason = verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                                    expected_core={**CORE, "verdict": "FAIL"})
    assert not ok and reason == "attestation_core_mismatch"


def test_field_addition_and_truncation_rejected(keys):
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_AUDIT, core=CORE)
    extra = {**sealed, "extra": "x"}
    assert verify_attestation(extra, public_key=public, domain=DOMAIN_AUDIT,
                              expected_core=CORE) == (False, "attestation_fields_mismatch")
    truncated = {k: v for k, v in sealed.items() if k != "issued_at"}
    assert verify_attestation(truncated, public_key=public, domain=DOMAIN_AUDIT,
                              expected_core=CORE) == (False, "attestation_fields_mismatch")


def test_wrong_key_rejected(keys, tmp_path):
    private, public = keys
    other_private = tmp_path / "o.pem"; other_public = tmp_path / "o.pub"
    generate_keypair(other_private, other_public)
    sealed = sign_attestation(private_key=other_private, public_key=other_public,
                              domain=DOMAIN_AUDIT, core=CORE)
    ok, reason = verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                                    expected_core=CORE)
    assert not ok and reason == "key_mismatch"


def test_unknown_domain_refused_both_ways(keys):
    private, public = keys
    with pytest.raises(ContractError):
        sign_attestation(private_key=private, public_key=public,
                         domain="abcr.made.up.v1", core=CORE)
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_VERIFICATION, core=CORE)
    assert verify_attestation(sealed, public_key=public, domain="abcr.made.up.v1",
                              expected_core=CORE) == (False, "attestation_domain_unknown")


def test_noncanonical_signature_encoding_rejected(keys):
    """尾比特非规范:64 字节 base64 的第 86 位有 4 个空闲比特,
    16 个不同字符解码结果相同。必须只接受规范形式。"""
    import base64, string
    private, public = keys
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_AUDIT, core=CORE)
    canonical = sealed["signature_b64"]
    raw = base64.b64decode(canonical, validate=True)
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
    variant = next(c for c in alphabet
                   if c != canonical[85]
                   and base64.b64decode(canonical[:85] + c + "==", validate=True) == raw)
    sealed["signature_b64"] = canonical[:85] + variant + "=="
    assert verify_attestation(sealed, public_key=public, domain=DOMAIN_AUDIT,
                              expected_core=CORE) == (False, "bad_signature_encoding")


def test_empty_core_refused(keys):
    private, public = keys
    with pytest.raises(ContractError):
        sign_attestation(private_key=private, public_key=public, domain=DOMAIN_AUDIT, core={})
