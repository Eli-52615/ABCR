"""A 侧脚手架 · 模拟 B 的 faketask + deterministic_v1 产出 fixture 批次。

> 非交付物、非 R1 判据。用途：B（Operator/rig）尚未就位时，让窗口 A 能端到端
> 自验 R1 闭环（rescore → compare → auditor 出报告）。R1 演练时由 B 的真实产物替换。
> 严格遵守 faketask_spec.md（§3.10）：g03/g07 输出 fail_sample 造已知错误分布。

产出（到指定 repo_root，缺省当前 worktree）：
  data/runs/<run_id>/manifest.json   —— §3.8 AMENDMENT-31 的 22 必含键
  data/runs/<run_id>/steps.jsonl     —— 10 步（每题一步），48 字段过 validate_step
  data/runs/<run_id>/scores.jsonl    —— deterministic_v1 的 is_correct（B 侧）
  ledger/{runs_index,batches,costs}.jsonl —— 生命周期 + 批次 + 成本事件（哈希链）

建模注记（冻结契约对齐，AMENDMENT-36）：steps.jsonl 与 B 真产物同形——48 字段整记录经
ledger_ref.append_record 挂链（含 prev_hash/entry_hash 两链键，无 seq）；A 审计验收面对 steps
只过宽松 validate_step（链键豁免，裁决 #11：steps 链归 B 自验）；RunLedger 用于五条账本链；
scores.jsonl 与 B scorer 同形（纯 12 字段 JSONL 追加，不挂链）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from abcr.common import constants
from abcr.common.ledger_ref import RunLedger, append_record

BATCH_ID = "B-20260714T090000Z-0001"
BATCH_TS = "20260714T090000Z"
CONDITIONS = ["vanilla", "persona_text"]
SEEDS = [1, 2, 3]
KNOWN_WRONG = {"g03", "g07"}


def canonical(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run_config(condition: str, seed: int) -> dict:
    return {
        "benchmark": "golden10", "condition": condition, "random_seed": seed,
        "split": "dev", "item_limit_per_run": 50, "engine": "fake",
        "model_id": "fake/deterministic-v1", "protocol_ref": "W1-V0.9",
    }


def config_hash_of(cfg: dict) -> str:
    return hashlib.sha256(canonical(cfg).encode("utf-8")).hexdigest()


def run_id_of(cfg: dict) -> str:
    return f"{BATCH_TS}-{config_hash_of(cfg)[:12]}"


def split_hash_of(items: list[str], split: str = "dev") -> str:
    """§3.7：sha256(\"\\n\".join(sorted(f\"{item_id}\\t{split}\")))。"""
    lines = sorted(f"{it}\t{split}" for it in items)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def build_step(golden_item: dict, cfg: dict, run_id: str, split_hash: str,
               output_text: str) -> dict:
    """一条假 step 记录（48 字段，过 validate_step）。"""
    return {
        "schema_version": "1.0", "run_id": run_id,
        "trajectory_id": f"{run_id}-{golden_item['id']}", "step_id": 0,
        "parent_run": None, "git_commit": "fixture0000",
        "model_id": "fake/deterministic-v1", "model_revision": "fixture",
        "dtype": "none", "quantization": None, "device": "none",
        "engine": "fake", "engine_version": "0.0", "torch_version": None,
        "cuda_version": None, "benchmark": "golden10", "split_hash": split_hash,
        "item_id": golden_item["id"], "condition": cfg["condition"],
        "trait": None, "trait_pole": None, "method": None, "layer": None,
        "coefficient": None, "intervention_strength": None,
        "random_seed": cfg["random_seed"], "env_seed": None,
        "prompt_hash": hashlib.sha256(golden_item["prompt"].encode()).hexdigest(),
        "chat_template_hash": "fixture", "config_hash": config_hash_of(cfg),
        "action": "generate", "obs_hash": None, "remaining_budget": None,
        "output_text": output_text, "parsed_answer": output_text.strip(),
        "is_correct": None, "latency_ms": 200, "input_tokens": 16,
        "output_tokens": max(1, len(output_text)), "stop_reason": "fake",
        "trajectory_stop_reason": "task_done", "trait_score": None,
        "fluency_score": None, "safety_flags": [], "activation_summary": None,
        "state_snapshot_ref": None, "protocol_ref": "W1-V0.9",
        "env_lock_ref": "env/lock-fixture.txt",
    }


def build_batch(repo_root: Path) -> list[str]:
    repo_root = Path(repo_root)
    golden = json.loads((repo_root / "data" / "golden" / "golden10.json")
                        .read_text(encoding="utf-8"))["items"]
    split_hash = split_hash_of([g["id"] for g in golden])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    ledger_dir = repo_root / "ledger"
    runs_idx = RunLedger(ledger_dir, "runs_index")
    batches = RunLedger(ledger_dir, "batches")
    costs = RunLedger(ledger_dir, "costs")

    batches.append("batch_drafted", subject_id=BATCH_ID, actor="human")
    batches.append("batch_approved", subject_id=BATCH_ID, actor="human")
    batches.append("batch_dispatch_started", subject_id=BATCH_ID, actor="operator")

    run_cfgs = [run_config(c, s) for c in CONDITIONS for s in SEEDS]
    run_ids: list[str] = []
    for cfg in run_cfgs:
        rid = run_id_of(cfg)
        run_ids.append(rid)
        run_dir = repo_root / "data" / "runs" / rid
        run_dir.mkdir(parents=True, exist_ok=True)

        # steps.jsonl（48 字段整记录经 append_record 挂链——与 B 真产物同形，AMENDMENT-36）
        steps_path = run_dir / "steps.jsonl"
        if steps_path.exists():          # 重跑幂等：append_record 只增不改，先清旧链
            steps_path.unlink()
        for g in golden:
            out = g["fail_sample"] if g["id"] in KNOWN_WRONG else g["pass_sample"]
            append_record(steps_path, build_step(g, cfg, rid, split_hash, out))

        # deterministic_v1 scores.jsonl（B 侧 is_correct）
        det_lines = []
        for g in golden:
            val = 0 if g["id"] in KNOWN_WRONG else 1
            det_lines.append(json.dumps({
                "schema_version": "1.0", "run_id": rid, "item_id": g["id"],
                "trajectory_id": f"{rid}-{g['id']}", "step_id": 0,
                "condition": cfg["condition"], "random_seed": cfg["random_seed"],
                "metric_name": "is_correct", "metric_value": val,
                "scorer_id": "deterministic_v1", "scorer_version": "1.0.0",
                "scored_at": now}, ensure_ascii=False))
        (run_dir / "scores.jsonl").write_text("\n".join(det_lines) + "\n", encoding="utf-8")

        # manifest.json（22 必含键）
        manifest = {
            "run_id": rid, "config": cfg, "config_hash": config_hash_of(cfg),
            "git_commit": "fixture0000", "git_clean": True,
            "code_tree_hash": "fixture-tree-hash", "model_id": "fake/deterministic-v1",
            "model_revision": "fixture", "chat_template_hash": "fixture",
            "split_hash": split_hash, "engine": "fake", "engine_version": "0.0",
            "torch_version": None, "python_version": "3.12.13",
            "env_lock_ref": "env/lock-fixture.txt", "seeds": [cfg["random_seed"]],
            "started_at": now, "finished_at": now, "status": "COMPLETED",
            "non_citable": True, "protocol_ref": "W1-V0.9", "batch_id": BATCH_ID,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # runs_index 生命周期事件
        runs_idx.append("run_registered", subject_id=rid, batch_id=BATCH_ID)
        runs_idx.append("run_queued", subject_id=rid)
        runs_idx.append("run_started", subject_id=rid)
        runs_idx.append("step_progress", subject_id=rid, steps_done=5, items_done=5)
        runs_idx.append("step_progress", subject_id=rid, steps_done=10, items_done=10)
        runs_idx.append("run_completed", subject_id=rid)
        runs_idx.append("run_scored", subject_id=rid)

        # costs（预估 + 实耗，偏差 0）
        costs.append("run_cost_estimated", subject_id=rid, batch_id=BATCH_ID,
                     amount_cny=0.0, basis="fake/zero")
        costs.append("run_cost_actual", subject_id=rid, batch_id=BATCH_ID,
                     amount_cny=0.0, basis="fake/zero")

    batches.append("batch_settled", subject_id=BATCH_ID, actor="operator")
    return run_ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="仓库根（缺省当前 worktree）")
    args = ap.parse_args()
    run_ids = build_batch(Path(args.repo_root).resolve())
    print(f"simulated fixture batch {BATCH_ID}: {len(run_ids)} runs")
    for r in run_ids:
        print(" ", r)
    sys.exit(0)


if __name__ == "__main__":
    main()
