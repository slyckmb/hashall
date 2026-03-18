#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
ensure_manifest
mapfile -t MODE_ARGS < <(phase_mode_args)

exec "$PYTHON_BIN" "$TOOL" copy \
  --manifest "$MANIFEST" \
  "${MODE_ARGS[@]}" \
  "$@"
