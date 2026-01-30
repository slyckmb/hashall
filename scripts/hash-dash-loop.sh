#!/bin/bash
set -euo pipefail

SCRIPT_VERSION="v6.3.2"
DB_PATH="${1:-$HOME/.hashall/hashall.sqlite3}"
DB_PATH="$(realpath "$DB_PATH")"

LAST_SCAN_ID=""
LAST_ROOT_PATH=""
LAST_STATS=""
LAST_UPDATED="N/A"
FILE_COUNT_ON_DISK="N/A"

detect_root_path_from_ps() {
  ps aux | grep '[f]ilehash_tool.py scan' | awk '
    {
      for (i = 1; i < NF; i++) {
        if ($i == "scan") {
          print $(i+1);
          exit;
        }
      }
    }'
}

get_scan_info() {
  local raw
  raw=$(sqlite3 -batch -noheader "$DB_PATH" <<EOF 2>/dev/null
PRAGMA busy_timeout=3000;
SELECT scan_id || '|' || root_path FROM scan_session ORDER BY start_time DESC LIMIT 1;
EOF
  )

  raw=$(echo "$raw" | grep '|' | head -n1)

  if [[ "$raw" == *"|"* ]]; then
    LAST_SCAN_ID="${raw%%|*}"
    LAST_ROOT_PATH="${raw##*|}"

    if [[ "$LAST_ROOT_PATH" == "/target" || -z "$LAST_ROOT_PATH" ]]; then
      local ps_path
      ps_path=$(detect_root_path_from_ps)
      if [[ -n "$ps_path" ]]; then
        echo "[DEBUG] Overriding /target with detected path: $ps_path"
        LAST_ROOT_PATH="$ps_path"
      fi
    fi

    echo "[DEBUG] Updated scan info at $(date +%T)"
    LAST_UPDATED="$(date +'%Y-%m-%d %H:%M:%S')"
    return 0
  else
    return 1
  fi
}

get_scan_stats() {
  local stats
  stats=$(sqlite3 -batch -noheader "$DB_PATH" <<EOF 2>/dev/null
PRAGMA busy_timeout=3000;
WITH current_scan AS (
  SELECT scan_id FROM scan_session ORDER BY start_time DESC LIMIT 1
)
SELECT
  (SELECT COUNT(*) FROM files WHERE scan_id = current_scan.scan_id),
  (SELECT COUNT(*) FROM files WHERE scan_id = current_scan.scan_id AND sha1 IS NOT NULL)
FROM current_scan;
EOF
  )

  if [[ "$stats" == *"|"* ]]; then
    LAST_STATS="$stats"
    return 0
  else
    return 1
  fi
}

count_files_on_disk() {
  if [[ -n "$LAST_ROOT_PATH" && -d "$LAST_ROOT_PATH" ]]; then
    FILE_COUNT_ON_DISK=$(find "$LAST_ROOT_PATH" -type f 2>/dev/null | wc -l)
  else
    FILE_COUNT_ON_DISK="N/A"
  fi
}

while true; do
  clear
  echo "🔧 Hash-Dash — Dashboard Monitor ($SCRIPT_VERSION)"
  echo

  get_scan_info || echo "[WARN] DB locked — using previous scan info"
  get_scan_stats || echo "[WARN] DB locked — using previous scan stats"
  count_files_on_disk

  echo "📅 Last Update:      $LAST_UPDATED"
  echo "📦 Scan Session:     ${LAST_SCAN_ID:-N/A}"
  echo "📁 Root Path:        ${LAST_ROOT_PATH:-N/A}"
  echo "📂 Files on Disk:    $FILE_COUNT_ON_DISK"
  echo "---------------------------------------------------------------"

  if [[ -n "$LAST_STATS" ]]; then
    echo "$LAST_STATS" | awk -F"|" '{
      total=$1; full=$2;
      pending = total - full;
      percent = (total > 0) ? (full / total) * 100 : 0;
      printf "🧾 Files tracked in DB: %d\n", total;
      printf "🔐 Full hashes complete: %d\n", full;
      printf "⏳ Pending verification: %d\n", pending;
      printf "✅ Verified %% complete:  %.2f%%\n", percent;
    }'
  else
    echo "⚠️  No scan stats available yet."
  fi

  sleep 5
done
