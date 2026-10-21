"""DEPRECATED —— top-level 判分器,已被 rig/scorer.py(生产)+ review.py(W1 门)取代,全仓零 import。

保留仅为历史/CLI 文案兼容。其原始 `空 checks → is_correct=True / score=1.0` 是根因②
(空被当满分)的一处样板;为防被当作模板复制,这里同步 fail-closed:无 checks → 分数未定义
(None),绝不给满分。任何新代码不应 import 本模块。
"""
import json
import pathlib
import statistics
import sys
from typing import Optional
from abcr.eval.deterministic.registry import run_checks
from abcr.common.evidence_floor import agreement_or_none, mean_or_none

SCORER_VERSION = "c1.0"


def score_run(run_id: str, items_path: Optional[str] = None, runs_dir: str = "runs", scores_dir: str = "scores") -> dict:
    run_path = pathlib.Path(runs_dir) / run_id
    steps_file = run_path / "steps.jsonl"
    manifest_file = run_path / "manifest.json"

    if not steps_file.exists():
        print(f"E10: steps.jsonl not found for run {run_id}", file=sys.stderr)
        sys.exit(1)

    if items_path is None:
        if manifest_file.exists():
            with open(manifest_file, "r") as f:
                manifest = json.load(f)
            items_path = manifest.get("items_path")
            if items_path is None:
                cfg = manifest.get("config", {})
                items_path = cfg.get("data", {}).get("items", "data/items/items.jsonl")
        else:
            items_path = "data/items/items.jsonl"

    items_by_id = {}
    items_file = pathlib.Path(items_path)
    if items_file.exists():
        with open(items_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    item = json.loads(line)
                    items_by_id[item["item_id"]] = item

    steps = []
    with open(steps_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))

    out_dir = pathlib.Path(scores_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    scores = []
    for step in steps:
        item_id = step.get("item_id", "")
        output_text = step.get("output_text", "")

        checks_spec = None
        if item_id in items_by_id:
            checks_spec = items_by_id[item_id].get("checks", [])
        elif "checks" in step:
            checks_spec = step["checks"]

        if checks_spec is None:
            checks_spec = []

        check_results = run_checks(output_text, checks_spec)
        n_checks = len(check_results)
        matches = sum(1 for r in check_results if r["pass"])
        # 根因②:无 checks → 分数未定义(None),is_correct=False(空 ≠ 正确),绝不给满分。
        score_val = agreement_or_none(matches, n_checks)   # None when n_checks == 0
        is_correct = (matches == n_checks) if n_checks else False

        score_entry = {
            "run_id": run_id,
            "trajectory_id": step.get("trajectory_id", ""),
            "step_id": step.get("step_id", ""),
            "item_id": item_id,
            "condition": step.get("condition", ""),
            "random_seed": step.get("random_seed", 0),
            "scorer_version": SCORER_VERSION,
            "checks": check_results,
            "is_correct": is_correct,
            "score": score_val,
        }
        scores.append(score_entry)

    scores_file = out_dir / "scores.jsonl"
    with open(scores_file, "w") as f:
        for s in scores:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    summary = _build_summary(scores, steps)
    summary_file = out_dir / "summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def _build_summary(scores: list[dict], steps: list[dict]) -> dict:
    groups: dict[str, list] = {}
    for s in scores:
        key = f"{s['condition']}|{s['random_seed']}"
        groups.setdefault(key, []).append(s)

    arm_summaries = {}
    for key, group in sorted(groups.items()):
        condition, seed = key.split("|", 1)
        correct_rates = [s["is_correct"] for s in group]
        score_vals = [s["score"] for s in group]
        # 根因②:空组均值 = None(未定义),绝不 0.0;含未定义分(None)的组也判为未定义,
        # 由下游 gate 见 None 判 FAIL,不得当 0 混入。
        undefined = any(v is None for v in score_vals)
        arm_summaries[key] = {
            "condition": condition,
            "random_seed": int(seed) if seed.isdigit() else seed,
            "n": len(group),
            "is_correct_rate": mean_or_none([int(bool(c)) for c in correct_rates]),
            "score_mean": None if undefined else mean_or_none(score_vals),
        }

    output_tokens = []
    for step in steps:
        ot = step.get("output_tokens")
        if ot is not None:
            output_tokens.append(ot)

    token_stats = {}
    if output_tokens:
        output_tokens.sort()
        token_stats = {
            "count": len(output_tokens),
            "mean": statistics.mean(output_tokens),
            "median": statistics.median(output_tokens),
            "p25": output_tokens[len(output_tokens) // 4],
            "p75": output_tokens[3 * len(output_tokens) // 4],
            "min": min(output_tokens),
            "max": max(output_tokens),
        }

    return {
        "run_id": scores[0]["run_id"] if scores else "",
        "scorer_version": SCORER_VERSION,
        "n_steps": len(scores),
        "arm_summaries": arm_summaries,
        "output_token_stats": token_stats,
    }


def main():
    import typer
    app = typer.Typer()

    @app.command()
    def score(run: str, items: Optional[str] = None):
        summary = score_run(run, items_path=items)
        print(json.dumps(summary, indent=2))

    app()


if __name__ == "__main__":
    main()
