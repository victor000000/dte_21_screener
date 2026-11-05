#!/bin/bash
# run_iv_sweep.sh — keep the IV/IVR/IVP sweep alive until the universe is covered.
#
# Why a supervisor: the universe is ~6,000 names, IBKR serves ~60 historical requests per
# 10 minutes, so a full pass is ~18 hours. Any single run can die (TWS session drop, a
# killed shell, the harness's 2-hour background cap). The fetcher is idempotent — it skips
# a symbol whose newest row is fresh — so *re-running it is the resume mechanism*, and all
# this loop has to do is keep re-running it until a pass fetches nothing new.
#
# Termination: a pass that reports "0 fetched" means every symbol is either already covered
# or permanently has no data. Failures do not block termination — a name with no listed
# options fails identically forever, and looping on it would stall the sweep.
#
#   bash scripts/run_iv_sweep.sh [universe-file] [duration]
set -u
cd "$(dirname "$0")/.." || { echo "cannot cd to the repo root"; exit 1; }
UNIVERSE="${1:-plans/ibkr_iv_universe_full.txt}"
DURATION="${2:-2 Y}"
LOG="logs/iv_sweep_$(date -u +%Y%m%d).log"
mkdir -p logs var/status

echo "=== supervisor start $(date -u '+%F %T') UTC · $UNIVERSE · $DURATION ===" >> "$LOG"
for pass in $(seq 1 40); do
    echo "--- pass $pass starting $(date -u '+%F %T') ---" >> "$LOG"
    uv run --no-project --with duckdb --with ib_async \
        python scripts/fetch_iv_history_ibkr.py \
        --universe "$UNIVERSE" --duration "$DURATION" --stale-days 1 >> "$LOG" 2>&1
    rc=$?
    last=$(grep -a "^done:" "$LOG" | tail -1)
    echo "--- pass $pass ended rc=$rc :: $last" >> "$LOG"
    if [ "$rc" -eq 0 ] && echo "$last" | grep -qE "^done: 0 fetched"; then
        echo "=== SWEEP COMPLETE $(date -u '+%F %T') UTC — universe covered ===" >> "$LOG"
        exit 0
    fi
    # A pass that fetched NOTHING and failed a lot means the link is down, not that the
    # universe is exhausted. Retrying after 20s just burns the next pass against a dead
    # gateway — on 2026-10-01 that turned one TWS outage into 31 wasted timeouts. Back off
    # hard instead; the links recover on their own (Error 1102) given time.
    # Any non-zero exit is an outage signature, not just a low-yield pass. A CONNECT FAILURE
    # -- TWS down, API port closed -- exits rc=1 after printing nothing, so the original test
    # (rc=0 AND "0 fetched") never matched and the supervisor hammered a dead port every 20
    # seconds. Observed 2026-10-01 18:35, eleven passes in a row.
    if [ "$rc" -ne 0 ] || echo "$last" | grep -qE "^done: 0 fetched, [0-9]+ skipped, ([2-9][0-9]|[0-9]{3,}) failed"; then
        echo "--- pass $pass failed/outage (rc=$rc) — cooling down 300s" >> "$LOG"
        sleep 300
    else
        sleep 20
    fi
done
echo "=== supervisor exhausted 40 passes $(date -u '+%F %T') UTC ===" >> "$LOG"
