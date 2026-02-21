#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-55_nohl-fix-target-hash.sh [options]

Options:
  --payload-prefix HEX      Payload hash prefix to target (required)
  --manifest PATH           Plan manifest JSON (default: latest nohl-plan-manifest-*.json)
  --min-free-pct N          Pool free-space guard percent for dryrun/apply (default: 15)
  --execute 0|1             Execute dryrun command (default: 0 = print only)
  --apply 0|1               Execute apply command after dryrun (default: 0)
  --fast 0|1                Pass --fast to underlying scripts (default: 1)
  --debug 0|1               Pass --debug to underlying scripts (default: 0)
  --output-prefix NAME      Output prefix for generated helper files (default: nohl)
  -h, --help                Show help
USAGE
}

latest_manifest() {
  local prefix="$1"
  ls -1t "out/reports/rehome-normalize/${prefix}-plan-manifest-"*.json 2>/dev/null | head -n1
}

PAYLOAD_PREFIX=""
MANIFEST_JSON=""
MIN_FREE_PCT="15"
EXECUTE_MODE="0"
APPLY_MODE="0"
FAST_MODE="1"
DEBUG_MODE="0"
OUTPUT_PREFIX="nohl"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --payload-prefix) PAYLOAD_PREFIX="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_JSON="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --execute) EXECUTE_MODE="${2:-}"; shift 2 ;;
    --apply) APPLY_MODE="${2:-}"; shift 2 ;;
    --fast) FAST_MODE="${2:-1}"; shift ;;
    --debug) DEBUG_MODE="${2:-1}"; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$PAYLOAD_PREFIX" ]]; then
  echo "Missing required arg: --payload-prefix" >&2
  exit 2
fi
if ! [[ "$MIN_FREE_PCT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --min-free-pct value: $MIN_FREE_PCT" >&2
  exit 2
fi
if [[ "$EXECUTE_MODE" != "0" && "$EXECUTE_MODE" != "1" ]]; then
  echo "Invalid --execute value: $EXECUTE_MODE (expected 0 or 1)" >&2
  exit 2
fi
if [[ "$APPLY_MODE" != "0" && "$APPLY_MODE" != "1" ]]; then
  echo "Invalid --apply value: $APPLY_MODE (expected 0 or 1)" >&2
  exit 2
fi
if [[ "$FAST_MODE" != "0" && "$FAST_MODE" != "1" ]]; then
  echo "Invalid --fast value: $FAST_MODE (expected 0 or 1)" >&2
  exit 2
fi
if [[ "$DEBUG_MODE" != "0" && "$DEBUG_MODE" != "1" ]]; then
  echo "Invalid --debug value: $DEBUG_MODE (expected 0 or 1)" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found in PATH" >&2
  exit 3
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "$MANIFEST_JSON" ]]; then
  MANIFEST_JSON="$(latest_manifest "$OUTPUT_PREFIX")"
fi
if [[ -z "$MANIFEST_JSON" || ! -f "$MANIFEST_JSON" ]]; then
  echo "Missing plan manifest; pass --manifest or run rehome-40 first" >&2
  exit 3
fi

mapfile -t MATCHED_HASHES < <(
  jq -r --arg p "$PAYLOAD_PREFIX" \
    '.entries[] | select(.status=="ok" and (.payload_hash|startswith($p))) | .payload_hash' \
    "$MANIFEST_JSON"
)

if [[ "${#MATCHED_HASHES[@]}" -eq 0 ]]; then
  echo "No payload hash found for prefix: $PAYLOAD_PREFIX" >&2
  exit 4
fi
if [[ "${#MATCHED_HASHES[@]}" -gt 1 ]]; then
  echo "Multiple payload hashes match prefix: $PAYLOAD_PREFIX" >&2
  printf '%s\n' "${MATCHED_HASHES[@]}" >&2
  exit 2
fi

FULL_HASH="${MATCHED_HASHES[0]}"
PLAN_PATH="$(
  jq -r --arg h "$FULL_HASH" \
    '.entries[] | select(.status=="ok" and .payload_hash==$h) | .plan_path' \
    "$MANIFEST_JSON" | head -n1
)"

if [[ -z "$PLAN_PATH" || "$PLAN_PATH" == "null" ]]; then
  echo "Missing plan_path for payload hash: $FULL_HASH" >&2
  exit 4
fi
if [[ ! -f "$PLAN_PATH" ]]; then
  echo "plan_path does not exist: $PLAN_PATH" >&2
  exit 4
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-target-fix-${stamp}.log"
hash_file="${log_dir}/${OUTPUT_PREFIX}-target-hash-${stamp}.txt"
plan_file="${log_dir}/${OUTPUT_PREFIX}-target-plan-${stamp}.tsv"

printf '%s\n' "$FULL_HASH" > "$hash_file"
printf '%s\t%s\n' "$FULL_HASH" "$PLAN_PATH" > "$plan_file"

dryrun_cmd=(
  bin/rehome-50_nohl-dryrun-group-batch.sh
  --hashes-file "$hash_file"
  --manifest "$MANIFEST_JSON"
  --min-free-pct "$MIN_FREE_PCT"
)
apply_cmd=(
  bin/rehome-60_nohl-apply-group-batch.sh
  --plans-file "$plan_file"
  --min-free-pct "$MIN_FREE_PCT"
)

if [[ "$FAST_MODE" == "1" ]]; then
  dryrun_cmd+=(--fast)
  apply_cmd+=(--fast)
fi
if [[ "$DEBUG_MODE" == "1" ]]; then
  dryrun_cmd+=(--debug)
  apply_cmd+=(--debug)
fi

printf -v dryrun_cmd_str '%q ' "${dryrun_cmd[@]}"
printf -v apply_cmd_str '%q ' "${apply_cmd[@]}"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 55: Targeted nohl payload fix"
echo "What this does: resolve one payload hash, run dryrun, then optional apply."
hr
echo "payload_prefix=${PAYLOAD_PREFIX}"
echo "full_hash=${FULL_HASH}"
echo "manifest=${MANIFEST_JSON}"
echo "hash_file=${hash_file}"
echo "plan_file=${plan_file}"
echo "run_log=${run_log}"
echo "dryrun_cmd=${dryrun_cmd_str% }"
echo "apply_cmd=${apply_cmd_str% }"

if [[ "$EXECUTE_MODE" != "1" ]]; then
  echo "status=printed_only execute=0"
  exit 0
fi

hr
echo "Executing targeted dryrun"
hr
"${dryrun_cmd[@]}"

if [[ "$APPLY_MODE" == "1" ]]; then
  hr
  echo "Executing targeted apply"
  hr
  "${apply_cmd[@]}"
else
  echo "status=dryrun_complete apply=0"
fi

echo "status=done execute=${EXECUTE_MODE} apply=${APPLY_MODE}"
