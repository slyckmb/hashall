#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-50_nohl-dryrun-group-batch.sh [options]

Options:
  --hashes-file PATH        Plannable payload hash file (default: latest nohl-payload-hashes-plannable-*.txt)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-name NAME          ZFS pool name to guard (default: pool)
  --min-free-pct N          Minimum required pool free % (default: 20)
  --stash-device ID         Stash device id (default: 49)
  --pool-device ID          Pool device id (default: 44)
  --spot-check N            Spot-check files in dryrun (default: 0)
  --limit N                 Limit hashes to process (default: 0 = all)
  --fast                    Fast mode (force spot-check 0)
  --debug                   Debug mode (enable qB debug env and verbose lines)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_plannable_hashes() {
  ls -1t out/reports/rehome-normalize/nohl-payload-hashes-plannable-*.txt 2>/dev/null | head -n1
}

HASHES_FILE=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_NAME="pool"
MIN_FREE_PCT="20"
STASH_DEVICE_ID="49"
POOL_DEVICE_ID="44"
SPOT_CHECK="0"
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-name) POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --stash-device) STASH_DEVICE_ID="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE_ID="${2:-}"; shift 2 ;;
    --spot-check) SPOT_CHECK="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
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

if [[ -z "$HASHES_FILE" ]]; then
  HASHES_FILE="$(latest_plannable_hashes)"
fi
if [[ -z "$HASHES_FILE" || ! -f "$HASHES_FILE" ]]; then
  echo "Missing plannable hashes file; run rehome-40 first or pass --hashes-file" >&2
  exit 3
fi

mapfile -t HASHES < <(sed -e 's/#.*$//' -e 's/[[:space:]]//g' "$HASHES_FILE" | awk 'NF > 0')
if [[ "$LIMIT" -gt 0 && "${#HASHES[@]}" -gt "$LIMIT" ]]; then
  HASHES=("${HASHES[@]:0:$LIMIT}")
fi
if [[ "${#HASHES[@]}" -eq 0 ]]; then
  echo "No hashes to dryrun" >&2
  exit 4
fi
if [[ "$FAST_MODE" -eq 1 ]]; then
  SPOT_CHECK="0"
fi
if [[ "$DEBUG_MODE" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi

pool_free_pct() {
  local used_pct free_pct
  used_pct="$(zpool list -H -o cap "$POOL_NAME" | tr -d ' %')"
  free_pct=$((100 - used_pct))
  echo "$free_pct"
}

assert_pool_space() {
  local free_pct
  free_pct="$(pool_free_pct)"
  if (( free_pct < MIN_FREE_PCT )); then
    echo "ERROR: pool $POOL_NAME free ${free_pct}% < required ${MIN_FREE_PCT}%" >&2
    return 1
  fi
  echo "pool_free_pct=${free_pct} required_min=${MIN_FREE_PCT}"
}

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-dryrun-group-batch-${stamp}.log"
ready_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-ready-${stamp}.txt"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-failed-${stamp}.txt"
blocked_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-blocked-${stamp}.txt"

ok=0
failed=0
blocked=0
> "$ready_hashes"
> "$failed_hashes"
> "$blocked_hashes"

{
  echo "run_id=${stamp} step=nohl-dryrun-group-batch"
  echo "config hashes_file=${HASHES_FILE} db=${DB_PATH} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT} stash_device=${STASH_DEVICE_ID} pool_device=${POOL_DEVICE_ID} spot_check=${SPOT_CHECK} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  total="${#HASHES[@]}"
  for i in "${!HASHES[@]}"; do
    idx=$((i + 1))
    hash="${HASHES[$i]}"
    echo "dryrun idx=${idx}/${total} payload=${hash:0:16} status=start"
    if [[ "$DEBUG_MODE" -eq 1 ]]; then
      echo "debug idx=${idx}/${total} payload=${hash} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT}"
    fi
    if ! assert_pool_space; then
      echo "$hash" >> "$failed_hashes"
      failed=$((failed + 1))
      continue
    fi

    plan_path="${log_dir}/${OUTPUT_PREFIX}-dryrun-plan-${idx}-${hash:0:12}-${stamp}.json"
    if ! PYTHONPATH=src python -m rehome.cli plan \
      --demote \
      --payload-hash "$hash" \
      --catalog "$DB_PATH" \
      --seeding-root /stash/media \
      --seeding-root /data/media \
      --seeding-root /pool/data \
      --library-root /stash/media \
      --library-root /data/media \
      --stash-device "$STASH_DEVICE_ID" \
      --pool-device "$POOL_DEVICE_ID" \
      --stash-seeding-root /stash/media/torrents/seeding \
      --pool-seeding-root /pool/data/seeds \
      --pool-payload-root /pool/data/seeds \
      --output "$plan_path"; then
      echo "dryrun idx=${idx}/${total} payload=${hash:0:16} status=plan_error"
      echo "$hash" >> "$failed_hashes"
      failed=$((failed + 1))
      continue
    fi

    decision="$(jq -r '.decision // ""' "$plan_path")"
    source_path="$(jq -r '.source_path // ""' "$plan_path")"
    target_path="$(jq -r '.target_path // ""' "$plan_path")"
    if [[ "$decision" == "BLOCK" ]]; then
      echo "dryrun idx=${idx}/${total} payload=${hash:0:16} decision=BLOCK from=${source_path} to=${target_path} status=blocked"
      echo "$hash" >> "$blocked_hashes"
      blocked=$((blocked + 1))
      continue
    fi

    if PYTHONPATH=src python -u -m rehome.cli apply "$plan_path" --dryrun --catalog "$DB_PATH" --spot-check "$SPOT_CHECK"; then
      echo "dryrun idx=${idx}/${total} payload=${hash:0:16} decision=${decision} from=${source_path} to=${target_path} status=ok"
      echo "$hash" >> "$ready_hashes"
      ok=$((ok + 1))
    else
      echo "dryrun idx=${idx}/${total} payload=${hash:0:16} decision=${decision} from=${source_path} to=${target_path} status=error"
      echo "$hash" >> "$failed_hashes"
      failed=$((failed + 1))
    fi
  done
  echo "summary total=${total} ok=${ok} failed=${failed} blocked=${blocked}"
  echo "ready_hashes=${ready_hashes}"
  echo "failed_hashes=${failed_hashes}"
  echo "blocked_hashes=${blocked_hashes}"
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "ready_hashes=${ready_hashes}"
echo "failed_hashes=${failed_hashes}"
echo "blocked_hashes=${blocked_hashes}"
