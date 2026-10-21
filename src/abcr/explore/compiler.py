"""Compile a confirmed human goal and a dev-only bundle into an immutable draft."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_ARTIFACT_FROZEN, sign_attestation, verify_attestation
from abcr.control.contracts import (ContractError, canonical_json, require_sha, sha256,
                                    strict_object, utc_now)
from abcr.explore.goal import Goal, TEMPLATE_REGISTRY_PATH, length_control_policy
from abcr.explore.item_pool import DevBundleRef, iter_bundle_items, verify_dev_bundle
from abcr.explore.length_control import (TaskExpansionLibrary,
                                         load_task_expansion_library,
                                         validate_task_expansion_plan_receipt)
from abcr.explore.personas import PersonaRegistry
from abcr.rig.models import TOKENIZER_FINGERPRINT_SCHEMA


_DEFAULT_LENGTH_LIBRARY = (Path(__file__).resolve().parent / "resources" /
                           "task_expansion_zh_v1.json")
_DEFAULT_TEMPLATE_REGISTRY = TEMPLATE_REGISTRY_PATH


@dataclass(frozen=True)
class GoalAnchorCandidate:
    goal_id: str
    goal_hash: str
    research_commit: str
    relative_path: str
    confirmed_by: str
    deployment_id: str
    protocol_ref: str


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


def goal_anchor_payload(anchor: GoalAnchor) -> dict[str, str]:
    """Canonical ResearchMemory payload for ``goal_anchor_frozen``.

    Runtime identity is deliberately part of the externally sealed ledger row, not
    merely a caller-authored compile envelope.  Approval validation uses the same
    exact field names and rejects any mismatch.
    """
    return {
        "goal_sha256": anchor.candidate.goal_hash,
        "goal_path": anchor.candidate.relative_path,
        "research_commit": anchor.candidate.research_commit,
        "receipt_id": anchor.receipt.receipt_id,
        "deployment_id": anchor.candidate.deployment_id,
        "protocol_ref": anchor.candidate.protocol_ref,
    }


@dataclass(frozen=True)
class CompileResult:
    batch_id: str
    envelope: dict[str, Any]
    envelope_hash: str


def _verified_selection_receipt(bundle: DevBundleRef, manifest: dict[str, Any],
                                supplied: dict[str, Any] | None) -> dict[str, Any]:
    """Return the finite item-pool receipt that every RunConfig must repeat."""
    derived = {
        "bundle_id": bundle.bundle_id,
        "manifest_hash": bundle.manifest_hash,
        "item_ids": list(bundle.item_ids),
        "source_hash": bundle.source_hash,
        "split": manifest.get("split"),
        "selected_bytes_hash": manifest.get("items_sha256"),
    }
    if supplied is None:
        return derived
    receipt = strict_object(
        supplied,
        required=set(derived),
        optional={"seal_receipt_id", "sealed_tree_hash"},
    )
    for key, value in derived.items():
        if receipt[key] != value:
            raise ContractError("selection_receipt_mismatch",
                                f"selection receipt.{key} 与签名 DevBundle 不一致")
    for field in ("selected_bytes_hash", "seal_receipt_id", "sealed_tree_hash"):
        if field in receipt:
            require_sha(receipt[field], f"selection_receipt.{field}")
    return dict(receipt)


def _fixture_execution_profile() -> dict[str, Any]:
    """Non-citable profile retained only for isolated workflow fixtures."""
    return {
        "benchmark_family": "ifeval_zh_v1",
        "model": {"engine": "fake", "model_id": "fake/deterministic-v1",
                  "revision": "fixture", "dtype": "none", "device": "none"},
        "decoding": {"temperature": 0.0, "max_new_tokens": 64},
        "tokenizer_sha256": sha256(b"fixture-tokenizer"),
        "tokenizer_fingerprint_schema": TOKENIZER_FINGERPRINT_SCHEMA,
        "chat_template_sha256": sha256(b"fixture-template"),
        "scorer": {"id": "deterministic_v1", "version": "1.0"},
        "release_pin": {"release_id": "fixture", "release_tree_hash": sha256(b"fixture-tree"),
                        "release_lock_hash": sha256(b"fixture-lock")},
        "prompt_plans": {},
    }


def _validate_execution_profile(profile: dict[str, Any] | None, *, fixture: bool) -> dict[str, Any]:
    if profile is None:
        if fixture:
            return _fixture_execution_profile()
        raise ContractError(
            "execution_profile_required",
            "生产编译必须提供 root-owned 冻结 execution profile；不得用本机 probe profile 冒充",
        )
    value = strict_object(
        profile,
        required={"benchmark_family", "model", "decoding", "tokenizer_sha256",
                  "tokenizer_fingerprint_schema", "chat_template_sha256", "scorer",
                  "release_pin", "prompt_plans"},
    )
    if not isinstance(value["benchmark_family"], str) or not value["benchmark_family"]:
        raise ContractError("execution_profile_invalid", "benchmark_family 必须是非空字符串")
    model = strict_object(
        value["model"],
        required={"engine", "model_id", "revision", "dtype", "device"},
    )
    if not all(isinstance(model[key], str) and model[key]
               for key in ("engine", "model_id", "revision", "dtype", "device")):
        raise ContractError("execution_profile_invalid", "model profile 字段必须是非空字符串")
    if model["revision"].startswith("PIN-AT-"):
        raise ContractError("execution_profile_unqualified",
                            "model revision 尚未钉死，不能编译证据 RunConfig")
    if not isinstance(value["decoding"], dict) or not value["decoding"]:
        raise ContractError("execution_profile_invalid", "decoding 必须是非空对象")
    scorer = strict_object(value["scorer"], required={"id", "version"})
    if not all(isinstance(scorer[key], str) and scorer[key] for key in ("id", "version")):
        raise ContractError("execution_profile_invalid", "scorer id/version 必须钉死")
    release = strict_object(
        value["release_pin"],
        required={"release_id", "release_tree_hash", "release_lock_hash"},
    )
    if not isinstance(release["release_id"], str) or not release["release_id"]:
        raise ContractError("execution_profile_invalid", "release_id 必须是非空字符串")
    for field in ("tokenizer_sha256", "chat_template_sha256"):
        require_sha(value[field], field)
    if value["tokenizer_fingerprint_schema"] != TOKENIZER_FINGERPRINT_SCHEMA:
        raise ContractError(
            "execution_profile_tokenizer_unqualified",
            "tokenizer_sha256 不是冻结 runtime 支持的实测 fingerprint schema",
        )
    for field in ("release_tree_hash", "release_lock_hash"):
        require_sha(release[field], f"release_pin.{field}")
    if not isinstance(value["prompt_plans"], dict):
        raise ContractError("execution_profile_invalid", "prompt_plans 必须是对象")
    return dict(value)


def _arm_condition(kind: Any) -> str:
    mapping = {"control": "vanilla", "vanilla": "vanilla",
               "persona": "persona_text", "persona_text": "persona_text",
               "length": "length_instruct", "length_instruct": "length_instruct"}
    try:
        return mapping[kind]
    except (KeyError, TypeError) as exc:
        raise ContractError("unsupported_arm_kind", f"编译器不支持实验臂 kind={kind!r}") from exc


def _persona_for_arm(arm: dict[str, Any], goal: Goal,
                     personas: PersonaRegistry) -> tuple[str, str]:
    ref = arm.get("persona_ref")
    if ref is None:
        if len(goal.personas) != 1:
            raise ContractError("arm_persona_ambiguous",
                                "多人格目标的每个 persona/length arm 必须显式 persona_ref")
        ref = goal.personas[0]
    if ref not in goal.personas:
        raise ContractError("arm_persona_out_of_goal", "arm persona_ref 不在目标书 personas 中")
    return ref, personas.get(ref).render()


def _prompt_fields(*, arm: dict[str, Any], condition: str, goal: Goal,
                   personas: PersonaRegistry, profile: dict[str, Any],
                   item_ids: tuple[str, ...], fixture: bool,
                   length_library: TaskExpansionLibrary | None = None) -> dict[str, Any]:
    if condition == "vanilla":
        return {"intervention": None}
    ref, persona_text = _persona_for_arm(arm, goal, personas)
    plans = profile["prompt_plans"]
    plan = plans.get(arm["id"])
    if plan is None and fixture and condition == "persona_text":
        # Fixture tokenizer is a whitespace counter.  Production has no such
        # fallback: exact counts must come from a qualified frozen tokenizer.
        plan = {"prompt_text": persona_text,
                "prompt_sha256": sha256(persona_text.encode()),
                "prompt_token_count": max(1, len(persona_text.split())),
                "rendered_prompt_token_counts": {
                    item_id: max(1, len(persona_text.split())) for item_id in item_ids}}
    if not isinstance(plan, dict):
        raise ContractError("prompt_plan_required",
                            f"{arm['id']} 缺冻结 tokenizer 生成的 exact-token prompt plan")
    required = {"prompt_text", "prompt_sha256", "prompt_token_count",
                "rendered_prompt_token_counts"}
    if condition == "length_instruct":
        if length_library is None:
            raise ContractError("length_library_required", "生产 ③L 编译缺冻结短句库")
        exact = validate_task_expansion_plan_receipt(
            plan, persona_text, item_ids,
            tokenizer_sha256=profile["tokenizer_sha256"],
            chat_template_sha256=profile["chat_template_sha256"],
            library=length_library,
        )
    else:
        exact = strict_object(plan, required=required,
                              optional={"rendered_prompt_sha256s"})
    if (not isinstance(exact["prompt_text"], str) or not exact["prompt_text"]
            or exact["prompt_sha256"] != sha256(exact["prompt_text"].encode())):
        raise ContractError("prompt_plan_invalid", "prompt plan 文本/hash 不一致")
    if condition == "persona_text" and exact["prompt_text"] != persona_text:
        raise ContractError("persona_prompt_drift", "persona prompt plan 与冻结 PersonaArtifact 不一致")
    count = exact["prompt_token_count"]
    rendered = exact["rendered_prompt_token_counts"]
    if (type(count) is not int or count < 1 or not isinstance(rendered, dict)
            or set(rendered) != set(item_ids)
            or any(type(rendered[item_id]) is not int or rendered[item_id] < 1
                   for item_id in item_ids)):
        raise ContractError("prompt_plan_invalid", "prompt token 计划未精确覆盖 item_ids")
    intervention = {"trait": ref, "prompt_text": exact["prompt_text"],
                    "prompt_sha256": exact["prompt_sha256"],
                    "artifact_ref": f"personas/{ref}/persona.json"}
    fields = {"intervention": intervention, "prompt_text": exact["prompt_text"],
              "prompt_sha256": exact["prompt_sha256"], "prompt_token_count": count,
              "rendered_prompt_token_counts": dict(rendered)}
    if condition == "length_instruct":
        fields["control_role"] = "task_expansion_bracket"
        fields["length_control_receipt"] = dict(exact)
    return fields


def _validate_persona_length_plans(*, goal: Goal, personas: PersonaRegistry,
                                   profile: dict[str, Any], item_ids: tuple[str, ...],
                                   library: TaskExpansionLibrary) -> None:
    """Bind each persona to exactly one own ③L receipt before any config is emitted."""
    persona_arm_by_ref: dict[str, dict[str, Any]] = {}
    length_arm_by_ref: dict[str, dict[str, Any]] = {}
    for arm in goal.arms:
        condition = _arm_condition(arm.get("kind"))
        if condition not in {"persona_text", "length_instruct"}:
            continue
        ref, _ = _persona_for_arm(arm, goal, personas)
        destination = persona_arm_by_ref if condition == "persona_text" else length_arm_by_ref
        if ref in destination:
            raise ContractError("persona_length_pair_invalid", "每个人格每类实验臂只能出现一次")
        destination[ref] = arm
    if set(persona_arm_by_ref) != set(goal.personas) or set(length_arm_by_ref) != set(goal.personas):
        raise ContractError("persona_length_pair_invalid",
                            "每个人格必须恰有一个 persona_text 与一个自己的 ③L")
    plans = profile["prompt_plans"]
    for ref in goal.personas:
        persona_text = personas.get(ref).render()
        persona_arm = persona_arm_by_ref[ref]
        length_arm = length_arm_by_ref[ref]
        persona_plan = plans.get(persona_arm.get("id"))
        length_plan = plans.get(length_arm.get("id"))
        if not isinstance(persona_plan, dict) or not isinstance(length_plan, dict):
            raise ContractError("prompt_plan_required", f"{ref} 缺 persona/③L 冻结 prompt plan")
        persona_exact = strict_object(
            persona_plan,
            required={"prompt_text", "prompt_sha256", "prompt_token_count",
                      "rendered_prompt_token_counts", "rendered_prompt_sha256s"},
        )
        if (persona_exact["prompt_text"] != persona_text
                or persona_exact["prompt_sha256"] != sha256(persona_text.encode("utf-8"))
                or type(persona_exact["prompt_token_count"]) is not int
                or persona_exact["prompt_token_count"] < 1):
            raise ContractError("persona_prompt_drift", "persona prompt plan 与冻结工件不一致")
        persona_counts = persona_exact["rendered_prompt_token_counts"]
        persona_hashes = persona_exact["rendered_prompt_sha256s"]
        if (not isinstance(persona_counts, dict) or set(persona_counts) != set(item_ids)
                or any(type(value) is not int or value < 1 for value in persona_counts.values())
                or not isinstance(persona_hashes, dict) or set(persona_hashes) != set(item_ids)):
            raise ContractError("persona_prompt_plan_invalid", "persona 最终 chat 计划未覆盖 item")
        for value in persona_hashes.values():
            require_sha(value, "persona.rendered_prompt_sha256")
        verified = validate_task_expansion_plan_receipt(
            length_plan, persona_text, item_ids,
            tokenizer_sha256=profile["tokenizer_sha256"],
            chat_template_sha256=profile["chat_template_sha256"], library=library)
        if (verified["target_prompt_token_count"] != persona_exact["prompt_token_count"]
                or verified["target_rendered_prompt_token_counts"] != persona_counts
                or verified["target_rendered_prompt_sha256s"] != persona_hashes):
            raise ContractError("persona_length_final_mismatch",
                                "③L 未与自己的 persona 最终 chat 序列化逐 item 精确配对")


def build_run_configs(*, goal: Goal, bundle: DevBundleRef,
                      personas: PersonaRegistry, selection_receipt: dict[str, Any],
                      execution_profile: dict[str, Any], evidence_base: dict[str, str],
                      fixture: bool = False,
                      length_library_path: Path | None = None,
                      template_registry_path: Path | None = None) -> list[dict[str, Any]]:
    """Build one deterministic immutable RunConfig for every arm x seed."""
    item_ids = tuple(bundle.item_ids)
    profile = _validate_execution_profile(execution_profile, fixture=fixture)
    evidence = {
        **evidence_base,
        "dev_bundle_id": bundle.bundle_id,
        "dev_bundle_manifest_hash": bundle.manifest_hash,
        "source_hash": bundle.source_hash,
        "item_set_hash": sha256(list(item_ids)),
        "selected_bytes_hash": selection_receipt["selected_bytes_hash"],
        "scorer_id": profile["scorer"]["id"],
        "scorer_version": profile["scorer"]["version"],
        "model_id": profile["model"]["model_id"],
        "model_revision": profile["model"]["revision"],
        "tokenizer_sha256": profile["tokenizer_sha256"],
        "tokenizer_fingerprint_schema": profile["tokenizer_fingerprint_schema"],
        "chat_template_sha256": profile["chat_template_sha256"],
        "release_id": profile["release_pin"]["release_id"],
        "release_tree_hash": profile["release_pin"]["release_tree_hash"],
        "release_lock_hash": profile["release_pin"]["release_lock_hash"],
    }
    length_library: TaskExpansionLibrary | None = None
    if not fixture:
        length_policy = length_control_policy(
            goal.template_id,
            Path(template_registry_path) if template_registry_path is not None
            else _DEFAULT_TEMPLATE_REGISTRY)
        conditions = [_arm_condition(arm.get("kind")) for arm in goal.arms]
        if conditions.count("vanilla") != 1:
            raise ContractError("vanilla_arm_invalid", "生产目标必须恰有一个 vanilla 对照臂")
        persona_refs = [_persona_for_arm(arm, goal, personas)[0]
                        for arm, condition in zip(goal.arms, conditions)
                        if condition == "persona_text"]
        length_refs = [_persona_for_arm(arm, goal, personas)[0]
                       for arm, condition in zip(goal.arms, conditions)
                       if condition == "length_instruct"]
        if (sorted(persona_refs) != sorted(goal.personas)
                or len(persona_refs) != len(set(persona_refs))):
            raise ContractError("persona_length_pair_invalid",
                                "每个人格必须恰有一个 persona_text 实验臂")
        has_complete_3l = (sorted(length_refs) == sorted(goal.personas)
                           and len(length_refs) == len(set(length_refs)))
        if ((length_policy == "required" and not has_complete_3l)
                or (length_policy == "optional" and length_refs and not has_complete_3l)):
            raise ContractError(
                "persona_length_pair_invalid",
                "强制模板必须完整③L；可选模板一旦请求③L也必须覆盖每个人格且不重复")
        if has_complete_3l:
            length_library = load_task_expansion_library(
                Path(length_library_path) if length_library_path is not None
                else _DEFAULT_LENGTH_LIBRARY)
            _validate_persona_length_plans(
                goal=goal, personas=personas, profile=profile, item_ids=item_ids,
                library=length_library)
    out: list[dict[str, Any]] = []
    arm_ids: set[str] = set()
    for arm in goal.arms:
        arm_id = arm.get("id")
        if not isinstance(arm_id, str) or not arm_id or arm_id in arm_ids:
            raise ContractError("bad_arm_id", "arm id 必须非空且不重复")
        arm_ids.add(arm_id)
        condition = _arm_condition(arm.get("kind"))
        prompt = _prompt_fields(arm=arm, condition=condition, goal=goal,
                                personas=personas, profile=profile,
                                item_ids=item_ids, fixture=fixture,
                                length_library=length_library)
        for seed in goal.seeds:
            cfg = {
                "config_version": "1.0", "protocol_ref": evidence_base["protocol_ref"],
                "arm_id": arm_id, "model": dict(profile["model"]),
                "benchmark": {"family": profile["benchmark_family"], "split": "dev",
                              "item_limit": len(item_ids)},
                "condition": condition, **prompt,
                "tokenizer_sha256": profile["tokenizer_sha256"],
                "tokenizer_fingerprint_schema": profile["tokenizer_fingerprint_schema"],
                "decoding": {**profile["decoding"], "seeds": [seed]},
                "item_ids": list(item_ids),
                "dev_bundle_ref": {"bundle_id": bundle.bundle_id,
                                   "manifest_hash": bundle.manifest_hash,
                                   "item_ids": list(item_ids), "source_hash": bundle.source_hash},
                "selection_receipt": dict(selection_receipt),
                "evidence_inputs": dict(evidence),
                "release_pin": dict(profile["release_pin"]),
            }
            out.append(cfg)
    if len({sha256(config) for config in out}) != len(out):
        raise ContractError("run_config_collision", "arm×seed RunConfig 必须具有唯一 config hash")
    return out


def prepare_goal_anchor(goal: Goal, *, research_commit: str, relative_path: str,
                        confirmed_by: str, deployment_id: str,
                        protocol_ref: str) -> GoalAnchorCandidate:
    if (not isinstance(research_commit, str) or len(research_commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in research_commit)):
        raise ContractError("research_commit_invalid",
                            "research_commit 必须是 SHA-1/SHA-256 Git object id")
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ContractError("bad_goal_path", "goal path 必须是规范相对路径")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ContractError("deployment_id_invalid", "deployment_id 必须是非空字符串")
    if not isinstance(protocol_ref, str) or not protocol_ref:
        raise ContractError("protocol_ref_invalid", "protocol_ref 必须是非空字符串")
    return GoalAnchorCandidate(goal.goal_id, goal.goal_hash, research_commit,
                               relative_path, confirmed_by, deployment_id, protocol_ref)


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
                 deployment_id: str, created_at: str | None = None,
                 selection_receipt: dict[str, Any] | None = None,
                 execution_profile: dict[str, Any] | None = None,
                 length_library_path: Path | None = None,
                 template_registry_path: Path | None = None) -> CompileResult:
    if goal.goal_hash != anchor.candidate.goal_hash:
        raise ContractError("goal_anchor_mismatch", "目标字节与冻结锚不一致")
    if goal.split != "dev":
        raise ContractError("non_dev_compile", "只允许编译 dev 目标")
    if (anchor.candidate.deployment_id != deployment_id
            or anchor.candidate.protocol_ref != protocol_ref):
        raise ContractError("goal_anchor_runtime_mismatch",
                            "deployment_id/protocol_ref 与冻结 goal anchor 不一致")
    manifest = verify_dev_bundle(bundle, trusted_dev_bundle_root,
                                 sealer_public_key=bundle_sealer_public_key)
    if len(bundle.item_ids) != goal.item_count:
        raise ContractError("bundle_item_count_mismatch", "DevBundle 题量与目标书不一致")
    persona_refs = []
    for ref in goal.personas:
        artifact = personas.get(ref)
        persona_refs.append({"ref": ref, "sha256": artifact.digest})
    receipt = _verified_selection_receipt(bundle, manifest, selection_receipt)
    fixture = deployment_id == "fixture"
    profile = _validate_execution_profile(execution_profile, fixture=fixture)
    # This eager read is of the already sealed, selected-only bundle.  Compiler
    # never receives a dataset/split root and therefore cannot inspect cal/holdout.
    selected = tuple(iter_bundle_items(
        bundle, trusted_dev_bundle_root, sealer_public_key=bundle_sealer_public_key))
    families = {item.get("family") for item in selected if item.get("family") is not None}
    if families and families != {profile["benchmark_family"]}:
        raise ContractError("execution_profile_family_mismatch",
                            "execution profile benchmark 与 DevBundle selected items 不一致")
    evidence_base = {
        "goal_hash": goal.goal_hash,
        "goal_receipt_id": anchor.receipt.receipt_id,
        "research_commit": anchor.candidate.research_commit,
        "deployment_id": deployment_id,
        "protocol_ref": protocol_ref,
    }
    run_configs = build_run_configs(
        goal=goal, bundle=bundle, personas=personas, selection_receipt=receipt,
        execution_profile=profile, evidence_base=evidence_base, fixture=fixture,
        length_library_path=length_library_path,
        template_registry_path=template_registry_path)
    scope = {
        "benchmark_families": sorted({cfg["benchmark"]["family"] for cfg in run_configs}),
        "conditions": sorted({cfg["condition"] for cfg in run_configs}),
        "splits": ["dev"], "item_limit_per_run": len(bundle.item_ids),
        "seeds": list(goal.seeds),
        "trait_whitelist": sorted({cfg["intervention"]["trait"] for cfg in run_configs
                                    if isinstance(cfg.get("intervention"), dict)
                                    and cfg["intervention"].get("trait")}),
    }
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
        "max_cost_usd": goal.max_cost_usd, "created_at": created_at or utc_now(),
        "selection_receipt": receipt, "scope": scope, "run_configs": run_configs,
    }
    batch_id = "EXP-" + sha256(core)[:20]
    envelope = dict(core, batch_id=batch_id)
    return CompileResult(batch_id, envelope, sha256(canonical_json(envelope)))
