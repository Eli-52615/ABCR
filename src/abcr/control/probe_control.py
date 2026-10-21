"""Operator-owned, idempotent control sagas for exploratory probe intents.

The command plane never accepts a filesystem path.  Every probe request is rebuilt
from one compiled, human-confirmed goal, its sealed DevBundle identity, a registered
PersonaArtifact, and the root-configured probe profile.  Results remain explicitly
non-citable and only their receipt/index crosses back from the probe domain.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from abcr.control.contracts import ContractError, require_sha, sha256, strict_object
from abcr.control.store import ControlStore, StoreError
from abcr.explore.goal import validate_goal
from abcr.explore.memory import ResearchMemory
from abcr.explore.personas import PersonaRegistry


def _actor_id(store: ControlStore, effect_id: str) -> str:
    actor = store.action_actor(effect_id)
    value = actor.get("open_id")
    if not isinstance(value, str) or not value:
        raise ContractError("actor_identity_missing", "命令缺少已认证操作者归因")
    return value


def _compiled_envelope(store: ControlStore, proposal_id: str,
                       goal_hash: str) -> dict[str, Any]:
    matches = []
    for event in store.rows("research_events"):
        if event["event_type"] != "compile_envelope_ready":
            continue
        value = json.loads(event["payload_json"])
        envelope = value.get("envelope")
        if (value.get("proposal_id") == proposal_id and isinstance(envelope, dict)
                and envelope.get("goal_hash") == goal_hash):
            matches.append(envelope)
    if len(matches) != 1:
        raise ContractError("probe_compiled_goal_missing",
                            "快道只能从唯一的已确认、已编译目标启动")
    return matches[0]


def _trusted_personas(root: Path) -> PersonaRegistry:
    """Load only finite, direct, operator-owned artifact files from the fixed root."""
    root = Path(root)
    try:
        info = root.lstat()
    except OSError as exc:
        raise ContractError("persona_root_unsafe", "人格根不可达") from exc
    if (root.is_symlink() or not root.is_absolute() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022):
        raise ContractError("persona_root_unsafe", "人格根 owner/mode/link 不可信")
    files = sorted(root.glob("*.json"))
    if not files or len(files) > 10000:
        raise ContractError("persona_root_unsafe", "人格工件集合为空或超限")
    for path in files:
        item = path.lstat()
        if (path.parent != root or path.is_symlink() or not stat.S_ISREG(item.st_mode)
                or item.st_nlink != 1 or item.st_uid != os.geteuid()
                or stat.S_IMODE(item.st_mode) & 0o022 or item.st_size > 1024 * 1024):
            raise ContractError("persona_artifact_unsafe", "人格工件 owner/mode/link/size 不可信")
    registry = PersonaRegistry(); registry.load_dir(root)
    return registry


def _selection(payload: dict[str, Any], *, personas: tuple[str, ...],
               predictions: tuple[Any, ...], seeds: tuple[int, ...]) -> tuple[int, int, bool]:
    """Select one prediction and seed; the scientific arm set is never narrowed.

    ``persona_ref`` remains accepted as a legacy assertion for already-rendered
    Feishu commands.  It is validated but cannot suppress vanilla or the other
    personas declared by the confirmed goal.
    """
    exact = strict_object(payload, required={"proposal_id"},
                          optional={"persona_ref", "prediction_index", "seed",
                                    "with_length_control"})
    persona_ref = exact.get("persona_ref")
    prediction_index = exact.get("prediction_index")
    seed = exact.get("seed")
    with_length_control = exact.get("with_length_control", False)
    if type(with_length_control) is not bool:
        raise ContractError("probe_length_control_invalid", "with_length_control 必须是布尔值")
    missing: list[str] = []
    if prediction_index is None:
        if len(predictions) == 1: prediction_index = 1
        else: missing.append("prediction_index")
    if seed is None:
        if len(seeds) == 1: seed = seeds[0]
        else: missing.append("seed")
    if missing:
        raise ContractError(
            "needs_clarification",
            "目标包含多个科学选择；请明确发送“运行快道 <proposal_id> "
            "<prediction序号，从1开始> <seed>”",
            {"missing": missing, "personas_always_run": list(personas),
             "prediction_indices": list(range(1, len(predictions) + 1)),
             "seeds": list(seeds)},
        )
    if persona_ref is not None and persona_ref not in personas:
        raise ContractError("probe_persona_not_in_goal", "所选人格不属于已确认目标")
    if (type(prediction_index) is not int or isinstance(prediction_index, bool)
            or not 1 <= prediction_index <= len(predictions)):
        raise ContractError("probe_prediction_invalid", "prediction 序号不合法")
    if type(seed) is not int or isinstance(seed, bool) or seed not in seeds:
        raise ContractError("probe_seed_not_in_goal", "seed 不属于已确认目标")
    return prediction_index, seed, with_length_control


def queue_probe(*, store: ControlStore, broker: Any, effect_id: str,
                payload: dict[str, Any], persona_root: Path,
                profile_id: str, max_output_tokens: int) -> dict[str, Any]:
    """Build and enqueue one fixed probe request; exact replay is a no-op."""
    proposal_id = payload.get("proposal_id")
    if not isinstance(proposal_id, str):
        raise ContractError("probe_proposal_invalid", "proposal_id 不合法")
    proposal = store.get_proposal(proposal_id)
    if proposal is None or proposal["state"] != "compiled":
        raise ContractError("probe_goal_not_compiled", "目标尚未完成确认与可信编译")
    report = validate_goal(proposal["raw_text"].encode("utf-8"))
    if not report.ok or report.goal is None:
        raise ContractError("probe_goal_invalid", "已存目标无法通过确定性复验")
    goal = report.goal
    envelope = _compiled_envelope(store, proposal_id, goal.goal_hash)
    prediction_index, seed, with_length_control = _selection(
        payload, personas=goal.personas, predictions=goal.predictions, seeds=goal.seeds)
    if not 1 <= len(goal.personas) <= 3:
        raise ContractError("probe_persona_count_invalid", "快道必须包含 1-3 个人格")
    registry = _trusted_personas(Path(persona_root))
    compiled_personas = envelope.get("personas")
    if (not isinstance(compiled_personas, list)
            or len(compiled_personas) != len(goal.personas)):
        raise ContractError("probe_persona_binding_invalid",
                            "实际 PersonaArtifact digest 与编译信封不一致")
    rendered_personas = []
    for persona_ref in goal.personas:
        persona = registry.get(persona_ref)
        matches = [item for item in compiled_personas if isinstance(item, dict)
                   and item.get("ref") == persona_ref
                   and item.get("sha256") == persona.digest]
        if len(matches) != 1:
            raise ContractError("probe_persona_binding_invalid",
                                "实际 PersonaArtifact digest 与编译信封不一致")
        rendered_personas.append({"persona_ref": persona_ref,
                                  "persona_text": persona.render()})
    if ({item.get("ref") for item in compiled_personas if isinstance(item, dict)}
            != set(goal.personas)):
        raise ContractError("probe_persona_binding_invalid",
                            "编译信封人格集合与已确认目标不一致")
    selection = strict_object(envelope["selection_receipt"], required={
        "bundle_id", "manifest_hash", "item_ids", "source_hash", "split",
        "selected_bytes_hash", "seal_receipt_id", "sealed_tree_hash"})
    if selection["split"] != "dev" or envelope.get("dev_bundle_id") != selection["bundle_id"]:
        raise ContractError("probe_bundle_binding_invalid", "编译信封的 DevBundle 绑定不合法")
    for field in ("bundle_id", "manifest_hash", "source_hash", "selected_bytes_hash",
                  "seal_receipt_id", "sealed_tree_hash"):
        require_sha(selection[field], f"selection_receipt.{field}")
    item_ids = selection["item_ids"]
    if (not isinstance(item_ids, list) or not item_ids
            or len(item_ids) != len(set(item_ids))
            or any(not isinstance(item_id, str) or not item_id for item_id in item_ids)):
        raise ContractError("probe_bundle_binding_invalid", "DevBundle item_ids 不合法")
    if (not isinstance(profile_id, str) or not profile_id
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096):
        raise ContractError("probe_policy_invalid", "root-owned 快道策略不合法")
    prediction = goal.predictions[prediction_index - 1]
    length_controls: list[dict[str, Any]] = []
    if with_length_control:
        run_configs = envelope.get("run_configs")
        if not isinstance(run_configs, list):
            raise ContractError("probe_length_control_missing", "编译信封没有 ③L RunConfig")
        for persona_ref in goal.personas:
            matches: dict[str, dict[str, Any]] = {}
            for cfg in run_configs:
                if (not isinstance(cfg, dict) or cfg.get("condition") != "length_instruct"
                        or (cfg.get("intervention") or {}).get("trait") != persona_ref
                        or not isinstance(cfg.get("length_control_receipt"), dict)):
                    continue
                digest = sha256(cfg["length_control_receipt"])
                matches[digest] = cfg["length_control_receipt"]
            if len(matches) != 1:
                raise ContractError("probe_length_control_missing",
                                    "每个人格必须恰有一个预编译且跨 seed 一致的 ③L")
            length_controls.append({"persona_ref": persona_ref,
                                    "plan": next(iter(matches.values()))})
    request = {
        "probe_id": "PROBE-" + effect_id[:24], "goal_hash": goal.goal_hash,
        "dev_bundle": {key: selection[key] for key in (
            "bundle_id", "manifest_hash", "item_ids", "source_hash")},
        "personas": rendered_personas,
        "prediction": json.dumps(prediction.__dict__, ensure_ascii=False, sort_keys=True),
        "seed": seed, "model_profile": profile_id,
        "max_output_tokens": max_output_tokens,
        "with_length_control": with_length_control,
        "length_controls": length_controls,
    }
    actor_id = _actor_id(store, effect_id)
    work_id = "probe-" + sha256({"effect_id": effect_id, "request": request})[:32]
    store.prepare_probe_run(effect_id=effect_id, work_id=work_id,
                            proposal_id=proposal_id, actor_id=actor_id,
                            goal_id=goal.goal_id, goal_hash=goal.goal_hash,
                            request=request)
    broker.request("work_enqueue", {"stage": "probe", "work_id": work_id,
                                    "attempt": 1, "fencing_token": 1,
                                    "producer": "abcr-operator", "payload": request})
    return {"code": "probe_queued", "probe_id": request["probe_id"],
            "work_id": work_id, "goal_id": goal.goal_id,
            "persona_refs": list(goal.personas),
            "arm_ids": ["vanilla", *[f"persona:{ref}" for ref in goal.personas],
                        *([f"length:{ref}" for ref in goal.personas]
                          if with_length_control else [])],
            "prediction_index": prediction_index, "seed": seed, "citable": False}


def _append_once(memory: ResearchMemory, *, event_type: str, subject_id: str,
                 actor_id: str, payload: dict[str, Any], identity_key: str,
                 identity_value: str) -> dict[str, Any]:
    matches = [row for row in memory.verify() if row["event_type"] == event_type
               and row["payload"].get(identity_key) == identity_value]
    if matches:
        expected = (subject_id, actor_id, payload)
        if any((row["subject_id"], row["actor_id"], row["payload"]) != expected
               for row in matches):
            raise ContractError("research_memory_replay_conflict",
                                "ResearchMemory 幂等身份已绑定不同内容")
        return matches[0]
    return memory.append(event_type, subject_id, payload, actor_id=actor_id)


def _seal(memory: ResearchMemory, broker: Any, nonce: str,
          expected_entry: str) -> dict[str, Any]:
    # The target row need not remain the head: another legitimate saga may append
    # before this retry.  It must, however, still exist in the verified chain.
    if expected_entry not in {row["entry_hash"] for row in memory.verify()}:
        raise ContractError("research_memory_target_missing",
                            "待封印 ResearchMemory 条目不在当前完整链")
    core = memory.seal_core()
    receipt = broker.request("seal_research_memory", {
        "nonce": nonce, "expected_length": core["length"],
        "expected_head_entry_hash": core["head_entry_hash"],
        "expected_ledger_sha256": core["ledger_sha256"],
    })
    if (not isinstance(receipt, dict) or receipt.get("length") != core["length"]
            or receipt.get("head_entry_hash") != core["head_entry_hash"]
            or receipt.get("ledger_sha256") != core["ledger_sha256"]):
        raise ContractError("research_seal_mismatch", "ResearchMemory 外部 seal 回执失配")
    return receipt


def reconcile_probe_results(*, store: ControlStore, broker: Any,
                            research_memory_path: Path) -> int:
    """Import finite probe receipts into panel state and sealed ResearchMemory."""
    completed: dict[str, list[dict[str, Any]]] = {}
    for item in broker.completed_fenced("probe"):
        completed.setdefault(item["work_id"], []).append(item)
    count = 0
    memory = ResearchMemory(Path(research_memory_path), owner_uid=os.geteuid())
    for run in store.rows("probe_runs"):
        if run["state"] == "completed" or run["work_id"] not in completed:
            continue
        fences = completed[run["work_id"]]
        if len(fences) != 1:
            raise ContractError("probe_result_fence_ambiguous", "快道结果 fence 不唯一")
        attempt = fences[0]["attempt"]; fencing_token = fences[0]["fencing_token"]
        envelope = broker.read_result("probe", run["work_id"], attempt=attempt,
                                      fencing_token=fencing_token)
        if (envelope["stage"] != "probe" or envelope["work_id"] != run["work_id"]
                or envelope["attempt"] != attempt
                or envelope["fencing_token"] != fencing_token
                or envelope["consumer"] != "abcr-probe"
                or envelope["result_hash"] != sha256(envelope["result"])):
            raise ContractError("probe_result_envelope_invalid", "快道结果信封/fence/hash 失配")
        outer = strict_object(envelope["result"], required={"ok"},
                              optional={"result", "error_code"})
        if outer["ok"] is not True or not isinstance(outer.get("result"), dict):
            raise ContractError("probe_result_failed", str(outer.get("error_code", "failed")))
        receipt = strict_object(outer["result"], required={
            "schema_version", "receipt_type", "probe_id", "model_profile", "row_count",
            "engine_fingerprint_sha256", "item_ids", "arm_ids", "row_hashes", "rows",
            "citable", "label",
            "started_at", "completed_at", "length_control_3l"})
        row_hashes = receipt["row_hashes"]; indexes = receipt["rows"]
        request = json.loads(run["request_json"])
        request_personas = request.get("personas")
        if (not isinstance(request_personas, list)
                or not 1 <= len(request_personas) <= 3
                or any(not isinstance(value, dict)
                       or set(value) != {"persona_ref", "persona_text"}
                       or not isinstance(value["persona_ref"], str)
                       for value in request_personas)):
            raise ContractError("probe_request_invalid", "快道原请求人格集合不合法")
        expected_arms = ["vanilla", *[
            f"persona:{value['persona_ref']}" for value in request_personas]]
        requested_3l = request.get("with_length_control") is True
        if requested_3l:
            controls = request.get("length_controls")
            if (not isinstance(controls, list) or len(controls) != len(request_personas)
                    or {value.get("persona_ref") for value in controls
                        if isinstance(value, dict)}
                    != {value["persona_ref"] for value in request_personas}):
                raise ContractError("probe_request_invalid", "快道 ③L 未完整覆盖人格集合")
            expected_arms.extend(
                f"length:{value['persona_ref']}" for value in request_personas)
        expected_item_ids = request.get("dev_bundle", {}).get("item_ids")
        expected_count = (len(expected_item_ids) * len(expected_arms)
                          if isinstance(expected_item_ids, list) else -1)
        if (not isinstance(row_hashes, list) or not isinstance(indexes, list)
                or any(not isinstance(value, str) for value in row_hashes)
                or len(row_hashes) != len(set(row_hashes))
                or receipt["schema_version"] != 2 or receipt["receipt_type"] != "ProbeResultReceipt"
                or receipt["citable"] is not False or receipt["row_count"] != len(receipt["row_hashes"])
                or receipt["label"] != "学习数据·不可引用"
                or receipt["row_count"] != len(receipt["rows"])
                or receipt["row_count"] != expected_count
                or receipt["probe_id"] != request["probe_id"]
                or receipt["model_profile"] != request["model_profile"]
                or receipt["item_ids"] != expected_item_ids
                or receipt["arm_ids"] != expected_arms
                or receipt["length_control_3l"] != {
                    "requested": requested_3l,
                    "status": "PASS" if requested_3l else "NOT_REQUESTED"}):
            raise ContractError("probe_result_invalid", "快道结果回执不合法")
        require_sha(receipt["engine_fingerprint_sha256"],
                    "engine_fingerprint_sha256")
        persona_by_arm = {f"persona:{value['persona_ref']}": value["persona_ref"]
                          for value in request_personas}
        if requested_3l:
            persona_by_arm.update({f"length:{value['persona_ref']}": value["persona_ref"]
                                   for value in request_personas})
        seen_cells: set[tuple[str, str, int]] = set()
        indexed_hashes: list[str] = []
        for index in indexes:
            exact = strict_object(index, required={
                "row_hash", "cell_id", "goal_hash", "item_id", "seed",
                "arm_id", "arm_kind", "persona_ref", "engine_fingerprint_sha256"})
            require_sha(exact["row_hash"], "row_hash")
            require_sha(exact["cell_id"], "cell_id")
            expected_persona_ref = persona_by_arm.get(exact["arm_id"])
            expected_kind = ("vanilla" if exact["arm_id"] == "vanilla" else
                             "length_control" if exact["arm_id"].startswith("length:")
                             else "persona")
            cell = (exact["arm_id"], exact["item_id"], exact["seed"])
            expected_cell_id = sha256({
                "probe_id": request["probe_id"], "arm_id": exact["arm_id"],
                "item_id": exact["item_id"], "seed": exact["seed"],
                "model_profile": request["model_profile"],
                "engine_fingerprint_sha256": receipt["engine_fingerprint_sha256"],
            })
            if (not isinstance(exact["item_id"], str) or not exact["item_id"]
                    or exact["item_id"] not in expected_item_ids
                    or exact["seed"] != request["seed"]
                    or exact["arm_id"] not in expected_arms
                    or exact["arm_kind"] != expected_kind
                    or exact["persona_ref"] != expected_persona_ref
                    or exact["engine_fingerprint_sha256"]
                       != receipt["engine_fingerprint_sha256"]
                    or exact["cell_id"] != expected_cell_id
                    or cell in seen_cells or exact["goal_hash"] != run["goal_hash"]):
                raise ContractError("probe_result_binding_invalid", "快道行索引与目标/回执不一致")
            seen_cells.add(cell); indexed_hashes.append(exact["row_hash"])
        expected_cells = {(arm_id, item_id, request["seed"])
                          for item_id in expected_item_ids for arm_id in expected_arms}
        if seen_cells != expected_cells:
            raise ContractError("probe_result_binding_invalid", "快道多臂 cell 覆盖不完整")
        if indexed_hashes != row_hashes:
            raise ContractError("probe_result_binding_invalid", "row_hashes 与有序行索引不一致")
        event_payload = {"work_id": run["work_id"], "effect_id": run["effect_id"],
                         "proposal_id": run["proposal_id"], "receipt": receipt,
                         "evidence_class": "exploratory_learning_only", "citable": False}
        row = _append_once(memory, event_type="probe_result_observed",
                           subject_id=run["goal_id"], actor_id=run["actor_id"],
                           payload=event_payload, identity_key="work_id",
                           identity_value=run["work_id"])
        _seal(memory, broker, "RM-PROBE-" + run["work_id"][:32], row["entry_hash"])
        store.settle_probe_run(work_id=run["work_id"], result=receipt,
                               result_hash=envelope["result_hash"])
        broker.acknowledge("probe", run["work_id"], result_hash=envelope["result_hash"],
                           attempt=attempt, fencing_token=fencing_token)
        count += 1
    return count


def create_promotion_draft(*, store: ControlStore, effect_id: str,
                           payload: dict[str, Any]) -> dict[str, Any]:
    exact = strict_object(payload, required={"row_hash"})
    row_hash = require_sha(exact["row_hash"], "row_hash")
    actor_id = _actor_id(store, effect_id)
    existing = [row for row in store.rows("probe_promotions")
                if row["effect_id"] == effect_id]
    if existing:
        return json.loads(existing[0]["draft_json"])
    sources = []
    for run in store.rows("probe_runs"):
        if run["state"] != "completed" or not run["result_json"]:
            continue
        receipt = json.loads(run["result_json"])
        sources.extend(index for index in receipt.get("rows", [])
                       if index.get("row_hash") == row_hash)
    if len(sources) != 1:
        raise ContractError("probe_row_unavailable", "该快道行尚未由可信回执回收或身份不唯一")
    source = sources[0]
    actions = [row for row in store.rows("actions") if row["effect_id"] == effect_id]
    created_at = actions[0]["created_at"] if len(actions) == 1 else "UNKNOWN"
    core = {"draft_only": True, "auto_execute": False,
            "requires_human_claude_review": True,
            "source_goal_hash": source["goal_hash"], "source_probe_rows": [row_hash],
            "source_probe_arm": {
                "arm_id": source.get("arm_id", "UNKNOWN"),
                "arm_kind": source.get("arm_kind", "UNKNOWN"),
                "persona_ref": source.get("persona_ref"),
            },
            "excluded_item_ids": [source["item_id"]], "confirmed_by": actor_id,
            "created_at": created_at,
            "next_step": "人需与 Claude 手动审阅；如要形成新目标，必须重新导入并明确确认"}
    draft = dict(core, promotion_id="PROM-" + sha256(core)[:20])
    store.save_probe_promotion(effect_id=effect_id, row_hash=row_hash,
                               actor_id=actor_id, draft=draft)
    return draft


def record_reflection(*, store: ControlStore, broker: Any, effect_id: str,
                      payload: dict[str, Any], research_memory_path: Path) -> dict[str, Any]:
    exact = strict_object(payload, required={"round_id", "reflection"})
    round_id = exact["round_id"]; reflection = exact["reflection"]
    if (not isinstance(round_id, str) or not isinstance(reflection, str)
            or not reflection.strip() or len(reflection.encode("utf-8")) > 64 * 1024):
        raise ContractError("reflection_invalid", "反思内容不合法")
    if not any(row["round_id"] == round_id for row in store.rows("round_reports")):
        raise ContractError("round_report_unavailable", "轮报告尚不可用，不能悬空记录反思")
    actor_id = _actor_id(store, effect_id)
    reflection_id = "REFL-" + sha256({"round_id": round_id, "actor_id": actor_id,
                                       "text": reflection})[:24]
    memory = ResearchMemory(Path(research_memory_path), owner_uid=os.geteuid())
    row = _append_once(memory, event_type="human_reflection", subject_id=round_id,
                       actor_id=actor_id,
                       payload={"reflection_id": reflection_id, "text": reflection,
                                "auto_start_new_goal": False},
                       identity_key="reflection_id", identity_value=reflection_id)
    seal = _seal(memory, broker, "RM-REFL-" + reflection_id[:32], row["entry_hash"])
    stored = store.record_human_reflection(round_id=round_id, actor_id=actor_id,
                                           reflection_text=reflection)
    if stored != reflection_id:
        raise StoreError("reflection identity drift")
    return {"reflection_id": reflection_id, "round_id": round_id,
            "research_memory_entry_hash": row["entry_hash"],
            "research_seal_receipt_id": seal.get("receipt_id"),
            "auto_started_goal": False}
