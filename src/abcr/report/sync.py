"""abcr.report.sync —— 四段同步视图（契约 §C1-6）。

架构位置：包C·唯一对外呈现出口。段 ∈ morning/afternoon/evening/urgent。
第一戒律（§1.4）：数据只来自账本/scores 查询（ledgerio + views），禁止自由回忆；
逐数带 run_id。所有统计数字只经 cite()/blind.render_effect() 两个出口。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from abcr.common import evidence_floor
from abcr.governor import triage as triagemod
from abcr.report import blind, ledgerio, views

DISCIPLINE_LINE = "> 数字均为 exploratory / rig-validation；mini 环产出不构成任何假设的证据。"
SEGMENTS = ("morning", "afternoon", "evening", "urgent")
W1_TOTAL_BUDGET_CNY = 150.0
BUDGET_ALERT_RATIO = 0.85   # 85% 熔断线（§C2-6）
CANONICAL_SCORER = "deterministic_v1"   # 效应对比只用规范确定性 scorer（防同 condition 两 scorer 自比）


def cite(value: object, run_id: str) -> str:
    """带源渲染：每个逐 run 统计数字同行注明 run_id（呈现纪律落地）。"""
    return f"{value}（run {run_id}）"


def cite_subject(value: object, subject_id: str) -> str:
    return f"{value}（{subject_id}）"


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _effect_arms(per_condition: list[dict]) -> tuple[dict, dict] | None:
    """从 per_condition 选两臂用于 is_correct 效应对比，fail-closed：
      · 只认规范 scorer（CANONICAL_SCORER）——同一 condition 的两个 scorer 不会被当 A/B；
      · 按 condition 去重（每 condition 取一行）——保证两臂是【不同 condition】；
      · 每臂样本量过 require_substantive——空/零样本臂不参与，绝不误导。
    条件不足（<2 不同 condition 或样本不足）→ None（呈现层据此不出效应块）。"""
    rows = [r for r in per_condition
            if r.get("metric_name") == "is_correct" and r.get("scorer_id") == CANONICAL_SCORER
            and _num(r.get("mean_value"))]
    by_cond: dict[str, dict] = {}
    for r in rows:
        by_cond.setdefault(r.get("condition"), r)
    arms = [r for c, r in by_cond.items() if c is not None]
    if len(arms) < 2:
        return None
    a, b = arms[0], arms[1]
    try:
        evidence_floor.require_substantive(int(a.get("n") or 0), "sync effect arm A")
        evidence_floor.require_substantive(int(b.get("n") or 0), "sync effect arm B")
    except evidence_floor.EvidenceError:
        return None
    return a, b


def _budget_summary(ledger_dir: Path) -> dict:
    """从 costs 链读实耗（§C2-6 ①）：run_cost_estimated / run_cost_actual / budget_alert
    汇总 + 余额 + 85% 熔断线距离；逐 run 实耗带 subject_id。"""
    events = ledgerio.read_chain_merged(ledger_dir, "costs")
    est = actual = 0.0
    alerts = 0
    per_run: list[tuple[str, float]] = []   # (subject_id, actual_amount)
    for e in events:
        ev = e.get("event")
        amt = e.get("amount_cny")
        if ev == "run_cost_estimated" and _num(amt):
            est += float(amt)
        elif ev == "run_cost_actual" and _num(amt):
            actual += float(amt)
            per_run.append((e.get("subject_id", "?"), float(amt)))
        elif ev == "budget_alert":
            alerts += 1
    remaining = W1_TOTAL_BUDGET_CNY - actual
    breaker = BUDGET_ALERT_RATIO * W1_TOTAL_BUDGET_CNY
    return {"est": est, "actual": actual, "alerts": alerts, "remaining": remaining,
            "breaker_line": breaker, "breaker_dist": breaker - actual, "per_run": per_run}


def _spent_cny(ledger_dir: Path) -> float:
    return _budget_summary(ledger_dir)["actual"]


def _non_citable(runs_dir: Path, run_id: str) -> bool:
    """读 data/runs/<rid>/manifest.json 的 non_citable（G7 透传；缺 manifest 保守按 True）。"""
    mp = Path(runs_dir) / run_id / "manifest.json"
    if not mp.exists():
        return True   # Mac 产物一律 non-citable；缺 manifest 时 fail-safe 标注
    try:
        return bool(json.loads(mp.read_text(encoding="utf-8")).get("non_citable", True))
    except Exception:  # noqa: BLE001
        return True


def _instances_lines(ledger_dir: Path) -> list[str]:
    """未 stopped 云实例折叠（§C2-6 ②；空转 idle_alert 标 A 级）。"""
    inst = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "instances"), ledgerio.INSTANCE_EVENT_STATE)
    lines: list[str] = []
    for iid, rec in sorted(inst.items()):
        state = rec["state"] or "?"
        if state == "STOPPED":
            continue
        idle = any(e.get("event") == "instance_idle_alert" for e in rec["events"])
        tag = "[A 空转] " if idle else ""
        lines.append(f"- {tag}{cite_subject(f'现态 {state}' + ('（idle_alert）' if idle else ''), iid)}")
    return lines


def _header(segment: str, date: str) -> list[str]:
    names = {"morning": "上午·计划与待批", "afternoon": "下午·进展与偏差",
             "evening": "晚间·结果、失败与明日建议", "urgent": "紧急·仅A级"}
    return [f"# 同步视图 {date} · {names[segment]}", DISCIPLINE_LINE, ""]


def _load_runs(ledger_dir: Path) -> dict:
    return ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "runs_index"), ledgerio.RUN_EVENT_STATE)


def render_morning(ledger_dir: Path, runs_dir: Path, envdir: Path, date: str,
                   buckets: dict, now: datetime, prev_ab_alerts: int | None = None) -> str:
    lines = _header("morning", date)
    # 前日 A+B 超线 → 置顶告警系统降敏待决（AMENDMENT-31）
    if prev_ab_alerts is not None and prev_ab_alerts > 3:
        lines.append(f"## ⚠ 告警系统降敏待决（前日 A+B 告警 {prev_ab_alerts}>3，强制置顶）")
        lines.append("")
    # 待批信封表
    lines.append("## 待批信封")
    drafts = []
    envdir = Path(envdir)
    if envdir.exists():
        for p in sorted(envdir.glob("*.json")):
            if p.name.endswith(".reject.json") or p.with_suffix(".reject.json").exists():
                continue
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if "approval" in env:
                continue
            drafts.append((p, env))
    if not drafts:
        lines.append("- （无待批信封）")
    for p, env in drafts:
        bid = env.get("batch_id", p.name)
        scope = env.get("scope", {})
        budget = env.get("budget", {})
        pc = Path("plans/precheck") / f"{bid}.precheck.json"
        verdict = "?"
        if pc.exists():
            try:
                verdict = "PASS" if json.loads(pc.read_text(encoding="utf-8")).get("ok") else "FAIL"
            except Exception:
                verdict = "?"
        summary = (f"conditions={scope.get('conditions')} splits={scope.get('splits')} "
                   f"item_limit={scope.get('item_limit_per_run')} "
                   f"预算(gpu={budget.get('gpu_hours_max')},cost={budget.get('cost_cap_cny')}) "
                   f"precheck={verdict}")
        lines.append(f"- {cite_subject(summary, bid)}")
    lines.append("")
    # 待决桶
    lines.append("## 待决")
    pend = buckets.get("待决", [])
    if not pend:
        lines.append("- （无）")
    for e in pend:
        lines.append(f"- {cite_subject(e['evidence'], e['subject_id'])}")
    lines.append("")
    # 今日预算与熔断（§C2-6 ①：从 costs 链读实耗；逐数带 subject_id）
    b = _budget_summary(ledger_dir)
    lines.append("## 今日预算与熔断")
    summary = (f"预估合计 {b['est']:.2f} 元；实耗合计 {b['actual']:.2f} 元；"
               f"预算告警 {b['alerts']} 次")
    lines.append(f"- {cite_subject(summary, 'W1')}")
    remaining_line = f"余额 {b['remaining']:.2f} 元（150 − 实耗）"
    lines.append(f"- {cite_subject(remaining_line, 'W1')}")
    breaker = f"距 85% 熔断线（{b['breaker_line']:.1f}）尚余 {b['breaker_dist']:.2f} 元"
    lines.append(f"- {cite_subject(breaker, 'W1')}")
    for sid, amt in b["per_run"]:
        lines.append(f"  - {cite_subject(f'实耗 {amt:.2f} 元', sid)}")
    lines.append("")
    # 云实例（§C2-6 ②：未 stopped；空转 idle_alert 标 A 级）
    lines.append("## 云实例（未 stopped）")
    inst_lines = _instances_lines(ledger_dir)
    lines.extend(inst_lines if inst_lines else ["- （无在运行云实例）"])
    return "\n".join(lines) + "\n"


def render_afternoon(ledger_dir: Path, runs_dir: Path, date: str,
                     buckets: dict, runs: dict) -> str:
    lines = _header("afternoon", date)
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    lines.append("## 各批次现态")
    if not batches:
        lines.append("- （无批次）")
    for bid, rec in sorted(batches.items()):
        lines.append(f"- {cite_subject(rec['state'], bid)}")
    lines.append("")
    lines.append("## RUNNING 进展")
    running = [(rid, rec) for rid, rec in runs.items() if rec["state"] == "RUNNING"]
    if not running:
        lines.append("- （无 RUNNING run）")
    for rid, rec in sorted(running):
        last_sp = next((e for e in reversed(rec["events"]) if e.get("event") == "step_progress"), {})
        prog = f"items_done={last_sp.get('items_done', '?')} steps_done={last_sp.get('steps_done', '?')}"
        lines.append(f"- {cite(prog, rid)}")
    lines.append("")
    lines.append("## 偏差（失败/停摆/TTL）")
    dev = buckets.get("失败未收敛", []) + buckets.get("停摆", []) + buckets.get("TTL超时", [])
    if not dev:
        lines.append("- （无偏差）")
    for e in dev:
        sev = f"[{e['severity']}] " if e.get("severity") else ""
        lines.append(f"- {sev}{cite_subject(e['evidence'], e['subject_id'])}")
    return "\n".join(lines) + "\n"


def render_evening(ledger_dir: Path, runs_dir: Path, date: str,
                   buckets: dict, runs: dict) -> str:
    lines = _header("evening", date)
    # 今日到 SCORED/AUDITED 的 run 逐条
    lines.append("## 今日结果（SCORED/AUDITED）")
    done_ids = [rid for rid, rec in runs.items() if rec["state"] in ("SCORED", "AUDITED")]
    metrics = views.per_run_metrics(runs_dir, done_ids) if done_ids else []
    if not metrics:
        lines.append("- （今日无 SCORED/AUDITED run 或无 scores）")
    confirmation = blind.current_phase() == "confirmation"
    for m in metrics:
        nc = "[non-citable] " if _non_citable(runs_dir, m["run_id"]) else ""   # G7 透传
        # 确认期锁盲：逐 run 原始均值明文列在效应块之上会泄露方向（读者可自算 Δ 符号），
        # 故确认期不呈现臂别原始值——与效应块 render_effect 的方向锁盲一致。
        val = "锁盲" if confirmation else f"{m['mean_value']:.4f}"
        line = cite(f"{nc}{m['metric_name']}={val}(scorer={m['scorer_id']}, n={m['n']})",
                    m["run_id"])
        lines.append(f"- {line}")
    lines.append("")
    # 效应对比（探索期直通；臂级聚合以贡献 run_id 列表随行注明）
    # fail-closed：只取规范 scorer；按 condition 去重取一行→两臂必为【不同 condition】
    # （堵"同 condition 两 scorer 被当 A/B 自比"）；任一臂样本不足即不出对比（不误导）。
    ov = views.overview(ledger_dir, runs_dir)
    arms = _effect_arms(ov["per_condition"])
    if arms is not None:
        a, b = arms
        eff = blind.render_effect("is_correct", a["mean_value"], b["mean_value"],
                                  a["condition"], b["condition"],
                                  source_run_ids=sorted(done_ids) or None)
        blind.assert_no_direction(eff)   # 确认期自检（探索期空操作）
        lines.append("## 效应对比（探索期）")
        lines.append(f"- {eff}")
        lines.append("")
    # 失败清单
    lines.append("## 失败清单")
    fails = buckets.get("失败未收敛", [])
    if not fails:
        lines.append("- （无失败）")
    for e in fails:
        lines.append(f"- {cite_subject(e['evidence'], e['subject_id'])}")
    lines.append("")
    # 今日 A+B 告警数
    n = triagemod.ab_alert_count(buckets)
    lines.append(f"**今日 A+B 告警数 {n}/3**")
    lines.append("")
    # 明日建议（规则模板，零 LLM）
    lines.append("## 明日建议")
    sug = []
    for e in buckets.get("失败未收敛", []):
        sug.append(f"- 建议续跑 {e['subject_id']}")
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    for bid, rec in sorted(batches.items()):
        if rec["state"] == "SETTLED":
            sug.append(f"- 待 A 审计 {bid}")
        elif rec["state"] == "DRAFT":
            sug.append(f"- 待批 {bid}")
    if not sug:
        sug.append("- （无待办建议）")
    lines.extend(sug)
    return "\n".join(lines) + "\n"


def render_urgent(date: str, buckets: dict) -> str:
    lines = _header("urgent", date)
    a_level = buckets.get("A级紧急", []) + buckets.get("停摆", [])   # 停摆为 A 级（AMENDMENT-31）
    a_level = [e for e in a_level if e.get("severity") == "A"]
    lines.append("## A 级异常")
    if not a_level:
        lines.append("- 无 A 级异常")
    else:
        for e in a_level:
            lines.append(f"- [A] {cite_subject(e['evidence'], e['subject_id'])}")
    return "\n".join(lines) + "\n"


def render_segment(segment: str, ledger_dir: Path, runs_dir: Path, envdir: Path,
                   date: str, now: datetime, alerts_dir: Path) -> str:
    buckets = triagemod.triage(ledger_dir, envdir, alerts_dir, now)
    runs = _load_runs(ledger_dir)
    if segment == "morning":
        return render_morning(ledger_dir, runs_dir, envdir, date, buckets, now)
    if segment == "afternoon":
        return render_afternoon(ledger_dir, runs_dir, date, buckets, runs)
    if segment == "evening":
        return render_evening(ledger_dir, runs_dir, date, buckets, runs)
    if segment == "urgent":
        return render_urgent(date, buckets)
    raise ValueError(f"未知段: {segment}")


def run(segment: str, out_dir: Path, ledger_dir: Path = Path("ledger"),
        runs_dir: Path = Path("data/runs"), envdir: Path = Path("configs/envelopes"),
        alerts_dir: Path = Path("state/alerts"), date: str | None = None,
        now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    date = date or now.strftime("%Y-%m-%d")
    md = render_segment(segment, ledger_dir, runs_dir, envdir, date, now, alerts_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"sync-{date}-{segment}.md"
    out.write_text(md, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="abcr.report.sync", description="四段同步视图")
    ap.add_argument("--segment", required=True, choices=SEGMENTS)
    ap.add_argument("--date", default=None)
    ap.add_argument("--ledger-dir", default="ledger")
    ap.add_argument("--runs-dir", default="data/runs")
    ap.add_argument("--envdir", default="configs/envelopes")
    ap.add_argument("--alerts-dir", default="state/alerts")
    ap.add_argument("--out", default="reports/")
    args = ap.parse_args()
    out = run(args.segment, Path(args.out), Path(args.ledger_dir), Path(args.runs_dir),
              Path(args.envdir), Path(args.alerts_dir), args.date)
    print(f"已生成: {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
