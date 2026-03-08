#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
ensure_manifest
mapfile -t MODE_ARGS < <(phase_mode_args)

EXTRA_ARGS=()
if [[ "${RESUME_REMAINING:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--resume-remaining)
fi
if [[ "${RECHECK_ON_FAILURE:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--recheck-on-failure)
fi

exec "$PYTHON_BIN" "$TOOL" resume \
  --manifest "$MANIFEST" \
  --qb-container "$QB_CONTAINER" \
  --pilot-size "$PILOT_SIZE" \
  --pilot-observe-seconds "$PILOT_OBSERVE_SECONDS" \
  "${MODE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
