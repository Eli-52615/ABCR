"""Exact evidence-set audit and independent citable attestation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abcr.control.attestation import DOMAIN_AUDIT, sign_attestation
from abcr.control.contracts import ContractError, sha256, utc_now
from abcr.explore.item_pool import DevBundleRef, verify_dev_bundle


def _run_id(batch_id: str, config_hash: str) -> str:
    parts = batch_id.split("-")
    segment = parts[1] if len(parts) >= 3 else batch_id
    return f"{segment}-{config_hash[:12]}"


def _production_expected_keys(compile_envelope: dict[str, Any]) -> dict[tuple, dict]:
    """Rebuild arm-unique execution keys from approved inline RunConfigs.

    ``arm_id`` is intentionally not added to the frozen 48-field step schema.
    The existing signed ``run_id + config_hash`` pair identifies exactly one
    approved arm; sidecars/scores repeat arm_id as an independent cross-check.
    """
    configs = compile_envelope.get("run_configs")
    if not isinstance(configs, list) or not configs or not all(isinstance(cfg, dict) for cfg in configs):
        raise ContractError("compile_run_configs_missing", "生产审计缺内联 RunConfigs")
    expected: dict[tuple, dict] = {}
    observed_arm_seeds: dict[str, set[int]] = {}
    observed_arm_conditions: dict[str, set[str]] = {}
    approved_items = compile_envelope.get("item_ids")
    approved_seeds = compile_envelope.get("seeds")
    for cfg in configs:
        arm_id = cfg.get("arm_id")
        condition = cfg.get("condition")
        item_ids = cfg.get("item_ids")
        seeds = (cfg.get("decoding") or {}).get("seeds")
        if (not isinstance(arm_id, str) or not arm_id or not isinstance(condition, str)
                or not condition or not isinstance(item_ids, list) or not item_ids
                or not all(isinstance(item, str) and item for item in item_ids)
                or not isinstance(seeds, list) or len(seeds) != 1
                or type(seeds[0]) is not int):
            raise ContractError("compile_run_config_invalid", "生产 RunConfig arm/item/seed 身份不完整")
        config_hash = sha256(cfg)
        run_id = _run_id(compile_envelope["batch_id"], config_hash)
        if item_ids != approved_items:
            raise ContractError("compile_item_set_mismatch", "每个 RunConfig 必须复制相同 item_ids")
        observed_arm_seeds.setdefault(arm_id, set()).add(seeds[0])
        observed_arm_conditions.setdefault(arm_id, set()).add(condition)
        for item_id in item_ids:
            key = (run_id, config_hash, arm_id, item_id, seeds[0], condition)
            if key in expected:
                raise ContractError("compile_expected_key_duplicate", "RunConfig 产生重复证据 key")
            expected[key] = {"run_id": run_id, "config_hash": config_hash,
                             "arm_id": arm_id, "item_id": item_id,
                             "random_seed": seeds[0], "condition": condition}
    declared_arms = compile_envelope.get("arms")
    declared_ids = [arm.get("id") if isinstance(arm, dict) else None
                    for arm in declared_arms] if isinstance(declared_arms, list) else []
    if (not isinstance(approved_seeds, list) or not approved_seeds
            or set(observed_arm_seeds) != set(declared_ids)
            or any(values != set(approved_seeds) for values in observed_arm_seeds.values())
            or any(len(values) != 1 for values in observed_arm_conditions.values())):
        raise ContractError("compile_arm_seed_matrix_incomplete",
                            "RunConfigs 未精确覆盖每个 arm×seed")
    return expected


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
    goal_id: str | None = None
    compile_envelope_sha256: str | None = None
    compile_envelope: dict[str, Any] | None = None
    sealed: dict[str, Any] | None = None


def audit_attestation_core(audit: AuditAttestation) -> dict[str, Any]:
    """从公开字段独立重建签名 core。

    消费方用它重建 ``expected_core`` 后传给 ``verify_attestation`` —— 只验签名
    而不比对 core,等于允许攻击者拿一份合法签名去背书另一份审计结论。
    """
    core = {"batch_id": audit.batch_id, "expected_keys_hash": audit.expected_keys_hash,
            "steps_hash": audit.steps_hash, "scores_hash": audit.scores_hash,
            "sidecars_hash": audit.sidecars_hash, "verdict": audit.verdict,
            "defects": list(audit.defects), "created_at": audit.created_at}
    if audit.goal_id is not None or audit.compile_envelope_sha256 is not None:
        core.update(goal_id=audit.goal_id,
                    compile_envelope_sha256=audit.compile_envelope_sha256)
    return core


def _verify_goal_binding(compile_envelope: dict[str, Any], *, batch_id: str,
                         item_ids: tuple[str, ...], seeds: tuple[int, ...],
                         conditions: tuple[str, ...], dev_bundle: DevBundleRef) -> tuple[str, str]:
    """Validate the compiler's self-certifying envelope before the auditor signs.

    The signed audit core records both ``goal_id`` and the full envelope digest.  This
    makes goal binding a production invariant at evidence creation, rather than an
    optional report-time hint.
    """
    if not isinstance(compile_envelope, dict):
        raise ContractError("compile_envelope_required",
                            "生产审计必须提供 compile envelope 以绑定 goal")
    required = ("batch_id", "goal_id", "goal_hash", "goal_receipt_id",
                "research_commit", "deployment_id", "protocol_ref", "item_ids",
                "seeds", "arms", "dev_bundle_id")
    if any(key not in compile_envelope for key in required):
        raise ContractError("compile_envelope_invalid", "compile envelope 缺少 goal 绑定字段")
    goal_id = compile_envelope["goal_id"]
    if not isinstance(goal_id, str) or not goal_id:
        raise ContractError("compile_envelope_invalid", "compile envelope goal_id 非法")
    core = {key: value for key, value in compile_envelope.items() if key != "batch_id"}
    committed = "EXP-" + sha256(core)[:20]
    if compile_envelope["batch_id"] != committed:
        raise ContractError("envelope_batch_id_unbound", "compile envelope batch_id 未承诺完整内容")
    if batch_id != committed:
        raise ContractError("envelope_batch_mismatch", "审计 batch_id 与 compile envelope 不一致")
    if compile_envelope["item_ids"] != list(item_ids):
        raise ContractError("envelope_evidence_scope_mismatch", "审计 item_ids 与 compile envelope 不一致")
    if compile_envelope["seeds"] != list(seeds):
        raise ContractError("envelope_evidence_scope_mismatch", "审计 seeds 与 compile envelope 不一致")
    arms = compile_envelope["arms"]
    arm_ids = [arm.get("id") if isinstance(arm, dict) else None for arm in arms]
    if not isinstance(arms, list) or arm_ids != list(conditions):
        raise ContractError("envelope_evidence_scope_mismatch", "审计 arm ids 与 compile envelope 不一致")
    if compile_envelope["dev_bundle_id"] != dev_bundle.bundle_id:
        raise ContractError("envelope_evidence_scope_mismatch", "审计 dev bundle 与 compile envelope 不一致")
    return goal_id, sha256(compile_envelope)


def audit_evidence(*, batch_id: str, item_ids: tuple[str, ...], seeds: tuple[int, ...],
                   conditions: tuple[str, ...], steps: list[dict[str, Any]],
                   scores: list[dict[str, Any]], sidecars: list[dict[str, Any]],
                   dev_bundle: DevBundleRef, trusted_dev_bundle_root: Path,
                   bundle_sealer_public_key: Path,
                   compile_envelope: dict[str, Any] | None = None,
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
    goal_id, compile_envelope_sha256 = _verify_goal_binding(
        compile_envelope, batch_id=batch_id, item_ids=item_ids, seeds=seeds,
        conditions=conditions, dev_bundle=dev_bundle)
    allowed_dev_ids = frozenset(dev_bundle.item_ids)
    defects: list[str] = []
    if set(item_ids) != allowed_dev_ids: defects.append("item_set_not_exact_dev_bundle")
    production = compile_envelope.get("deployment_id") != "fixture"
    if production:
        expected_map = _production_expected_keys(compile_envelope)
        expected = set(expected_map)
        by_execution = {(value["run_id"], value["config_hash"]): value
                        for value in expected_map.values()}

        def arm_key(row: dict[str, Any], *, require_arm: bool) -> tuple:
            identity = (row.get("run_id"), row.get("config_hash"))
            approved = by_execution.get(identity)
            if approved is None:
                return (*identity, row.get("arm_id"), row.get("item_id"),
                        row.get("random_seed"), row.get("condition"))
            if require_arm and row.get("arm_id") != approved["arm_id"]:
                return (*identity, row.get("arm_id"), row.get("item_id"),
                        row.get("random_seed"), row.get("condition"))
            return (*identity, approved["arm_id"], row.get("item_id"),
                    row.get("random_seed"), row.get("condition"))

        step_keys = [arm_key(row, require_arm=False) for row in steps]
        sidecar_keys = [arm_key(row, require_arm=True) for row in sidecars]
        score_keys = [arm_key(row, require_arm=True) for row in scores]
        for name, observed in (("steps", step_keys), ("sidecars", sidecar_keys)):
            if len(observed) != len(set(observed)): defects.append(f"{name}_duplicate_key")
            if set(observed) != expected: defects.append(f"{name}_expected_set_mismatch")
        # Multiple metric rows per execution key are valid, but a metric may not
        # duplicate and every approved arm key must appear at least once.
        score_metric_keys = [(key, row.get("metric_name"))
                             for key, row in zip(score_keys, scores)]
        if len(score_metric_keys) != len(set(score_metric_keys)):
            defects.append("scores_duplicate_metric_key")
        if any(not isinstance(row.get("metric_name"), str) or not row["metric_name"]
               for row in scores):
            defects.append("scores_metric_name_missing")
        if set(score_keys) != expected:
            defects.append("scores_expected_set_mismatch")
        step_by_key = {key: row for key, row in zip(step_keys, steps)}
        sidecar_by_key = {key: row for key, row in zip(sidecar_keys, sidecars)}
        for key in expected:
            step = step_by_key.get(key)
            sidecar = sidecar_by_key.get(key)
            if step is None or sidecar is None:
                continue
            prompt_text = sidecar.get("prompt_text")
            if (not isinstance(prompt_text, str)
                    or sidecar.get("prompt_hash") != sha256(prompt_text.encode("utf-8"))
                    or step.get("prompt_hash") != sidecar.get("prompt_hash")):
                defects.append("prompt_sidecar_hash_mismatch")
                break
    else:
        # Historical/fixture bridge.  Production can never enter this branch.
        expected = {(item, seed, condition) for item in item_ids
                    for seed in seeds for condition in conditions}
        def keys(rows):
            return [(x.get("item_id"), x.get("random_seed"), x.get("condition")) for x in rows]
        for name, observed in (("steps", keys(steps)), ("scores", keys(scores)),
                               ("sidecars", keys(sidecars))):
            if len(observed) != len(set(observed)): defects.append(f"{name}_duplicate_key")
            if set(observed) != expected: defects.append(f"{name}_expected_set_mismatch")
    for step in steps:
        if not step.get("prompt_hash") or not step.get("output_text"):
            defects.append("step_raw_evidence_missing"); break
    core = {"batch_id": batch_id, "expected_keys_hash": sha256(sorted(expected)),
            "steps_hash": sha256(steps), "scores_hash": sha256(scores),
            "sidecars_hash": sha256(sidecars), "verdict": "PASS" if not defects else "FAIL",
            "defects": sorted(set(defects)), "created_at": utc_now(),
            "goal_id": goal_id, "compile_envelope_sha256": compile_envelope_sha256}
    sealed = sign_attestation(private_key=Path(auditor_private_key),
                              public_key=Path(auditor_public_key),
                              domain=DOMAIN_AUDIT, core=core)
    return AuditAttestation(batch_id=batch_id, expected_keys_hash=core["expected_keys_hash"],
                            steps_hash=core["steps_hash"], scores_hash=core["scores_hash"],
                            sidecars_hash=core["sidecars_hash"], verdict=core["verdict"],
                            defects=tuple(core["defects"]), created_at=core["created_at"],
                            attestation_hash=sha256(core), goal_id=goal_id,
                            compile_envelope_sha256=compile_envelope_sha256,
                            compile_envelope=dict(compile_envelope), sealed=sealed)
