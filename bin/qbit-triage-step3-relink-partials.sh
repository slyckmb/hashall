#!/usr/bin/env bash
# Relink partial-download and missingFiles torrents to their canonical content locations.
# Uses the hashall catalog to find where content actually lives on disk, then calls
# qBittorrent's setLocation + recheckTorrents APIs to fix broken save_paths.
#
# Three categories of fix:
#   RELINK   — content found at a different path → setLocation + recheck
#   RECHECK  — content found at qbit's current save_path → recheck only
#   UNRESOLVED — content not found anywhere → manual investigation needed
#
# Default: dry-run (no changes). Pass --apply to execute.
# Usage: bin/qbit-triage-step3-relink-partials.sh [--apply]
set -euo pipefail

set +x
source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"

DB="${HOME}/.hashall/catalog.db"

LOGDIR="$HOME/.logs/hashall/reports/qbit-triage"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/relink-partials-$(date +%Y%m%d-%H%M%S).log"

PARTIAL_HASHES="$LOGDIR/partial-hashes.txt"
MISSING_HASHES="$LOGDIR/missing-files-hashes.txt"

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}
qb_login

echo "================================================================" | tee -a "$LOG"
echo "RELINK PARTIALS — $(date '+%F %T')  [APPLY=$APPLY]" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"

ALL_JSON=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info")

# ------------------------------------------------------------------
# resolve_hash HASH QBIT_SAVE_PATH
#   Sets globals: RESOLVED_TYPE, RESOLVED_NEW_SAVE
#   RESOLVED_TYPE: relink | recheck | unresolved
#   RESOLVED_NEW_SAVE: the save_path to use (for relink), or "" (recheck)
# ------------------------------------------------------------------
RESOLVED_TYPE=""
RESOLVED_NEW_SAVE=""

resolve_hash() {
  local HASH="$1"
  local QBIT_SAVE="$2"
  RESOLVED_TYPE="unresolved"
  RESOLVED_NEW_SAVE=""

  # Fetch catalog row
  local ROOT_NAME ROOT_PATH DEVICE_ID
  IFS='|' read -r ROOT_NAME ROOT_PATH DEVICE_ID < <(
    sqlite3 "$DB" \
      "SELECT COALESCE(ti.root_name,''),
              COALESCE(p.root_path,''),
              COALESCE(p.device_id,-1)
       FROM torrent_instances ti
       JOIN payloads p ON ti.payload_id = p.payload_id
       WHERE ti.torrent_hash = '${HASH}'" 2>/dev/null
  )

  if [[ -z "$ROOT_NAME" ]]; then
    RESOLVED_TYPE="unresolved:not_in_catalog"
    return
  fi

  local DISK_SAVE_PATH=""

  # ------ Find canonical save_path on disk ------

  if [[ "$ROOT_PATH" == /incomplete_torrents/* || "$DEVICE_ID" == "-1" ]]; then
    # Payload couldn't be matched to a device. Search active files on pool then stash.
    # Try multi-file torrent (root_name is a directory):
    local FB
    FB=$(sqlite3 "$DB" \
      "SELECT path FROM files_231
       WHERE status='active' AND path LIKE '%/${ROOT_NAME}/%'
         AND path NOT LIKE '%.torrent'
       ORDER BY CASE WHEN path LIKE 'seeds/%' THEN 0 ELSE 1 END
       LIMIT 1" 2>/dev/null || true)

    if [[ -z "$FB" ]]; then
      # Try single-file torrent (root_name is a filename, possibly with or without extension)
      FB=$(sqlite3 "$DB" \
        "SELECT path FROM files_231
         WHERE status='active'
           AND (path LIKE '%/${ROOT_NAME}' OR path LIKE '%/${ROOT_NAME}.%')
           AND path NOT LIKE '%.torrent'
         ORDER BY CASE WHEN path LIKE 'seeds/%' THEN 0 ELSE 1 END
         LIMIT 1" 2>/dev/null || true)
    fi

    if [[ -n "$FB" ]]; then
      local FB_FULL="/pool/data/$FB"
      DISK_SAVE_PATH="${FB_FULL%%/${ROOT_NAME}*}"
    else
      # Fallback to stash catalog
      FB=$(sqlite3 "$DB" \
        "SELECT path FROM files_44
         WHERE status='active'
           AND (path LIKE '%/${ROOT_NAME}/%' OR path LIKE '%/${ROOT_NAME}'
                OR path LIKE '%/${ROOT_NAME}.%')
           AND path NOT LIKE '%.torrent'
         LIMIT 1" 2>/dev/null || true)
      if [[ -n "$FB" ]]; then
        local FB_FULL="/stash/media/$FB"
        DISK_SAVE_PATH="${FB_FULL%%/${ROOT_NAME}*}"
      fi
    fi

  elif [[ "$DEVICE_ID" == "231" ]]; then
    # Pool: root_path is /pool/data/...
    DISK_SAVE_PATH="${ROOT_PATH%%/${ROOT_NAME}*}"

  elif [[ "$DEVICE_ID" == "44" ]]; then
    # Stash: root_path is /stash/media/...
    DISK_SAVE_PATH="${ROOT_PATH%%/${ROOT_NAME}*}"

  else
    RESOLVED_TYPE="unresolved:unknown_device_${DEVICE_ID}"
    return
  fi

  if [[ -z "$DISK_SAVE_PATH" || "$DISK_SAVE_PATH" == "$ROOT_PATH" ]]; then
    RESOLVED_TYPE="unresolved:path_strip_failed"
    return
  fi

  # Verify content exists at disk_save_path/root_name
  local CONTENT_PATH="${DISK_SAVE_PATH}/${ROOT_NAME}"
  if [[ ! -e "$CONTENT_PATH" ]]; then
    RESOLVED_TYPE="unresolved:content_missing:${CONTENT_PATH}"
    return
  fi

  # Convert stash absolute paths to qbit bind-mount paths (/stash/media/ → /data/media/)
  local NEW_SAVE
  if [[ "$DISK_SAVE_PATH" == /stash/media/* ]]; then
    NEW_SAVE="/data/media/${DISK_SAVE_PATH#/stash/media/}"
  else
    NEW_SAVE="$DISK_SAVE_PATH"
  fi

  # Compare with qbit's current save_path (strip trailing slashes for comparison)
  local NORM_QBIT="${QBIT_SAVE%/}"
  local NORM_NEW="${NEW_SAVE%/}"

  if [[ "$NORM_NEW" == "$NORM_QBIT" ]]; then
    RESOLVED_TYPE="recheck"
    RESOLVED_NEW_SAVE="$QBIT_SAVE"
  else
    RESOLVED_TYPE="relink"
    RESOLVED_NEW_SAVE="$NEW_SAVE"
  fi
}

# ------------------------------------------------------------------
# Process a file of hashes
# ------------------------------------------------------------------
declare -a RELINK_HASHES=()
declare -a RELINK_PATHS=()
declare -a RECHECK_HASHES=()
declare -a UNRESOLVED_HASHES=()

process_file() {
  local INPUT_FILE="$1"
  local LABEL="${2:-}"

  while IFS= read -r HASH; do
    [[ -z "$HASH" ]] && continue

    # Get qbit's current save_path for this hash
    local QBIT_SAVE
    QBIT_SAVE=$(echo "$ALL_JSON" | \
      jq -r --arg h "$HASH" '.[] | select(.hash == $h) | .save_path // ""')

    if [[ -z "$QBIT_SAVE" ]]; then
      echo "SKIP      [$HASH]${LABEL:+ [$LABEL]} — not found in current qbit state" | tee -a "$LOG"
      continue
    fi

    resolve_hash "$HASH" "$QBIT_SAVE"

    case "$RESOLVED_TYPE" in
      relink)
        echo "RELINK    [$HASH]${LABEL:+ [$LABEL]}" | tee -a "$LOG"
        echo "  FROM: $QBIT_SAVE" | tee -a "$LOG"
        echo "  TO:   $RESOLVED_NEW_SAVE" | tee -a "$LOG"
        RELINK_HASHES+=("$HASH")
        RELINK_PATHS+=("$RESOLVED_NEW_SAVE")
        ;;
      recheck)
        echo "RECHECK   [$HASH]${LABEL:+ [$LABEL]} — content at: $QBIT_SAVE" | tee -a "$LOG"
        RECHECK_HASHES+=("$HASH")
        ;;
      unresolved:*)
        echo "UNRESOLVED [$HASH]${LABEL:+ [$LABEL]} — ${RESOLVED_TYPE#unresolved:}" | tee -a "$LOG"
        UNRESOLVED_HASHES+=("$HASH")
        ;;
      *)
        echo "UNRESOLVED [$HASH]${LABEL:+ [$LABEL]} — $RESOLVED_TYPE" | tee -a "$LOG"
        UNRESOLVED_HASHES+=("$HASH")
        ;;
    esac
  done < "$INPUT_FILE"
}

echo "" | tee -a "$LOG"
echo "--- processing missingFiles (2) ---" | tee -a "$LOG"
process_file "$MISSING_HASHES" "missing"

echo "" | tee -a "$LOG"
echo "--- processing partials (80) ---" | tee -a "$LOG"
process_file "$PARTIAL_HASHES" "partial"

echo "" | tee -a "$LOG"
echo "--- summary ---" | tee -a "$LOG"
echo "RELINK (setLocation + recheck): ${#RELINK_HASHES[@]}" | tee -a "$LOG"
echo "RECHECK only:                   ${#RECHECK_HASHES[@]}" | tee -a "$LOG"
echo "UNRESOLVED (needs investigation): ${#UNRESOLVED_HASHES[@]}" | tee -a "$LOG"
echo "" | tee -a "$LOG"

if [[ ${#UNRESOLVED_HASHES[@]} -gt 0 ]]; then
  echo "Unresolved hashes:" | tee -a "$LOG"
  for H in "${UNRESOLVED_HASHES[@]}"; do
    echo "  $H" | tee -a "$LOG"
  done
  echo "" | tee -a "$LOG"
fi

if [[ "$APPLY" == false ]]; then
  echo "Dry-run complete — no changes made." | tee -a "$LOG"
  echo "Re-run with --apply to execute setLocation + recheck." | tee -a "$LOG"
  echo "log: $LOG"
  exit 0
fi

# ================================================================
# APPLY — execute setLocation then recheckTorrents
# ================================================================

# Re-auth (cookie may have aged out during processing)
qb_login

echo "--- applying setLocation ---" | tee -a "$LOG"
for i in "${!RELINK_HASHES[@]}"; do
  local_hash="${RELINK_HASHES[$i]}"
  local_path="${RELINK_PATHS[$i]}"
  HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/setLocation" \
    --data-urlencode "hashes=${local_hash}" \
    --data-urlencode "location=${local_path}")
  echo "  setLocation $local_hash → $local_path : HTTP $HTTP_CODE" | tee -a "$LOG"
done

echo "" | tee -a "$LOG"
echo "--- triggering recheck on all resolved torrents ---" | tee -a "$LOG"

ALL_RECHECK_HASHES=("${RELINK_HASHES[@]}" "${RECHECK_HASHES[@]}")
TOTAL_RECHECK="${#ALL_RECHECK_HASHES[@]}"

if [[ "$TOTAL_RECHECK" -gt 0 ]]; then
  # Build pipe-delimited hash list for qbit API
  RECHECK_LIST=$(printf '%s|' "${ALL_RECHECK_HASHES[@]}")
  RECHECK_LIST="${RECHECK_LIST%|}"

  HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/recheck" \
    --data-urlencode "hashes=${RECHECK_LIST}")
  echo "  recheckTorrents ($TOTAL_RECHECK hashes): HTTP $HTTP_CODE" | tee -a "$LOG"

  # Immediately stop all rechecked torrents so qbit doesn't auto-start downloads
  echo "" | tee -a "$LOG"
  echo "--- stopping all rechecked torrents to prevent auto-download ---" | tee -a "$LOG"
  HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
    --data-urlencode "hashes=${RECHECK_LIST}")
  echo "  stop ($TOTAL_RECHECK hashes): HTTP $HTTP_CODE" | tee -a "$LOG"
fi

echo "" | tee -a "$LOG"
echo "DONE — $(date '+%F %T')" | tee -a "$LOG"
echo "log: $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo ">>> Rechecks complete (torrents left stopped). Run inspect to see new state. <<<"
