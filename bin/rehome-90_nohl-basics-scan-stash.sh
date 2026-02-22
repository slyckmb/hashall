#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
WORKERS="${WORKERS:-}"
SHOW_PATH="${SHOW_PATH:-1}"
PARALLEL="${PARALLEL:-1}"
LOW_PRIORITY="${LOW_PRIORITY:-1}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-scan-stash-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 90: Basics scan (/stash/media)"
echo "What this does: refresh DB filesystem truth for stash roots."
hr
echo "run_id=${stamp} step=basics-scan-stash db=${DB_PATH} parallel=${PARALLEL} workers=${WORKERS:-auto} low_priority=${LOW_PRIORITY} show_path=${SHOW_PATH}"

cmd=(python -m hashall.cli scan /stash/media --db "$DB_PATH" --fast)
if [[ "$PARALLEL" == "1" ]]; then
  cmd+=(--parallel)
fi
if [[ -n "$WORKERS" ]]; then
  cmd+=(--workers "$WORKERS")
fi
if [[ "$SHOW_PATH" == "1" ]]; then
  cmd+=(--show-path)
fi
if [[ "$LOW_PRIORITY" == "1" ]]; then
  cmd+=(--low-priority)
fi

echo "cmd=PYTHONPATH=src ${cmd[*]}"
PYTHONPATH=src "${cmd[@]}"

hr
echo "result=ok step=basics-scan-stash run_log=${run_log}"
hr
