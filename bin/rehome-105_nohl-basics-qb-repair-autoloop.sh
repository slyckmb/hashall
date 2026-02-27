#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-105_nohl-basics-qb-repair-autoloop.sh [options]

What this does:
  - Iteratively builds a conflict-free mapping (104 + 103)
  - Runs bounded Phase 102 apply batches
  - Refreshes baseline/mapping/audit after each batch
  - Stops safely on no-work or no-progress

Options:
  --baseline-json PATH    Starting baseline JSON (required)
  --mapping-json PATH     Starting mapping JSON (required)
  --audit-json PATH       Starting ownership-audit JSON (required)
  --batch-limit N         Phase 102 apply limit per round (default: 25)
  --phase102-batch-size N  Phase 102 batch wave size (default: 10)
  --phase102-selection-mode MODE  auto|pilot|throughput for Phase 102 (default: auto)
  --max-rounds N          Maximum rounds (default: 25)
  --candidate-top-n N     Candidate attempts per hash (default: 3)
  --mapping-top-n N       Phase 101 candidate-top-n during refresh (default: 10)
  --output-prefix NAME    Output prefix for refresh runs (default: nohl-loop)
  --sleep-s N             Sleep between rounds (default: 2)
  --apply-mode MODE       apply | dryrun-only (default: apply)
  --conflict-block-mode MODE  strict | ownership-only | custom (default: strict)
  --conflict-block-types CSV  Used with custom mode; CSV of conflict types to block
  --phase102-candidate-max-seconds N  Per-candidate budget for Phase 102 (default: 300)
  --phase102-item-max-seconds N       Per-hash budget for Phase 102 (default: 900)
  --candidate-failure-cache-json PATH  Persisted cache for failed hash/path attempts (default: per output-prefix path)
  --candidate-failure-cache-threshold N  Skip candidate after N cached failures (default: 1)
  --max-failed-attempts-per-hash N  Quarantine hash after N apply failures (default: 1)
  --lane-mode MODE         all | route-found | build-from-sibling (default: all)
  --lane-route-top-n N     Route candidates kept in lane planning (default: 3)
  -h, --help              Show help
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

BASELINE_JSON=""
MAPPING_JSON=""
AUDIT_JSON=""
BATCH_LIMIT="${BATCH_LIMIT:-25}"
PHASE102_BATCH_SIZE="${PHASE102_BATCH_SIZE:-10}"
PHASE102_SELECTION_MODE="${PHASE102_SELECTION_MODE:-auto}"
MAX_ROUNDS="${MAX_ROUNDS:-25}"
CANDIDATE_TOP_N="${CANDIDATE_TOP_N:-3}"
MAPPING_TOP_N="${MAPPING_TOP_N:-10}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl-loop}"
SLEEP_S="${SLEEP_S:-2}"
APPLY_MODE="${APPLY_MODE:-apply}"
CONFLICT_BLOCK_MODE="${CONFLICT_BLOCK_MODE:-strict}"
CONFLICT_BLOCK_TYPES="${CONFLICT_BLOCK_TYPES:-}"
PHASE102_CANDIDATE_MAX_SECONDS="${PHASE102_CANDIDATE_MAX_SECONDS:-300}"
PHASE102_ITEM_MAX_SECONDS="${PHASE102_ITEM_MAX_SECONDS:-900}"
CANDIDATE_FAILURE_CACHE_JSON="${CANDIDATE_FAILURE_CACHE_JSON:-}"
CANDIDATE_FAILURE_CACHE_THRESHOLD="${CANDIDATE_FAILURE_CACHE_THRESHOLD:-1}"
MAX_FAILED_ATTEMPTS_PER_HASH="${MAX_FAILED_ATTEMPTS_PER_HASH:-1}"
LANE_MODE="${LANE_MODE:-all}"
LANE_ROUTE_TOP_N="${LANE_ROUTE_TOP_N:-3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --audit-json) AUDIT_JSON="${2:-}"; shift 2 ;;
    --batch-limit) BATCH_LIMIT="${2:-}"; shift 2 ;;
    --phase102-batch-size) PHASE102_BATCH_SIZE="${2:-}"; shift 2 ;;
    --phase102-selection-mode) PHASE102_SELECTION_MODE="${2:-}"; shift 2 ;;
    --max-rounds) MAX_ROUNDS="${2:-}"; shift 2 ;;
    --candidate-top-n) CANDIDATE_TOP_N="${2:-}"; shift 2 ;;
    --mapping-top-n) MAPPING_TOP_N="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --sleep-s) SLEEP_S="${2:-}"; shift 2 ;;
    --apply-mode) APPLY_MODE="${2:-}"; shift 2 ;;
    --conflict-block-mode) CONFLICT_BLOCK_MODE="${2:-}"; shift 2 ;;
    --conflict-block-types) CONFLICT_BLOCK_TYPES="${2:-}"; shift 2 ;;
    --phase102-candidate-max-seconds) PHASE102_CANDIDATE_MAX_SECONDS="${2:-}"; shift 2 ;;
    --phase102-item-max-seconds) PHASE102_ITEM_MAX_SECONDS="${2:-}"; shift 2 ;;
    --candidate-failure-cache-json) CANDIDATE_FAILURE_CACHE_JSON="${2:-}"; shift 2 ;;
    --candidate-failure-cache-threshold) CANDIDATE_FAILURE_CACHE_THRESHOLD="${2:-}"; shift 2 ;;
    --max-failed-attempts-per-hash) MAX_FAILED_ATTEMPTS_PER_HASH="${2:-}"; shift 2 ;;
    --lane-mode) LANE_MODE="${2:-}"; shift 2 ;;
    --lane-route-top-n) LANE_ROUTE_TOP_N="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for n in "$BATCH_LIMIT" "$PHASE102_BATCH_SIZE" "$MAX_ROUNDS" "$CANDIDATE_TOP_N" "$MAPPING_TOP_N" "$SLEEP_S" "$PHASE102_CANDIDATE_MAX_SECONDS" "$PHASE102_ITEM_MAX_SECONDS" "$CANDIDATE_FAILURE_CACHE_THRESHOLD" "$MAX_FAILED_ATTEMPTS_PER_HASH" "$LANE_ROUTE_TOP_N"; do
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
done
if [[ "$BATCH_LIMIT" -lt 1 || "$PHASE102_BATCH_SIZE" -lt 1 || "$MAX_ROUNDS" -lt 1 || "$CANDIDATE_TOP_N" -lt 1 || "$MAPPING_TOP_N" -lt 1 ]]; then
  echo "batch/max/candidate/mapping limits must be >=1" >&2
  exit 2
fi
if [[ "$PHASE102_SELECTION_MODE" != "auto" && "$PHASE102_SELECTION_MODE" != "pilot" && "$PHASE102_SELECTION_MODE" != "throughput" ]]; then
  echo "Invalid --phase102-selection-mode: $PHASE102_SELECTION_MODE (expected auto|pilot|throughput)" >&2
  exit 2
fi
if [[ "$APPLY_MODE" != "apply" && "$APPLY_MODE" != "dryrun-only" ]]; then
  echo "Invalid --apply-mode: $APPLY_MODE (expected apply|dryrun-only)" >&2
  exit 2
fi
if [[ "$CONFLICT_BLOCK_MODE" != "strict" && "$CONFLICT_BLOCK_MODE" != "ownership-only" && "$CONFLICT_BLOCK_MODE" != "custom" ]]; then
  echo "Invalid --conflict-block-mode: $CONFLICT_BLOCK_MODE (expected strict|ownership-only|custom)" >&2
  exit 2
fi
if [[ "$LANE_MODE" != "all" && "$LANE_MODE" != "route-found" && "$LANE_MODE" != "build-from-sibling" ]]; then
  echo "Invalid --lane-mode: $LANE_MODE (expected all|route-found|build-from-sibling)" >&2
  exit 2
fi
if [[ "$MAX_FAILED_ATTEMPTS_PER_HASH" -lt 1 ]]; then
  echo "--max-failed-attempts-per-hash must be >=1" >&2
  exit 2
fi
if [[ "$LANE_ROUTE_TOP_N" -lt 1 ]]; then
  echo "--lane-route-top-n must be >=1" >&2
  exit 2
fi
if [[ "$PHASE102_CANDIDATE_MAX_SECONDS" -lt 30 ]]; then
  echo "--phase102-candidate-max-seconds must be >=30" >&2
  exit 2
fi
if [[ "$PHASE102_ITEM_MAX_SECONDS" -lt "$PHASE102_CANDIDATE_MAX_SECONDS" ]]; then
  echo "--phase102-item-max-seconds must be >= --phase102-candidate-max-seconds" >&2
  exit 2
fi
if [[ "$CANDIDATE_FAILURE_CACHE_THRESHOLD" -lt 1 ]]; then
  echo "--candidate-failure-cache-threshold must be >=1" >&2
  exit 2
fi
if [[ "$CONFLICT_BLOCK_MODE" == "custom" && -z "$CONFLICT_BLOCK_TYPES" ]]; then
  echo "--conflict-block-types is required when --conflict-block-mode=custom" >&2
  exit 2
fi

case "$CONFLICT_BLOCK_MODE" in
  strict)
    EFFECTIVE_BLOCK_CONFLICT_TYPES="all"
    ;;
  ownership-only)
    EFFECTIVE_BLOCK_CONFLICT_TYPES="shared_target_payload,target_owned_by_other_hash"
    ;;
  custom)
    EFFECTIVE_BLOCK_CONFLICT_TYPES="$CONFLICT_BLOCK_TYPES"
    ;;
esac

if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing/invalid --baseline-json" >&2
  exit 3
fi
if [[ -z "$MAPPING_JSON" || ! -f "$MAPPING_JSON" ]]; then
  echo "Missing/invalid --mapping-json" >&2
  exit 3
fi
if [[ -z "$AUDIT_JSON" || ! -f "$AUDIT_JSON" ]]; then
  echo "Missing/invalid --audit-json" >&2
  exit 3
fi

log_root="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_root"

lock_file="${log_root}/${OUTPUT_PREFIX}-autoloop.lock"
exec 9>"$lock_file"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    echo "Another autoloop run appears active for output_prefix=${OUTPUT_PREFIX}; lock=${lock_file}" >&2
    exit 6
  fi
fi

run_stamp="$(date +%Y%m%d-%H%M%S)"
run_log="${log_root}/${OUTPUT_PREFIX}-autoloop-${run_stamp}.log"
exec > >(tee "$run_log") 2>&1

extract_kv() {
  local key="$1"
  awk -v k="$key" '
    index($0, k"=")==1 {
      print substr($0, length(k) + 2)
    }
  ' | tail -n1 | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

extract_embedded_kv() {
  local key="$1"
  awk -v k="$key" '
    {
      pat = k"=[^[:space:]]+"
      if (match($0, pat)) {
        val = substr($0, RSTART + length(k) + 1, RLENGTH - length(k) - 1)
        print val
      }
    }
  ' | tail -n1 | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

run_capture() {
  local __out_var="$1"
  shift
  local out rc
  set +e
  out="$("$@" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$out"
  printf -v "$__out_var" '%s' "$out"
  return "$rc"
}

resolve_result_json() {
  local output="$1"
  local prefix="$2"
  local value=""
  value="$(printf '%s\n' "$output" | extract_kv result_json)"
  if [[ -z "$value" ]]; then
    value="$(printf '%s\n' "$output" | extract_embedded_kv result_json)"
  fi
  if [[ -z "$value" || ! -f "$value" ]]; then
    value="$(
      printf '%s\n' "$output" \
        | grep -oE '/[^[:space:]]*qb-repair-pilot-result-[0-9]{8}-[0-9]{6}\.json' \
        | tail -n1 || true
    )"
  fi
  if [[ -z "$value" || ! -f "$value" ]]; then
    value="$(ls -1t "${prefix}"*.json 2>/dev/null | head -n1 || true)"
  fi
  printf '%s' "$value"
}

echo "============================================================"
echo "Phase 105: qB repair autoloop"
echo "run_log=${run_log}"
echo "start_baseline=${BASELINE_JSON}"
echo "start_mapping=${MAPPING_JSON}"
echo "start_audit=${AUDIT_JSON}"
echo "batch_limit=${BATCH_LIMIT} phase102_batch_size=${PHASE102_BATCH_SIZE} phase102_selection_mode=${PHASE102_SELECTION_MODE} max_rounds=${MAX_ROUNDS} candidate_top_n=${CANDIDATE_TOP_N} mapping_top_n=${MAPPING_TOP_N}"
echo "apply_mode=${APPLY_MODE}"
echo "conflict_block_mode=${CONFLICT_BLOCK_MODE} conflict_block_types=${EFFECTIVE_BLOCK_CONFLICT_TYPES}"
echo "phase102_candidate_max_seconds=${PHASE102_CANDIDATE_MAX_SECONDS} phase102_item_max_seconds=${PHASE102_ITEM_MAX_SECONDS} candidate_failure_cache_threshold=${CANDIDATE_FAILURE_CACHE_THRESHOLD}"
echo "max_failed_attempts_per_hash=${MAX_FAILED_ATTEMPTS_PER_HASH}"
echo "lane_mode=${LANE_MODE} lane_route_top_n=${LANE_ROUTE_TOP_N}"
echo "============================================================"

blocked_hashes_file="${log_root}/${OUTPUT_PREFIX}-blocked-hashes-${run_stamp}.txt"
failed_counts_json="${log_root}/${OUTPUT_PREFIX}-failed-counts-${run_stamp}.json"
candidate_failure_cache_json="$CANDIDATE_FAILURE_CACHE_JSON"
if [[ -z "$candidate_failure_cache_json" ]]; then
  candidate_failure_cache_json="${log_root}/${OUTPUT_PREFIX}-candidate-failure-cache.json"
fi
: >"$blocked_hashes_file"
printf '{}\n' >"$failed_counts_json"
if [[ ! -f "$candidate_failure_cache_json" ]]; then
  printf '{}\n' >"$candidate_failure_cache_json"
fi

round=1
while [[ "$round" -le "$MAX_ROUNDS" ]]; do
  echo
  echo "----- round ${round}/${MAX_ROUNDS} -----"

  filter_pass=1
  current_map="$MAPPING_JSON"
  current_audit="$AUDIT_JSON"

  while true; do
    map_for_clean="$current_map"
    if [[ -s "$blocked_hashes_file" ]]; then
      map_for_clean="${log_root}/${OUTPUT_PREFIX}-blocked-filtered-r${round}-p${filter_pass}-$(date +%Y%m%d-%H%M%S).json"
      python3 - "$current_map" "$blocked_hashes_file" "$map_for_clean" <<'PY'
import json
import sys
from pathlib import Path

mapping_path = Path(sys.argv[1])
blocked_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])

blocked = {
    line.strip().lower()
    for line in blocked_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
}
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
entries = list(mapping.get("entries", []))
filtered = [
    row for row in entries
    if str(row.get("hash", "")).strip().lower() not in blocked
]
mapping["entries"] = filtered
mapping["_blocked_hash_filter"] = {
    "blocked_hashes": len(blocked),
    "entries_before": len(entries),
    "entries_after": len(filtered),
}
out_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
print(
    f"blocked_hash_filter blocked={len(blocked)} "
    f"entries_before={len(entries)} entries_after={len(filtered)} output={out_path}"
)
PY
    fi

    clean_map="${log_root}/${OUTPUT_PREFIX}-clean-map-r${round}-p${filter_pass}-$(date +%Y%m%d-%H%M%S).json"
    echo "[r${round} p${filter_pass}] build clean map"
    out=""
    run_capture out \
      bin/rehome-104_nohl-basics-qb-build-clean-mapping.sh \
      --mapping-json "$map_for_clean" \
      --audit-json "$current_audit" \
      --baseline-json "$BASELINE_JSON" \
      --block-conflict-types "$EFFECTIVE_BLOCK_CONFLICT_TYPES" \
      --clean-map "$clean_map"

    built_map="$(printf '%s\n' "$out" | extract_kv clean_map)"
    if [[ -z "$built_map" && -f "$clean_map" ]]; then
      built_map="$clean_map"
    fi
    if [[ -z "$built_map" || ! -f "$built_map" ]]; then
      echo "Failed to produce clean map in round=${round} pass=${filter_pass}" >&2
      exit 4
    fi

    echo "[r${round} p${filter_pass}] ownership audit clean map"
    audit_out=""
    run_capture audit_out \
      bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh \
      --mapping-json "$built_map" \
      --baseline-json "$BASELINE_JSON" \
      --candidate-top-n "$CANDIDATE_TOP_N" \
      --output-prefix "${OUTPUT_PREFIX}-r${round}-p${filter_pass}" || true

    audit_json="$(printf '%s\n' "$audit_out" | extract_kv json_output)"
    if [[ -z "$audit_json" || ! -f "$audit_json" ]]; then
      echo "Failed to parse audit json in round=${round} pass=${filter_pass}" >&2
      exit 4
    fi
    conflict_count="$(jq -r '.summary.conflict_count // 0' "$audit_json")"
    blocked_conflict_count="$(
      python3 - "$audit_json" "$EFFECTIVE_BLOCK_CONFLICT_TYPES" <<'PY'
import json
import sys
from pathlib import Path

audit = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raw_types = str(sys.argv[2] or "").strip()
if not raw_types or raw_types.lower() == "all":
    print(int(audit.get("summary", {}).get("conflict_count", 0) or 0))
    raise SystemExit(0)

blocked_types = {
    part.strip()
    for part in raw_types.split(",")
    if part.strip()
}
count = 0
for row in audit.get("conflicts", []):
    row_types = {
        str(item).strip()
        for item in (row.get("conflicts") or [])
        if str(item).strip()
    }
    if row_types & blocked_types:
        count += 1
print(count)
PY
    )"
    blocked_conflict_count="${blocked_conflict_count:-0}"
    echo "[r${round} p${filter_pass}] conflict_count=${conflict_count} blocked_conflict_count=${blocked_conflict_count}"

    current_map="$built_map"
    current_audit="$audit_json"
    if [[ "$blocked_conflict_count" -eq 0 ]]; then
      break
    fi
    filter_pass=$((filter_pass + 1))
    if [[ "$filter_pass" -gt 8 ]]; then
      echo "Too many filter passes; stopping for manual review." >&2
      exit 5
    fi
  done

  phase102_map="$current_map"
  phase102_audit="$current_audit"
  if [[ "$LANE_MODE" != "all" ]]; then
    lane_hash_out=""
    run_capture lane_hash_out \
      bin/rehome-106_nohl-basics-qb-hash-root-report.sh \
      --mapping-json "$current_map" \
      --baseline-json "$BASELINE_JSON" \
      --candidate-top-n "$MAPPING_TOP_N" \
      --output-prefix "${OUTPUT_PREFIX}-r${round}-lane106"
    lane_hash_json="$(printf '%s\n' "$lane_hash_out" | extract_kv json_output)"
    if [[ -z "$lane_hash_json" || ! -f "$lane_hash_json" ]]; then
      echo "Failed to parse lane hash/root json in round=${round}" >&2
      exit 4
    fi

    lane_plan_out=""
    run_capture lane_plan_out \
      bin/rehome-107_nohl-basics-qb-repair-lane-plan.sh \
      --hash-root-json "$lane_hash_json" \
      --route-top-n "$LANE_ROUTE_TOP_N" \
      --output-prefix "${OUTPUT_PREFIX}-r${round}-lane107"
    lane_plan_json="$(printf '%s\n' "$lane_plan_out" | extract_kv json_output)"
    if [[ -z "$lane_plan_json" || ! -f "$lane_plan_json" ]]; then
      echo "Failed to parse lane plan json in round=${round}" >&2
      exit 4
    fi

    lane_target=""
    case "$LANE_MODE" in
      route-found) lane_target="route_found" ;;
      build-from-sibling) lane_target="build_from_sibling" ;;
      *) lane_target="" ;;
    esac
    lane_map="${log_root}/${OUTPUT_PREFIX}-lane-map-r${round}-$(date +%Y%m%d-%H%M%S).json"
    lane_filter_out="$(
      python3 - "$current_map" "$lane_plan_json" "$lane_target" "$lane_map" <<'PY'
import json
import sys
from pathlib import Path

mapping_path = Path(sys.argv[1])
lane_path = Path(sys.argv[2])
lane_target = str(sys.argv[3]).strip()
out_path = Path(sys.argv[4])

mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
lane_plan = json.loads(lane_path.read_text(encoding="utf-8"))
allowed = {
    str(row.get("hash", "")).strip().lower()
    for row in lane_plan.get("entries", [])
    if str(row.get("lane", "")).strip().lower() == lane_target
}
entries = list(mapping.get("entries", []))
filtered = [
    row for row in entries
    if str(row.get("hash", "")).strip().lower() in allowed
]
mapping["entries"] = filtered
mapping["_lane_filter"] = {
    "lane_target": lane_target,
    "entries_before": len(entries),
    "entries_after": len(filtered),
}
out_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
print(f"lane_target={lane_target}")
print(f"entries_before={len(entries)}")
print(f"entries_after={len(filtered)}")
print(f"lane_map={out_path}")
PY
    )"
    lane_entries_after="$(printf '%s\n' "$lane_filter_out" | extract_kv entries_after)"
    lane_entries_after="${lane_entries_after:-0}"
    echo "[r${round}] lane_filter mode=${LANE_MODE} entries_after=${lane_entries_after}"
    if [[ ! -f "$lane_map" ]]; then
      echo "Failed to build lane-filtered mapping in round=${round}" >&2
      exit 4
    fi

    lane_audit_out=""
    run_capture lane_audit_out \
      bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh \
      --mapping-json "$lane_map" \
      --baseline-json "$BASELINE_JSON" \
      --candidate-top-n "$CANDIDATE_TOP_N" \
      --output-prefix "${OUTPUT_PREFIX}-r${round}-lane-audit" || true
    lane_audit_json="$(printf '%s\n' "$lane_audit_out" | extract_kv json_output)"
    if [[ -z "$lane_audit_json" || ! -f "$lane_audit_json" ]]; then
      echo "Failed to parse lane audit json in round=${round}" >&2
      exit 4
    fi
    phase102_map="$lane_map"
    phase102_audit="$lane_audit_json"
  fi

  echo "[r${round}] phase 102 dryrun check"
  dryrun_out=""
  run_capture dryrun_out \
    bin/rehome-102_nohl-basics-qb-repair-pilot.sh \
    --mode dryrun \
    --limit 10 \
    --selection-mode "$PHASE102_SELECTION_MODE" \
    --batch-size "$PHASE102_BATCH_SIZE" \
    --candidate-top-n "$CANDIDATE_TOP_N" \
    --candidate-fallback \
    --candidate-max-seconds "$PHASE102_CANDIDATE_MAX_SECONDS" \
    --item-max-seconds "$PHASE102_ITEM_MAX_SECONDS" \
    --candidate-failure-cache-json "$candidate_failure_cache_json" \
    --candidate-failure-cache-threshold "$CANDIDATE_FAILURE_CACHE_THRESHOLD" \
    --mapping-json "$phase102_map" \
    --baseline-json "$BASELINE_JSON" \
    --output-prefix "${OUTPUT_PREFIX}-r${round}-dryrun"
  dryrun_result_json="$(
    resolve_result_json \
      "$dryrun_out" \
      "${log_root}/${OUTPUT_PREFIX}-r${round}-dryrun-qb-repair-pilot-result-"
  )"
  if [[ -z "$dryrun_result_json" || ! -f "$dryrun_result_json" ]]; then
    echo "Failed to parse dryrun result json in round=${round}" >&2
    exit 4
  fi
  dry_selected="$(jq -r '.summary.selected // 0' "$dryrun_result_json")"
  echo "[r${round}] dryrun selected=${dry_selected}"
  if [[ "$dry_selected" -eq 0 ]]; then
    echo "No candidates selected in dryrun. Autoloop complete."
    break
  fi
  if [[ "$APPLY_MODE" == "dryrun-only" ]]; then
    echo "apply_mode=dryrun-only; stopping after successful dryrun check."
    break
  fi

  echo "[r${round}] phase 102 apply"
  apply_cmd=(
    bin/rehome-102_nohl-basics-qb-repair-pilot.sh
    --mode apply
    --limit "$BATCH_LIMIT"
    --selection-mode "$PHASE102_SELECTION_MODE"
    --batch-size "$PHASE102_BATCH_SIZE"
    --candidate-top-n "$CANDIDATE_TOP_N"
    --candidate-fallback
    --candidate-max-seconds "$PHASE102_CANDIDATE_MAX_SECONDS"
    --item-max-seconds "$PHASE102_ITEM_MAX_SECONDS"
    --candidate-failure-cache-json "$candidate_failure_cache_json"
    --candidate-failure-cache-threshold "$CANDIDATE_FAILURE_CACHE_THRESHOLD"
    --mapping-json "$phase102_map"
    --baseline-json "$BASELINE_JSON"
    --ownership-audit-json "$phase102_audit"
    --output-prefix "${OUTPUT_PREFIX}-r${round}-apply"
  )
  if [[ "$EFFECTIVE_BLOCK_CONFLICT_TYPES" != "all" ]]; then
    apply_cmd+=(--allow-ownership-conflicts)
  fi
  apply_out=""
  run_capture apply_out \
    "${apply_cmd[@]}" || true

  apply_result_json="$(
    resolve_result_json \
      "$apply_out" \
      "${log_root}/${OUTPUT_PREFIX}-r${round}-apply-qb-repair-pilot-result-"
  )"
  if [[ -z "$apply_result_json" || ! -f "$apply_result_json" ]]; then
    echo "Failed to parse apply result json in round=${round}" >&2
    exit 4
  fi
  selected="$(jq -r '.summary.selected // 0' "$apply_result_json")"
  ok="$(jq -r '.summary.ok // 0' "$apply_result_json")"
  errors="$(jq -r '.summary.errors // 0' "$apply_result_json")"
  fallback_used="$(jq -r '.summary.fallback_used // 0' "$apply_result_json")"
  echo "[r${round}] apply selected=${selected} ok=${ok} errors=${errors} fallback_used=${fallback_used} result_json=${apply_result_json}"

  block_parse_out="$(
    python3 - "$apply_result_json" "$blocked_hashes_file" "$failed_counts_json" "$MAX_FAILED_ATTEMPTS_PER_HASH" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
blocked_path = Path(sys.argv[2])
counts_path = Path(sys.argv[3])
threshold = max(1, int(sys.argv[4]))

result = json.loads(result_path.read_text(encoding="utf-8"))
blocked = set()
if blocked_path.exists():
    blocked = {
        line.strip().lower()
        for line in blocked_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
if counts_path.exists():
    try:
        counts = json.loads(counts_path.read_text(encoding="utf-8"))
    except Exception:
        counts = {}
else:
    counts = {}

newly_blocked = set()
error_hashes = set()
for row in result.get("results", []):
    if str(row.get("status", "")).lower() != "error":
        continue
    h = str(row.get("hash", "")).lower().strip()
    if not h:
        continue
    error_hashes.add(h)
    counts[h] = int(counts.get(h, 0) or 0) + 1
    if int(counts[h]) >= threshold and h not in blocked:
        blocked.add(h)
        newly_blocked.add(h)

blocked_path.write_text(
    "\n".join(sorted(blocked)) + ("\n" if blocked else ""),
    encoding="utf-8",
)
counts_path.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"error_hashes={len(error_hashes)}")
print(f"newly_blocked={len(newly_blocked)}")
print(f"blocked_total={len(blocked)}")
PY
  )"
  error_hashes_count="$(printf '%s\n' "$block_parse_out" | extract_kv error_hashes)"
  newly_blocked_count="$(printf '%s\n' "$block_parse_out" | extract_kv newly_blocked)"
  blocked_total_count="$(printf '%s\n' "$block_parse_out" | extract_kv blocked_total)"
  error_hashes_count="${error_hashes_count:-0}"
  newly_blocked_count="${newly_blocked_count:-0}"
  blocked_total_count="${blocked_total_count:-0}"
  echo "[r${round}] failure_quarantine errors_seen=${error_hashes_count} newly_blocked=${newly_blocked_count} blocked_total=${blocked_total_count}"

  if [[ "$selected" -eq 0 ]]; then
    echo "No items selected for apply. Autoloop complete."
    break
  fi
  refresh_reason="none"
  if [[ "$ok" -gt 0 ]]; then
    refresh_reason="successful_repairs"
  elif [[ "$newly_blocked_count" -gt 0 ]]; then
    refresh_reason="quarantined_failed_hashes"
  fi
  if [[ "$refresh_reason" == "none" ]]; then
    echo "No successful repairs and no newly quarantined hashes. Stopping to avoid churn."
    break
  fi
  if [[ "$ok" -eq 0 ]]; then
    echo "[r${round}] no_success_but_progress reason=${refresh_reason}; continuing after refresh."
  fi

  echo "[r${round}] refresh baseline + mapping + audit reason=${refresh_reason}"
  base_out=""
  run_capture base_out \
    bin/rehome-100_nohl-basics-qb-repair-baseline.sh \
    --output-prefix "${OUTPUT_PREFIX}-r${round}-base"
  next_base="$(printf '%s\n' "$base_out" | extract_kv json_output)"
  if [[ -z "$next_base" || ! -f "$next_base" ]]; then
    echo "Failed to parse refreshed baseline json in round=${round}" >&2
    exit 4
  fi

  map_out=""
  run_capture map_out \
    bin/rehome-101_nohl-basics-qb-candidate-mapping.sh \
    --baseline-json "$next_base" \
    --tracker-aware \
    --candidate-top-n "$MAPPING_TOP_N" \
    --output-prefix "${OUTPUT_PREFIX}-r${round}-map"
  next_map="$(printf '%s\n' "$map_out" | extract_kv json_output)"
  if [[ -z "$next_map" || ! -f "$next_map" ]]; then
    echo "Failed to parse refreshed mapping json in round=${round}" >&2
    exit 4
  fi

  audit_out=""
  run_capture audit_out \
    bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh \
    --mapping-json "$next_map" \
    --baseline-json "$next_base" \
    --candidate-top-n "$CANDIDATE_TOP_N" \
    --output-prefix "${OUTPUT_PREFIX}-r${round}-audit" || true
  next_audit="$(printf '%s\n' "$audit_out" | extract_kv json_output)"
  if [[ -z "$next_audit" || ! -f "$next_audit" ]]; then
    echo "Failed to parse refreshed audit json in round=${round}" >&2
    exit 4
  fi

  BASELINE_JSON="$next_base"
  MAPPING_JSON="$next_map"
  AUDIT_JSON="$next_audit"

  round=$((round + 1))
  if [[ "$SLEEP_S" -gt 0 ]]; then
    sleep "$SLEEP_S"
  fi
done

echo
echo "============================================================"
echo "Phase 105 complete"
echo "final_baseline=${BASELINE_JSON}"
echo "final_mapping=${MAPPING_JSON}"
echo "final_audit=${AUDIT_JSON}"
echo "candidate_failure_cache_json=${candidate_failure_cache_json}"
echo "run_log=${run_log}"
echo "============================================================"
