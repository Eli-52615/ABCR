"""scripts/a_audit.py —— 审计 CLI 入口（A1-6）。

用法：
  python scripts/a_audit.py <batch_id> --items 1,2,4 [--apply]
产出 reports/audit/<batch_id>.{json,md}（JSON 与 MD 同源）。--apply 才真写账本处置（缺省 dry-run）。

（实现用 stdlib argparse 而非 typer——§9.1 零外部依赖偏好；行为与文档验收命令一致。）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from abcr.audit.auditor import audit_batch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id", help="批次 id（B-...）")
    ap.add_argument("--items", default="1,2,4", help="逗号分隔审计项清单")
    ap.add_argument("--apply", action="store_true", help="真写账本处置（缺省 dry-run）")
    ap.add_argument("--strict", action="store_true",
                    help="项5 code_tree_hash 漂移升级为 FAIL（复现包出包前）")
    ap.add_argument("--repo-root", default=".", help="仓库根")
    args = ap.parse_args()

    items = tuple(int(x) for x in args.items.split(",") if x.strip())
    repo_root = Path(args.repo_root).resolve()
    report = audit_batch(repo_root, args.batch_id, items=items,
                         apply=args.apply, strict=args.strict)
    json_p, md_p = report.write(repo_root)

    print(f"batch {args.batch_id} overall={report.overall}")
    for it in report.items:
        print(f"  item{it.id} {it.name}: {it.verdict}"
              + (f"  [{it.disposition}]" if it.disposition else ""))
    print(f"报告: {json_p}  |  {md_p}")
    return 0 if report.overall == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
