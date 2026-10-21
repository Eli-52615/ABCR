#!/usr/bin/env python3
"""abcr.ops.watchdog — 进度看门狗（零 token 磁盘检测 + 冷却去重 + 只检测不处置）。

架构位置：Operator(B) 的旁路哨兵。与执行进程各自独立读盘，不 import 对方
运行态、不共享节流文件（防"双保险互抵"）。异常只告警，处置权在人/dispatch 重跑。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from abcr.common.constants import STATE_DIR_DEFAULT
from abcr.ledger import statemachine
from abcr.ops.runstate import STATUS_RUNNING, STATUS_SUSPENDED, runs_dir

LEDGER_RUNS = Path("ledger/runs_index.jsonl")
LEDGER_INSTANCES = Path("ledger/instances.jsonl")


# —— 路径全部调用时读 env（AMENDMENT-38：STATE_DIR_DEFAULT 纯字面量，禁 import 时快照）——
def _state_dir() -> Path:
    return Path(os.environ.get("ABCR_STATE_DIR", STATE_DIR_DEFAULT))


def _state_path() -> Path:
    return _state_dir() / "watchdog-dispatched.json"


def _alerts_dir() -> Path:
    return _state_dir() / "alerts"

# 收口事件：出现任一则该 run 不再报任何 TTL
_TERMINAL = frozenset({"run_audited", "run_accepted", "run_quarantined", "run_cancelled"})


# —— 阈值全部运行时读 env（K10 / AMENDMENT-28③）：不改码即可调 ——
def _cooldown_s() -> float:
    return float(os.environ.get("ABCR_WD_COOLDOWN_S", "3600"))


def _stall_s() -> float:
    return float(os.environ.get("ABCR_WD_STALL_S", "900"))


def _fresh_s() -> float:
    return float(os.environ.get("ABCR_WD_FRESH_S", "1800"))


def _idle_s() -> float:
    return float(os.environ.get("ABCR_WD_IDLE_S", "900"))


def _ttl() -> dict[str, float]:
    """TTL 一律经 statemachine.ttl_seconds() 调用时读（AMENDMENT-38：A 系命名，
    状态停留上限语义；B 旧名 ABCR_TTL_HEARTBEAT_S/ABCR_TTL_AUDITED_S 废）。"""
    t = statemachine.ttl_seconds()
    return {
        "queued_s": float(t["QUEUED"]),                 # QUEUED 停留（未 started）
        "heartbeat_s": float(t["RUNNING_HEARTBEAT"]),   # RUNNING 心跳间隔上限
        "completed_s": float(t["COMPLETED"]),           # COMPLETED 停留（未 scored）
        "scored_s": float(t["SCORED"]),                 # SCORED 停留（未 audited）
    }


_CLOCK_SKEW_TOLERANCE_S = 5.0


def _age(iso_ts: str) -> float | None:
    try:
        t = datetime.fromisoformat(iso_ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - t).total_seconds()
        # NF-01: a timestamp meaningfully in the FUTURE is anomalous, not "fresh".
        # A negative age reads as fresh (age <= fresh_s) AND slips past stall
        # detection (age > stall_s is False) — fail-open both ways. Beyond a small
        # clock-skew tolerance, fold a future timestamp to positive magnitude so
        # every threshold check fails closed (treats it as stale/suspicious).
        if age < -_CLOCK_SKEW_TOLERANCE_S:
            return abs(age)
        return age
    except Exception:
        return None


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _recently_dispatched(key: str) -> bool:
    ts = _load_state().get(key)
    return ts is not None and (time.time() - float(ts)) < _cooldown_s()


def _mark(key: str) -> None:
    d = _load_state()
    d[key] = time.time()
    now = time.time()
    d = {k: v for k, v in d.items() if now - float(v) < _cooldown_s() * 3}  # prune 过期
    try:
        state = _state_path()
        state.parent.mkdir(parents=True, exist_ok=True)
        tmp = state.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(state)
    except Exception:
        pass  # 节流落盘失败不阻断——最坏多告警一次，有冷却兜底


def detect_runstate() -> list[dict]:
    """runstate 侧：STALLED（running 但心跳陈旧）/ SUSPENDED_FAIL（新鲜失败挂起）。"""
    out: list[dict] = []
    runs = runs_dir()
    if not runs.is_dir():
        return out
    stall_s, fresh_s = _stall_s(), _fresh_s()
    for p in runs.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            # F-OPS-05 修复：坏 state 文件不再静默吞没（旧实现 continue = fail-OPEN，
            # 恰是最该告警的腐坏态被隐藏）。单坏文件仍不阻断其余检测，但产 A 级告警。
            out.append({"kind": "STATE_CORRUPT", "run_id": p.stem, "severity": "A",
                        "detail": str(e)[:200]})
            continue
        if not isinstance(rec, dict):
            out.append({"kind": "STATE_CORRUPT", "run_id": p.stem, "severity": "A",
                        "detail": "state 文件顶层非对象"})
            continue
        status = rec.get("status")
        age = _age(rec.get("updated_at", ""))
        if age is None:
            # 坏/缺时间戳：running 记录无法判定心跳新鲜度 → fail-closed 告警（宁误报不漏报）。
            if status == STATUS_RUNNING:
                out.append({"kind": "STATE_BAD_TS", "run_id": rec.get("run_id") or p.stem,
                            "severity": "A", "updated_at": rec.get("updated_at")})
            continue
        if status == STATUS_RUNNING and age > stall_s:
            out.append({"kind": "STALLED", "run_id": rec.get("run_id"), "age_s": round(age)})
        elif status == STATUS_SUSPENDED and age <= fresh_s:
            out.append({"kind": "SUSPENDED_FAIL", "run_id": rec.get("run_id"),
                        "reason": rec.get("reason", "")})
    return out


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def detect_ledger_ttl() -> list[dict]:
    """账本侧 TTL 对账（契约 §2.4）：重放 runs_index 事件（run 主体在 payload.subject_id——
    AMENDMENT-4），按 run 聚合最后状态与时间戳，超时产出 TTL_QUEUED / TTL_HEARTBEAT /
    TTL_UNSCORED / TTL_UNAUDITED 异常。收口事件（audited/accepted/quarantined/cancelled）
    出现则该 run 不再报。"""
    out: list[dict] = []
    ttl = _ttl()
    # 按 run 聚合：event→最新 ts；记录是否见过各关键事件
    agg: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for ev in _read_ledger(LEDGER_RUNS):
        rid = ev.get("subject_id")
        if not rid:
            continue
        if rid not in agg:
            agg[rid] = {}
            order.append(rid)
        agg[rid][ev.get("event", "")] = ev.get("ts", "")
    for rid in order:
        ev = agg[rid]
        if any(t in ev for t in _TERMINAL):
            continue
        # RUNNING：有 run_started 无 run_completed → 看最近 step_progress（无则 run_started）
        if "run_started" in ev and "run_completed" not in ev:
            last_hb = ev.get("step_progress") or ev.get("run_started")
            age = _age(last_hb)
            if age is not None and age > ttl["heartbeat_s"]:
                out.append({"kind": "TTL_HEARTBEAT", "run_id": rid, "age_s": round(age)})
            continue
        # QUEUED：有 run_queued 无 run_started
        if "run_queued" in ev and "run_started" not in ev:
            age = _age(ev["run_queued"])
            if age is not None and age > ttl["queued_s"]:
                out.append({"kind": "TTL_QUEUED", "run_id": rid, "age_s": round(age)})
            continue
        # COMPLETED：有 run_completed 无 run_scored（COMPLETED 态停留上限）
        if "run_completed" in ev and "run_scored" not in ev:
            age = _age(ev["run_completed"])
            if age is not None and age > ttl["completed_s"]:
                out.append({"kind": "TTL_UNSCORED", "run_id": rid, "age_s": round(age)})
            continue
        # SCORED：有 run_scored 无 run_audited（SCORED 态停留上限 = ABCR_TTL_SCORED_S，A 义）
        if "run_scored" in ev and "run_audited" not in ev:
            age = _age(ev["run_scored"])
            if age is not None and age > ttl["scored_s"]:
                out.append({"kind": "TTL_UNAUDITED", "run_id": rid, "age_s": round(age)})
            continue
    return out


def detect_instance_idle() -> list[dict]:
    """第三类检测（AMENDMENT-28③，阶段2 B2-8 后实装）。阶段1 无 instances 链：文件不存在返回 []。

    F-OPS-07 修复：旧实现用**全局** running_fresh——任一 run 有新鲜 step_progress
    即 return [] 抹平**所有** live 实例的空转告警（实例A空转、实例B新鲜 → A 被 B
    的新鲜度掩盖，漏报）。改为**按实例判新鲜度**：某实例只有被**归属于它自己**的
    新鲜进展才豁免，绝不被别的实例的新鲜度掩盖。

    归属链（fail-closed）：
      - instance 事件上的 run_id/runs 字段 → 该实例"拥有"的 run；其 step_progress
        新鲜 ⇒ 该实例新鲜。
      - runs_index step_progress 上的 instance_id 字段 → 直接归属到该实例。
      - 一个 live 实例若**无任何可归属的新鲜进展**（无 owned 新鲜 run、无直接 tag），
        无法证明它在推进 ⇒ 判 INSTANCE_IDLE 告警（宁误报不漏报）。
    """
    if not LEDGER_INSTANCES.exists():
        return []
    # started/stopped + 实例→owned run_ids 归属（instance 事件携带 run_id / runs 时建立）
    started: set[str] = set()
    stopped: set[str] = set()
    inst_runs: dict[str, set[str]] = {}
    for ev in _read_ledger(LEDGER_INSTANCES):
        iid = ev.get("subject_id", "")
        e = ev.get("event")
        if e == "instance_started":
            started.add(iid)
        elif e == "instance_stopped":
            stopped.add(iid)
        if iid:
            rid = ev.get("run_id")
            if rid:
                inst_runs.setdefault(iid, set()).add(rid)
            runs = ev.get("runs")
            if isinstance(runs, (list, tuple, set)):
                for r in runs:
                    if r:
                        inst_runs.setdefault(iid, set()).add(r)
    live = started - stopped
    if not live:
        return []
    # 归集新鲜度：按 run（subject_id）与按实例直接 tag（instance_id）两条归属路径。
    idle_s = _idle_s()
    fresh_runs: set[str] = set()
    fresh_instances: set[str] = set()
    for ev in _read_ledger(LEDGER_RUNS):
        if ev.get("event") != "step_progress":
            continue
        age = _age(ev.get("ts", ""))
        if age is None or age >= idle_s:
            continue
        rid = ev.get("subject_id", "")
        if rid:
            fresh_runs.add(rid)
        iid_tag = ev.get("instance_id")
        if iid_tag:
            fresh_instances.add(iid_tag)
    out: list[dict] = []
    for iid in sorted(live):
        # 只有归属于该实例自己的新鲜进展才豁免——绝不被其他实例的新鲜度掩盖。
        if iid in fresh_instances:
            continue
        if inst_runs.get(iid, set()) & fresh_runs:
            continue
        out.append({"kind": "INSTANCE_IDLE", "run_id": iid, "severity": "A"})
    return out


def handle(anomaly: dict, dispatch: bool) -> str:
    key = f"{anomaly['run_id']}:{anomaly['kind']}"
    if _recently_dispatched(key):
        return "skip(冷却中,已报过)"
    if not dispatch:
        return "would_dispatch(dry-run)"
    alerts_dir = _alerts_dir()
    alerts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # F-OPS-06 修复：文件名加 run_id + 唯一后缀，防「不同 run 同类异常同秒互相覆盖」
    # 静默丢一条告警。仍以 <ts>-<kind> 开头、以 .json 结尾（consumer 按内容解析，兼容）。
    subj = re.sub(r"[^A-Za-z0-9._-]", "_", str(anomaly.get("run_id", "") or "nosub"))[:80]
    alert = alerts_dir / f"{ts}-{anomaly['kind']}-{subj}-{uuid.uuid4().hex[:8]}.json"
    record = {"ts": ts, "kind": anomaly["kind"],
              "severity": anomaly.get("severity", "B"),          # A/B/C 三级（AMENDMENT-18）
              "subject_id": anomaly.get("run_id", ""),           # run_id 或 instance_id
              "reason": json.dumps(anomaly, ensure_ascii=False)}
    alert.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[watchdog] ANOMALY {json.dumps(anomaly, ensure_ascii=False)}", flush=True)
    _mark(key)
    return "dispatched"


def main() -> int:
    ap = argparse.ArgumentParser(description="ABCR 进度看门狗（零 token 磁盘检测 + 冷却去重告警）")
    ap.add_argument("--interval", type=float, default=600.0, help="扫描周期秒")
    ap.add_argument("--once", action="store_true", help="只扫一次（smoke/调试）")
    ap.add_argument("--dry-run", action="store_true", help="只检测不告警")
    a = ap.parse_args()
    print(f"[watchdog] 启动：每 {a.interval:.0f}s 扫描 {runs_dir()} dry_run={a.dry_run}", flush=True)
    while True:
        try:
            for anomaly in detect_runstate() + detect_ledger_ttl() + detect_instance_idle():
                action = handle(anomaly, dispatch=not a.dry_run)
                print(f"[watchdog] {anomaly['kind']} run={anomaly['run_id']} → {action}", flush=True)
        except Exception as e:
            print(f"[watchdog] 单轮异常（继续）: {e}", flush=True)  # 单轮崩溃绝不退出循环
        if a.once:
            break
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
