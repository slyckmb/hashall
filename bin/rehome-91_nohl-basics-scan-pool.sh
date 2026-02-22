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
SCAN_ROOTS_CSV="${SCAN_ROOTS_CSV:-/pool/data,/mnt/hotspare6tb}"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-scan-pool-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 91: Basics scan (pool + hotspare roots)"
echo "What this does: refresh DB filesystem truth for pool/hotspare roots."
hr
echo "run_id=${stamp} step=basics-scan-pool db=${DB_PATH} roots=${SCAN_ROOTS_CSV} parallel=${PARALLEL} workers=${WORKERS:-auto} low_priority=${LOW_PRIORITY} show_path=${SHOW_PATH}"

IFS=',' read -r -a scan_roots <<< "$SCAN_ROOTS_CSV"
scanned=0
skipped=0
for scan_root in "${scan_roots[@]}"; do
  # Trim whitespace around each CSV token.
  root="${scan_root#"${scan_root%%[![:space:]]*}"}"
  root="${root%"${root##*[![:space:]]}"}"
  if [[ -z "$root" ]]; then
    continue
  fi
  if [[ ! -d "$root" ]]; then
    echo "scan_skip root=${root} reason=missing_directory"
    skipped=$((skipped + 1))
    continue
  fi

  cmd=(python -m hashall.cli scan "$root" --db "$DB_PATH" --fast)
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
  scanned=$((scanned + 1))
done

echo "scan_summary scanned_roots=${scanned} skipped_roots=${skipped}"
if [[ "$scanned" -eq 0 ]]; then
  echo "No scan roots available under SCAN_ROOTS_CSV=${SCAN_ROOTS_CSV}" >&2
  exit 3
fi

hr
echo "result=ok step=basics-scan-pool run_log=${run_log}"
hr
