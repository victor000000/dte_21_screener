#!/bin/bash
# watch_iv_merge.sh — wait out the IV downloaders, then merge what they staged.
#
# WHY THIS EXISTS. The repo already has a drain for the option-bar sweep
# (after_download_queue.sh), and it matches *download_option_bars.py* by basename — so an IV
# run has NO watcher of its own. Two things went wrong on 2026-10-03 because of that:
#
#   * an IV run was orphaned when the chain that launched it was killed, and its 606 MB of
#     staging sat unmerged for an hour with the database silently missing the rows;
#   * a later gap-fill run finished with nothing watching, and would have done the same —
#     caught only by checking `pgrep` and finding the previous watcher had exited at 16:30.
#
# A watcher that exits on success needs re-arming per run. This one is that re-arm: start it
# alongside run_iv_shards.sh and it folds the result when the last shard exits.
#
# It watches by PROCESS NAME rather than by PID, so it survives the downloader being
# restarted or relaunched mid-flight. And it runs merge_staging.py, which discovers every
# staging file itself and upserts on conflict — safe to run late, safe to run twice.
#
#   bash scripts/watch_iv_merge.sh [&]      # then start the shards
#
# Both steps below keep their EXIT CODE. Piping them into tail made the script's status
# tail's, so a merge that duplicated rows (merge_staging exits 1) or left staging files
# unmerged (exits 2) reported the same thing as a clean one -- "IV merge watch complete".
# This watcher is unattended by design, so that banner is the only report anyone gets.
set -u
cd "$(dirname "$0")/.." || { echo "cannot cd to the repo root"; exit 1; }

fail=0
run() {   # run <label> <tail-lines> <cmd...>
    local label="$1" n="$2"; shift 2
    "$@" 2>&1 | tail -"$n"
    local rc=${PIPESTATUS[0]}
    if [ "$rc" != 0 ]; then
        case "$rc" in
            2) echo "  !! $label INCOMPLETE (rc=2) — staging NOT fully merged; files kept" ;;
            *) echo "  !! $label FAILED (rc=$rc) — see the lines above" ;;
        esac
        fail=1
    fi
}

while :; do
    alive=0
    for p in $(ls /proc | grep -E '^[0-9]+$'); do
        c=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null)
        # Basename, not full path: the data/application split moves this file, and a
        # hard-coded path would stop matching — the watcher would decide the downloader had
        # exited and merge into market_history WHILE it was still writing.
        case "$c" in *download_atm_iv.py*) alive=1;; esac
    done
    [ $alive -eq 0 ] && break
    sleep 60
done

echo "=== IV downloader exited $(date -u +%FT%TZ) ==="
echo "--- merge ---"
run "merge staging" 14 uv run --no-project --with duckdb python scripts/merge_staging.py
echo "--- duplicate check ---"
run "duplicate check" 8 uv run --no-project --with duckdb python scripts/check_duplicates.py
if [ "$fail" = 0 ]; then
    echo "=== IV merge watch complete $(date -u +%FT%TZ) ==="
else
    echo "=== IV MERGE WATCH FINISHED WITH FAILURES $(date -u +%FT%TZ) — see the !! lines ==="
fi
exit "$fail"
