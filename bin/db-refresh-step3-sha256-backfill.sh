#!/usr/bin/env bash
# STEP 3: Targeted SHA256 upgrade — collision candidates only (NOT full backfill).
# Uses `dupes --auto-upgrade` per device: reads only files that share a quick_hash
# (1MB sample). Much faster than full sha256-backfill across all files.
# Run per device so you can monitor per-device progress separately.
# Pause after this and paste tail of log to Claude before running step 4.
set -euo pipefail

REPO="/home/michael/dev/work/hashall"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$REPO/src"

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step3-dupes-upgrade-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================" | tee -a "$LOGFILE"
echo "STEP 3: dupes --auto-upgrade per device — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
echo "Note: only hashes collision candidates (same quick_hash), NOT all files." | tee -a "$LOGFILE"
echo "================================================================" | tee -a "$LOGFILE"

run_dupes() {
  local device="$1"
  echo "" | tee -a "$LOGFILE"
  echo "--- dupes --device $device --- $(date '+%F %T')" | tee -a "$LOGFILE"
  "$PYTHON" -m hashall dupes --device "$device" --auto-upgrade 2>&1 | tee -a "$LOGFILE"
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
echo ">>> Paste the last ~50 lines to Claude before running step 4. <<<"
