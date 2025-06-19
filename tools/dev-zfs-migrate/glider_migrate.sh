          b#!/bin/bash

set -euo pipefail

# Usage: glider_migrate_v3.sh <SRC_BASE> <DST_BASE> [PARALLEL_JOBS]
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <SRC_BASE> <DST_BASE> [PARALLEL_JOBS]"
  exit 1
fi

SRC_BASE="$1"
DST_BASE="$2"
PARALLEL_JOBS="${3:-8}"  # Default to 8 jobs if not specified
LOG_DIR="$HOME/logs/rsync-migration/$(basename "$SRC_BASE")-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

echo "Starting migration:"
echo "  Source: $SRC_BASE"
echo "  Dest:   $DST_BASE"
echo "  Logs:   $LOG_DIR"
echo "  Parallel Jobs: $PARALLEL_JOBS"
echo ""

find "$SRC_BASE" -mindepth 1 -maxdepth 1 -type d | \
  parallel --bar --eta --delay 1 --line-buffer -j${PARALLEL_JOBS} '
    DIRNAME=$(basename "{}")
    SRC="{}"
    DST="'"$DST_BASE"'/${DIRNAME}"
    LOG="'"$LOG_DIR"'/${DIRNAME}.log"

    echo "[START] Syncing $SRC -> $DST" > "$LOG"

    sudo rsync -aHv --partial --inplace --stats "$SRC/" "$DST/" >> "$LOG" 2>&1

    if [[ $? -eq 0 ]]; then
        echo "[DONE]  $SRC" >> "$LOG"
    else
        echo "[ERROR] $SRC" >> "$LOG"
    fi
  '

echo "✅ Migration complete. Logs: $LOG_DIR"
