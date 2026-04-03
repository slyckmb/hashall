#!/usr/bin/env bash
# Script: run-pool-migration-maintenance-loop.sh
# Version: 0.1.0
# Last-updated: 2026-04-02T17:25:00-04:00

set -euo pipefail

SCRIPT_NAME="run-pool-migration-maintenance-loop.sh"
VERSION="0.1.0"
LAST_UPDATED="2026-04-02T17:25:00-04:00"

DRYRUN=0
MAX_ROUNDS=3
LIMIT=20
SKIP_CLEANUP=0

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${HOME}/.logs/hashall/pool-migration-loop"
mkdir -p "$LOG_DIR"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_LOG="${LOG_DIR}/${RUN_ID}.log"

STALE_HIM_PATHS=(
  "/pool/data/cross-seed-link/SpeedCD/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED"
  "/pool/data/cross-seed-link/TorrentDay/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED"
)

usage() {
  cat <<'EOF'
Usage:
  run-pool-migration-maintenance-loop.sh [options]

Options:
  -n, --dryrun          Print commands without mutating state
  --max-rounds N        Max stash->pool rehome rounds to execute (default: 3)
  --limit N             Candidate limit per rehome round (default: 20)
  --skip-cleanup        Skip stale /pool/data residue cleanup
  -h, --help            Show this help

Behavior:
  1. Recover/sync qB + RT stack via payload-sync-only helper
  2. Delete two exact stale "How It's Made" duplicate roots if and only if:
     - no qB torrent rows still save there
     - no RT session rows still point there
  3. Reconcile /pool/data after cleanup and rerun payload sync
  4. Loop stash -> pool-media rehome rounds, but auto-apply only when the
     dry-run batch is entirely REUSE. Any MOVE/BLOCK/FAIL pauses the loop.
EOF
}

log_banner() {
  local event="$1"
  echo "event=${event} script=${SCRIPT_NAME} version=${VERSION} last_updated=${LAST_UPDATED} timestamp=$(date --iso-8601=seconds)"
}

run_cmd() {
  local label="$1"
  shift
  echo
  echo "[▶] ${label}"
  printf 'cmd='
  printf '%q ' "$@"
  echo
  echo "════════════════════════════════════════════════════════════════════"
  if [[ "$DRYRUN" -eq 1 ]]; then
    echo "dryrun=1 status=skipped step=${label}"
    return 0
  fi
  if "$@"; then
    echo "dryrun=0 status=ok step=${label}"
    return 0
  fi
  local rc=$?
  echo "dryrun=0 status=failed step=${label} rc=${rc}"
  return "$rc"
}

pause_and_exit() {
  local reason="$1"
  echo
  echo "[⏸] pause"
  echo "reason=${reason}"
  echo "run_log=${RUN_LOG}"
  exit 2
}

ensure_stack_synced() {
  run_cmd "payload-sync-only" "${ROOT_DIR}/bin/run-hashall-upgrade-scans.sh" --payload-sync-only
}

path_has_qb_rows() {
  local path="$1"
  python - "$path" <<'PY'
import sqlite3, sys
from pathlib import Path
db = Path.home()/'.hashall'/'catalog.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
prefix = sys.argv[1]
count = cur.execute(
    "select count(*) from torrent_instances where lower(coalesce(save_path,'')) like lower(?)",
    (prefix + '%',),
).fetchone()[0]
raise SystemExit(0 if count == 0 else 1)
PY
}

path_has_rt_rows() {
  local path="$1"
  local tmp
  tmp="$(mktemp)"
  python -m hashall.cli rt session-audit --path-contains "$path" --limit 5 --json-output >"$tmp"
  python - "$tmp" <<'PY'
import json, re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'(\{\s*"summary".*\})\s*$', text, re.S)
if not m:
    raise SystemExit(1)
data = json.loads(m.group(1))
rows = data.get("rows") or []
raise SystemExit(0 if len(rows) == 0 else 1)
PY
}

cleanup_stale_how_its_made() {
  local cleaned=0
  local path
  for path in "${STALE_HIM_PATHS[@]}"; do
    if [[ ! -e "$path" ]]; then
      echo "cleanup_skip path=${path} reason=missing"
      continue
    fi
    if ! path_has_qb_rows "$path"; then
      pause_and_exit "qb_rows_still_reference_${path}"
    fi
    if ! path_has_rt_rows "$path"; then
      pause_and_exit "rt_rows_still_reference_${path}"
    fi
    echo "cleanup_candidate path=${path}"
    du -sh "$path" || true
    if [[ "$DRYRUN" -eq 1 ]]; then
      echo "dryrun=1 status=skipped step=cleanup path=${path}"
    else
      rm -rf --one-file-system "$path"
      echo "dryrun=0 status=ok step=cleanup path=${path}"
      cleaned=1
    fi
  done

  if [[ "$cleaned" -eq 1 ]]; then
    run_cmd "scan:/pool/data" python -m hashall.cli scan /pool/data --hash-mode upgrade --drift-policy quick
    ensure_stack_synced
  fi
}

analyze_rehome_batch() {
  local dryrun_log="$1"
  python - "$dryrun_log" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8', errors='replace')
plan_decisions = re.findall(r'^\s*plan\s+([A-Z]+)\b', text, re.M)
has_fail = bool(re.search(r'^\s*(check|apply|verify)\s+.*\bFAIL\b', text, re.M))
has_error = 'status=failed' in text or 'Traceback' in text
if 'No eligible candidates found.' in text or re.search(r'taking top 0\b', text):
    print('status=empty')
    raise SystemExit(0)
if not plan_decisions:
    print('status=unknown')
    raise SystemExit(0)
if has_fail or has_error:
    print('status=bad')
    raise SystemExit(0)
if any(dec != 'REUSE' for dec in plan_decisions):
    print('status=non_reuse')
    print('decisions=' + ','.join(plan_decisions))
    raise SystemExit(0)
print('status=all_reuse')
print('count=' + str(len(plan_decisions)))
PY
}

run_rehome_round() {
  local round="$1"
  local dryrun_log="${LOG_DIR}/${RUN_ID}-round${round}-dryrun.log"
  local apply_log="${LOG_DIR}/${RUN_ID}-round${round}-apply.log"
  local analysis

  echo
  echo "[🔎] round=${round} dryrun"
  if [[ "$DRYRUN" -eq 1 ]]; then
    python -m hashall.cli rehome auto --from stash --to pool-media --limit "$LIMIT" | tee "$dryrun_log"
    analysis="$(analyze_rehome_batch "$dryrun_log")"
    printf '%s\n' "$analysis"
    return 0
  fi

  python -m hashall.cli rehome auto --from stash --to pool-media --limit "$LIMIT" | tee "$dryrun_log"
  analysis="$(analyze_rehome_batch "$dryrun_log")"
  printf '%s\n' "$analysis"

  if grep -q '^status=empty$' <<<"$analysis"; then
    echo "round=${round} result=no_candidates"
    return 10
  fi
  if ! grep -q '^status=all_reuse$' <<<"$analysis"; then
    pause_and_exit "round_${round}_not_all_reuse"
  fi

  echo
  echo "[▶] round=${round} apply"
  python -m hashall.cli rehome auto --from stash --to pool-media --limit "$LIMIT" --apply | tee "$apply_log"
  if grep -Eq 'apply\s+FAIL|verify\s+.*FAIL|status=failed|Traceback|status=dest_missing' "$apply_log"; then
    pause_and_exit "round_${round}_apply_failed"
  fi

  ensure_stack_synced
  return 0
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n|--dryrun)
        DRYRUN=1
        shift
        ;;
      --max-rounds)
        MAX_ROUNDS="$2"
        shift 2
        ;;
      --limit)
        LIMIT="$2"
        shift 2
        ;;
      --skip-cleanup)
        SKIP_CLEANUP=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
  done

  exec > >(tee -a "$RUN_LOG") 2>&1

  log_banner "start"
  echo "run_log=${RUN_LOG}"
  echo "max_rounds=${MAX_ROUNDS} limit=${LIMIT} dryrun=${DRYRUN} skip_cleanup=${SKIP_CLEANUP}"

  ensure_stack_synced

  if [[ "$SKIP_CLEANUP" -ne 1 ]]; then
    cleanup_stale_how_its_made
  fi

  local round
  for round in $(seq 1 "$MAX_ROUNDS"); do
    if run_rehome_round "$round"; then
      :
    else
      local rc=$?
      if [[ "$rc" -eq 10 ]]; then
        echo "result=complete reason=no_more_candidates round=${round}"
        log_banner "end"
        return 0
      fi
      return "$rc"
    fi
  done

  echo "result=paused reason=max_rounds_reached rounds=${MAX_ROUNDS}"
  log_banner "end"
}

main "$@"
