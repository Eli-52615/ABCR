"""P0-2 回归:auditor attestation 必须验签才能成为可引用来源。

原缺陷:``build_round_report`` 的接受判据是 ``sha256(audit_core) ==
audit.attestation_hash`` —— 对公开字段做**自洽性**校验,无密钥、无 MAC、无签名。
对自己主张的哈希不是出处证明,手工构造一份全 "0"*64 的 PASS attestation 就能
拿到 ``citable: True``。

本文件把那次实测攻击原样固化为回归,并补齐同类对抗面。
"""
from __future__ import annotations

import pytest

from abcr.audit.evidence import AuditAttestation, audit_attestation_core, audit_evidence
from abcr.control.attestation import (
    DOMAIN_ARTIFACT_FROZEN,
    DOMAIN_AUDIT,
    sign_attestation,
)
from abcr.control.contracts import ContractError, sha256
from abcr.control.ed25519 import generate_keypair
from abcr.explore.compiler import (
    ArtifactFrozenReceipt,
    frozen_receipt_core,
    prepare_goal_anchor,
    sign_frozen_receipt,
)
from abcr.explore.item_pool import SelectionRequest, build_dev_bundle
from abcr.explore.rounds import build_round_report, next_goal_draft
from tests.explore.test_itempool_workflow import (itempool_keys, registry, sealed_bundle,
                                                  sources, valid_goal)
from abcr.explore.goal import validate_goal

FAKE = "0" * 64
BATCH = "EXP-victim"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def auditor_keys(tmp_path):
    """auditor 密钥对。密钥路径可注入,但**没有**「无密钥则跳过验签」的分支。"""
    private, public = tmp_path / "auditor.key", tmp_path / "auditor.pub"
    generate_keypair(private, public)
    return private, public


@pytest.fixture
def other_keys(tmp_path):
    private, public = tmp_path / "other.key", tmp_path / "other.pub"
    generate_keypair(private, public)
    return private, public


@pytest.fixture
def genuine_audit(tmp_path, auditor_keys):
    """走真实 auditor 路径产出的签名 attestation。"""
    private, public = auditor_keys
    dataset, split = sources(tmp_path)
    sealer = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("s", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=sealer)
    item_id = bundle.item_ids[0]
    keys = [(item_id, 1, "vanilla"), (item_id, 1, "persona")]
    steps = [{"item_id": i, "random_seed": s, "condition": c,
              "prompt_hash": "p", "output_text": "x"} for i, s, c in keys]
    rows = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    return audit_evidence(batch_id=BATCH, item_ids=(item_id,), seeds=(1,),
                          conditions=("vanilla", "persona"), steps=steps, scores=rows,
                          sidecars=rows, dev_bundle=bundle,
                          trusted_dev_bundle_root=tmp_path / "bundles",
                          bundle_sealer_public_key=sealer[1],
                          auditor_private_key=private, auditor_public_key=public)


def report(audit, public_key, **kw):
    kw.setdefault("observations", [{"k": 1}])
    kw.setdefault("interpretations", ["i"])
    kw.setdefault("limitations", ["l"])
    kw.setdefault("suggestion_inputs", [])
    return build_round_report(round_id="R1", goal_id="G1", audit=audit,
                              expected_batch_id=audit.batch_id,
                              auditor_public_key=public_key, **kw)


def forged(**overrides):
    """规格判据里那份伪造 attestation:PASS、全零哈希、无 auditor、无证据。"""
    core = {"batch_id": BATCH, "expected_keys_hash": FAKE, "steps_hash": FAKE,
            "scores_hash": FAKE, "sidecars_hash": FAKE, "verdict": "PASS",
            "defects": [], "created_at": "2026-07-20T00:00:00Z"}
    core.update(overrides)
    return AuditAttestation(batch_id=core["batch_id"], expected_keys_hash=core["expected_keys_hash"],
                            steps_hash=core["steps_hash"], scores_hash=core["scores_hash"],
                            sidecars_hash=core["sidecars_hash"], verdict=core["verdict"],
                            defects=tuple(core["defects"]), created_at=core["created_at"],
                            attestation_hash=sha256(core))


# --------------------------------------------------------------------------
# 验收核心:原样执行那次已验证的攻击
# --------------------------------------------------------------------------

def test_forged_attestation_is_no_longer_citable(auditor_keys):
    """实测攻击原样重放:曾经拿到 status=reported / CITABLE=True。现在必须失败。"""
    _, public = auditor_keys
    attack = forged()
    # 自洽哈希依然成立 —— 这正是原判据的全部内容,也正是它不够的证明。
    assert sha256(audit_attestation_core(attack)) == attack.attestation_hash
    with pytest.raises(ContractError) as excinfo:
        report(attack, public)
    assert excinfo.value.code == "audit_attestation_unsigned"


def test_forged_attestation_with_bolted_on_signature_field(auditor_keys, other_keys):
    """攻击者自带一把密钥给伪造 core 签名 —— 公钥不匹配,依然拒绝。"""
    _, victim_public = auditor_keys
    attacker_private, attacker_public = other_keys
    attack = forged()
    sealed = sign_attestation(private_key=attacker_private, public_key=attacker_public,
                              domain=DOMAIN_AUDIT, core=audit_attestation_core(attack))
    attack = AuditAttestation(**{**attack.__dict__, "sealed": sealed})
    with pytest.raises(ContractError) as excinfo:
        report(attack, victim_public)
    assert excinfo.value.code == "audit_attestation_unverified"


# --------------------------------------------------------------------------
# 正向路径
# --------------------------------------------------------------------------

def test_genuine_signed_attestation_is_citable(genuine_audit, auditor_keys):
    _, public = auditor_keys
    assert genuine_audit.verdict == "PASS"
    result = report(genuine_audit, public)
    assert result.citable is True
    assert result.status == "reported"
    assert result.audit_attestation == genuine_audit.attestation_hash


def test_genuine_fail_verdict_is_quarantined(tmp_path, auditor_keys):
    """既有断言不削弱:FAIL 判决签名有效也不可引用。"""
    private, public = auditor_keys
    dataset, split = sources(tmp_path)
    sealer = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("s", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=sealer)
    item_id = bundle.item_ids[0]
    keys = [(item_id, 1, "vanilla"), (item_id, 1, "persona")]
    steps = [{"item_id": i, "random_seed": s, "condition": c,
              "prompt_hash": "p", "output_text": "x"} for i, s, c in keys]
    rows = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    audit = audit_evidence(batch_id=BATCH, item_ids=(item_id,), seeds=(1,),
                           conditions=("vanilla", "persona"), steps=steps + [steps[0]],
                           scores=rows, sidecars=rows, dev_bundle=bundle,
                           trusted_dev_bundle_root=tmp_path / "bundles",
                           bundle_sealer_public_key=sealer[1],
                           auditor_private_key=private, auditor_public_key=public)
    assert audit.verdict == "FAIL"
    result = report(audit, public)
    assert result.citable is False and result.status == "quarantined"


def test_suggestion_and_draft_contract_preserved(genuine_audit, auditor_keys):
    """既有断言不削弱:建议必须自带竞争解释,next_goal_draft 仍无执行把手。"""
    _, public = auditor_keys
    raw = {"observation": "o", "competing_explanation": "c",
           "discriminating_experiment": "d", "opposite_result_update": "u",
           "evidence_refs": ["e"]}
    result = report(genuine_audit, public, suggestion_inputs=[raw])
    draft = next_goal_draft(result, result.suggestions[0].suggestion_id)
    assert draft["auto_execute"] is False and draft["draft_only"] is True
    with pytest.raises(ContractError):
        report(genuine_audit, public, suggestion_inputs=[{**raw, "competing_explanation": ""}])


# --------------------------------------------------------------------------
# 对抗面:全部 fail-closed
# --------------------------------------------------------------------------

def test_valid_signature_swapped_core_rejected(genuine_audit, auditor_keys):
    """签名有效但 core 被掉包 —— FAIL 判决换成 PASS,拒绝背书。"""
    _, public = auditor_keys
    swapped = AuditAttestation(**{**genuine_audit.__dict__, "steps_hash": FAKE})
    # 重算自洽哈希,让廉价前置检查照样通过。
    swapped = AuditAttestation(**{**swapped.__dict__,
                                  "attestation_hash": sha256(audit_attestation_core(swapped))})
    with pytest.raises(ContractError) as excinfo:
        report(swapped, public)
    assert excinfo.value.code == "audit_attestation_unverified"


def test_artifact_frozen_domain_cannot_pose_as_audit(auditor_keys):
    """域分隔:用 DOMAIN_ARTIFACT_FROZEN 签的东西不能冒充审计证明。"""
    private, public = auditor_keys
    attack = forged()
    sealed = sign_attestation(private_key=private, public_key=public,
                              domain=DOMAIN_ARTIFACT_FROZEN,
                              core=audit_attestation_core(attack))
    attack = AuditAttestation(**{**attack.__dict__, "sealed": sealed})
    with pytest.raises(ContractError) as excinfo:
        report(attack, public)
    assert excinfo.value.code == "audit_attestation_unverified"


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda s: {**s, "extra_field": "x"}, id="added_field"),
    pytest.param(lambda s: {k: v for k, v in s.items() if k != "issued_at"}, id="removed_field"),
    pytest.param(lambda s: {k: v for k, v in s.items() if k != "signature_b64"}, id="missing_signature"),
    pytest.param(lambda s: {**s, "domain": "abcr.made.up.v1"}, id="unknown_domain"),
    pytest.param(lambda s: {**s, "core_sha256": FAKE}, id="core_hash_swapped"),
    pytest.param(lambda s: {**s, "signature_b64": "AAAA"}, id="signature_garbage"),
])
def test_sealed_field_tampering_rejected(genuine_audit, auditor_keys, mutate):
    _, public = auditor_keys
    tampered = AuditAttestation(**{**genuine_audit.__dict__,
                                   "sealed": mutate(dict(genuine_audit.sealed))})
    with pytest.raises(ContractError) as excinfo:
        report(tampered, public)
    assert excinfo.value.code == "audit_attestation_unverified"


def test_wrong_public_key_rejected(genuine_audit, other_keys):
    _, wrong_public = other_keys
    with pytest.raises(ContractError) as excinfo:
        report(genuine_audit, wrong_public)
    assert excinfo.value.code == "audit_attestation_unverified"


def test_missing_public_key_is_hard_error_not_a_skip(genuine_audit):
    """缺密钥必须是硬错误 —— 「无密钥则跳过验签」等于把门又拆了。"""
    with pytest.raises(ContractError) as excinfo:
        build_round_report(round_id="R1", goal_id="G1", audit=genuine_audit,
                           observations=[{"k": 1}], interpretations=["i"], limitations=["l"],
                           suggestion_inputs=[], expected_batch_id=genuine_audit.batch_id)
    assert excinfo.value.code == "auditor_public_key_missing"


def test_auditor_cannot_issue_unsigned_attestation(tmp_path):
    """签发侧同样没有免签名路径。"""
    dataset, split = sources(tmp_path)
    sealer = itempool_keys(tmp_path)
    bundle = sealed_bundle(SelectionRequest("s", "a" * 64, 1, 1),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=sealer)
    with pytest.raises(ContractError) as excinfo:
        audit_evidence(batch_id=BATCH, item_ids=bundle.item_ids, seeds=(1,),
                       conditions=("vanilla",), steps=[], scores=[], sidecars=[],
                       dev_bundle=bundle, trusted_dev_bundle_root=tmp_path / "bundles",
                       bundle_sealer_public_key=sealer[1])
    assert excinfo.value.code == "auditor_key_missing"


def test_batch_id_binding_preserved(genuine_audit, auditor_keys):
    """既有断言不削弱:身份检查仍在,且发生在验签之前。"""
    _, public = auditor_keys
    with pytest.raises(ContractError) as excinfo:
        build_round_report(round_id="R1", goal_id="G1", audit=genuine_audit,
                           observations=[{"k": 1}], interpretations=["i"], limitations=["l"],
                           suggestion_inputs=[], expected_batch_id="EXP-other",
                           auditor_public_key=public)
    assert excinfo.value.code == "audit_attestation_invalid"


# --------------------------------------------------------------------------
# 同类缺陷:ArtifactFrozenReceipt(规格判据 13 的「伪造收据」)
# --------------------------------------------------------------------------

@pytest.fixture
def candidate(tmp_path):
    goal = validate_goal(valid_goal()).goal
    assert goal
    return goal, prepare_goal_anchor(goal, research_commit="c" * 64,
                                     relative_path="goals/g.yaml", confirmed_by="owner")


def test_forged_frozen_receipt_rejected(candidate, auditor_keys):
    """一行代码构造的无签名收据 —— 曾经直接通过,现在拒绝。"""
    from abcr.explore.compiler import freeze_goal
    goal, cand = candidate
    _, public = auditor_keys
    fake = ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now")
    with pytest.raises(ContractError) as excinfo:
        freeze_goal(cand, fake, receipt_public_key=public)
    assert excinfo.value.code == "freeze_receipt_unsigned"


def test_signed_frozen_receipt_accepted(candidate, auditor_keys):
    from abcr.explore.compiler import freeze_goal
    goal, cand = candidate
    private, public = auditor_keys
    receipt = sign_frozen_receipt(ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now"),
                                  private_key=private, public_key=public)
    anchor = freeze_goal(cand, receipt, receipt_public_key=public)
    assert anchor.receipt.receipt_id == "R1"


def test_frozen_receipt_missing_key_is_hard_error(candidate, auditor_keys):
    from abcr.explore.compiler import freeze_goal
    goal, cand = candidate
    private, public = auditor_keys
    receipt = sign_frozen_receipt(ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now"),
                                  private_key=private, public_key=public)
    with pytest.raises(ContractError) as excinfo:
        freeze_goal(cand, receipt)
    assert excinfo.value.code == "freeze_receipt_key_missing"


def test_frozen_receipt_core_swap_rejected(candidate, auditor_keys):
    """拿一份合法签名去背书另一个 receipt_id。"""
    from abcr.explore.compiler import freeze_goal
    goal, cand = candidate
    private, public = auditor_keys
    signed = sign_frozen_receipt(ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now"),
                                 private_key=private, public_key=public)
    swapped = ArtifactFrozenReceipt("R2-forged", goal.goal_hash, "c" * 64, "now", signed.sealed)
    with pytest.raises(ContractError) as excinfo:
        freeze_goal(cand, swapped, receipt_public_key=public)
    assert excinfo.value.code == "freeze_receipt_unverified"


# --------------------------------------------------------------------------
# B4:「用真证据给假叙事背书」—— 真 attestation 挂到任意 goal_id + 捏造叙事。
# --------------------------------------------------------------------------

@pytest.fixture
def compiled_audit(tmp_path, auditor_keys):
    """走**真实 compile 链路**的签名审计。

    与 ``genuine_audit`` 的区别:这里 batch_id 由 ``compile_goal`` 从含 goal_id 的
    core 派生(``EXP-`` + sha256(core)[:20]),因此 batch_id 密码学承诺 goal_id ——
    这正是 goal 绑定校验所依赖的事实。返回 (audit, envelope, auditor_public)。
    """
    from abcr.explore.compiler import (ArtifactFrozenReceipt, compile_goal, freeze_goal,
                                       prepare_goal_anchor, sign_frozen_receipt)
    apriv, apub = auditor_keys
    dataset, split = sources(tmp_path)
    sealer = itempool_keys(tmp_path)
    rpriv, rpub = tmp_path / "r.key", tmp_path / "r.pub"
    generate_keypair(rpriv, rpub)
    goal = validate_goal(valid_goal()).goal
    assert goal
    bundle = sealed_bundle(SelectionRequest("S", goal.goal_hash, goal.item_count, goal.seeds[0]),
                           dataset_path=dataset, split_path=split,
                           output_root=tmp_path / "bundles", keys=sealer)
    cand = prepare_goal_anchor(goal, research_commit="c" * 64, relative_path="goals/g.yaml",
                               confirmed_by="owner")
    receipt = sign_frozen_receipt(ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now"),
                                  private_key=rpriv, public_key=rpub)
    anchor = freeze_goal(cand, receipt, receipt_public_key=rpub)
    compiled = compile_goal(goal, anchor, bundle, registry(), protocol_ref="W1-V1",
                            trusted_dev_bundle_root=tmp_path / "bundles",
                            bundle_sealer_public_key=sealer[1])
    env = compiled.envelope
    keys = [(i, s, a["id"]) for i in env["item_ids"] for s in env["seeds"] for a in env["arms"]]
    steps = [{"item_id": i, "random_seed": s, "condition": c, "prompt_hash": "p",
              "output_text": "x"} for i, s, c in keys]
    rows = [{"item_id": i, "random_seed": s, "condition": c} for i, s, c in keys]
    audit = audit_evidence(batch_id=env["batch_id"], item_ids=tuple(env["item_ids"]),
                           seeds=tuple(env["seeds"]), conditions=tuple(a["id"] for a in env["arms"]),
                           steps=steps, scores=rows, sidecars=rows, dev_bundle=bundle,
                           trusted_dev_bundle_root=tmp_path / "bundles",
                           bundle_sealer_public_key=sealer[1],
                           auditor_private_key=apriv, auditor_public_key=apub)
    return audit, env, apub


def test_b4_real_evidence_on_foreign_goal_rejected(compiled_audit):
    """规格判据里那次实测:真 PASS attestation 挂到**不同** goal_id + 捏造 observations。

    给出把 batch_id 承诺到 goal_id 的 compile envelope 后,build_round_report 强制
    校验证据集确实属于声称的 goal —— 不一致即硬失败,不再 citable=True。
    """
    audit, env, apub = compiled_audit
    assert audit.verdict == "PASS"
    with pytest.raises(ContractError) as exc:
        build_round_report(round_id="R-attack", goal_id="G-COMPLETELY-DIFFERENT", audit=audit,
                           expected_batch_id=audit.batch_id,
                           observations=[{"effect": "HUGE persona effect, p<0.001"}],
                           interpretations=["persona control works spectacularly"], limitations=[],
                           suggestion_inputs=[], auditor_public_key=apub, compile_envelope=env)
    assert exc.value.code == "goal_binding_mismatch"


def test_genuine_evidence_on_correct_goal_binds(compiled_audit):
    """正向:证据集属于声称的 goal_id → citable=True 且 goal_binding_verified=True。"""
    audit, env, apub = compiled_audit
    r = build_round_report(round_id="R1", goal_id=env["goal_id"], audit=audit,
                           expected_batch_id=audit.batch_id, observations=[{"k": 1}],
                           interpretations=["i"], limitations=[], suggestion_inputs=[],
                           auditor_public_key=apub, compile_envelope=env)
    assert r.citable is True and r.status == "reported"
    assert r.goal_binding_verified is True


def test_wrong_batch_envelope_rejected(compiled_audit):
    """既有 batch_id 绑定不能回归:自洽但 batch_id 与 attestation 不符的信封 → 拒。"""
    audit, env, apub = compiled_audit
    # 另建一个自洽信封(改 goal_id 后重算承诺的 batch_id),其 batch_id ≠ 审计 batch。
    tampered = dict(env, goal_id="G-OTHER")
    tampered["batch_id"] = "EXP-" + sha256({k: v for k, v in tampered.items()
                                            if k != "batch_id"})[:20]
    assert tampered["batch_id"] != audit.batch_id
    with pytest.raises(ContractError) as exc:
        build_round_report(round_id="R1", goal_id="G-OTHER", audit=audit,
                           expected_batch_id=audit.batch_id, observations=[{"k": 1}],
                           interpretations=["i"], limitations=[], suggestion_inputs=[],
                           auditor_public_key=apub, compile_envelope=tampered)
    assert exc.value.code == "envelope_batch_mismatch"


def test_envelope_with_unbound_batch_id_rejected(compiled_audit):
    """把 goal_id 换掉却保留原 batch_id —— batch_id 不再是内容承诺,拒绝据此绑定。"""
    audit, env, apub = compiled_audit
    unbound = dict(env, goal_id="G-SWAPPED")  # batch_id 保持原值,已不再承诺该内容
    with pytest.raises(ContractError) as exc:
        build_round_report(round_id="R1", goal_id="G-SWAPPED", audit=audit,
                           expected_batch_id=audit.batch_id, observations=[{"k": 1}],
                           interpretations=["i"], limitations=[], suggestion_inputs=[],
                           auditor_public_key=apub, compile_envelope=unbound)
    assert exc.value.code == "envelope_batch_id_unbound"


def test_malformed_compile_envelope_rejected(compiled_audit):
    """绑定证明结构非法(缺 goal_id/batch_id)→ 硬失败,不静默跳过。"""
    audit, _env, apub = compiled_audit
    with pytest.raises(ContractError) as exc:
        build_round_report(round_id="R1", goal_id="G", audit=audit,
                           expected_batch_id=audit.batch_id, observations=[{"k": 1}],
                           interpretations=["i"], limitations=[], suggestion_inputs=[],
                           auditor_public_key=apub, compile_envelope={"goal_id": "G"})
    assert exc.value.code == "bad_compile_envelope"


# --------------------------------------------------------------------------
# B4 的叙事半边:citable 只担保被签名的证据集,叙事永远不属于被认证内容。
# --------------------------------------------------------------------------

def test_narrative_is_structurally_unauthenticated(genuine_audit, auditor_keys):
    """attested_evidence 只含 auditor 签名表面;叙事恒标 narrative_authenticated=False。"""
    _, public = auditor_keys
    r = report(genuine_audit, public)
    assert r.narrative_authenticated is False
    assert set(r.attested_evidence) == {
        "batch_id", "expected_keys_hash", "steps_hash", "scores_hash", "sidecars_hash",
        "verdict", "defects", "created_at", "attestation_hash"}
    # 叙事字段与 goal_id 关联都不在被认证表面里。
    for leaked in ("observations", "interpretations", "limitations", "goal_id", "suggestions"):
        assert leaked not in r.attested_evidence


def test_swapping_narrative_does_not_change_attested_evidence(genuine_audit, auditor_keys):
    """把 observations/interpretations 整体替换,被认证表面不变 —— 叙事搭不了签名便车。"""
    _, public = auditor_keys
    r1 = report(genuine_audit, public, observations=[{"a": 1}], interpretations=["x"])
    r2 = report(genuine_audit, public, observations=[{"b": 2}],
                interpretations=["totally different fabricated claim"])
    assert r1.observations != r2.observations           # 叙事确实变了
    assert r1.attested_evidence == r2.attested_evidence  # 被认证表面纹丝不动


def test_empty_narrative_null_effect_still_citable(genuine_audit, auditor_keys):
    """既有语义不削弱:observations 可空、null 效应不是错误,依然 citable。"""
    _, public = auditor_keys
    r = report(genuine_audit, public, observations=[], interpretations=[], limitations=[])
    assert r.citable is True and r.status == "reported"


def test_without_binding_goal_association_marked_unverified(genuine_audit, auditor_keys):
    """残余边界如实标注:未提供 compile envelope 时 goal 关联未经认证。

    这是本次修复在 rounds.py 内可达的诚实边界 —— 让 goal 绑定**强制**(缺证明即
    不可引用)需要让 compile envelope 贯穿所有调用点(audit/evidence.py 的
    attestation core 不含 goal_id),属跨文件协调。此路径下绝不静默背书。
    """
    _, public = auditor_keys
    r = report(genuine_audit, public)  # 无 compile_envelope
    assert r.goal_binding_verified is False
    assert r.narrative_authenticated is False


def test_audit_domain_cannot_pose_as_frozen_receipt(candidate, auditor_keys):
    """反向域分隔:审计域签名不能当冻结收据用。"""
    from abcr.explore.compiler import freeze_goal
    goal, cand = candidate
    private, public = auditor_keys
    receipt = ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now")
    sealed = sign_attestation(private_key=private, public_key=public, domain=DOMAIN_AUDIT,
                              core=frozen_receipt_core(receipt))
    with pytest.raises(ContractError) as excinfo:
        freeze_goal(cand, ArtifactFrozenReceipt("R1", goal.goal_hash, "c" * 64, "now", sealed),
                    receipt_public_key=public)
    assert excinfo.value.code == "freeze_receipt_unverified"


def test_frozen_receipt_mismatch_still_checked(candidate, auditor_keys):
    """既有断言不削弱:内容不匹配仍先于验签被拒。"""
    from abcr.explore.compiler import freeze_goal
    _, cand = candidate
    private, public = auditor_keys
    bad = sign_frozen_receipt(ArtifactFrozenReceipt("R2", "f" * 64, "c" * 64, "now"),
                              private_key=private, public_key=public)
    with pytest.raises(ContractError) as excinfo:
        freeze_goal(cand, bad, receipt_public_key=public)
    assert excinfo.value.code == "freeze_receipt_mismatch"
