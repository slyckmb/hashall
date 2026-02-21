#!/usr/bin/env bash
set -euo pipefail

QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
INTERVAL_S=15
ONCE=0
UNTIL_CLEAR=0

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--interval <seconds>] [--once] [--until-clear]

Watches qB torrent state counts (checking/missing/moving/down/up).
Env: QBIT_URL, QBIT_USER, QBIT_PASS
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

COOKIE_FILE="$(mktemp)"
trap 'rm -f "$COOKIE_FILE"' EXIT

while true; do
  curl -fsS -c "$COOKIE_FILE" \
    --data-urlencode "username=${QBIT_USER}" \
    --data-urlencode "password=${QBIT_PASS}" \
    "${QBIT_URL}/api/v2/auth/login" >/dev/null

  TORRENTS_JSON="$(curl -fsS -b "$COOKIE_FILE" "${QBIT_URL}/api/v2/torrents/info")"

  read -r CHECKING MISSING MOVING DOWN UP TOP_STATES <<<"$(jq -r '
    [
      ([.[] | (.state // "" | ascii_downcase) | select(startswith("checking"))] | length),
      ([.[] | select((.state // "") == "missingFiles")] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "moving")] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "downloading" or (.state // "" | ascii_downcase) == "stalleddl")] | length),
      ([.[] | select((.state // "" | ascii_downcase) == "uploading" or (.state // "" | ascii_downcase) == "stalledup")] | length),
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

  printf '%s checking=%s missing=%s moving=%s down=%s up=%s top=%s\n' \
    "$(date '+%F %T')" "$CHECKING" "$MISSING" "$MOVING" "$DOWN" "$UP" "$TOP_STATES"

  if [[ "$UNTIL_CLEAR" -eq 1 && "$CHECKING" -eq 0 ]]; then
    echo "done checking=0"
    exit 0
  fi

  if [[ "$ONCE" -eq 1 ]]; then
    exit 0
  fi

  sleep "$INTERVAL_S"
done
