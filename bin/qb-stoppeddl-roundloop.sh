#!/usr/bin/env bash
set -euo pipefail

SEMVER="0.1.3"
SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<'USAGE'
Usage:
  bin/qb-stoppeddl-roundloop.sh [options]

Round workflow:
  1) Refresh stoppedDL bucket snapshot
  2) Run one drain pass
  3) Apply from drain-latest using current active-hashes filter
  4) Wait until qB global checking* count reaches 0
  5) Refresh bucket and repeat

Defaults are set for unattended operation.

Options:
  --bucket-dir PATH           Bucket directory (default: /tmp/qb-stoppeddl-bucket-live)
  --states CSV                Bucket states (default: stoppedDL)
  --max-rounds N              Max rounds (0 = unlimited, default: 0)
  --max-no-progress N         Stop after N rounds with no stoppedDL reduction (default: 3)
  --round-sleep N             Sleep seconds between rounds (default: 5)
  --checking-poll N           Poll seconds while waiting for checking*=0 (default: 20)
  --checking-timeout N        Max seconds to wait for checking*=0 (0 = no timeout, default: 7200)
  --stop-file PATH            Stop loop when this file exists (default: <bucket>/STOP_ROUNDLOOP)
  --clear-stop-file           Remove stale stop file at startup (default: enabled)
  --no-clear-stop-file        Respect existing stop file and exit immediately
  --allow-class CSV           Apply classes (default: a,b,c)
  --min-ratio N               Apply min ratio (default: 1.0)
  --ops-mode MODE             Apply ops mode: auto|fastresume|api (default: auto)
  --dry-run                   Do not pass --apply to qb-stoppeddl-apply.py
  --drain-limit N             Drain --limit (default: 0)
  --max-candidates N          Drain --max-candidates (default: 1)
  --verify-timeout N          Drain per-candidate verify timeout seconds (default: 2400)
  --verify-poll N             Drain verify poll seconds (default: 1)
  --show-verify-progress      Pass --show-verify-progress to drain
  --apply-poll N              Apply poll interval (default: 5)
  --apply-timeout N           Apply per-hash timeout (default: 2400)
  --completion-file PATH      Apply completion marker path (default: <bucket>/reports/apply-last-completion.json)
  --wait-recheck              Pass --wait-recheck to apply (default: no-wait)
  -h, --help                  Show help
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

BUCKET_DIR="${BUCKET_DIR:-/tmp/qb-stoppeddl-bucket-live}"
STATES="${STATES:-stoppedDL}"
MAX_ROUNDS="${MAX_ROUNDS:-0}"
MAX_NO_PROGRESS="${MAX_NO_PROGRESS:-3}"
ROUND_SLEEP="${ROUND_SLEEP:-5}"
CHECKING_POLL="${CHECKING_POLL:-20}"
CHECKING_TIMEOUT="${CHECKING_TIMEOUT:-7200}"
ALLOW_CLASS="${ALLOW_CLASS:-a,b,c}"
MIN_RATIO="${MIN_RATIO:-1.0}"
OPS_MODE="${OPS_MODE:-auto}"
APPLY_MODE="apply"
STOP_FILE=""

DRAIN_LIMIT="${DRAIN_LIMIT:-0}"
MAX_CANDIDATES="${MAX_CANDIDATES:-1}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-2400}"
VERIFY_POLL="${VERIFY_POLL:-1}"
SHOW_VERIFY_PROGRESS="false"

APPLY_POLL="${APPLY_POLL:-5}"
APPLY_TIMEOUT="${APPLY_TIMEOUT:-2400}"
WAIT_RECHECK="false"
COMPLETION_FILE=""
CLEAR_STOP_FILE="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket-dir) BUCKET_DIR="${2:-}"; shift 2 ;;
    --states) STATES="${2:-}"; shift 2 ;;
    --max-rounds) MAX_ROUNDS="${2:-}"; shift 2 ;;
    --max-no-progress) MAX_NO_PROGRESS="${2:-}"; shift 2 ;;
    --round-sleep) ROUND_SLEEP="${2:-}"; shift 2 ;;
    --checking-poll) CHECKING_POLL="${2:-}"; shift 2 ;;
    --checking-timeout) CHECKING_TIMEOUT="${2:-}"; shift 2 ;;
    --stop-file) STOP_FILE="${2:-}"; shift 2 ;;
    --clear-stop-file) CLEAR_STOP_FILE="true"; shift ;;
    --no-clear-stop-file) CLEAR_STOP_FILE="false"; shift ;;
    --allow-class) ALLOW_CLASS="${2:-}"; shift 2 ;;
    --min-ratio) MIN_RATIO="${2:-}"; shift 2 ;;
    --ops-mode) OPS_MODE="${2:-}"; shift 2 ;;
    --dry-run) APPLY_MODE="dryrun" ; shift ;;
    --drain-limit) DRAIN_LIMIT="${2:-}"; shift 2 ;;
    --max-candidates) MAX_CANDIDATES="${2:-}"; shift 2 ;;
    --verify-timeout) VERIFY_TIMEOUT="${2:-}"; shift 2 ;;
    --verify-poll) VERIFY_POLL="${2:-}"; shift 2 ;;
    --show-verify-progress) SHOW_VERIFY_PROGRESS="true"; shift ;;
    --apply-poll) APPLY_POLL="${2:-}"; shift 2 ;;
    --apply-timeout) APPLY_TIMEOUT="${2:-}"; shift 2 ;;
    --completion-file) COMPLETION_FILE="${2:-}"; shift 2 ;;
    --wait-recheck) WAIT_RECHECK="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for n in \
  "$MAX_ROUNDS" "$MAX_NO_PROGRESS" "$ROUND_SLEEP" \
  "$CHECKING_POLL" "$CHECKING_TIMEOUT" \
  "$DRAIN_LIMIT" "$MAX_CANDIDATES" "$VERIFY_TIMEOUT" "$VERIFY_POLL" \
  "$APPLY_POLL" "$APPLY_TIMEOUT"; do
  if ! [[ "$n" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
done
if [[ "$OPS_MODE" != "auto" && "$OPS_MODE" != "fastresume" && "$OPS_MODE" != "api" ]]; then
  echo "Invalid --ops-mode: $OPS_MODE (expected auto|fastresume|api)" >&2
  exit 2
fi

ts() {
  date '+%Y-%m-%dT%H:%M:%S'
}

BUCKET_DIR="$(python3 -c 'import os,sys; print(os.path.expanduser(sys.argv[1]))' "$BUCKET_DIR")"
REPORTS_DIR="${BUCKET_DIR}/reports"
ACTIVE_HASHES_FILE="${BUCKET_DIR}/active-hashes.txt"
STOP_FILE="${STOP_FILE:-${BUCKET_DIR}/STOP_ROUNDLOOP}"
COMPLETION_FILE="${COMPLETION_FILE:-${REPORTS_DIR}/apply-last-completion.json}"
mkdir -p "$REPORTS_DIR"

if [[ "$CLEAR_STOP_FILE" == "true" && -e "$STOP_FILE" ]]; then
  rm -f "$STOP_FILE"
  echo "status ts=$(ts) action=startup_clear_stop_file stop_file=${STOP_FILE}"
fi

get_bucket_count() {
  if [[ ! -f "$ACTIVE_HASHES_FILE" ]]; then
    echo 0
    return 0
  fi
  wc -l < "$ACTIVE_HASHES_FILE" | tr -d '[:space:]'
}

get_qb_checking_count() {
  python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
if not qb.test_connection() or not qb.login():
    print(-1)
    raise SystemExit(0)
rows = qb.get_torrents()
states = {"checkingdl", "checkingup", "checkingresumedata"}
print(sum(1 for r in rows if str(r.state or "").lower() in states))
PY
}

wait_checking_zero() {
  local started now elapsed checking
  started="$(date +%s)"
  while true; do
    if [[ -e "$STOP_FILE" ]]; then
      echo "status ts=$(ts) action=stop reason=stop_file_exists stop_file=${STOP_FILE}"
      exit 0
    fi
    checking="$(get_qb_checking_count || echo -1)"
    if [[ "$checking" == "0" ]]; then
      echo "status ts=$(ts) checking=0 gate=passed"
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - started))
    if [[ "$CHECKING_TIMEOUT" != "0" && "$elapsed" -ge "${CHECKING_TIMEOUT%.*}" ]]; then
      echo "status ts=$(ts) checking=${checking} gate=timeout elapsed=${elapsed}s"
      return 1
    fi
    if [[ "$checking" == "-1" ]]; then
      echo "status ts=$(ts) checking=unknown qb=offline elapsed=${elapsed}s"
    else
      echo "status ts=$(ts) checking=${checking} gate=waiting elapsed=${elapsed}s"
    fi
    sleep "$CHECKING_POLL"
  done
}

is_drain_final() {
  local report="$1"
  jq -e '
    (.progress_reason == "final")
    and (.summary.processed == .summary.selected)
  ' "$report" >/dev/null 2>&1
}

eligible_in_report() {
  local report="$1"
  jq -r --arg classes "$ALLOW_CLASS" --argjson min_ratio "$MIN_RATIO" '
    def allow:
      ($classes | ascii_downcase | gsub("\\s+"; "") | split(",") | map(select(length > 0)));
    [
      .entries[]?
      | (.classification // "" | ascii_downcase) as $c
      | select((allow | index($c)) != null)
      | select((.best_result.verified // false) == true)
      | select((.best_result.verify_ratio // 0.0) >= $min_ratio)
    ] | length
  ' "$report" 2>/dev/null || echo 0
}

run_bucket_refresh() {
  python3 bin/qb-stoppeddl-bucket.py \
    --bucket-dir "$BUCKET_DIR" \
    --states "$STATES" \
    --prune-absent
}

run_bucket_resync() {
  python3 bin/qb-stoppeddl-bucket.py \
    --bucket-dir "$BUCKET_DIR" \
    --states "$STATES" \
    --no-export-torrents \
    --prune-absent
}

run_drain_once() {
  local cmd
  cmd=(
    python3
    bin/qb-stoppeddl-drain.py
    --bucket-dir "$BUCKET_DIR"
    --limit "$DRAIN_LIMIT"
    --max-candidates "$MAX_CANDIDATES"
    --verify-timeout "$VERIFY_TIMEOUT"
    --verify-poll "$VERIFY_POLL"
  )
  if [[ "$SHOW_VERIFY_PROGRESS" == "true" ]]; then
    cmd+=(--show-verify-progress)
  fi
  "${cmd[@]}"
}

run_apply_once() {
  local drain_report cmd eligible before_mtime after_mtime
  drain_report="${REPORTS_DIR}/drain-latest.json"
  if [[ ! -f "$drain_report" ]]; then
    echo "status ts=$(ts) action=skip_apply reason=no_drain_latest"
    return 0
  fi
  if ! is_drain_final "$drain_report"; then
    echo "status ts=$(ts) action=skip_apply reason=drain_not_final report=${drain_report}"
    return 0
  fi

  eligible="$(eligible_in_report "$drain_report")"
  echo "status ts=$(ts) drain_eligible=${eligible} report=${drain_report}"
  if [[ "${eligible}" == "0" ]]; then
    echo "status ts=$(ts) action=skip_apply reason=no_eligible_rows"
    return 0
  fi

  cmd=(
    python3
    bin/qb-stoppeddl-apply.py
    --bucket-dir "$BUCKET_DIR"
    --drain-report "$drain_report"
    --hashes-file "$ACTIVE_HASHES_FILE"
    --allow-class "$ALLOW_CLASS"
    --min-ratio "$MIN_RATIO"
    --ops-mode "$OPS_MODE"
    --poll "$APPLY_POLL"
    --timeout "$APPLY_TIMEOUT"
    --completion-file "$COMPLETION_FILE"
  )
  if [[ "$WAIT_RECHECK" == "true" ]]; then
    cmd+=(--wait-recheck)
  fi
  if [[ "$APPLY_MODE" == "apply" ]]; then
    cmd+=(--apply)
  fi

  before_mtime="$(stat -c %Y "$COMPLETION_FILE" 2>/dev/null || echo 0)"
  "${cmd[@]}"
  if [[ ! -f "$COMPLETION_FILE" ]]; then
    echo "status ts=$(ts) action=stop reason=missing_completion_file completion_file=${COMPLETION_FILE}"
    return 1
  fi
  after_mtime="$(stat -c %Y "$COMPLETION_FILE" 2>/dev/null || echo 0)"
  if [[ "$after_mtime" -le "$before_mtime" ]]; then
    echo "status ts=$(ts) action=stop reason=stale_completion_file completion_file=${COMPLETION_FILE}"
    return 1
  fi
}

echo "start ts=$(ts) script=${SCRIPT_NAME} semver=${SEMVER} bucket_dir=${BUCKET_DIR} states=${STATES}"
echo "config max_rounds=${MAX_ROUNDS} max_no_progress=${MAX_NO_PROGRESS} round_sleep=${ROUND_SLEEP}s checking_poll=${CHECKING_POLL}s checking_timeout=${CHECKING_TIMEOUT}s"
echo "config drain_limit=${DRAIN_LIMIT} max_candidates=${MAX_CANDIDATES} verify_timeout=${VERIFY_TIMEOUT}s verify_poll=${VERIFY_POLL}s show_verify_progress=${SHOW_VERIFY_PROGRESS}"
echo "config apply_mode=${APPLY_MODE} allow_class=${ALLOW_CLASS} min_ratio=${MIN_RATIO} ops_mode=${OPS_MODE} apply_poll=${APPLY_POLL}s apply_timeout=${APPLY_TIMEOUT}s wait_recheck=${WAIT_RECHECK}"
echo "paths reports_dir=${REPORTS_DIR} active_hashes=${ACTIVE_HASHES_FILE} completion_file=${COMPLETION_FILE} stop_file=${STOP_FILE} clear_stop_file=${CLEAR_STOP_FILE}"

round=0
no_progress=0

while true; do
  if [[ -e "$STOP_FILE" ]]; then
    echo "status ts=$(ts) action=stop reason=stop_file_exists stop_file=${STOP_FILE}"
    exit 0
  fi

  round=$((round + 1))
  if [[ "$MAX_ROUNDS" != "0" && "$round" -gt "${MAX_ROUNDS%.*}" ]]; then
    echo "status ts=$(ts) action=stop reason=max_rounds_reached round=${round}"
    exit 0
  fi

  echo "round ts=$(ts) num=${round} phase=bucket_refresh"
  run_bucket_refresh
  before="$(get_bucket_count)"
  echo "round ts=$(ts) num=${round} stoppedDL_before=${before}"
  if [[ "$before" == "0" ]]; then
    echo "status ts=$(ts) action=stop reason=bucket_empty round=${round}"
    exit 0
  fi

  echo "round ts=$(ts) num=${round} phase=drain"
  run_drain_once

  echo "round ts=$(ts) num=${round} phase=apply"
  run_apply_once

  echo "round ts=$(ts) num=${round} phase=wait_checking_zero"
  if ! wait_checking_zero; then
    echo "status ts=$(ts) action=stop reason=checking_timeout round=${round}"
    exit 3
  fi

  echo "round ts=$(ts) num=${round} phase=bucket_resync"
  run_bucket_resync
  after="$(get_bucket_count)"
  echo "round ts=$(ts) num=${round} stoppedDL_after=${after}"

  if [[ "${after}" -lt "${before}" ]]; then
    no_progress=0
  else
    no_progress=$((no_progress + 1))
  fi
  echo "round ts=$(ts) num=${round} progress before=${before} after=${after} no_progress=${no_progress}/${MAX_NO_PROGRESS}"

  if [[ "$MAX_NO_PROGRESS" != "0" && "$no_progress" -ge "${MAX_NO_PROGRESS%.*}" ]]; then
    echo "status ts=$(ts) action=stop reason=no_progress_limit round=${round} before=${before} after=${after}"
    exit 0
  fi

  sleep "$ROUND_SLEEP"
done
