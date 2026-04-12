#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.3"
LAST_UPDATED="2026-04-09T07:05:00-04:00"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT

usage() {
  cat <<'USAGE'
Usage:
  bin/qb-stoppeddl-apply-watch.sh [options] [-- <extra args for qb-stoppeddl-apply.py>]

What this does:
  - Watches drain reports in <bucket>/reports
  - Picks only completed final drain reports (not in-progress files)
  - Optionally requires at least one apply-eligible row
  - Runs qb-stoppeddl-apply.py against that report and current active-hashes.txt
  - Remembers the last applied drain report to avoid replaying stale work

Options:
  --bucket-dir PATH         Bucket directory (default: ~/.hashall/qb-stoppeddl-bucket)
  --poll N                  Seconds between checks in loop mode (default: 20)
  --once                    Run a single check/apply pass and exit
  --allow-class CSV         Allowed classes for eligible report check and apply (default: a,b,c)
  --min-ratio N             Min ratio for eligible report check and apply (default: 1.0)
  --no-apply                Dry-run mode (omit --apply to qb-stoppeddl-apply.py)
  --require-eligible        Require report to have >=1 apply-eligible row (default: enabled)
  --no-require-eligible     Allow completed reports even if they may apply zero rows
  --state-file PATH         Last-applied report marker file
  --completion-file PATH    Apply completion marker file
  --stop-file PATH          If this file exists, loop exits cleanly
  --lock-file PATH          Shared mutate lock path (default: <bucket>/MUTATE.lock)
  --lock-wait N             Seconds to wait for lock (0 = no wait, default: 0)
  -h, --help                Show help

Examples:
  # Loop forever, apply from the newest completed report with work
  bin/qb-stoppeddl-apply-watch.sh

  # One-shot
  bin/qb-stoppeddl-apply-watch.sh --once

  # Forward extra args to apply (after --)
  bin/qb-stoppeddl-apply-watch.sh -- --ops-mode auto --no-wait-recheck
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

BUCKET_DIR="${BUCKET_DIR:-${HOME}/.hashall/qb-stoppeddl-bucket}"
POLL="${POLL:-20}"
ALLOW_CLASS="${ALLOW_CLASS:-a,b,c}"
MIN_RATIO="${MIN_RATIO:-1.0}"
ONCE="false"
APPLY="true"
REQUIRE_ELIGIBLE="true"
STATE_FILE=""
STOP_FILE=""
COMPLETION_FILE=""
EXTRA_ARGS=()
LOCK_FILE=""
LOCK_WAIT="${LOCK_WAIT:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket-dir) BUCKET_DIR="${2:-}"; shift 2 ;;
    --poll) POLL="${2:-}"; shift 2 ;;
    --once) ONCE="true"; shift ;;
    --allow-class) ALLOW_CLASS="${2:-}"; shift 2 ;;
    --min-ratio) MIN_RATIO="${2:-}"; shift 2 ;;
    --no-apply) APPLY="false"; shift ;;
    --require-eligible) REQUIRE_ELIGIBLE="true"; shift ;;
    --no-require-eligible) REQUIRE_ELIGIBLE="false"; shift ;;
    --state-file) STATE_FILE="${2:-}"; shift 2 ;;
    --completion-file) COMPLETION_FILE="${2:-}"; shift 2 ;;
    --stop-file) STOP_FILE="${2:-}"; shift 2 ;;
    --lock-file) LOCK_FILE="${2:-}"; shift 2 ;;
    --lock-wait) LOCK_WAIT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$POLL" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Invalid --poll: $POLL" >&2
  exit 2
fi
if ! [[ "$MIN_RATIO" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Invalid --min-ratio: $MIN_RATIO" >&2
  exit 2
fi
if ! [[ "$LOCK_WAIT" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Invalid --lock-wait: $LOCK_WAIT" >&2
  exit 2
fi

BUCKET_DIR="$(python3 -c 'import os,sys; print(os.path.expanduser(sys.argv[1]))' "$BUCKET_DIR")"
REPORTS_DIR="${BUCKET_DIR}/reports"
ACTIVE_HASHES_FILE="${BUCKET_DIR}/active-hashes.txt"
STATE_FILE="${STATE_FILE:-${REPORTS_DIR}/apply-watch-last-report.txt}"
COMPLETION_FILE="${COMPLETION_FILE:-${REPORTS_DIR}/apply-last-completion.json}"
STOP_FILE="${STOP_FILE:-${BUCKET_DIR}/STOP_APPLY}"
LOCK_FILE="${LOCK_FILE:-${BUCKET_DIR}/MUTATE.lock}"

mkdir -p "$REPORTS_DIR"

ts() {
  date '+%Y-%m-%dT%H:%M:%S'
}

acquire_mutate_lock() {
  if [[ "$APPLY" != "true" ]]; then
    echo "status ts=$(ts) action=lock_skip reason=no_apply lock_file=${LOCK_FILE}"
    return 0
  fi
  if ! command -v flock >/dev/null 2>&1; then
    echo "ERROR: flock not found; cannot enforce mutate lock" >&2
    return 2
  fi
  exec 200>"$LOCK_FILE"
  if [[ "$LOCK_WAIT" == "0" ]]; then
    if ! flock -n 200; then
      echo "status ts=$(ts) action=stop reason=lock_busy lock_file=${LOCK_FILE}"
      return 1
    fi
  else
    if ! flock -w "$LOCK_WAIT" 200; then
      echo "status ts=$(ts) action=stop reason=lock_timeout lock_file=${LOCK_FILE} wait=${LOCK_WAIT}s"
      return 1
    fi
  fi
  echo "status ts=$(ts) action=lock_acquired lock_file=${LOCK_FILE}"
  return 0
}

if ! acquire_mutate_lock; then
  rc=$?
  if [[ "$rc" -eq 1 ]]; then
    exit 0
  fi
  exit "$rc"
fi

is_report_complete() {
  local report="$1"
  jq -e '
    (.progress_reason == "final")
    and (.summary.processed == .summary.selected)
  ' "$report" >/dev/null 2>&1
}

has_eligible_rows() {
  local report="$1"
  jq -e --arg classes "$ALLOW_CLASS" --argjson min_ratio "$MIN_RATIO" '
    def allow:
      ($classes | ascii_downcase | gsub("\\s+"; "") | split(",") | map(select(length > 0)));
    (
      [
        .entries[]?
        | (.classification // "" | ascii_downcase) as $c
        | select((allow | index($c)) != null)
        | select((.best_result.verified // false) == true)
        | select((.best_result.verify_ratio // 0.0) >= $min_ratio)
      ]
      | length
    ) > 0
  ' "$report" >/dev/null 2>&1
}

pick_latest_report() {
  local f
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    is_report_complete "$f" || continue
    if [[ "$REQUIRE_ELIGIBLE" == "true" ]]; then
      has_eligible_rows "$f" || continue
    fi
    printf '%s\n' "$f"
    return 0
  done < <(ls -1t "${REPORTS_DIR}"/drain-*.json 2>/dev/null || true)
  return 1
}

run_apply_once() {
  local report last cmd before_mtime after_mtime
  report="$(pick_latest_report || true)"
  if [[ -z "$report" ]]; then
    echo "status ts=$(ts) action=skip reason=no_completed_report"
    return 0
  fi

  last="$(cat "$STATE_FILE" 2>/dev/null || true)"
  if [[ -n "$last" && "$report" == "$last" ]]; then
    echo "status ts=$(ts) action=skip reason=already_applied report=${report}"
    return 0
  fi

  cmd=(
    python3
    bin/qb-stoppeddl-apply.py
    --bucket-dir "$BUCKET_DIR"
    --drain-report "$report"
    --hashes-file "$ACTIVE_HASHES_FILE"
    --allow-class "$ALLOW_CLASS"
    --min-ratio "$MIN_RATIO"
    --completion-file "$COMPLETION_FILE"
  )
  if [[ "$APPLY" == "true" ]]; then
    cmd+=(--apply)
  fi
  if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
    cmd+=("${EXTRA_ARGS[@]}")
  fi

  echo "start ts=$(ts) script=${SCRIPT_NAME} semver=${SEMVER} report=${report} apply=${APPLY}"
  before_mtime="$(stat -c %Y "$COMPLETION_FILE" 2>/dev/null || echo 0)"
  "${cmd[@]}"
  if [[ "$APPLY" == "true" ]]; then
    if [[ ! -f "$COMPLETION_FILE" ]]; then
      echo "status ts=$(ts) action=error reason=missing_completion_file completion_file=${COMPLETION_FILE}"
      return 1
    fi
    after_mtime="$(stat -c %Y "$COMPLETION_FILE" 2>/dev/null || echo 0)"
    if [[ "$after_mtime" -le "$before_mtime" ]]; then
      echo "status ts=$(ts) action=error reason=stale_completion_file completion_file=${COMPLETION_FILE}"
      return 1
    fi
    printf '%s\n' "$report" > "$STATE_FILE"
    echo "status ts=$(ts) action=done report=${report} state_file=${STATE_FILE} completion_file=${COMPLETION_FILE}"
  else
    echo "status ts=$(ts) action=done_dryrun report=${report} state_file=unchanged"
  fi
}

echo "start ts=$(ts) script=${SCRIPT_NAME} semver=${SEMVER} bucket_dir=${BUCKET_DIR} poll=${POLL}s once=${ONCE} require_eligible=${REQUIRE_ELIGIBLE} apply=${APPLY}"
echo "paths reports_dir=${REPORTS_DIR} active_hashes=${ACTIVE_HASHES_FILE} state_file=${STATE_FILE} completion_file=${COMPLETION_FILE} stop_file=${STOP_FILE} lock_file=${LOCK_FILE} lock_wait=${LOCK_WAIT}s"

while true; do
  if [[ -e "$STOP_FILE" ]]; then
    echo "status ts=$(ts) action=stop reason=stop_file_exists stop_file=${STOP_FILE}"
    exit 0
  fi

  if ! run_apply_once; then
    echo "status ts=$(ts) action=error reason=apply_failed"
  fi

  if [[ "$ONCE" == "true" ]]; then
    exit 0
  fi
  sleep "$POLL"
done
