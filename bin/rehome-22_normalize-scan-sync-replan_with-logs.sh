#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-22_normalize-scan-sync-replan_with-logs.sh --plan PLAN.json [options]

What it does:
  1) Extract skipped source_path values from a normalize plan.
  2) Scan existing skipped roots (directory or parent of file source path).
  3) Run one payload sync using --path-prefix-file.
  4) Build a fresh normalize plan.

Options:
  --plan PATH               Input normalize plan JSON with skipped entries (required)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-device ID          Pool device_id (default: 44)
  --pool-root PATH          Pool seeding root (default: /pool/data/seeds)
  --stash-root PATH         Stash seeding root hint (default: /stash/media/torrents/seeding)
  --limit N                 Normalize candidate limit (default: 0 = all)
  --all-mismatches          Include non-flat mismatches (default: flat-only on)
  --scan-hash-mode MODE     Scan hash mode: fast|full|upgrade (default: fast)
  --output PATH             New plan output JSON path (default: auto timestamped)
  -h, --help                Show help
USAGE
}

INPUT_PLAN=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_DEVICE="44"
POOL_ROOT="/pool/data/seeds"
STASH_ROOT="/stash/media/torrents/seeding"
LIMIT="0"
FLAT_ONLY="1"
SCAN_HASH_MODE="fast"
PLAN_OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) INPUT_PLAN="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE="${2:-}"; shift 2 ;;
    --pool-root) POOL_ROOT="${2:-}"; shift 2 ;;
    --stash-root) STASH_ROOT="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --all-mismatches) FLAT_ONLY="0"; shift ;;
    --scan-hash-mode) SCAN_HASH_MODE="${2:-}"; shift 2 ;;
    --output) PLAN_OUTPUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$INPUT_PLAN" ]]; then
  echo "Missing required --plan" >&2
  usage
  exit 2
fi
if [[ ! -f "$INPUT_PLAN" ]]; then
  echo "Plan not found: $INPUT_PLAN" >&2
  exit 2
fi
if [[ "$SCAN_HASH_MODE" != "fast" && "$SCAN_HASH_MODE" != "full" && "$SCAN_HASH_MODE" != "upgrade" ]]; then
  echo "Invalid --scan-hash-mode: $SCAN_HASH_MODE (expected fast|full|upgrade)" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTHONUNBUFFERED=1
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
run_log="${log_dir}/rehome-normalize-scan-sync-replan-run-${stamp}.log"
scan_log="${log_dir}/rehome-normalize-scan-sync-replan-scan-${stamp}.log"
sync_log="${log_dir}/rehome-normalize-scan-sync-replan-sync-${stamp}.log"
plan_log="${log_dir}/rehome-normalize-scan-sync-replan-plan-${stamp}.log"
prefix_file="/tmp/rehome-skipped-prefixes-${stamp}.txt"
scan_roots_file="/tmp/rehome-skipped-scan-roots-${stamp}.txt"

if [[ -z "$PLAN_OUTPUT" ]]; then
  PLAN_OUTPUT="${log_dir}/rehome-plan-normalize-scan-sync-retry-${stamp}.json"
fi

HASHALL_SEMVER="$(PYTHONPATH=src python - <<'PY'
from hashall import __version__
print(__version__)
PY
)"
REHOME_SEMVER="$(PYTHONPATH=src python - <<'PY'
from rehome import __version__
print(__version__)
PY
)"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "tool_semver_hashall=${HASHALL_SEMVER} tool_semver_rehome=${REHOME_SEMVER} git_sha=${GIT_SHA}" | tee "$run_log"
echo "run_id=${stamp} step=scan-sync-replan input_plan=${INPUT_PLAN}" | tee -a "$run_log"

echo "step=extract_skipped_prefixes cmd=jq" | tee -a "$run_log"
jq -r '.skipped[].source_path' "$INPUT_PLAN" | sed '/^$/d' | sort -u | tee "$prefix_file" > /dev/null
prefix_count="$(wc -l < "$prefix_file" | tr -d ' ')"
echo "skipped_prefix_count=${prefix_count} prefix_file=${prefix_file}" | tee -a "$run_log"
if [[ "$prefix_count" == "0" ]]; then
  echo "No skipped source_path entries found in input plan" | tee -a "$run_log"
  exit 1
fi

echo "step=derive_scan_roots" | tee -a "$run_log"
while IFS= read -r source_path; do
  if [[ -d "$source_path" ]]; then
    printf '%s\n' "$source_path"
  elif [[ -f "$source_path" ]]; then
    dirname "$source_path"
  fi
done < "$prefix_file" | sed '/^$/d' | sort -u | tee "$scan_roots_file" > /dev/null
scan_root_count="$(wc -l < "$scan_roots_file" | tr -d ' ')"
echo "scan_root_count=${scan_root_count} scan_roots_file=${scan_roots_file}" | tee -a "$run_log"

if [[ "$scan_root_count" != "0" ]]; then
  echo "step=scan_roots cmd=python -m hashall.cli scan" | tee -a "$run_log"
  while IFS= read -r scan_root; do
    {
      echo "scan_root=${scan_root}"
      PYTHONPATH=src python -m hashall.cli scan \
        "$scan_root" \
        --db "$DB_PATH" \
        --hash-mode "$SCAN_HASH_MODE" \
        --parallel \
        --low-priority
    } 2>&1 | tee -a "$scan_log" | tee -a "$run_log"
  done < "$scan_roots_file"
else
  echo "step=scan_roots status=skipped reason=no_existing_roots" | tee -a "$run_log"
fi

echo "step=payload_sync cmd=python -m hashall.cli payload sync" | tee -a "$run_log"
{
  PYTHONPATH=src python -m hashall.cli payload sync \
    --db "$DB_PATH" \
    --path-prefix-file "$prefix_file" \
    --upgrade-missing \
    --parallel \
    --low-priority
} 2>&1 | tee "$sync_log" | tee -a "$run_log"

echo "step=replan cmd=make rehome-normalize-plan" | tee -a "$run_log"
{
  make rehome-normalize-plan \
    "REHOME_CATALOG=${DB_PATH}" \
    "REHOME_POOL_DEVICE=${POOL_DEVICE}" \
    "REHOME_NORMALIZE_POOL_ROOT=${POOL_ROOT}" \
    "REHOME_NORMALIZE_STASH_ROOT=${STASH_ROOT}" \
    "REHOME_NORMALIZE_LIMIT=${LIMIT}" \
    "REHOME_NORMALIZE_FLAT_ONLY=${FLAT_ONLY}" \
    "REHOME_NORMALIZE_PRINT_SKIPPED=1" \
    "REHOME_NORMALIZE_REFRESH=0" \
    "REHOME_NORMALIZE_OUTPUT=${PLAN_OUTPUT}"
} 2>&1 | tee "$plan_log" | tee -a "$run_log"

echo "plan_output=${PLAN_OUTPUT}" | tee -a "$run_log"
echo "prefix_file=${prefix_file}" | tee -a "$run_log"
echo "scan_roots_file=${scan_roots_file}" | tee -a "$run_log"
echo "run_log=${run_log}" | tee -a "$run_log"
echo "scan_log=${scan_log}" | tee -a "$run_log"
echo "sync_log=${sync_log}" | tee -a "$run_log"
echo "plan_log=${plan_log}" | tee -a "$run_log"
