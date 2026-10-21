"""Strict goal validation: parse and check, never invent scientific choices."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

from abcr.control.contracts import ContractError, canonical_json, require_id, sha256, strict_object

MAX_GOAL_BYTES = 64 * 1024
READY_TEMPLATES = frozenset({
    "behavior_probe", "persona_control", "component_ablation", "dose_response",
    "robustness", "persona_task_match", "light_agentic", "internal_mediation",
    "confirmation",
})


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueSafeLoader, node: yaml.nodes.MappingNode, deep: bool = False):
    out: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ContractError("non_string_key", "目标书所有键必须是字符串")
        if key in out:
            raise ContractError("duplicate_key", f"目标书包含重复键: {key}")
        out[key] = loader.construct_object(value_node, deep=deep)
    return out


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True)
class Prediction:
    task_family: str
    direction: str
    rationale: str


@dataclass(frozen=True)
class Goal:
    goal_id: str
    title: str
    design_origin: str
    hypothesis: str
    template_id: str
    split: str
    personas: tuple[str, ...]
    arms: tuple[dict[str, Any], ...]
    predictions: tuple[Prediction, ...]
    falsifier: str
    metrics: tuple[str, ...]
    item_count: int
    seeds: tuple[int, ...]
    max_cost_usd: float
    parent_round_id: str | None = None
    decision_rules: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_id(self.goal_id, "goal_id")

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["personas"] = list(self.personas)
        out["arms"] = list(self.arms)
        out["predictions"] = [asdict(p) for p in self.predictions]
        out["metrics"] = list(self.metrics)
        out["seeds"] = list(self.seeds)
        return out

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def goal_hash(self) -> str:
        return sha256(self.canonical_bytes)


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    goal: Goal | None
    defects: tuple[dict[str, Any], ...]


def _load_one(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_GOAL_BYTES:
        raise ContractError("goal_size", f"目标书必须为 1..{MAX_GOAL_BYTES} bytes")
    try:
        for token in yaml.scan(raw.decode("utf-8")):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise ContractError("yaml_indirection_forbidden", "目标书禁止 tag、anchor 和 alias")
        docs = list(yaml.load_all(raw.decode("utf-8"), Loader=_UniqueSafeLoader))
    except ContractError:
        raise
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ContractError("invalid_yaml", f"目标书 YAML 无法解析: {exc}") from exc
    if len(docs) != 1:
        raise ContractError("multi_document", "目标书必须且只能包含一个 YAML document")
    if not isinstance(docs[0], dict):
        raise ContractError("not_object", "目标书顶层必须是 mapping")
    return docs[0]


def validate_goal(raw: bytes, *, ready_templates: frozenset[str] = READY_TEMPLATES) -> ValidationReport:
    try:
        obj = strict_object(
            _load_one(raw),
            required={"goal_id", "title", "design_origin", "hypothesis", "template_id",
                      "split", "personas", "arms", "predictions", "falsifier", "metrics",
                      "item_count", "seeds", "max_cost_usd"},
            optional={"parent_round_id", "decision_rules"},
        )
        defects: list[dict[str, Any]] = []

        def defect(code: str, message: str, field_name: str) -> None:
            defects.append({"code": code, "message": message, "field": field_name})

        if obj["design_origin"] != "human_claude_manual":
            defect("bad_origin", "当前阶段只接收人与 Claude 手工定稿的目标", "design_origin")
        if not isinstance(obj["template_id"], str) or obj["template_id"] not in ready_templates:
            defect("unsupported_template", "模板未登记为 ready", "template_id")
        if obj["split"] != "dev":
            defect("non_dev_split", "探索目标只能使用 dev split", "split")
        for name in ("title", "hypothesis", "falsifier"):
            if not isinstance(obj[name], str) or not obj[name].strip():
                defect("empty_text", "字段必须是非空文字", name)
        if not isinstance(obj["personas"], list) or not obj["personas"] or not all(isinstance(x, str) and x for x in obj["personas"]):
            defect("bad_personas", "personas 必须是非空字符串列表", "personas")
        if not isinstance(obj["arms"], list) or len(obj["arms"]) < 2 or not all(isinstance(x, dict) for x in obj["arms"]):
            defect("bad_arms", "至少需要两个结构化实验臂（含对照）", "arms")
        else:
            arm_ids = [x.get("id") for x in obj["arms"]]
            if (not all(isinstance(x, str) and x for x in arm_ids)
                    or len(set(arm_ids)) != len(arm_ids)
                    or not all(isinstance(x.get("kind"), str) and x.get("kind") for x in obj["arms"])):
                defect("bad_arms", "每个实验臂需有去重 id 和非空 kind", "arms")
            if not any(x.get("kind") in {"vanilla", "control"} for x in obj["arms"]):
                defect("control_arm_missing", "实验臂必须包含 vanilla/control 对照", "arms")
        preds: list[Prediction] = []
        if not isinstance(obj["predictions"], list) or not obj["predictions"]:
            defect("missing_predictions", "至少需要一个逐任务族预测", "predictions")
        else:
            for i, pred in enumerate(obj["predictions"]):
                if not isinstance(pred, dict) or set(pred) != {"task_family", "direction", "rationale"}:
                    defect("bad_prediction", f"预测 {i} 字段不完整", "predictions")
                    continue
                if (not all(isinstance(pred[k], str) and pred[k].strip()
                            for k in ("task_family", "direction", "rationale"))
                        or pred["direction"] not in {"increase", "decrease", "null", "mixed"}):
                    defect("bad_direction", f"预测 {i} 方向不合法", "predictions")
                    continue
                preds.append(Prediction(**pred))
        if (not isinstance(obj["metrics"], list) or not obj["metrics"]
                or not all(isinstance(x, str) and x for x in obj["metrics"])
                or len(set(obj["metrics"])) != len(obj["metrics"])):
            defect("bad_metrics", "metrics 必须是非空字符串列表", "metrics")
        if isinstance(obj["item_count"], bool) or not isinstance(obj["item_count"], int) or not 1 <= obj["item_count"] <= 1000:
            defect("bad_item_count", "item_count 必须为 1..1000", "item_count")
        seeds_well_typed = (isinstance(obj["seeds"], list) and bool(obj["seeds"])
                            and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2**32
                                    for x in obj["seeds"]))
        if not seeds_well_typed or len(set(obj["seeds"])) != len(obj["seeds"]):
            defect("bad_seeds", "seeds 必须是非空、去重的 uint32 列表", "seeds")
        cost = obj["max_cost_usd"]
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not 0 <= float(cost) <= 10000:
            defect("bad_budget", "max_cost_usd 必须为 0..10000 的有限数字", "max_cost_usd")
        rules = obj.get("decision_rules", {})
        if rules and (not isinstance(rules, dict) or set(rules) != {"if_support", "if_refute"}
                      or not all(isinstance(x, str) and x.strip() for x in rules.values())):
            defect("bad_decision_rules", "decision_rules 需包含 if_support 与 if_refute", "decision_rules")
        parent = obj.get("parent_round_id")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            defect("bad_parent_round", "parent_round_id 必须是非空字符串或 null", "parent_round_id")
        if defects:
            return ValidationReport(False, None, tuple(defects))
        goal = Goal(
            goal_id=obj["goal_id"], title=obj["title"].strip(),
            design_origin=obj["design_origin"], hypothesis=obj["hypothesis"].strip(),
            template_id=obj["template_id"], split="dev", personas=tuple(obj["personas"]),
            arms=tuple(obj["arms"]), predictions=tuple(preds), falsifier=obj["falsifier"].strip(),
            metrics=tuple(obj["metrics"]), item_count=obj["item_count"],
            seeds=tuple(obj["seeds"]), max_cost_usd=float(cost),
            parent_round_id=obj.get("parent_round_id"), decision_rules=rules,
        )
        return ValidationReport(True, goal, ())
    except ContractError as exc:
        return ValidationReport(False, None, ({"code": exc.code, "message": exc.message,
                                                "details": exc.details},))


def load_goal(path: Path) -> ValidationReport:
    return validate_goal(Path(path).read_bytes())
