#!/usr/bin/env bash
set -euo pipefail

PATH_CONTAINS="${PATH_CONTAINS:-cross-seed-link}"
LIMIT="${LIMIT:-10}"
WATCH_SECONDS="${WATCH_SECONDS:-120}"
WATCH_INTERVAL="${WATCH_INTERVAL:-5}"
LOG_DIR="${HOME}/.logs/hashall/pilot-normalization"
PYTHON_BIN="${PYTHON_BIN:-python}"
APPLY=0
LIST_ONLY=0
WATCH=0
HASH=""

usage() {
  cat <<'EOF'
Usage:
  scripts/pilot-normalization.sh [--list] [--limit N]
  scripts/pilot-normalization.sh --hash HASH [--watch]
  scripts/pilot-normalization.sh --hash HASH --apply [--watch] [--watch-seconds N] [--watch-interval N]

Safe wrapper for one-hash cross-seed-link -> cross-seed normalization.

Defaults:
  - list candidate status only
  - no filesystem or client mutations
  - only /pool/media candidates are considered safe

Options:
  --hash HASH             Show plan for a specific hash. Required for --apply.
  --apply                 Execute a single-hash normalization.
  --list                  List candidate hashes and status (default behavior).
  --limit N               Max candidates to show in list mode. Default: 10
  --watch                 Poll qB/RT after apply until RT leaves checking or timeout.
  --watch-seconds N       Watch timeout. Default: 120
  --watch-interval N      Poll interval. Default: 5
  --path-contains TEXT    Legacy path substring to audit. Default: cross-seed-link
  -h, --help              Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hash)
      HASH="${2:-}"
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    --limit)
      LIMIT="${2:-}"
      shift 2
      ;;
    --watch)
      WATCH=1
      shift
      ;;
    --watch-seconds)
      WATCH_SECONDS="${2:-}"
      shift 2
      ;;
    --watch-interval)
      WATCH_INTERVAL="${2:-}"
      shift 2
      ;;
    --path-contains)
      PATH_CONTAINS="${2:-}"
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

if [[ "$APPLY" -eq 1 && -z "$HASH" ]]; then
  echo "Refusing to apply without --hash." >&2
  exit 2
fi

if ! [[ "$LIMIT" =~ ^[0-9]+$ && "$WATCH_SECONDS" =~ ^[0-9]+$ && "$WATCH_INTERVAL" =~ ^[0-9]+$ ]]; then
  echo "--limit, --watch-seconds, and --watch-interval must be non-negative integers." >&2
  exit 2
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd git
require_cmd jq
require_cmd "$PYTHON_BIN"

verify_context() {
  local pwd_now branch root
  pwd_now="$(pwd)"
  branch="$(git branch --show-current)"
  root="$(git rev-parse --show-toplevel)"
  if [[ "$pwd_now" != *"/.agent/worktrees/"* ]]; then
    echo "Refusing to run outside a chatrap worktree: $pwd_now" >&2
    exit 2
  fi
  if [[ "$branch" != cr/* ]]; then
    echo "Refusing to run outside a cr/ branch: $branch" >&2
    exit 2
  fi
  echo "Preflight"
  echo "  root: $root"
  echo "  pwd: $pwd_now"
  echo "  branch: $branch"
}

ensure_clients_up() {
  local qb_ok rt_ok
  qb_ok="$(
    "$PYTHON_BIN" - <<'PY'
from hashall.qbittorrent import get_qbittorrent_client
try:
    qb = get_qbittorrent_client()
    rows = qb.get_torrents(category="cross-seed")
    print("ok" if rows is not None else "fail")
except Exception:
    print("fail")
PY
  )"
  rt_ok="$(
    "$PYTHON_BIN" - <<'PY'
from hashall.rtorrent import fetch_rt_status_rows
try:
    rows = fetch_rt_status_rows()
    print("ok" if rows is not None else "fail")
except Exception:
    print("fail")
PY
  )"
  echo "  clients: qb=$qb_ok rt=$rt_ok"
  if [[ "$qb_ok" != "ok" || "$rt_ok" != "ok" ]]; then
    echo "Client preflight failed: qb=$qb_ok rt=$rt_ok" >&2
    exit 1
  fi
}

cli_json() {
  "$PYTHON_BIN" -m hashall.cli "$@" --json-output | sed -n '/^{/,$p'
}

get_plan_json() {
  local hash="$1"
  cli_json payload normalize-cross-seed-link --hash "$hash"
}

get_audit_json() {
  cli_json rt session-audit --path-contains "$PATH_CONTAINS"
}

classify_plan() {
  local plan_json="$1"
  local ready qb_state rt_state qb_old_save issue_text
  ready="$(jq -r '.plan.ready' <<<"$plan_json")"
  qb_state="$(jq -r '.plan.qb_state' <<<"$plan_json")"
  rt_state="$(jq -r '.plan.rt_state' <<<"$plan_json")"
  qb_old_save="$(jq -r '.plan.qb_old_save_path' <<<"$plan_json")"
  issue_text="$(jq -r '.plan.issues | join(",")' <<<"$plan_json")"
  if [[ "$qb_old_save" == *"/cross-seed/"* && "$qb_old_save" != *"/cross-seed-link/"* ]]; then
    echo "skip:already_canonical"
    return
  fi
  if [[ "$qb_old_save" != /pool/media/* ]]; then
    echo "skip:not_pool_media"
    return
  fi
  case "${qb_state,,}" in
    stoppedup|stoppeddl) ;;
    *)
      echo "skip:qb_not_stopped:${qb_state:-unknown}"
      return
      ;;
  esac
  case "${rt_state,,}" in
    checking|checkup|checkpending|queueddl|metaerror|error)
      echo "skip:rt_busy:${rt_state:-unknown}"
      return
      ;;
  esac
  if [[ "$ready" != "true" ]]; then
    echo "skip:issues:${issue_text:-unknown}"
    return
  fi
  echo "safe"
}

print_candidate_table() {
  local audit_json="$1" shown=0
  echo "Candidates"
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    local hash dir exists plan_json status qb_old_save qb_new_save rt_state
    hash="$(jq -r '.torrent_hash' <<<"$row")"
    dir="$(jq -r '.directory' <<<"$row")"
    exists="$(jq -r '.path_exists' <<<"$row")"
    rt_state="$(jq -r '.state // ""' <<<"$row")"
    [[ "$exists" != "true" ]] && continue
    plan_json="$(get_plan_json "$hash")"
    status="$(classify_plan "$plan_json")"
    qb_old_save="$(jq -r '.plan.qb_old_save_path' <<<"$plan_json")"
    qb_new_save="$(jq -r '.plan.qb_new_save_path' <<<"$plan_json")"
    printf '  %-40s %-36s\n' "$hash" "$status"
    echo "    rt_dir: $dir"
    echo "    rt_state: $rt_state"
    echo "    qb_old: $qb_old_save"
    echo "    qb_new: $qb_new_save"
    shown=$((shown + 1))
    [[ "$shown" -ge "$LIMIT" ]] && break
  done < <(jq -c '.rows[]?' <<<"$audit_json")
  if [[ "$shown" -eq 0 ]]; then
    echo "  no candidates matched current filters"
  fi
}

print_hash_plan() {
  local hash="$1" plan_json status
  plan_json="$(get_plan_json "$hash")"
  status="$(classify_plan "$plan_json")"
  echo "Selected Hash"
  echo "  hash: $hash"
  echo "  status: $status"
  jq -r '
    .plan as $p |
    [
      "  qb_state: " + $p.qb_state,
      "  rt_state: " + $p.rt_state,
      "  qb_old_save_path: " + $p.qb_old_save_path,
      "  qb_new_save_path: " + $p.qb_new_save_path,
      "  qb_old_content_path: " + $p.qb_old_content_path,
      "  qb_new_content_path: " + $p.qb_new_content_path,
      "  rt_old_directory: " + $p.rt_old_directory,
      "  rt_new_directory: " + $p.rt_new_directory,
      "  rt_old_apply_directory: " + $p.rt_old_apply_directory,
      "  rt_new_apply_directory: " + $p.rt_new_apply_directory,
      "  source_exists: " + ($p.source_exists|tostring),
      "  target_exists: " + ($p.target_exists|tostring),
      "  same_filesystem: " + ($p.same_filesystem|tostring),
      "  issues: " + (($p.issues | join(",")) // "")
    ] | .[]
  ' <<<"$plan_json"
}

post_state_json() {
  local hash="$1"
  "$PYTHON_BIN" - "$hash" <<'PY'
import json
import sys
from hashall.qbittorrent import get_qbittorrent_client
from hashall.rtorrent import fetch_rt_status_rows

h = sys.argv[1].strip().lower()
qb = get_qbittorrent_client().get_torrent_info(h)
rt = None
for row in fetch_rt_status_rows():
    if (row.get("hash") or "").lower() == h:
        rt = row
        break

payload = {
    "qb": {
        "save_path": getattr(qb, "save_path", "") if qb else "",
        "content_path": getattr(qb, "content_path", "") if qb else "",
        "state": getattr(qb, "state", "") if qb else "",
    },
    "rt": rt or {},
}
print(json.dumps(payload))
PY
}

legacy_counts_json() {
  "$PYTHON_BIN" - "$PATH_CONTAINS" <<'PY'
import json
import sys
from hashall.qbittorrent import get_qbittorrent_client
from hashall.rtorrent import fetch_rt_status_rows

needle = sys.argv[1]
qb = get_qbittorrent_client()
qb_rows = qb.get_torrents() or []
qb_count = 0
for row in qb_rows:
    save_path = getattr(row, "save_path", "") or ""
    if needle in save_path:
        qb_count += 1

rt_count = 0
for row in fetch_rt_status_rows():
    directory = row.get("directory", "") or ""
    if needle in directory:
        rt_count += 1

print(json.dumps({"path_contains": needle, "qb": qb_count, "rt": rt_count}))
PY
}

print_legacy_counts() {
  local counts_json="$1"
  echo "Remaining Legacy Count"
  echo "  path_contains: $(jq -r '.path_contains' <<<"$counts_json")"
  echo "  qb: $(jq -r '.qb' <<<"$counts_json")"
  echo "  rt: $(jq -r '.rt' <<<"$counts_json")"
}

print_residue_check() {
  local plan_json="$1"
  local legacy_path legacy_parent
  legacy_path="$(jq -r '.plan.qb_old_content_path' <<<"$plan_json")"
  if [[ "$legacy_path" != *"/${PATH_CONTAINS}/"* ]]; then
    echo "Residue Check"
    echo "  legacy_content: not_applicable"
    echo "  reason: plan is already on canonical path"
    return
  fi
  legacy_parent="$(dirname "$legacy_path")"
  echo "Residue Check"
  if [[ -e "$legacy_path" ]]; then
    echo "  legacy_content: present"
    echo "  path: $legacy_path"
  else
    echo "  legacy_content: gone"
  fi
  if [[ -d "$legacy_parent" ]]; then
    if find "$legacy_parent" -mindepth 1 -maxdepth 1 | read -r _; then
      echo "  legacy_parent: non_empty"
      echo "  parent: $legacy_parent"
    else
      echo "  legacy_parent: empty"
      echo "  parent: $legacy_parent"
    fi
  else
    echo "  legacy_parent: gone"
  fi
}

watch_hash() {
  local hash="$1" expected_qb="$2" expected_rt="$3" deadline now state_json qb_path rt_path rt_state
  deadline=$(( $(date +%s) + WATCH_SECONDS ))
  echo "Watch"
  while true; do
    state_json="$(post_state_json "$hash")"
    qb_path="$(jq -r '.qb.save_path' <<<"$state_json")"
    rt_path="$(jq -r '.rt.directory // ""' <<<"$state_json")"
    rt_state="$(jq -r '.rt.state // ""' <<<"$state_json")"
    echo "  qb: $qb_path"
    echo "  rt: $rt_path [$rt_state]"
    if [[ "$qb_path" == "$expected_qb" && "$rt_path" == "$expected_rt" && "${rt_state,,}" != "checking" ]]; then
      echo "  verdict: success"
      return 0
    fi
    now="$(date +%s)"
    if (( now >= deadline )); then
      echo "  verdict: ambiguous_needs_review"
      return 1
    fi
    sleep "$WATCH_INTERVAL"
  done
}

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

verify_context
ensure_clients_up
echo "  log: $LOG_FILE"

if [[ "$LIST_ONLY" -eq 1 || ( "$APPLY" -eq 0 && -z "$HASH" ) ]]; then
  audit_json="$(get_audit_json)"
  print_candidate_table "$audit_json"
  exit 0
fi

plan_json="$(get_plan_json "$HASH")"
status="$(classify_plan "$plan_json")"
print_hash_plan "$HASH"

expected_qb="$(jq -r '.plan.qb_new_save_path' <<<"$plan_json")"
expected_rt="$(jq -r '.plan.rt_new_directory' <<<"$plan_json")"

if [[ "$APPLY" -eq 1 ]]; then
  if [[ "$status" != "safe" ]]; then
    echo "Refusing apply for non-safe candidate: $status" >&2
    exit 1
  fi

  echo "Apply"
  apply_json="$(cli_json payload normalize-cross-seed-link --hash "$HASH" --apply)"
  echo "$apply_json" | jq '.'

  expected_qb="$(jq -r '.result.qb_final_save_path // .plan.qb_new_save_path' <<<"$apply_json")"
  expected_rt="$(jq -r '.result.rt_final_directory // .plan.rt_new_directory' <<<"$apply_json")"
fi

echo "Post-Check"
post_state_json "$HASH" | jq '.'
print_residue_check "$plan_json"
print_legacy_counts "$(legacy_counts_json)"

if [[ "$WATCH" -eq 1 ]]; then
  watch_hash "$HASH" "$expected_qb" "$expected_rt"
fi
