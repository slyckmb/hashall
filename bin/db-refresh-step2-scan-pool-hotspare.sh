#!/usr/bin/env bash
# STEP 2: Scan /pool/data and /mnt/hotspare6tb
# Both should auto-correct from their temp/old device IDs to live IDs.
# Pause after this and paste tail of log to Claude before continuing.
set -euo pipefail

WT="/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$WT/src"

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step2-scan-pool-hotspare-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================"
echo "STEP 2: scan /pool/data + /mnt/hotspare6tb — $(date '+%F %T')"
echo "log: $LOGFILE"
echo "================================================================"

echo "--- scan /pool/data ---"
"$PYTHON" -m hashall scan /pool/data --parallel --workers 8 2>&1 | tee "$LOGFILE"

echo ""
echo "--- scan /mnt/hotspare6tb ---"
"$PYTHON" -m hashall scan /mnt/hotspare6tb --parallel --workers 8 2>&1 | tee -a "$LOGFILE"

echo ""
echo "--- devices list after step 2 ---"
"$PYTHON" -m hashall devices list 2>&1 | tee -a "$LOGFILE"

echo ""
echo "STEP 2 DONE — $(date '+%F %T')"
echo "log: $LOGFILE"
echo ""
echo ">>> Paste the last ~50 lines to Claude before running step 3. <<<"
