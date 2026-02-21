#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
WORKERS="${WORKERS:-}"
LOW_PRIORITY="${LOW_PRIORITY:-1}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-payload-sync-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 92: Basics payload sync"
echo "What this does: refresh torrent->payload mappings and upgrade missing hashes."
hr
echo "run_id=${stamp} step=basics-payload-sync db=${DB_PATH} qbit_url=${QBIT_URL} qbit_user=${QBIT_USER} workers=${WORKERS:-auto} low_priority=${LOW_PRIORITY}"

cmd=(
  python -m hashall.cli payload sync
  --db "$DB_PATH"
  --qbit-url "$QBIT_URL"
  --qbit-user "$QBIT_USER"
  --qbit-pass "$QBIT_PASS"
  --path-prefix /stash/media
  --path-prefix /data/media
  --path-prefix /pool/data
  --upgrade-missing
  --parallel
  --hash-progress full
)
if [[ -n "$WORKERS" ]]; then
  cmd+=(--workers "$WORKERS")
fi
if [[ "$LOW_PRIORITY" == "1" ]]; then
  cmd+=(--low-priority)
fi

echo "cmd=PYTHONPATH=src ${cmd[*]}"
PYTHONPATH=src "${cmd[@]}"

hr
echo "result=ok step=basics-payload-sync run_log=${run_log}"
hr
