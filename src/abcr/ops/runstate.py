"""abcr.ops.runstate — run 断点续跑对账层（item 级）。

架构位置：Operator(B) 的恢复中枢。dispatch 崩溃/被杀后，重跑同一命令即从
未完成 item 继续（幂等续跑）；watchdog 靠本模块状态文件做停摆检测。
移植自 V2 resumable.py 模式（flock+uuid-tmp 原子写为 B2 竞态修复范式，勿简化）。
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from abcr.common.constants import STATE_DIR_DEFAULT

STATUS_RUNNING = "running"
STATUS_SUSPENDED = "suspended"
STATUS_DONE = "done"

# scan_orphans 存活性判定：pid 不存活 且 心跳陈旧超本阈值才判孤儿。
# 若 pid 不可确证死亡但心跳仍新鲜（< 阈值），fail-safe 不误杀活 run（F-OPS-01 修复）。
ORPHAN_HEARTBEAT_GRACE_S_DEFAULT = 900.0


def _orphan_grace_s() -> float:
    try:
        return float(os.environ.get("ABCR_ORPHAN_GRACE_S", ORPHAN_HEARTBEAT_GRACE_S_DEFAULT))
    except (TypeError, ValueError):
        return ORPHAN_HEARTBEAT_GRACE_S_DEFAULT


def _pid_alive(pid: object) -> bool:
    """PID 存活性探测。非法/缺失 pid → 视为不存活（无法证明存活）。
    PermissionError（进程存在但非本用户）→ 存活。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _age_s(iso_ts: object) -> float | None:
    if not isinstance(iso_ts, str) or not iso_ts:
        return None
    try:
        t = datetime.fromisoformat(iso_ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except ValueError:
        return None


def runs_dir() -> Path:
    """状态根调用时读 env（AMENDMENT-38：禁 import 时快照 ABCR_STATE_DIR）。"""
    return Path(os.environ.get("ABCR_STATE_DIR", STATE_DIR_DEFAULT)) / "runs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(run_id: str) -> Path:
    d = runs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{run_id}.json"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(".json.lock")


def _write_locked(path: Path, record: dict) -> None:
    """写 tmp+replace。调用方必须已持有 <path>.json.lock 的 LOCK_EX（RMW 已在锁内）。
    tmp 用 pid+uuid 唯一后缀防并发 rename 互踩。"""
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{uuid.uuid4().hex}.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_unlocked(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _update(run_id: str, mutate) -> dict | None:
    """把 load→改→write 整个 read-modify-write 纳入同一把 LOCK_EX，真正串行化并发写
    （F-OPS-02 修复：旧实现 load() 在写锁外，跨进程零互斥，并发丢写）。
    mutate(rec_or_None) 返回新记录则落盘并返回；返回 None 则不写、返回 None。
    锁文件独立、不随数据文件被 rename 替换，故跨进程有效。"""
    path = _path(run_id)
    with open(_lock_path(path), "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rec = _read_unlocked(path)          # 锁内新鲜读
        new = mutate(rec)
        if new is None:
            return None
        _write_locked(path, new)            # 锁内写：全程串行
        return new


def _write_atomic(path: Path, record: dict) -> None:
    """兼容保留：无条件覆盖写（自持锁）。RMW 路径请改用 _update 以纳入锁内新鲜读。"""
    with open(_lock_path(path), "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _write_locked(path, record)


def load(run_id: str) -> dict | None:
    p = _path(run_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        return json.load(f)


def register_run(run_id: str, item_ids: list[str], meta: dict | None = None) -> dict:
    """run 启动即登记（在真正开跑之前调用——崩溃后磁盘上仍有续跑句柄）。
    已存在同 run_id 则视为续跑：保留 items 进度，只回置 running + resume_count+1。"""
    def mutate(rec: dict | None) -> dict:
        if rec is not None:
            rec.update(status=STATUS_RUNNING, pid=os.getpid(), updated_at=_now())
            rec["resume_count"] = int(rec.get("resume_count", 0)) + 1
            return rec
        return {
            "run_id": run_id,
            "status": STATUS_RUNNING,
            "items": {i: "pending" for i in item_ids},
            "meta": meta or {},
            "reason": "",
            "pid": os.getpid(),
            "created_at": _now(),
            "updated_at": _now(),
            "resume_count": 0,
        }

    return _update(run_id, mutate)  # type: ignore[return-value]


def pending_items(run_id: str) -> list[str]:
    rec = load(run_id) or {}
    return [k for k, v in (rec.get("items") or {}).items() if v != "done"]


def mark_item_done(run_id: str, item_id: str) -> None:
    """单 item 完成即落盘——这是断点的最小粒度。幂等：重复标 done 无副作用。
    load→改→write 全程在 _update 的 LOCK_EX 内串行（F-OPS-02）。"""
    def mutate(rec: dict | None) -> dict | None:
        if rec is None:
            return None
        rec.setdefault("items", {})[item_id] = "done"
        rec["updated_at"] = _now()
        if rec["items"] and all(v == "done" for v in rec["items"].values()):
            rec["status"] = STATUS_DONE
        return rec

    _update(run_id, mutate)


def mark_suspended(run_id: str, reason: str) -> None:
    def mutate(rec: dict | None) -> dict | None:
        if rec is None:
            return None
        rec.update(status=STATUS_SUSPENDED, reason=reason, updated_at=_now())
        return rec

    _update(run_id, mutate)


def scan_orphans() -> list[dict]:
    """进程启动/重启时调用：把「执行进程已消失」的残留 running 记录转 suspended。
    F-OPS-01 修复：先做存活性检查——pid 仍存活的 run 绝不误杀；pid 无法证明死亡但
    心跳仍新鲜（< ORPHAN grace）的也 fail-safe 保留（可能是并发启动的活 run）。
    只有 pid 确证不存活 且 心跳陈旧 才判孤儿。"""
    out: list[dict] = []
    runs = runs_dir()
    if not runs.is_dir():
        return out
    grace = _orphan_grace_s()
    for p in runs.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("status") != STATUS_RUNNING:
            continue
        if _pid_alive(rec.get("pid")):
            continue  # 执行进程仍在跑 → 不是孤儿，绝不误杀
        age = _age_s(rec.get("updated_at"))
        if age is not None and age < grace:
            continue  # 心跳新鲜、pid 未证死 → fail-safe 不误杀（交 watchdog 判 STALLED）
        rid = rec.get("run_id")
        if not rid:
            continue
        mark_suspended(rid, "进程重启，执行进程已消失（孤儿恢复：PID 不存活且心跳陈旧）")
        out.append(rec)
    return out


def can_resume(run_id: str, max_resume: int = 5, cooldown_s: float = 60.0) -> tuple[bool, str]:
    """自动续跑守卫：毒丸上限 + 冷却；任何异常 fail-closed 返回 False。"""
    try:
        rec = load(run_id)
        if rec is None:
            return False, "无此 run 记录"
        if rec.get("status") != STATUS_SUSPENDED:
            return False, f"状态为 {rec.get('status')}，非 suspended"
        n = int(rec.get("resume_count", 0))
        if n >= max_resume:
            return False, f"续跑次数 {n} >= {max_resume}（毒丸上限），需人工介入"
        if n > 0 and rec.get("updated_at"):
            gap = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(rec["updated_at"])).total_seconds()
            if gap < cooldown_s:
                return False, f"距上次续跑仅 {gap:.0f}s（冷却中）"
        return True, "ok"
    except Exception as e:
        return False, f"can_resume 守卫异常: {e}"
