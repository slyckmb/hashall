#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
ensure_manifest
mapfile -t MODE_ARGS < <(phase_mode_args)

EXTRA_ARGS=()
if [[ "${AUTO_STOP_QB:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--auto-stop-qb)
fi

exec "$PYTHON_BIN" "$TOOL" patch \
  --manifest "$MANIFEST" \
  --journal "$JOURNAL" \
  --qb-container "$QB_CONTAINER" \
  "${MODE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
