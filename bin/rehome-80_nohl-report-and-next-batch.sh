#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-80_nohl-report-and-next-batch.sh [options]

Options:
  --output-prefix NAME      Artifact prefix (default: nohl)
  --show-commands 0|1       Print next command sequence (default: 1)
  --fast                    Fast mode annotation in report
  --debug                   Debug mode annotation in report
  -h, --help                Show help
USAGE
}

OUTPUT_PREFIX="nohl"
SHOW_COMMANDS="1"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --show-commands) SHOW_COMMANDS="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
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

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-report-next-batch-${stamp}.log"

latest_discover="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-discover-"*.json 2>/dev/null | head -n1 || true)"
latest_manifest="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-plan-manifest-"*.json 2>/dev/null | head -n1 || true)"
latest_dryrun_ready="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-ready-"*.txt 2>/dev/null | head -n1 || true)"
latest_apply_fail="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-failed-"*.txt 2>/dev/null | head -n1 || true)"
latest_apply_deferred="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-deferred-"*.txt 2>/dev/null | head -n1 || true)"
latest_followup="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-followup-"*.json 2>/dev/null | head -n1 || true)"
latest_pending="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-payload-hashes-followup-pending-"*.txt 2>/dev/null | head -n1 || true)"
latest_failed="$(ls -1t "${log_dir}/${OUTPUT_PREFIX}-payload-hashes-followup-failed-"*.txt 2>/dev/null | head -n1 || true)"

count_lines() {
  local path="$1"
  if [[ -n "$path" && -f "$path" ]]; then
    wc -l < "$path" | tr -d ' '
  else
    echo "0"
  fi
}

{
  hr
  echo "Phase 80: Final report and next commands"
  echo "What this does: summarize latest run results and print the next batch commands."
  hr
  echo "run_id=${stamp} step=nohl-report-and-next-batch"
  echo "mode fast=${FAST_MODE} debug=${DEBUG_MODE}"
  echo "latest_discover=${latest_discover:-none}"
  echo "latest_manifest=${latest_manifest:-none}"
  echo "latest_dryrun_ready=${latest_dryrun_ready:-none}"
  echo "latest_apply_fail=${latest_apply_fail:-none}"
  echo "latest_apply_deferred=${latest_apply_deferred:-none}"
  echo "latest_followup=${latest_followup:-none}"
  echo "latest_pending=${latest_pending:-none}"
  echo "latest_failed=${latest_failed:-none}"

  if [[ -n "$latest_discover" && -f "$latest_discover" ]]; then
    jq -r '.summary' "$latest_discover"
  fi
  if [[ -n "$latest_manifest" && -f "$latest_manifest" ]]; then
    jq -r '.summary' "$latest_manifest"
  fi
  if [[ -n "$latest_followup" && -f "$latest_followup" ]]; then
    jq -r '.summary' "$latest_followup"
  fi

  echo "counts dryrun_ready=$(count_lines "$latest_dryrun_ready") apply_failed=$(count_lines "$latest_apply_fail") apply_deferred=$(count_lines "$latest_apply_deferred") followup_pending=$(count_lines "$latest_pending") followup_failed=$(count_lines "$latest_failed")"

  if [[ "$SHOW_COMMANDS" == "1" ]]; then
    fast_arg=""
    debug_arg=""
    [[ "$FAST_MODE" == "1" ]] && fast_arg=" --fast"
    [[ "$DEBUG_MODE" == "1" ]] && debug_arg=" --debug"
    echo "next_commands_begin"
    echo "bin/rehome-30_nohl-discover-and-rank.sh --min-free-pct 20 --limit 0${fast_arg}${debug_arg}"
    echo "bin/rehome-40_nohl-build-group-plan.sh --resume 1${fast_arg}${debug_arg}"
    echo "bin/rehome-50_nohl-dryrun-group-batch.sh --min-free-pct 20${fast_arg}${debug_arg}"
    echo "bin/rehome-60_nohl-apply-group-batch.sh --min-free-pct 20${fast_arg}${debug_arg}"
    echo "bin/rehome-70_nohl-followup-and-reconcile.sh --cleanup 1${fast_arg}${debug_arg}"
    echo "bin/rehome-80_nohl-report-and-next-batch.sh${fast_arg}${debug_arg}"
    echo "next_commands_end"
  fi
  hr
  echo "Phase 80 complete: report generated and next commands listed."
  hr
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
