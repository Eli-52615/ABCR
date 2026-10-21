"""ABCR experiment runner — config → preflight → generate → steps.jsonl."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch
import typer
import yaml

from abcr.logging.errors import (
    AbcrError, die,
    E01_PREFLIGHT_GIT_DIRTY, E02_REVISION_MISMATCH, E03_TEMPLATE_HASH_MISMATCH,
    E04_SPLIT_HASH_MISMATCH, E05_CONFIG_INVALID, E06_ARM_PURITY_VIOLATION,
    E09_RESUME_CONFLICT, E12_MANIFEST_INCOMPLETE,
    E19_RESOURCE_PRESSURE, E20_RESOURCE_LEASE_BUSY, E21_PREFLIGHT_RESOURCE_FAIL,
)
from abcr.logging.schema import SCHEMA_VERSION, canonical_json
from abcr.logging.writer import StepWriter
from abcr.logging.manifest import write_manifest, finalize_manifest, _arm_purity
from abcr.interventions.api import get_intervention

app = typer.Typer()

E06_VECTOR_KEYS = {"vector_dir", "vector_path", "match_to", "direction_seed", "target_norm"}
E06_PERSONA_KEYS = {"artifact", "instruction_index"}


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _load_config(config_path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(config_path).read_text())


def _load_models_yaml() -> dict[str, Any]:
    return yaml.safe_load(Path("configs/models.yaml").read_text())["models"]


def _deterministic_sample(item_id: str, rate: float) -> bool:
    h = int(hashlib.sha256(item_id.encode()).hexdigest()[:8], 16)
    return (h % 1000) < int(rate * 1000)


def _validate_config(config: dict[str, Any]) -> None:
    required = ["model_key", "condition", "intervention", "data", "decoding"]
    for k in required:
        if k not in config:
            raise AbcrError(E05_CONFIG_INVALID, f"missing config key: {k}")
    valid_conditions = {"vanilla", "prompt_persona", "residual_vector", "random_direction"}
    if config["condition"] not in valid_conditions:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid condition: {config['condition']}")
    valid_model_keys = {"tinyqwen", "qwen2.5-0.5b-instruct", "qwen2.5-3b-instruct", "qwen2.5-7b-instruct"}
    if config["model_key"] not in valid_model_keys:
        raise AbcrError(E05_CONFIG_INVALID, f"invalid model_key: {config['model_key']}")
    data = config["data"]
    for dk in ["family", "items", "split_file", "split"]:
        if dk not in data:
            raise AbcrError(E05_CONFIG_INVALID, f"missing data.{dk}")
    dec = config["decoding"]
    for dk in ["temperature", "seeds", "max_new_tokens"]:
        if dk not in dec:
            raise AbcrError(E05_CONFIG_INVALID, f"missing decoding.{dk}")


def _check_arm_purity(config: dict[str, Any]) -> None:
    """委托给 manifest._arm_purity 的白名单实现（F-INT-05 / F-ARM-01）：
    早期门与 write_manifest 使用同一 fail-closed 白名单，杜绝旧黑名单被
    嵌套 dict / 改名键 / 自由文本人格引用旁路。凡能通过 write_manifest 的合法
    intervention 都能通过此门（同函数同输入）。"""
    _arm_purity(config.get("intervention", {}))


def _preflight(config: dict[str, Any], dev: bool) -> tuple[bool, dict[str, str]]:
    meta: dict[str, str] = {}
    citable = True

    # E01: git clean
    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        if status:
            if dev:
                citable = False
            else:
                raise AbcrError(E01_PREFLIGHT_GIT_DIRTY, "working tree not clean")
    except FileNotFoundError:
        if not dev:
            raise AbcrError(E01_PREFLIGHT_GIT_DIRTY, "git not available")
        citable = False

    # E02: model revision
    models = _load_models_yaml()
    model_key = config["model_key"]
    if model_key not in models:
        raise AbcrError(E02_REVISION_MISMATCH, f"model_key {model_key} not in models.yaml")
    model_info = models[model_key]
    model_id = model_info["model_id"]
    expected_rev = model_info["revision"]

    if model_key == "tinyqwen":
        if expected_rev != "local-fixture-seed0":
            raise AbcrError(E02_REVISION_MISMATCH, "tinyqwen revision must be local-fixture-seed0")
    else:
        model_path = Path(model_id)
        if model_path.exists() and (model_path / "config.json").exists():
            actual_rev = hashlib.sha256((model_path / "config.json").read_bytes()).hexdigest()[:12]
            if actual_rev != expected_rev:
                raise AbcrError(E02_REVISION_MISMATCH,
                                f"model {model_key}: expected rev {expected_rev}, got {actual_rev}")

    meta["model_id"] = model_id
    meta["model_revision"] = expected_rev

    # E03: template hash
    template_dir = Path(f"configs/templates/{model_key}")
    if template_dir.exists():
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(model_id)
        tpl = tok.chat_template or ""
        actual_hash = _sha256_str(tpl)
        expected_hash = (template_dir / "chat_template.hash").read_text().strip()
        if actual_hash != expected_hash:
            raise AbcrError(E03_TEMPLATE_HASH_MISMATCH,
                            f"template hash mismatch for {model_key}")
        meta["chat_template_hash"] = actual_hash
    else:
        raise AbcrError(E03_TEMPLATE_HASH_MISMATCH, f"no template dir for {model_key}")

    # E04: split hash
    split_file = Path(config["data"]["split_file"])
    if not split_file.exists():
        raise AbcrError(E04_SPLIT_HASH_MISMATCH, f"split file not found: {split_file}")
    actual_split_hash = _sha256_file(split_file)
    sha_file = split_file.with_suffix(split_file.suffix + ".sha256")
    if sha_file.exists():
        expected_split_hash = sha_file.read_text().strip()
        if actual_split_hash != expected_split_hash:
            raise AbcrError(E04_SPLIT_HASH_MISMATCH, "split file hash mismatch")
    meta["split_hash"] = actual_split_hash

    # E05: config validation
    _validate_config(config)

    # E06: arm purity
    _check_arm_purity(config)

    return citable, meta


def _load_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    items_path = Path(config["data"]["items"])
    split_path = Path(config["data"]["split_file"])
    target_split = config["data"]["split"]

    split_data = json.loads(split_path.read_text())
    assignment = split_data["assignment"]

    # F-A-08: bind the items file to the split it was built from. The split
    # records items_source_sha256; if the items file on disk does not hash to
    # that value, the prompt/answer contents have drifted from what the split
    # (and therefore this run's provenance) claims — fail closed.
    expected_items_sha = split_data.get("items_source_sha256")
    if not expected_items_sha:
        raise AbcrError(
            E04_SPLIT_HASH_MISMATCH,
            f"split {split_path} missing items_source_sha256; cannot bind items file",
        )
    actual_items_sha = hashlib.sha256(items_path.read_bytes()).hexdigest()
    if actual_items_sha != expected_items_sha:
        raise AbcrError(
            E04_SPLIT_HASH_MISMATCH,
            f"items file sha256 {actual_items_sha[:12]} != "
            f"split.items_source_sha256 {expected_items_sha[:12]} ({items_path})",
        )

    items = []
    for line in items_path.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        # F-A-08: for prompt-hash-scheme item_ids (16 lowercase hex, the id
        # scheme emitted by build_items), recompute the id from the prompt and
        # reject any item whose id no longer matches its prompt. Non-hex ids
        # (e.g. fixture ids like fix_001) are left to the SHA gate above.
        iid = item["item_id"]
        if re.fullmatch(r"[0-9a-f]{16}", iid):
            recomputed = hashlib.sha256(item["prompt"].encode()).hexdigest()[:16]
            if recomputed != iid:
                raise AbcrError(
                    E04_SPLIT_HASH_MISMATCH,
                    f"item_id {iid} != sha256(prompt)[:16] {recomputed}; "
                    "items file prompt/id binding tampered",
                )
        if assignment.get(iid) == target_split:
            items.append(item)

    items.sort(key=lambda x: x["item_id"])
    limit = config.get("data", {}).get("limit")
    if limit:
        items = items[:limit]

    return items


def _generate(model, tokenizer, prompt: str, seed: int, config: dict[str, Any]) -> tuple[str, str, int, int, float]:
    dec = config["decoding"]
    temperature = dec["temperature"]
    max_new_tokens = dec["max_new_tokens"]

    torch.manual_seed(seed)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]

    t0 = time.monotonic()
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            do_sample=(temperature > 0),
            temperature=temperature if temperature > 0 else None,
            top_p=1.0 if temperature > 0 else None,
            max_new_tokens=max_new_tokens,
            pad_token_id=tokenizer.eos_token_id,
        )
    latency_ms = (time.monotonic() - t0) * 1000

    new_tokens = out[0][input_len:]
    output_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

    if out[0][-1] == tokenizer.eos_token_id:
        stop_reason = "eos"
    elif len(new_tokens) >= max_new_tokens:
        stop_reason = "max_new_tokens"
    else:
        # F-A-15 fail-closed: generation stopped without an EOS token and
        # without hitting max_new_tokens — an unknown/anomalous termination
        # (e.g. StoppingCriteria, truncated generate, backend cut). The old
        # code back-filled this as "eos", silently laundering a truncated /
        # anomalous run into a clean-stop signal (the §12.3 mutation the
        # test suite requires killed). Emit "error" (a member of both
        # logging.VALID_STOP_REASONS and ledger STOP_REASONS) so downstream
        # audit sees the anomaly instead of a false clean stop.
        stop_reason = "error"

    return output_text, stop_reason, input_len, len(new_tokens), latency_ms


def _run_id_from_config(config: dict[str, Any], suffix: str = "") -> str:
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    config_hash = hashlib.sha256(canonical_json(config).encode()).hexdigest()[:12]
    run_id = f"{ts}-{config_hash}"
    if suffix:
        run_id = f"{run_id}-{suffix}"
    return run_id


# Canonical condition -> effective intervention method. A run's declared
# condition must match the method actually built from its intervention spec,
# otherwise a "vanilla" arm can silently carry a steering hook (F-INT-03).
CONDITION_METHOD = {
    "vanilla": "none",
    "prompt_persona": "prompt_persona",
    "residual_vector": "residual_vector",
    "random_direction": "random_direction",
}


def _safe_run_dir(run_id: str) -> Path:
    """Resolve runs/<run_id> and fail closed on any path escape (F-A-02).

    run_id is attacker/typo-controllable (via --resume / --repair / generated).
    An absolute path, ``..`` traversal, or symlink that resolves outside runs/
    would let the runner create or overwrite files anywhere on disk. We require
    the realpath-resolved directory to be a direct child of the resolved runs/
    root; anything else is rejected with a non-zero exit.
    """
    if not run_id or not run_id.strip():
        die(E05_CONFIG_INVALID, "empty run_id")
    runs_root = Path("runs").resolve()
    candidate = Path("runs") / run_id
    # Path('runs') / '/abs' collapses to '/abs'; resolve() also folds '..' and
    # follows symlinks so a symlinked run dir cannot smuggle us out of runs/.
    resolved = candidate.resolve()
    try:
        resolved.relative_to(runs_root)
    except ValueError:
        die(E05_CONFIG_INVALID, f"run_id escapes runs/: {run_id!r}")
    if resolved.parent != runs_root:
        die(E05_CONFIG_INVALID,
            f"run_id must be a direct child of runs/, got {run_id!r}")
    return resolved


def _assert_resume_consistent(run_dir: Path, cfg: dict[str, Any],
                              split_hash: str) -> None:
    """Reject a resume whose config drifted from the existing manifest (F-A-01).

    Resuming must never rewrite the manifest with a different config, nor append
    steps from a different experimental arm into the same run/hash-chain. If any
    provenance-defining dimension (full config hash, condition, model, split,
    seeds, split_hash) differs from what the run was started with, fail closed.
    """
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        # Nothing to conflict with (e.g. resuming a run dir that has no manifest
        # yet). Treat as a fresh start rather than silently overwriting later.
        return
    try:
        existing = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AbcrError(E12_MANIFEST_INCOMPLETE,
                        f"resume manifest unreadable: {exc}")

    new_hash = hashlib.sha256(canonical_json(cfg).encode()).hexdigest()
    old_hash = existing.get("config_hash")
    if old_hash and old_hash != new_hash:
        raise AbcrError(
            E09_RESUME_CONFLICT,
            f"resume config drift: manifest config_hash={str(old_hash)[:12]} "
            f"!= current {new_hash[:12]}; refusing to overwrite manifest / mix arms",
        )

    old_cfg = existing.get("config", {}) or {}
    old_dec = (old_cfg.get("decoding") or {})
    checks = [
        ("condition", old_cfg.get("condition"), cfg.get("condition")),
        ("model_key",
         existing.get("model", {}).get("key", old_cfg.get("model_key")),
         cfg.get("model_key")),
        ("data.split", (old_cfg.get("data") or {}).get("split"),
         (cfg.get("data") or {}).get("split")),
        ("decoding.seeds", old_dec.get("seeds"),
         (cfg.get("decoding") or {}).get("seeds")),
        ("split_hash", existing.get("split_hash"), split_hash),
    ]
    for dim, old_v, new_v in checks:
        if old_v is not None and old_v != new_v:
            raise AbcrError(
                E09_RESUME_CONFLICT,
                f"resume {dim} drift: manifest={old_v!r} != current={new_v!r}; "
                "refusing to mix conditions into one run",
            )


@app.command()
def run(
    config: str = typer.Option(..., help="Path to run config YAML"),
    dev: bool = typer.Option(False, help="Dev mode: allow dirty git, mark non-citable"),
    resume: str = typer.Option(None, help="Resume existing run_id"),
    repair_run: str = typer.Option(None, "--repair", help="Repair corrupt run_id"),
    max_items_per_chunk: int = typer.Option(None, "--max-items-per-chunk",
                                            help="Max items per chunk (3B default 20)"),
) -> None:
    cfg = _load_config(config)

    if repair_run:
        run_dir = _safe_run_dir(repair_run)
        if not run_dir.exists():
            die(E05_CONFIG_INVALID, f"run dir not found: {run_dir}")
        event = StepWriter.repair(run_dir)
        print(f"Repair complete: {event}")
        return

    needs_guard = (cfg["model_key"] not in ("tinyqwen",)
                   or os.environ.get("ABCR_FORCE_GUARD"))
    lock = None

    if needs_guard:
        from abcr.resource_guard import (
            HeavyLock, preflight as rg_preflight, check_pressure_fuse,
            set_mps_memory_limit, mps_cleanup, get_lock_dir,
        )
        if max_items_per_chunk is None and cfg["model_key"] == "qwen2.5-3b-instruct":
            max_items_per_chunk = 20
        if max_items_per_chunk is None and cfg["model_key"] == "qwen2.5-0.5b-instruct":
            max_items_per_chunk = 100
        lock = HeavyLock(pkg="A", task=f"run --config {config}", lock_dir=get_lock_dir())
        if not lock.acquire():
            print(f"{E20_RESOURCE_LEASE_BUSY}: heavy.lock lease timeout (8h)",
                  file=sys.stderr)
            sys.exit(20)
        ok, issues = rg_preflight()
        if not ok:
            lock.release()
            print(f"{E21_PREFLIGHT_RESOURCE_FAIL}: {'; '.join(issues)}",
                  file=sys.stderr)
            sys.exit(21)
        if cfg["model_key"] in ("qwen2.5-3b-instruct", "qwen2.5-7b-instruct"):
            frac = set_mps_memory_limit()
            if frac is not None:
                print(f"  MPS memory fraction: {frac:.3f}")

    try:
        citable, meta = _preflight(cfg, dev)
        if dev:
            citable = False

        # Load model
        from abcr.models import load
        model, tokenizer, model_meta = load(cfg["model_key"])

        # Intervention
        intervention = get_intervention(cfg.get("intervention", {}), cfg["model_key"])
        iv_desc = intervention.describe()

        # F-INT-03: the declared condition must match the method that was actually
        # built from the intervention spec. Otherwise a config that says
        # condition=vanilla but wires up a residual_vector/random_direction/etc hook
        # would run a steered arm labelled as a clean baseline. Fail closed.
        effective_method = iv_desc.get("method", "none")
        expected_method = CONDITION_METHOD.get(cfg["condition"])
        if expected_method is None or effective_method != expected_method:
            if lock is not None:
                lock.release()
            raise AbcrError(
                E06_ARM_PURITY_VIOLATION,
                f"condition={cfg['condition']!r} but effective intervention "
                f"method={effective_method!r} (expected {expected_method!r})",
            )

        # Run ID — resolve under runs/ with realpath containment (F-A-02).
        if resume:
            run_id = resume
        else:
            run_id = _run_id_from_config(cfg)

        run_dir = _safe_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Template hash
        template_hash = meta.get("chat_template_hash", "")

        # Git commit
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            git_commit = "UNKNOWN"

        # Protocol ref
        protocol_ref_path = Path("configs/protocol_ref.txt")
        protocol_ref = protocol_ref_path.read_text().strip() if protocol_ref_path.exists() else "UNAVAILABLE"

        # Items
        items = _load_items(cfg)
        seeds = cfg["decoding"]["seeds"]
        activation_rate = cfg.get("activation_sampling_rate", 0.0)

        n_expected = len(items) * len(seeds)

        # F-A-01: on resume, verify the existing manifest is consistent with the
        # current config BEFORE (re)writing anything. If it drifted, refuse; if it
        # matches, preserve the original manifest (do not overwrite its started_at /
        # provenance). Only start a fresh manifest when there is none.
        if resume:
            _assert_resume_consistent(run_dir, cfg, meta["split_hash"])
        resuming_existing = bool(resume and (run_dir / "manifest.json").exists())

        if resuming_existing:
            manifest = json.loads((run_dir / "manifest.json").read_text())
        else:
            # Write manifest
            manifest = write_manifest(run_dir, cfg, {
                "run_id": run_id,
                "model_id": model_meta.get("model_id", meta["model_id"]),
                "model_revision": meta["model_revision"],
                "dtype": model_meta["dtype"],
                "device_backend": model_meta["device_backend"],
                "chat_template_hash": template_hash,
                "split_hash": meta["split_hash"],
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "n_steps_expected": n_expected,
                "citable": citable,
            })

        config_hash = hashlib.sha256(canonical_json(cfg).encode()).hexdigest()
        env_lock_ref = "env.lock"

        writer = StepWriter(run_dir)
        step_count = len(writer.load_done())
        condition = cfg["condition"]

        warning_count = 0
        resource_events: list[dict] = []
        chunk_count = 0
        should_exit = False

        print(f"Run {run_id}: {len(items)} items × {len(seeds)} seeds = {n_expected} steps")
        print(f"  condition={condition}, model={cfg['model_key']}, citable={citable}")
        if step_count > 0:
            print(f"  Resuming: {step_count} steps already done")

        for item in items:
            if should_exit:
                break
            prompt_text = item["prompt"]
            messages = []
            if intervention.system_text:
                messages.append({"role": "system", "content": intervention.system_text})
            messages.append({"role": "user", "content": prompt_text})
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            prompt_hash = _sha256_str(rendered)

            for seed in seeds:
                if writer.is_done(item["item_id"], seed, condition):
                    continue

                if needs_guard:
                    if os.getppid() == 1:
                        resource_events.append({
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "reason": "orphan_detected",
                            "steps_done": step_count,
                        })
                        should_exit = True
                        break
                    action, warning_count = check_pressure_fuse(warning_count)
                    if action:
                        resource_events.append({
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "reason": action,
                            "steps_done": step_count,
                        })
                        should_exit = True
                        break

                # Activation sampling — reset capture_path each step to prevent leak
                if hasattr(intervention, 'capture_path'):
                    intervention.capture_path = None
                act_path = None
                if _deterministic_sample(item["item_id"], activation_rate):
                    act_dir = run_dir / "activations"
                    act_dir.mkdir(exist_ok=True)
                    act_path = str(act_dir / f"{item['item_id']}_{seed}.npz")
                    if hasattr(intervention, 'capture_path'):
                        intervention.capture_path = act_path

                with intervention.context(model):
                    output_text, stop_reason, in_toks, out_toks, latency = _generate(
                        model, tokenizer, rendered, seed, cfg
                    )

                    act_summary = intervention.activation_summary() if hasattr(intervention, 'activation_summary') else None

                step = {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    "trajectory_id": f"{run_id}:{item['item_id']}:{seed}",
                    "step_id": 0,
                    "parent_run": cfg.get("_parent_run"),
                    "git_commit": git_commit,
                    "config_hash": config_hash,
                    "protocol_ref": protocol_ref,
                    "env_lock_ref": env_lock_ref,
                    "model_id": model_meta.get("model_id", meta["model_id"]),
                    "model_revision": meta["model_revision"],
                    "dtype": model_meta["dtype"],
                    "quantization": None,
                    "device": str(model.device),
                    "device_backend": model_meta["device_backend"],
                    "engine": "transformers",
                    "engine_version": model_meta["engine_version"],
                    "torch_version": model_meta["torch_version"],
                    "cuda_version": None,
                    "chat_template_hash": template_hash,
                    "benchmark": cfg["data"]["family"],
                    "split_hash": meta["split_hash"],
                    "item_id": item["item_id"],
                    "condition": condition,
                    "trait": iv_desc.get("trait"),
                    "trait_pole": iv_desc.get("trait_pole"),
                    "method": iv_desc.get("method", "none"),
                    "layer": iv_desc.get("layer"),
                    "coefficient": iv_desc.get("coefficient"),
                    "intervention_strength": iv_desc.get("intervention_strength"),
                    "env_seed": None,
                    "action": None,
                    "obs_hash": None,
                    "remaining_budget": None,
                    "stop_reason": stop_reason,
                    "state_snapshot_ref": None,
                    "random_seed": seed,
                    "prompt_hash": prompt_hash,
                    "output_text": output_text,
                    "parsed_answer": None,
                    "is_correct": None,
                    "latency_ms": round(latency, 1),
                    "input_tokens": in_toks,
                    "output_tokens": out_toks,
                    "trait_score": None,
                    "fluency_score": None,
                    "safety_flags": [],
                    "activation_summary": act_summary,
                    "citable": citable,
                    "prev_hash": "",
                    "entry_hash": "",
                }

                writer.append(step)
                step_count += 1
                print(f"  [{step_count}/{n_expected}] item={item['item_id'][:8]} seed={seed} "
                      f"toks={out_toks} lat={latency:.0f}ms")

                chunk_count += 1
                if max_items_per_chunk and chunk_count >= max_items_per_chunk:
                    should_exit = True
                    break

        finalize_manifest(run_dir, step_count,
                          resource_events=resource_events or None)

        if resource_events:
            print(f"\n{E19_RESOURCE_PRESSURE}: {resource_events[-1]['reason']}")
            print(f"Resume: .venv/bin/python -m abcr.run --config {config}"
                  f" --dev --resume {run_id}")
            if needs_guard:
                try:
                    mem = mps_cleanup()
                    if mem is not None:
                        print(f"  driver_allocated_memory after cleanup: {mem/(1024**3):.2f}GB")
                except Exception:
                    pass
            if lock:
                lock.release()
            sys.exit(19)

        if should_exit and step_count < n_expected:
            print(f"\nChunk limit: {chunk_count} items, {step_count}/{n_expected} done")
            print(f"Resume: .venv/bin/python -m abcr.run --config {config}"
                  f" --dev --resume {run_id}")
            if needs_guard:
                try:
                    mem = mps_cleanup()
                    if mem is not None:
                        print(f"  driver_allocated_memory after cleanup: {mem/(1024**3):.2f}GB")
                except Exception:
                    pass
            if lock:
                lock.release()
            sys.exit(100)
        else:
            # temp0 sanity run (only when main loop completed fully)
            if cfg["decoding"].get("temp0_sanity") and cfg["decoding"]["temperature"] > 0:
                t0_cfg = dict(cfg)
                t0_cfg = json.loads(json.dumps(cfg))
                t0_cfg["decoding"] = dict(t0_cfg["decoding"])
                t0_cfg["decoding"]["temperature"] = 0
                t0_cfg["decoding"]["seeds"] = [0]
                t0_cfg["decoding"]["temp0_sanity"] = False
                t0_cfg["_parent_run"] = run_id
                t0_run_id = f"{run_id}-t0"
                t0_run_dir = Path("runs") / t0_run_id
                t0_run_dir.mkdir(parents=True, exist_ok=True)

                t0_manifest = write_manifest(t0_run_dir, t0_cfg, {
                    "run_id": t0_run_id,
                    "model_id": model_meta.get("model_id", meta["model_id"]),
                    "model_revision": meta["model_revision"],
                    "dtype": model_meta["dtype"],
                    "device_backend": model_meta["device_backend"],
                    "chat_template_hash": template_hash,
                    "split_hash": meta["split_hash"],
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "n_steps_expected": len(items),
                    "citable": citable,
                })

                t0_writer = StepWriter(t0_run_dir)
                t0_count = len(t0_writer.load_done())
                t0_config_hash = hashlib.sha256(canonical_json(t0_cfg).encode()).hexdigest()
                t0_warning_count = 0
                t0_resource_events: list[dict] = []
                t0_should_exit = False

                print(f"\ntemp0 sanity run {t0_run_id}: {len(items)} items × 1 seed")

                for item in items:
                    if t0_should_exit:
                        break
                    messages = []
                    if intervention.system_text:
                        messages.append({"role": "system", "content": intervention.system_text})
                    messages.append({"role": "user", "content": item["prompt"]})
                    rendered = tokenizer.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=True
                    )
                    prompt_hash = _sha256_str(rendered)

                    if t0_writer.is_done(item["item_id"], 0, condition):
                        continue

                    if needs_guard:
                        action, t0_warning_count = check_pressure_fuse(t0_warning_count)
                        if action:
                            t0_resource_events.append({
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "reason": action,
                                "steps_done": t0_count,
                            })
                            t0_should_exit = True
                            break

                    # F-INT-04: the t0 sanity loop must not inherit the main
                    # loop's residual capture_path. If the last main-loop step
                    # was sampled, capture_path still points at that main-run
                    # NPZ; the intervention's finally-block would overwrite it
                    # with t0 projections. The t0 loop captures no activations,
                    # so clear the path each step.
                    if hasattr(intervention, 'capture_path'):
                        intervention.capture_path = None

                    with intervention.context(model):
                        output_text, stop_reason, in_toks, out_toks, latency = _generate(
                            model, tokenizer, rendered, 0, t0_cfg
                        )

                    step = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": t0_run_id,
                        "trajectory_id": f"{t0_run_id}:{item['item_id']}:0",
                        "step_id": 0,
                        "parent_run": run_id,
                        "git_commit": git_commit,
                        "config_hash": t0_config_hash,
                        "protocol_ref": protocol_ref,
                        "env_lock_ref": env_lock_ref,
                        "model_id": model_meta.get("model_id", meta["model_id"]),
                        "model_revision": meta["model_revision"],
                        "dtype": model_meta["dtype"],
                        "quantization": None,
                        "device": str(model.device),
                        "device_backend": model_meta["device_backend"],
                        "engine": "transformers",
                        "engine_version": model_meta["engine_version"],
                        "torch_version": model_meta["torch_version"],
                        "cuda_version": None,
                        "chat_template_hash": template_hash,
                        "benchmark": cfg["data"]["family"],
                        "split_hash": meta["split_hash"],
                        "item_id": item["item_id"],
                        "condition": condition,
                        "trait": iv_desc.get("trait"),
                        "trait_pole": iv_desc.get("trait_pole"),
                        "method": iv_desc.get("method", "none"),
                        "layer": iv_desc.get("layer"),
                        "coefficient": iv_desc.get("coefficient"),
                        "intervention_strength": iv_desc.get("intervention_strength"),
                        "env_seed": None,
                        "action": None,
                        "obs_hash": None,
                        "remaining_budget": None,
                        "stop_reason": stop_reason,
                        "state_snapshot_ref": None,
                        "random_seed": 0,
                        "prompt_hash": prompt_hash,
                        "output_text": output_text,
                        "parsed_answer": None,
                        "is_correct": None,
                        "latency_ms": round(latency, 1),
                        "input_tokens": in_toks,
                        "output_tokens": out_toks,
                        "trait_score": None,
                        "fluency_score": None,
                        "safety_flags": [],
                        "activation_summary": None,
                        "citable": citable,
                        "prev_hash": "",
                        "entry_hash": "",
                    }

                    t0_writer.append(step)
                    t0_count += 1
                    print(f"  [t0 {t0_count}/{len(items)}] item={item['item_id'][:8]} "
                          f"toks={out_toks} lat={latency:.0f}ms")

                finalize_manifest(t0_run_dir, t0_count,
                                  resource_events=t0_resource_events or None)

                if t0_resource_events:
                    print(f"\n{E19_RESOURCE_PRESSURE}: temp0 interrupted")
                    print(f"Resume temp0 manually if needed: run_id={t0_run_id}")
                else:
                    print(f"temp0 sanity run complete: {t0_count} steps")

        print(f"\nRun complete: {run_id}, {step_count} steps written")

        if needs_guard:
            try:
                mem = mps_cleanup()
                if mem is not None:
                    print(f"  driver_allocated_memory after cleanup: {mem/(1024**3):.2f}GB")
            except Exception:
                pass
        if lock:
            lock.release()
    finally:
        # F-A-07: any exit path (normal, sys.exit, OOM/exception)
        # must release the single global heavy.lock. release() is
        # idempotent, so the explicit releases above are harmless.
        if lock is not None:
            lock.release()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
