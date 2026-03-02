#!/usr/bin/env bash
# STEP 1: Scan /stash/media
# Tests the device-id rotation fix (49→44).
# Pause after this and paste tail of log to Claude before continuing.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$REPO/src"

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step1-scan-stash-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================"
echo "STEP 1: scan /stash/media — $(date '+%F %T')"
echo "log: $LOGFILE"
echo "================================================================"

"$PYTHON" -m hashall scan /stash/media          --parallel --workers 8 2>&1 | tee    "$LOGFILE"
"$PYTHON" -m hashall scan /stash/home/michael  --parallel --workers 8 2>&1 | tee -a "$LOGFILE"
"$PYTHON" -m hashall scan /stash/home/kimberly --parallel --workers 8 2>&1 | tee -a "$LOGFILE"
"$PYTHON" -m hashall scan /stash/hiker/cloud    --parallel --workers 8 2>&1 | tee -a "$LOGFILE"
"$PYTHON" -m hashall scan /stash/hiker/computing --parallel --workers 4 2>&1 | tee -a "$LOGFILE"
"$PYTHON" -m hashall scan /stash/secrets        --parallel --workers 4 2>&1 | tee -a "$LOGFILE"

echo ""
echo "--- devices list after step 1 ---"
"$PYTHON" -m hashall devices list 2>&1 | tee -a "$LOGFILE"

echo ""
echo "STEP 1 DONE — $(date '+%F %T')"
echo "log: $LOGFILE"
echo ""
echo ">>> Paste the last ~40 lines to Claude before running step 2. <<<"
