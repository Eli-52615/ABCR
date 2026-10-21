"""scripts/a_drill_2_fake_completion.py —— 演练2 · 伪报完成无 step（A 是防线，A2-6 / R2-A2）。

单命令可跑，结束打印 `DRILL 2 VERDICT: PASS|FAIL` + 留痕清单。AMENDMENT-17 隔离：全程在隔离
root 的账本副本上跑，真链零写入；注入 payload actor="drill"。

注入（ABCR_FAKETASK_SKIP_LEDGER_WRITES=1 语义）：假任务照常"跑完"并宣称完成（manifest
status=COMPLETED + runs_index run_completed），但不落 step 行（steps.jsonl 清空）。期望检测者 =
**A（你）**：auditor item1 manifest 完整性——steps 行数(0) ≠ 信封期望(10)。期望处置：auditor
--apply 将该批 QUARANTINED（AMENDMENT-16：run 先 run_audited(quarantined) 再 run_quarantined，
批次 batch_audited(quarantined)）。

留痕断言：① reports/audit/<batch>.json overall=FAIL 且 item1 FAIL、证据含行数对比；
② runs_index 含 run_audited(quarantined) 与 run_quarantined，derive_run_state 无违规；
③ QUARANTINED 数据原样留存（目录未删、未被覆盖）；④ 链完整。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abcr.audit.auditor import audit_batch
from abcr.common.ledger_ref import RunLedger
from abcr.ledger.statemachine import derive_run_state
from abcr.sandboxing.drills import harness as H


def run_drill(repo_root: Path) -> int:
    repo_root = Path(repo_root).resolve()
    if not (repo_root / "data" / "golden" / "golden10.json").exists():
        print("SKIP: 缺 data/golden/golden10.json（前置未满足）")
        print("DRILL 2 VERDICT: SKIP")
        return 0
    iso_root = H.new_iso_root(repo_root, "drill2-fake-completion")
    H.seed_frozen_inputs(repo_root, iso_root)
    before = H.real_ledger_digest(repo_root)

    # 坑16 切真：真调 dispatch 打隔离 root，产出真实 6-run 批（替代 sim 合成账本；真 dispatch
    # 代码路径 + faketask 执行器 + 真账本事件）。真链零写入由 check⑤ 前后哈希证。
    proc = H.drive_real_dispatch(repo_root, iso_root)
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:], file=sys.stderr)
        print("DRILL 2 VERDICT: FAIL（真 dispatch 未正常收口，无法进入伪完成注入）")
        return 1
    batch_id = json.loads(
        (repo_root / "fixtures" / "envelope_fixture.json").read_text(encoding="utf-8")
    )["batch_id"]
    run_ids = H.run_ids_in(iso_root)
    victim = run_ids[0]
    victim_dir = iso_root / "data" / "runs" / victim

    # <<< skip_ledger_writes 注入：宣称完成但清空 step 行（steps.jsonl → 0 行）>>>
    steps_before = (victim_dir / "steps.jsonl").read_text(encoding="utf-8")
    (victim_dir / "steps.jsonl").write_text("", encoding="utf-8")
    manifest_before = (victim_dir / "manifest.json").read_text(encoding="utf-8")

    # 期望检测者 = A：auditor item1（+ item4），--apply 落 QUARANTINE
    report = audit_batch(iso_root, batch_id, items=(1, 4), apply=True)
    report.write(iso_root)

    checks: list[tuple[str, bool, list[str]]] = []

    # ① overall=FAIL 且 item1 FAIL、证据含行数对比
    item1 = next((it for it in report.items if it.id == 1), None)
    line_ev = item1 and any(("行数" in e and "≠" in e) for e in item1.evidence)
    ok1 = (report.overall == "FAIL" and item1 is not None and item1.verdict == "FAIL"
           and bool(line_ev))
    checks.append(("① overall=FAIL, item1 FAIL, 证据含行数对比", ok1,
                   [f"overall={report.overall}, item1={item1.verdict if item1 else None}"]
                   + [e for e in (item1.evidence if item1 else []) if "行数" in e][:3]))

    # ② runs_index 含 run_audited(quarantined)+run_quarantined，derive_run_state 无违规
    ri = RunLedger(iso_root / "ledger", "runs_index")
    v_events = [e for e in ri.events() if e.get("subject_id") == victim]
    has_audit_q = any(e.get("event") == "run_audited" and e.get("verdict") == "quarantined"
                      for e in v_events)
    has_quar = any(e.get("event") == "run_quarantined" for e in v_events)
    _, violations = derive_run_state(v_events)
    ok2 = has_audit_q and has_quar and not violations
    checks.append(("② run_audited(quarantined)+run_quarantined 入账, derive 无违规", ok2,
                   [f"run_audited(quarantined)={has_audit_q}, run_quarantined={has_quar}, "
                    f"violations={violations}"]))

    # ③ QUARANTINED 数据原样留存（目录/manifest 未删未改；steps 仍是注入后的空——未被重跑覆盖）
    manifest_after = (victim_dir / "manifest.json").read_text(encoding="utf-8") \
        if (victim_dir / "manifest.json").exists() else None
    ok3 = (victim_dir.exists() and manifest_after == manifest_before
           and (victim_dir / "steps.jsonl").read_text(encoding="utf-8") == "")
    checks.append(("③ QUARANTINED 数据原样留存（目录/manifest 未动、未被覆盖）", ok3,
                   [f"dir存在={victim_dir.exists()}, manifest未改={manifest_after == manifest_before}"]))

    # ④ 链完整
    ok4, l4 = H.verify_all_chains(iso_root)
    checks.append(("④ 五链 verify_chain", ok4, l4))

    # ⑤ 真链零写入
    after = H.real_ledger_digest(repo_root)
    ok5 = before == after
    checks.append(("⑤ 真链零写入", ok5, ["真链未变" if ok5 else "真链被改！"]))

    for name, ok, lines in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for ln in lines:
            print(f"      {ln}")

    passed = all(ok for _, ok, _ in checks)
    return H.finish(2, passed, iso_root,
                    [f"reports/audit/{batch_id}.json", f"data/runs/{victim}",
                     "ledger/runs_index.jsonl"],
                    {"drill": "fake_completion_no_step", "victim_run": victim,
                     "injected": "steps.jsonl 清空（skip_ledger_writes 语义）",
                     "steps_before_lines": len([l for l in steps_before.splitlines() if l.strip()]),
                     "checks": {n: ok for n, ok, _ in checks}})


def main() -> int:
    ap = argparse.ArgumentParser(description="演练2 伪报完成无 step")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    return run_drill(Path(args.repo_root))


if __name__ == "__main__":
    sys.exit(main())
