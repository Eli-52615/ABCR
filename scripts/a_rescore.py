"""scripts/a_rescore.py —— 独立复评入口（A1-5）。

用法：
  python scripts/a_rescore.py <run_dir>          # 复评单个 run 目录
  python scripts/a_rescore.py <batch_id>         # 经账本折叠该批全部 run 后逐个复评
复评完成不改 run 状态（不追加 run_scored——那是 B scorer 的语义）；比对结果进 auditor 报告。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abcr.audit.rescore import rescore_run
from abcr.common.ledger_ref import RunLedger


def runs_of_batch(repo_root: Path, batch_id: str) -> list[Path]:
    """经 runs_index 的 run_registered(batch_id) 事件折叠该批 run 目录。"""
    ledger = RunLedger(repo_root / "ledger", "runs_index")
    out: list[Path] = []
    seen: set[str] = set()
    for ev in ledger.events():
        if ev.get("event") == "run_registered" and ev.get("batch_id") == batch_id:
            rid = ev.get("subject_id")
            if rid and rid not in seen:
                seen.add(rid)
                out.append(repo_root / "data" / "runs" / rid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="run 目录路径 或 batch_id（B-...）")
    ap.add_argument("--repo-root", default=".", help="仓库根（batch_id 模式用）")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    target = args.target
    if target.startswith("B-"):
        run_dirs = runs_of_batch(repo_root, target)
        if not run_dirs:
            print(f"batch {target}: 账本中无 run_registered，无可复评 run", file=sys.stderr)
            return 1
    else:
        run_dirs = [Path(target).resolve()]

    total = 0
    for rd in run_dirs:
        if not (rd / "steps.jsonl").exists():
            print(f"SKIP {rd}: 无 steps.jsonl", file=sys.stderr)
            continue
        n = rescore_run(rd)
        total += n
        print(f"{rd.name}: +{n} rescore_v1 rows")
    print(f"total new rescore_v1 rows: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
