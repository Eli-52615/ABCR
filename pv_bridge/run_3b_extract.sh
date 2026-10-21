#!/bin/bash
# B2.8 driver: 3B optimistic dev extraction in 8×50 chunks with checkpoint resume.
# Each chunk = 5 questions × 5 instructions × 2 responses = 50 generations.
# Restart-safe: completed chunks (final CSV exists) are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."

export OPENAI_API_KEY=$(cat ~/oc-boss-state/deepseek.key)
export OPENAI_BASE_URL=https://api.deepseek.com

CKPT=pv_bridge/out/3b-optimistic-ckpt
mkdir -p "$CKPT"

N_INSTR=5
N_PER_Q=2
CHUNK_Q=5

COMPLETED=0
TOTAL=8

for POLE in pos neg; do
    for Q_START in 0 5 10 15; do
        Q_END=$((Q_START + CHUNK_Q))
        CID="${POLE}_q${Q_START}-${Q_END}"
        CSV="${CKPT}/${CID}.csv"

        if [ -f "$CSV" ]; then
            echo "[SKIP] $CID (checkpoint exists: $(wc -l < "$CSV") lines)"
            COMPLETED=$((COMPLETED + 1))
            continue
        fi

        SEED_OFF=$((Q_START * N_INSTR * N_PER_Q))
        echo "========================================"
        echo "[RUN ] $CID  seed_offset=$SEED_OFF  (chunk $((COMPLETED+1))/$TOTAL)"
        echo "========================================"

        .venv-pv/bin/python pv_bridge/extract_mac.py \
            --model-key qwen2.5-3b-instruct \
            --trait optimistic \
            --artifact artifacts/traits/optimistic/extract.json \
            --pole "$POLE" \
            --n-per-q "$N_PER_Q" \
            --out-csv "$CSV" \
            --device mps \
            --dtype float16 \
            --question-start "$Q_START" \
            --question-end "$Q_END" \
            --seed-offset "$SEED_OFF"

        COMPLETED=$((COMPLETED + 1))
        echo "[DONE] $CID  ($COMPLETED/$TOTAL complete)"
    done
done

echo ""
echo "=== All 8 chunks complete. Merging... ==="

.venv-pv/bin/python -c "
import pandas as pd, pathlib, json, os
d = pathlib.Path('$CKPT')
for pole in ['pos', 'neg']:
    chunks = sorted(d.glob(f'{pole}_q*.csv'))
    assert len(chunks) == 4, f'{pole}: expected 4 chunks, got {len(chunks)}: {chunks}'
    df = pd.concat([pd.read_csv(c) for c in chunks], ignore_index=True)
    out = f'pv_bridge/out/optimistic_3b_{pole}.csv'
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
echo "Pos CSV: pv_bridge/out/optimistic_3b_pos.csv"
echo "Neg CSV: pv_bridge/out/optimistic_3b_neg.csv"
