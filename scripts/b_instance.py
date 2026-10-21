#!/usr/bin/env python3
"""scripts/b_instance.py — 云实例生命周期 CLI（B2-8；账本记账层，非控制层）。

用法：
  b_instance.py register --instance-id autodl-123 --vendor autodl --spec "RTX4090-24G" \
      --price-cny-per-hour 2.5 --batch-id B-...
  b_instance.py start    --instance-id autodl-123
  b_instance.py stop     --instance-id autodl-123 --amount-cny 18.6 \
      --verified-by "ssh拒连+控制台已停+账单读数"
  b_instance.py idle-sim --instance-id autodl-123        # 演练：actor=drill
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abcr.ops import cloud


def main() -> int:
    ap = argparse.ArgumentParser(description="云实例账本登记 CLI")
    ap.add_argument("--ledger-dir", default="ledger")
    sub = ap.add_subparsers(dest="action", required=True)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--instance-id", required=True)
    p_reg.add_argument("--vendor", required=True)
    p_reg.add_argument("--spec", required=True)
    p_reg.add_argument("--price-cny-per-hour", type=float, required=True)
    p_reg.add_argument("--batch-id", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--instance-id", required=True)

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--instance-id", required=True)
    p_stop.add_argument("--amount-cny", type=float, required=True)
    p_stop.add_argument("--verified-by", required=True)

    p_idle = sub.add_parser("idle-sim")
    p_idle.add_argument("--instance-id", required=True)

    a = ap.parse_args()
    ld = Path(a.ledger_dir)

    if a.action == "register":
        rec = cloud.register(a.instance_id, a.vendor, a.spec,
                             a.price_cny_per_hour, a.batch_id, ledger_dir=ld)
        print(json.dumps({"event": rec["event"], "subject_id": rec["subject_id"]}, ensure_ascii=False))
    elif a.action == "start":
        rec = cloud.start(a.instance_id, ledger_dir=ld)
        print(json.dumps({"event": rec["event"], "subject_id": rec["subject_id"]}, ensure_ascii=False))
    elif a.action == "stop":
        stopped, cost = cloud.stop(a.instance_id, a.amount_cny, a.verified_by, ledger_dir=ld)
        print(json.dumps({"instance_stopped": stopped["subject_id"],
                          "run_cost_actual": cost["amount_cny"],
                          "basis": cost["basis"]}, ensure_ascii=False))
    elif a.action == "idle-sim":
        rec = cloud.idle_sim(a.instance_id, ledger_dir=ld)
        print(json.dumps({"event": rec["event"], "actor": rec["actor"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
