#!/usr/bin/env bash
set -euo pipefail


SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.0"
LAST_UPDATED="2026-04-09T07:05:00-04:00"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
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
