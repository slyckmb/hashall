#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
ensure_manifest
mapfile -t MODE_ARGS < <(phase_mode_args)

EXTRA_ARGS=()
if [[ "${APPLY:-0}" == "1" ]]; then
  [[ "${CONFIRM_CLEANUP:-0}" == "1" ]] || {
    echo "error: set CONFIRM_CLEANUP=1 before live cleanup" >&2
    exit 2
  }
  EXTRA_ARGS+=(--confirm-cleanup)
fi

exec "$PYTHON_BIN" "$TOOL" cleanup \
  --manifest "$MANIFEST" \
  "${MODE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
