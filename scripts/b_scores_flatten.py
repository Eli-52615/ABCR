#!/usr/bin/env python3
"""scripts/b_scores_flatten.py — 把各 run 的 scores.jsonl 拉平为确定性可比对形态。

架构位置：B1-6 验收工具。只取确定性的 is_correct 指标行，抛掉 run_id/scored_at 等
非确定性字段，按 (condition, random_seed, item_id) 排序输出——供
`diff <(b_scores_flatten.py data/runs) fixtures/expected_scores.jsonl` 比对。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def flatten(runs_root: Path) -> list[dict]:
    rows: list[dict] = []
    for scores_path in sorted(runs_root.glob("*/scores.jsonl")):
        for line in scores_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("metric_name") != "is_correct":
                continue
            rows.append({
                "item_id": r["item_id"],
                "condition": r["condition"],
                "random_seed": r["random_seed"],
                "metric_name": "is_correct",
                "metric_value": r["metric_value"],
            })
    rows.sort(key=lambda x: (x["condition"], x["random_seed"], x["item_id"]))
    return rows


def main() -> int:
    runs_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/runs")
    for row in flatten(runs_root):
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
