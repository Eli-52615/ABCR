#!/usr/bin/env python3
"""scripts/c_shadow_graduation.py —— 影子模式毕业检查器（§7.2，只交检查器不接线）。

毕业判据（冻结，§7.2 / C2-1 逐字同一）：累计 **20 个 run** 的 shadow 批次记录中，
草案与人工决策**零关键差异**（key_difference==false）**且**这些批次的 auditor 报告全绿。
达成后才允许讨论开启信封 auto_dispatch；确认期发射恒人工，不受此开关影响。

数据源：
  · plans/shadow/*.shadow.json —— 逐批 key_difference（C2-1 产物）；
  · run↔batch 关联走 runs_index 的 run_registered.batch_id（AMENDMENT-19；未启动 run
    以信封 run_configs 对账），装载经 ledgerio.read_chain_merged 含云链段；
  · reports/audit/<batch_id>.json 的整体 verdict（A 的报告；键形 = `overall`——本仓 A 的
    abcr.audit.report.AuditReport.to_dict() 实物核实，跨包接口一致）。PASS 才计入。

打印 GRADUATED（≥20 run 且全绿）或 NOT_GRADUATED + 逐批证据行。不接线、不写账本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许脚本直跑：把 <repo>/src 挂上（若调用方已设 PYTHONPATH 则无害）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abcr.governor import shadow  # noqa: E402
from abcr.report import ledgerio  # noqa: E402

GRADUATION_RUN_THRESHOLD = 20


def _batch_run_count(repo_root: Path, batch_id: str) -> int:
    """该批 run 数：runs_index run_registered(batch_id) 折叠；为 0 则以信封 run_configs 对账。"""
    events = ledgerio.read_chain_merged(repo_root / "ledger", "runs_index")
    started = {e.get("subject_id") for e in events
               if e.get("event") == "run_registered" and e.get("batch_id") == batch_id
               and e.get("subject_id")}
    if started:
        return len(started)
    env_p = repo_root / "configs" / "envelopes" / f"{batch_id}.json"
    if env_p.exists():
        try:
            return len(json.loads(env_p.read_text(encoding="utf-8")).get("run_configs", []))
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _audit_verdict(repo_root: Path, batch_id: str) -> str:
    """A 的审计报告 overall；缺报告 → 'MISSING'，坏报告 → 'UNREADABLE'。"""
    ap = repo_root / "reports" / "audit" / f"{batch_id}.json"
    if not ap.exists():
        return "MISSING"
    try:
        return str(json.loads(ap.read_text(encoding="utf-8")).get("overall", "UNKNOWN"))
    except Exception:  # noqa: BLE001
        return "UNREADABLE"


def graduation_status(repo_root: Path) -> dict:
    """扫 plans/shadow/*.shadow.json，对 key_difference==false 批次统计 run 数与审计 verdict。"""
    repo_root = Path(repo_root)
    shadow_dir = repo_root / "plans" / "shadow"
    batches: list[dict] = []
    for sp in sorted(shadow_dir.glob("*.shadow.json")) if shadow_dir.exists() else []:
        try:
            rec = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        bid = rec.get("batch_id", sp.stem.replace(".shadow", ""))
        key_diff = bool(rec.get("key_difference"))
        runs = _batch_run_count(repo_root, bid)
        verdict = _audit_verdict(repo_root, bid)
        # 外部锚校验（对抗根因①：plans/shadow/*.shadow.json 可手写伪造）——
        # 只有 seal 进仓级规范锚存储、且内容未被篡改的记录才可能计入毕业。
        seal_ok, seal_reason = shadow.verify_seal(rec)
        batches.append({"batch_id": bid, "key_difference": key_diff,
                        "runs": runs, "audit_verdict": verdict,
                        "seal_ok": seal_ok, "seal_reason": seal_reason,
                        "counts_toward_graduation":
                            seal_ok and (not key_diff) and verdict == "PASS"})
    # 计入毕业的批次 = 已外部锚 且 零关键差异 且 审计 PASS
    qualifying = [b for b in batches if b["counts_toward_graduation"]]
    total_runs = sum(b["runs"] for b in qualifying)
    # 全绿：所有【已锚且零关键差异】批次的审计都 PASS（任一非 PASS → 未全绿）
    zero_key = [b for b in batches if b["seal_ok"] and not b["key_difference"]]
    all_green = bool(zero_key) and all(b["audit_verdict"] == "PASS" for b in zero_key)
    graduated = total_runs >= GRADUATION_RUN_THRESHOLD and all_green
    return {"graduated": graduated, "total_runs": total_runs,
            "threshold": GRADUATION_RUN_THRESHOLD, "all_green": all_green,
            "batches": batches, "qualifying": [b["batch_id"] for b in qualifying]}


def render(status: dict) -> str:
    head = "GRADUATED" if status["graduated"] else "NOT_GRADUATED"
    lines = [f"{head} — 零关键差异累计 {status['total_runs']}/{status['threshold']} run；"
             f"审计全绿={status['all_green']}"]
    if not status["batches"]:
        lines.append("- （plans/shadow/ 无 shadow 记录）")
    for b in status["batches"]:
        mark = "✓计入" if b["counts_toward_graduation"] else "✗不计"
        kd = "关键差异" if b["key_difference"] else "零关键差异"
        seal = "已锚" if b.get("seal_ok") else f"无锚/失配({b.get('seal_reason', '?')})"
        lines.append(f"- [{mark}] {b['batch_id']}: {kd}; runs={b['runs']}; "
                     f"审计={b['audit_verdict']}; 外部锚={seal}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(prog="c_shadow_graduation", description="影子模式毕业检查器（§7.2）")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    status = graduation_status(Path(args.repo_root))
    sys.stdout.write(render(status))
    return 0 if status["graduated"] else 1


if __name__ == "__main__":
    sys.exit(main())
