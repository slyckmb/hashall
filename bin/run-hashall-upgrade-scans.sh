#!/usr/bin/env bash
# Script: run-hashall-upgrade-scans.sh
# Version: 0.3.0
# Last-updated: 2026-04-03T15:15:00-04:00

set -euo pipefail

SCRIPT_NAME="run-hashall-upgrade-scans.sh"
VERSION="0.3.0"
LAST_UPDATED="2026-04-03T15:15:00-04:00"

DRYRUN=0
CONTINUE_ON_ERROR=0
PAYLOAD_SYNC_ONLY=0
STACK_RESTARTS=0

STACK_CONTAINERS=(
  "gluetun"
  "qbittorrent_vpn"
  "rtorrent_vpn"
)
STACK_READY_ATTEMPTS=18
STACK_READY_SLEEP_S=10
PAYLOAD_SOURCE="rt"
RT_SESSION_DIR="/dump/docker/gluetun_qbit/rtorrent_vpn/.session"

compose_up_gluetun_qbit_stack() {
  local label_source=""
  local workdir=""
  local config_file=""
  for label_source in qbittorrent_vpn rtorrent_vpn gluetun; do
    workdir="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$label_source" 2>/dev/null || true)"
    config_file="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$label_source" 2>/dev/null || true)"
    if [[ -n "$workdir" && -n "$config_file" ]]; then
      break
    fi
  done
  if [[ -z "$workdir" || -z "$config_file" ]]; then
    return 1
  fi
  docker compose --project-directory "$workdir" -f "$config_file" up -d gluetun qbittorrent_vpn rtorrent_vpn
}

usage() {
  cat <<'EOF'
Usage:
  run-hashall-upgrade-scans.sh [options]

Options:
  -n, --dryrun            Print commands without executing them
  -c, --continue-on-error Continue scanning other roots if one fails
  --payload-sync-only     Skip scans and resume from payload sync only
  --payload-source SRC    Final payload sync source: rt or qb (default: rt)
  --rt-session-dir PATH   rTorrent session directory for --payload-source rt
  -h, --help              Show this help

Examples:
  run-hashall-upgrade-scans.sh
  run-hashall-upgrade-scans.sh --dryrun
  run-hashall-upgrade-scans.sh --continue-on-error
  run-hashall-upgrade-scans.sh --payload-sync-only
  run-hashall-upgrade-scans.sh --payload-source rt
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

probe_qb_client() {
  if [[ "$DRYRUN" -eq 1 ]]; then
    return 0
  fi
  python - <<'PY'
from hashall.qbittorrent import get_qbittorrent_client

client = get_qbittorrent_client()
raise SystemExit(0 if client.test_connection() else 1)
PY
}

probe_rt_cache() {
  if [[ "$DRYRUN" -eq 1 ]]; then
    return 0
  fi
  python - <<'PY'
from pathlib import Path
import json
import os

meta_path = Path(os.path.expanduser("~/.cache/silo-rt/torrents.meta.json"))
if not meta_path.exists():
    raise SystemExit(1)
try:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

source = str(meta.get("source") or "").strip()
last_error = str(meta.get("last_error") or "").strip()
if source == "daemon_error" or last_error:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

restart_gluetun_qbit_stack() {
  echo
  echo "[↻] restart gluetun_qbit stack"
  printf 'stack_containers=%s\n' "${STACK_CONTAINERS[*]}"
  if [[ "$DRYRUN" -eq 1 ]]; then
    echo "dryrun=1 status=skipped step=restart-stack"
    return 0
  fi
  if ! compose_up_gluetun_qbit_stack; then
    docker stop qbittorrent_vpn rtorrent_vpn >/dev/null 2>&1 || true
    docker restart gluetun
    local attempt=1
    while [[ "$attempt" -le "$STACK_READY_ATTEMPTS" ]]; do
      local gluetun_state
      gluetun_state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' gluetun 2>/dev/null || true)"
      if [[ "$gluetun_state" == "healthy" || "$gluetun_state" == "running" ]]; then
        break
      fi
      echo "status=pending step=wait-for-gluetun attempts=${attempt}/${STACK_READY_ATTEMPTS} state=${gluetun_state:-unknown}"
      sleep "$STACK_READY_SLEEP_S"
      attempt=$((attempt + 1))
    done
    docker start qbittorrent_vpn rtorrent_vpn
  fi
  STACK_RESTARTS=$((STACK_RESTARTS + 1))
}

wait_for_stack_ready() {
  local attempt=1
  while [[ "$attempt" -le "$STACK_READY_ATTEMPTS" ]]; do
    if probe_qb_client && probe_rt_cache; then
      echo "status=ok step=wait-for-stack-ready attempts=${attempt}"
      return 0
    fi
    echo "status=pending step=wait-for-stack-ready attempts=${attempt}/${STACK_READY_ATTEMPTS}"
    sleep "$STACK_READY_SLEEP_S"
    attempt=$((attempt + 1))
  done
  echo "status=failed step=wait-for-stack-ready attempts=${STACK_READY_ATTEMPTS}"
  return 1
}

ensure_client_stack_ready() {
  echo
  echo "[🩺] client stack preflight"
  if probe_qb_client && probe_rt_cache; then
    echo "status=ok step=client-stack-preflight"
    return 0
  fi
  echo "status=degraded step=client-stack-preflight action=restart-stack"
  restart_gluetun_qbit_stack || return 1
  wait_for_stack_ready
}

run_payload_sync_with_recovery() {
  if ! ensure_client_stack_ready; then
    echo "status=failed step=client-stack-preflight"
    payload_sync_status="failed"
    return 1
  fi

  local sync_cmd=(
    python -m hashall.cli payload sync
    --source "$PAYLOAD_SOURCE"
    --upgrade-missing
  )
  if [[ "$PAYLOAD_SOURCE" == "rt" ]]; then
    sync_cmd+=(--rt-session-dir "$RT_SESSION_DIR")
  fi

  if run_cmd "payload-sync" "${sync_cmd[@]}"; then
    payload_sync_status="ok"
    return 0
  fi

  echo "status=degraded step=payload-sync action=restart-stack-and-retry"
  if ! restart_gluetun_qbit_stack; then
    payload_sync_status="failed"
    return 1
  fi
  if ! wait_for_stack_ready; then
    payload_sync_status="failed"
    return 1
  fi
  if run_cmd "payload-sync-retry" "${sync_cmd[@]}"; then
    payload_sync_status="recovered"
    return 0
  fi

  payload_sync_status="failed"
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
  local scan_fail_count=0
  local payload_sync_status="skipped"
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
    --payload-sync-only)
      PAYLOAD_SYNC_ONLY=1
      shift
      ;;
    --payload-source)
      PAYLOAD_SOURCE="${2:-}"
      if [[ "$PAYLOAD_SOURCE" != "rt" && "$PAYLOAD_SOURCE" != "qb" ]]; then
        echo "error=invalid_payload_source value=${PAYLOAD_SOURCE:-missing}"
        usage
        exit 2
      fi
      shift 2
      ;;
    --rt-session-dir)
      RT_SESSION_DIR="${2:-}"
      if [[ -z "$RT_SESSION_DIR" ]]; then
        echo "error=missing_rt_session_dir"
        usage
        exit 2
      fi
      shift 2
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

  if [[ "$PAYLOAD_SYNC_ONLY" -ne 1 ]]; then
    echo
    echo "[📂 Scan Roots]"
    printf 'count=%s\n' "${#roots[@]}"
    printf 'root=%s\n' "${roots[@]}"

    for root in "${roots[@]}"; do
      if run_cmd "scan:${root}" python -m hashall.cli scan "$root" --hash-mode upgrade --drift-policy quick; then
        ok_count=$((ok_count + 1))
      else
        scan_fail_count=$((scan_fail_count + 1))
        if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
          echo
          echo "[📊 Summary]"
          echo "scans_ok=${ok_count}"
          echo "scans_failed=${scan_fail_count}"
          echo "payload_sync=skipped"
          echo "stack_restarts=${STACK_RESTARTS}"
          log_banner "end"
          exit 1
        fi
      fi
    done
  else
    echo
    echo "[⏭] Skipping scans and resuming at payload sync only"
  fi

  if ! run_payload_sync_with_recovery; then
    :
  fi

  echo
  echo "[📊 Summary]"
  echo "scans_ok=${ok_count}"
  echo "scans_failed=${scan_fail_count}"
  echo "payload_sync=${payload_sync_status}"
  echo "payload_source=${PAYLOAD_SOURCE}"
  echo "stack_restarts=${STACK_RESTARTS}"

  log_banner "end"

  [[ "$scan_fail_count" -eq 0 && "$payload_sync_status" != "failed" ]]
}

main "$@"
