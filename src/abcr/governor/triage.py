"""abcr.governor.triage —— 异常分诊 v0（零 LLM，例外驱动排版；契约 §C1-5）。

架构位置：包C·Governor 呈现侧。读账本（只读，经 ledgerio.read_chain_merged 含云链段）
→ 规则分桶 → 异常摘要 MD。正常合计一行；篇幅全给偏差/失败/待决。

severity 三级映射（AMENDMENT-31）：
  A = 预算(budget_alert/实耗≥85%) / 污染(QUARANTINED) / 冻结区违规 / 停摆 / 云实例空转
  B = 失败未收敛 / 审计不一致 / TTL 超时
  C = 其余（待决 / 已收敛偏差 等）
MD 尾部输出「今日 A+B 告警数 N/3」（A+B 合计每日 ≤3 为健康线）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from abcr.report import ledgerio

# TTL 表（秒，§3.3；env 可覆盖，此处用冻结缺省）
TTL_QUEUED = 3600
TTL_HEARTBEAT = 1800
TTL_COMPLETED_TO_SCORED = 7200
TTL_SCORED_TO_AUDITED = 7200
W1_TOTAL_BUDGET_CNY = 150.0
BUDGET_ALERT_RATIO = 0.85


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)   # K6：naive 按 UTC 补
    return t


def _age_s(ts: str | None, now: datetime) -> float | None:
    t = _parse_ts(ts)
    if t is None:
        return None
    return (now - t).total_seconds()


def triage(ledger_dir: Path = Path("ledger"),
           envdir: Path = Path("configs/envelopes"),
           alerts_dir: Path = Path("state/alerts"),
           now: datetime | None = None) -> dict:
    """分桶。返回 {bucket_name: [entry,...]}，entry = {subject_id, severity, evidence}。"""
    now = now or datetime.now(timezone.utc)
    ledger_dir = Path(ledger_dir)

    runs = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "runs_index"), ledgerio.RUN_EVENT_STATE)
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    costs = ledgerio.read_chain_merged(ledger_dir, "costs")
    instances = ledgerio.read_chain_merged(ledger_dir, "instances")

    buckets: dict[str, list] = {
        "A级紧急": [], "失败未收敛": [], "停摆": [], "TTL超时": [],
        "待决": [], "已收敛偏差": [], "正常": [],
    }

    # ---- A 级：预算 / 污染 / 告警文件 / dispatch 拒绝 / 云实例空转 ----
    spent = sum(float(ev.get("amount_cny", 0) or 0)
                for ev in costs if ev.get("event") == "run_cost_actual"
                and isinstance(ev.get("amount_cny"), (int, float))
                and not isinstance(ev.get("amount_cny"), bool))
    for ev in costs:
        if ev.get("event") == "budget_alert":
            buckets["A级紧急"].append({"subject_id": ev.get("subject_id", "?"),
                                       "severity": "A",
                                       "evidence": f"budget_alert @ {ev.get('ts')}"})
    if spent >= BUDGET_ALERT_RATIO * W1_TOTAL_BUDGET_CNY:
        buckets["A级紧急"].append({"subject_id": "W1", "severity": "A",
                                   "evidence": f"实耗 {spent:.2f} ≥ 85%×150={BUDGET_ALERT_RATIO * 150:.1f}"})
    for ev in instances:
        if ev.get("event") == "instance_idle_alert":
            buckets["A级紧急"].append({"subject_id": ev.get("subject_id") or ev.get("instance_id", "?"),
                                       "severity": "A",
                                       "evidence": f"instance_idle_alert @ {ev.get('ts')}"})
    for bid, rec in batches.items():
        if any(e.get("event") == "batch_dispatch_rejected" for e in rec["events"]):
            evd = next(e for e in rec["events"] if e.get("event") == "batch_dispatch_rejected")
            buckets["A级紧急"].append({"subject_id": bid, "severity": "A",
                                       "evidence": f"batch_dispatch_rejected 原因={evd.get('reason', '?')} @ {evd.get('ts')}"})
    alerts_dir = Path(alerts_dir)
    if alerts_dir.exists():
        for af in sorted(alerts_dir.glob("*.json")):
            try:
                a = json.loads(af.read_text(encoding="utf-8"))
            except Exception:
                buckets["A级紧急"].append({"subject_id": af.name, "severity": "A",
                                           "evidence": "告警文件损坏（按 A 级留证）"})
                continue
            sev = a.get("severity", "A")
            entry = {"subject_id": a.get("subject_id", af.name), "severity": sev,
                     "evidence": f"alert[{a.get('kind', '?')}] {a.get('reason', '')} @ {a.get('ts', af.name)}"}
            buckets["A级紧急" if sev == "A" else ("TTL超时" if sev == "B" else "待决")].append(entry)

    # ---- run 级分桶 ----
    for rid, rec in runs.items():
        state = rec["state"]
        chain_events = {e.get("event") for e in rec["events"]}
        had_failed = "run_failed" in chain_events
        if state == "QUARANTINED":
            buckets["A级紧急"].append({"subject_id": rid, "severity": "A",
                                       "evidence": f"现态 QUARANTINED @ {rec['last_ts']}"})
            continue
        if state == "FAILED":
            fail_ev = next((e for e in reversed(rec["events"]) if e.get("event") == "run_failed"), {})
            buckets["失败未收敛"].append({"subject_id": rid, "severity": "B",
                                          "evidence": f"现态 FAILED；失败事件 @ {fail_ev.get('ts')}；链 {sorted(chain_events)}"})
            continue
        if state == "RUNNING":
            ref = max([t for t in (rec["last_progress_ts"], rec["last_ts"]) if t], default=None)
            age = _age_s(ref, now)
            if age is not None and age > TTL_HEARTBEAT:
                buckets["停摆"].append({"subject_id": rid, "severity": "A",
                                        "evidence": f"RUNNING 无心跳 {age:.0f}s > {TTL_HEARTBEAT}s（末 step/事件 @ {ref}）"})
                continue
        # TTL 超时
        age_last = _age_s(rec["last_ts"], now)
        if state == "QUEUED" and age_last and age_last > TTL_QUEUED:
            buckets["TTL超时"].append({"subject_id": rid, "severity": "B",
                                       "evidence": f"QUEUED {age_last:.0f}s > {TTL_QUEUED}s @ {rec['last_ts']}"})
            continue
        if state == "COMPLETED" and age_last and age_last > TTL_COMPLETED_TO_SCORED:
            buckets["TTL超时"].append({"subject_id": rid, "severity": "B",
                                       "evidence": f"COMPLETED 未 SCORED {age_last:.0f}s > {TTL_COMPLETED_TO_SCORED}s"})
            continue
        if state == "SCORED" and age_last and age_last > TTL_SCORED_TO_AUDITED:
            buckets["TTL超时"].append({"subject_id": rid, "severity": "B",
                                       "evidence": f"SCORED 未 AUDITED {age_last:.0f}s > {TTL_SCORED_TO_AUDITED}s"})
            continue
        # 已收敛偏差：链中出现过 run_failed 但现态已收敛
        if had_failed and state in {"COMPLETED", "SCORED", "AUDITED", "ACCEPTED"}:
            buckets["已收敛偏差"].append({"subject_id": rid, "severity": "C",
                                          "evidence": f"曾 run_failed，现态 {state}（断点续跑成功）"})
            continue
        # 正常
        buckets["正常"].append({"subject_id": rid, "severity": None,
                                "evidence": f"现态 {state}"})

    # ---- 待决：批次 SETTLED未AUDITED / AUDITED未REPORTED + 待批信封 ----
    for bid, rec in batches.items():
        if rec["state"] == "SETTLED":
            buckets["待决"].append({"subject_id": bid, "severity": "C",
                                    "evidence": "批次 SETTLED 未 AUDITED（待 A 审计）"})
        elif rec["state"] == "AUDITED":
            buckets["待决"].append({"subject_id": bid, "severity": "C",
                                    "evidence": "批次 AUDITED 未 REPORTED（待出报告）"})
    envdir = Path(envdir)
    if envdir.exists():
        for p in sorted(envdir.glob("*.json")):
            if p.name.endswith(".reject.json") or p.with_suffix(".reject.json").exists():
                continue
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if "approval" not in env:
                buckets["待决"].append({"subject_id": env.get("batch_id", p.name), "severity": "C",
                                        "evidence": f"待批信封 DRAFT: {p.name}"})
    return buckets


def ab_alert_count(buckets: dict) -> int:
    """今日 A+B 告警数：所有条目中 severity ∈ {A,B} 计数。"""
    return sum(1 for entries in buckets.values() for e in entries if e.get("severity") in ("A", "B"))


def render_md(buckets: dict, now: datetime) -> str:
    date = now.strftime("%Y-%m-%d")
    lines = [f"# 异常分诊 {date}",
             f"> 生成于 {now.isoformat(timespec='seconds')}；exploratory / rig-validation。", ""]
    order = ["A级紧急", "失败未收敛", "停摆", "TTL超时", "待决", "已收敛偏差"]
    for name in order:
        entries = buckets.get(name, [])
        if not entries:
            continue
        lines.append(f"## {name}（{len(entries)}）")
        for e in entries:
            sev = f"[{e['severity']}] " if e.get("severity") else ""
            lines.append(f"- {sev}`{e['subject_id']}` — {e['evidence']}")
        lines.append("")
    # 正常桶：合计一行
    normal = buckets.get("正常", [])
    from collections import Counter
    states = Counter(e["evidence"].replace("现态 ", "") for e in normal)
    breakdown = " / ".join(f"{k} {v}" for k, v in sorted(states.items())) if states else ""
    lines.append(f"## 正常")
    lines.append(f"- 正常 run {len(normal)} 个" + (f"（{breakdown}）" if breakdown else ""))
    lines.append("")
    # 尾部告警计数行
    n = ab_alert_count(buckets)
    lines.append(f"---")
    lines.append(f"**今日 A+B 告警数 {n}/3**"
                 + ("（⚠ 超健康线，次日 sync morning 应置顶「告警系统降敏待决」）" if n > 3 else ""))
    return "\n".join(lines) + "\n"


def run(ledger_dir: Path, out_dir: Path, now: datetime | None = None,
        envdir: Path = Path("configs/envelopes"),
        alerts_dir: Path = Path("state/alerts")) -> Path:
    now = now or datetime.now(timezone.utc)
    buckets = triage(ledger_dir, envdir, alerts_dir, now)
    md = render_md(buckets, now)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"triage-{now.strftime('%Y-%m-%d')}.md"
    out.write_text(md, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="triage", description="ABCR 异常分诊 v0")
    ap.add_argument("--ledger-dir", default="ledger")
    ap.add_argument("--out", default="reports/")
    ap.add_argument("--now", default=None, help="UTC ISO（测试注入）")
    ap.add_argument("--envdir", default="configs/envelopes")
    ap.add_argument("--alerts-dir", default="state/alerts")
    args = ap.parse_args()
    now = _parse_ts(args.now) if args.now else None
    out = run(Path(args.ledger_dir), Path(args.out), now,
              Path(args.envdir), Path(args.alerts_dir))
    print(f"已生成: {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
