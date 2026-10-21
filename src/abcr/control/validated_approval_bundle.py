"""Validator-signed finite approval bundle across Operator → broker → Human domains.

Scientific validation belongs to a fixed non-root validator/auditor process.  The
root broker never invokes git or another subprocess and never makes an approval
judgment: it only verifies the validator signature in-process, checks the finite wire
shape, and hands the canonical bytes to its fixed-source sealing machinery.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from abcr.control.attestation import (ALGORITHM, ATTESTATION_VERSION,
                                      DOMAIN_APPROVAL_BUNDLE_VALIDATED,
                                      sign_attestation, verify_attestation)
from abcr.control.contracts import (ContractError, canonical_json, require_id,
                                    require_sha, sha256, strict_object)
from abcr.control.ed25519 import ApprovalRequestBundle, VerifiedAnchor


SCHEMA = "abcr.validator-signed-approval-bundle.v1"
BROKER_OPERATION = "seal_approval_bundle"
CORE_FIELDS = {
    "schema", "request_id", "batch_id", "envelope_sha256",
    "goal_anchor_entry_hash", "goal_anchor_receipt_id", "research_commit",
    "goal_sha256", "deployment_id", "protocol_ref",
}
SEALED_FIELDS = {
    "attestation_version", "alg", "key_id", "domain", "core_sha256",
    "issued_at", "signature_b64",
}


@dataclass(frozen=True)
class BrokerVerifiedApprovalCandidate:
    """Pure result the broker binds to its fixed-source seal/receipt operation."""
    validated: VerifiedAnchor
    canonical_bytes: bytes
    document_sha256: str
    validated_core_sha256: str


def _core(verified: VerifiedAnchor) -> dict[str, Any]:
    return {"schema": SCHEMA, **verified.__dict__}


def _validate_core(value: Any) -> tuple[dict[str, Any], VerifiedAnchor]:
    core = strict_object(value, required=CORE_FIELDS)
    if core["schema"] != SCHEMA:
        raise ContractError("validated_approval_schema", "validated approval schema 不匹配")
    for field in ("request_id", "batch_id", "goal_anchor_receipt_id"):
        require_id(core[field], field)
    for field in ("deployment_id", "protocol_ref"):
        if (not isinstance(core[field], str) or not core[field]
                or any(ch in core[field] for ch in "\r\n\x00")):
            raise ContractError("validated_approval_core", f"{field} 非法")
    for field in ("envelope_sha256", "goal_anchor_entry_hash", "goal_sha256"):
        require_sha(core[field], field)
    commit = core["research_commit"]
    if (not isinstance(commit, str) or len(commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in commit)):
        raise ContractError("validated_approval_core", "research_commit 非法")
    values = {key: core[key] for key in VerifiedAnchor.__dataclass_fields__}
    return core, VerifiedAnchor(**values)


def validator_validate_and_sign(
        bundle: ApprovalRequestBundle, *, research_repo: Path, anchor_ledger: Path,
        anchor_ledger_owner_uid: int, anchor_seal_path: Path,
        anchor_sealer_public_key: Path, anchor_seal_owner_uid: int,
        validator_private_key: Path, validator_public_key: Path) -> dict[str, Any]:
    """Non-root validator side; this is the only function allowed to run git checks."""
    verified = bundle.validate(
        research_repo=research_repo, anchor_ledger=anchor_ledger,
        anchor_ledger_owner_uid=anchor_ledger_owner_uid,
        anchor_seal_path=anchor_seal_path,
        anchor_sealer_public_key=anchor_sealer_public_key,
        anchor_seal_owner_uid=anchor_seal_owner_uid)
    core = _core(verified)
    sealed = sign_attestation(
        private_key=Path(validator_private_key), public_key=Path(validator_public_key),
        domain=DOMAIN_APPROVAL_BUNDLE_VALIDATED, core=core)
    return {"validated_core": core, "validator_attestation": sealed}


def _outer(document: Any) -> tuple[dict[str, Any], dict[str, Any], VerifiedAnchor]:
    outer = strict_object(document, required={"validated_core", "validator_attestation"})
    core, verified = _validate_core(outer["validated_core"])
    if not isinstance(outer["validator_attestation"], dict):
        raise ContractError("validator_approval_unverified", "validator attestation 非法")
    return outer, core, verified


def verify_validator_document(document: Any, *, validator_public_key: Path) -> VerifiedAnchor:
    """Human side validator verification; no research repository or ledger is mounted."""
    outer, core, verified = _outer(document)
    ok, reason = verify_attestation(
        outer["validator_attestation"], public_key=Path(validator_public_key),
        domain=DOMAIN_APPROVAL_BUNDLE_VALIDATED, expected_core=core)
    if not ok:
        raise ContractError("validator_approval_unverified", "validator approval bundle 验签失败",
                            {"reason": reason})
    return verified


def broker_verify_candidate(document: Any, *, validator_public_key_pem: bytes,
                            now: datetime | None = None) -> BrokerVerifiedApprovalCandidate:
    """Root broker's pure mechanical gate: no subprocess and no caller path input.

    ``validator_public_key_pem`` must be read by the broker from its fixed root-owned
    config before this call; it is never accepted from the request document.
    """
    outer, core, verified = _outer(document)
    sealed = outer["validator_attestation"]
    if set(sealed) != SEALED_FIELDS:
        raise ContractError("validator_approval_unverified", "validator attestation 字段不精确")
    if (sealed.get("attestation_version") != ATTESTATION_VERSION
            or sealed.get("alg") != ALGORITHM
            or sealed.get("domain") != DOMAIN_APPROVAL_BUNDLE_VALIDATED
            or sealed.get("core_sha256") != sha256(core)):
        raise ContractError("validator_approval_unverified", "validator attestation 协议不匹配")
    if not isinstance(validator_public_key_pem, bytes) or not validator_public_key_pem:
        raise ContractError("validator_public_key_invalid", "validator public key bytes 缺失")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = serialization.load_pem_public_key(validator_public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError("not Ed25519")
        der = key.public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)
    except ImportError as exc:
        raise ContractError("inprocess_ed25519_unavailable",
                            "broker runtime 缺少冻结 cryptography Ed25519 verifier") from exc
    except (TypeError, ValueError) as exc:
        raise ContractError("validator_public_key_invalid", "validator public key 无法解析") from exc
    if sealed.get("key_id") != sha256(der):
        raise ContractError("validator_approval_unverified", "validator key_id 不匹配")
    try:
        issued = datetime.fromisoformat(sealed["issued_at"])
        if issued.tzinfo is None or issued > (now or datetime.now(timezone.utc)) + timedelta(seconds=30):
            raise ValueError("bad issued_at")
        text = sealed["signature_b64"]
        signature = base64.b64decode(text, validate=True)
        if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != text:
            raise ValueError("non-canonical signature")
        payload = canonical_json({key: value for key, value in sealed.items()
                                  if key != "signature_b64"})
        key.verify(signature, payload)
    except InvalidSignature as exc:
        raise ContractError("validator_approval_unverified", "validator signature 不匹配") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("validator_approval_unverified", "validator attestation 编码非法") from exc
    canonical = canonical_json(outer) + b"\n"
    return BrokerVerifiedApprovalCandidate(
        verified, canonical, sha256(canonical), sha256(core))


def verify_finite_request(bundle: ApprovalRequestBundle, verified: VerifiedAnchor) -> None:
    """Bind the unsealed display payload to the validator-signed finite core."""
    try:
        goal_bytes = base64.b64decode(bundle.goal_bytes_b64, validate=True)
    except Exception as exc:
        raise ContractError("validated_approval_request_mismatch", "goal bytes base64 非法") from exc
    if base64.b64encode(goal_bytes).decode("ascii") != bundle.goal_bytes_b64:
        raise ContractError("validated_approval_request_mismatch", "goal bytes base64 非 canonical")
    receipt = bundle.artifact_frozen_receipt
    envelope = bundle.envelope
    if (not isinstance(receipt, dict) or not isinstance(envelope, dict)
            or bundle.request_id != verified.request_id
            or sha256(envelope) != verified.envelope_sha256
            or bundle.envelope_sha256 != verified.envelope_sha256
            or sha256(goal_bytes) != verified.goal_sha256
            or bundle.goal_sha256 != verified.goal_sha256
            or bundle.research_commit != verified.research_commit
            or envelope.get("batch_id") != verified.batch_id
            or envelope.get("goal_hash") != verified.goal_sha256
            or envelope.get("research_commit") != verified.research_commit
            or envelope.get("goal_receipt_id") != verified.goal_anchor_receipt_id
            or receipt.get("receipt_id") != verified.goal_anchor_receipt_id
            or receipt.get("goal_hash") != verified.goal_sha256
            or receipt.get("research_commit") != verified.research_commit):
        raise ContractError("validated_approval_request_mismatch",
                            "finite human 请求与 validator-signed core 不一致")
