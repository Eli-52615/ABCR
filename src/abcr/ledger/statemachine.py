"""abcr.ledger.statemachine —— 三层状态机迁移守卫 + TTL 表（契约 §3.3 实现）。

架构位置：包A·裁判侧。纯函数、零 IO。B 的 dispatch/watchdog 在写账本前调
validate_transition 自检；auditor 事后重放事件流用 derive_run_state 复核。
你不驱动状态、不修状态——只提供"什么迁移合法"的唯一裁决函数与"从账本事件流
推导当前状态"的唯一读法。

三条已裁决约定（AMENDMENT-5/16）：
1. 事件词表无 run_rejected——REJECTED 经 run_audited payload {"verdict":"rejected"} 表达，
   derive_run_state 推导出 AUDITED 后由 auditor 读 verdict 细分。
2. 整批 QUARANTINED 落账序 = 批内每 run 先 run_audited(verdict:"quarantined") 再 run_quarantined，
   批次追加 batch_audited(verdict:"quarantined")（批次状态机无 QUARANTINED 态）。
3. 审计豁免迁移：COMPLETED/FAILED/SCORED → AUDITED 均合法；三处置终态只能自 AUDITED 进入。
"""
from __future__ import annotations

import os
from typing import Optional

from abcr.common import constants

# ---- 运行对象 ----
RUN_STATES = frozenset({
    "PLANNED", "QUEUED", "RUNNING", "PAUSED", "FAILED", "COMPLETED",
    "SCORED", "AUDITED", "ACCEPTED", "REJECTED", "QUARANTINED", "CANCELLED"})
RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED":   frozenset({"QUEUED", "CANCELLED"}),
    "QUEUED":    frozenset({"RUNNING", "CANCELLED"}),
    "RUNNING":   frozenset({"PAUSED", "FAILED", "COMPLETED", "CANCELLED"}),
    "PAUSED":    frozenset({"RUNNING", "CANCELLED"}),
    # AMENDMENT-16 审计豁免迁移：COMPLETED/FAILED/SCORED → AUDITED 均合法
    # （审计可介入任何非终态后）；三处置终态只能自 AUDITED 进入。
    "FAILED":    frozenset({"RUNNING", "CANCELLED", "AUDITED"}),   # FAILED 可 RESUME 回 RUNNING
    "COMPLETED": frozenset({"SCORED", "AUDITED"}),
    "SCORED":    frozenset({"AUDITED"}),
    "AUDITED":   frozenset({"ACCEPTED", "REJECTED", "QUARANTINED"}),
    "ACCEPTED":  frozenset(), "REJECTED": frozenset(),
    "QUARANTINED": frozenset(), "CANCELLED": frozenset(),
}
# ---- 批次对象 ----
BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"APPROVED"}), "APPROVED": frozenset({"DISPATCHING"}),
    "DISPATCHING": frozenset({"SETTLED"}), "SETTLED": frozenset({"AUDITED"}),
    "AUDITED": frozenset({"REPORTED"}), "REPORTED": frozenset(),
}
# ---- 协议对象 ----
PROTOCOL_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"REVIEW"}), "REVIEW": frozenset({"FROZEN"}),
    "FROZEN": frozenset({"SUPERSEDED"}), "SUPERSEDED": frozenset(),
}   # AMENDMENT = 新对象从 DRAFT 起，旧对象 FROZEN→SUPERSEDED

_TABLES = {"run": RUN_TRANSITIONS, "batch": BATCH_TRANSITIONS,
           "protocol": PROTOCOL_TRANSITIONS}

# 事件 → 运行状态（runs_index 词表全映射；step_progress 不改状态只刷心跳）
RUN_EVENT_STATE: dict[str, str] = {
    "run_registered": "PLANNED", "run_queued": "QUEUED",
    "run_started": "RUNNING", "run_paused": "PAUSED",
    "run_resumed": "RUNNING", "run_failed": "FAILED",
    "run_completed": "COMPLETED", "run_scored": "SCORED",
    "run_audited": "AUDITED", "run_accepted": "ACCEPTED",
    "run_quarantined": "QUARANTINED", "run_cancelled": "CANCELLED",
}
BATCH_EVENT_STATE: dict[str, str] = {
    "batch_drafted": "DRAFT", "batch_approved": "APPROVED",
    "batch_dispatch_started": "DISPATCHING", "batch_settled": "SETTLED",
    "batch_audited": "AUDITED", "batch_reported": "REPORTED",
    # AMENDMENT-13：batch_rejected（人工驳回，abcrctl 落账）与 batch_dispatch_rejected
    # （dispatch 拒绝，B 落账）只增事件、不增批次状态枚举——两者是不推进状态的标记
    # 事件（批次停在事件发生态：rejected 停在 DRAFT、dispatch_rejected 停在 APPROVED），
    # 驳回细节由 payload 原因码表达；故意不入本映射（状态推导中跳过、不判违规）。
}

# TTL 表（秒；constants.py 为冻结源，env 可覆盖）
def ttl_seconds() -> dict[str, int]:
    return {
        "QUEUED":            int(os.environ.get("ABCR_TTL_QUEUED_S",
                                                str(constants.TTL_QUEUED_S))),
        "RUNNING_HEARTBEAT": int(os.environ.get("ABCR_TTL_RUNNING_HEARTBEAT_S",
                                                str(constants.TTL_RUNNING_HEARTBEAT_S))),
        "COMPLETED":         int(os.environ.get("ABCR_TTL_COMPLETED_S",
                                                str(constants.TTL_COMPLETED_S))),
        "SCORED":            int(os.environ.get("ABCR_TTL_SCORED_S",
                                                str(constants.TTL_SCORED_S))),
    }


class TransitionError(Exception):
    """非法状态迁移（assert_* 薄封装抛出；AMENDMENT-38 增补,B watchdog 调用形态兼容）。"""


def assert_run(cur: str, new: str) -> None:
    ok, why = validate_transition("run", cur, new)
    if not ok:
        raise TransitionError(why)


def assert_batch(cur: str, new: str) -> None:
    ok, why = validate_transition("batch", cur, new)
    if not ok:
        raise TransitionError(why)


def assert_protocol(cur: str, new: str) -> None:
    ok, why = validate_transition("protocol", cur, new)
    if not ok:
        raise TransitionError(why)


def validate_transition(kind: str, cur: str, new: str) -> tuple[bool, str]:
    """迁移合法性唯一裁决。kind ∈ {run, batch, protocol}。不抛异常。"""
    table = _TABLES.get(kind)
    if table is None:
        return False, f"未知对象层 '{kind}'"
    if cur not in table:
        return False, f"未知状态 '{cur}'"
    if new not in table:
        return False, f"未知目标状态 '{new}'"
    if new in table[cur]:
        return True, "ok"
    return False, f"非法迁移 {cur} → {new}（合法目标: {sorted(table[cur]) or '无（终态）'}）"


def derive_run_state(events: list[dict]) -> tuple[Optional[str], list[str]]:
    """从 runs_index 单主体事件序列推导当前状态；顺带复核逐步迁移合法性。
    返回 (当前状态或 None, 违规清单)。auditor 复核入口。"""
    state: Optional[str] = None
    violations: list[str] = []
    for i, ev in enumerate(events):
        name = ev.get("event", "")
        if name == "step_progress":
            if state != "RUNNING":
                violations.append(f"#{i}: step_progress 出现在 {state} 态")
            continue
        target = RUN_EVENT_STATE.get(name)
        if target is None:
            violations.append(f"#{i}: 未知事件 '{name}'")
            continue
        if state is None:
            if target != "PLANNED":
                violations.append(f"#{i}: 首事件应为 run_registered，实为 '{name}'")
            state = target
            continue
        ok, why = validate_transition("run", state, target)
        if not ok:
            violations.append(f"#{i}: {why}")
        state = target
    return state, violations
