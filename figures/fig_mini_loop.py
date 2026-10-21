import json
import pathlib
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_scores(scores_dir: str, run_id: str) -> list[dict]:
    path = pathlib.Path(scores_dir) / run_id / "scores.jsonl"
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def load_steps(runs_dir: str, run_id: str) -> list[dict]:
    path = pathlib.Path(runs_dir) / run_id / "steps.jsonl"
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def main(runset_path: str = "runs/MINILOOP-RUNSET.json",
         runs_dir: str = "runs", scores_dir: str = "scores",
         out_path: str = "figures/mini_loop.png"):

    with open(runset_path) as f:
        runset = json.load(f)

    main_runs = runset.get("main_runs", [])
    if not main_runs:
        print("No main_runs in MINILOOP-RUNSET.json", file=sys.stderr)
        sys.exit(1)

    arm_data = {}
    arm_tokens = {}

    for run_id in main_runs:
        scores = load_scores(scores_dir, run_id)
        steps = load_steps(runs_dir, run_id)

        step_tokens = {}
        for step in steps:
            key = (step.get("trajectory_id", ""), step.get("step_id", ""))
            step_tokens[key] = step.get("output_tokens", 0)

        for s in scores:
            cond = s.get("condition", "unknown")
            seed = s.get("random_seed", 0)
            arm_data.setdefault(cond, {}).setdefault(seed, []).append(s["is_correct"])

            key = (s.get("trajectory_id", ""), s.get("step_id", ""))
            tokens = step_tokens.get(key, 0)
            arm_tokens.setdefault(cond, []).append(tokens)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    colors = plt.cm.Set2(np.linspace(0, 1, max(len(arm_data), 4)))
    arm_names = sorted(arm_data.keys())

    for i, arm in enumerate(arm_names):
        seeds = sorted(arm_data[arm].keys())
        rates = []
        for seed in seeds:
            correct_list = arm_data[arm][seed]
            rate = sum(correct_list) / len(correct_list) if correct_list else 0
            rates.append(rate)
        ax1.scatter(seeds, rates, label=arm, color=colors[i], s=60, alpha=0.8, zorder=3)
        mean_rate = np.mean(rates)
        ax1.axhline(mean_rate, color=colors[i], linestyle="--", alpha=0.4)

    ax1.set_xlabel("Random Seed")
    ax1.set_ylabel("is_correct Rate")
    ax1.set_title("Panel 1: Per-Seed Score by Arm")
    ax1.legend(loc="best", fontsize=8)
    ax1.set_ylim(-0.05, 1.05)
    ax1.grid(True, alpha=0.3)

    positions = []
    labels = []
    data_lists = []
    for i, arm in enumerate(arm_names):
        tokens = arm_tokens.get(arm, [])
        if tokens:
            positions.append(i)
            labels.append(arm)
            data_lists.append(tokens)

    if data_lists:
        bp = ax2.boxplot(data_lists, positions=positions, widths=0.6, patch_artist=True)
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)

    ax2.set_xticks(positions)
    ax2.set_xticklabels(labels, rotation=15, ha="right")
    ax2.set_ylabel("Output Tokens")
    ax2.set_title("Panel 2: Output Length Distribution by Arm")
    ax2.grid(True, alpha=0.3)

    fig.suptitle(
        "rig-validation run — NOT evidence · non-citable · dev split · exploratory",
        fontsize=10, fontstyle="italic", color="red", y=0.02,
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.98])

    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"主图已保存: {out_path}")


if __name__ == "__main__":
    import typer
    app = typer.Typer()

    @app.command()
    def plot(runset: str = "runs/MINILOOP-RUNSET.json", out: str = "figures/mini_loop.png"):
        main(runset_path=runset, out_path=out)

    app()
