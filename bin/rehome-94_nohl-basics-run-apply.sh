#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MIN_FREE_PCT="${MIN_FREE_PCT:-15}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"
HEARTBEAT_S="${HEARTBEAT_S:-5}"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-run-apply-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 94: noHL pipeline apply"
echo "What this does: run the noHL pipeline including live apply."
hr
echo "run_id=${stamp} step=basics-run-apply min_free_pct=${MIN_FREE_PCT} fast=${FAST} debug=${DEBUG} heartbeat_s=${HEARTBEAT_S}"

cmd=(bin/codex-says-run-this-next.sh --min-free-pct "$MIN_FREE_PCT")
echo "cmd=REHOME_PROCESS_MODE=nohl-restart REHOME_NOHL_EXECUTE=1 REHOME_NOHL_APPLY=1 REHOME_NOHL_FAST=${FAST} REHOME_NOHL_DEBUG=${DEBUG} REHOME_PROGRESS_HEARTBEAT_SECONDS=${HEARTBEAT_S} ${cmd[*]}"
REHOME_PROCESS_MODE=nohl-restart \
REHOME_NOHL_EXECUTE=1 \
REHOME_NOHL_APPLY=1 \
REHOME_NOHL_FAST="$FAST" \
REHOME_NOHL_DEBUG="$DEBUG" \
REHOME_PROGRESS_HEARTBEAT_SECONDS="$HEARTBEAT_S" \
"${cmd[@]}"

hr
echo "result=ok step=basics-run-apply run_log=${run_log}"
hr
