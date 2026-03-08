#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOL="$SCRIPT_DIR/qb-zfs-relocate.py"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/out/qb-zfs-relocate/pool-data-to-media}"
MANIFEST="${MANIFEST:-$OUT_DIR/manifest.json}"
HASH_FILE="${HASH_FILE:-$OUT_DIR/selected-hashes.txt}"
FASTRESUME_DIR="${FASTRESUME_DIR:-/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup}"
TORRENT_DIR="${TORRENT_DIR:-$FASTRESUME_DIR}"
TORRENT_EXPORT_DIR="${TORRENT_EXPORT_DIR:-$OUT_DIR/torrents}"
JOURNAL="${JOURNAL:-$OUT_DIR/patch-journal.jsonl}"
QB_CONTAINER="${QB_CONTAINER:-qbittorrent_vpn}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEFAULT_LOG_BASE="${HOME:-$REPO_ROOT}"
LOG_DIR="${LOG_DIR:-$DEFAULT_LOG_BASE/.logs/qb-zfs-relocate}"
SOURCE_ROOT="${SOURCE_ROOT:-/pool/data/media/torrents/seeding}"
DEST_ROOT="${DEST_ROOT:-/pool/media/torrents/seeding}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-1800}"
BATCH_SIZE="${BATCH_SIZE:-0}"
PILOT_SIZE="${PILOT_SIZE:-5}"
PILOT_OBSERVE_SECONDS="${PILOT_OBSERVE_SECONDS:-15}"
export QB_ZFS_RELOCATE_LOG_DIR="$LOG_DIR"

mkdir -p "$OUT_DIR" "$TORRENT_EXPORT_DIR"

require_python() {
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "error: python not found: $PYTHON_BIN" >&2
    exit 2
  }
}

phase_mode_args() {
  if [[ "${APPLY:-0}" == "1" ]]; then
    printf '%s\n' --apply
  else
    printf '%s\n' --dryrun
  fi
}

hash_file_has_entries() {
  [[ -f "$HASH_FILE" ]] || return 1
  grep -Eq '^[[:space:]]*[^#[:space:]]' "$HASH_FILE"
}

plan_hash_args() {
  if hash_file_has_entries; then
    printf '%s\n' --hashes-file
    printf '%s\n' "$HASH_FILE"
    return 0
  fi
  if [[ -f "$HASH_FILE" ]]; then
    echo "warning: ignoring empty/comment-only hash override file: $HASH_FILE" >&2
  fi
}

batch_size_args() {
  if [[ -n "${BATCH_SIZE}" && "${BATCH_SIZE}" != "0" ]]; then
    printf '%s\n' --batch-size
    printf '%s\n' "$BATCH_SIZE"
  fi
}

ensure_manifest() {
  if [[ -f "$MANIFEST" ]]; then
    return 0
  fi
  echo "error: manifest not found: $MANIFEST" >&2
  echo "hint: run bin/migrate-pool-data-to-media_01_plan.sh first; it auto-discovers torrents under SOURCE_ROOT." >&2
  exit 2
}
