#!/usr/bin/env bash
# STEP 3: Targeted SHA256 upgrade — collision candidates only (NOT full backfill).
# Uses `dupes --auto-upgrade` per device: reads only files that share a quick_hash
# (1MB sample). Much faster than full sha256-backfill across all files.
# Run per device so you can monitor per-device progress separately.
# Pause after this and paste tail of log to Claude before running step 4.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step3-dupes-upgrade-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================" | tee -a "$LOGFILE"
echo "STEP 3: dupes --auto-upgrade per device — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
echo "Note: only hashes collision candidates (same quick_hash), NOT all files." | tee -a "$LOGFILE"
echo "repo: $REPO" | tee -a "$LOGFILE"
echo "================================================================" | tee -a "$LOGFILE"

run_dupes() {
  local device="$1"
  local dupes_pid=""
  local interrupted=0
  local started_at now elapsed last_line

  _cleanup_child() {
    interrupted=1
    if [[ -n "$dupes_pid" ]] && kill -0 "$dupes_pid" 2>/dev/null; then
      echo "  [interrupt] stopping dupes child pid=$dupes_pid device=$device" | tee -a "$LOGFILE"
      kill -TERM "$dupes_pid" 2>/dev/null || true
      sleep 2
      if kill -0 "$dupes_pid" 2>/dev/null; then
        kill -KILL "$dupes_pid" 2>/dev/null || true
      fi
    fi
  }

  echo "" | tee -a "$LOGFILE"
  echo "--- dupes --device $device --- $(date '+%F %T')" | tee -a "$LOGFILE"
  trap _cleanup_child INT TERM
  "$PYTHON" -m hashall dupes --device "$device" --auto-upgrade \
    > >(tee -a "$LOGFILE") 2>&1 &
  dupes_pid=$!

  started_at="$(date +%s)"
  while kill -0 "$dupes_pid" 2>/dev/null; do
    sleep 20
    kill -0 "$dupes_pid" 2>/dev/null || break
    now="$(date +%s)"
    elapsed="$((now - started_at))"
    if [[ -f "$HOME/.logs/hashall/hashall.log" ]]; then
      last_line="$(tail -n 1 "$HOME/.logs/hashall/hashall.log" 2>/dev/null || true)"
      echo "  [heartbeat] device=$device elapsed=${elapsed}s last_hashall_log=${last_line:0:180}" | tee -a "$LOGFILE"
    else
      echo "  [heartbeat] device=$device elapsed=${elapsed}s (hashall.log unavailable)" | tee -a "$LOGFILE"
    fi
  done

  local rc=0
  wait "$dupes_pid" || rc=$?
  trap - INT TERM
  if [[ "$interrupted" -ne 0 ]]; then
    return 130
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo "--- failed $device rc=$rc --- $(date '+%F %T')" | tee -a "$LOGFILE"
    return "$rc"
  fi
  echo "--- done $device --- $(date '+%F %T')" | tee -a "$LOGFILE"
}

run_dupes stash
run_dupes data
run_dupes hotspare6tb

echo "" | tee -a "$LOGFILE"
echo "--- stats after step 3 ---" | tee -a "$LOGFILE"
"$PYTHON" -m hashall stats 2>&1 | tee -a "$LOGFILE"

echo "" | tee -a "$LOGFILE"
echo "STEP 3 DONE — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
echo ">>> Paste the last ~50 lines to Claude, then run optional step 3.5 (link dedup) before step 4. <<<"
