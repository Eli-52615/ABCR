"""abcr.report.blind —— 方向锁盲（确认期同步不含效应方向；契约级呈现纪律，W1 即建）。

架构位置：包C·一切效应呈现的强制闸。sync/weekly/cli 中凡呈现"条件间差异"，
必须经 render_effect；确认期剥除方向，解盲权在人（确认期结束后）。
"""
from __future__ import annotations

import os

DIRECTION_TOKENS = ("↑", "↓", "高于", "低于", "上升", "下降", "降低", "正向", "负向",
                    "更好", "更差", "提升", "优于", "劣于", ">", "<",
                    "pos>neg", "neg>pos")   # 无重复项（V1.0 曾重复"下降"，测试有防回归断言）


def current_phase() -> str:
    """exploration | confirmation；缺省 exploration（W1 全程）。"""
    return os.environ.get("ABCR_PHASE", "exploration")


def render_effect(metric_name: str, value_a: float, value_b: float,
                  label_a: str, label_b: str,
                  source_run_ids: list[str] | None = None) -> str:
    """探索期完整呈现；确认期只报量级，不报方向、不报两臂各自数值。
    source_run_ids = 本对比数字的贡献 run 列表——呈现纪律"逐数带 run_id"对
    臂级聚合数的落地：聚合数字以贡献 run_id 列表随行注明（C-R1-7 抽查可回溯）。"""
    delta = value_a - value_b
    runs = f"（runs: {','.join(source_run_ids)}）" if source_run_ids else ""
    if current_phase() == "confirmation":
        return (f"{metric_name}: |Δ|={abs(delta):.4f}"
                f"（方向锁盲：确认期不呈现方向与臂别数值，解盲由人于确认期后执行）{runs}")
    sign = ">" if delta > 0 else ("<" if delta < 0 else "=")
    return (f"{metric_name}: {label_a}={value_a:.4f} {sign} {label_b}={value_b:.4f}"
            f"（Δ={delta:+.4f}）{runs}")


def assert_no_direction(text: str) -> None:
    """确认期渲染后自检：正文含方向 token 即 raise（fail-closed，宁可不出报告不泄方向）。"""
    if current_phase() != "confirmation":
        return
    for t in DIRECTION_TOKENS:
        if t in text:
            raise ValueError(f"方向锁盲违规: 输出含方向 token {t!r}")
