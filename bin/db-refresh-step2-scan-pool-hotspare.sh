#!/usr/bin/env bash
# STEP 2: Scan /pool/data, /pool/media, and /mnt/hotspare6tb
# All pool datasets and hotspare should be present in catalog devices/files tables.
# Pause after this and paste tail of log to Claude before continuing.
set -euo pipefail


SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.0"
LAST_UPDATED="2026-04-09T07:05:00-04:00"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$REPO/src"

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step2-scan-pool-hotspare-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================"
echo "STEP 2: scan /pool/data + /pool/media + /mnt/hotspare6tb — $(date '+%F %T')"
echo "log: $LOGFILE"
echo "================================================================"

echo "--- scan /pool/data ---"
"$PYTHON" -m hashall scan /pool/data --parallel --workers 8 2>&1 | tee "$LOGFILE"

echo ""
echo "--- scan /pool/media ---"
"$PYTHON" -m hashall scan /pool/media --parallel --workers 8 2>&1 | tee -a "$LOGFILE"

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
