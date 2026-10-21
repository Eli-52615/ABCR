#!/usr/bin/env python3
"""scripts/b_r1_assert.py — R1 自证断言（契约 §5-B1-8 断言清单）。

在 b_r1_selfcheck.sh 的 crash 续跑演练之后运行，逐项硬校验：
  ① 每 run steps.jsonl 的 (item_id, random_seed) 无重复且计 10 条
  ② runs_index/batches 哈希链 verify_chain 不抛
  ③ scores 与 fixtures/expected_scores.jsonl 一致
  ④ 每 run 事件序符合 §0.3-6（crash run 额外含 run_failed→run_resumed）
  ⑤ queue/done 恰 6 文件、pending/running/failed 空
任一不满足即 raise AssertionError（非零退出）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from abcr.common.ledger_ref import RunLedger
from abcr.ops import queue

RUNS_ROOT = Path("data/runs")


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def assert_steps_no_dup() -> None:
    for steps in sorted(RUNS_ROOT.glob("*/steps.jsonl")):
        rows = _load_jsonl(steps)
        keys = [(r["item_id"], r["random_seed"]) for r in rows]
        assert len(keys) == len(set(keys)), f"{steps} 有重复 (item,seed): {keys}"
        assert len(rows) == 10, f"{steps} 应 10 条 step，实为 {len(rows)}"
    print("① steps 无重复且每 run 10 条 —— OK")


def assert_chains() -> None:
    for name in ("runs_index", "batches"):
        RunLedger(Path("ledger"), name).verify_chain()
    for steps in RUNS_ROOT.glob("*/steps.jsonl"):
        # AMENDMENT-36：模块级 verify_chain(path) 已废；steps.jsonl 用 RunLedger 重放
        # 验链（verify_chain 只依赖记录内的 prev_hash/entry_hash，与链 stem/run_id 无关）。
        RunLedger(steps.parent, "steps").verify_chain()
    print("② 哈希链自洽（runs_index/batches/steps）—— OK")


def assert_scores_match() -> None:
    got = subprocess.run([sys.executable, "scripts/b_scores_flatten.py", "data/runs"],
                         capture_output=True, text=True, check=True).stdout.strip()
    expected = Path("fixtures/expected_scores.jsonl").read_text(encoding="utf-8").strip()
    assert got == expected, "scores 与 expected_scores.jsonl 不一致"
    print("③ 分数与 expected_scores.jsonl 完全一致 —— OK")


def assert_event_order() -> None:
    evs = RunLedger(Path("ledger"), "runs_index").events()   # AMENDMENT-36：read_all() → events()
    by_run: dict[str, list[str]] = {}
    for e in evs:
        by_run.setdefault(e["subject_id"], []).append(e["event"])
    assert len(by_run) == 6, f"应 6 run，实为 {len(by_run)}"
    for rid, seq in by_run.items():
        for a, b in (("run_registered", "run_queued"), ("run_queued", "run_started"),
                     ("run_started", "run_completed"), ("run_completed", "run_scored")):
            assert a in seq and b in seq and seq.index(a) < seq.index(b), \
                f"{rid} 事件序 {a}→{b} 不满足：{seq}"
        assert "step_progress" in seq, f"{rid} 无 step_progress：{seq}"
        if "run_failed" in seq:   # crash run
            assert "run_resumed" in seq, f"{rid} 有 failed 无 resumed：{seq}"
            assert seq.index("run_started") < seq.index("run_failed") < seq.index("run_resumed") \
                < seq.index("run_completed"), f"{rid} crash 事件序错位：{seq}"
    print(f"④ 事件序合规（6 run；crash run 含 failed→resumed）—— OK")


def assert_queue() -> None:
    assert len(queue.list_state("done")) == 6, queue.list_state("done")
    for st in ("pending", "running", "failed"):
        assert queue.list_state(st) == [], f"queue/{st} 非空：{queue.list_state(st)}"
    print("⑤ queue/done=6、pending/running/failed 空 —— OK")


def main() -> int:
    assert_steps_no_dup()
    assert_chains()
    assert_scores_match()
    assert_event_order()
    assert_queue()
    print("R1 ASSERT ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
