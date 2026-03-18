#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
set_write_manifest
record_current_manifest "$MANIFEST"
mapfile -t HASH_ARGS < <(plan_hash_args)
mapfile -t BATCH_ARGS < <(batch_size_args)

exec "$PYTHON_BIN" "$TOOL" plan \
  --manifest "$MANIFEST" \
  --source-root "$SOURCE_ROOT" \
  --dest-root "$DEST_ROOT" \
  --fastresume-dir "$FASTRESUME_DIR" \
  --torrent-dir "$TORRENT_DIR" \
  --export-torrents-dir "$TORRENT_EXPORT_DIR" \
  "${BATCH_ARGS[@]}" \
  "${HASH_ARGS[@]}" \
  "$@"
