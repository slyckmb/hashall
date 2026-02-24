#!/usr/bin/env bash
# qbit-start-seeding-gradual.sh — gradually start stoppedUP torrents in escalating batches.
# Version: 1.1.1
# Date:    2026-02-24
#
# After each batch waits for state to settle, then checks no torrent flipped
# to a downloading/broken state. On any bad state: immediately stops the
# affected torrents and halts.
# Safe by default: dry-run unless --apply is passed.
# Idempotent: only targets stoppedUP (100%) torrents; already-started ones
# are stalledUP/uploading and are skipped automatically.
#
# Usage: bin/qbit-start-seeding-gradual.sh [--apply] [--resume] [--daemon] [--min-batch N] [--poll N]
#   --apply        Execute changes (dry-run if omitted)
#   --resume       Skip torrents already in stalledUP/uploading/queuedUP
#   --daemon       Continuous watch loop: poll QB, run ramp when stoppedUP >= --min-batch
#   --min-batch N  Daemon threshold: wait until stoppedUP count >= N before ramp (default: 10)
#   --poll N       Daemon poll interval in seconds (default: 60)
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_VERSION="1.1.1"
SCRIPT_DATE="2026-02-24"

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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)      APPLY=true; shift ;;
    --resume)     RESUME=true; shift ;;
    --daemon)     DAEMON=true; shift ;;
    --min-batch)  MIN_BATCH="$2"; shift 2 ;;
    --poll)       POLL="$2"; shift 2 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

# In daemon mode, RESUME is implicitly true so each run only starts new ones
if [[ "$DAEMON" == true ]]; then
  RESUME=true
fi

COOKIE=$(mktemp /tmp/qb.XXXXXX)
TMPJSON=$(mktemp /tmp/qb_sg.XXXXXX)
TMPWATCH=$(mktemp /tmp/qb_sg_watch.XXXXXX)   # newline-separated started hashes
TMPHALT=$(mktemp /tmp/qb_sg_halt.XXXXXX)     # pipe-separated bad hashes on halt

# Persistent daemon log (only used when --daemon is active)
DAEMON_LOG="$LOGDIR/daemon.log"
DAEMON_HALT_RESET="$LOGDIR/daemon-halt-reset"

# Per-run log file; set once here for one-shot mode, overridden per-run in daemon mode
LOG="$LOGDIR/start-seeding-gradual-$(date +%Y%m%d-%H%M%S).log"

_DAEMON_EXIT=false

_cleanup() {
  rm -f "$COOKIE" "$TMPJSON" "$TMPWATCH" "$TMPHALT"
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

# ---------------------------------------------------------------------------
# run_ramp_start — batch ramp logic. Uses global LOG (caller sets per-run path).
# Returns 0 on clean completion, 1 if halted due to downloading detection.
# ---------------------------------------------------------------------------
run_ramp_start() {
  local resume_flag="$RESUME"

  # Reset watch file for this run
  > "$TMPWATCH"

  qb_login

  log "════════════════════════════════════════════════════════════"
  log "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
  log "apply=$APPLY  resume=$resume_flag  daemon=$DAEMON"
  log "════════════════════════════════════════════════════════════"

  # Fetch all torrents into temp file (avoids stdin conflicts with Python heredocs)
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPJSON"

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
      # Append new batch hashes to watch file
      printf '%s\n' "${batch[@]}" >> "$TMPWATCH"
      total_started=$(( total_started + bsize ))

      log "  waiting ${SETTLE_SECS}s for state to settle..."
      sleep "$SETTLE_SECS"
      qb_login 2>/dev/null || true

      # Check all started torrents for bad states (read watch list from file, not arg)
      curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPJSON"
      CHECK=$(python3 - "$TMPJSON" "$TMPWATCH" << 'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
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
)

      N_OK=$(echo "$CHECK" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['ok']))")
      N_DL=$(echo "$CHECK" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['downloading']))")
      N_BAD=$(echo "$CHECK" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['other_bad']))")
      N_STOP=$(echo "$CHECK" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['still_stopped']))")

      log "  check: ok=$N_OK  downloading=$N_DL  other_bad=$N_BAD  still_stoppedUP=$N_STOP"

      if [[ "$N_DL" -gt 0 ]]; then
        log ""
        log "WARNING: DOWNLOADING DETECTED — stopping affected torrents immediately:"
        BAD_HASHES=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
for h, s, p in d['downloading']:
    print(f'  {h[:12]}  {s}  {p:.4f}')
print('HASHES:' + '|'.join(h for h,s,p in d['downloading']))
" "$CHECK" | tee -a "$LOG" | grep '^HASHES:' | sed 's/^HASHES://')
        # Stop the bad ones (BAD_HASHES contains full 40-char hashes, pipe-separated)
        curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=$BAD_HASHES" >/dev/null 2>&1 || true
        log "  stop HTTP sent for: $BAD_HASHES"
        log ""
        log "HALTED — check the torrents listed above."
        # Record halt hashes for daemon error state
        echo "$BAD_HASHES" > "$TMPHALT"
        failures=$(( failures + N_DL ))
        ramp_halted=true
        break
      fi

      if [[ "$N_BAD" -gt 0 ]]; then
        log ""
        log "⚠️  Bad state (non-downloading) detected — listing but continuing:"
        echo "$CHECK" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for h, s, p in d['other_bad']:
    print(f'  {h}  {s}  {p:.4f}')
" | tee -a "$LOG"
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
echo "daemon mode  apply=$APPLY  min-batch=$MIN_BATCH  poll=${POLL}s"
echo "daemon log: $DAEMON_LOG"
echo "reset file:  $DAEMON_HALT_RESET"
echo "════════════════════════════════════════════════════════════"

{
  echo "════════════════════════════════════════════════════════════"
  echo "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
  echo "daemon mode  apply=$APPLY  min-batch=$MIN_BATCH  poll=${POLL}s"
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
      echo "error ts=$TS HALT: downloading detected hashes=$HALT_HASHES — create $DAEMON_HALT_RESET to resume" | tee -a "$DAEMON_LOG"
      sleep "$POLL"
      continue
    fi
  fi

  # Poll QB for current stoppedUP count
  qb_login 2>/dev/null || true
  if ! curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPJSON" 2>/dev/null; then
    echo "$(date '+%F %T') [daemon] WARNING: failed to fetch torrent list, retrying in ${POLL}s" | tee -a "$DAEMON_LOG"
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
      echo "$(date '+%F %T') [daemon] Ramp HALTED (downloading detected) hashes=$HALT_HASHES — log: $LOG" | tee -a "$DAEMON_LOG"
      echo "$(date '+%F %T') [daemon] Create $DAEMON_HALT_RESET to resume after investigating" | tee -a "$DAEMON_LOG"
    fi
  fi

  if [[ "$_DAEMON_EXIT" == true ]]; then
    echo "$(date '+%F %T') [daemon] Exiting cleanly." | tee -a "$DAEMON_LOG"
    break
  fi

  sleep "$POLL"
done
