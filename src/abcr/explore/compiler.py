"""Compile a confirmed human goal and a dev-only bundle into an immutable draft."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_ARTIFACT_FROZEN, sign_attestation, verify_attestation
from abcr.control.contracts import ContractError, canonical_json, require_sha, sha256, utc_now
from abcr.explore.goal import Goal
from abcr.explore.item_pool import DevBundleRef, verify_dev_bundle
from abcr.explore.personas import PersonaRegistry


@dataclass(frozen=True)
class GoalAnchorCandidate:
    goal_id: str
    goal_hash: str
    research_commit: str
    relative_path: str
    confirmed_by: str


@dataclass(frozen=True)
class ArtifactFrozenReceipt:
    """artifact_frozen 收据 + 签发方的**签名**证明。

    无签名的 dataclass 一行代码就能伪造(规格判据 13 的「伪造收据」)。真正的
    信任根是 ``sealed``:一份 ``DOMAIN_ARTIFACT_FROZEN`` 域分隔的 attestation。
    """
    receipt_id: str
    goal_hash: str
    research_commit: str
    recorded_at: str
    sealed: dict[str, Any] | None = None


def frozen_receipt_core(receipt: ArtifactFrozenReceipt) -> dict[str, Any]:
    """从公开字段独立重建签名 core,供签发与验证两侧共用。"""
    return {"receipt_id": receipt.receipt_id, "goal_hash": receipt.goal_hash,
            "research_commit": receipt.research_commit, "recorded_at": receipt.recorded_at}


def sign_frozen_receipt(receipt: ArtifactFrozenReceipt, *, private_key: Path,
                        public_key: Path) -> ArtifactFrozenReceipt:
    """给 artifact_frozen 收据盖上域分隔签名。"""
    sealed = sign_attestation(private_key=Path(private_key), public_key=Path(public_key),
                              domain=DOMAIN_ARTIFACT_FROZEN,
                              core=frozen_receipt_core(receipt))
    return ArtifactFrozenReceipt(receipt.receipt_id, receipt.goal_hash,
                                 receipt.research_commit, receipt.recorded_at, sealed)


@dataclass(frozen=True)
class GoalAnchor:
    candidate: GoalAnchorCandidate
    receipt: ArtifactFrozenReceipt


@dataclass(frozen=True)
class CompileResult:
    batch_id: str
    envelope: dict[str, Any]
    envelope_hash: str


def prepare_goal_anchor(goal: Goal, *, research_commit: str, relative_path: str,
                        confirmed_by: str) -> GoalAnchorCandidate:
    require_sha(research_commit, "research_commit")
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ContractError("bad_goal_path", "goal path 必须是规范相对路径")
    return GoalAnchorCandidate(goal.goal_id, goal.goal_hash, research_commit,
                               relative_path, confirmed_by)


def freeze_goal(candidate: GoalAnchorCandidate, receipt: ArtifactFrozenReceipt, *,
                receipt_public_key: Path | None = None) -> GoalAnchor:
    """消费 artifact_frozen 收据。**必须验签** —— 无签名收据一律拒绝。"""
    if (receipt.goal_hash, receipt.research_commit) != (candidate.goal_hash, candidate.research_commit):
        raise ContractError("freeze_receipt_mismatch", "artifact_frozen receipt 与候选目标不一致")
    if receipt_public_key is None:
        raise ContractError("freeze_receipt_key_missing",
                            "校验 artifact_frozen 收据必须提供公钥(不存在免验签路径)")
    if not isinstance(receipt.sealed, dict):
        raise ContractError("freeze_receipt_unsigned", "artifact_frozen 收据未签名,拒绝接受")
    ok, reason = verify_attestation(receipt.sealed, public_key=Path(receipt_public_key),
                                    domain=DOMAIN_ARTIFACT_FROZEN,
                                    expected_core=frozen_receipt_core(receipt))
    if not ok:
        raise ContractError("freeze_receipt_unverified",
                            f"artifact_frozen 收据验签失败: {reason}", {"reason": reason})
    return GoalAnchor(candidate, receipt)


def compile_goal(goal: Goal, anchor: GoalAnchor, bundle: DevBundleRef,
                 personas: PersonaRegistry, *, protocol_ref: str,
                 trusted_dev_bundle_root: Path, bundle_sealer_public_key: Path,
                 deployment_id: str = "fixture") -> CompileResult:
    if goal.goal_hash != anchor.candidate.goal_hash:
        raise ContractError("goal_anchor_mismatch", "目标字节与冻结锚不一致")
    if goal.split != "dev":
        raise ContractError("non_dev_compile", "只允许编译 dev 目标")
    verify_dev_bundle(bundle, trusted_dev_bundle_root,
                      sealer_public_key=bundle_sealer_public_key)
    if len(bundle.item_ids) != goal.item_count:
        raise ContractError("bundle_item_count_mismatch", "DevBundle 题量与目标书不一致")
    persona_refs = []
    for ref in goal.personas:
        artifact = personas.get(ref)
        persona_refs.append({"ref": ref, "sha256": artifact.digest})
    core = {
        "schema_version": "exploration-1", "goal_id": goal.goal_id,
        "goal_hash": goal.goal_hash, "goal_receipt_id": anchor.receipt.receipt_id,
        "research_commit": anchor.candidate.research_commit, "template_id": goal.template_id,
        "protocol_ref": protocol_ref, "deployment_id": deployment_id,
        "split": "dev", "dev_bundle_id": bundle.bundle_id,
        "dev_bundle_manifest_hash": bundle.manifest_hash,
        "item_ids": list(bundle.item_ids), "seeds": list(goal.seeds),
        "personas": persona_refs, "arms": list(goal.arms), "metrics": list(goal.metrics),
        "predictions": [p.__dict__ for p in goal.predictions], "falsifier": goal.falsifier,
        "max_cost_usd": goal.max_cost_usd, "created_at": utc_now(),
    }
    batch_id = "EXP-" + sha256(core)[:20]
    envelope = dict(core, batch_id=batch_id)
    return CompileResult(batch_id, envelope, sha256(canonical_json(envelope)))
