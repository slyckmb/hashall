#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOL="$SCRIPT_DIR/qb-zfs-relocate.py"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/out/qb-zfs-relocate/pool-data-to-media}"
RUNS_DIR="${RUNS_DIR:-$OUT_DIR/runs}"
RUN_STAMP="${RUN_STAMP:-$(date +%Y%m%d-%H%M%S)}"
MANIFEST="${MANIFEST:-}"
CURRENT_MANIFEST="${CURRENT_MANIFEST:-$OUT_DIR/current-manifest.txt}"
LATEST_MANIFEST_LINK="${LATEST_MANIFEST_LINK:-$OUT_DIR/latest-manifest.json}"
HASH_FILE="${HASH_FILE:-$OUT_DIR/selected-hashes.txt}"
FASTRESUME_DIR="${FASTRESUME_DIR:-/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup}"
TORRENT_DIR="${TORRENT_DIR:-$FASTRESUME_DIR}"
TORRENT_EXPORT_DIR="${TORRENT_EXPORT_DIR:-$OUT_DIR/torrents}"
JOURNAL="${JOURNAL:-$OUT_DIR/patch-journal.jsonl}"
CLEANUP_JOURNAL="${CLEANUP_JOURNAL:-$OUT_DIR/cleanup-journal.jsonl}"
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
CLEANUP_PILOT_SIZE="${CLEANUP_PILOT_SIZE:-1}"
CLEANUP_BATCH_SIZE="${CLEANUP_BATCH_SIZE:-0}"
CLEANUP_OBSERVE_SECONDS="${CLEANUP_OBSERVE_SECONDS:-60}"
CLEANUP_MIN_DEPTH="${CLEANUP_MIN_DEPTH:-1}"
AUTO_CLEANUP="${AUTO_CLEANUP:-off}"
export QB_ZFS_RELOCATE_LOG_DIR="$LOG_DIR"

mkdir -p "$OUT_DIR" "$RUNS_DIR" "$TORRENT_EXPORT_DIR"

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

cleanup_args() {
  printf '%s\n' --cleanup-journal
  printf '%s\n' "$CLEANUP_JOURNAL"
  printf '%s\n' --cleanup-pilot-size
  printf '%s\n' "$CLEANUP_PILOT_SIZE"
  if [[ -n "${CLEANUP_BATCH_SIZE}" && "${CLEANUP_BATCH_SIZE}" != "0" ]]; then
    printf '%s\n' --cleanup-batch-size
    printf '%s\n' "$CLEANUP_BATCH_SIZE"
  fi
  printf '%s\n' --cleanup-observe-seconds
  printf '%s\n' "$CLEANUP_OBSERVE_SECONDS"
  printf '%s\n' --cleanup-min-depth
  printf '%s\n' "$CLEANUP_MIN_DEPTH"
}

default_manifest_path() {
  printf '%s\n' "$RUNS_DIR/$RUN_STAMP/manifest.json"
}

resolve_write_manifest() {
  if [[ -n "${MANIFEST:-}" ]]; then
    printf '%s\n' "$MANIFEST"
  else
    default_manifest_path
  fi
}

resolve_read_manifest() {
  if [[ -n "${MANIFEST:-}" ]]; then
    printf '%s\n' "$MANIFEST"
    return 0
  fi
  if [[ -f "$CURRENT_MANIFEST" ]]; then
    local current
    current="$(<"$CURRENT_MANIFEST")"
    if [[ -n "$current" ]]; then
      printf '%s\n' "$current"
      return 0
    fi
  fi
  local latest=""
  if [[ -d "$RUNS_DIR" ]]; then
    latest="$(find "$RUNS_DIR" -mindepth 2 -maxdepth 2 -type f -name manifest.json -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
  fi
  if [[ -n "$latest" ]]; then
    printf '%s\n' "$latest"
  fi
}

set_write_manifest() {
  MANIFEST="$(resolve_write_manifest)"
  export MANIFEST
  mkdir -p "$(dirname "$MANIFEST")"
}

record_current_manifest() {
  local manifest_path="$1"
  mkdir -p "$(dirname "$CURRENT_MANIFEST")"
  printf '%s\n' "$manifest_path" > "$CURRENT_MANIFEST"
  ln -snf "$manifest_path" "$LATEST_MANIFEST_LINK"
}

ensure_manifest() {
  MANIFEST="$(resolve_read_manifest)"
  export MANIFEST
  if [[ -n "${MANIFEST:-}" && -f "$MANIFEST" ]]; then
    return 0
  fi
  echo "error: manifest not found: ${MANIFEST:-<none>}" >&2
  echo "hint: run bin/migrate-pool-data-to-media_01_plan.sh first; it auto-discovers torrents under SOURCE_ROOT." >&2
  exit 2
}
