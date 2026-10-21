"""scripts/a_views.py —— 账本只读视图查询入口（A1-4；R1-full）。

用法：python scripts/a_views.py runs|batches|anomalies|scores
fable 与 C 阶段1 查账入口。全模块只 SELECT（views.py 保证）。
（用 stdlib argparse；表格用简单对齐打印，避免额外依赖。）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abcr.ledger import views


def _print_rows(header: list[str], rows: list[tuple]) -> None:
    print(" | ".join(header))
    print("-" * (len(" | ".join(header))))
    for r in rows:
        print(" | ".join(str(x) for x in r))
    print(f"({len(rows)} 行)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["runs", "batches", "anomalies", "scores"])
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    repo = Path(args.repo_root).resolve()

    if args.what == "runs":
        _print_rows(["subject_id", "last_event", "last_ts", "n_events"],
                    views.run_summary(repo))
    elif args.what == "batches":
        _print_rows(["batch_id", "last_event", "last_ts"], views.batch_progress(repo))
    elif args.what == "anomalies":
        _print_rows(["subject_id", "last_event", "last_ts", "age_s"], views.anomalies(repo))
    elif args.what == "scores":
        con = views.connect(repo)
        try:
            rows = con.execute(
                "SELECT scorer_id, metric_name, count(*) AS n "
                "FROM all_scores GROUP BY scorer_id, metric_name ORDER BY 1,2").fetchall()
            _print_rows(["scorer_id", "metric_name", "n"], rows)
        except Exception:  # noqa: BLE001 —— 无 scores 时视图不存在
            print("(无 scores 数据)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
