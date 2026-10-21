#!/usr/bin/env python3
"""scripts/b_flip_demo.py — steering 行为翻转 demo 生成器（B2-11）。

输入：官方 eval_persona 三份产物 CSV（baseline / +coef / -coef，列：
question,prompt,answer,question_id,{trait},coherence）。
输出：demos/flip_demo_<trait>.md —— 按 trait 分差 top-k 题并排展示。
用法：python scripts/b_flip_demo.py --trait optimistic \
        --baseline eval_persona_eval/.../optimistic.csv \
        --pos steer_pos.csv --neg steer_neg.csv --topk 3
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trait", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--pos", required=True)
    ap.add_argument("--neg", required=True)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    t = a.trait
    base = pd.read_csv(a.baseline).groupby("question_id").first()
    pos = pd.read_csv(a.pos).groupby("question_id").first()
    neg = pd.read_csv(a.neg).groupby("question_id").first()
    common = base.index.intersection(pos.index).intersection(neg.index)
    gap = (pos.loc[common, t] - neg.loc[common, t]).sort_values(ascending=False)
    lines = [f"# Steering 翻转 demo · trait={t}", "",
             "> exploratory / rig-validation —— 演示素材，不构成任何假设的证据", ""]
    for qid in gap.index[: a.topk]:
        lines += [f"## {qid}（trait 分：+coef {pos.loc[qid, t]:.0f} ｜ baseline "
                  f"{base.loc[qid, t]:.0f} ｜ -coef {neg.loc[qid, t]:.0f}）",
                  f"**题目**：{base.loc[qid, 'question']}", "",
                  f"**正向注入**：{pos.loc[qid, 'answer']}", "",
                  f"**基线**：{base.loc[qid, 'answer']}", "",
                  f"**负向注入**：{neg.loc[qid, 'answer']}", ""]
    out = Path(a.out or f"demos/flip_demo_{t}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
