"""C3.2 Expression Correctness Pipeline — blind_score → deblind → report.

Run with:
  OPENAI_API_KEY=<key> python pv_bridge/run_c32_exprcheck.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from abcr.eval.judge.blind import blind_score
from abcr.resource_guard import HeavyLock, get_lock_dir, check_pressure_fuse

TRAIT = "conscientiousness"
OUT_DIR = ROOT / "pv_bridge" / "out" / TRAIT
POOL_CSV = OUT_DIR / "exprcheck_pool.csv"
KEY_CSV = OUT_DIR / "exprcheck_key.csv"
SCORES_JSONL = OUT_DIR / "exprcheck_scores.jsonl"
REPORT_JSON = OUT_DIR / "exprcheck_report.json"


def load_prompts() -> tuple[str, str]:
    eval_path = ROOT / "artifacts" / "traits" / TRAIT / "eval.json"
    eval_data = json.loads(eval_path.read_text())
    trait_prompt = eval_data["eval_prompt"]

    sys.path.insert(0, str(ROOT / "third_party" / "persona_vectors" / "eval"))
    from prompts import Prompts
    coherence_prompt = Prompts["coherence_0_100"]
    return trait_prompt, coherence_prompt


def deblind(scores_jsonl: pathlib.Path, key_csv: pathlib.Path) -> list[dict]:
    import csv

    key_map = {}
    with open(key_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key_map[row["sample_id"]] = row["condition"]

    deblinded = []
    with open(scores_jsonl, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            sid = str(entry["sample_id"])
            entry["condition"] = key_map.get(sid, "UNKNOWN")
            deblinded.append(entry)
    return deblinded


def generate_report(deblinded: list[dict], score_meta: dict) -> dict:
    from collections import defaultdict
    import statistics

    by_condition: dict[str, list] = defaultdict(list)
    coherence_by_condition: dict[str, list] = defaultdict(list)

    for entry in deblinded:
        cond = entry["condition"]
        if entry.get("trait_score") is not None:
            by_condition[cond].append(entry["trait_score"])
        if entry.get("coherence_score") is not None:
            coherence_by_condition[cond].append(entry["coherence_score"])

    def stats(scores: list) -> dict:
        if not scores:
            return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
        return {
            "n": len(scores),
            "mean": round(statistics.mean(scores), 2),
            "std": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
            "min": min(scores),
            "max": max(scores),
        }

    trait_stats = {cond: stats(scores) for cond, scores in sorted(by_condition.items())}
    coherence_stats = {cond: stats(scores) for cond, scores in sorted(coherence_by_condition.items())}

    baseline_scores = by_condition.get("baseline", [])
    pos_scores = by_condition.get("steered_pos", [])
    neg_scores = by_condition.get("steered_neg", [])

    effect = {}
    if baseline_scores and pos_scores:
        effect["pos_vs_baseline"] = round(
            statistics.mean(pos_scores) - statistics.mean(baseline_scores), 2
        )
    if baseline_scores and neg_scores:
        effect["neg_vs_baseline"] = round(
            statistics.mean(neg_scores) - statistics.mean(baseline_scores), 2
        )
    if pos_scores and neg_scores:
        effect["pos_vs_neg"] = round(
            statistics.mean(pos_scores) - statistics.mean(neg_scores), 2
        )

    return {
        "trait": TRAIT,
        "n_total": len(deblinded),
        "n_scored": sum(len(v) for v in by_condition.values()),
        "trait_by_condition": trait_stats,
        "coherence_by_condition": coherence_stats,
        "effect_sizes": effect,
        "score_meta": score_meta,
        "label": "exploratory / rig-validation",
        "citable": False,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main():
    if not POOL_CSV.exists():
        print(f"ERROR: Pool CSV not found: {POOL_CSV}", file=sys.stderr)
        sys.exit(1)
    if not KEY_CSV.exists():
        print(f"ERROR: Key CSV not found: {KEY_CSV}", file=sys.stderr)
        sys.exit(1)

    ld = get_lock_dir()
    lock = HeavyLock(pkg="C", task="C3.2-exprcheck-score", lock_dir=ld)
    if not lock.acquire(nowait=True):
        owner = lock.owner_info()
        print(f"BLOCKED: heavy.lock held by {json.dumps(owner)}", file=sys.stderr)
        sys.exit(20)

    try:
        print(f"[C3.2] Starting expression correctness scoring")
        print(f"[C3.2] Pool: {POOL_CSV}")
        print(f"[C3.2] Output: {SCORES_JSONL}")

        trait_prompt, coherence_prompt = load_prompts()
        print(f"[C3.2] Trait prompt loaded ({len(trait_prompt)} chars)")
        print(f"[C3.2] Coherence prompt loaded ({len(coherence_prompt)} chars)")

        score_meta = blind_score(
            pool_csv=str(POOL_CSV),
            eval_prompt_template=trait_prompt,
            out_jsonl=str(SCORES_JSONL),
            coherence_prompt_template=coherence_prompt,
            mode="text_parse",
            seed=42,
            prompt_source={
                "trait_eval": f"artifacts/traits/{TRAIT}/eval.json:eval_prompt",
                "coherence": "third_party/persona_vectors/eval/prompts.py:3-21",
            },
        )
        print(f"[C3.2] Scoring complete: {score_meta['n']} samples, "
              f"{score_meta['cost']['calls']} API calls")
        print(f"[C3.2] Trait refusals: {score_meta['n_trait_refusal']}, "
              f"Coherence refusals: {score_meta['n_coherence_refusal']}")

        print(f"[C3.2] Deblinding with key: {KEY_CSV}")
        deblinded = deblind(SCORES_JSONL, KEY_CSV)

        deblinded_path = OUT_DIR / "exprcheck_deblinded.jsonl"
        with open(deblinded_path, "w") as f:
            for entry in deblinded:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"[C3.2] Deblinded: {deblinded_path} ({len(deblinded)} entries)")

        report = generate_report(deblinded, score_meta)
        REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"[C3.2] Report: {REPORT_JSON}")
        print(f"[C3.2] Effect sizes: {json.dumps(report['effect_sizes'])}")
        print(f"\n{'='*60}")
        print(f"TRAIT SCORES BY CONDITION:")
        for cond, st in report["trait_by_condition"].items():
            print(f"  {cond:12s}: mean={st['mean']}, std={st['std']}, n={st['n']}")
        print(f"\nCOHERENCE SCORES BY CONDITION:")
        for cond, st in report["coherence_by_condition"].items():
            print(f"  {cond:12s}: mean={st['mean']}, std={st['std']}, n={st['n']}")
        print(f"{'='*60}")

    finally:
        lock.release()
        print("[C3.2] Lock released")


if __name__ == "__main__":
    main()
