#!/usr/bin/env bash
# qbit-start-seeding-gradual.sh — gradually start stoppedUP torrents in escalating batches.
# Version: 1.3.1
# Date:    2026-02-27
#
# After each batch waits for state to settle, then checks the protected watch
# scope (all torrents added before today) for downloading/broken flips. On any
# bad state: immediately stops the affected torrents and halts.
# Safe by default: dry-run unless --apply is passed.
# Idempotent: only targets stoppedUP (100%) torrents; already-started ones
# are stalledUP/uploading and are skipped automatically.
#
# Usage: bin/qbit-start-seeding-gradual.sh [--apply] [--resume] [--daemon] [--min-batch N] [--poll N] [--cache] [--cache-max-age N]
#   --apply        Execute changes (dry-run if omitted)
#   --resume       Skip torrents already in stalledUP/uploading/queuedUP
#   --daemon       Continuous watch loop: poll QB, run ramp when stoppedUP >= --min-batch
#   --min-batch N  Daemon threshold: wait until stoppedUP count >= N before ramp (default: 10)
#   --poll N       Daemon poll interval in seconds (default: 60)
#   --cache        Use shared qB cache agent for torrents/info reads
#   --cache-max-age N  Max cache age seconds when --cache is enabled (default: 15)
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_VERSION="1.3.1"
SCRIPT_DATE="2026-02-27"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"

LOGDIR="$HOME/.logs/hashall/reports/qbit-triage"
mkdir -p "$LOGDIR"

APPLY=false
RESUME=false
DAEMON=false
MIN_BATCH=10
POLL=60
USE_CACHE=false
CACHE_MAX_AGE=15
CACHE_AGENT="${QBIT_CACHE_AGENT:-$SCRIPT_DIR/qbit-cache-agent.py}"
CACHE_CLIENT_ID="${SCRIPT_NAME}:$$"

usage_short() {
  cat <<EOF
Usage: $SCRIPT_NAME [--apply] [--resume] [--daemon] [--min-batch N] [--poll N] [--cache] [--cache-max-age N] [-h|--help]
Try '$SCRIPT_NAME --help' for details.
EOF
}

usage_help() {
  cat <<'EOF'
qbit-start-seeding-gradual.sh

Purpose:
  Gradually start stoppedUP torrents in escalating batches with safety checks.
  In daemon mode, it polls qB and runs the ramp automatically when the
  stoppedUP threshold is met.

Usage:
  bin/qbit-start-seeding-gradual.sh [OPTIONS]

Options:
  --apply
      Execute changes (default is dry-run).

  --resume
      Skip torrents already in seeding states.

  --daemon
      Run continuously. Poll qB and trigger ramp when stoppedUP count is
      >= --min-batch.

  --min-batch N
      Daemon threshold for running a ramp pass.
      Default: 10

  --poll N
      Daemon poll interval in seconds.
      Controls how often qB is checked and how often daemon status/halt lines
      are emitted.
      Default: 60

  --cache
      Read qB torrents/info via shared cache agent instead of polling qB API
      directly on every read.

  --cache-max-age N
      Maximum cache age in seconds when --cache is enabled.
      Smaller values request a fresher snapshot.
      Default: 15

  -h, --help
      Show this detailed help and exit.

Examples:
  # Show detailed help
  bin/qbit-start-seeding-gradual.sh --help

  # One-shot dry-run
  bin/qbit-start-seeding-gradual.sh --resume

  # Daemon mode, live apply, check every 60s
  bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 60

  # Same, but read qB state via shared cache (max age 5s)
  bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 60 --cache --cache-max-age 5
EOF
}

if [[ $# -eq 0 ]]; then
  usage_short
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)    usage_help; exit 0 ;;
    --apply)      APPLY=true; shift ;;
    --resume)     RESUME=true; shift ;;
    --daemon)     DAEMON=true; shift ;;
    --min-batch)  MIN_BATCH="$2"; shift 2 ;;
    --poll)       POLL="$2"; shift 2 ;;
    --cache)      USE_CACHE=true; shift ;;
    --cache-max-age) CACHE_MAX_AGE="$2"; shift 2 ;;
    *)
      echo "unknown: $1" >&2
      usage_short >&2
      exit 1
      ;;
  esac
done

# In daemon mode, RESUME is implicitly true so each run only starts new ones
if [[ "$DAEMON" == true ]]; then
  RESUME=true
fi
if ! [[ "$CACHE_MAX_AGE" =~ ^[0-9]+$ ]] || [[ "$CACHE_MAX_AGE" -lt 0 ]]; then
  echo "--cache-max-age must be a non-negative integer" >&2
  exit 2
fi
if [[ "$USE_CACHE" == true && ! -f "$CACHE_AGENT" ]]; then
  echo "--cache enabled but cache agent not found: $CACHE_AGENT" >&2
  exit 2
fi

COOKIE=$(mktemp /tmp/qb.XXXXXX)
TMPJSON=$(mktemp /tmp/qb_sg.XXXXXX)
TMPWATCH=$(mktemp /tmp/qb_sg_watch.XXXXXX)   # newline-separated protected hashes
TMPHALT=$(mktemp /tmp/qb_sg_halt.XXXXXX)     # pipe-separated bad hashes on halt
TMPCHECK=$(mktemp /tmp/qb_sg_check.XXXXXX)   # JSON state-check payload
TMPBASE_DL=$(mktemp /tmp/qb_sg_base_dl.XXXXXX) # baseline downloading-like hashes in watch scope
TMPCURR_DL=$(mktemp /tmp/qb_sg_curr_dl.XXXXXX) # current downloading-like hashes in watch scope
TMPFLIP_DL=$(mktemp /tmp/qb_sg_flip_dl.XXXXXX) # newly flipped hashes (current - baseline)

# Persistent daemon log (only used when --daemon is active)
DAEMON_LOG="$LOGDIR/daemon.log"
DAEMON_HALT_RESET="$LOGDIR/daemon-halt-reset"

# Per-run log file; set once here for one-shot mode, overridden per-run in daemon mode
LOG="$LOGDIR/start-seeding-gradual-$(date +%Y%m%d-%H%M%S).log"

_DAEMON_EXIT=false

_cleanup() {
  rm -f "$COOKIE" "$TMPJSON" "$TMPWATCH" "$TMPHALT" "$TMPCHECK" "$TMPBASE_DL" "$TMPCURR_DL" "$TMPFLIP_DL"
}
trap '_cleanup' EXIT

_handle_signal() {
  echo "" >&2
  echo "$(date '+%F %T') [daemon] Caught signal — finishing current operation then exiting..." >&2
  if [[ "$DAEMON" == true ]]; then
    echo "$(date '+%F %T') [daemon] Signal received — exiting after current operation" >> "$DAEMON_LOG"
  fi
  _DAEMON_EXIT=true
}
trap '_handle_signal' SIGINT SIGTERM

log() { echo "$*" | tee -a "$LOG"; }

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}

fetch_torrents_info() {
  local attempts="${1:-3}"
  local delay_s="${2:-2}"
  local i=1
  while [[ "$i" -le "$attempts" ]]; do
    if [[ "$USE_CACHE" == true ]]; then
      if QBIT_URL="$QB_URL" QBIT_USER="$QB_USER" QBIT_PASS="$QB_PASS" \
          python3 "$CACHE_AGENT" \
            --max-age "$CACHE_MAX_AGE" \
            --requested-interval "$CACHE_MAX_AGE" \
            --client-id "$CACHE_CLIENT_ID" \
            --ensure-daemon \
            > "$TMPJSON" 2>>"$LOG"; then
        return 0
      fi
      log "  warn: failed to fetch torrent states via cache agent (attempt $i/$attempts)"
    else
      if curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPJSON" 2>>"$LOG"; then
        return 0
      fi
      log "  warn: failed to fetch torrent states (attempt $i/$attempts)"
      qb_login 2>/dev/null || true
    fi
    sleep "$delay_s"
    i=$(( i + 1 ))
  done
  return 1
}

build_watch_scope_before_today() {
  local data_file="$1"
  python3 - "$data_file" << 'PYEOF'
import json, sys
from datetime import datetime

data = json.load(open(sys.argv[1]))
today = datetime.now()
today_start = int(datetime(today.year, today.month, today.day).timestamp())

for t in data:
    h = str(t.get("hash", "")).strip()
    if not h:
        continue
    added_raw = t.get("added_on", 0)
    try:
        added_on = int(added_raw)
    except Exception:
        added_on = 0
    # Unknown added_on is treated as protected for fail-closed safety.
    if added_on <= 0 or added_on < today_start:
        print(h)
PYEOF
}

# ---------------------------------------------------------------------------
# run_ramp_start — batch ramp logic. Uses global LOG (caller sets per-run path).
# Returns 0 on clean completion, 1 if halted due to downloading detection.
# ---------------------------------------------------------------------------
run_ramp_start() {
  local resume_flag="$RESUME"

  if [[ "$USE_CACHE" != true ]]; then
    qb_login
  fi

  log "════════════════════════════════════════════════════════════"
  log "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
  log "apply=$APPLY  resume=$resume_flag  daemon=$DAEMON  cache=$USE_CACHE  cache_max_age=$CACHE_MAX_AGE"
  log "════════════════════════════════════════════════════════════"

  # Fetch all torrents into temp file (avoids stdin conflicts with Python heredocs)
  if ! fetch_torrents_info 3 1; then
    log "ERROR: unable to fetch initial torrent list from qB API"
    return 1
  fi

  # Build protected watch scope: all torrents added before today (fail-closed on unknown added_on).
  if ! build_watch_scope_before_today "$TMPJSON" > "$TMPWATCH"; then
    log "ERROR: unable to derive protected watch scope"
    return 1
  fi
  WATCH_TOTAL=$(grep -c . "$TMPWATCH" 2>/dev/null || true)
  log "  protected watch scope (added before today): $WATCH_TOTAL"
  if ! python3 - "$TMPJSON" "$TMPWATCH" << 'PYEOF' > "$TMPBASE_DL"
import json, sys
data = json.load(open(sys.argv[1]))
watch = set(open(sys.argv[2]).read().split())
download_bad = {'checkingDL','downloading','stalledDL'}
for t in data:
    h = str(t.get("hash", "")).strip()
    if not h or h not in watch:
        continue
    s = t.get("state", "")
    p = t.get("progress", 0)
    if s in download_bad or (s == 'stoppedDL' and p < 0.9999):
        print(h)
PYEOF
  then
    log "ERROR: unable to derive baseline downloading-like scope"
    return 1
  fi
  LC_ALL=C sort -u "$TMPBASE_DL" -o "$TMPBASE_DL"
  BASE_DL_COUNT=$(grep -c . "$TMPBASE_DL" 2>/dev/null || true)
  if [[ "$BASE_DL_COUNT" -gt 0 ]]; then
    log "  baseline downloading-like in watch scope: $BASE_DL_COUNT (flip-only gate enabled)"
  fi

  # Collect stoppedUP hashes (100% progress, not seeding yet)
  CANDIDATES=$(python3 - "$TMPJSON" "$resume_flag" << 'PYEOF'
import json, sys

data_file, resume_flag = sys.argv[1], sys.argv[2] == "true"
data = json.load(open(data_file))

good_seeding = {"stalledUP", "uploading", "queuedUP", "forcedUP"}

hashes = []
already_seeding = 0
for t in data:
    s = t.get("state", "")
    p = t.get("progress", 0)
    if s == "stoppedUP" and abs(p - 1.0) < 0.0001:
        hashes.append(t["hash"])
    elif s in good_seeding:
        already_seeding += 1

print(f"  already seeding: {already_seeding}", file=sys.stderr)
for h in hashes:
    print(h)
PYEOF
)

  TOTAL=$(echo "$CANDIDATES" | grep -c . 2>/dev/null || true)
  log "  stoppedUP candidates: $TOTAL"
  if [[ "$TOTAL" -eq 0 ]]; then
    log "Nothing to start."
    return 0
  fi

  # Escalating batch sizes
  BATCH_SIZES=(1 2 5 10 25 50 100 250 500 1000 9999)
  SETTLE_SECS=45          # wait after start before checking

  total_started=0
  failures=0

  mapfile -t all_hashes < <(echo "$CANDIDATES")

  log ""
  log "Batch plan: ${BATCH_SIZES[*]}"
  log "Settle wait: ${SETTLE_SECS}s per batch"
  log ""

  local offset=0
  local batch_num=0
  local ramp_halted=false
  for bsize in "${BATCH_SIZES[@]}"; do
    batch_num=$(( batch_num + 1 ))
    remaining=$(( TOTAL - offset ))
    [[ $remaining -le 0 ]] && break
    [[ $bsize -gt $remaining ]] && bsize=$remaining

    batch=("${all_hashes[@]:$offset:$bsize}")
    offset=$(( offset + bsize ))

    log "▸ Batch $batch_num — starting $bsize torrents (total so far: $total_started)"
    for h in "${batch[@]}"; do
      log "    $h"
    done

    if [[ "$APPLY" == true ]]; then
      qb_login 2>/dev/null || true
      PIPE=$(IFS='|'; echo "${batch[*]}")
      HTTP=$(curl -sS -o/dev/null -w "%{http_code}" \
          -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/start" \
          --data-urlencode "hashes=$PIPE")
      log "  start HTTP: $HTTP"
      total_started=$(( total_started + bsize ))

      log "  waiting ${SETTLE_SECS}s for state to settle..."
      sleep "$SETTLE_SECS"
      qb_login 2>/dev/null || true

      # Check protected watch scope for bad states (read watch list from file, not arg)
      if ! fetch_torrents_info 3 2; then
        log "  ERROR: unable to fetch state after settle window; stopping batch and halting."
        PIPE=$(IFS='|'; echo "${batch[*]}")
        curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=$PIPE" >/dev/null 2>&1 || true
        log "  stop HTTP sent for batch: $PIPE"
        echo "safety_check_failed:fetch_torrents_info:$PIPE" > "$TMPHALT"
        failures=$(( failures + bsize ))
        ramp_halted=true
        break
      fi

      if ! python3 - "$TMPJSON" "$TMPWATCH" << 'PYEOF' > "$TMPCHECK"
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"state_json_parse_error:{e}", file=sys.stderr)
    raise SystemExit(2)
watch = set(open(sys.argv[2]).read().split())
download_bad = {'checkingDL','downloading','stalledDL'}
other_bad    = {'missingFiles','error'}
results = {'ok':[], 'downloading':[], 'other_bad':[], 'still_stopped':[]}
for t in data:
    if t['hash'] not in watch: continue
    s = t['state']
    p = t.get('progress', 0)
    h = t['hash']  # full 40-char hash for API calls
    if s in download_bad or (s == 'stoppedDL' and p < 0.9999):
        results['downloading'].append([h, s, p])
    elif s in other_bad:
        results['other_bad'].append([h, s, p])
    elif s == 'stoppedUP':
        results['still_stopped'].append([h, s, p])
    else:
        results['ok'].append(h)
print(json.dumps(results))
PYEOF
      then
        log "  ERROR: failed to parse state-check payload; stopping batch and halting."
        PIPE=$(IFS='|'; echo "${batch[*]}")
        curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=$PIPE" >/dev/null 2>&1 || true
        log "  stop HTTP sent for batch: $PIPE"
        echo "safety_check_failed:parse_state_payload:$PIPE" > "$TMPHALT"
        failures=$(( failures + bsize ))
        ramp_halted=true
        break
      fi

      if ! COUNTS=$(python3 - "$TMPCHECK" << 'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"state_counts_parse_error:{e}", file=sys.stderr)
    raise SystemExit(2)
print(len(d.get("ok", [])), len(d.get("downloading", [])), len(d.get("other_bad", [])), len(d.get("still_stopped", [])))
PYEOF
      ); then
        log "  ERROR: failed to summarize state-check payload; stopping batch and halting."
        PIPE=$(IFS='|'; echo "${batch[*]}")
        curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=$PIPE" >/dev/null 2>&1 || true
        log "  stop HTTP sent for batch: $PIPE"
        echo "safety_check_failed:parse_state_counts:$PIPE" > "$TMPHALT"
        failures=$(( failures + bsize ))
        ramp_halted=true
        break
      fi
      read -r N_OK N_DL N_BAD N_STOP <<< "$COUNTS"
      if ! python3 - "$TMPCHECK" << 'PYEOF' > "$TMPCURR_DL"
import json, sys
d = json.load(open(sys.argv[1]))
for rec in d.get("downloading", []):
    if isinstance(rec, list) and rec:
        h = str(rec[0]).strip()
        if h:
            print(h)
PYEOF
      then
        log "  ERROR: failed to extract downloading hash set; stopping batch and halting."
        PIPE=$(IFS='|'; echo "${batch[*]}")
        curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=$PIPE" >/dev/null 2>&1 || true
        log "  stop HTTP sent for batch: $PIPE"
        echo "safety_check_failed:extract_downloading_hash_set:$PIPE" > "$TMPHALT"
        failures=$(( failures + bsize ))
        ramp_halted=true
        break
      fi
      LC_ALL=C sort -u "$TMPCURR_DL" -o "$TMPCURR_DL"
      comm -23 "$TMPCURR_DL" "$TMPBASE_DL" > "$TMPFLIP_DL" || true
      CURR_DL_COUNT=$(grep -c . "$TMPCURR_DL" 2>/dev/null || true)
      NEW_DL_COUNT=$(grep -c . "$TMPFLIP_DL" 2>/dev/null || true)
      PREEXIST_DL_COUNT=$(( CURR_DL_COUNT - NEW_DL_COUNT ))
      if [[ "$PREEXIST_DL_COUNT" -lt 0 ]]; then
        PREEXIST_DL_COUNT=0
      fi

      log "  check: ok=$N_OK  downloading_total=$CURR_DL_COUNT  downloading_new=$NEW_DL_COUNT  downloading_preexisting=$PREEXIST_DL_COUNT  other_bad=$N_BAD  still_stoppedUP=$N_STOP"

      if [[ "$NEW_DL_COUNT" -gt 0 ]]; then
        log ""
        log "WARNING: NEW downloading flips detected — stopping newly flipped torrents immediately:"
        BAD_HASHES=$(python3 - "$TMPCHECK" "$TMPFLIP_DL" << 'PYEOF' | tee -a "$LOG" | grep '^HASHES:' | sed 's/^HASHES://'
import json, sys
d = json.load(open(sys.argv[1]))
flipped = set(line.strip() for line in open(sys.argv[2]) if line.strip())
selected = []
for h, s, p in d.get('downloading', []):
    if h in flipped:
        selected.append((h, s, p))
for h, s, p in selected:
    print(f'  {h[:12]}  {s}  {p:.4f}')
print('HASHES:' + '|'.join(h for h, s, p in selected))
PYEOF
)
        if [[ -n "$BAD_HASHES" ]]; then
          curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
              --data-urlencode "hashes=$BAD_HASHES" >/dev/null 2>&1 || true
          log "  stop HTTP sent for: $BAD_HASHES"
        else
          log "  stop HTTP skipped: no concrete flipped hashes resolved"
        fi
        log ""
        log "HALTED — check the torrents listed above."
        # Record halt hashes for daemon error state
        echo "$BAD_HASHES" > "$TMPHALT"
        failures=$(( failures + NEW_DL_COUNT ))
        ramp_halted=true
        break
      fi
      if [[ "$PREEXIST_DL_COUNT" -gt 0 ]]; then
        log "  note: pre-existing downloading-like torrents detected; ignored by flip-only safety gate."
      fi

      if [[ "$N_BAD" -gt 0 ]]; then
        log ""
        log "⚠️  Bad state (non-downloading) detected — listing but continuing:"
        python3 - "$TMPCHECK" << 'PYEOF' | tee -a "$LOG"
import json, sys
d = json.load(open(sys.argv[1]))
for h, s, p in d.get('other_bad', []):
    print(f'  {h}  {s}  {p:.4f}')
PYEOF
      fi

      log "  ✓ batch OK — all started torrents stable"
    else
      log "  [dry-run] would start: ${batch[*]}"
      total_started=$(( total_started + bsize ))
    fi
    log ""
  done

  log "════════════════════════════════════════════════════════════"
  log "DONE  started=$total_started  failures=$failures  $(date '+%F %T')"
  log "log: $LOG"
  log "════════════════════════════════════════════════════════════"

  if [[ "$ramp_halted" == true ]]; then
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# One-shot mode (no --daemon)
# ---------------------------------------------------------------------------
if [[ "$DAEMON" == false ]]; then
  run_ramp_start
  exit $?
fi

# ---------------------------------------------------------------------------
# Daemon mode
# ---------------------------------------------------------------------------
echo "════════════════════════════════════════════════════════════"
echo "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
echo "daemon mode  apply=$APPLY  min-batch=$MIN_BATCH  poll=${POLL}s  cache=$USE_CACHE  cache_max_age=${CACHE_MAX_AGE}s"
echo "daemon log: $DAEMON_LOG"
echo "reset file:  $DAEMON_HALT_RESET"
echo "════════════════════════════════════════════════════════════"

{
  echo "════════════════════════════════════════════════════════════"
  echo "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
  echo "daemon mode  apply=$APPLY  min-batch=$MIN_BATCH  poll=${POLL}s  cache=$USE_CACHE  cache_max_age=${CACHE_MAX_AGE}s"
  echo "════════════════════════════════════════════════════════════"
} >> "$DAEMON_LOG"

DAEMON_HALTED=false
HALT_HASHES=""

while true; do
  if [[ "$_DAEMON_EXIT" == true ]]; then
    echo "$(date '+%F %T') [daemon] Exiting cleanly." | tee -a "$DAEMON_LOG"
    break
  fi

  # --- Halt state: emit error every poll, block ramp until reset file appears ---
  if [[ "$DAEMON_HALTED" == true ]]; then
    if [[ -f "$DAEMON_HALT_RESET" ]]; then
      echo "$(date '+%F %T') [daemon] Reset acknowledged — resuming normal operation" | tee -a "$DAEMON_LOG"
      DAEMON_HALTED=false
      HALT_HASHES=""
      rm -f "$DAEMON_HALT_RESET"
    else
      TS="$(date '+%F %T')"
      echo "error ts=$TS HALT: safety gate triggered detail=$HALT_HASHES — create $DAEMON_HALT_RESET to resume" | tee -a "$DAEMON_LOG"
      sleep "$POLL"
      continue
    fi
  fi

  # Poll QB/cache for current stoppedUP count
  if ! fetch_torrents_info 3 1; then
    echo "$(date '+%F %T') [daemon] WARNING: failed to fetch torrent list (cache=${USE_CACHE}), retrying in ${POLL}s" | tee -a "$DAEMON_LOG"
    sleep "$POLL"
    continue
  fi

  STOPPED_UP_COUNT=$(python3 - "$TMPJSON" << 'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
count = sum(1 for t in data if t.get("state") == "stoppedUP" and abs(t.get("progress", 0) - 1.0) < 0.0001)
print(count)
PYEOF
)

  TS="$(date '+%F %T')"
  STATUS_LINE="status ts=$TS stoppedUP=$STOPPED_UP_COUNT threshold=$MIN_BATCH"
  echo "$STATUS_LINE" | tee -a "$DAEMON_LOG"

  if [[ "$STOPPED_UP_COUNT" -ge "$MIN_BATCH" ]]; then
    echo "$(date '+%F %T') [daemon] Threshold met ($STOPPED_UP_COUNT >= $MIN_BATCH) — running ramp-start" | tee -a "$DAEMON_LOG"

    # Per-run log file
    RUN_TS="$(date +%Y%m%d-%H%M%S)"
    LOG="$LOGDIR/start-seeding-gradual-${RUN_TS}.log"

    echo "$(date '+%F %T') [daemon] Run started — log: $LOG" >> "$DAEMON_LOG"

    if run_ramp_start; then
      echo "$(date '+%F %T') [daemon] Ramp completed cleanly — log: $LOG" | tee -a "$DAEMON_LOG"
    else
      HALT_HASHES="$(cat "$TMPHALT" 2>/dev/null || echo 'unknown')"
      DAEMON_HALTED=true
      echo "$(date '+%F %T') [daemon] Ramp HALTED (safety gate) detail=$HALT_HASHES — log: $LOG" | tee -a "$DAEMON_LOG"
      echo "$(date '+%F %T') [daemon] Create $DAEMON_HALT_RESET to resume after investigating" | tee -a "$DAEMON_LOG"
    fi
  fi

  if [[ "$_DAEMON_EXIT" == true ]]; then
    echo "$(date '+%F %T') [daemon] Exiting cleanly." | tee -a "$DAEMON_LOG"
    break
  fi

  sleep "$POLL"
done
