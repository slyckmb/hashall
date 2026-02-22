#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-89_nohl-basics-qb-automation-audit.sh [options]

Options:
  --mode MODE              audit | apply (default: audit)
  --output-prefix NAME     Output prefix (default: nohl)
  --qbit-manage-config P   qbit_manage config.yml path
                           (default: /home/michael/dev/sys/docker/qbit_manage/config.yml)
  --qbit-conf PATH         qBittorrent.conf path
                           (default: /home/michael/dev/sys/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/qBittorrent.conf)
  --qbit-manage-container  qbit_manage docker container name (default: qbit_manage)
  --fast                   Fast mode annotation
  --debug                  Debug mode annotation
  -h, --help               Show help
USAGE
}

yaml_pick_first() {
  local key="$1"
  local path="$2"
  local line
  line="$(rg -N "^[[:space:]]*${key}:[[:space:]]*" "$path" 2>/dev/null | head -n1 || true)"
  if [[ -z "$line" ]]; then
    echo ""
    return 0
  fi
  echo "$line" | sed -E "s/^[[:space:]]*${key}:[[:space:]]*//; s/[[:space:]]+#.*$//"
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MODE="${MODE:-audit}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
QBIT_MANAGE_CONFIG="${QBIT_MANAGE_CONFIG:-/home/michael/dev/sys/docker/qbit_manage/config.yml}"
QBIT_CONF="${QBIT_CONF:-/home/michael/dev/sys/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/qBittorrent.conf}"
QBIT_MANAGE_CONTAINER="${QBIT_MANAGE_CONTAINER:-qbit_manage}"
QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --qbit-manage-config) QBIT_MANAGE_CONFIG="${2:-}"; shift 2 ;;
    --qbit-conf) QBIT_CONF="${2:-}"; shift 2 ;;
    --qbit-manage-container) QBIT_MANAGE_CONTAINER="${2:-}"; shift 2 ;;
    --fast) FAST=1; shift ;;
    --debug) DEBUG=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "audit" && "$MODE" != "apply" ]]; then
  echo "Invalid --mode: $MODE" >&2
  exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found" >&2
  exit 3
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found" >&2
  exit 3
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-automation-audit-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 89: qB automation audit"
echo "What this does: check qB/qbit_manage auto-resume behavior and optionally enforce safe add-as-paused."
hr
echo "run_id=${stamp} step=basics-qb-automation-audit mode=${MODE} output_prefix=${OUTPUT_PREFIX} qbit_url=${QBIT_URL} qbit_manage_config=${QBIT_MANAGE_CONFIG} qbit_conf=${QBIT_CONF} container=${QBIT_MANAGE_CONTAINER} fast=${FAST} debug=${DEBUG}"

cookie_file="$(mktemp)"
trap 'rm -f "$cookie_file"' EXIT

auth_result="$(curl -fsS -c "$cookie_file" \
  --data-urlencode "username=${QBIT_USER}" \
  --data-urlencode "password=${QBIT_PASS}" \
  "${QBIT_URL}/api/v2/auth/login" || true)"
if [[ "$auth_result" != "Ok." ]]; then
  echo "Failed qB auth result=${auth_result:-empty}" >&2
  exit 4
fi

prefs_json="$(curl -fsS -b "$cookie_file" "${QBIT_URL}/api/v2/app/preferences")"
add_stopped_enabled="$(jq -r 'if has("add_stopped_enabled") then (.add_stopped_enabled|tostring) else "missing" end' <<<"$prefs_json")"
start_paused_enabled="$(jq -r 'if has("start_paused_enabled") then (.start_paused_enabled|tostring) else "missing" end' <<<"$prefs_json")"
auto_tmm_enabled="$(jq -r 'if has("auto_tmm_enabled") then (.auto_tmm_enabled|tostring) else "missing" end' <<<"$prefs_json")"

if [[ "$MODE" == "apply" && "$add_stopped_enabled" != "true" ]]; then
  set_json='{"add_stopped_enabled":true}'
  curl -fsS -b "$cookie_file" \
    --data-urlencode "json=${set_json}" \
    "${QBIT_URL}/api/v2/app/setPreferences" >/dev/null
  prefs_json="$(curl -fsS -b "$cookie_file" "${QBIT_URL}/api/v2/app/preferences")"
  add_stopped_enabled="$(jq -r 'if has("add_stopped_enabled") then (.add_stopped_enabled|tostring) else "missing" end' <<<"$prefs_json")"
  echo "qbit_pref_enforce key=add_stopped_enabled value=${add_stopped_enabled}"
fi

qbm_exists=0
qbm_recheck="missing"
qbm_tag_update="missing"
qbm_cat_update="missing"
qbm_force_auto_tmm="missing"
qbm_dry_run="missing"
qbm_nohl_filter="missing"
if [[ -f "$QBIT_MANAGE_CONFIG" ]]; then
  qbm_exists=1
  qbm_recheck="$(yaml_pick_first "recheck" "$QBIT_MANAGE_CONFIG")"
  qbm_tag_update="$(yaml_pick_first "tag_update" "$QBIT_MANAGE_CONFIG")"
  qbm_cat_update="$(yaml_pick_first "cat_update" "$QBIT_MANAGE_CONFIG")"
  qbm_force_auto_tmm="$(yaml_pick_first "force_auto_tmm" "$QBIT_MANAGE_CONFIG")"
  qbm_dry_run="$(yaml_pick_first "dry_run" "$QBIT_MANAGE_CONFIG")"
  qbm_nohl_filter="$(yaml_pick_first "tag_nohardlinks_filter_completed" "$QBIT_MANAGE_CONFIG")"
fi

qbm_container_state="unknown"
if command -v docker >/dev/null 2>&1; then
  if docker ps -a --format '{{.Names}}\t{{.Status}}' >/tmp/rehome-qbm-docker-status.txt 2>/tmp/rehome-qbm-docker-status.err; then
    qbm_container_state="$(awk -F'\t' -v n="$QBIT_MANAGE_CONTAINER" '$1 == n {print $2; found=1; exit} END {if (!found) print "not-found"}' /tmp/rehome-qbm-docker-status.txt)"
  else
    qbm_container_state="docker-error"
  fi
  rm -f /tmp/rehome-qbm-docker-status.txt /tmp/rehome-qbm-docker-status.err
fi

run_external_enabled="missing"
run_external_cmd=""
run_external_script=""
run_external_script_exists=0
run_external_script_resumes=0
if [[ -f "$QBIT_CONF" ]]; then
  run_external_enabled="$(rg -N '^Torrenting\\RunExternalProgramEnabled=' "$QBIT_CONF" | head -n1 | cut -d= -f2- || true)"
  run_external_cmd="$(rg -N '^Torrenting\\RunExternalProgram=' "$QBIT_CONF" | head -n1 | cut -d= -f2- || true)"
  if [[ -n "$run_external_cmd" ]]; then
    run_external_script="$(sed -E 's/^"([^"]+)".*/\1/; t; s/^([^[:space:]]+).*/\1/' <<<"$run_external_cmd")"
    if [[ -f "$run_external_script" ]]; then
      run_external_script_exists=1
      if rg -n 'api/v2/torrents/resume|/torrents/resume|torrents/resume' "$run_external_script" >/dev/null 2>&1; then
        run_external_script_resumes=1
      fi
    fi
  fi
fi

declare -a risks=()
if [[ "$add_stopped_enabled" != "true" ]]; then
  risks+=("qbit_add_stopped_disabled")
fi
if [[ "$qbm_recheck" == "true" ]]; then
  risks+=("qbit_manage_recheck_enabled")
fi
if [[ "$run_external_enabled" == "true" && "$run_external_script_resumes" == "1" ]]; then
  risks+=("qb_on_add_script_resumes")
fi

echo "qbit_pref add_stopped_enabled=${add_stopped_enabled} start_paused_enabled=${start_paused_enabled} auto_tmm_enabled=${auto_tmm_enabled}"
echo "qbit_manage config_exists=${qbm_exists} container_state=${qbm_container_state} recheck=${qbm_recheck:-missing} tag_update=${qbm_tag_update:-missing} cat_update=${qbm_cat_update:-missing} force_auto_tmm=${qbm_force_auto_tmm:-missing} dry_run=${qbm_dry_run:-missing} tag_nohardlinks_filter_completed=${qbm_nohl_filter:-missing}"
echo "qb_on_add enabled=${run_external_enabled:-missing} command=${run_external_cmd:-missing} script=${run_external_script:-missing} script_exists=${run_external_script_exists} script_contains_resume=${run_external_script_resumes}"
echo "summary risk_count=${#risks[@]} risks=${risks[*]:-none}"

hr
echo "result=ok step=basics-qb-automation-audit run_log=${run_log}"
hr
