#!/usr/bin/env bash
set -euo pipefail

DST_DEFAULT="/stash/media/torrents/seeding/recovery_20260211/recycle_snapshot_20260207/"

# Try known snapshot layouts in priority order.
SRC_CANDIDATES=(
  "/stash/media/torrents/.zfs/snapshot/recycle_snapshot_20260207/"
  "/stash/media/.zfs/snapshot/recycle_snapshot_20260207/torrents/"
  "/stash/media/.zfs/snapshot/hashall-link-plan2-20260207-223702/torrents/"
)

DRY_RUN=0
ASSUME_YES=0
SRC=""
SRC_SET=0
DST="$DST_DEFAULT"
BWLIMIT=""

usage() {
  cat <<'USAGE'
Usage: recovery-rsync-pass.sh [options]

Run an idempotent rsync pass from a ZFS snapshot into recovery staging.
Only missing/changed data is transferred; existing recovered data is respected.

Options:
  -n, --dry-run        Preview only (no writes)
  -y, --yes            Skip live-run confirmation prompt
      --src PATH       Source directory (override auto-detected snapshot path)
      --dst PATH       Destination directory (default: recovery staging path)
      --bwlimit KBPS   Optional rsync --bwlimit value (KB/s)
  -h, --help           Show help

Examples:
  recovery-rsync-pass.sh --dry-run
  recovery-rsync-pass.sh
  recovery-rsync-pass.sh --src /stash/media/.zfs/snapshot/<snapshot_name>/torrents/ \
                         --dst /stash/media/torrents/seeding/recovery_20260212/<snapshot_name>/
USAGE
}

normalize_dir() {
  local p="$1"
  p="${p%/}/"
  printf '%s' "$p"
}

dir_exists() {
  local p="$1"
  [[ -d "$p" ]] && return 0
  if command -v sudo >/dev/null 2>&1; then
    sudo test -d "$p" 2>/dev/null && return 0
  fi
  return 1
}

auto_detect_src() {
  local c
  for c in "${SRC_CANDIDATES[@]}"; do
    c="$(normalize_dir "$c")"
    if dir_exists "$c"; then
      printf '%s' "$c"
      return 0
    fi
  done
  return 1
}

show_snapshot_hint() {
  echo "hint: recent snapshot names under /stash/media/.zfs/snapshot:" >&2
  ls -1 /stash/media/.zfs/snapshot 2>/dev/null | tail -20 >&2 || true
  echo "hint: rerun with --src /stash/media/.zfs/snapshot/<snapshot_name>/torrents/" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run)
      DRY_RUN=1
      shift
      ;;
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    --src)
      [[ $# -ge 2 ]] || { echo "error: --src requires a path" >&2; exit 2; }
      SRC="$2"
      SRC_SET=1
      shift 2
      ;;
    --dst)
      [[ $# -ge 2 ]] || { echo "error: --dst requires a path" >&2; exit 2; }
      DST="$2"
      shift 2
      ;;
    --bwlimit)
      [[ $# -ge 2 ]] || { echo "error: --bwlimit requires a value" >&2; exit 2; }
      BWLIMIT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$SRC_SET" -eq 0 ]]; then
  if ! SRC="$(auto_detect_src)"; then
    echo "error: no default snapshot source path was found" >&2
    show_snapshot_hint
    exit 2
  fi
fi

SRC="$(normalize_dir "$SRC")"
DST="$(normalize_dir "$DST")"

[[ -n "$SRC" && -n "$DST" ]] || { echo "error: src/dst cannot be empty" >&2; exit 2; }
[[ "$SRC" != "/" && "$DST" != "/" ]] || { echo "error: refusing to use '/' as src or dst" >&2; exit 2; }
[[ "$SRC" != "$DST" ]] || { echo "error: src and dst must differ" >&2; exit 2; }

# Guardrails for this recovery workflow.
if [[ "$SRC" != /stash/media/torrents/.zfs/snapshot/* && "$SRC" != /stash/media/.zfs/snapshot/*/torrents/* ]]; then
  echo "error: src must be under /stash/media/torrents/.zfs/snapshot/ or /stash/media/.zfs/snapshot/<snap>/torrents/" >&2
  exit 2
fi
[[ "$DST" == /stash/media/torrents/seeding/recovery_* ]] || {
  echo "error: dst must be under /stash/media/torrents/seeding/recovery_*" >&2
  exit 2
}

if ! dir_exists "$SRC"; then
  echo "error: source does not exist: $SRC" >&2
  show_snapshot_hint
  exit 2
fi

if [[ ! -d "$DST" ]]; then
  echo "info: creating destination: $DST"
  sudo mkdir -p "$DST"
fi

RSYNC_OPTS=(
  -aHAX
  --numeric-ids
  --partial
  --append-verify
  --info=progress2,stats2
  --human-readable
)

if [[ -n "$BWLIMIT" ]]; then
  RSYNC_OPTS+=("--bwlimit=$BWLIMIT")
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  RSYNC_OPTS+=(--dry-run)
fi

printf 'mode=%s\n' "$( [[ "$DRY_RUN" -eq 1 ]] && echo dry-run || echo live )"
printf 'src=%s\n' "$SRC"
printf 'dst=%s\n' "$DST"
[[ -n "$BWLIMIT" ]] && printf 'bwlimit=%s KB/s\n' "$BWLIMIT"

printf 'cmd='
printf '%q ' sudo ionice -c2 -n7 nice -n 19 rsync "${RSYNC_OPTS[@]}" "$SRC" "$DST"
printf '\n'

if [[ "$DRY_RUN" -eq 0 && "$ASSUME_YES" -eq 0 ]]; then
  read -r -p "Proceed with LIVE rsync recovery pass? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *)
      echo "aborted"
      exit 1
      ;;
  esac
fi

exec sudo ionice -c2 -n7 nice -n 19 rsync "${RSYNC_OPTS[@]}" "$SRC" "$DST"
