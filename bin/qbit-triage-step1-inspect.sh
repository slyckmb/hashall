#!/usr/bin/env bash
# Inspect qbit problem torrents: missingFiles + partial-progress torrents.
# Read-only — no changes made.
set -euo pipefail

set +x
source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"

LOGDIR="$HOME/.logs/hashall/reports/qbit-triage"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/inspect-$(date +%Y%m%d-%H%M%S).log"

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null

ALL_JSON=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info")

echo "================================================================" | tee -a "$LOG"
echo "QBIT TRIAGE INSPECTION — $(date '+%F %T')" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"

# --- missingFiles ---
echo "" | tee -a "$LOG"
echo "--- missingFiles torrents ---" | tee -a "$LOG"
echo "$ALL_JSON" | jq -r '
  .[] | select((.state | ascii_downcase) == "missingfiles")
  | "hash=\(.hash)\n  name=\(.name)\n  save_path=\(.save_path)\n  content_path=\(.content_path // "N/A")\n  size=\(.size)\n  progress=\(.progress)"
' 2>&1 | tee -a "$LOG"

# --- partial progress (1–99%) ---
echo "" | tee -a "$LOG"
echo "--- partial-progress torrents (1-99%) ---" | tee -a "$LOG"
echo "$ALL_JSON" | jq -r '
  .[] | select(.progress > 0.0 and .progress < 1.0)
  | "hash=\(.hash)\n  name=\(.name)\n  state=\(.state)\n  save_path=\(.save_path)\n  progress=\(.progress | . * 100 | round)%\n  size=\(.size)\n  downloaded=\(.downloaded)"
' 2>&1 | tee -a "$LOG"

PARTIAL_COUNT=$(echo "$ALL_JSON" | jq '[.[] | select(.progress > 0.0 and .progress < 1.0)] | length')
MISSING_COUNT=$(echo "$ALL_JSON" | jq '[.[] | select((.state | ascii_downcase) == "missingfiles")] | length')

echo "" | tee -a "$LOG"
echo "--- summary ---" | tee -a "$LOG"
echo "missingFiles: $MISSING_COUNT" | tee -a "$LOG"
echo "partial (1-99%): $PARTIAL_COUNT" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Save hashes to files for use by fix scripts
echo "$ALL_JSON" | jq -r '.[] | select((.state | ascii_downcase) == "missingfiles") | .hash' \
  > "$LOGDIR/missing-files-hashes.txt"
echo "$ALL_JSON" | jq -r '.[] | select(.progress > 0.0 and .progress < 1.0) | .hash' \
  > "$LOGDIR/partial-hashes.txt"

echo "hash files written:" | tee -a "$LOG"
echo "  $LOGDIR/missing-files-hashes.txt" | tee -a "$LOG"
echo "  $LOGDIR/partial-hashes.txt" | tee -a "$LOG"
echo "log: $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo ">>> Paste output to Claude before running step 2. <<<"
