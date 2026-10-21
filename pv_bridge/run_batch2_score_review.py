"""Batch 2③: Score and review all 8 backfill runs under guard.

4 main runs (28 steps each): score + review
4 t0 runs (14 steps each): score + review
All deterministic (no API calls).
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from abcr.score import score_run
from abcr.review import review_run
from abcr.resource_guard import HeavyLock, get_lock_dir

BATCH2_MAIN = [
    "20260712-130600-f9cc074895de",
    "20260712-133352-0a5a38ac8bf7",
    "20260712-134715-c52d9d7295b3",
    "20260712-142226-bdcb51755747",
]

BATCH2_T0 = [
    "20260712-130600-f9cc074895de-t0",
    "20260712-133352-0a5a38ac8bf7-t0",
    "20260712-134715-c52d9d7295b3-t0",
    "20260712-142226-bdcb51755747-t0",
]

ARM_LABELS = {
    "20260712-130600-f9cc074895de": "vanilla",
    "20260712-133352-0a5a38ac8bf7": "prompt_persona",
    "20260712-134715-c52d9d7295b3": "residual_vector",
    "20260712-142226-bdcb51755747": "random_direction",
}


def check_activation_sampling(run_id: str, run_path: pathlib.Path, manifest: dict) -> dict:
    """P4: verify activation_summary sampling set equality."""
    act_dir = run_path / "activations"
    if not act_dir.exists():
        return {"status": "no_activations_dir", "ok": True}

    npz_files = list(act_dir.glob("*.npz"))
    npz_items = set()
    for f in npz_files:
        parts = f.stem.split("_")
        if len(parts) >= 2:
            npz_items.add(parts[0])

    steps_file = run_path / "steps.jsonl"
    summary_items = set()
    with open(steps_file) as f:
        for line in f:
            if not line.strip():
                continue
            step = json.loads(line)
            if step.get("activation_summary"):
                summary_items.add(step["item_id"])

    if not npz_items and not summary_items:
        return {"status": "no_activations", "ok": True}

    ok = npz_items == summary_items
    return {
        "status": "checked",
        "npz_items": sorted(npz_items),
        "summary_items": sorted(summary_items),
        "sets_equal": ok,
        "ok": ok,
    }


def main():
    ld = get_lock_dir()
    lock = HeavyLock(pkg="C", task="batch2③-score-review", lock_dir=ld)
    if not lock.acquire(nowait=True):
        owner = lock.owner_info()
        print(f"BLOCKED: heavy.lock held by {json.dumps(owner)}", file=sys.stderr)
        sys.exit(20)

    try:
        all_pass = True
        a_side_bugs = []
        results = {}

        print("=" * 60)
        print("BATCH 2③: SCORE + REVIEW (8 runs)")
        print("=" * 60)

        for run_id in BATCH2_MAIN:
            arm = ARM_LABELS.get(run_id, "?")
            print(f"\n--- MAIN {arm}: {run_id} ---")

            summary = score_run(run_id, runs_dir="runs", scores_dir="scores")
            print(f"  SCORE: {summary['n_steps']} steps, arms={list(summary['arm_summaries'].keys())}")

            report = review_run(run_id, runs_dir="runs", scores_dir="scores", review_dir="review")
            ok = report["pass"]
            print(f"  REVIEW: pass={ok}, chain_ok={report['chain_ok']}, "
                  f"errors={report['error_codes']}, mismatches={len(report['score_mismatches'])}")

            manifest_path = pathlib.Path("runs") / run_id / "manifest.json"
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

            mc = report.get("manifest_checks", {})
            print(f"  MANIFEST: config_hash_ok={mc.get('config_hash_ok')}, "
                  f"arm_purity_ok={mc.get('arm_purity_ok')}, "
                  f"protocol_ref={mc.get('protocol_ref_present')}, "
                  f"fields_complete={mc.get('manifest_fields_complete')}")

            aph = report.get("arm_prompt_hash_check", {})
            print(f"  ARM PROMPT HASH: ok={aph.get('ok')}, violations={aph.get('violations')}")

            vc = report.get("vector_artifact_check", {})
            print(f"  VECTOR ARTIFACT: ok={vc.get('ok')}")

            act_check = check_activation_sampling(
                run_id, pathlib.Path("runs") / run_id, manifest)
            print(f"  P4 ACTIVATION: {act_check['status']}, ok={act_check['ok']}")

            if not ok:
                all_pass = False
                a_side_bugs.append(f"MAIN {arm} ({run_id}): errors={report['error_codes']}")

            if not act_check["ok"]:
                all_pass = False
                a_side_bugs.append(f"MAIN {arm} ({run_id}): activation sampling mismatch")

            results[run_id] = {
                "type": "main",
                "arm": arm,
                "score_summary": summary,
                "review_pass": ok,
                "review_errors": report["error_codes"],
                "activation_p4": act_check,
            }

        for run_id in BATCH2_T0:
            base_id = run_id.replace("-t0", "")
            arm = ARM_LABELS.get(base_id, "?")
            print(f"\n--- T0 {arm}: {run_id} ---")

            summary = score_run(run_id, runs_dir="runs", scores_dir="scores")
            print(f"  SCORE: {summary['n_steps']} steps")

            report = review_run(run_id, runs_dir="runs", scores_dir="scores", review_dir="review")
            ok = report["pass"]
            print(f"  REVIEW: pass={ok}, chain_ok={report['chain_ok']}, "
                  f"errors={report['error_codes']}, mismatches={len(report['score_mismatches'])}")

            mc = report.get("manifest_checks", {})
            print(f"  MANIFEST: config_hash_ok={mc.get('config_hash_ok')}, "
                  f"protocol_ref={mc.get('protocol_ref_present')}, "
                  f"fields_complete={mc.get('manifest_fields_complete')}")

            if not ok:
                all_pass = False
                a_side_bugs.append(f"T0 {arm} ({run_id}): errors={report['error_codes']}")

            results[run_id] = {
                "type": "t0",
                "arm": arm,
                "score_summary": summary,
                "review_pass": ok,
                "review_errors": report["error_codes"],
            }

        print("\n" + "=" * 60)
        print(f"OVERALL: {'ALL PASS' if all_pass else 'FAILURES FOUND'}")
        if a_side_bugs:
            print("\nA-SIDE BUGS:")
            for bug in a_side_bugs:
                print(f"  - {bug}")
        print("=" * 60)

        return all_pass, a_side_bugs, results

    finally:
        lock.release()
        print("[guard] Lock released")


if __name__ == "__main__":
    ok, bugs, _ = main()
    if not ok:
        sys.exit(1)
