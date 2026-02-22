#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-missing-audit-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 95: qB missingFiles audit"
echo "What this does: classify missing torrents and generate remediation plan."
hr
echo "run_id=${stamp} step=basics-qb-missing-audit output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} fast=${FAST} debug=${DEBUG}"

cmd=(bin/rehome-56_qb-missing-audit.sh --output-prefix "$OUTPUT_PREFIX" --limit "$LIMIT")
if [[ "$FAST" == "1" ]]; then
  cmd+=(--fast)
fi
if [[ "$DEBUG" == "1" ]]; then
  cmd+=(--debug)
fi

echo "cmd=${cmd[*]}"
"${cmd[@]}"

hr
echo "result=ok step=basics-qb-missing-audit run_log=${run_log}"
hr
