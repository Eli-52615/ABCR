"""scripts/a_ledger_digest.py —— 打印五链链尾摘要（A1-1）。

供 fable 在 worktree 外留存 snapshot_digest() 副本、R 门比对（防整链重算伪造的第二道防线）。
云链段（ledger/cloud-day<N>/，AMENDMENT-2）逐段另列。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from abcr.common.ledger_ref import RunLedger

CHAINS = ("runs_index", "batches", "costs", "instances", "protocol")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    ledger_dir = Path(args.repo_root).resolve() / "ledger"
    for chain in CHAINS:
        main_p = ledger_dir / f"{chain}.jsonl"
        if main_p.exists():
            print(f"{chain:12s} {RunLedger(ledger_dir, chain).snapshot_digest()}")
        else:
            print(f"{chain:12s} (空链)")
        for seg in sorted(ledger_dir.glob(f"cloud-day*/{chain}.jsonl")):
            digest = RunLedger(seg.parent, seg.stem).snapshot_digest()
            print(f"  └─ {seg.parent.name}/{chain}  {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
