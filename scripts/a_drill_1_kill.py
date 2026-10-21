"""scripts/a_drill_1_kill.py —— 演练1 · 杀 RUNNING 进程（恢复与续跑对账，A2-6 / R2-A1）。

单命令可跑，自带前置检查，结束打印 `DRILL 1 VERDICT: PASS|FAIL` + 留痕清单。

AMENDMENT-17 隔离：全程在隔离 root state/audit/drills/drill1-kill-<UTC>/ 的账本副本上跑，真链
零写入；注入事件 payload actor="drill"。演练在 fixture 假任务负载上做（零成本、确定性）。

模式：**REAL（坑16 已切真，2026-07-15）**——两阶段真调 dispatch 打隔离 root：
  Phase1 `ABCR_FAKETASK_CRASH_AT_ITEM=g05` 令首个 run 跑到 g05 被 os._exit(1) 杀（留 RUNNING 孤儿 +
         半截 steps）；Phase2 原命令重跑 → dispatch 的 scan_orphans 检测孤儿 → mark_suspended →
         _process_run 走 resume 路径（run_failed→run_resumed，续跑只补未完成 item，AMENDMENT-25 去重）
         → run_completed → 批次收口。账本生命周期由真 dispatch 代码产出，非手工合成。
  隔离-root 旗标 = ABCR_LEDGER_DIR/RUNS_ROOT/QUEUE_ROOT/STATE_DIR（harness.dispatch_env）。

A 侧留痕断言（本脚本负责）：
  ① runs_index 事件序含 run_started → step_progress+ →（run_failed|run_paused）→ run_resumed →
     run_completed，derive_run_state 无违规；
  ② 五链 verify_chain 全过（被杀进程 fsync 保证不留半行）；
  ③ steps.jsonl 无重复 (item_id, seed, step_id)（幂等）；
  ④ rescore 该 run 与 expected 一致（杀进程不损数据）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abcr.common.ledger_ref import RunLedger
from abcr.ledger.statemachine import derive_run_state
from abcr.sandboxing.drills import harness as H

CRASH_AT = "g05"          # 首个 run 跑到该 item 时 os._exit(1) 被杀（faketask AMENDMENT-24）


def _find_resumed_run(iso_root: Path) -> str | None:
    """从隔离 root runs_index 找"被杀又续跑"的 run —— 即含 run_resumed 事件那个（真 dispatch 落账）。"""
    for e in RunLedger(iso_root / "ledger", "runs_index").events():
        if e.get("event") == "run_resumed":
            return e.get("subject_id")
    return None


def _assert_lifecycle(iso_root: Path, rid: str) -> tuple[bool, list[str]]:
    ev_all = RunLedger(iso_root / "ledger", "runs_index").events()
    evs = [e for e in ev_all if e.get("subject_id") == rid]
    names = [e.get("event") for e in evs]
    state, violations = derive_run_state(evs)
    ok = True
    lines: list[str] = [f"事件序: {names}"]
    if violations:
        ok = False
        lines.append(f"derive_run_state 违规: {violations}")
    else:
        lines.append(f"derive_run_state 无违规，终点={state}")
    # 必含子序列 run_started → (run_failed|run_paused) → run_resumed → run_completed。
    # 注（坑16 切真修正）：不再要求 step_progress 排在 run_failed 之前——真 os._exit(1) 突兀杀进程，
    # Heartbeat 的 step_progress 未及 flush 即死，故真事件序为 started→failed→resumed→step_progress→
    # completed。step_progress 的"至少出现一次"另行断言（progress 曾被记录），排位不入子序列契约。
    required = ["run_started", None, "run_resumed", "run_completed"]   # None = run_failed|run_paused
    idx = 0
    for n in names:
        if idx < len(required):
            want = required[idx]
            if want is None:
                if n in ("run_failed", "run_paused"):
                    idx += 1
            elif n == want:
                idx += 1
    if idx < len(required):
        ok = False
        lines.append(f"生命周期子序列缺失（匹配到 {idx}/{len(required)}）")
    else:
        lines.append("生命周期子序列完整: started→(failed|paused)→resumed→completed")
    # step_progress 至少出现一次（续跑期间进度确被记录；排位不限）
    if "step_progress" not in names:
        ok = False
        lines.append("缺 step_progress —— 续跑期间未记录任何进度")
    else:
        lines.append(f"step_progress 出现 {names.count('step_progress')} 次（progress 已记录）")
    return ok, lines


def _assert_rescore(repo_root: Path, iso_root: Path, run_dir: Path) -> tuple[bool, list[str]]:
    from abcr.audit.rescore import rescore_run
    rescore_run(run_dir)
    expected = {}
    exp_path = iso_root / "fixtures" / "expected_scores.jsonl"
    for ln in exp_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("metric_name") == "is_correct":
            expected[(r["item_id"], r["random_seed"], r["condition"])] = r["metric_value"]
    got = {}
    for ln in (run_dir / "scores.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("scorer_id") == "rescore_v1" and r.get("metric_name") == "is_correct":
            got[(r["item_id"], r["random_seed"], r["condition"])] = r["metric_value"]
    mism = [k for k, v in got.items() if expected.get(k) != v]
    if mism:
        return False, [f"rescore vs expected 不一致 {mism[:5]}"]
    return True, [f"rescore vs expected 一致（{len(got)} item，含 g03/g07=0）"]


def run_drill(repo_root: Path) -> int:
    repo_root = Path(repo_root).resolve()
    if not (repo_root / "data" / "golden" / "golden10.json").exists():
        print("SKIP: 缺 data/golden/golden10.json（前置未满足）")
        print("DRILL 1 VERDICT: SKIP")
        return 0
    iso_root = H.new_iso_root(repo_root, "drill1-kill")
    H.seed_frozen_inputs(repo_root, iso_root)
    before = H.real_ledger_digest(repo_root)

    # Phase1：真调 dispatch 带 crash 注入 → 首个 run 跑到 CRASH_AT 被 os._exit(1) 杀，留 RUNNING
    # 孤儿 + 半截 steps（faketask os._exit → 进程非零退出属预期，不视为失败）。
    p1 = H.drive_real_dispatch(repo_root, iso_root,
                               extra_env={"ABCR_FAKETASK_CRASH_AT_ITEM": CRASH_AT})
    killed = p1.returncode != 0
    # Phase2：原命令重跑 → dispatch scan_orphans 检测孤儿 → mark_suspended → _process_run resume
    # 路径（run_failed→run_resumed，AMENDMENT-25 只补未完成 item）→ run_completed → 批次收口。
    # F-OPS-01（fix-round1 移植）给 scan_orphans 加了「pid 确证死亡 且 心跳陈旧超 grace 才判孤儿」
    # 的 fail-safe，默认 grace=900s。本演练同步 kill+resume（秒级），Phase1 死亡子进程留下的
    # RUNNING 记录 pid 已死但 updated_at 仍新鲜，会被 fail-safe 保留而不触发 scan_orphans 续跑。
    # 演练意在秒级验证 resume 路径本身，故显式 ABCR_ORPHAN_GRACE_S=0 关掉心跳宽限，让「pid 死」
    # 即判孤儿——生产链路的 900s fail-safe 语义完全不动（仅本演练子进程环境为 0）。
    p2 = H.drive_real_dispatch(repo_root, iso_root,
                               extra_env={"ABCR_ORPHAN_GRACE_S": "0"})
    if p2.returncode != 0:
        print(p2.stdout[-2000:])
        print(p2.stderr[-2000:], file=sys.stderr)
        print("DRILL 1 VERDICT: FAIL（续跑未收口，returncode!=0）")
        return 1
    rid = _find_resumed_run(iso_root)
    if rid is None:
        print("DRILL 1 VERDICT: FAIL（runs_index 无 run_resumed —— 续跑路径未触发）")
        return 1
    run_dir = iso_root / "data" / "runs" / rid

    checks: list[tuple[str, bool, list[str]]] = []
    checks.append(("⓪ Phase1 真被杀（os._exit 非零退出）", killed,
                   [f"phase1 returncode={p1.returncode}（!=0 即崩溃注入生效）"]))
    ok1, l1 = _assert_lifecycle(iso_root, rid); checks.append(("① 生命周期/derive_run_state", ok1, l1))
    ok2, l2 = H.verify_all_chains(iso_root); checks.append(("② 五链 verify_chain", ok2, l2))
    ok3, l3 = H.no_duplicate_steps(run_dir); checks.append(("③ steps 幂等无重复", ok3, l3))
    ok4, l4 = _assert_rescore(repo_root, iso_root, run_dir); checks.append(("④ rescore vs expected", ok4, l4))

    after = H.real_ledger_digest(repo_root)
    zero_write = before == after
    checks.append(("⑤ 真链零写入（演练前后逐字节不变）", zero_write,
                   ["真链未变" if zero_write else f"真链被改！before={before} after={after}"]))

    for name, ok, lines in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for ln in lines:
            print(f"      {ln}")

    passed = all(ok for _, ok, _ in checks)
    return H.finish(1, passed, iso_root,
                    [f"data/runs/{rid}", "ledger/runs_index.jsonl"],
                    {"drill": "kill_running",
                     "mode": "REAL（真调 dispatch;crash注入 g05 + scan_orphans 续跑;坑16 已切真）",
                     "phase1_returncode": p1.returncode, "run_id": rid,
                     "checks": {n: ok for n, ok, _ in checks}})


def main() -> int:
    ap = argparse.ArgumentParser(description="演练1 杀 RUNNING 进程")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    return run_drill(Path(args.repo_root))


if __name__ == "__main__":
    sys.exit(main())
