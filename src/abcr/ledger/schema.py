"""abcr.ledger.schema —— 全字段 schema 校验器（冻结契约 §3.4 的守卫实现）。

架构位置：包A·裁判侧。零外部依赖、零 LLM、纯函数（可独立复现）。
消费者：auditor（审计闸）、tests/contract、B/C 写入前自检（可选）。
模式出处：V2 tasklog 范式 = SCHEMA_VERSION 常量 + frozenset 枚举
+ 表驱动必需字段 + 不抛异常的 ValidationResult + int 字段先拒 bool。

枚举/常量一律 from abcr.common import constants（§4.4：constants.py 为冻结单一来源）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from abcr.common import constants  # 枚举/TTL/GENESIS/salt 的冻结单一来源

SCHEMA_VERSION = constants.SCHEMA_VERSION

# —— 枚举取自 constants（冻结单一来源）——
CONDITIONS = constants.CONDITIONS
STOP_REASONS = constants.STOP_REASONS
TRAJECTORY_STOP_REASONS = constants.TRAJECTORY_STOP_REASONS
TRAIT_POLES = constants.TRAIT_POLES
METHODS = constants.METHODS
SAFETY_FLAGS = constants.SAFETY_FLAGS
METRIC_NAMES = constants.METRIC_NAMES
SCORER_IDS = constants.SCORER_IDS
LEDGER_EVENTS = constants.LEDGER_EVENTS


@dataclass
class ValidationResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "PASS"
        return (f"FAIL (缺失: {', '.join(self.missing) or '-'}"
                f" | 异常: {', '.join(self.anomalies) or '-'})")


# (字段名, 允许类型, allow_none) —— 48 行与契约 §3.4 表逐行对应，顺序一致
_Num = (int, float)
_STEP_FIELDS: tuple[tuple[str, Any, bool], ...] = (
    ("schema_version", str, False), ("run_id", str, False),
    ("trajectory_id", str, False), ("step_id", int, False),
    ("parent_run", str, True), ("git_commit", str, False),
    ("model_id", str, False), ("model_revision", str, False),
    ("dtype", str, False), ("quantization", str, True),
    ("device", str, False), ("engine", str, False),
    ("engine_version", str, False), ("torch_version", str, True),
    ("cuda_version", str, True), ("benchmark", str, False),
    ("split_hash", str, False), ("item_id", str, False),
    ("condition", str, False), ("trait", str, True),
    ("trait_pole", str, True), ("method", str, True),
    ("layer", int, True), ("coefficient", _Num, True),
    ("intervention_strength", _Num, True), ("random_seed", int, False),
    ("env_seed", int, True), ("prompt_hash", str, False),
    ("chat_template_hash", str, False), ("config_hash", str, False),
    ("action", str, True), ("obs_hash", str, True),
    ("remaining_budget", _Num, True), ("output_text", str, False),
    ("parsed_answer", str, True), ("is_correct", bool, True),
    ("latency_ms", int, False), ("input_tokens", int, False),
    ("output_tokens", int, False), ("stop_reason", str, False),
    ("trajectory_stop_reason", str, True), ("trait_score", _Num, True),
    ("fluency_score", _Num, True), ("safety_flags", list, False),
    ("activation_summary", str, True), ("state_snapshot_ref", str, True),
    ("protocol_ref", str, False), ("env_lock_ref", str, False),
)

_SCORE_FIELDS: tuple[tuple[str, Any, bool], ...] = (
    ("schema_version", str, False), ("run_id", str, False),
    ("item_id", str, False), ("trajectory_id", str, False),
    ("step_id", int, False), ("condition", str, False),
    ("random_seed", int, False), ("metric_name", str, False),
    # metric_value 可空（AMENDMENT-39：B1-10 judge 数字总概率<0.25 记 None 的语义依据）
    ("metric_value", _Num, True), ("scorer_id", str, False),
    ("scorer_version", str, False), ("scored_at", str, False),
)

# strict 模式下允许出现在记录里的非表内键：整记录挂链通道补的链字段（AMENDMENT-36/39）
_CHAIN_KEYS = frozenset({"prev_hash", "entry_hash"})


def _check_fields(rec: dict, table: tuple, r: ValidationResult,
                  strict: bool = False) -> None:
    """表驱动类型检查。要害：bool 是 int 的子类——数值字段先拒 bool；
    NaN/±Inf 一律拒（K9，AMENDMENT-39）；strict=True 拒未知字段（链字段豁免）。"""
    for name, typ, allow_none in table:
        if name not in rec:
            r.missing.append(name)
            continue
        val = rec[name]
        if val is None:
            if not allow_none:
                r.anomalies.append(f"{name}: 不可为 null")
            continue
        wants_bool = typ is bool
        if not wants_bool and isinstance(val, bool):
            r.anomalies.append(f"{name}: bool 冒充数值/其他类型")
            continue
        if not isinstance(val, typ):
            r.anomalies.append(f"{name}: 类型 {type(val).__name__} 不符")
            continue
        if isinstance(val, float) and (val != val or val in (float("inf"), float("-inf"))):
            r.anomalies.append(f"{name}: NaN/Inf 拒收（K9）")
    if strict:
        known = {name for name, _, _ in table} | _CHAIN_KEYS
        for k in rec:
            if k not in known:
                r.anomalies.append(f"{k}: 未知字段（strict 模式拒收）")


def _finish(r: ValidationResult) -> ValidationResult:
    r.ok = not r.missing and not r.anomalies
    return r


def validate_step(rec: dict, strict: bool = False) -> ValidationResult:
    r = ValidationResult(ok=True)
    _check_fields(rec, _STEP_FIELDS, r, strict=strict)
    if rec.get("schema_version") not in (None,) and rec.get("schema_version") != SCHEMA_VERSION:
        r.anomalies.append("schema_version: 非 '1.0'")
    for f_ in ("step_id", "latency_ms", "input_tokens", "output_tokens"):
        v = rec.get(f_)
        if isinstance(v, int) and not isinstance(v, bool) and v < 0:
            r.anomalies.append(f"{f_}: 负值")
    for f_, enum in (("condition", CONDITIONS), ("stop_reason", STOP_REASONS)):
        v = rec.get(f_)
        if isinstance(v, str) and v not in enum:
            r.anomalies.append(f"{f_}: '{v}' 不在枚举")
    for f_, enum in (("trajectory_stop_reason", TRAJECTORY_STOP_REASONS),
                     ("trait_pole", TRAIT_POLES), ("method", METHODS)):
        v = rec.get(f_)
        if v is not None and isinstance(v, str) and v not in enum:
            r.anomalies.append(f"{f_}: '{v}' 不在枚举")
    flags = rec.get("safety_flags")
    if isinstance(flags, list):
        for x in flags:
            if not isinstance(x, str) or x not in SAFETY_FLAGS:
                r.anomalies.append(f"safety_flags: 非法元素 {x!r}")
    # 交叉一致性（D4 裁定 + 干预臂必填）
    if rec.get("trait_score") is not None:
        r.anomalies.append("trait_score: steps 内恒 null（权威值在 scores.jsonl）")
    if rec.get("fluency_score") is not None:
        r.anomalies.append("fluency_score: steps 内恒 null（权威值在 scores.jsonl）")
    if rec.get("condition") in ("inject", "ablate") and rec.get("trait") is None:
        r.anomalies.append("trait: 干预臂必填")
    # parsed_answer 为 null 时 safety_flags 应含 parse_fail —— 该联动检查归
    # auditor 健康面板（聚合层）承担，schema 层不重复告警。
    return _finish(r)


def validate_score(rec: dict, strict: bool = False) -> ValidationResult:
    r = ValidationResult(ok=True)
    _check_fields(rec, _SCORE_FIELDS, r, strict=strict)
    if rec.get("schema_version") != SCHEMA_VERSION:
        r.anomalies.append("schema_version: 非 '1.0'")
    if isinstance(rec.get("metric_name"), str) and rec["metric_name"] not in METRIC_NAMES:
        r.anomalies.append(f"metric_name: '{rec['metric_name']}' 不在枚举")
    if isinstance(rec.get("scorer_id"), str) and rec["scorer_id"] not in SCORER_IDS:
        r.anomalies.append(f"scorer_id: '{rec['scorer_id']}' 不在枚举")
    if isinstance(rec.get("condition"), str) and rec["condition"] not in CONDITIONS:
        r.anomalies.append(f"condition: '{rec['condition']}' 不在枚举")
    return _finish(r)


def validate_envelope(env: dict) -> ValidationResult:
    """信封结构校验（草案可无 approval；APPROVED 起必须有）。"""
    r = ValidationResult(ok=True)
    for k, typ in (("envelope_version", str), ("batch_id", str), ("protocol_ref", str),
                   ("scope", dict), ("budget", dict), ("deadline_utc", str),
                   ("run_configs", list), ("drafted_by", str)):
        if k not in env:
            r.missing.append(k)
        elif not isinstance(env[k], typ):
            r.anomalies.append(f"{k}: 类型不符")
    scope = env.get("scope") or {}
    for k in ("benchmark_families", "conditions", "splits",
              "item_limit_per_run", "seeds", "trait_whitelist"):
        if k not in scope:
            r.missing.append(f"scope.{k}")
    budget = env.get("budget") or {}
    for k in ("gpu_hours_max", "cost_cap_cny"):
        v = budget.get(k)
        if v is None:
            r.missing.append(f"budget.{k}")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            r.anomalies.append(f"budget.{k}: 须为非负数值")
    bid = env.get("batch_id")
    if isinstance(bid, str):
        import re
        if not re.fullmatch(r"B-\d{8}T\d{6}Z-\d{4}", bid):
            r.anomalies.append("batch_id: 不符 B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>")
    for c in scope.get("conditions", []) or []:
        if c not in CONDITIONS:
            r.anomalies.append(f"scope.conditions: '{c}' 不在枚举")
    return _finish(r)


def validate_ledger_event(chain: str, rec: dict) -> ValidationResult:
    """chain ∈ {runs_index, batches, costs, instances, protocol}。"""
    r = ValidationResult(ok=True)
    if chain not in LEDGER_EVENTS:
        r.anomalies.append(f"未知账本链 '{chain}'")
        return _finish(r)
    for k in ("ts", "run_id", "event", "prev_hash", "entry_hash"):
        if k not in rec:
            r.missing.append(k)
        elif not isinstance(rec[k], str):
            r.anomalies.append(f"{k}: 须为 str")
    ev = rec.get("event")
    if isinstance(ev, str) and ev not in LEDGER_EVENTS[chain]:
        r.anomalies.append(f"event: '{ev}' 不在 {chain} 词表")
    if ev == "step_progress":
        for k in ("steps_done", "items_done"):
            v = rec.get(k)
            if v is None:
                r.missing.append(k)
            elif isinstance(v, bool) or not isinstance(v, int) or v < 0:
                r.anomalies.append(f"{k}: 须为非负 int（拒 bool）")
    return _finish(r)
