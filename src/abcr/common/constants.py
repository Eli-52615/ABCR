"""abcr.common.constants —— 全项目冻结常量单一来源（契约 §3 逐字固化）。

架构位置：common 层 · fable 维护。三包（A/B/C）一律 `from abcr.common import constants`
复用枚举 / TTL / GENESIS / salt / manipulation 词表，禁止各自重抄一份（双实现必须同定义）。

冻结版（fable 广播 20260715 · AMENDMENT-38）：以窗口 A 的 bootstrap 版（文档 §3 逐字固化）
为基座，并入窗口 B 的 HEARTBEAT_EVERY / LEDGER_CHAINS / STATE_DIR_DEFAULT 与 B 系事件集别名。
TTL 命名 = A 系（状态停留语义）；env 覆盖一律经 statemachine.ttl_seconds() 调用时读，
本模块只存纯字面量（禁止 import 时读 env——防快照失配）。
"""
from __future__ import annotations

# ---- §3.7 哈希协议常量 ----
GENESIS_HASH: str = "0" * 64  # 协议常量：改动即令所有既有链失配
SPLIT_SALT: str = "abcr-w1-v1"  # §3.7 切分 salt（协议常量）

# ---- schema 版本 ----
SCHEMA_VERSION: str = "1.0"
PROTOCOL_REF: str = "W1-V0.9"

# ---- §3.4 steps/scores 枚举 ----
CONDITIONS: frozenset[str] = frozenset({
    "vanilla", "persona_text", "neutral_token", "length_instruct",
    "inject", "ablate", "inject_random", "ablate_random",
    "synthetic_test", "fake"})
STOP_REASONS: frozenset[str] = frozenset({"eos", "max_tokens", "error", "fake"})
TRAJECTORY_STOP_REASONS: frozenset[str] = frozenset({
    "task_done", "budget_exhausted", "max_steps", "error"})
TRAIT_POLES: frozenset[str] = frozenset({"pos", "neg"})
METHODS: frozenset[str] = frozenset({"prompt", "residual_inject", "residual_ablate"})
SAFETY_FLAGS: frozenset[str] = frozenset({
    "parse_fail", "truncated", "empty", "refusal", "repetition"})
METRIC_NAMES: frozenset[str] = frozenset({
    "is_correct", "trait_score", "coherence_score", "fluency_score",
    "output_len_chars", "output_len_tokens", "hedging_rate",
    "self_check_marker_rate", "parse_ok"})
SCORER_IDS: frozenset[str] = frozenset({
    "deterministic_v1", "judge_deepseek_v1", "rescore_v1"})

# ---- §3.2 账本事件词表（枚举冻结；第五链 protocol 系 AMENDMENT-7）----
LEDGER_EVENTS: dict[str, frozenset[str]] = {
    "runs_index": frozenset({
        "run_registered", "run_queued", "run_started", "step_progress",
        "run_paused", "run_resumed", "run_failed", "run_completed",
        "run_scored", "run_audited", "run_accepted", "run_quarantined",
        "run_cancelled"}),
    "batches": frozenset({
        "batch_drafted", "batch_approved", "batch_rejected",
        "batch_dispatch_rejected",           # AMENDMENT-13：dispatch 侧拒绝（B 落账）
        "batch_dispatch_started",
        "batch_settled", "batch_audited", "batch_reported"}),
    "costs": frozenset({"run_cost_estimated", "run_cost_actual", "budget_alert"}),
    "instances": frozenset({
        "instance_registered", "instance_started", "instance_stopped",
        "instance_idle_alert"}),
    "protocol": frozenset({"artifact_frozen", "artifact_superseded"}),  # AMENDMENT-7
}

# ---- §3.3 TTL 表（秒；env 可覆盖，读取见 statemachine.ttl_seconds）----
TTL_QUEUED_S: int = 3600
TTL_RUNNING_HEARTBEAT_S: int = 1800
TTL_COMPLETED_S: int = 7200
TTL_SCORED_S: int = 7200

# ---- 心跳与运行状态根（AMENDMENT-38 并入 B 系常量；纯字面量，env 调用时读）----
HEARTBEAT_EVERY: int = 5            # 契约：每 N=5 item 落 step_progress
STATE_DIR_DEFAULT: str = "state"    # env ABCR_STATE_DIR 由使用方调用时读，勿在 import 时快照

# ---- 账本五链文件名 ----
LEDGER_CHAINS: tuple[str, ...] = (
    "runs_index", "batches", "protocol", "costs", "instances")

# ---- B 系事件集别名（AMENDMENT-38：兼容 B 包既有 import，单一来源仍是 LEDGER_EVENTS）----
RUNS_INDEX_EVENTS = LEDGER_EVENTS["runs_index"]
BATCHES_EVENTS = LEDGER_EVENTS["batches"]
COSTS_EVENTS = LEDGER_EVENTS["costs"]
INSTANCES_EVENTS = LEDGER_EVENTS["instances"]
PROTOCOL_EVENTS = LEDGER_EVENTS["protocol"]

# ---- §A1-5 manipulation-check 词表与句切分符集（AMENDMENT-6/21 冻结）----
HEDGING_WORDS: tuple[str, ...] = (
    "可能", "也许", "或许", "大概", "不确定", "似乎", "恐怕",
    "maybe", "perhaps", "possibly", "might", "not sure")
SELF_CHECK_MARKERS: tuple[str, ...] = (
    "让我检查", "再确认", "验证一下", "复核", "等等，",
    "double-check", "let me verify", "wait,")
SENTENCE_SEPARATORS: str = "。！？!?.；"  # AMENDMENT-21 冻结符集（换行另行处理）
