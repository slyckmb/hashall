#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-stage0.sh [--dryrun|--apply] [--resume 0|1]

Description:
  Move completed qBittorrent items with save_path under /pool/data/*
  into /pool/data/seeds/* while preserving the relative path.

Modes:
  --dryrun   Plan only (default)
  --apply    Pause -> setLocation -> poll save_path

Options:
  --resume   Resume torrents after relocation (default: 0)

Environment:
  QBIT_URL   qB base URL (default: http://localhost:9003)
  QBIT_USER  qB username (default: admin)
  QBIT_PASS  qB password (default: adminpass)
USAGE
}

MODE="dryrun"
RESUME_AFTER_RELOCATE="${HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE:-0}"
while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --dryrun)
      MODE="dryrun"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --resume)
      RESUME_AFTER_RELOCATE="${2:-}"
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
if [[ "$RESUME_AFTER_RELOCATE" != "0" && "$RESUME_AFTER_RELOCATE" != "1" ]]; then
  echo "Invalid --resume value: $RESUME_AFTER_RELOCATE" >&2
  exit 2
fi

for bin in curl jq; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Missing required dependency: $bin" >&2
    exit 1
  fi
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

stamp="$(date +%Y%m%d-%H%M%S)"
log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
log_file="${log_dir}/stage0-${stamp}.log"
exec > >(tee -a "$log_file") 2>&1

QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
QBIT_URL="${QBIT_URL%/}"

SOURCE_ROOT="/pool/data"
TARGET_ROOT="/pool/data/seeds"
POLL_INTERVAL=2
HEARTBEAT_INTERVAL=5
STUCK_TIMEOUT=60

COOKIE_JAR="$(mktemp "${TMPDIR:-/tmp}/rehome-stage0-cookie.XXXXXX")"
cleanup() {
  rm -f "$COOKIE_JAR"
}
trap cleanup EXIT

normalize_path() {
  local path="$1"
  while [[ "$path" == */ && "$path" != "/" ]]; do
    path="${path%/}"
  done
  printf '%s' "$path"
}

nearest_existing_path() {
  local path
  path="$(normalize_path "$1")"
  while [[ ! -e "$path" && "$path" != "/" ]]; do
    path="$(dirname "$path")"
  done
  printf '%s' "$path"
}

check_move_permissions() {
  local from="$1"
  local to="$2"
  local target_probe

  # Only enforce local FS checks when source path is locally visible.
  if [[ ! -e "$from" ]]; then
    return 0
  fi

  if [[ ! -w "$from" ]]; then
    printf 'source_not_writable:%s' "$from"
    return 1
  fi

  target_probe="$(nearest_existing_path "$to")"
  if [[ -d "$target_probe" && ! -w "$target_probe" ]]; then
    printf 'target_parent_not_writable:%s' "$target_probe"
    return 1
  fi

  return 0
}

target_for_source() {
  local from
  local rel
  from="$(normalize_path "$1")"

  if [[ "$from" == "$TARGET_ROOT" || "$from" == "$TARGET_ROOT/"* ]]; then
    return 1
  fi
  if [[ "$from" == "$SOURCE_ROOT" ]]; then
    printf '%s' "$TARGET_ROOT"
    return 0
  fi
  if [[ "$from" != "$SOURCE_ROOT/"* ]]; then
    return 1
  fi

  rel="${from#${SOURCE_ROOT}/}"
  printf '%s/%s' "$TARGET_ROOT" "$rel"
}

qb_login() {
  local resp
  resp="$(
    curl -fsS \
      -c "$COOKIE_JAR" \
      --data-urlencode "username=${QBIT_USER}" \
      --data-urlencode "password=${QBIT_PASS}" \
      "${QBIT_URL}/api/v2/auth/login"
  )" || return 1
  [[ "$resp" == "Ok."* ]]
}

qb_get() {
  local endpoint="$1"
  curl -fsS -b "$COOKIE_JAR" -c "$COOKIE_JAR" "${QBIT_URL}${endpoint}"
}

qb_post_code() {
  local endpoint="$1"
  shift
  curl -sS -o /dev/null -w '%{http_code}' \
    -b "$COOKIE_JAR" \
    -c "$COOKIE_JAR" \
    -X POST "${QBIT_URL}${endpoint}" \
    "$@"
}

qb_post_ok() {
  local endpoint="$1"
  shift
  local code
  code="$(qb_post_code "$endpoint" "$@")" || return 1
  [[ "$code" == 2* ]]
}

qb_pause() {
  local hash="$1"
  local code
  code="$(qb_post_code "/api/v2/torrents/pause" --data-urlencode "hashes=${hash}")" || return 1
  if [[ "$code" == "404" ]]; then
    code="$(qb_post_code "/api/v2/torrents/stop" --data-urlencode "hashes=${hash}")" || return 1
  fi
  [[ "$code" == 2* ]]
}

qb_resume() {
  local hash="$1"
  local code
  code="$(qb_post_code "/api/v2/torrents/resume" --data-urlencode "hashes=${hash}")" || return 1
  if [[ "$code" == "404" ]]; then
    code="$(qb_post_code "/api/v2/torrents/start" --data-urlencode "hashes=${hash}")" || return 1
  fi
  [[ "$code" == 2* ]]
}

collect_candidates() {
  local json
  json="$(qb_get "/api/v2/torrents/info")" || return 1
  jq -r '
    .[]
    | select((.progress // 0) >= 1)
    | .hash as $hash
    | (.save_path // "") as $save
    | select($save | startswith("/pool/data/"))
    | select(($save == "/pool/data/seeds" or ($save | startswith("/pool/data/seeds/"))) | not)
    | select($hash != "")
    | [$hash, $save]
    | @tsv
  ' <<<"$json"
}

torrent_save_path_for_hash() {
  local hash="$1"
  local json
  json="$(qb_get "/api/v2/torrents/info?hashes=${hash}")" || return 1
  jq -r 'if length > 0 then (.[] | .save_path // "") else "" end' <<<"$json" | head -n 1
}

POLL_WAITED=0
poll_until_location() {
  local hash="$1"
  local target="$2"
  local idx="$3"
  local total="$4"
  local start now elapsed next_heartbeat
  local current current_norm target_norm

  target_norm="$(normalize_path "$target")"
  start="$(date +%s)"
  next_heartbeat="$HEARTBEAT_INTERVAL"
  POLL_WAITED=0

  while true; do
    current="$(torrent_save_path_for_hash "$hash")" || return 2
    current_norm="$(normalize_path "$current")"
    now="$(date +%s)"
    elapsed=$((now - start))
    POLL_WAITED="$elapsed"

    if [[ "$current_norm" == "$target_norm" ]]; then
      return 0
    fi

    if (( elapsed >= STUCK_TIMEOUT )); then
      return 1
    fi

    if (( elapsed >= next_heartbeat )); then
      printf 'heartbeat %s/%s %s waiting=%ss current=%s target=%s\n' \
        "$idx" "$total" "$hash" "$elapsed" "$current_norm" "$target_norm"
      next_heartbeat=$((next_heartbeat + HEARTBEAT_INTERVAL))
    fi

    sleep "$POLL_INTERVAL"
  done
}

printf 'stage0 mode=%s resume=%s qbit_url=%s log=%s\n' "$MODE" "$RESUME_AFTER_RELOCATE" "$QBIT_URL" "$log_file"

if ! qb_login; then
  echo "Failed to authenticate to qBittorrent at ${QBIT_URL}" >&2
  exit 1
fi

candidates_raw="$(collect_candidates)" || {
  echo "Failed to fetch candidate torrents." >&2
  exit 1
}

candidates=()
if [[ -n "$candidates_raw" ]]; then
  mapfile -t candidates <<<"$candidates_raw"
fi

total="${#candidates[@]}"
printf 'candidate_total=%s\n' "$total"

if (( total == 0 )); then
  echo "No completed torrents under /pool/data/ requiring normalization."
  exit 0
fi

ok_count=0
error_count=0
stuck_count=0

for ((i = 0; i < total; i++)); do
  idx=$((i + 1))
  row="${candidates[$i]}"
  IFS=$'\t' read -r hash from_path <<<"$row"

  from_path="$(normalize_path "$from_path")"
  if ! to_path="$(target_for_source "$from_path")"; then
    printf '%s/%s %s %s->(skip) 0s/error\n' "$idx" "$total" "$hash" "$from_path"
    error_count=$((error_count + 1))
    continue
  fi
  to_path="$(normalize_path "$to_path")"

  if [[ "$MODE" == "dryrun" ]]; then
    printf '%s/%s %s %s->%s 0s/dryrun\n' "$idx" "$total" "$hash" "$from_path" "$to_path"
    ok_count=$((ok_count + 1))
    continue
  fi

  perm_issue=""
  if ! perm_issue="$(check_move_permissions "$from_path" "$to_path")"; then
    printf '%s/%s %s %s->%s 0s/blocked_perm(%s)\n' \
      "$idx" "$total" "$hash" "$from_path" "$to_path" "$perm_issue"
    error_count=$((error_count + 1))
    continue
  fi

  waited=0
  result="ok"
  paused=0

  if ! qb_pause "$hash"; then
    result="error"
  else
    paused=1

    if ! qb_post_ok "/api/v2/torrents/setLocation" \
      --data-urlencode "hashes=${hash}" \
      --data-urlencode "location=${to_path}"; then
      result="error"
    elif poll_until_location "$hash" "$to_path" "$idx" "$total"; then
      waited="$POLL_WAITED"
    else
      poll_rc="$?"
      waited="$POLL_WAITED"
      if [[ "$poll_rc" -eq 1 ]]; then
        result="stuck"
      else
        result="error"
      fi
    fi
  fi

  if (( paused == 1 )) && [[ "$RESUME_AFTER_RELOCATE" == "1" ]]; then
    if ! qb_resume "$hash"; then
      if [[ "$result" == "ok" ]]; then
        result="error"
      fi
    fi
  fi

  printf '%s/%s %s %s->%s %ss/%s\n' \
    "$idx" "$total" "$hash" "$from_path" "$to_path" "$waited" "$result"

  if [[ "$result" == "ok" ]]; then
    ok_count=$((ok_count + 1))
  elif [[ "$result" == "stuck" ]]; then
    stuck_count=$((stuck_count + 1))
    error_count=$((error_count + 1))
  else
    error_count=$((error_count + 1))
  fi
done

printf 'summary mode=%s total=%s ok=%s errors=%s stuck=%s log=%s\n' \
  "$MODE" "$total" "$ok_count" "$error_count" "$stuck_count" "$log_file"

if (( error_count > 0 )); then
  exit 1
fi
