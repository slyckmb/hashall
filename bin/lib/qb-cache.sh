#!/usr/bin/env bash

qb_cache_agent_path() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  printf '%s\n' "${QBIT_CACHE_AGENT:-$script_dir/qb-cache-agent.py}"
}

qb_cache_fetch_torrents_info() {
  local out_path="${1:-}"
  local max_age="${2:-${QB_CACHE_MAX_AGE:-15}}"
  local wait_fresh="${3:-${QB_CACHE_WAIT_FRESH:-5}}"
  local requested_interval="${4:-$max_age}"
  local agent
  local qbit_url
  local qbit_user
  local qbit_pass
  local client_id

  agent="$(qb_cache_agent_path)"
  if [[ ! -f "$agent" ]]; then
    echo "qb_cache_fetch_torrents_info: cache agent not found: $agent" >&2
    return 1
  fi

  qbit_url="${QB_URL:-${QBIT_URL:-http://localhost:9003}}"
  qbit_user="${QB_USER:-${QBITTORRENTAPI_USERNAME:-admin}}"
  qbit_pass="${QB_PASS:-${QBITTORRENTAPI_PASSWORD:-adminpass}}"
  client_id="${QB_CACHE_CLIENT_ID:-$(basename "$0"):$$}"

  if [[ -n "$out_path" ]]; then
    QBIT_URL="$qbit_url" QBIT_USER="$qbit_user" QBIT_PASS="$qbit_pass" \
      python3 "$agent" \
        --max-age "$max_age" \
        --wait-fresh "$wait_fresh" \
        --requested-interval "$requested_interval" \
        --client-id "$client_id" \
        --ensure-daemon \
        > "$out_path"
  else
    QBIT_URL="$qbit_url" QBIT_USER="$qbit_user" QBIT_PASS="$qbit_pass" \
      python3 "$agent" \
        --max-age "$max_age" \
        --wait-fresh "$wait_fresh" \
        --requested-interval "$requested_interval" \
        --client-id "$client_id" \
        --ensure-daemon
  fi
}
