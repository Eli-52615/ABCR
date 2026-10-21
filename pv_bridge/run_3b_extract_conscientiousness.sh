#!/bin/bash
# B3.2 driver: 3B conscientiousness dev extraction — process-per-chunk with resource_guard (F14).
# Each chunk = 5 questions × 5 instructions × 2 responses = 50 generations.
# Model is loaded and released per chunk (no cross-chunk residency).
# Each chunk wrapped via resource_guard (heavy.lock + preflight + soft fuse).
# In-generation: extract_mac.py does sample-between pressure probe + orphan check (F14.5/F14.6).
# E19 (pressure fuse) → wait for recovery (normal ×120s) → retry; batch stop on 3 consecutive or 5 total.
set -euo pipefail
cd "$(dirname "$0")/.."

export OPENAI_API_KEY=$(cat ~/oc-boss-state/deepseek.key)
export OPENAI_BASE_URL=https://api.deepseek.com

TRAIT=conscientiousness
CKPT=pv_bridge/out/3b-${TRAIT}-ckpt
mkdir -p "$CKPT"

N_INSTR=5
N_PER_Q=2
CHUNK_Q=5
E19_CONSEC=0
E19_TOTAL=0

wait_for_e19_recovery() {
    echo "[E19-RECOVERY] Waiting for pressure normal × 120s (timeout 30min)..."
    local consec_normal=0
    local elapsed=0
    local timeout=1800
    while [ "$consec_normal" -lt 12 ]; do
        local level
        level=$(sysctl -n kern.memorystatus_vm_pressure_level)
        if [ "$level" -eq 1 ]; then
            consec_normal=$((consec_normal + 1))
            echo "[E19-RECOVERY] pressure=normal (${consec_normal}/12 consecutive OK)"
        else
            consec_normal=0
            echo "[E19-RECOVERY] pressure=$level (reset, ${elapsed}s/${timeout}s)"
        fi
        if [ "$elapsed" -ge "$timeout" ]; then
            echo "[BLOCKER] E19 recovery timeout (30min). Stopping batch."
            exit 19
        fi
        sleep 10
        elapsed=$((elapsed + 10))
    done
    echo "[E19-RECOVERY] Pressure stable 120s. Resuming."
}

COMPLETED=0
TOTAL=8

CHUNKS=()
for POLE in pos neg; do
    for Q_START in 0 5 10 15; do
        CHUNKS+=("${POLE}:${Q_START}")
    done
done

for ENTRY in "${CHUNKS[@]}"; do
    POLE="${ENTRY%%:*}"
    Q_START="${ENTRY##*:}"
    Q_END=$((Q_START + CHUNK_Q))
    CID="${POLE}_q${Q_START}-${Q_END}"
    CSV="${CKPT}/${CID}.csv"

    if [ -f "$CSV" ]; then
        echo "[SKIP] $CID (checkpoint exists: $(wc -l < "$CSV") lines)"
        COMPLETED=$((COMPLETED + 1))
        continue
    fi

    SEED_OFF=$((Q_START * N_INSTR * N_PER_Q))

    while true; do
        echo "========================================"
        echo "[RUN ] $CID  seed_offset=$SEED_OFF  (chunk $((COMPLETED+1))/$TOTAL)"
        echo "========================================"

        set +e
        .venv/bin/python -m abcr.resource_guard run -- \
            .venv-pv/bin/python pv_bridge/extract_mac.py \
            --model-key qwen2.5-3b-instruct \
            --trait "$TRAIT" \
            --artifact "artifacts/traits/${TRAIT}/extract.json" \
            --pole "$POLE" \
            --n-per-q "$N_PER_Q" \
            --out-csv "$CSV" \
            --device mps \
            --dtype float16 \
            --question-start "$Q_START" \
            --question-end "$Q_END" \
            --seed-offset "$SEED_OFF"
        RC=$?
        set -e

        if [ "$RC" -eq 0 ]; then
            E19_CONSEC=0
            break
        elif [ "$RC" -eq 19 ]; then
            E19_CONSEC=$((E19_CONSEC + 1))
            E19_TOTAL=$((E19_TOTAL + 1))
            echo "[E19] Pressure fuse. Consecutive=$E19_CONSEC Total=$E19_TOTAL"
            if [ "$E19_CONSEC" -ge 3 ] || [ "$E19_TOTAL" -ge 5 ]; then
                echo "[BLOCKER] E19 batch stop threshold. Aborting."
                exit 19
            fi
            wait_for_e19_recovery
        else
            echo "[FAIL] $CID exited with code $RC"
            exit "$RC"
        fi
    done

    COMPLETED=$((COMPLETED + 1))
    echo "[DONE] $CID  ($COMPLETED/$TOTAL complete)"
    echo "[DONE] Python process exited. Model released."
done

echo ""
echo "=== All $TOTAL chunks complete. Merging... ==="

.venv-pv/bin/python -c "
import pandas as pd, pathlib
d = pathlib.Path('$CKPT')
for pole in ['pos', 'neg']:
    chunks = sorted(d.glob(f'{pole}_q*.csv'))
    assert len(chunks) == 4, f'{pole}: expected 4 chunks, got {len(chunks)}: {chunks}'
    df = pd.concat([pd.read_csv(c) for c in chunks], ignore_index=True)
    out = f'pv_bridge/out/${TRAIT}_3b_{pole}.csv'
    df.to_csv(out, index=False)
    print(f'{out}: {len(df)} rows')
    raws = sorted(d.glob(f'{pole}_q*.csv.judge_raw.jsonl'))
    with open(f'{out}.judge_raw.jsonl', 'w') as f:
        for r in raws:
            f.write(r.read_text())
    print(f'{out}.judge_raw.jsonl: merged from {len(raws)} files')
"

echo ""
echo "=== Merged CSVs ready. Run generate_vec next. ==="
echo "Pos CSV: pv_bridge/out/${TRAIT}_3b_pos.csv"
echo "Neg CSV: pv_bridge/out/${TRAIT}_3b_neg.csv"
