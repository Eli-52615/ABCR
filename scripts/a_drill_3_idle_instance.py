"""scripts/a_drill_3_idle_instance.py —— 演练3 · 实例空转（预算告警触发，A2-6 / R2-A3/A9）。

单命令可跑，结束打印 `DRILL 3 VERDICT: PASS|FAIL` + 留痕清单。AMENDMENT-17 隔离：**全程在隔离
root 的账本副本上**（真链零写入；instances/costs 人造事件由本脚本在隔离副本内追加——隔离副本非
生产账本，不算越权）；注入 payload 带 actor="drill"；独立节流文件（隔离 root 自带 state/audit/）。

注入：instances 链 instance_registered + instance_started（payload 键 AMENDMENT-9:
subject_id="drill-inst-01", instance_id="drill-inst-01", vendor="drill", spec="drill",
price_cny_per_h=6.0, batch_id=null, actor="drill"；payload.started_at = 2 小时前），不追加
instance_stopped；costs 链人造 run_cost_actual 若干条（actor="drill"）使累计 ≥ ¥128（85% 线）。
期望检测者 = A：budget_recon 空转检查（started 无 stopped 超 1h）+ 85% 熔断。

留痕断言：① 隔离副本 costs 链尾存在 budget_alert 且 payload.ratio ≥ 0.85；② 告警文件存在字段齐；
③ 24h 冷却生效（连调两次，第二次不新增告警）；④ 人造行 actor="drill" 登记 README；
⑤ 真实 ledger/ 链演练前后逐字节不变。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from abcr.audit import budget_recon as br
from abcr.common.ledger_ref import RunLedger
from abcr.sandboxing.drills import harness as H

INST_ID = "drill-inst-01"
BATCH_ID = "B-20260714T090000Z-0001"


def run_drill(repo_root: Path) -> int:
    repo_root = Path(repo_root).resolve()
    iso_root = H.new_iso_root(repo_root, "drill3-idle-instance")
    H.copy_real_ledger(repo_root, iso_root)      # 在真链副本上跑（AMENDMENT-17）
    before = H.real_ledger_digest(repo_root)

    inst = RunLedger(iso_root / "ledger", "instances")
    costs = RunLedger(iso_root / "ledger", "costs")

    # <<< 注入：实例空转（started 2h 前、无 stopped）>>>
    started_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    inst.append("instance_registered", subject_id=INST_ID, instance_id=INST_ID,
                vendor="drill", spec="drill", price_cny_per_h=6.0, batch_id=None, actor="drill")
    inst.append("instance_started", subject_id=INST_ID, instance_id=INST_ID,
                vendor="drill", spec="drill", price_cny_per_h=6.0, batch_id=None,
                started_at=started_at, actor="drill")
    # <<< 注入：人造 run_cost_actual 使累计 ≥ ¥128 >>>
    for i, amt in enumerate((65.0, 65.0)):       # 计 ¥130
        costs.append("run_cost_actual", subject_id=f"drill-run-{i}", batch_id=BATCH_ID,
                     amount_cny=amt, basis="drill", actor="drill")

    checks: list[tuple[str, bool, list[str]]] = []

    # 期望检测者 = A：85% 熔断（check_fuse，repo_root=隔离 root）
    payload = br.check_fuse(iso_root, costs.append)
    alert_evs = [e for e in costs.events() if e.get("event") == "budget_alert"]
    ok1 = (payload is not None and alert_evs and alert_evs[-1].get("ratio", 0) >= 0.85)
    checks.append(("① budget_alert 入隔离 costs 链且 ratio≥0.85", bool(ok1),
                   [f"payload={payload}", f"链尾 budget_alert ratio={alert_evs[-1].get('ratio') if alert_evs else None}"]))

    # ② 告警文件存在且字段齐
    alerts = sorted((iso_root / "state" / "audit" / "alerts").glob("budget-*.json"))
    fields_ok = False
    if alerts:
        af = json.loads(alerts[-1].read_text(encoding="utf-8"))
        fields_ok = all(k in af for k in ("total_cny", "cap_cny", "ratio", "actor"))
    checks.append(("② 告警文件存在且字段齐 (total_cny/cap_cny/ratio/actor)", bool(alerts) and fields_ok,
                   [f"文件={[str(a.name) for a in alerts]}"]))

    # ③ 24h 冷却：连调第二次不新增告警
    payload2 = br.check_fuse(iso_root, costs.append)
    alert_evs2 = [e for e in costs.events() if e.get("event") == "budget_alert"]
    ok3 = payload2 is None and len(alert_evs2) == len(alert_evs)
    checks.append(("③ 24h 冷却生效（第二次不新增告警）", ok3,
                   [f"第二次 payload={payload2}, budget_alert 计数 {len(alert_evs)}→{len(alert_evs2)}"]))

    # ④ reconcile 空转 FAIL 行 + 人造行 actor=drill 可识别
    res = br.reconcile_batch(iso_root, BATCH_ID)
    idle_line = any("started 无 stopped" in e and INST_ID in e for e in res["evidence"])
    drill_tagged = all(e.get("actor") == "drill" for e in inst.events()
                       if e.get("subject_id") == INST_ID)
    checks.append(("④ reconcile 空转 FAIL 行 + 注入行 actor=drill", idle_line and drill_tagged,
                   [f"reconcile={res['verdict']}"] + [e for e in res["evidence"] if INST_ID in e][:2]))

    # ⑤ 真链零写入
    after = H.real_ledger_digest(repo_root)
    ok5 = before == after
    checks.append(("⑤ 真实 ledger 链演练前后逐字节不变", ok5, ["真链未变" if ok5 else "真链被改！"]))

    for name, ok, lines in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for ln in lines:
            print(f"      {ln}")

    passed = all(ok for _, ok, _ in checks)
    return H.finish(3, passed, iso_root,
                    ["ledger/costs.jsonl", "ledger/instances.jsonl",
                     "state/audit/alerts/"],
                    {"drill": "idle_instance_budget_alert", "instance": INST_ID,
                     "injected_actor": "drill", "started_at": started_at,
                     "injected_cost_cny": 130.0,
                     "checks": {n: ok for n, ok, _ in checks}})


def main() -> int:
    ap = argparse.ArgumentParser(description="演练3 实例空转（预算告警）")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    return run_drill(Path(args.repo_root))


if __name__ == "__main__":
    sys.exit(main())
