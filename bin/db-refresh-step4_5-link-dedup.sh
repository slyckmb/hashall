#!/usr/bin/env bash
# STEP 3.5: Optional dedup hardlink step between SHA256 upgrade and payload sync.
# Safe by default: creates plans + executes dry-run only.
# Use --apply to execute hardlink actions after dry-run previews.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/michael/.venvs/hashall/bin/python"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

APPLY=false
DEVICES_CSV="${DEVICES_CSV:-stash,data,spare}"
MIN_SIZE="${MIN_SIZE:-1048576}"   # 1 MiB default to avoid tiny-file churn
EXEC_LIMIT="${EXEC_LIMIT:-0}"     # 0 = all planned actions
LOCK_RETRY_SECS="${LOCK_RETRY_SECS:-30}"
LOCK_MAX_RETRIES="${LOCK_MAX_RETRIES:-0}"  # 0 = retry forever on DB lock
DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
ALIASES=()

usage() {
  cat <<'EOF'
Usage: bin/db-refresh-step4_5-link-dedup.sh [--apply] [--devices CSV | --alias NAME ...] [--min-size N] [--limit N] [--lock-retry-secs N] [--lock-max-retries N]

Options:
  --apply          Execute hardlink actions after dry-run (default: dry-run only)
  --devices CSV    Comma-separated device aliases (default: stash,data,spare)
  --alias NAME     Repeatable alias selector (example: --alias data --alias stash)
  --min-size N     Min file size in bytes for plan candidates (default: 1048576)
  --limit N        Max actions for execute phase per device (default: 0 = all)
  --lock-retry-secs N   Sleep interval between DB-lock retries (default: 30)
  --lock-max-retries N  Max DB-lock retries per command (default: 0 = unlimited)
  -h, --help       Show help

Environment overrides:
  DEVICES_CSV, MIN_SIZE, EXEC_LIMIT, LOCK_RETRY_SECS, LOCK_MAX_RETRIES, DB_PATH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    --devices) DEVICES_CSV="${2:-}"; shift 2 ;;
    --alias) ALIASES+=("${2:-}"); shift 2 ;;
    --min-size) MIN_SIZE="${2:-}"; shift 2 ;;
    --limit) EXEC_LIMIT="${2:-}"; shift 2 ;;
    --lock-retry-secs) LOCK_RETRY_SECS="${2:-}"; shift 2 ;;
    --lock-max-retries) LOCK_MAX_RETRIES="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "${#ALIASES[@]}" -gt 0 ]]; then
  DEVICES_CSV="$(IFS=,; echo "${ALIASES[*]}")"
fi

[[ -n "$DEVICES_CSV" ]] || { echo "devices list is empty"; exit 2; }
[[ "$MIN_SIZE" =~ ^[0-9]+$ ]] || { echo "Invalid --min-size: $MIN_SIZE" >&2; exit 2; }
[[ "$EXEC_LIMIT" =~ ^[0-9]+$ ]] || { echo "Invalid --limit: $EXEC_LIMIT" >&2; exit 2; }
[[ "$LOCK_RETRY_SECS" =~ ^[0-9]+$ ]] || { echo "Invalid --lock-retry-secs: $LOCK_RETRY_SECS" >&2; exit 2; }
[[ "$LOCK_MAX_RETRIES" =~ ^[0-9]+$ ]] || { echo "Invalid --lock-max-retries: $LOCK_MAX_RETRIES" >&2; exit 2; }
(( LOCK_RETRY_SECS > 0 )) || { echo "--lock-retry-secs must be > 0" >&2; exit 2; }

LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOGFILE="$LOGDIR/step3_5-link-dedup-${STAMP}.log"

echo "================================================================" | tee -a "$LOGFILE"
echo "STEP 3.5: link dedup plan/execute — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
echo "apply=${APPLY} devices=${DEVICES_CSV} min_size=${MIN_SIZE} limit=${EXEC_LIMIT}" | tee -a "$LOGFILE"
echo "lock_retry_secs=${LOCK_RETRY_SECS} lock_max_retries=${LOCK_MAX_RETRIES}" | tee -a "$LOGFILE"
echo "db=${DB_PATH}" | tee -a "$LOGFILE"
echo "================================================================" | tee -a "$LOGFILE"

IFS=',' read -r -a DEVICES <<< "$DEVICES_CSV"

resolve_device_alias() {
  local requested="$1"
  "$PYTHON" - "$DB_PATH" "$requested" <<'PY'
import sqlite3
import sys

db_path, requested = sys.argv[1], sys.argv[2]
requested_lc = requested.lower()

conn = sqlite3.connect(db_path)
cur = conn.cursor()

def first(query, params=()):
    row = cur.execute(query, params).fetchone()
    return row[0] if row and row[0] else ""

alias = first("SELECT device_alias FROM devices WHERE lower(device_alias)=lower(?) LIMIT 1", (requested,))
if alias:
    print(alias)
    raise SystemExit(0)

if requested_lc in {"spare", "hotspare6tb"}:
    alias = first("SELECT device_alias FROM devices WHERE lower(device_alias)=lower('spare') LIMIT 1")
    if alias:
        print(alias)
        raise SystemExit(0)
    alias = first("SELECT device_alias FROM devices WHERE lower(device_alias)=lower('hotspare6tb') LIMIT 1")
    if alias:
        print(alias)
        raise SystemExit(0)
    alias = first(
        "SELECT device_alias FROM devices "
        "WHERE preferred_mount_point='/mnt/hotspare6tb' OR mount_point='/mnt/hotspare6tb' "
        "ORDER BY device_alias LIMIT 1"
    )
    if alias:
        print(alias)
        raise SystemExit(0)

print("")
PY
}

run_hashall_with_retry() {
  local out_file="$1"
  shift
  local attempt=1
  local rc=0

  while true; do
    : > "$out_file"
    set +e
    "$PYTHON" -m hashall "$@" 2>&1 | tee "$out_file"
    rc=${PIPESTATUS[0]}
    set -e
    cat "$out_file" >> "$LOGFILE"

    if [[ "$rc" -eq 0 ]]; then
      return 0
    fi

    if grep -q "database is locked" "$out_file"; then
      if [[ "$LOCK_MAX_RETRIES" -ne 0 && "$attempt" -ge "$LOCK_MAX_RETRIES" ]]; then
        echo "DB lock retry limit reached (attempts=${attempt}) for: hashall $*" | tee -a "$LOGFILE"
        return "$rc"
      fi
      echo "  [lock-wait] cmd='hashall $*' attempt=${attempt} sleep=${LOCK_RETRY_SECS}s" | tee -a "$LOGFILE"
      sleep "$LOCK_RETRY_SECS"
      attempt=$((attempt + 1))
      continue
    fi

    return "$rc"
  done
}

declare -A seen_devices=()
declare -a resolved_devices=()
for DEVICE in "${DEVICES[@]}"; do
  DEVICE="$(echo "$DEVICE" | xargs)"
  [[ -n "$DEVICE" ]] || continue
  RESOLVED="$(resolve_device_alias "$DEVICE" | tr -d '\r\n' || true)"
  if [[ -z "$RESOLVED" ]]; then
    echo "WARN: device alias not found for requested='$DEVICE' (skipping)" | tee -a "$LOGFILE"
    continue
  fi
  if [[ -z "${seen_devices[$RESOLVED]+x}" ]]; then
    seen_devices[$RESOLVED]=1
    resolved_devices+=("$RESOLVED")
  fi
done

if [[ "${#resolved_devices[@]}" -eq 0 ]]; then
  echo "ERROR: no valid devices resolved for step 3.5; requested=${DEVICES_CSV}" | tee -a "$LOGFILE"
  exit 1
fi

echo "resolved_devices=$(IFS=,; echo "${resolved_devices[*]}")" | tee -a "$LOGFILE"

run_device_plan() {
  local DEVICE="$1"

  PLAN_NAME="db-refresh-step3_5-${DEVICE}-${STAMP}"
  TMP_OUT="$(mktemp /tmp/link-plan.${DEVICE}.XXXXXX)"

  echo "" | tee -a "$LOGFILE"
  echo "--- device=${DEVICE} plan=${PLAN_NAME} --- $(date '+%F %T')" | tee -a "$LOGFILE"
  run_hashall_with_retry "$TMP_OUT" link plan "$PLAN_NAME" \
    --device "$DEVICE" \
    --min-size "$MIN_SIZE" \
    --no-upgrade-collisions

  PLAN_ID="$(python3 - <<'PY' "$TMP_OUT"
import re, sys
text = open(sys.argv[1], "r", encoding="utf-8", errors="replace").read()
patterns = [
    r"\bID:\s*([0-9]+)\b",
    r"\bPlan\s*#\s*([0-9]+)\b",
    r"\bshow-plan\s+([0-9]+)\b",
]
for pattern in patterns:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if m:
        print(m.group(1))
        break
else:
    print("")
PY
)"

  [[ -n "$PLAN_ID" ]] || { echo "Could not parse plan id for device=${DEVICE}" | tee -a "$LOGFILE"; rm -f "$TMP_OUT"; return 1; }
  echo "plan_id=${PLAN_ID}" | tee -a "$LOGFILE"
  rm -f "$TMP_OUT"

  TMP_OUT="$(mktemp /tmp/link-show.${DEVICE}.XXXXXX)"
  run_hashall_with_retry "$TMP_OUT" link show-plan "$PLAN_ID" --limit 20
  rm -f "$TMP_OUT"

  echo "--- dry-run execute plan_id=${PLAN_ID} ---" | tee -a "$LOGFILE"
  TMP_OUT="$(mktemp /tmp/link-dryrun.${DEVICE}.XXXXXX)"
  run_hashall_with_retry "$TMP_OUT" link execute "$PLAN_ID" --dry-run --limit "$EXEC_LIMIT"
  rm -f "$TMP_OUT"

  if [[ "$APPLY" == "true" ]]; then
    echo "--- apply execute plan_id=${PLAN_ID} ---" | tee -a "$LOGFILE"
    TMP_OUT="$(mktemp /tmp/link-apply.${DEVICE}.XXXXXX)"
    run_hashall_with_retry "$TMP_OUT" link execute "$PLAN_ID" --limit "$EXEC_LIMIT" --yes
    rm -f "$TMP_OUT"
  fi
}

failures=0
for DEVICE in "${resolved_devices[@]}"; do
  if ! run_device_plan "$DEVICE"; then
    failures=$((failures + 1))
    echo "ERROR: device run failed for ${DEVICE}" | tee -a "$LOGFILE"
  fi
done

echo "" | tee -a "$LOGFILE"
echo "--- stats after step 3.5 ---" | tee -a "$LOGFILE"
TMP_OUT="$(mktemp /tmp/link-stats.XXXXXX)"
run_hashall_with_retry "$TMP_OUT" stats
rm -f "$TMP_OUT"

echo "" | tee -a "$LOGFILE"
echo "STEP 3.5 DONE — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
if [[ "$APPLY" == "true" ]]; then
  echo ">>> Hardlink actions were applied. Review output before step 4. <<<" | tee -a "$LOGFILE"
else
  echo ">>> Dry-run only. Re-run with --apply to execute before step 4. <<<" | tee -a "$LOGFILE"
fi

if [[ "$failures" -ne 0 ]]; then
  echo "ERROR: step 3.5 completed with ${failures} failed device(s)." | tee -a "$LOGFILE"
  exit 1
fi
