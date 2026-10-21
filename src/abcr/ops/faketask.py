"""abcr.ops.faketask — 确定性假任务执行器（契约 §2.12 规格）。

架构位置：Operator(B) 的执行器插槽中 engine=fake 的实现；阶段1 用它打通
信封→队列→执行→评分→审计全链，阶段2 保留作故障演练注入器。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

GOLDEN_PATH = Path("data/golden/golden10.json")
FAIL_ITEMS = frozenset({"g03", "g07"})   # 制造已知错误分布（契约 §2.12）
ITEM_SECONDS = 0.2


def _knob(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def _load_golden() -> dict[str, dict]:
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    return {r["id"]: r for r in items}


def generate(item_id: str) -> str:
    """单 item 确定性输出（无任何随机性；seed 不影响 fake 输出——期望分数才可预生成）。"""
    rec = _load_golden()[item_id]
    return rec["fail_sample"] if item_id in FAIL_ITEMS else rec["pass_sample"]


def run_items(
    item_ids: list[str],
    emit_step: Callable[[str, str], None],
    mark_done: Callable[[str], None],
) -> None:
    """逐 item 执行。emit_step(item_id, output_text) 写 steps.jsonl（由调用方 dispatch 注入，
    含 48 字段组装）；mark_done(item_id) 落 runstate 断点。

    故障旋钮（环境变量，值 = item_id 或 "1"；名称冻结——AMENDMENT-3）：
      ABCR_FAKETASK_CRASH_AT_ITEM   到该 item 时进程即死 os._exit(1)（AMENDMENT-24；崩溃演练→断点续跑）
      ABCR_FAKETASK_HANG_AT_ITEM    到该 item 时永久挂起（停摆演练→watchdog STALLED）
      ABCR_FAKETASK_SKIP_LEDGER_WRITES  =1 时不写 step（伪报完成演练→A 审计拦截）
      ABCR_FAKETASK_EXIT_WITHOUT_DONE   =1 时写完首个 step 后直接 os._exit(0)（幽灵状态演练）
    """
    crash_at = _knob("ABCR_FAKETASK_CRASH_AT_ITEM")
    hang_at = _knob("ABCR_FAKETASK_HANG_AT_ITEM")
    skip_ledger = _knob("ABCR_FAKETASK_SKIP_LEDGER_WRITES")
    exit_wo_done = _knob("ABCR_FAKETASK_EXIT_WITHOUT_DONE")
    for item_id in item_ids:
        if crash_at == item_id:
            print(f"[faketask] injected crash at {item_id}", file=sys.stderr, flush=True)
            os._exit(1)   # 进程即死（AMENDMENT-24）：dispatch 无从捕获——真实崩溃语义，恢复走启动对账
        if hang_at == item_id:
            while True:                      # 停摆：进程活着，工作流死了
                time.sleep(60)
        time.sleep(ITEM_SECONDS)
        out = generate(item_id)
        if not skip_ledger:
            emit_step(item_id, out)
        if exit_wo_done:
            os._exit(0)                      # 不落 done、不 settle——幽灵 RUNNING
        mark_done(item_id)
