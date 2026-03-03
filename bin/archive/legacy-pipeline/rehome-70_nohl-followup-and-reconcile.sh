#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-70_nohl-followup-and-reconcile.sh [options]

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --cleanup 0|1             Retry source cleanup during followup (default: 1)
  --retry-failed 0|1        Include rehome_verify_failed tags (default: 0)
  --limit N                 Followup candidate limit (default: 0 = all)
  --print-torrents 0|1      Print per-torrent followup checks (default: 0)
  --fast                    Fast mode (skip torrent-level print unless explicitly set)
  --debug                   Debug mode (force torrent-level print)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

DB_PATH="/home/michael/.hashall/catalog.db"
CLEANUP="1"
RETRY_FAILED="0"
LIMIT="0"
PRINT_TORRENTS="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --cleanup) CLEANUP="${2:-}"; shift 2 ;;
    --retry-failed) RETRY_FAILED="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --print-torrents) PRINT_TORRENTS="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-followup-reconcile-${stamp}.log"
followup_json="${log_dir}/${OUTPUT_PREFIX}-followup-${stamp}.json"
pending_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-followup-pending-${stamp}.txt"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-followup-failed-${stamp}.txt"

if [[ "$FAST_MODE" -eq 1 && "$PRINT_TORRENTS" == "1" ]]; then
  PRINT_TORRENTS="0"
fi
if [[ "$DEBUG_MODE" -eq 1 ]]; then
  PRINT_TORRENTS="1"
fi

{
  hr
  echo "Phase 70: Follow-up verification and reconcile"
  echo "What this does: verify moved groups, retry cleanup, and list pending/failed groups."
  hr
  echo "run_id=${stamp} step=nohl-followup-and-reconcile"
  echo "config db=${DB_PATH} cleanup=${CLEANUP} retry_failed=${RETRY_FAILED} limit=${LIMIT} print_torrents=${PRINT_TORRENTS} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  make rehome-followup \
    REHOME_CATALOG="$DB_PATH" \
    REHOME_FOLLOWUP_CLEANUP="$CLEANUP" \
    REHOME_FOLLOWUP_RETRY_FAILED="$RETRY_FAILED" \
    REHOME_FOLLOWUP_LIMIT="$LIMIT" \
    REHOME_FOLLOWUP_PRINT_TORRENTS="$PRINT_TORRENTS" \
    REHOME_FOLLOWUP_OUTPUT="$followup_json"
  jq -r '.summary' "$followup_json"
  jq -r '.entries[]? | select(.outcome=="pending") | .payload_hash' "$followup_json" | sed '/^$/d' | sort -u > "$pending_hashes"
  jq -r '.entries[]? | select(.outcome=="failed") | .payload_hash' "$followup_json" | sed '/^$/d' | sort -u > "$failed_hashes"
  echo "pending_count=$(wc -l < "$pending_hashes" | tr -d ' ') failed_count=$(wc -l < "$failed_hashes" | tr -d ' ')"
  echo "followup_json=${followup_json}"
  echo "pending_hashes=${pending_hashes}"
  echo "failed_hashes=${failed_hashes}"
  total_groups="$(jq -r '.summary.groups_total // 0' "$followup_json")"
  groups_ok="$(jq -r '.summary.groups_ok // 0' "$followup_json")"
  groups_pending="$(jq -r '.summary.groups_pending // 0' "$followup_json")"
  groups_failed="$(jq -r '.summary.groups_failed // 0' "$followup_json")"
  hr
  echo "Phase 70 complete: groups_total=${total_groups}, ok=${groups_ok}, pending=${groups_pending}, failed=${groups_failed}."
  hr
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "followup_json=${followup_json}"
echo "pending_hashes=${pending_hashes}"
echo "failed_hashes=${failed_hashes}"
