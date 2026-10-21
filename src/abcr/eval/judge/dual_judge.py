import csv
import json
import os
import pathlib
import random
import subprocess
import sys
import time
from typing import Optional

import numpy as np
from scipy import stats

from abcr.eval.judge.client import TraitJudge


def run_dual_judge(
    pool_csv: str,
    eval_prompt_template: str,
    n: int = 50,
    seed: int = 42,
    out_path: str = "review/judge_consistency_n50.json",
    figure_path: str = "figures/judge_consistency.png",
) -> dict:
    pool_path = pathlib.Path(pool_csv)
    if not pool_path.exists():
        print(f"Pool CSV not found: {pool_csv}", file=sys.stderr)
        sys.exit(1)

    with open(pool_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    question_col = _find_col(columns, ["question", "prompt", "instruction"])
    answer_col = _find_col(columns, ["answer", "response", "output", "completion"])

    if not question_col or not answer_col:
        print(f"Cannot find question/answer columns in {columns}", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(seed)
    sampled = rng.sample(rows, min(n, len(rows)))

    judge_ds = TraitJudge(mode="logprob_weighted")

    raw_dir = pathlib.Path(out_path).parent / "judge_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "dual_judge_n50.jsonl"

    ds_scores = []
    claude_scores = []
    sample_ids = []

    with open(raw_path, "w") as raw_f:
        for i, row in enumerate(sampled):
            question = row[question_col]
            answer = row[answer_col]
            sample_id = row.get("id", row.get("sample_id", f"s{i:03d}"))

            filled_prompt = eval_prompt_template.replace("{question}", question).replace("{answer}", answer)

            ds_result = judge_ds.score(filled_prompt)
            ds_score = ds_result.get("score")

            claude_score = _score_with_claude(filled_prompt)

            raw_entry = {
                "sample_id": sample_id,
                "deepseek_raw": ds_result,
                "claude_score": claude_score,
            }
            raw_f.write(json.dumps(raw_entry, ensure_ascii=False) + "\n")

            ds_scores.append(ds_score)
            claude_scores.append(claude_score)
            sample_ids.append(sample_id)

            if (i + 1) % 10 == 0:
                print(f"  双 judge 进度: {i+1}/{len(sampled)}")
            time.sleep(0.3)

    valid_mask = [(d is not None and c is not None) for d, c in zip(ds_scores, claude_scores)]
    ds_valid = [d for d, m in zip(ds_scores, valid_mask) if m]
    cl_valid = [c for c, m in zip(claude_scores, valid_mask) if m]

    n_valid = len(ds_valid)
    if n_valid < 5:
        print(f"Warning: only {n_valid} valid pairs for correlation", file=sys.stderr)

    pearson_r = float(np.corrcoef(ds_valid, cl_valid)[0, 1]) if n_valid >= 3 else None
    spearman_r = float(stats.spearmanr(ds_valid, cl_valid).statistic) if n_valid >= 3 else None
    mae = float(np.mean(np.abs(np.array(ds_valid) - np.array(cl_valid)))) if n_valid > 0 else None
    mean_diff = float(np.mean(np.array(ds_valid) - np.array(cl_valid))) if n_valid > 0 else None

    ds_refusal_rate = sum(1 for s in ds_scores if s is None) / len(ds_scores)
    cl_refusal_rate = sum(1 for s in claude_scores if s is None) / len(claude_scores)

    report = {
        "n": len(sampled),
        "n_valid_pairs": n_valid,
        "pearson": pearson_r,
        "spearman": spearman_r,
        "MAE": mae,
        "mean_diff": mean_diff,
        "deepseek_refusal_rate": round(ds_refusal_rate, 4),
        "claude_refusal_rate": round(cl_refusal_rate, 4),
        "deepseek_scores": ds_scores,
        "claude_scores": claude_scores,
        "sample_ids": sample_ids,
        "seed": seed,
        "pool_csv": str(pool_csv),
        "judge1": {"model": "deepseek-chat", "mode": "logprob_weighted"},
        "judge2": {"model": "claude (CLI)", "mode": "text_parse"},
        "cost": judge_ds.cost_summary(),
        "同源提示": "第二 judge（Claude）与锚 trait 工件生成模型同源，此一致性数据用于量化 DeepSeek 替换漂移，不作独立效度证明",
    }

    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    _plot_scatter(ds_valid, cl_valid, figure_path, pearson_r, spearman_r)

    print(f"双 judge 完成: n={len(sampled)}, valid={n_valid}, pearson={pearson_r}, spearman={spearman_r}, MAE={mae}")
    return report


def _find_col(columns: list[str], candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    for c in candidates:
        for col in columns:
            if c.lower() in col.lower():
                return col
    return None


def _score_with_claude(eval_prompt: str) -> Optional[float]:
    try:
        result = subprocess.run(
            [os.path.expanduser("~/.local/bin/claude"), "-p", eval_prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDE_RAW": "1"},
        )
        if result.returncode != 0:
            return None

        resp = json.loads(result.stdout)
        text = resp.get("result", "").strip()

        try:
            val = int(text)
            if 0 <= val <= 100:
                return float(val)
        except ValueError:
            for token in text.split():
                try:
                    val = int(token)
                    if 0 <= val <= 100:
                        return float(val)
                except ValueError:
                    continue
        return None
    except Exception:
        return None


def _plot_scatter(ds: list, cl: list, out_path: str,
                  pearson: Optional[float], spearman: Optional[float]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(ds, cl, alpha=0.6, s=40, edgecolors="k", linewidths=0.5)
    ax.plot([0, 100], [0, 100], "k--", alpha=0.3, label="y=x")
    ax.set_xlabel("DeepSeek Score")
    ax.set_ylabel("Claude Score")
    ax.set_title("Judge Consistency: DeepSeek vs Claude (n=50)")
    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)

    info = []
    if pearson is not None:
        info.append(f"Pearson r = {pearson:.3f}")
    if spearman is not None:
        info.append(f"Spearman ρ = {spearman:.3f}")
    if info:
        ax.text(0.05, 0.95, "\n".join(info), transform=ax.transAxes,
                fontsize=9, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.text(0.5, 0.01,
            "dev · non-citable · exploratory",
            ha="center", fontsize=8,
            fontstyle="italic", color="red")

    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)

    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    import typer
    app = typer.Typer()

    @app.command()
    def dual(pool: str, prompt: str, n: int = 50, seed: int = 42):
        run_dual_judge(pool, prompt, n=n, seed=seed)

    app()
