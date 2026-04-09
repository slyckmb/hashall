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
