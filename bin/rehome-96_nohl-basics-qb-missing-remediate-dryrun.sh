#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

latest_plan() {
  local prefix="$1"
  ls -1t "$HOME/.logs/hashall/reports/rehome-normalize/${prefix}-qb-missing-remediate-plan-"*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"
HEARTBEAT_S="${HEARTBEAT_S:-5}"
PLAN="${PLAN:-}"

if [[ -z "$PLAN" ]]; then
  PLAN="$(latest_plan "$OUTPUT_PREFIX")"
fi
if [[ -z "$PLAN" || ! -f "$PLAN" ]]; then
  echo "Missing remediation plan JSON; run bin/rehome-95_nohl-basics-qb-missing-audit.sh first." >&2
  exit 3
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-missing-remediate-dryrun-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 96: qB missingFiles remediate dryrun"
echo "What this does: preview targeted qB setLocation fixes without live changes."
hr
echo "run_id=${stamp} step=basics-qb-missing-remediate-dryrun plan=${PLAN} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} heartbeat_s=${HEARTBEAT_S} fast=${FAST} debug=${DEBUG}"

cmd=(
  bin/rehome-57_qb-missing-remediate.sh
  --plan "$PLAN"
  --mode dryrun
  --limit "$LIMIT"
  --heartbeat-s "$HEARTBEAT_S"
  --output-prefix "$OUTPUT_PREFIX"
)
if [[ "$FAST" == "1" ]]; then
  cmd+=(--fast)
fi
if [[ "$DEBUG" == "1" ]]; then
  cmd+=(--debug)
fi

echo "cmd=${cmd[*]}"
"${cmd[@]}"

hr
echo "result=ok step=basics-qb-missing-remediate-dryrun run_log=${run_log}"
hr
