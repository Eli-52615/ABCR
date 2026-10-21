"""abcr.audit.budget_recon —— 成本对账 + ¥150/85% 熔断告警（审计项6，A2-3+A2-4）。

架构位置：包A·验船师侧。两职责：
1. **审计项6 · 成本对账**（reconcile_batch，只读）：逐 run join costs 链的
   run_cost_estimated / run_cost_actual（键 subject_id），|actual−estimated|/estimated ≥ 10%
   = 该 run FAIL；批内任何 run 缺 run_cost_actual = FAIL（跑了没记账）；instances 链每个
   instance_started 须有配对 instance_stopped，缺配对且距 started 超 1h = FAIL。
2. **预算熔断**（check_fuse，A 是 budget_alert 唯一写者）：∑run_cost_actual +（进行中实例
   时价×已运行小时）≥ 85%（¥127.5，cap ¥150）→ budget_alert 入账 + 告警文件 + 24h 冷却去重。
   熔断是告警不是拦截——停批决定在人；职责是让超线不可能无声。

payload 键名已裁决（AMENDMENT-9）：costs 事件 {subject_id, amount_cny, basis}（run 级另带
batch_id）；instances 事件 {instance_id, vendor, spec, price_cny_per_h, batch_id}。budget_alert
payload = {total_cny, cap_cny, ratio, actor}（本卡定义，A 唯一写者）。云链段合并只读（AMENDMENT-2）；
演练隔离（AMENDMENT-17）：repo_root 指向隔离 root 即可，节流/告警文件随之隔离。

契约出处：工程包A §6·A2-3/A2-4 骨架逐字移植 + §8.2 R2-A8/A9。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from abcr.audit.report import AuditItem

DEVIATION_MAX = 0.10          # 审计项6 判据：预估 vs 实耗偏差 <10%
ALERT_COOLDOWN_S = 86400.0
IDLE_INSTANCE_MAX_S = 3600.0  # started 无 stopped 超 1h = 空转违约


def budget_cap_cny() -> float:
    """函数内读 env（照 A1-3 ttl_seconds() 写法）——模块导入期读会让测试的
    env 覆盖/monkeypatch 失效。"""
    return float(os.environ.get("ABCR_BUDGET_CAP_CNY", "150"))


def fuse_ratio() -> float:
    return float(os.environ.get("ABCR_BUDGET_FUSE_RATIO", "0.85"))


def _read_chain(repo_root: Path, chain: str) -> list[dict]:
    """装载主链 + 云链段（AMENDMENT-2：ledger/cloud-day<N>/ 各文件自成一链，
    verify 按段独立、读取合并只读）。"""
    paths = [Path(repo_root) / "ledger" / f"{chain}.jsonl"]
    paths += sorted(Path(repo_root, "ledger").glob(f"cloud-day*/{chain}.jsonl"))
    out: list[dict] = []
    for p in paths:
        if p.exists():
            out.extend(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
                       if l.strip())
    return out


def total_actual_cny(repo_root: Path) -> float:
    return sum(float(e.get("amount_cny", 0.0)) for e in _read_chain(repo_root, "costs")
               if e.get("event") == "run_cost_actual")


def _parse_ts(v) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def effective_started_at(ev: dict, now: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[str]]:
    """一条 instance_started 的**有效**开机时刻 + 篡改说明。

    根因②/③：``payload.started_at`` 是显式开放的注入面（"演练注入用"），而链上 ``ts``
    是 append 时写入并挂进哈希链的字段。原实现无条件 ``started_at or ts``，于是
    把 started_at 写成**未来**时间即可让 (now − started) 变负 → max(...,0) 归零 →
    估价 ¥0 且空转时长 <1h → 既不计费也不判违约。实测击穿：started_at=now+10h
    → reconcile PASS、running_estimate ¥0。

    规则（fail-closed 方向恒取更早、更贵的那个）：
      · started_at 缺失/非法 → 用链上 ts；
      · started_at 晚于链上 ts（含未来时间戳）→ 视为篡改，回退链上 ts 并上报；
      · 有效时刻仍晚于 now（链上 ts 本身在未来）→ 篡改，钳到 now 并上报。
    """
    now = now or datetime.now(timezone.utc)
    chain_ts = _parse_ts(ev.get("ts"))
    claimed = _parse_ts(ev.get("started_at"))
    iid = ev.get("subject_id")
    tamper = None
    started = claimed or chain_ts
    if claimed is not None and chain_ts is not None and claimed > chain_ts:
        started = chain_ts
        tamper = (f"instance {iid}: payload.started_at={ev.get('started_at')} 晚于挂链 ts="
                  f"{ev.get('ts')}（未来/超前时间戳 → 计量被抹零），已回退链上 ts")
    if started is not None and started > now:
        started = now
        tamper = (f"instance {iid}: 有效开机时刻 {started.isoformat()} 位于未来"
                  f"（时间戳篡改），已钳到当前时刻")
    return started, tamper


def _unpaired_starts(inst: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """每个 subject 的**最早**未配对 instance_started + 配对异常说明。

    根因④/伪心跳：原实现 ``started = {subject_id: ts}`` 字典 last-write-win，重复调
    start（"心跳"）每次都把开机时刻刷新成现在，空转钟永远归零，1h 空转违约判据形同虚设。
    实测击穿：5h 未关机的实例 reconcile=FAIL，再调一次 start 后立刻变 PASS。
    这里改成按事件顺序配对，未配对段取**最早**那条；start 次数超过 stop 次数 +1
    （即存在"开了又开"）另行上报为配对违约。
    """
    starts: dict[str, list[dict]] = {}
    stops: dict[str, int] = {}
    for e in inst:
        sid = e.get("subject_id")
        if e.get("event") == "instance_started":
            starts.setdefault(sid, []).append(e)
        elif e.get("event") == "instance_stopped":
            stops[sid] = stops.get(sid, 0) + 1
    unpaired: dict[str, dict] = {}
    issues: list[str] = []
    for sid, evs in starts.items():
        n_stop = stops.get(sid, 0)
        if n_stop >= len(evs):
            continue
        rest = evs[n_stop:]
        if len(rest) > 1:
            issues.append(f"instance {sid}: {len(rest)} 条未配对 instance_started"
                          f"（重复开机/伪心跳——重调 start 不得重置空转钟）")
        unpaired[sid] = rest[0]          # 最早那条为准
    return unpaired, issues


def running_estimate_cny(repo_root: Path) -> float:
    """进行中实例估计（AMENDMENT-28②）：instances 链未配对 started 者，
    按 payload.price_cny_per_h（AMENDMENT-9 键名）× 已运行小时累加。
    开机时刻经 effective_started_at 净化（未来时间戳不得把估价抹成 ¥0），
    未配对段取最早那条（重复 start 不得重置计时）。"""
    inst = _read_chain(repo_root, "instances")
    now = datetime.now(timezone.utc)
    unpaired, _ = _unpaired_starts(inst)
    total = 0.0
    for e in unpaired.values():
        started, _tamper = effective_started_at(e, now)
        if started is None:
            continue
        hours = max((now - started).total_seconds(), 0.0) / 3600.0
        total += float(e.get("price_cny_per_h", 0.0)) * hours
    return total


def reconcile_batch(repo_root: Path, batch_id: str) -> dict:
    """审计项6：逐 run 预估/实耗偏差 + 实例开关机配对。返回结构化结果供 AuditReport。"""
    costs = _read_chain(repo_root, "costs")
    est = {e["subject_id"]: float(e["amount_cny"]) for e in costs
           if e.get("event") == "run_cost_estimated" and e.get("batch_id") == batch_id}
    act = {e["subject_id"]: float(e["amount_cny"]) for e in costs
           if e.get("event") == "run_cost_actual" and e.get("batch_id") == batch_id}
    fails: list[str] = []
    for rid, e_v in est.items():
        if rid not in act:
            fails.append(f"{rid}: 有预估无实耗（跑了没记账）")
        elif e_v > 0 and abs(act[rid] - e_v) / e_v >= DEVIATION_MAX:
            fails.append(f"{rid}: 偏差 {abs(act[rid]-e_v)/e_v:.1%} ≥ 10%"
                         f"（估 {e_v} 实 {act[rid]}）")
    inst = _read_chain(repo_root, "instances")
    now = datetime.now(timezone.utc)
    unpaired, pairing_issues = _unpaired_starts(inst)
    fails += pairing_issues                       # 重复开机（伪心跳）本身即配对违约
    for iid, ev in unpaired.items():
        started, tamper = effective_started_at(ev, now)
        if tamper:
            fails.append(tamper)
        if started is None:
            fails.append(f"instance {iid}: instance_started 无可解析时间戳（无法对账 → FAIL）")
            continue
        age = (now - started).total_seconds()
        if age > IDLE_INSTANCE_MAX_S:
            fails.append(f"instance {iid}: started 无 stopped 已 {age/3600:.1f}h（完成即关机违约）")

    # 已关机实例：自述实耗 vs 账本计量（价 × 时长）交叉核对——纯自述 ¥0 洗账在这里被抓。
    # 这条判据不依赖 cloud.stop() 是否被走过：直接往账本里 append 一条伪 instance_stopped
    # 也一样对表。计量到手才判，缺价/缺时间戳不臆造。
    fails += _stopped_underreport_fails(inst, now)
    return {"verdict": "FAIL" if fails else "PASS",
            "evidence": fails or ["偏差全部 <10%；实例开关机配对完整"]}


def _stopped_underreport_fails(inst: list[dict], now: datetime) -> list[str]:
    """已配对实例：instance_stopped.amount_cny 显著低于 价×(stop−start) 即判 FAIL。

    根因③（验船师问运动员）：原实现只看"有没有配对"，从不问"报的钱对不对"，
    于是 amount_cny=0.0 + 编造的 verified_by 就能把一段真实燃烧洗成 ¥0 且配对完整。
    """
    out: list[str] = []
    starts: dict[str, list[dict]] = {}
    stops: dict[str, list[dict]] = {}
    for e in inst:
        sid = e.get("subject_id")
        if e.get("event") == "instance_started":
            starts.setdefault(sid, []).append(e)
        elif e.get("event") == "instance_stopped":
            stops.setdefault(sid, []).append(e)
    for sid, stop_evs in stops.items():
        for i, stop_ev in enumerate(stop_evs):
            if i >= len(starts.get(sid, [])):
                out.append(f"instance {sid}: instance_stopped 无对应 instance_started（凭空关机记账）")
                continue
            start_ev = starts[sid][i]
            started, tamper = effective_started_at(start_ev, now)
            if tamper:
                out.append(tamper)
            price = float(start_ev.get("price_cny_per_h") or 0.0)
            stop_ts = _parse_ts(stop_ev.get("ts"))
            if started is None or stop_ts is None or price <= 0.0:
                continue                                  # 无从计量：不臆造判据
            hours = max((stop_ts - started).total_seconds(), 0.0) / 3600.0
            metered = price * hours
            if metered <= 0.0:
                continue                                  # 零时长计费段：无可对之表
            reported = stop_ev.get("amount_cny")
            if not isinstance(reported, (int, float)) or isinstance(reported, bool):
                out.append(f"instance {sid}: 计量 ¥{metered:.2f} 却缺 amount_cny 数值"
                           f"（自述实耗缺位，缺失≠零成本 → FAIL）")
                continue
            if float(reported) < metered * (1.0 - DEVIATION_MAX):
                out.append(
                    f"instance {sid}: 自述实耗 ¥{float(reported):.2f} 低于账本计量 "
                    f"¥{metered:.2f}（{price}/h × {hours:.3f}h）逾 {DEVIATION_MAX:.0%}"
                    f"——自述（verified={stop_ev.get('verified')!r}）不得冲掉真实计量")
    return out


def check_fuse(repo_root: Path, ledger_append: Callable[..., dict],
               alert_actor: str = "budget_recon") -> Optional[dict]:
    """85% 熔断：超线→ budget_alert 入账 + 告警文件；24h 冷却。ledger_append =
    costs 链 RunLedger.append 的绑定（由调用方注入，走 AMENDMENT-15 flock 写互斥）。
    演练（AMENDMENT-17）：repo_root 指向隔离 root 即可，节流/告警文件随之隔离。"""
    cap = budget_cap_cny()
    total = total_actual_cny(repo_root) + running_estimate_cny(repo_root)  # AMENDMENT-28②
    ratio = total / cap
    if ratio < fuse_ratio():
        return None
    throttle = Path(repo_root) / "state" / "audit" / "budget_alert_throttle.json"
    try:
        last = json.loads(throttle.read_text(encoding="utf-8")).get("ts", 0.0)
    except (OSError, ValueError):
        last = 0.0
    if time.time() - last < ALERT_COOLDOWN_S:
        return None
    payload = {"total_cny": round(total, 2), "cap_cny": cap,
               "ratio": round(ratio, 4), "actor": alert_actor}
    ledger_append("budget_alert", subject_id="W1", **payload)
    alerts = Path(repo_root) / "state" / "audit" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (alerts / f"budget-{ts}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    throttle.parent.mkdir(parents=True, exist_ok=True)
    tmp = throttle.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    tmp.replace(throttle)
    return payload


def budget_recon_item(repo_root: Path, batch_id: str,
                      run_ids: Optional[list[str]] = None) -> AuditItem:
    """审计项6 编排（只读对账）：reconcile_batch + 只读熔断比率呈现（不写账本）。
    熔断写入路径 = check_fuse（由监控/演练3 触发，A 唯一写者，此处只呈现比率不双写）。"""
    repo_root = Path(repo_root)
    res = reconcile_batch(repo_root, batch_id)
    evidence = list(res["evidence"])
    verdict = res["verdict"]
    cap = budget_cap_cny()
    total = total_actual_cny(repo_root) + running_estimate_cny(repo_root)
    ratio = total / cap if cap else 0.0
    # 判据接线（根因④：¥150 硬上限原只在文档/呈现，从不成为 verdict）。累计（实耗 +
    # 进行中实例估计）达到/越过 cap = 预算超线 = 硬 FAIL；不再"只写证据行不判"。
    # 85% 熔断线是告警（check_fuse），越过 cap 才是审计意义上的越界。
    if cap > 0 and total >= cap:
        verdict = "FAIL"
        evidence.append(f"检查FAIL: 累计 ¥{total:.2f} ≥ 预算 cap ¥{cap:.2f}（预算超线，硬判据接线）")
    evidence.append(f"预算比率: 累计 ¥{total:.2f} / cap ¥{cap:.2f} = {ratio:.1%}"
                    f"{'（≥85% 熔断线，见 check_fuse/演练3）' if ratio >= fuse_ratio() else ''}")
    return AuditItem.make(6, verdict, evidence)
