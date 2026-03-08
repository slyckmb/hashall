#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/migrate-pool-data-to-media_common.sh"

require_python
set_write_manifest
record_current_manifest "$MANIFEST"
mapfile -t MODE_ARGS < <(phase_mode_args)
mapfile -t HASH_ARGS < <(plan_hash_args)
mapfile -t BATCH_ARGS < <(batch_size_args)
mapfile -t CLEANUP_ARGS < <(cleanup_args)

EXTRA_ARGS=()
if [[ "${AUTO_STOP_QB:-1}" == "1" ]]; then
  EXTRA_ARGS+=(--auto-stop-qb)
fi
if [[ "${AUTO_CLEANUP:-off}" != "off" ]]; then
  EXTRA_ARGS+=(--auto-cleanup "$AUTO_CLEANUP")
fi
if [[ "${RESUME_REMAINING:-1}" == "1" ]]; then
  EXTRA_ARGS+=(--resume-remaining)
fi
if [[ "${RECHECK_ON_FAILURE:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--recheck-on-failure)
fi
if [[ "${ALLOW_PARTIALS:-0}" == "1" ]]; then
  EXTRA_ARGS+=(--allow-partials)
fi

exec "$PYTHON_BIN" "$TOOL" migrate \
  --manifest "$MANIFEST" \
  --source-root "$SOURCE_ROOT" \
  --dest-root "$DEST_ROOT" \
  --fastresume-dir "$FASTRESUME_DIR" \
  --torrent-dir "$TORRENT_DIR" \
  --export-torrents-dir "$TORRENT_EXPORT_DIR" \
  --journal "$JOURNAL" \
  --timeout "$VERIFY_TIMEOUT" \
  --qb-container "$QB_CONTAINER" \
  --pilot-size "$PILOT_SIZE" \
  --pilot-observe-seconds "$PILOT_OBSERVE_SECONDS" \
  "${MODE_ARGS[@]}" \
  "${BATCH_ARGS[@]}" \
  "${CLEANUP_ARGS[@]}" \
  "${HASH_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
