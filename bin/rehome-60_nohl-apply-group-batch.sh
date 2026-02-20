#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-60_nohl-apply-group-batch.sh [options]

Options:
  --hashes-file PATH        Dryrun-ready payload hash file (default: latest nohl-payload-hashes-dryrun-ready-*.txt)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-name NAME          ZFS pool name to guard (default: pool)
  --min-free-pct N          Minimum required free percent on pool (default: 20)
  --pool-device ID          Pool device id (default: 44)
  --stash-device ID         Stash device id (default: 49)
  --spot-check N            Spot-check files during apply (default: 0)
  --debug                   Enable HASHALL_REHOME_QB_DEBUG=1
  --limit N                 Limit hashes to process (default: 0 = all)
  --fast                    Fast mode (no additional behavior change; explicit run profile)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_ready_hashes() {
  ls -1t out/reports/rehome-normalize/nohl-payload-hashes-dryrun-ready-*.txt 2>/dev/null | head -n1
}

HASHES_FILE=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_NAME="pool"
MIN_FREE_PCT="20"
POOL_DEVICE_ID="44"
STASH_DEVICE_ID="49"
SPOT_CHECK="0"
DEBUG_MODE=0
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-name) POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE_ID="${2:-}"; shift 2 ;;
    --stash-device) STASH_DEVICE_ID="${2:-}"; shift 2 ;;
    --spot-check) SPOT_CHECK="${2:-}"; shift 2 ;;
    --debug) DEBUG_MODE=1; shift ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
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

if [[ -z "$HASHES_FILE" ]]; then
  HASHES_FILE="$(latest_ready_hashes)"
fi
if [[ -z "$HASHES_FILE" || ! -f "$HASHES_FILE" ]]; then
  echo "Missing ready hashes file; run rehome-50 first or pass --hashes-file" >&2
  exit 3
fi

mapfile -t HASHES < <(sed -e 's/#.*$//' -e 's/[[:space:]]//g' "$HASHES_FILE" | awk 'NF > 0')
if [[ "$LIMIT" -gt 0 && "${#HASHES[@]}" -gt "$LIMIT" ]]; then
  HASHES=("${HASHES[@]:0:$LIMIT}")
fi
if [[ "${#HASHES[@]}" -eq 0 ]]; then
  echo "No hashes to apply" >&2
  exit 4
fi

if [[ "$DEBUG_MODE" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-apply-group-batch-${stamp}.log"
ok_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-ok-${stamp}.txt"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-failed-${stamp}.txt"
> "$ok_hashes"
> "$failed_hashes"

ok=0
failed=0
{
  echo "run_id=${stamp} step=nohl-apply-group-batch"
  echo "config hashes_file=${HASHES_FILE} db=${DB_PATH} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT} stash_device=${STASH_DEVICE_ID} pool_device=${POOL_DEVICE_ID} spot_check=${SPOT_CHECK} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  total="${#HASHES[@]}"
  for i in "${!HASHES[@]}"; do
    idx=$((i + 1))
    hash="${HASHES[$i]}"
    echo "apply idx=${idx}/${total} payload=${hash:0:16} status=start"
    if [[ "$DEBUG_MODE" -eq 1 ]]; then
      echo "debug idx=${idx}/${total} payload=${hash} min_free_pct=${MIN_FREE_PCT} pool_name=${POOL_NAME}"
    fi
    if bin/rehome-10_apply-batch-with-guards.sh \
      --db "$DB_PATH" \
      --pool-name "$POOL_NAME" \
      --min-free-pct "$MIN_FREE_PCT" \
      --pool-device "$POOL_DEVICE_ID" \
      --stash-device "$STASH_DEVICE_ID" \
      --spot-check "$SPOT_CHECK" \
      --followup 0 \
      --hash "$hash"; then
      echo "apply idx=${idx}/${total} payload=${hash:0:16} status=ok"
      echo "$hash" >> "$ok_hashes"
      ok=$((ok + 1))
    else
      echo "apply idx=${idx}/${total} payload=${hash:0:16} status=error"
      echo "$hash" >> "$failed_hashes"
      failed=$((failed + 1))
    fi
  done
  echo "summary total=${total} ok=${ok} failed=${failed}"
  echo "ok_hashes=${ok_hashes}"
  echo "failed_hashes=${failed_hashes}"
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "ok_hashes=${ok_hashes}"
echo "failed_hashes=${failed_hashes}"
