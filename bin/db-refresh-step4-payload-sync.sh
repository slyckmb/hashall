#!/usr/bin/env bash
# STEP 4: Payload sync — maps qBittorrent torrents to catalog payloads.
# Fast (API calls only). Needs qbit secrets.
# Paste full output to Claude — torrent count and any errors matter.
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
