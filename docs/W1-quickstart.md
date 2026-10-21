# ABCR — AI Behavioral Controllability Research

W1 goal: build a reproducible experiment pipeline from frozen config to repro-pack. Three packages (A=Runner/Ledger, B=Hook/Vector/PV, C=Scorer/Audit) developed in parallel with frozen interfaces.

## Directory Layout

- `configs/` — model pins, chat template hashes, run configs
- `src/abcr/` — core library (run, models, splits, logging, interventions, eval)
- `data/` — items and splits
- `runs/` — per-run output (steps.jsonl, manifest.json, activations)
- `scores/` — scoring output
- `tests/` — unit + contract tests by stage

## Quick Start

```bash
make bootstrap          # repo skeleton + venv + model downloads + tinyqwen
make stage1-regression  # run S1 contract tests
make stage2-regression  # run S2 contract tests
make mini-loop          # execute 4-arm mini experiment loop
make repro-pack PRESET=miniloop  # build reproducibility package
```

## Running Manual (bootstrap → repro-pack)

### 1. Bootstrap

```bash
bash scripts/bootstrap.sh
# Idempotent — re-run is safe. Creates:
#   .venv (Python 3.11, all deps)
#   configs/models.yaml (revision pins via config.json sha256)
#   configs/templates/ (chat_template hash + 3 samples per model)
#   tests/fixtures/tinyqwen/ (tiny random-init model for fast S1 tests)
```

### 2. Run a single arm

```bash
# --dev allows dirty git and marks output citable=false
.venv/bin/python -m abcr.run --config configs/runs/mini_vanilla.yaml --dev
```

Available configs: `mini_vanilla.yaml`, `mini_text.yaml`, `mini_random.yaml`, `mini_vector.yaml`.

Each run produces `runs/<run_id>/` with:
- `steps.jsonl` — append-only hash-chained experiment log
- `manifest.json` — config snapshot, model revision, arm purity
- `config.yaml` + `env.lock` — full reproducibility context
- `activations/` — sampled activation captures (npz, 10% rate)

If `temp0_sanity: true` in config, a deterministic t0 companion run is auto-generated.

### 3. Resume / repair

```bash
# Resume after crash (reads existing steps, skips completed)
.venv/bin/python -m abcr.run --config configs/runs/mini_vanilla.yaml --dev --resume <run_id>

# Repair corrupt tail (renames broken file, rewrites clean prefix)
.venv/bin/python -m abcr.run --config configs/runs/mini_vanilla.yaml --dev --repair <run_id>
```

### 4. Score a run (Package C)

```bash
.venv/bin/python -m abcr.score --run <run_id>
# Output: scores/<run_id>/scores.jsonl + summary.json
```

### 5. Review / audit a run (Package C)

```bash
.venv/bin/python -m abcr.review --run <run_id>
# Output: review/<run_id>/review_report.json
```

### 6. Contract tests

```bash
.venv/bin/python -m pytest tests/contract/stage1/ -v  # writer, preflight, tinyqwen e2e
.venv/bin/python -m pytest tests/contract/stage2/ -v  # real model smoke, template pin, doublerun
.venv/bin/python -m pytest tests/contract/stage3/ -v  # arm purity, mini loop coverage
```

### 7. Key invariants

- **Hash chain**: every step's `entry_hash = sha256(canonical_json(step without entry_hash) + prev_hash)`. Chain starts from `"0"*64`.
- **Arm purity**: vanilla has no persona/vector refs; text has persona only; vector/random has vector only. Enforced by preflight E06.
- **Idempotent resume**: `(item_id, random_seed, condition, step_id)` tuple deduplication.
- **Mac runs are `citable=false`**: formal evidence requires 24GB GPU with bf16. All Mac outputs are marked exploratory/rig-validation.
