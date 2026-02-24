#!/usr/bin/env bash
# STEP 4: Payload sync — maps qBittorrent torrents to catalog payloads.
# Fast (API calls only). Needs qbit secrets.
# Paste full output to Claude — torrent count and any errors matter.
set -euo pipefail

WT="/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$WT/src"

LOGDIR="$WT/out/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/step4-payload-sync-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================"
echo "STEP 4: payload sync — $(date '+%F %T')"
echo "log: $LOGFILE"
echo "================================================================"

set +x
source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null || {
  echo "ERROR: could not source qbit secrets at /home/michael/dev/secrets/qbittorrent/api.env"
  exit 1
}

"$PYTHON" -m hashall payload sync \
  --qbit-url  "http://localhost:9003" \
  --qbit-user "$QBITTORRENTAPI_USERNAME" \
  --qbit-pass "$QBITTORRENTAPI_PASSWORD" \
  2>&1 | tee "$LOGFILE"

echo ""
echo "--- stats after payload sync ---"
"$PYTHON" -m hashall stats 2>&1 | tee -a "$LOGFILE"

echo ""
echo "STEP 4 DONE — $(date '+%F %T')"
echo "log: $LOGFILE"
echo ""
echo ">>> Paste full output to Claude — DB refresh complete, qbit triage is next. <<<"
