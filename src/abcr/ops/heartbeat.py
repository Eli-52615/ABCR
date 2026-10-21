"""abcr.ops.heartbeat — 进度心跳（契约 §2.3：每 N=5 item 落 step_progress）。

架构位置：dispatch/runner 的 run 循环内挂钩；watchdog 与 A 的状态机 TTL
（RUNNING 心跳间隔上限 1800s）都以此事件为"活体证据"。
"""
from __future__ import annotations

from typing import Any, Callable

HEARTBEAT_EVERY = 5   # constants.py 若另有定义以其为准


class Heartbeat:
    def __init__(self, ledger_append: Callable[..., Any], run_id: str,
                 every: int = HEARTBEAT_EVERY, start_items: int = 0) -> None:
        self._append = ledger_append          # 注入 ledger_ref 的 append（runs_index 链）
        self._run_id = run_id
        self._every = every
        # start_items：续跑时预置已完成计数，使 items_done 反映全局进度（AMENDMENT-25 续跑连续性）
        self._items_done = start_items
        self._steps_done = start_items

    def tick(self, steps_in_item: int = 1) -> None:
        """每完成一个 item 调一次。到整 5 即落账。"""
        self._items_done += 1
        self._steps_done += steps_in_item
        if self._items_done % self._every == 0:
            self._append("step_progress", subject_id=self._run_id,   # payload 主体键 = subject_id（AMENDMENT-4）
                         steps_done=self._steps_done, items_done=self._items_done)

    def flush(self) -> None:
        """run 收尾时调：把不足 5 的尾巴也落一条（收尾进度可见）。"""
        if self._items_done % self._every != 0:
            self._append("step_progress", subject_id=self._run_id,
                         steps_done=self._steps_done, items_done=self._items_done)
