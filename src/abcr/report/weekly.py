"""abcr.report.weekly —— 周证据对象包生成器（契约 §C2-4）。

架构位置：包C·对外证据出口。模板实例化 + 从 views/triage 拉数字（人工补图与叙述）。
第一戒律：一切数字出自账本视图，带 run_id + exploratory 标注；确认期效应经 blind
锁盲（本生成器对效应区块调 assert_no_direction——C2-5 接线点之一）。

模板权威 = reports/weekly/TEMPLATE-weekly-evidence.md（源交付物，头注释五禁令逐字）；
文件缺失时回退到本模块内嵌 _EMBEDDED_TEMPLATE（内容逐字同一）。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from abcr.common import evidence_floor
from abcr.governor import triage as triagemod
from abcr.report import blind, ledgerio, views

TEMPLATE_REL = "reports/weekly/TEMPLATE-weekly-evidence.md"
CANONICAL_SCORER = "deterministic_v1"   # 效应对比只用规范确定性 scorer（防同 condition 两 scorer 自比）

_EMBEDDED_TEMPLATE = """<!--
对外禁令（全部禁止，违者撤回重写）：
1. 只发愿景不发证据；2. 把 exploratory 数字当结论表述；
3. 用 judge 单一分数宣称"突破"；4. 只晒代码量/工程量；5. 藏负结果。
一切数字必须出自账本视图（report.cli / views），带 run_id 与 exploratory / rig-validation 标注。
确认期（ABCR_PHASE=confirmation）本模板输出不得含效应方向（blind.render_effect 强制）。
-->

# 周证据对象包 · {{WEEK}}

> 数字均为 exploratory / rig-validation；mini 环产出不构成任何假设的证据。

## ① 一张图

{{FIGURE}}

> 图注：数据来源批次 {{SOURCE_BATCHES}}；rig-validation, not evidence。（人工补/核图路径到 figures/ 与图注。）

{{EFFECT}}

## ② 一段可复现说明

{{REPRO}}

## ③ 本周失败

{{FAILURES}}

## ④ 下周假设

{{HYPOTHESES}}
"""


def _load_template(repo_root: Path) -> str:
    tp = Path(repo_root) / TEMPLATE_REL
    if tp.exists():
        return tp.read_text(encoding="utf-8")
    return _EMBEDDED_TEMPLATE


def _source_batches(ledger_dir: Path) -> str:
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    return "、".join(sorted(batches)) if batches else "（本周账本无批次）"


def _effect_block(ledger_dir: Path, runs_dir: Path) -> str:
    """效应速览：≥2 条件的 is_correct 均值差经 blind.render_effect（确认期锁盲）。
    对效应区块调 assert_no_direction（C2-5 接线；确认期含方向 token 即 raise）。"""
    # fail-closed：只认规范 scorer，且按 condition 去重 → 两臂必为【不同 condition】。
    # 删除旧的"回退丢 scorer 过滤"分支：它会把同一 condition 的两个 scorer 判分不一致
    # 当成臂间效应呈现（验船师问运动员的一种）。同臂样本不足亦不出对比。
    ov = views.overview(ledger_dir, runs_dir)
    rows = [r for r in ov["per_condition"]
            if r.get("metric_name") == "is_correct"
            and r.get("scorer_id") == CANONICAL_SCORER
            and isinstance(r.get("mean_value"), (int, float))]
    by_cond: dict = {}
    for r in rows:
        by_cond.setdefault(r.get("condition"), r)
    arms = [r for c, r in by_cond.items() if c is not None]
    if len(arms) < 2:
        return f"> 效应速览：本周（{CANONICAL_SCORER}）不同 condition 数 <2，无臂间对比。"
    a, b = arms[0], arms[1]
    try:
        evidence_floor.require_substantive(int(a.get("n") or 0), "weekly effect arm A")
        evidence_floor.require_substantive(int(b.get("n") or 0), "weekly effect arm B")
    except evidence_floor.EvidenceError:
        return f"> 效应速览：本周（{CANONICAL_SCORER}）臂样本不足，无臂间对比。"
    eff = blind.render_effect("is_correct", a["mean_value"], b["mean_value"],
                              a["condition"], b["condition"])
    blind.assert_no_direction(eff)   # 确认期锁盲自检（探索期空操作）
    return f"> 效应速览（{blind.current_phase()}）：{eff}"


def _failures_block(ledger_dir: Path, runs_dir: Path, envdir: Path,
                    alerts_dir: Path, now: datetime) -> str:
    """③ 本周失败：triage 失败桶逐条 run_id + 有效负结果。此节不可为空——
    实在没有写「本周无失败记录」并附账本查询命令为证。"""
    buckets = triagemod.triage(ledger_dir, envdir, alerts_dir, now)
    fails = buckets.get("失败未收敛", []) + buckets.get("停摆", [])
    lines: list[str] = []
    for e in fails:
        sev = f"[{e['severity']}] " if e.get("severity") else ""
        lines.append(f"- {sev}`{e['subject_id']}` — {e['evidence']}")
    # 已收敛偏差（断点续跑）也照记（有效负结果的一种呈现）
    for e in buckets.get("已收敛偏差", []):
        lines.append(f"- （已收敛偏差）`{e['subject_id']}` — {e['evidence']}")
    if not lines:
        return ("- 本周无失败记录。\n"
                "- 账本查询为证：`PYTHONPATH=src python -m abcr.governor.triage "
                "--ledger-dir ledger`（失败未收敛/停摆桶为空）。")
    return "\n".join(lines)


def _repro_block(ledger_dir: Path) -> str:
    batches = ledgerio.fold_subjects(
        ledgerio.read_chain_merged(ledger_dir, "batches"), ledgerio.BATCH_EVENT_STATE)
    settled = [bid for bid, rec in sorted(batches.items())
               if rec["state"] in ("SETTLED", "AUDITED", "REPORTED")]
    bid = settled[0] if settled else (sorted(batches)[0] if batches else "<batch_id>")
    return ("\n".join([
        f"复现包：`demos/repro-{bid}/`（`PYTHONPATH=src python -m abcr.report.repro_pack "
        f"--batch {bid} --out demos/` 出包）。",
        "复算（仓库外，无需权重）：",
        "```bash",
        "python tools/rescore_standalone.py --pack . --report rescore_report.json",
        "```",
        "预期 deterministic_v1 / rescore_v1 两组一致率均 == 1.0（见 ACCEPTANCE.md 四步）。",
    ]))


def render(week: str, ledger_dir: Path, runs_dir: Path, envdir: Path,
           alerts_dir: Path, repo_root: Path, now: datetime) -> str:
    tmpl = _load_template(repo_root)
    figure = "（人工补图：figures/{}.png——三臂逐 seed is_correct + 长度分布双联图）".format(week)
    hyp = ("- （人工填：下周要证伪什么，一句一条）\n"
           "- （例：persona_text 臂 is_correct 与 vanilla 无差异——待更大题量证伪/证实）")
    out = (tmpl
           .replace("{{WEEK}}", week)
           .replace("{{FIGURE}}", figure)
           .replace("{{SOURCE_BATCHES}}", _source_batches(ledger_dir))
           .replace("{{EFFECT}}", _effect_block(ledger_dir, runs_dir))
           .replace("{{REPRO}}", _repro_block(ledger_dir))
           .replace("{{FAILURES}}", _failures_block(ledger_dir, runs_dir, envdir, alerts_dir, now))
           .replace("{{HYPOTHESES}}", hyp))
    return out


def run(week: str, out_dir: Path, ledger_dir: Path = Path("ledger"),
        runs_dir: Path = Path("data/runs"), envdir: Path = Path("configs/envelopes"),
        alerts_dir: Path = Path("state/alerts"), repo_root: Path = Path("."),
        now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    md = render(week, Path(ledger_dir), Path(runs_dir), Path(envdir), Path(alerts_dir),
                Path(repo_root), now)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"weekly-{week}-evidence.md"
    out.write_text(md, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="abcr.report.weekly", description="周证据对象包生成器（§C2-4）")
    ap.add_argument("--week", required=True, help="ISO 周，如 2026-W29")
    ap.add_argument("--out", default="reports/weekly/")
    ap.add_argument("--ledger-dir", default="ledger")
    ap.add_argument("--runs-dir", default="data/runs")
    ap.add_argument("--envdir", default="configs/envelopes")
    ap.add_argument("--alerts-dir", default="state/alerts")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    out = run(args.week, Path(args.out), Path(args.ledger_dir), Path(args.runs_dir),
              Path(args.envdir), Path(args.alerts_dir), Path(args.repo_root))
    print(f"已生成: {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
