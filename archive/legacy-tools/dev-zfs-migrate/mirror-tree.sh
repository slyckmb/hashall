#!/bin/bash
# mirror_tree.sh — Safely mirror a source tree to a destination using rsync
# Default: dry-run mode
# Use --force to allow actual deletion/sync

set -euo pipefail

SRC="/mnt/media/Downloads/torrents/orphaned_data/"
DST="/pool/data/torrents_orphaned_data/"
LOG="./tmp/mirror_tree_rsync.log"

# Default to dry-run unless --force is explicitly provided
RSYNC_FLAGS="-avh --progress --itemize-changes --delete --dry-run"

if [[ "${1:-}" == "--force" ]]; then
  echo "[!] Force mode enabled — real file operations will occur."
  RSYNC_FLAGS="-avh --progress --itemize-changes --delete"
else
  echo "[*] Running in dry-run mode. Use '--force' to apply changes."
fi

echo "[*] Source:      $SRC"
echo "[*] Destination: $DST"
echo "[*] Log:         $LOG"
echo

# Execute the rsync command and log output
rsync $RSYNC_FLAGS "$SRC" "$DST" | tee "$LOG"

# Summarize results
if [[ "$RSYNC_FLAGS" == *"--dry-run"* ]]; then
  echo
  echo "[*] Dry-run completed. Review $LOG for what would change."
  echo "[*] Run again with '--force' to apply changes."
else
  echo
  echo "[✔] Sync completed. Changes have been applied."
fi
