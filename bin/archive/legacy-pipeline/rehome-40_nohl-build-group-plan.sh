#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-40_nohl-build-group-plan.sh [options]

Options:
  --hashes-file PATH        Ranked payload hash file (default: latest nohl-payload-hashes-ranked-*.txt)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --stash-device ID         Stash device id (default: 49)
  --pool-device ID          Pool device id (default: 44)
  --limit N                 Limit payload groups from hashes file (default: 0 = all)
  --resume 0|1              Resume from latest/selected manifest (default: 1)
  --resume-manifest PATH    Resume from explicit manifest path
  --fast                    Fast mode (minimal per-item diagnostics)
  --debug                   Debug mode (verbose command tracing)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_hashes_file() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-payload-hashes-ranked-*.txt 2>/dev/null | head -n1
}

latest_manifest_file() {
  local prefix="$1"
  ls -1t "$HOME/.logs/hashall/reports/rehome-normalize/${prefix}-plan-manifest-"*.json 2>/dev/null | head -n1
}

HASHES_FILE=""
DB_PATH="/home/michael/.hashall/catalog.db"
STASH_DEVICE_ID="49"
POOL_DEVICE_ID="44"
LIMIT="0"
RESUME="1"
RESUME_MANIFEST=""
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --stash-device) STASH_DEVICE_ID="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE_ID="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --resume) RESUME="${2:-}"; shift 2 ;;
    --resume-manifest) RESUME_MANIFEST="${2:-}"; shift 2 ;;
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
  HASHES_FILE="$(latest_hashes_file)"
fi
if [[ -z "$HASHES_FILE" || ! -f "$HASHES_FILE" ]]; then
  echo "Missing hashes file; run rehome-30 first or pass --hashes-file" >&2
  exit 3
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-build-group-plan-${stamp}.log"
manifest_json="${log_dir}/${OUTPUT_PREFIX}-plan-manifest-${stamp}.json"
plan_dir="${log_dir}/${OUTPUT_PREFIX}-plans-${stamp}"

if [[ "$RESUME" == "1" ]]; then
  if [[ -z "$RESUME_MANIFEST" ]]; then
    RESUME_MANIFEST="$(latest_manifest_file "$OUTPUT_PREFIX")"
  fi
  if [[ -n "$RESUME_MANIFEST" && -f "$RESUME_MANIFEST" ]]; then
    manifest_json="$RESUME_MANIFEST"
    prior_output_dir="$(jq -r '.output_dir // empty' "$manifest_json" 2>/dev/null || true)"
    if [[ -n "$prior_output_dir" ]]; then
      plan_dir="$prior_output_dir"
    fi
  fi
fi

mkdir -p "$plan_dir"
plannable_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-plannable-${stamp}.txt"
blocked_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-blocked-${stamp}.txt"
report_tsv="${log_dir}/${OUTPUT_PREFIX}-plan-report-${stamp}.tsv"

resume_flag="--resume"
if [[ "$RESUME" != "1" ]]; then
  resume_flag="--no-resume"
fi

{
  hr
  echo "Phase 40: Build per-group rehome plans"
  echo "What this does: generate one actionable rehome plan per payload group."
  hr
  echo "run_id=${stamp} step=nohl-build-group-plan"
  echo "config hashes_file=${HASHES_FILE} db=${DB_PATH} stash_device=${STASH_DEVICE_ID} pool_device=${POOL_DEVICE_ID} limit=${LIMIT} resume=${RESUME} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  echo "config manifest=${manifest_json} plan_dir=${plan_dir}"

  cmd=(
    python -u -m rehome.cli plan-batch
    --demote
    --payload-hashes-file "$HASHES_FILE"
    --catalog "$DB_PATH"
    --seeding-root /stash/media
    --seeding-root /data/media
    --seeding-root /pool/data
    --library-root /stash/media
    --library-root /data/media
    --stash-device "$STASH_DEVICE_ID"
    --pool-device "$POOL_DEVICE_ID"
    --stash-seeding-root /stash/media/torrents/seeding
    --pool-seeding-root /pool/data/seeds
    --pool-payload-root /pool/data/seeds
    --output-dir "$plan_dir"
    --manifest "$manifest_json"
    --report-tsv "$report_tsv"
    --plannable-hashes-out "$plannable_hashes"
    --blocked-hashes-out "$blocked_hashes"
    --limit "$LIMIT"
    "$resume_flag"
    --output-prefix "$OUTPUT_PREFIX"
  )
  if [[ "$DEBUG_MODE" == "1" ]]; then
    echo "debug cmd=${cmd[*]}"
  fi

  PYTHONPATH=src "${cmd[@]}"

  if [[ -f "$manifest_json" ]]; then
    input_hashes="$(jq -r '.summary.input_hashes // 0' "$manifest_json")"
    plannable_count="$(jq -r '.summary.plannable // 0' "$manifest_json")"
    blocked_count="$(jq -r '.summary.blocked // 0' "$manifest_json")"
    error_count="$(jq -r '.summary.errors // 0' "$manifest_json")"
    elapsed_s="$(jq -r '.summary.elapsed_s // 0' "$manifest_json")"
    hr
    echo "Phase 40 complete: planned ${plannable_count}/${input_hashes}, blocked ${blocked_count}, errors ${error_count}, elapsed ${elapsed_s}s."
    hr
  fi
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "manifest_json=${manifest_json}"
echo "plannable_hashes=${plannable_hashes}"
echo "blocked_hashes=${blocked_hashes}"
echo "report_tsv=${report_tsv}"
