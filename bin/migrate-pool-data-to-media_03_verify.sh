#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
ensure_manifest

exec "$PYTHON_BIN" "$TOOL" verify \
  --manifest "$MANIFEST" \
  --timeout "$VERIFY_TIMEOUT" \
  "$@"
