"""scripts/a_rescore_compare.py —— rescore_v1 vs expected 比对（R1-A6 核验脚本，A1-5）。

用法：
  python scripts/a_rescore_compare.py --runs 'data/runs/*' --against fixtures/expected_scores.jsonl
  python scripts/a_rescore_compare.py --runs <batch_id> --against <expected.jsonl>

比对对象 = rescore_v1 产出的 is_correct 行；join 键 = (item_id, random_seed, condition, metric_name)
——expected_scores.jsonl 无法预知 run_id，不按 run_id join。
输出契约：全同 → 打印 "MATCH N/N" 且 exit 0；任何不同 → 逐行打印
"MISMATCH <键> expected=<v1> got=<v2>" 且 exit 1。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from abcr.common.ledger_ref import RunLedger

KEY_FIELDS = ("item_id", "random_seed", "condition", "metric_name")


def _key(row: dict) -> tuple:
    return tuple(row.get(k) for k in KEY_FIELDS)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def resolve_run_dirs(runs_arg: str, repo_root: Path) -> list[Path]:
    if runs_arg.startswith("B-"):
        ledger = RunLedger(repo_root / "ledger", "runs_index")
        out, seen = [], set()
        for ev in ledger.events():
            if ev.get("event") == "run_registered" and ev.get("batch_id") == runs_arg:
                rid = ev.get("subject_id")
                if rid and rid not in seen:
                    seen.add(rid)
                    out.append(repo_root / "data" / "runs" / rid)
        return out
    return [Path(p) for p in sorted(glob.glob(runs_arg))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs/*", help="run 目录 glob 或 batch_id")
    ap.add_argument("--against", required=True, help="expected.jsonl 路径")
    ap.add_argument("--repo-root", default=".", help="仓库根（batch_id 模式用）")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    run_dirs = resolve_run_dirs(args.runs, repo_root)

    # 收集 rescore_v1 的 is_correct 行
    got: dict[tuple, int] = {}
    for rd in run_dirs:
        for row in _load_jsonl(rd / "scores.jsonl"):
            if row.get("scorer_id") == "rescore_v1" and row.get("metric_name") == "is_correct":
                got[_key(row)] = row.get("metric_value")

    # expected（只取 is_correct）
    expected: dict[tuple, int] = {}
    for row in _load_jsonl(Path(args.against)):
        if row.get("metric_name") == "is_correct":
            expected[_key(row)] = row.get("metric_value")

    mismatches: list[str] = []
    matched = 0
    for k, ev in expected.items():
        if k not in got:
            mismatches.append(f"MISMATCH {k} expected={ev} got=<缺失>")
        elif got[k] != ev:
            mismatches.append(f"MISMATCH {k} expected={ev} got={got[k]}")
        else:
            matched += 1
    # rescore 侧多出的键（expected 无）也算不一致
    for k, gv in got.items():
        if k not in expected:
            mismatches.append(f"MISMATCH {k} expected=<缺失> got={gv}")

    if mismatches:
        for m in mismatches:
            print(m)
        print(f"MISMATCH {len(mismatches)} 项（matched {matched}/{len(expected)}）")
        return 1
    print(f"MATCH {matched}/{len(expected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
