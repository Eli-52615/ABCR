"""Domain-separated detached Ed25519 attestations.

批准令牌(``ed25519.sign_token_v2``)携带一组冻结字段,适合单一用途。证明
(attestation)则相反:core 由调用方决定,因此**域分隔符是唯一阻止一份审计
证明被当作测试证明验证通过的东西**。域必须在签名载荷之内。

裸 ``sha256(core)`` 不是证明 —— 对自己主张的哈希任何人都能重算。本模块存在
的理由就是把那些自证哈希换成真签名。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json, sha256
from abcr.control.ed25519 import _b64, _run, _unb64, openssl_path, public_fingerprint

ATTESTATION_VERSION = "1.0"
ALGORITHM = "Ed25519"

# 冻结域名单。新增域必须登记在此 —— 未登记的域一律拒绝,避免调用方
# 临时编造域名而绕开域分隔。
DOMAIN_AUDIT = "abcr.audit.attestation.v1"
DOMAIN_TEST_RESULT = "abcr.test.result.v1"
DOMAIN_VERIFICATION = "abcr.verification.attestation.v1"
DOMAIN_ARTIFACT_FROZEN = "abcr.artifact.frozen.v1"
DOMAIN_SEAL_RECEIPT = "abcr.seal.receipt.v1"
DOMAIN_ORACLE_RECEIPT = "abcr.oracle.receipt.v1"
DOMAIN_DEV_BUNDLE = "abcr.dev_bundle.seal.v1"
DOMAIN_RESEARCH_MEMORY = "abcr.research_memory.seal.v1"
DOMAIN_APPROVAL_BUNDLE_VALIDATED = "abcr.approval_bundle.validated.v1"
DOMAIN_APPROVAL_DISPATCH_CLAIM = "abcr.approval.dispatch_claim.v1"

KNOWN_DOMAINS = frozenset({
    DOMAIN_AUDIT, DOMAIN_TEST_RESULT, DOMAIN_VERIFICATION,
    DOMAIN_ARTIFACT_FROZEN, DOMAIN_SEAL_RECEIPT, DOMAIN_ORACLE_RECEIPT,
    DOMAIN_DEV_BUNDLE,
    DOMAIN_RESEARCH_MEMORY,
    DOMAIN_APPROVAL_BUNDLE_VALIDATED,
    DOMAIN_APPROVAL_DISPATCH_CLAIM,
})

_SEALED_FIELDS = frozenset({
    "attestation_version", "alg", "key_id", "domain", "core_sha256",
    "issued_at", "signature_b64",
})

MAX_CLOCK_SKEW = timedelta(seconds=30)


def _require_domain(domain: str) -> None:
    if not isinstance(domain, str) or domain not in KNOWN_DOMAINS:
        raise ContractError("attestation_domain_unknown", f"未登记的证明域: {domain!r}")


def _payload(sealed: dict[str, Any]) -> bytes:
    """签名载荷 = 除 signature_b64 外的全部字段。

    字段集合本身进入签名,因此增删字段都会导致验签失败。
    """
    return canonical_json({k: v for k, v in sealed.items() if k != "signature_b64"})


def sign_attestation(*, private_key: Path, public_key: Path, domain: str,
                     core: dict[str, Any], issued_at: datetime | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    """对 core 产出一份域分隔的可离线验证证明。

    private key 只在签名者进程内使用,不会被返回或记录。
    """
    _require_domain(domain)
    if not isinstance(core, dict) or not core:
        raise ContractError("attestation_core_invalid", "attestation core 必须是非空 dict")
    private_info = Path(private_key).lstat()
    import stat as _stat
    if (Path(private_key).is_symlink() or not _stat.S_ISREG(private_info.st_mode)
            or private_info.st_nlink != 1 or private_info.st_mode & 0o077):
        raise ContractError("private_key_permissions", "private key 必须是 0600 单链接 regular file")
    now = now or datetime.now(timezone.utc)
    issued_at = issued_at or now
    if issued_at.tzinfo is None or issued_at > now + MAX_CLOCK_SKEW:
        raise ContractError("issued_at_invalid", "issued_at 不合法")
    sealed = {
        "attestation_version": ATTESTATION_VERSION,
        "alg": ALGORITHM,
        "key_id": public_fingerprint(public_key),
        "domain": domain,
        "core_sha256": sha256(core),
        "issued_at": issued_at.isoformat(),
    }
    import tempfile
    with tempfile.TemporaryDirectory(prefix="abcr-attest-") as tmp:
        msg = Path(tmp) / "message"; sig = Path(tmp) / "signature"
        msg.write_bytes(_payload(sealed))
        proc = _run([openssl_path(), "pkeyutl", "-sign", "-inkey", str(private_key),
                     "-rawin", "-in", str(msg), "-out", str(sig)])
        if proc.returncode != 0:
            raise ContractError("attestation_sign_failed", "Ed25519 证明签名失败")
        sealed["signature_b64"] = _b64(sig.read_bytes())
    return sealed


def verify_attestation(sealed: dict[str, Any], *, public_key: Path, domain: str,
                       expected_core: dict[str, Any],
                       now: datetime | None = None) -> tuple[bool, str]:
    """验证证明。返回 (ok, reason);任何异常路径一律 fail-closed。

    调用方必须传入自己独立重建的 expected_core —— 只验签名而不比对 core,
    等于允许攻击者拿一份合法签名去背书另一份内容。
    """
    try:
        _require_domain(domain)
    except ContractError:
        return False, "attestation_domain_unknown"
    if not isinstance(sealed, dict) or set(sealed) != _SEALED_FIELDS:
        return False, "attestation_fields_mismatch"
    if (sealed["attestation_version"] != ATTESTATION_VERSION
            or sealed["alg"] != ALGORITHM):
        return False, "attestation_protocol_mismatch"
    # 域分隔:签名有效但域不符,依然拒绝。
    if sealed["domain"] != domain:
        return False, "attestation_domain_mismatch"
    if not all(isinstance(sealed[k], str) and sealed[k] for k in _SEALED_FIELDS):
        return False, "attestation_value_type"
    if not isinstance(expected_core, dict) or not expected_core:
        return False, "expected_core_invalid"
    if sealed["core_sha256"] != sha256(expected_core):
        return False, "attestation_core_mismatch"
    try:
        fingerprint = public_fingerprint(public_key)
    except (ContractError, OSError):
        return False, "public_key_invalid"
    if sealed["key_id"] != fingerprint:
        return False, "key_mismatch"
    try:
        issued = datetime.fromisoformat(sealed["issued_at"])
    except (TypeError, ValueError):
        return False, "bad_issued_at"
    if issued.tzinfo is None:
        return False, "bad_issued_at"
    if issued > (now or datetime.now(timezone.utc)) + MAX_CLOCK_SKEW:
        return False, "future_issued"
    try:
        signature = _unb64(sealed["signature_b64"])
    except ContractError:
        return False, "bad_signature_encoding"
    import tempfile
    with tempfile.TemporaryDirectory(prefix="abcr-attest-verify-") as tmp:
        msg = Path(tmp) / "message"; sig = Path(tmp) / "signature"
        msg.write_bytes(_payload(sealed)); sig.write_bytes(signature)
        proc = _run([openssl_path(), "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key),
                     "-rawin", "-in", str(msg), "-sigfile", str(sig)])
    return (True, "ok") if proc.returncode == 0 else (False, "bad_signature")
