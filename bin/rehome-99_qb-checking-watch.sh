#!/usr/bin/env bash
set -euo pipefail

QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
INTERVAL_S=15
ONCE=0
UNTIL_CLEAR=0
ENFORCE_PAUSED_DL=0
ALLOW_FILE=""
EVENTS_JSONL=""
MAX_ITERATIONS=0
declare -a ALLOW_HASHES=()

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Watches qB torrent state counts (checking/missing/moving/down/up).
Optional watchdog mode pauses unexpected downloading torrents and emits alerts.
Env: QBIT_URL, QBIT_USER, QBIT_PASS

Options:
  --interval N            Poll interval seconds (default: 15)
  --once                  Run one sample then exit
  --until-clear           Exit when checking=0 and moving=0 and down=0
  --enforce-paused-dl     Pause unexpected downloading/stalledDL torrents
  --allow-hash HASH       Allowlist hash that watchdog must not auto-pause (repeatable)
  --allow-file PATH       File with allowlisted hashes (one per line)
  --events-jsonl PATH     Write watchdog events as JSONL
  --max-iterations N      Exit after N polling iterations (default: 0 = infinite)
  -h, --help              Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)
      INTERVAL_S="${2:-}"
      shift 2
      ;;
    --once)
      ONCE=1
      shift
      ;;
    --until-clear)
      UNTIL_CLEAR=1
      shift
      ;;
    --enforce-paused-dl)
      ENFORCE_PAUSED_DL=1
      shift
      ;;
    --allow-hash)
      ALLOW_HASHES+=("${2:-}")
      shift 2
      ;;
    --allow-file)
      ALLOW_FILE="${2:-}"
      shift 2
      ;;
    --events-jsonl)
      EVENTS_JSONL="${2:-}"
      shift 2
      ;;
    --max-iterations)
      MAX_ITERATIONS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$INTERVAL_S" =~ ^[0-9]+$ ]] || [[ "$INTERVAL_S" -lt 1 ]]; then
  echo "--interval must be a positive integer" >&2
  exit 2
fi
if ! [[ "$MAX_ITERATIONS" =~ ^[0-9]+$ ]]; then
  echo "--max-iterations must be a non-negative integer" >&2
  exit 2
fi

COOKIE_FILE="$(mktemp)"
trap 'rm -f "$COOKIE_FILE"' EXIT
if [[ "$ENFORCE_PAUSED_DL" -eq 1 && -n "$EVENTS_JSONL" ]]; then
  mkdir -p "$(dirname "$EVENTS_JSONL")"
fi

declare -A ALLOW_HASH_MAP=()
for h in "${ALLOW_HASHES[@]}"; do
  key="$(tr '[:upper:]' '[:lower:]' <<<"${h//[[:space:]]/}")"
  [[ -n "$key" ]] && ALLOW_HASH_MAP["$key"]=1
done
if [[ -n "$ALLOW_FILE" && -f "$ALLOW_FILE" ]]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    key="$(tr '[:upper:]' '[:lower:]' <<<"${line//[[:space:]]/}")"
    [[ -n "$key" ]] && ALLOW_HASH_MAP["$key"]=1
  done < "$ALLOW_FILE"
fi

if [[ "$ENFORCE_PAUSED_DL" -eq 1 && -z "$EVENTS_JSONL" ]]; then
  stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
  EVENTS_JSONL="out/reports/rehome-normalize/qb-paused-dl-watchdog-${stamp}.jsonl"
  mkdir -p "$(dirname "$EVENTS_JSONL")"
fi

echo "watchdog_config interval_s=${INTERVAL_S} once=${ONCE} until_clear=${UNTIL_CLEAR} enforce_paused_dl=${ENFORCE_PAUSED_DL} allow_count=${#ALLOW_HASH_MAP[@]} events_jsonl=${EVENTS_JSONL:-none} max_iterations=${MAX_ITERATIONS}"

api_post_status() {
  local endpoint="$1"
  local hashes="$2"
  curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE_FILE" \
    --data-urlencode "hashes=${hashes}" \
    "${QBIT_URL}${endpoint}" || echo "000"
}

pause_with_fallback() {
  local hashes="$1"
  local code=""

  code="$(api_post_status "/api/v2/torrents/pause" "$hashes")"
  case "$code" in
    200|202)
      PAUSE_ACTION_RESULT="paused"
      return 0
      ;;
    404)
      code="$(api_post_status "/api/v2/torrents/stop" "$hashes")"
      if [[ "$code" == "200" || "$code" == "202" ]]; then
        PAUSE_ACTION_RESULT="paused_via_stop"
        return 0
      fi
      PAUSE_ACTION_RESULT="pause_failed_stop_http_${code}"
      return 1
      ;;
    *)
      PAUSE_ACTION_RESULT="pause_failed_http_${code}"
      return 1
      ;;
  esac
}

iteration=0

while true; do
  iteration=$((iteration + 1))

  curl -fsS -c "$COOKIE_FILE" \
    --data-urlencode "username=${QBIT_USER}" \
    --data-urlencode "password=${QBIT_PASS}" \
    "${QBIT_URL}/api/v2/auth/login" >/dev/null

  TORRENTS_JSON="$(curl -fsS -b "$COOKIE_FILE" "${QBIT_URL}/api/v2/torrents/info")"

  read -r CHECKING MISSING MOVING DOWN UP COUNT_ZERO COUNT_PARTIAL STOPPED_UP STOPPED_DL TOP_STATES <<<"$(jq -r '
    [
      ([.[] | (.state // "" | ascii_downcase) | select(startswith("checking"))] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "missingfiles")] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "moving")] | length),
      ([.[] | select(
        (.state // "" | ascii_downcase) == "downloading"
        or (.state // "" | ascii_downcase) == "stalleddl"
        or (.state // "" | ascii_downcase) == "queueddl"
        or (.state // "" | ascii_downcase) == "forceddl"
        or (.state // "" | ascii_downcase) == "metadl"
        or (.state // "" | ascii_downcase) == "checkingdl"
      )] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "uploading" or (.state // "" | ascii_downcase) == "stalledup")] | length),
      ([.[] | select((.progress // 0) <= 0.0)] | length),
      ([.[] | select((.progress // 0) > 0.0 and (.progress // 0) < 1.0)] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "stoppedup")] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "stoppeddl")] | length),
      (
        group_by(.state // "UNKNOWN")
        | map({s: (.[0].state // "UNKNOWN"), c: length})
        | sort_by(-.c)
        | .[:8]
        | map("\(.s)=\(.c)")
        | join(",")
      )
    ] | @tsv
  ' <<<"$TORRENTS_JSON")"

  mapfile -t DOWN_HASHES_RAW < <(jq -r '
    .[]
    | select(
        (.state // "" | ascii_downcase) == "downloading"
        or (.state // "" | ascii_downcase) == "stalleddl"
        or (.state // "" | ascii_downcase) == "queueddl"
        or (.state // "" | ascii_downcase) == "forceddl"
        or (.state // "" | ascii_downcase) == "metadl"
        or (.state // "" | ascii_downcase) == "checkingdl"
      )
    | (.hash // "" | ascii_downcase)
  ' <<<"$TORRENTS_JSON")
  declare -a UNEXPECTED_DOWN=()
  declare -A SEEN_HASH=()
  for torrent_hash in "${DOWN_HASHES_RAW[@]}"; do
    [[ -z "$torrent_hash" ]] && continue
    if [[ -n "${SEEN_HASH[$torrent_hash]+x}" ]]; then
      continue
    fi
    SEEN_HASH["$torrent_hash"]=1
    if [[ -z "${ALLOW_HASH_MAP[$torrent_hash]+x}" ]]; then
      UNEXPECTED_DOWN+=("$torrent_hash")
    fi
  done

  paused_now=0
  if [[ "$ENFORCE_PAUSED_DL" -eq 1 && "${#UNEXPECTED_DOWN[@]}" -gt 0 ]]; then
    pause_hashes="$(IFS='|'; echo "${UNEXPECTED_DOWN[*]}")"
    pause_action="pause_failed"
    PAUSE_ACTION_RESULT="pause_failed"
    if pause_with_fallback "$pause_hashes"; then
      pause_action="$PAUSE_ACTION_RESULT"
      paused_now="${#UNEXPECTED_DOWN[@]}"
    else
      pause_action="$PAUSE_ACTION_RESULT"
    fi
    alert_hashes="$(IFS=,; echo "${UNEXPECTED_DOWN[*]}")"
    printf '%s ALERT unexpected_downloading action=%s count=%s hashes=%s\n' \
      "$(date '+%F %T')" "$pause_action" "${#UNEXPECTED_DOWN[@]}" "$alert_hashes"
    if [[ -n "$EVENTS_JSONL" ]]; then
      hashes_json="$(printf '%s\n' "${UNEXPECTED_DOWN[@]}" | jq -Rsc 'split("\n")[:-1]')"
      jq -cn \
        --arg ts "$(date '+%F %T')" \
        --arg action "$pause_action" \
        --argjson count "${#UNEXPECTED_DOWN[@]}" \
        --argjson paused "$paused_now" \
        --argjson hashes "$hashes_json" \
        '{ts:$ts,event:"unexpected_downloading",action:$action,count:$count,paused:$paused,hashes:$hashes}' \
        >> "$EVENTS_JSONL"
    fi
  fi

  top_states="stoppedUP=${STOPPED_UP},stoppedDL=${STOPPED_DL}"
  printf '%s checking=%s missing=%s moving=%s down=%s up=%s unexpected_down=%s paused_now=%s count_zero=%s count_partial=%s top=%s\n' \
    "$(date '+%F %T')" "$CHECKING" "$MISSING" "$MOVING" "$DOWN" "$UP" "${#UNEXPECTED_DOWN[@]}" "$paused_now" "$COUNT_ZERO" "$COUNT_PARTIAL" "$top_states"

  if [[ "$UNTIL_CLEAR" -eq 1 && "$CHECKING" -eq 0 && "$MOVING" -eq 0 && "$DOWN" -eq 0 ]]; then
    echo "done checking=0 moving=0 down=0"
    exit 0
  fi

  if [[ "$ONCE" -eq 1 ]]; then
    exit 0
  fi
  if [[ "$MAX_ITERATIONS" -gt 0 && "$iteration" -ge "$MAX_ITERATIONS" ]]; then
    echo "done max_iterations=${MAX_ITERATIONS}"
    exit 0
  fi

  sleep "$INTERVAL_S"
done
