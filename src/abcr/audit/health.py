"""abcr.audit.health —— 审计 item4 健康面板（从 steps 聚合五率）。

架构位置：包A·验船师侧。五率 = parse 失败率 / 拒答率 / 截断率 / 空输出率 / 重复退化率
（各 = 命中 safety_flags 的 step 数 / 总 step 数，对整批聚合）。阈值 env 可覆盖，写入报告头部。
任一超阈 → 处置 = 整批 QUARANTINED（落账由 auditor 编排，A1-3 约定2 / AMENDMENT-16）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from abcr.audit.report import AuditItem
from abcr.common import evidence_floor

# 五率阈值（默认值；env 覆盖）——对整批聚合
_FLAG_ENV = {
    "parse_fail": "ABCR_HEALTH_PARSE_FAIL_MAX",
    "refusal": "ABCR_HEALTH_REFUSAL_MAX",
    "truncated": "ABCR_HEALTH_TRUNCATED_MAX",
    "empty": "ABCR_HEALTH_EMPTY_MAX",
    "repetition": "ABCR_HEALTH_REPETITION_MAX",
}
_DEFAULTS = {"parse_fail": 0.20, "refusal": 0.20, "truncated": 0.30,
             "empty": 0.05, "repetition": 0.20}


def thresholds() -> dict[str, float]:
    """五率阈值（函数内读 env，导入期不固化——便于 monkeypatch）。"""
    return {k: float(os.environ.get(_FLAG_ENV[k], str(_DEFAULTS[k]))) for k in _DEFAULTS}


def _load_steps(run_dir: Path) -> list[dict]:
    p = run_dir / "steps.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def compute_rates(run_dirs: list[Path]) -> tuple[dict[str, float], int, dict[str, list[tuple[str, str]]]]:
    """返回 (五率, 总 step 数, 每旗命中 step 的 (run_id,item_id) 清单)。"""
    total = 0
    counts = {k: 0 for k in _DEFAULTS}
    hits: dict[str, list[tuple[str, str]]] = {k: [] for k in _DEFAULTS}
    for rd in run_dirs:
        for st in _load_steps(rd):
            total += 1
            flags = st.get("safety_flags") or []
            for flag in _DEFAULTS:
                if flag in flags:
                    counts[flag] += 1
                    hits[flag].append((st.get("run_id", "?"), st.get("item_id", "?")))
    rates = {k: (counts[k] / total if total else 0.0) for k in _DEFAULTS}
    return rates, total, hits


def health_panel(run_dirs: list[Path]) -> tuple[AuditItem, bool]:
    """返回 (AuditItem(id=4), 是否超阈)。超阈时 verdict=FAIL、disposition 标 QUARANTINED 意图。

    入口证据地板（根因②：空被当成功）：run_dirs 为空 / 全批零 step 时，五率分母为 0，
    原实现让 rates 全取 0.0 → 无一超阈 → **真 PASS**。于是"幽灵批 / 把 steps 全删掉"
    这类零证据输入反而拿到健康面板绿灯。此处在入口 require_substantive fail-closed：
    没有 step 就没有健康率可言，抛 EvidenceError 由 auditor 的 _safe 转成 item4 FAIL。
    """
    thr = thresholds()
    evidence_floor.require_substantive(len(run_dirs), "health_panel 的 run 集")
    rates, total, hits = compute_rates(run_dirs)
    evidence_floor.require_substantive(total, "health_panel 的 step 总数")
    breached = [k for k in _DEFAULTS if rates[k] > thr[k]]
    evidence = [
        f"{k} {rates[k]:.4f} (阈 {thr[k]})" + (f" ← 超阈 命中={hits[k]}" if k in breached else "")
        for k in _DEFAULTS
    ]
    evidence.append(f"总 step 数={total}")
    if breached:
        disp = f"整批 QUARANTINED（超阈: {', '.join(breached)}）"
        return AuditItem.make(4, "FAIL", evidence, disposition=disp), True
    return AuditItem.make(4, "PASS", evidence, disposition=None), False
