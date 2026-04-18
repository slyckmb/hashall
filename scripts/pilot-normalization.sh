#!/usr/bin/env bash
set -euo pipefail

PATH_CONTAINS="${PATH_CONTAINS:-cross-seed-link}"
LIMIT="${LIMIT:-10}"
WATCH_SECONDS="${WATCH_SECONDS:-120}"
WATCH_INTERVAL="${WATCH_INTERVAL:-5}"
LOG_DIR="${HOME}/.logs/hashall/pilot-normalization"
PYTHON_BIN="${PYTHON_BIN:-python}"
QB_CACHE_MAX_AGE="${QB_CACHE_MAX_AGE:-20}"
QB_CACHE_WAIT_FRESH="${QB_CACHE_WAIT_FRESH:-5}"
RT_CACHE_MAX_AGE="${RT_CACHE_MAX_AGE:-30}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QB_CACHE_LIB="$REPO_ROOT/bin/lib/qb-cache.sh"
APPLY=0
LIST_ONLY=0
WATCH=0
PICK_SAFE=0
HASH=""

usage() {
  cat <<'EOF'
Usage:
  scripts/pilot-normalization.sh [--list] [--limit N]
  scripts/pilot-normalization.sh --pick-safe [--watch]
  scripts/pilot-normalization.sh --hash HASH [--watch]
  scripts/pilot-normalization.sh [--pick-safe] --apply [--watch] [--watch-seconds N] [--watch-interval N]

Safe wrapper for one-hash cross-seed-link -> cross-seed normalization.

Defaults:
  - list candidate status only
  - no filesystem or client mutations
  - only /pool/media candidates are considered safe
  - read-heavy qB/RT status uses the shared cache helpers where possible

Options:
  --hash HASH             Show plan for a specific hash. Required for --apply.
  --pick-safe            Auto-select the next safe hash from current candidates.
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
    --pick-safe)
      PICK_SAFE=1
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

if [[ ! -f "$QB_CACHE_LIB" ]]; then
  echo "Missing qB cache helper library: $QB_CACHE_LIB" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$QB_CACHE_LIB"

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
  local qb_ok rt_ok attempt max_attempts sleep_seconds qb_tmp rt_json rt_freshness
  max_attempts=4
  sleep_seconds=2
  for attempt in $(seq 1 "$max_attempts"); do
    qb_tmp="$(mktemp)"
    if qb_cache_snapshot > "$qb_tmp"; then
      qb_ok="$("$PYTHON_BIN" - "$qb_tmp" <<'PY'
import json
import sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    print("ok" if isinstance(rows, list) and len(rows) >= 0 else "fail")
except Exception:
    print("fail")
PY
)"
    else
      qb_ok="fail"
    fi
    rm -f "$qb_tmp"
    rt_json="$(
      "$PYTHON_BIN" - <<'PY'
import json
from hashall.rt_cache import load_rt_cache_snapshot
try:
    snap = load_rt_cache_snapshot(max_age_s=30.0)
    print(json.dumps({"freshness": snap.get("freshness"), "rows_total": snap.get("rows_total", 0)}))
except Exception as exc:
    print(json.dumps({"freshness": "error", "error": str(exc)}))
PY
    )"
    rt_freshness="$(jq -r '.freshness // "error"' <<<"$rt_json")"
    case "$rt_freshness" in
      fresh|stale|stale_error) rt_ok="ok" ;;
      *) rt_ok="fail" ;;
    esac
    echo "  cache_reads[$attempt/$max_attempts]: qb=$qb_ok rt=$rt_ok rt_freshness=$rt_freshness"
    if [[ "$qb_ok" == "ok" && "$rt_ok" == "ok" ]]; then
      return 0
    fi
    if [[ "$attempt" -lt "$max_attempts" ]]; then
      sleep "$sleep_seconds"
    fi
  done
  echo "Client preflight failed after $max_attempts attempts: qb=$qb_ok rt=$rt_ok" >&2
  exit 1
}

cli_json() {
  "$PYTHON_BIN" -m hashall.cli "$@" --json-output | sed -n '/^{/,$p'
}

qb_cache_snapshot() {
  local out_path
  out_path="$(mktemp)"
  qb_cache_fetch_torrents_info "$out_path" "$QB_CACHE_MAX_AGE" "$QB_CACHE_WAIT_FRESH" "$QB_CACHE_MAX_AGE" >/dev/null
  "$PYTHON_BIN" - "$out_path" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
start = text.find("[\n")
end = text.rfind("\n]")
if start < 0 or end < 0 or end < start:
    raise SystemExit(1)
print(text[start:end + 2], end="")
PY
  rm -f "$out_path"
}

rt_cache_snapshot() {
  "$PYTHON_BIN" - <<'PY'
import json
from hashall.rt_cache import load_rt_cache_snapshot
snap = load_rt_cache_snapshot(max_age_s=30.0)
print(json.dumps(snap))
PY
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
  local audit_json="$1" shown=0 rt_cache_json
  rt_cache_json="$(rt_cache_snapshot)"
  echo "Candidates"
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    local hash dir exists plan_json status qb_old_save qb_new_save rt_state
    hash="$(jq -r '.torrent_hash' <<<"$row")"
    dir="$(jq -r '.directory' <<<"$row")"
    exists="$(jq -r '.path_exists' <<<"$row")"
    rt_state="$(jq -r --arg hash "$hash" '.rows[]? | select(.hash == ($hash | ascii_downcase)) | .state' <<<"$rt_cache_json" | head -n1)"
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

selection_key() {
  local plan_json="$1"
  local qb_state rt_state qb_old_save rank
  qb_state="$(jq -r '.plan.qb_state' <<<"$plan_json")"
  rt_state="$(jq -r '.plan.rt_state' <<<"$plan_json")"
  qb_old_save="$(jq -r '.plan.qb_old_save_path' <<<"$plan_json")"
  case "${rt_state,,}" in
    stoppedup) rank="00" ;;
    stalledup) rank="01" ;;
    stoppeddl) rank="02" ;;
    stalleddl) rank="03" ;;
    *) rank="09" ;;
  esac
  printf '%s|%s|%s\n' "$rank" "${qb_state,,}" "$qb_old_save"
}

pick_safe_hash() {
  local audit_json="$1" best_hash="" best_key="" best_status="" best_plan=""
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    local hash exists plan_json status key
    hash="$(jq -r '.torrent_hash' <<<"$row")"
    exists="$(jq -r '.path_exists' <<<"$row")"
    [[ "$exists" != "true" ]] && continue
    plan_json="$(get_plan_json "$hash")"
    status="$(classify_plan "$plan_json")"
    [[ "$status" != "safe" ]] && continue
    key="$(selection_key "$plan_json")"
    if [[ -z "$best_key" || "$key" < "$best_key" ]]; then
      best_hash="$hash"
      best_key="$key"
      best_status="$status"
      best_plan="$plan_json"
    fi
  done < <(jq -c '.rows[]?' <<<"$audit_json")

  if [[ -z "$best_hash" ]]; then
    return 1
  fi

  echo "Auto-Pick"
  echo "  hash: $best_hash"
  echo "  status: $best_status"
  echo "  selection_key: $best_key"
  HASH="$best_hash"
  PICKED_PLAN_JSON="$best_plan"
  return 0
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
  local qb_tmp rt_tmp
  qb_tmp="$(mktemp)"
  rt_tmp="$(mktemp)"
  qb_cache_snapshot > "$qb_tmp"
  rt_cache_snapshot > "$rt_tmp"
  "$PYTHON_BIN" - "$hash" "$qb_tmp" "$rt_tmp" <<'PY'
import json
import sys
h = sys.argv[1].strip().lower()
with open(sys.argv[2], encoding="utf-8") as fh:
    qb_payload = json.load(fh)
with open(sys.argv[3], encoding="utf-8") as fh:
    rt_payload = json.load(fh)

qb = None
for row in qb_payload:
    if str(row.get("hash") or "").strip().lower() == h:
        qb = row
        break
rt = None
for row in rt_payload.get("rows", []):
    if (row.get("hash") or "").lower() == h:
        rt = row
        break

payload = {
    "qb": {
        "save_path": (qb or {}).get("save_path", ""),
        "content_path": (qb or {}).get("content_path", ""),
        "state": (qb or {}).get("state", ""),
    },
    "rt": rt or {},
    "cache": {
        "rt_freshness": rt_payload.get("freshness", ""),
        "rt_cache_age_s": rt_payload.get("cache_age_s"),
    },
}
print(json.dumps(payload))
PY
  rm -f "$qb_tmp" "$rt_tmp"
}

legacy_counts_json() {
  local qb_tmp rt_tmp
  qb_tmp="$(mktemp)"
  rt_tmp="$(mktemp)"
  qb_cache_snapshot > "$qb_tmp"
  rt_cache_snapshot > "$rt_tmp"
  "$PYTHON_BIN" - "$PATH_CONTAINS" "$qb_tmp" "$rt_tmp" <<'PY'
import json
import sys
needle = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as fh:
    qb_rows = json.load(fh)
with open(sys.argv[3], encoding="utf-8") as fh:
    rt_payload = json.load(fh)
qb_count = 0
for row in qb_rows:
    save_path = row.get("save_path", "") or ""
    if needle in save_path:
        qb_count += 1

rt_count = 0
for row in rt_payload.get("rows", []):
    directory = row.get("directory", "") or ""
    if needle in directory:
        rt_count += 1

print(json.dumps({
    "path_contains": needle,
    "qb": qb_count,
    "rt": rt_count,
    "rt_freshness": rt_payload.get("freshness", ""),
    "rt_cache_age_s": rt_payload.get("cache_age_s"),
}))
PY
  rm -f "$qb_tmp" "$rt_tmp"
}

print_legacy_counts() {
  local counts_json="$1"
  echo "Remaining Legacy Count"
  echo "  path_contains: $(jq -r '.path_contains' <<<"$counts_json")"
  echo "  qb: $(jq -r '.qb' <<<"$counts_json")"
  echo "  rt: $(jq -r '.rt' <<<"$counts_json")"
  echo "  rt_freshness: $(jq -r '.rt_freshness // ""' <<<"$counts_json")"
  echo "  rt_cache_age_s: $(jq -r '.rt_cache_age_s // ""' <<<"$counts_json")"
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

audit_json="$(get_audit_json)"

if [[ "$PICK_SAFE" -eq 1 || ( "$APPLY" -eq 1 && -z "$HASH" ) ]]; then
  if ! pick_safe_hash "$audit_json"; then
    echo "No safe candidate is available for auto-pick." >&2
    exit 1
  fi
fi

if [[ "$LIST_ONLY" -eq 1 || ( "$APPLY" -eq 0 && -z "$HASH" && "$PICK_SAFE" -eq 0 ) ]]; then
  print_candidate_table "$audit_json"
  exit 0
fi

plan_json="${PICKED_PLAN_JSON:-$(get_plan_json "$HASH")}"
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
