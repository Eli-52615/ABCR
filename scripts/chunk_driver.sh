#!/usr/bin/env bash
# F14.6 Chunk driver — loops chunked runs, handles E19 pressure recovery.
# Usage: scripts/chunk_driver.sh <config_yaml> [extra_run_args...]
# Exit codes: 0=complete, 1=batch stopped, 2=usage error
set -euo pipefail

CONFIG="${1:?Usage: $0 <config_yaml> [extra_run_args...]}"
shift

# Parse EXTRA_ARGS: extract --resume into RUN_ID, keep the rest clean
EXTRA_ARGS=()
_INIT_RUN_ID=""
while (( $# > 0 )); do
    case "$1" in
        --resume)
            _INIT_RUN_ID="$2"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

export PYTHONUNBUFFERED=1
PYTHON="${PYTHON:-.venv/bin/python}"
PROBE_PYTHON=".venv/bin/python"
MAX_WAIT_SECS="${ABCR_PRESSURE_WAIT_SECS:-1800}"
RECOVERY_SECS="${ABCR_RECOVERY_SECS:-120}"
POLL_INTERVAL=10

# BatchGuard state
E19_CONSECUTIVE=0
E19_TOTAL=0
E19_TIMES=()
RUN_ID="${_INIT_RUN_ID}"

log() { echo "[chunk_driver] $(date '+%H:%M:%S') $*"; }

wait_for_pressure_recovery() {
    log "E19 received — waiting for pressure to return to normal (max ${MAX_WAIT_SECS}s)..."
    local waited=0 normal_streak=0
    while (( waited < MAX_WAIT_SECS )); do
        local level
        level=$("$PROBE_PYTHON" -c "
from abcr.resource_guard import get_pressure_level, PRESSURE_NORMAL
print('normal' if get_pressure_level() == PRESSURE_NORMAL else 'elevated')
" 2>/dev/null || echo "elevated")

        if [[ "$level" == "normal" ]]; then
            normal_streak=$((normal_streak + POLL_INTERVAL))
            if (( normal_streak >= RECOVERY_SECS )); then
                log "Pressure normal for ${RECOVERY_SECS}s — resuming."
                return 0
            fi
        else
            normal_streak=0
        fi
        sleep "$POLL_INTERVAL"
        waited=$((waited + POLL_INTERVAL))
    done
    log "Pressure did not recover within ${MAX_WAIT_SECS}s."
    return 1
}

check_batch_guard() {
    local now
    now=$(date +%s)
    E19_CONSECUTIVE=$((E19_CONSECUTIVE + 1))
    E19_TOTAL=$((E19_TOTAL + 1))
    E19_TIMES+=("$now")

    if (( E19_CONSECUTIVE >= 6 )); then
        local len=${#E19_TIMES[@]}
        local third_idx=$((len - 3))
        local third_ago=${E19_TIMES[$third_idx]}
        if (( now - third_ago < 3600 )); then
            log "BATCH STOP: 3 consecutive E19 within 1h"
            return 1
        fi
    fi
    if (( E19_TOTAL >= 8 )); then
        log "BATCH STOP: 5 total E19"
        return 1
    fi
    return 0
}

write_blocker() {
    local reason="$1"
    log "Writing BLOCKER to STATUS-A.md"
    echo "" >> STATUS-A.md
    echo "### BLOCKER (chunk_driver)" >> STATUS-A.md
    echo "- $(date -u '+%Y-%m-%dT%H:%M:%SZ'): $reason" >> STATUS-A.md
    echo "- config: $CONFIG" >> STATUS-A.md
    echo "- E19 total: $E19_TOTAL, consecutive: $E19_CONSECUTIVE" >> STATUS-A.md
}

log "Starting chunk driver for $CONFIG"

while true; do
    log "Launching chunk: $PYTHON -m abcr.run --config $CONFIG --dev ${EXTRA_ARGS[*]+${EXTRA_ARGS[*]}} ${RUN_ID:+--resume $RUN_ID}"

    set +e
    "$PYTHON" -m abcr.run --config "$CONFIG" --dev ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
        ${RUN_ID:+--resume "$RUN_ID"}
    RC=$?
    set -e

    if (( RC == 0 )); then
        log "Run complete (exit 0)."
        E19_CONSECUTIVE=0
        break
    elif (( RC == 100 )); then
        log "Chunk limit reached — continuing next chunk."
        E19_CONSECUTIVE=0
        if [[ -z "$RUN_ID" ]]; then
            RUN_ID=$(ls -1dt runs/20* 2>/dev/null | head -1 | xargs basename)
            log "Discovered run_id=$RUN_ID for resume"
        fi
    elif (( RC == 19 )); then
        log "E19 (resource pressure) at chunk boundary."

        if ! check_batch_guard; then
            write_blocker "BatchGuard triggered (consecutive=$E19_CONSECUTIVE total=$E19_TOTAL)"
            exit 1
        fi

        if ! wait_for_pressure_recovery; then
            write_blocker "Pressure did not recover within ${MAX_WAIT_SECS}s"
            exit 1
        fi

        if [[ -z "$RUN_ID" ]]; then
            RUN_ID=$(ls -1dt runs/20* 2>/dev/null | head -1 | xargs basename)
            log "Discovered run_id=$RUN_ID for resume"
        fi
    elif (( RC == 20 )); then
        log "E20: lock busy — another heavy process is running. Aborting."
        exit 1
    elif (( RC == 21 )); then
        log "E21: preflight failed. Aborting."
        exit 1
    else
        log "Unexpected exit code $RC. Aborting."
        exit 1
    fi
done

log "Chunk driver finished successfully."
exit 0
