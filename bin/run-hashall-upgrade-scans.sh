#!/usr/bin/env bash
# Script: run-hashall-upgrade-scans.sh
# Version: 0.1.0
# Last-updated: 2026-04-01T17:00:00-07:00

set -euo pipefail

SCRIPT_NAME="run-hashall-upgrade-scans.sh"
VERSION="0.1.0"
LAST_UPDATED="2026-04-01T17:00:00-07:00"

DRYRUN=0
CONTINUE_ON_ERROR=0

usage() {
  cat <<'EOF'
Usage:
  run-hashall-upgrade-scans.sh [options]

Options:
  -n, --dryrun            Print commands without executing them
  -c, --continue-on-error Continue scanning other roots if one fails
  -h, --help              Show this help

Examples:
  run-hashall-upgrade-scans.sh
  run-hashall-upgrade-scans.sh --dryrun
  run-hashall-upgrade-scans.sh --continue-on-error
EOF
}

log_banner() {
  local phase="$1"
  printf 'event=%s script=%s version=%s last_updated=%s timestamp=%s\n' \
    "$phase" "$SCRIPT_NAME" "$VERSION" "$LAST_UPDATED" "$(date -Iseconds)"
}

run_cmd() {
  local label="$1"
  shift

  echo
  echo "[▶] ${label}"
  printf 'step=%s cmd=%q\n' "$label" "$*"

  if [[ "$DRYRUN" -eq 1 ]]; then
    echo "dryrun=1 status=skipped step=${label}"
    return 0
  fi

  if "$@"; then
    echo "dryrun=0 status=ok step=${label}"
    return 0
  fi

  echo "dryrun=0 status=failed step=${label}"
  return 1
}

main() {
  local roots=(
    "/stash/media"
    "/pool/data"
    "/pool/media"
    "/mnt/hotspare6tb"
  )

  local ok_count=0
  local fail_count=0
  local root

  while [[ $# -gt 0 ]]; do
    case "$1" in
    -n | --dryrun)
      DRYRUN=1
      shift
      ;;
    -c | --continue-on-error)
      CONTINUE_ON_ERROR=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error=unknown_argument arg=$1"
      usage
      exit 2
      ;;
    esac
  done

  log_banner "start"

  echo
  echo "[📂 Scan Roots]"
  printf 'count=%s\n' "${#roots[@]}"
  printf 'root=%s\n' "${roots[@]}"

  for root in "${roots[@]}"; do
    if run_cmd "scan:${root}" python -m hashall.cli scan "$root" --hash-mode upgrade --drift-policy quick; then
      ok_count=$((ok_count + 1))
    else
      fail_count=$((fail_count + 1))
      if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
        echo
        echo "[📊 Summary]"
        echo "scans_ok=${ok_count}"
        echo "scans_failed=${fail_count}"
        echo "payload_sync=skipped"
        log_banner "end"
        exit 1
      fi
    fi
  done

  if run_cmd "payload-sync" python -m hashall.cli payload sync --upgrade-missing; then
    payload_sync_status="ok"
  else
    payload_sync_status="failed"
    fail_count=$((fail_count + 1))
  fi

  echo
  echo "[📊 Summary]"
  echo "scans_ok=${ok_count}"
  echo "scans_failed=${fail_count}"
  echo "payload_sync=${payload_sync_status}"

  log_banner "end"

  [[ "$fail_count" -eq 0 ]]
}

main "$@"
