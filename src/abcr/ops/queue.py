"""abcr.ops.queue — 目录式运行队列（契约 §2.1 queue/ 归 Operator 读写）。

架构位置：dispatch 与执行器之间的持久化缓冲；同时是并发写账本的串行化闸
（账本哈希链单写者假设靠"同一时刻只有一个 dispatch 进程消费队列"保证）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

QUEUE_ROOT_DEFAULT = Path("queue")
STATES = ("pending", "running", "done", "failed")


def _queue_root() -> Path:
    """队列根调用时读 env（AMENDMENT-38：禁 import 时快照;隔离演练/云日经 ABCR_QUEUE_ROOT 指向沙箱）。
    无 env 时返回默认 queue/——与旧常量字节等价,R1 回归不受影响。"""
    return Path(os.environ.get("ABCR_QUEUE_ROOT", str(QUEUE_ROOT_DEFAULT)))


def init_dirs() -> None:
    for s in STATES:
        (_queue_root() / s).mkdir(parents=True, exist_ok=True)


def enqueue(run_id: str, payload: dict) -> Path:
    """写 tmp 再同目录 rename 发布——读者永远看不到半写文件。幂等：已存在即跳过。"""
    init_dirs()
    dst = _queue_root() / "pending" / f"{run_id}.json"
    if dst.exists() or _in_any_state(run_id):
        return dst
    tmp = _queue_root() / "pending" / f".{run_id}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dst)
    return dst


def _in_any_state(run_id: str) -> bool:
    return any((_queue_root() / s / f"{run_id}.json").exists() for s in STATES)


def claim(run_id: str) -> Path | None:
    """pending→running 原子改名即认领；输家 FileNotFoundError → None。"""
    src = _queue_root() / "pending" / f"{run_id}.json"
    dst = _queue_root() / "running" / f"{run_id}.json"
    try:
        os.rename(src, dst)
        return dst
    except FileNotFoundError:
        return None


def settle(run_id: str, ok: bool) -> Path:
    """running→done|failed。失败重跑路径：failed→pending 用 requeue()。"""
    src = _queue_root() / "running" / f"{run_id}.json"
    dst = _queue_root() / ("done" if ok else "failed") / f"{run_id}.json"
    os.rename(src, dst)
    return dst


def requeue(run_id: str) -> Path:
    src = _queue_root() / "failed" / f"{run_id}.json"
    dst = _queue_root() / "pending" / f"{run_id}.json"
    os.rename(src, dst)
    return dst


def list_state(state: str) -> list[str]:
    d = _queue_root() / state
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def read_payload(run_id: str, state: str) -> dict:
    return json.loads((_queue_root() / state / f"{run_id}.json").read_text(encoding="utf-8"))
