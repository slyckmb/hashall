#!/usr/bin/env bash
# Version: 1.0.0
# Fix ownership/permissions on media roots after docker containers set wrong perms.
# Owner: michael:michael  |  dirs: 2755 (setgid)  |  files: 644
set -euo pipefail

SCRIPT_VERSION="1.0.0"
DRY_RUN=0
TARGETS=()

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run] [path ...]

Recursively fix ownership and permissions on media roots:
  chown -R michael:michael <path>
  find <path> -type d → chmod 2755 (setgid + rwxr-xr-x)
  find <path> -type f → chmod 644

Default targets (if no paths specified):
  /data/media
  /pool/data
  /mnt/hotspare6tb

Options:
  --dry-run   Show what would be done, don't apply
  -h, --help  Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --dry-run) DRY_RUN=1; shift ;;
  -h|--help) usage; exit 0 ;;
  -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  *) TARGETS+=("$1"); shift ;;
  esac
done

if [[ "${#TARGETS[@]}" -eq 0 ]]; then
  TARGETS=(/data/media /pool/data /mnt/hotspare6tb)
fi

echo "fix-permissions.sh v${SCRIPT_VERSION} dry_run=${DRY_RUN}"
echo "Targets: ${TARGETS[*]}"

for root in "${TARGETS[@]}"; do
  if [[ ! -d "$root" ]]; then
    echo "SKIP (not a directory): $root"
    continue
  fi
  echo ""
  echo "==> $root"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] chown -R michael:michael $root"
    echo "  [dry-run] find $root -type d -exec chmod 2755 {} +"
    echo "  [dry-run] find $root -type f -exec chmod 644 {} +"
  else
    echo -n "  chown..."
    chown -R michael:michael "$root"
    echo " done"
    echo -n "  chmod dirs (2755)..."
    find "$root" -type d -exec chmod 2755 {} +
    echo " done"
    echo -n "  chmod files (644)..."
    find "$root" -type f -exec chmod 644 {} +
    echo " done"
    echo "  $root FIXED"
  fi
done

echo ""
echo "fix-permissions.sh complete"
