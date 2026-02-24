#!/usr/bin/env bash
# Start all stoppedUP torrents (100% complete, just need resuming).
# Starts in one batch then monitors for any that flip to missingFiles.
# Safe to run — only touches torrents already at 100% progress.
set -euo pipefail

set +x
source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"

LOGDIR="$HOME/.logs/hashall/reports/qbit-triage"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/start-stopped-up-$(date +%Y%m%d-%H%M%S).log"

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null

echo "================================================================" | tee -a "$LOG"
echo "START stoppedUP torrents — $(date '+%F %T')" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"

ALL_JSON=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info")

# Collect stoppedUP hashes
STOPPED_UP_HASHES=$(echo "$ALL_JSON" | jq -r '
  .[] | select((.state | ascii_downcase) == "stoppedup") | .hash
')
COUNT=$(echo "$STOPPED_UP_HASHES" | grep -c . || true)
echo "stoppedUP count: $COUNT" | tee -a "$LOG"

if [[ "$COUNT" -eq 0 ]]; then
  echo "Nothing to start." | tee -a "$LOG"
  exit 0
fi

# Build pipe-delimited hash list for API
HASH_LIST=$(echo "$STOPPED_UP_HASHES" | tr '\n' '|' | sed 's/|$//')

echo "Starting $COUNT torrents... $(date '+%F %T')" | tee -a "$LOG"
HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
  -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/start" \
  --data-urlencode "hashes=$HASH_LIST")
echo "API response: $HTTP_CODE" | tee -a "$LOG"

if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "202" ]]; then
  echo "ERROR: unexpected HTTP $HTTP_CODE from start endpoint" | tee -a "$LOG"
  exit 1
fi

echo "Start command sent. Waiting 15s for state to settle..." | tee -a "$LOG"
sleep 15

# Re-login (cookie may have expired)
curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null

# Snapshot state after start
AFTER_JSON=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info")

MISSING_AFTER=$(echo "$AFTER_JSON" | jq '[.[] | select((.state | ascii_downcase) == "missingfiles")] | length')
STOPPED_UP_AFTER=$(echo "$AFTER_JSON" | jq '[.[] | select((.state | ascii_downcase) == "stoppedup")] | length')
STALLED_UP_AFTER=$(echo "$AFTER_JSON" | jq '[.[] | select((.state | ascii_downcase) == "stalledup")] | length')
UPLOADING_AFTER=$(echo "$AFTER_JSON" | jq '[.[] | select((.state | ascii_downcase) == "uploading")] | length')

echo "" | tee -a "$LOG"
echo "--- state 15s after start ---" | tee -a "$LOG"
echo "stoppedUP:    $STOPPED_UP_AFTER  (was $COUNT)" | tee -a "$LOG"
echo "stalledUP:    $STALLED_UP_AFTER" | tee -a "$LOG"
echo "uploading:    $UPLOADING_AFTER" | tee -a "$LOG"
echo "missingFiles: $MISSING_AFTER" | tee -a "$LOG"

# List any NEW missingFiles
if [[ "$MISSING_AFTER" -gt 2 ]]; then
  echo "" | tee -a "$LOG"
  echo "⚠️  New missingFiles detected — listing:" | tee -a "$LOG"
  echo "$AFTER_JSON" | jq -r '
    .[] | select((.state | ascii_downcase) == "missingfiles")
    | "  \(.hash) \(.name)\n    save_path=\(.save_path)"
  ' | tee -a "$LOG"
fi

echo "" | tee -a "$LOG"
echo "DONE — $(date '+%F %T')" | tee -a "$LOG"
echo "log: $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo ">>> Paste output to Claude. Run watchdog to monitor ongoing state: <<<"
echo "    QBIT_USER=\$QBITTORRENTAPI_USERNAME QBIT_PASS=\$QBITTORRENTAPI_PASSWORD \\"
echo "      bin/rehome-99_qb-checking-watch.sh --interval 30 --enforce-paused-dl"
