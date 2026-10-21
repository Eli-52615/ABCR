"""Round reports keep observations, interpretations and suggestions separate."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_AUDIT, verify_attestation
from abcr.control.contracts import ContractError, sha256, utc_now
from abcr.audit.evidence import AuditAttestation, audit_attestation_core


@dataclass(frozen=True)
class Suggestion:
    suggestion_id: str
    observation: str
    competing_explanation: str
    discriminating_experiment: str
    opposite_result_update: str
    evidence_refs: tuple[str, ...]
    origin: str = "machine"


@dataclass(frozen=True)
class RoundReport:
    round_id: str
    goal_id: str
    status: str
    observations: tuple[dict[str, Any], ...]
    interpretations: tuple[str, ...]
    limitations: tuple[str, ...]
    suggestions: tuple[Suggestion, ...]
    citable: bool
    audit_attestation: str | None
    generated_at: str
    report_hash: str
    # --- 认证边界的显式声明(B4 修复) ---------------------------------------
    # ``attested_evidence`` 是 auditor 签名**唯一**担保的表面:证据集哈希 + batch_id
    # + verdict。``citable`` 只对它成立,``citable_scope`` 把这句话写进结构里。
    attested_evidence: dict[str, Any] | None = None
    # observations/interpretations/limitations 是**人类叙事**,无签名；goal_id 与
    # compile envelope 的绑定另由 attested_evidence 认证。此字段恒为 False。
    narrative_authenticated: bool = False
    # 证据集是否被证明**确实属于本报告声称的 goal_id**。生产构造必须校验
    # auditor 随证明携带（或调用方显式提供）的 compile envelope，故成功返回恒为 True。
    goal_binding_verified: bool = False
    analysis_origin: str = "human_recorded"


def _envelope_committed_batch_id(envelope: dict[str, Any]) -> str:
    """复算 compile envelope 承诺的 batch_id。

    compile_goal 里 ``batch_id = "EXP-" + sha256(core)[:20]`` 且 ``envelope =
    dict(core, batch_id=batch_id)``,core 含 goal_id。故去掉 batch_id 后重算,若
    等于 envelope 自带的 batch_id,则该 batch_id 是对整个 core(含 goal_id)的抗
    碰撞承诺 —— 攻击者无法在不改 batch_id 的前提下把 goal_id 换成别的 goal。
    """
    core = {k: v for k, v in envelope.items() if k != "batch_id"}
    return "EXP-" + sha256(core)[:20]


def build_round_report(*, round_id: str, goal_id: str, audit: AuditAttestation,
                       observations: list[dict[str, Any]], interpretations: list[str],
                       limitations: list[str], suggestion_inputs: list[dict[str, Any]],
                       expected_batch_id: str,
                       auditor_public_key: Path | None = None,
                       compile_envelope: dict[str, Any] | None = None,
                       analysis_origin: str = "human_recorded",
                       generated_at: str | None = None) -> RoundReport:
    """构造轮次报告。

    核心不变式:
    1. **只有 auditor 签名的 attestation 才是可引用来源**。裸哈希自洽检查保留为
       廉价前置,但绝不单独充分 —— 对自己主张的哈希不是出处证明。
    2. **auditor 签「证据集 + goal/envelope 绑定」**(steps/scores/sidecars 哈希、
       batch_id、goal_id、compile envelope 摘要与 verdict)。
       observations/interpretations/limitations 与 goal_id 关联**都不在签名内**,
       是人类可变叙事。因此 ``citable`` 的担保范围被结构性收窄到 ``attested_evidence``
       一块,叙事**无法冒充成被认证内容**(B4:「用真证据给假叙事背书」)。
    3. **goal 绑定 fail-closed**:``compile_envelope`` 是必需的。auditor 签名 core
       同时携带 goal_id 与完整 envelope 摘要；报告端重算 envelope 的自证 batch_id、
       goal_id 与摘要，任一不一致都硬失败。不存在生产免绑定路径。
    """
    # 廉价前置:自洽性 + 身份。通过它**不代表**任何出处,只是提前挡掉明显噪声。
    audit_core = audit_attestation_core(audit)
    if sha256(audit_core) != audit.attestation_hash or audit.batch_id != expected_batch_id:
        raise ContractError("audit_attestation_invalid", "审计 attestation 身份或内容不匹配")
    # 信任根:验签。缺公钥是硬错误,不存在「无密钥则跳过验签」的分支。
    if auditor_public_key is None:
        raise ContractError("auditor_public_key_missing",
                            "校验审计证明必须提供 auditor 公钥(不存在免验签路径)")
    if not isinstance(audit.sealed, dict):
        raise ContractError("audit_attestation_unsigned",
                            "审计证明未签名 —— 裸哈希不是出处证明,拒绝引用")
    ok, reason = verify_attestation(audit.sealed, public_key=Path(auditor_public_key),
                                    domain=DOMAIN_AUDIT, expected_core=audit_core)
    if not ok:
        raise ContractError("audit_attestation_unverified",
                            f"审计证明验签失败: {reason}", {"reason": reason})
    audit_status = audit.verdict
    audit_attestation = audit.attestation_hash
    if audit_status not in {"PASS", "FAIL", "QUARANTINED"}:
        raise ContractError("bad_audit_status", "audit status 不合法")

    if compile_envelope is None:
        compile_envelope = audit.compile_envelope

    # --- goal 绑定(fail-closed):证据集必须确实属于本报告声称的 goal_id ---------
    # 无 auditor 私钥的攻击者可以拿一份**真**签名去挂**任意** goal_id + 捏造叙事。
    # auditor 签的是 batch_id;compile envelope 里 batch_id 又是对 goal_id 的抗碰撞
    # 承诺。故只要给出该信封,即可把「auditor 签了 batch」传递成「auditor 的证据集
    # 属于这个 goal」。任何不一致 = 主动攻击信号,一律硬失败。
    if (not isinstance(compile_envelope, dict)
            or "batch_id" not in compile_envelope or "goal_id" not in compile_envelope):
        raise ContractError("bad_compile_envelope",
                            "goal 绑定证明必须是含 batch_id 与 goal_id 的 compile envelope")
    if _envelope_committed_batch_id(compile_envelope) != compile_envelope["batch_id"]:
        raise ContractError("envelope_batch_id_unbound",
                            "compile envelope 的 batch_id 不是其内容的密码学承诺 —— "
                            "无法据此把证据集绑定到 goal")
    if compile_envelope["batch_id"] != audit.batch_id:
        raise ContractError("envelope_batch_mismatch",
                            "goal 绑定证明的 batch_id 与审计 attestation 不一致")
    if compile_envelope["goal_id"] != goal_id or audit.goal_id != goal_id:
        raise ContractError("goal_binding_mismatch",
                            "审计证据集不属于报告声称的 goal_id —— "
                            "拒绝用真证据给他 goal 的叙事背书")
    if audit.compile_envelope_sha256 != sha256(compile_envelope):
        raise ContractError("audit_envelope_mismatch",
                            "auditor 签名的 compile envelope 摘要与报告证明不一致")
    goal_binding_verified = True

    # citable 的担保范围 = 证据集(auditor 签名表面),**不含**叙事、**不隐含** goal 关联。
    citable = audit_status == "PASS" and bool(audit_attestation)
    status = "reported" if citable else "quarantined"
    if analysis_origin not in {"human_recorded", "machine_deterministic"}:
        raise ContractError("analysis_origin_invalid", "轮报告分析来源不合法")
    suggestions = []
    for raw in suggestion_inputs:
        required = {"observation", "competing_explanation", "discriminating_experiment",
                    "opposite_result_update", "evidence_refs"}
        if set(raw) != required or not all(raw.get(k) for k in required):
            raise ContractError("bad_suggestion", "机器建议必须包含证据、竞争解释和反向更新")
        sid = "SUG-" + sha256(raw)[:16]
        suggestions.append(Suggestion(sid, raw["observation"], raw["competing_explanation"],
                                      raw["discriminating_experiment"], raw["opposite_result_update"],
                                      tuple(raw["evidence_refs"]),
                                      "machine" if analysis_origin == "machine_deterministic"
                                      else "human_recorded"))

    # 唯一被 auditor 签名担保的表面 —— citable 只对它成立。
    attested_evidence = {"batch_id": audit.batch_id, "expected_keys_hash": audit.expected_keys_hash,
                         "steps_hash": audit.steps_hash, "scores_hash": audit.scores_hash,
                         "sidecars_hash": audit.sidecars_hash, "verdict": audit.verdict,
                         "defects": list(audit.defects), "created_at": audit.created_at,
                         "attestation_hash": audit.attestation_hash,
                         "goal_id": audit.goal_id,
                         "compile_envelope_sha256": audit.compile_envelope_sha256}
    # 人类叙事块 —— 结构上与被认证块分离,恒标 authenticated=False；其中 goal_id
    # 仅作关联索引，真实性由上面的 signed goal/envelope binding 独立保证。
    analysis = {"round_id": round_id, "goal_id": goal_id,
                "origin": analysis_origin, "observations": observations,
                "interpretations": interpretations, "limitations": limitations,
                "suggestions": [asdict(x) for x in suggestions],
                "authenticated": False,
                "human_reflections_included": False}
    report_generated_at = generated_at or utc_now()
    core = {"schema": "round-report-2", "status": status, "citable": citable,
            "citable_scope": "attested_evidence_only", "goal_binding_verified": goal_binding_verified,
            "attested_evidence": attested_evidence, "analysis": analysis,
            "generated_at": report_generated_at}
    return RoundReport(round_id=round_id, goal_id=goal_id, status=status,
                       observations=tuple(observations), interpretations=tuple(interpretations),
                       limitations=tuple(limitations), suggestions=tuple(suggestions), citable=citable,
                       audit_attestation=audit_attestation, generated_at=core["generated_at"],
                       report_hash=sha256(core), attested_evidence=attested_evidence,
                       narrative_authenticated=False, goal_binding_verified=goal_binding_verified,
                       analysis_origin=analysis_origin)


def next_goal_draft(report: RoundReport, suggestion_id: str) -> dict[str, Any]:
    """Create inert text for human+Claude; intentionally has no compile/dispatch handle."""
    suggestion = next((x for x in report.suggestions if x.suggestion_id == suggestion_id), None)
    if suggestion is None:
        raise ContractError("suggestion_unknown", "建议不存在")
    return {"draft_only": True, "requires_human_claude_review": True,
            "parent_round_id": report.round_id, "source_suggestion": asdict(suggestion),
            "auto_execute": False}
