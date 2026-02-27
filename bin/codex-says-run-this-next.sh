#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

chatrap verify >/dev/null 2>&1 || true

# Run profile: edit here if you want different defaults.
OUT_PREFIX="${OUT_PREFIX:-nohl}"
LOOP_PREFIX="${LOOP_PREFIX:-nohl-autoloop-v2}"
TRACKER_REGISTRY="${TRACKER_REGISTRY:-/home/michael/dev/tools/traktor/config/tracker-registry.yml}"

BATCH_LIMIT="${BATCH_LIMIT:-20}"
PHASE102_BATCH_SIZE="${PHASE102_BATCH_SIZE:-5}"
PHASE102_SELECTION_MODE="${PHASE102_SELECTION_MODE:-throughput}"
MAX_ROUNDS="${MAX_ROUNDS:-25}"
CANDIDATE_TOP_N="${CANDIDATE_TOP_N:-2}"
MAPPING_TOP_N="${MAPPING_TOP_N:-10}"
SLEEP_S="${SLEEP_S:-2}"
APPLY_MODE="${APPLY_MODE:-apply}"
CONFLICT_BLOCK_MODE="${CONFLICT_BLOCK_MODE:-ownership-only}"
CONFLICT_BLOCK_TYPES="${CONFLICT_BLOCK_TYPES:-}"
PHASE102_CANDIDATE_MAX_SECONDS="${PHASE102_CANDIDATE_MAX_SECONDS:-180}"
PHASE102_ITEM_MAX_SECONDS="${PHASE102_ITEM_MAX_SECONDS:-540}"
CANDIDATE_FAILURE_CACHE_JSON="${CANDIDATE_FAILURE_CACHE_JSON:-}"
CANDIDATE_FAILURE_CACHE_THRESHOLD="${CANDIDATE_FAILURE_CACHE_THRESHOLD:-1}"
MAX_FAILED_ATTEMPTS_PER_HASH="${MAX_FAILED_ATTEMPTS_PER_HASH:-1}"
LANE_MODE="${LANE_MODE:-route-found}"
LANE_ROUTE_TOP_N="${LANE_ROUTE_TOP_N:-3}"

bin/rehome-100_nohl-basics-qb-repair-baseline.sh --output-prefix "$OUT_PREFIX"
BASELINE_JSON="$(ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/${OUT_PREFIX}-qb-repair-baseline-*.json | head -n1)"

map_cmd=(
  bin/rehome-101_nohl-basics-qb-candidate-mapping.sh
  --baseline-json "$BASELINE_JSON"
  --tracker-aware
  --manifest-aware
  --manifest-sample 6
  --candidate-top-n "$MAPPING_TOP_N"
  --output-prefix "$OUT_PREFIX"
)
if [[ -f "$TRACKER_REGISTRY" ]]; then
  map_cmd+=(--tracker-registry "$TRACKER_REGISTRY")
fi
"${map_cmd[@]}"
MAPPING_JSON="$(ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/${OUT_PREFIX}-qb-candidate-mapping-*.json | head -n1)"

bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh \
  --mapping-json "$MAPPING_JSON" \
  --baseline-json "$BASELINE_JSON" \
  --candidate-top-n "$CANDIDATE_TOP_N" \
  --output-prefix "$OUT_PREFIX" || true
AUDIT_JSON="$(ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/${OUT_PREFIX}-qb-payload-ownership-audit-*.json | head -n1)"

loop_cmd=(
  bin/rehome-105_nohl-basics-qb-repair-autoloop.sh
  --baseline-json "$BASELINE_JSON"
  --mapping-json "$MAPPING_JSON"
  --audit-json "$AUDIT_JSON"
  --batch-limit "$BATCH_LIMIT"
  --phase102-batch-size "$PHASE102_BATCH_SIZE"
  --phase102-selection-mode "$PHASE102_SELECTION_MODE"
  --max-rounds "$MAX_ROUNDS"
  --candidate-top-n "$CANDIDATE_TOP_N"
  --mapping-top-n "$MAPPING_TOP_N"
  --output-prefix "$LOOP_PREFIX"
  --sleep-s "$SLEEP_S"
  --apply-mode "$APPLY_MODE"
  --conflict-block-mode "$CONFLICT_BLOCK_MODE"
  --phase102-candidate-max-seconds "$PHASE102_CANDIDATE_MAX_SECONDS"
  --phase102-item-max-seconds "$PHASE102_ITEM_MAX_SECONDS"
  --candidate-failure-cache-threshold "$CANDIDATE_FAILURE_CACHE_THRESHOLD"
  --max-failed-attempts-per-hash "$MAX_FAILED_ATTEMPTS_PER_HASH"
  --lane-mode "$LANE_MODE"
  --lane-route-top-n "$LANE_ROUTE_TOP_N"
)
if [[ "$CONFLICT_BLOCK_MODE" == "custom" ]]; then
  loop_cmd+=(--conflict-block-types "$CONFLICT_BLOCK_TYPES")
fi
if [[ -n "$CANDIDATE_FAILURE_CACHE_JSON" ]]; then
  loop_cmd+=(--candidate-failure-cache-json "$CANDIDATE_FAILURE_CACHE_JSON")
fi
"${loop_cmd[@]}"
