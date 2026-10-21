"""Small deterministic facade used by fixture journeys and the operator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, canonical_json
from abcr.control.store import ControlStore
from abcr.explore.compiler import ArtifactFrozenReceipt, compile_goal, freeze_goal, prepare_goal_anchor
from abcr.explore.goal import Goal, validate_goal
from abcr.explore.item_pool import DevBundleRef
from abcr.explore.personas import PersonaRegistry


@dataclass
class ScientificWorkflow:
    store: ControlStore
    personas: PersonaRegistry
    trusted_dev_bundle_root: Path
    # 无默认值是刻意的:artifact_frozen 收据的验签公钥若可省略,这条链路
    # 就退回到「收据无人验证」的原始缺陷。缺公钥必须在构造期就暴露。
    receipt_public_key: Path
    # itempool 封印公钥。dev bundle 的信任根 —— 缺它则 compile 无法验证
    # bundle 不是手搓的 holdout 冒充品。
    bundle_sealer_public_key: Path

    def validate_proposal(self, proposal_id: str, raw: bytes) -> Goal:
        report = validate_goal(raw)
        if not report.ok or report.goal is None:
            self.store.set_proposal_state(proposal_id, "imported", "invalid")
            raise ContractError("goal_invalid", "目标书未通过确定性校验", {"defects": report.defects})
        if not self.store.set_proposal_state(proposal_id, "imported", "validated",
                                             report.goal.as_dict()):
            raise ContractError("proposal_state", "提案不在 imported 状态")
        return report.goal

    def confirm_and_compile(self, proposal_id: str, goal: Goal, *, actor_id: str, research_commit: str,
                            goal_path: str, receipt: ArtifactFrozenReceipt,
                            bundle: DevBundleRef, protocol_ref: str,
                            deployment_id: str) -> dict[str, Any]:
        proposal = self.store.get_proposal(proposal_id)
        if (proposal is None or proposal["state"] != "validated"
                or proposal["normalized_json"] != canonical_json(goal.as_dict()).decode()):
            raise ContractError("proposal_goal_mismatch", "确认目标与已校验提案不是同一内容")
        if not self.store.set_proposal_state(proposal_id, "validated", "human_confirmed"):
            raise ContractError("proposal_not_validated", "只有 validated 提案可确认")
        candidate = prepare_goal_anchor(goal, research_commit=research_commit,
                                        relative_path=goal_path, confirmed_by=actor_id,
                                        deployment_id=deployment_id,
                                        protocol_ref=protocol_ref)
        anchor = freeze_goal(candidate, receipt, receipt_public_key=self.receipt_public_key)
        compiled = compile_goal(goal, anchor, bundle, self.personas, protocol_ref=protocol_ref,
                                trusted_dev_bundle_root=self.trusted_dev_bundle_root,
                                bundle_sealer_public_key=self.bundle_sealer_public_key,
                                deployment_id=deployment_id)
        self.store.set_proposal_state(proposal_id, "human_confirmed", "compiled")
        return compiled.envelope
