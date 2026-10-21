"""abcr.report.cli —— 三层钻取 CLI（overview → batch → run/item）。全程 ≤1 分钟（体验判据 K14）。

用法（在 worktree 根）：
  PYTHONPATH=src python -m abcr.report.cli overview
  PYTHONPATH=src python -m abcr.report.cli batch <batch_id>
  PYTHONPATH=src python -m abcr.report.cli run <run_id> --item <item_id>   # 打印 output_text 原文
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from abcr.report import views


def _escape_controls(s: str) -> str:
    """只对控制字符做 repr 转义，正文全文不截断（这是"钻到原始输出"的意义，§C1-7 L3）。"""
    return "".join(ch if (ch >= " " or ch in "\n\t") else repr(ch)[1:-1] for ch in s)


def cmd_overview(args) -> int:
    ov = views.overview(Path(args.ledger_dir), Path(args.runs_dir))
    print("# L1 宏观汇总")
    print(f"批次现态计数: {ov['batch_state_counts'] or '（无）'}")
    print(f"run 现态计数: {ov['run_state_counts'] or '（无）'}")
    print("per-condition 确定性指标均值（分 scorer_id）:")
    if not ov["per_condition"]:
        print("  （无 scores 数据）")
    for r in ov["per_condition"]:
        print(f"  {r['condition']:<14} {r['metric_name']:<16} {r['scorer_id']:<16} "
              f"mean={r['mean_value']} n={r['n']}")
    return 0


def cmd_batch(args) -> int:
    bd = views.batch_detail(args.batch_id, Path(args.ledger_dir), Path(args.runs_dir))
    print(f"# L2 批次 {bd['batch_id']}")
    print(f"run 数: {len(bd['runs'])}")
    for r in bd["runs"]:
        print(f"  {r['run_id']:<40} cond={r['condition']} seeds={r['seeds']} 现态={r['state']}")
    print("臂级聚合（condition×metric×scorer_id）:")
    if not bd["arm_aggregate"]:
        print("  （无 scores 数据）")
    for a in bd["arm_aggregate"]:
        print(f"  {a['condition']:<14} {a['metric_name']:<16} {a['scorer_id']:<16} "
              f"mean={a['mean_value']} n={a['n']}")
    return 0


def cmd_run(args) -> int:
    ri = views.run_item(args.run_id, args.item, Path(args.runs_dir))
    print(f"# L3 run {ri['run_id']} item {ri['item_id']}")
    if not ri["steps"]:
        print("（该 run/item 无 steps 记录——可能未启动，降级用信封 run_configs 对账）")
    for st in ri["steps"]:
        print(f"--- step trajectory={st.get('trajectory_id')} step_id={st.get('step_id')} "
              f"condition={st.get('condition')} seed={st.get('random_seed')} ---")
        print("output_text（原文，不截断）:")
        print(_escape_controls(str(st.get("output_text", ""))))
    print("\nscores:")
    for sc in ri["scores"]:
        print(f"  {sc.get('metric_name')}={sc.get('metric_value')} "
              f"scorer_id={sc.get('scorer_id')} seed={sc.get('random_seed')}")
    return 0


def main() -> int:
    # 公共旗标经 parent parser 下放到各子命令，故 `overview --ledger-dir ...` 也可用
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ledger-dir", default="ledger")
    common.add_argument("--runs-dir", default="data/runs")
    ap = argparse.ArgumentParser(prog="abcr.report.cli", description="三层钻取", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("overview", parents=[common]); p.set_defaults(fn=cmd_overview)
    p = sub.add_parser("batch", parents=[common]); p.add_argument("batch_id"); p.set_defaults(fn=cmd_batch)
    p = sub.add_parser("run", parents=[common]); p.add_argument("run_id"); p.add_argument("--item", required=True)
    p.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
