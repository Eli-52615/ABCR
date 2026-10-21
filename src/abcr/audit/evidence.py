"""Exact evidence-set audit and independent citable attestation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_AUDIT, sign_attestation
from abcr.control.contracts import ContractError, sha256, utc_now
from abcr.explore.item_pool import DevBundleRef, verify_dev_bundle


@dataclass(frozen=True)
class AuditAttestation:
    """审计结论 + auditor 的**签名**证明。

    ``attestation_hash`` 只是对公开字段的自洽哈希 —— 任何人都能重算,因此它
    **不是出处证明**,只能当廉价前置检查。真正的信任根是 ``sealed``:一份
    ``DOMAIN_AUDIT`` 域分隔的 Ed25519 detached attestation。消费方必须验签。
    """
    batch_id: str
    expected_keys_hash: str
    steps_hash: str
    scores_hash: str
    sidecars_hash: str
    verdict: str
    defects: tuple[str, ...]
    created_at: str
    attestation_hash: str
    sealed: dict[str, Any] | None = None


def audit_attestation_core(audit: AuditAttestation) -> dict[str, Any]:
    """从公开字段独立重建签名 core。

    消费方用它重建 ``expected_core`` 后传给 ``verify_attestation`` —— 只验签名
    而不比对 core,等于允许攻击者拿一份合法签名去背书另一份审计结论。
    """
    return {"batch_id": audit.batch_id, "expected_keys_hash": audit.expected_keys_hash,
            "steps_hash": audit.steps_hash, "scores_hash": audit.scores_hash,
            "sidecars_hash": audit.sidecars_hash, "verdict": audit.verdict,
            "defects": list(audit.defects), "created_at": audit.created_at}


def audit_evidence(*, batch_id: str, item_ids: tuple[str, ...], seeds: tuple[int, ...],
                   conditions: tuple[str, ...], steps: list[dict[str, Any]],
                   scores: list[dict[str, Any]], sidecars: list[dict[str, Any]],
                   dev_bundle: DevBundleRef, trusted_dev_bundle_root: Path,
                   bundle_sealer_public_key: Path,
                   auditor_private_key: Path | None = None,
                   auditor_public_key: Path | None = None) -> AuditAttestation:
    """执行精确证据集审计并**签发签名证明**。

    auditor 密钥缺失是硬错误 —— 没有「无密钥则产出未签名证明」的分支,否则
    等于把门重新拆掉。
    """
    if auditor_private_key is None or auditor_public_key is None:
        raise ContractError("auditor_key_missing",
                            "签发审计证明必须提供 auditor 密钥对(不存在免签名路径)")
    verify_dev_bundle(dev_bundle, trusted_dev_bundle_root,
                      sealer_public_key=bundle_sealer_public_key)
    allowed_dev_ids = frozenset(dev_bundle.item_ids)
    expected = {(item, seed, condition) for item in item_ids for seed in seeds for condition in conditions}
    defects: list[str] = []
    if set(item_ids) != allowed_dev_ids: defects.append("item_set_not_exact_dev_bundle")
    def keys(rows): return [(x.get("item_id"), x.get("random_seed"), x.get("condition")) for x in rows]
    step_keys = keys(steps); score_keys = keys(scores); sidecar_keys = keys(sidecars)
    for name, observed in (("steps", step_keys), ("scores", score_keys), ("sidecars", sidecar_keys)):
        if len(observed) != len(set(observed)): defects.append(f"{name}_duplicate_key")
        if set(observed) != expected: defects.append(f"{name}_expected_set_mismatch")
    for step in steps:
        if not step.get("prompt_hash") or not step.get("output_text"):
            defects.append("step_raw_evidence_missing"); break
    core = {"batch_id": batch_id, "expected_keys_hash": sha256(sorted(expected)),
            "steps_hash": sha256(steps), "scores_hash": sha256(scores),
            "sidecars_hash": sha256(sidecars), "verdict": "PASS" if not defects else "FAIL",
            "defects": sorted(set(defects)), "created_at": utc_now()}
    sealed = sign_attestation(private_key=Path(auditor_private_key),
                              public_key=Path(auditor_public_key),
                              domain=DOMAIN_AUDIT, core=core)
    return AuditAttestation(batch_id=batch_id, expected_keys_hash=core["expected_keys_hash"],
                            steps_hash=core["steps_hash"], scores_hash=core["scores_hash"],
                            sidecars_hash=core["sidecars_hash"], verdict=core["verdict"],
                            defects=tuple(core["defects"]), created_at=core["created_at"],
                            attestation_hash=sha256(core), sealed=sealed)
