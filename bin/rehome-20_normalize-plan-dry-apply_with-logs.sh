#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-20_normalize-plan-dry-apply_with-logs.sh [options]

What it does:
  1) Build normalize plan (misplaced pool payload roots).
  2) Run dry-run apply with duplicate-source cleanup preview enabled.
  3) Optionally run live apply.

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-device ID          Pool device_id (default: 44)
  --limit N                 Candidate limit for normalize planning (default: 20)
  --pool-root PATH          Pool seeding root (default: /pool/data/seeds)
  --stash-root PATH         Stash seeding root (default: /stash/media/torrents/seeding)
  --all-mismatches          Include non-flat mismatches (default: flat-only on)
  --apply                   Run live apply after successful dry-run
  --debug                   Enable qB debug logs during apply (HASHALL_REHOME_QB_DEBUG=1)
  --output PATH             Plan JSON output path (default: auto timestamped)
  -h, --help                Show help

Examples:
  bin/rehome-20_normalize-plan-dry-apply_with-logs.sh
  bin/rehome-20_normalize-plan-dry-apply_with-logs.sh --limit 5 --apply --debug
USAGE
}

DB_PATH="/home/michael/.hashall/catalog.db"
POOL_DEVICE="44"
LIMIT="20"
POOL_ROOT="/pool/data/seeds"
STASH_ROOT="/stash/media/torrents/seeding"
FLAT_ONLY="1"
DO_APPLY="0"
DEBUG_MODE="0"
PLAN_OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --pool-root) POOL_ROOT="${2:-}"; shift 2 ;;
    --stash-root) STASH_ROOT="${2:-}"; shift 2 ;;
    --all-mismatches) FLAT_ONLY="0"; shift ;;
    --apply) DO_APPLY="1"; shift ;;
    --debug) DEBUG_MODE="1"; shift ;;
    --output) PLAN_OUTPUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ "$DEBUG_MODE" == "1" ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi
export PYTHONUNBUFFERED=1

stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
run_log="${log_dir}/rehome-normalize-run-${stamp}.log"
plan_log="${log_dir}/rehome-normalize-plan-${stamp}.log"
dry_log="${log_dir}/rehome-normalize-dry-${stamp}.log"
apply_log="${log_dir}/rehome-normalize-apply-${stamp}.log"

if [[ -z "$PLAN_OUTPUT" ]]; then
  PLAN_OUTPUT="${log_dir}/rehome-plan-normalize-${stamp}.json"
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
echo "run_id=${stamp} debug_mode=${DEBUG_MODE} do_apply=${DO_APPLY}" | tee -a "$run_log"

echo "step=plan cmd=make rehome-normalize-plan" | tee -a "$run_log"
{
  make rehome-normalize-plan \
    REHOME_CATALOG="$DB_PATH" \
    REHOME_POOL_DEVICE="$POOL_DEVICE" \
    REHOME_NORMALIZE_LIMIT="$LIMIT" \
    REHOME_NORMALIZE_POOL_ROOT="$POOL_ROOT" \
    REHOME_NORMALIZE_STASH_ROOT="$STASH_ROOT" \
    REHOME_NORMALIZE_FLAT_ONLY="$FLAT_ONLY" \
    REHOME_NORMALIZE_OUTPUT="$PLAN_OUTPUT"
} 2>&1 | tee "$plan_log" | tee -a "$run_log"

echo "step=dryrun cmd=make rehome-apply-dry" | tee -a "$run_log"
{
  make rehome-apply-dry \
    REHOME_CATALOG="$DB_PATH" \
    REHOME_PLAN="$PLAN_OUTPUT" \
    REHOME_SPOT_CHECK=0 \
    REHOME_CLEANUP_DUPLICATE_PAYLOAD=1
} 2>&1 | tee "$dry_log" | tee -a "$run_log"

if [[ "$DO_APPLY" == "1" ]]; then
  echo "step=apply cmd=make rehome-apply" | tee -a "$run_log"
  {
    make rehome-apply \
      REHOME_CATALOG="$DB_PATH" \
      REHOME_PLAN="$PLAN_OUTPUT" \
      REHOME_SPOT_CHECK=0 \
      REHOME_CLEANUP_DUPLICATE_PAYLOAD=1
  } 2>&1 | tee "$apply_log" | tee -a "$run_log"
else
  echo "step=apply skipped=true reason=flag_not_set" | tee -a "$run_log"
fi

echo "plan_output=${PLAN_OUTPUT}" | tee -a "$run_log"
echo "run_log=${run_log}" | tee -a "$run_log"
echo "plan_log=${plan_log}" | tee -a "$run_log"
echo "dry_log=${dry_log}" | tee -a "$run_log"
if [[ "$DO_APPLY" == "1" ]]; then
  echo "apply_log=${apply_log}" | tee -a "$run_log"
fi

