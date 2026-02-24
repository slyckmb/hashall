#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-20_normalize-refresh-plan_with-logs.sh [options]

What it does:
  1) Refresh payload metadata from qB into catalog (scoped by pool root).
  2) Build normalize plan with summary + skipped reasons.

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-device ID          Pool device_id (default: 44)
  --pool-root PATH          Pool seeding root (default: /pool/data/seeds)
  --stash-root PATH         Stash seeding root hint (default: /stash/media/torrents/seeding)
  --limit N                 Normalize candidate limit (default: 0 = all)
  --all-mismatches          Include non-flat mismatches (default: flat-only on)
  --refresh-category NAME   Optional qB category filter for refresh
  --refresh-tag NAME        Optional qB tag filter for refresh
  --refresh-limit N         Optional qB refresh torrent limit (default: 0 = all)
  --output PATH             Plan output JSON path (default: auto timestamped)
  -h, --help                Show help
USAGE
}

DB_PATH="/home/michael/.hashall/catalog.db"
POOL_DEVICE="44"
POOL_ROOT="/pool/data/seeds"
STASH_ROOT="/stash/media/torrents/seeding"
LIMIT="0"
FLAT_ONLY="1"
REFRESH_CATEGORY=""
REFRESH_TAG=""
REFRESH_LIMIT="0"
PLAN_OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE="${2:-}"; shift 2 ;;
    --pool-root) POOL_ROOT="${2:-}"; shift 2 ;;
    --stash-root) STASH_ROOT="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --all-mismatches) FLAT_ONLY="0"; shift ;;
    --refresh-category) REFRESH_CATEGORY="${2:-}"; shift 2 ;;
    --refresh-tag) REFRESH_TAG="${2:-}"; shift 2 ;;
    --refresh-limit) REFRESH_LIMIT="${2:-}"; shift 2 ;;
    --output) PLAN_OUTPUT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTHONUNBUFFERED=1
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
run_log="${log_dir}/rehome-normalize-refresh-plan-run-${stamp}.log"
plan_log="${log_dir}/rehome-normalize-refresh-plan-${stamp}.log"

if [[ -z "$PLAN_OUTPUT" ]]; then
  PLAN_OUTPUT="${log_dir}/rehome-plan-normalize-refresh-${stamp}.json"
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
echo "run_id=${stamp} step=normalize-refresh-plan" | tee -a "$run_log"
echo "step=plan cmd=make rehome-normalize-plan" | tee -a "$run_log"

cmd=(
  make rehome-normalize-plan
  "REHOME_CATALOG=${DB_PATH}"
  "REHOME_POOL_DEVICE=${POOL_DEVICE}"
  "REHOME_NORMALIZE_POOL_ROOT=${POOL_ROOT}"
  "REHOME_NORMALIZE_STASH_ROOT=${STASH_ROOT}"
  "REHOME_NORMALIZE_LIMIT=${LIMIT}"
  "REHOME_NORMALIZE_FLAT_ONLY=${FLAT_ONLY}"
  "REHOME_NORMALIZE_PRINT_SKIPPED=1"
  "REHOME_NORMALIZE_REFRESH=1"
  "REHOME_NORMALIZE_REFRESH_LIMIT=${REFRESH_LIMIT}"
  "REHOME_NORMALIZE_OUTPUT=${PLAN_OUTPUT}"
)
if [[ -n "$REFRESH_CATEGORY" ]]; then
  cmd+=("REHOME_NORMALIZE_REFRESH_CATEGORY=${REFRESH_CATEGORY}")
fi
if [[ -n "$REFRESH_TAG" ]]; then
  cmd+=("REHOME_NORMALIZE_REFRESH_TAG=${REFRESH_TAG}")
fi

{
  "${cmd[@]}"
} 2>&1 | tee "$plan_log" | tee -a "$run_log"

echo "plan_output=${PLAN_OUTPUT}" | tee -a "$run_log"
echo "run_log=${run_log}" | tee -a "$run_log"
echo "plan_log=${plan_log}" | tee -a "$run_log"
