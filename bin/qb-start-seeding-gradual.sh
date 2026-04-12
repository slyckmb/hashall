#!/usr/bin/env bash

# qb-start-seeding-gradual.sh — gradually start stoppedUP torrents in escalating batches.
# Version: 1.4.1
# Date:    2026-03-16
#
# After each batch waits for state to settle, then checks the protected watch
# scope (all torrents added before today) for downloading/broken flips. On any
# bad state: immediately stops the affected torrents and halts.
# Safe by default: dry-run unless --apply is passed.
# Idempotent: only targets stoppedUP (100%) torrents; already-started ones
# are stalledUP/uploading and are skipped automatically.
#
# Usage: bin/qb-start-seeding-gradual.sh [--apply] [--resume] [--daemon] [--guard-only] [--min-batch N] [--poll N] [--cache] [--no-cache] [--cache-max-age N] [--guard-stop-cooldown N] [--guard-cooldown-state PATH] [--guard-include-checkingdl] [--guard-recheck-allowlist-file PATH] [--ignore-hashes CSV] [--ignore-hashes-file PATH]
#   --apply        Execute changes (dry-run if omitted)
#   --resume       Skip torrents already in stalledUP/uploading/queuedUP
#   --daemon       Continuous watch loop: poll QB, run ramp when stoppedUP >= --min-batch
#   --guard-only   Do not start anything; only detect/stop downloading-like flips in protected scope
#   --min-batch N  Daemon threshold: wait until stoppedUP count >= N before ramp (default: 10)
#   --poll N       Daemon poll interval in seconds (default: 60)
#   --cache        Use shared qB cache agent for torrents/info reads (default)
#   --no-cache     Bypass shared qB cache agent for torrents/info reads
#   --cache-max-age N  Max cache age seconds when --cache is enabled (default: 15)
#   --guard-stop-cooldown N  Suppress repeated stop requests per hash for N seconds in guard-only mode (default: 120)
#   --guard-cooldown-state PATH  JSON state file for guard cooldown tracking
#   --guard-include-checkingdl  Treat checkingDL as dangerous in guard mode (default: disabled)
#   --guard-recheck-allowlist-file PATH  JSON TTL map of hashes exempted during repair rechecks
#   --ignore-hashes CSV  Hashes/prefixes to ignore in watch/candidate checks
#   --ignore-hashes-file PATH  Ignore hash file (default: /tmp/qb-stoppeddl-bucket-live/download-whitelist-hashes.txt if present)
SCRIPT_NAME="$(basename "$0")"
SEMVER="1.4.1"
LAST_UPDATED="2026-03-16"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_VERSION="1.4.1"
SCRIPT_DATE="2026-03-16"
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
GUARD_ONLY=false
MIN_BATCH=10
POLL=60
USE_CACHE=true
CACHE_MAX_AGE=30
GUARD_STOP_COOLDOWN=120
GUARD_INCLUDE_CHECKINGDL=false
CACHE_AGENT="${QBIT_CACHE_AGENT:-$SCRIPT_DIR/qb-cache-agent.py}"
QB_ACTION_HELPER="${QBIT_ACTION_HELPER:-$SCRIPT_DIR/qb-action.py}"
CACHE_CLIENT_ID="${SCRIPT_NAME}:$$"
IGNORE_HASHES=""
IGNORE_HASHES_FILE=""
DEFAULT_IGNORE_HASHES_FILE="${QBIT_IGNORE_HASHES_FILE:-/tmp/qb-stoppeddl-bucket-live/download-whitelist-hashes.txt}"
GUARD_RECHECK_ALLOWLIST_FILE="${QBIT_GUARD_RECHECK_ALLOWLIST_FILE:-/tmp/qb-stoppeddl-bucket-live/guard-recheck-allowlist.json}"

usage_short() {
  cat <<EOF
Usage: $SCRIPT_NAME [--apply] [--resume] [--daemon] [--min-batch N] [--poll N] [--cache] [--no-cache] [--cache-max-age N] [--guard-stop-cooldown N] [--guard-cooldown-state PATH] [--guard-include-checkingdl] [--guard-recheck-allowlist-file PATH] [--ignore-hashes CSV] [--ignore-hashes-file PATH] [-h|--help]
Try '$SCRIPT_NAME --help' for details.
EOF
}

usage_help() {
  cat <<'EOF'
qb-start-seeding-gradual.sh

Purpose:
  Gradually start stoppedUP torrents in escalating batches with safety checks.
  In daemon mode, it polls qB and runs the ramp automatically when the
  stoppedUP threshold is met.

Usage:
  bin/qb-start-seeding-gradual.sh [OPTIONS]

Options:
  --apply
      Execute changes (default is dry-run).

  --resume
      Skip torrents already in seeding states.

  --daemon
      Run continuously. Poll qB and trigger ramp when stoppedUP count is
      >= --min-batch.

  --guard-only
      Guard mode. Never starts torrents.
      Scans protected scope and immediately stops active download states
      (downloading/stalledDL/queuedDL/forcedDL/metaDL) found there.
      Useful to prevent unexpected downloads while you investigate.

  --guard-include-checkingdl
      Also treat checkingDL as dangerous in guard mode.
      Default: disabled, so active rechecks are not auto-stopped.

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
      directly on every read. Default: enabled.

  --no-cache
      Bypass shared cache and query qB API directly for torrents/info reads.

  --cache-max-age N
      Maximum cache age in seconds when --cache is enabled.
      Smaller values request a fresher snapshot.
      Default: 15

  --guard-stop-cooldown N
      Guard-only mode: suppress repeated stop requests for the same hash for
      N seconds. This reduces stop spam when hashes repeatedly re-enter
      download-like states during churn.
      Default: 120

  --guard-cooldown-state PATH
      JSON file used to track last stop timestamp per hash for cooldown logic.
      Default:
      ~/.logs/hashall/reports/qbit-triage/guard-stop-cooldown.json

  --guard-recheck-allowlist-file PATH
      JSON TTL map {hash: expires_epoch} used to exempt active repair rechecks
      from guard stopping.
      Default:
      /tmp/qb-stoppeddl-bucket-live/guard-recheck-allowlist.json

  --ignore-hashes CSV
      Hashes/prefixes to exclude from watch and candidate logic.

  --ignore-hashes-file PATH
      Ignore hash file (one hash/prefix per line; # comments allowed).
      If omitted, defaults to:
      /tmp/qb-stoppeddl-bucket-live/download-whitelist-hashes.txt
      when that file exists.

  -h, --help
      Show this detailed help and exit.

Examples:
  # Show detailed help
  bin/qb-start-seeding-gradual.sh --help

  # One-shot dry-run
  bin/qb-start-seeding-gradual.sh --resume

  # Daemon mode, live apply, check every 60s
  bin/qb-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 60

  # Same, but read qB state via shared cache (max age 5s)
  bin/qb-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 60 --cache --cache-max-age 5

  # Guard-only daemon: never starts, only auto-stops download-like flips
  bin/qb-start-seeding-gradual.sh --daemon --guard-only --apply --poll 5 --cache --cache-max-age 5

  # Guard-only with 5-minute stop cooldown per hash
  bin/qb-start-seeding-gradual.sh --daemon --guard-only --apply --poll 5 --guard-stop-cooldown 300

  # Ignore a known legacy downloader by hash prefix
  bin/qb-start-seeding-gradual.sh --daemon --apply --ignore-hashes 102b7bf38155
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
    --guard-only) GUARD_ONLY=true; shift ;;
    --min-batch)  MIN_BATCH="$2"; shift 2 ;;
    --poll)       POLL="$2"; shift 2 ;;
    --cache)      USE_CACHE=true; shift ;;
    --no-cache)   USE_CACHE=false; shift ;;
    --cache-max-age) CACHE_MAX_AGE="$2"; shift 2 ;;
    --guard-stop-cooldown) GUARD_STOP_COOLDOWN="$2"; shift 2 ;;
    --guard-cooldown-state) GUARD_COOLDOWN_STATE="$2"; shift 2 ;;
    --guard-include-checkingdl) GUARD_INCLUDE_CHECKINGDL=true; shift ;;
    --no-guard-include-checkingdl) GUARD_INCLUDE_CHECKINGDL=false; shift ;;
    --guard-recheck-allowlist-file) GUARD_RECHECK_ALLOWLIST_FILE="$2"; shift 2 ;;
    --ignore-hashes) IGNORE_HASHES="$2"; shift 2 ;;
    --ignore-hashes-file) IGNORE_HASHES_FILE="$2"; shift 2 ;;
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
if ! [[ "$GUARD_STOP_COOLDOWN" =~ ^[0-9]+$ ]] || [[ "$GUARD_STOP_COOLDOWN" -lt 0 ]]; then
  echo "--guard-stop-cooldown must be a non-negative integer" >&2
  exit 2
fi
if [[ "$USE_CACHE" == true && ! -f "$CACHE_AGENT" ]]; then
  echo "--cache enabled but cache agent not found: $CACHE_AGENT" >&2
  exit 2
fi
if [[ "$APPLY" == true && ! -f "$QB_ACTION_HELPER" ]]; then
  echo "qB action helper not found: $QB_ACTION_HELPER" >&2
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
TMPIGNORE=$(mktemp /tmp/qb_sg_ignore.XXXXXX)   # normalized ignore hashes/prefixes

# Persistent daemon log (only used when --daemon is active)
DAEMON_LOG="$LOGDIR/daemon.log"
DAEMON_HALT_RESET="$LOGDIR/daemon-halt-reset"
GUARD_COOLDOWN_STATE="${GUARD_COOLDOWN_STATE:-$LOGDIR/guard-stop-cooldown.json}"

# Per-run log file; set once here for one-shot mode, overridden per-run in daemon mode
LOG="$LOGDIR/start-seeding-gradual-$(date +%Y%m%d-%H%M%S).log"

_DAEMON_EXIT=false

_cleanup() {
  rm -f "$COOKIE" "$TMPJSON" "$TMPWATCH" "$TMPHALT" "$TMPCHECK" "$TMPBASE_DL" "$TMPCURR_DL" "$TMPFLIP_DL" "$TMPIGNORE"
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

qb_action() {
  local action="$1"
  local hashes="$2"
  QBIT_URL="$QB_URL" QBIT_USER="$QB_USER" QBIT_PASS="$QB_PASS" \
    python3 "$QB_ACTION_HELPER" "$action" "$hashes"
}

qb_action_best_effort() {
  local action="$1"
  local hashes="$2"
  local label="$3"
  local output=""
  if output="$(qb_action "$action" "$hashes" 2>&1)"; then
    log "  ${label}: $output"
  else
    log "  ${label} failed: ${output:-unknown_error}"
  fi
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
  local ignore_file="$2"
  python3 - "$data_file" "$ignore_file" << 'PYEOF'
import json, sys
from datetime import datetime

data = json.load(open(sys.argv[1]))
ignore = [line.strip().lower() for line in open(sys.argv[2]).read().splitlines() if line.strip()]
def ignored(h):
    h = str(h or "").strip().lower()
    if not h:
        return False
    return any(h == p or h.startswith(p) for p in ignore)
today = datetime.now()
today_start = int(datetime(today.year, today.month, today.day).timestamp())

for t in data:
    h = str(t.get("hash", "")).strip()
    if not h:
        continue
    if ignored(h):
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

build_ignore_hashes() {
  python3 - "$IGNORE_HASHES" "$IGNORE_HASHES_FILE" "$DEFAULT_IGNORE_HASHES_FILE" << 'PYEOF'
import sys
from pathlib import Path

def parse_tokens(text: str):
    if not text:
        return []
    for ch in ("|", ",", "\n", "\t"):
        text = text.replace(ch, " ")
    out = []
    seen = set()
    for tok in text.split():
        h = tok.strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out

inline, explicit_file, default_file = sys.argv[1], sys.argv[2], sys.argv[3]
vals = []
vals.extend(parse_tokens(inline))
src = ""
if explicit_file:
    src = explicit_file
elif Path(default_file).exists():
    src = default_file
if src and Path(src).exists():
    lines = []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    vals.extend(parse_tokens(" ".join(lines)))

# De-dup stable order
seen = set()
for h in vals:
    if h in seen:
        continue
    seen.add(h)
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

  build_ignore_hashes > "$TMPIGNORE" || true
  IGNORE_COUNT=$(grep -c . "$TMPIGNORE" 2>/dev/null || true)
  if [[ "$IGNORE_COUNT" -gt 0 ]]; then
    local ignore_src="$IGNORE_HASHES_FILE"
    if [[ -z "$ignore_src" && -f "$DEFAULT_IGNORE_HASHES_FILE" ]]; then
      ignore_src="$DEFAULT_IGNORE_HASHES_FILE"
    fi
    log "  ignore hash filters loaded: $IGNORE_COUNT source=${ignore_src:-inline}"
  fi

  # Build protected watch scope: all torrents added before today (fail-closed on unknown added_on).
  if ! build_watch_scope_before_today "$TMPJSON" "$TMPIGNORE" > "$TMPWATCH"; then
    log "ERROR: unable to derive protected watch scope"
    return 1
  fi
  WATCH_TOTAL=$(grep -c . "$TMPWATCH" 2>/dev/null || true)
  log "  protected watch scope (added before today): $WATCH_TOTAL"
  if ! python3 - "$TMPJSON" "$TMPWATCH" << 'PYEOF' > "$TMPBASE_DL"
import json, sys
data = json.load(open(sys.argv[1]))
watch = set(open(sys.argv[2]).read().split())
download_bad = {'downloading','stalledDL'}
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
    log "  baseline downloading-like in watch scope: $BASE_DL_COUNT (gate: only newly flipped downloading-like state halts)"
  fi

  # Collect stoppedUP hashes (100% progress, not seeding yet)
  CANDIDATES=$(python3 - "$TMPJSON" "$resume_flag" "$TMPIGNORE" << 'PYEOF'
import json, sys

data_file, resume_flag = sys.argv[1], sys.argv[2] == "true"
ignore = [line.strip().lower() for line in open(sys.argv[3]).read().splitlines() if line.strip()]
def ignored(h):
    h = str(h or "").strip().lower()
    if not h:
        return False
    return any(h == p or h.startswith(p) for p in ignore)
data = json.load(open(data_file))

good_seeding = {"stalledUP", "uploading", "queuedUP", "forcedUP"}

hashes = []
already_seeding = 0
for t in data:
    h = str(t.get("hash", "")).strip()
    if not h or ignored(h):
        continue
    s = t.get("state", "")
    p = t.get("progress", 0)
    if s == "stoppedUP" and abs(p - 1.0) < 0.0001:
        hashes.append(h)
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
      PIPE=$(IFS='|'; echo "${batch[*]}")
      if START_OUT="$(qb_action resume "$PIPE" 2>&1)"; then
        log "  start request: $START_OUT"
      else
        log "  ERROR: start request failed: ${START_OUT:-unknown_error}"
        echo "safety_check_failed:start_request:$PIPE" > "$TMPHALT"
        failures=$(( failures + bsize ))
        ramp_halted=true
        break
      fi
      total_started=$(( total_started + bsize ))

      log "  waiting ${SETTLE_SECS}s for state to settle..."
      sleep "$SETTLE_SECS"

      # Check protected watch scope for bad states (read watch list from file, not arg)
      if ! fetch_torrents_info 3 2; then
        log "  ERROR: unable to fetch state after settle window; stopping batch and halting."
        PIPE=$(IFS='|'; echo "${batch[*]}")
        qb_action_best_effort pause "$PIPE" "stop request sent for batch"
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
download_bad = {'downloading','stalledDL'}
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
        qb_action_best_effort pause "$PIPE" "stop request sent for batch"
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
        qb_action_best_effort pause "$PIPE" "stop request sent for batch"
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
        qb_action_best_effort pause "$PIPE" "stop request sent for batch"
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
        log "WARNING: newly flipped downloading-like state detected in protected scope — stopping affected torrents immediately:"
        BAD_HASHES=""
        if [[ -s "$TMPFLIP_DL" ]]; then
          BAD_HASHES="$(paste -sd'|' "$TMPFLIP_DL")"
          python3 - "$TMPCHECK" "$TMPFLIP_DL" << 'PYEOF' | tee -a "$LOG" >/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
flips = set(open(sys.argv[2]).read().split())
for h, s, p in d.get('downloading', []):
    if h in flips:
        print(f'  {h[:12]}  {s}  {p:.4f}')
PYEOF
        fi
        if [[ -n "$BAD_HASHES" ]]; then
          qb_action_best_effort pause "$BAD_HASHES" "stop request sent for"
        else
          log "  stop request skipped: no concrete flipped hashes resolved"
        fi
        log ""
        log "HALTED — check the torrents listed above."
        # Record halt hashes for daemon error state
        echo "$BAD_HASHES" > "$TMPHALT"
        failures=$(( failures + CURR_DL_COUNT ))
        ramp_halted=true
        break
      fi

      if [[ "$PREEXIST_DL_COUNT" -gt 0 ]]; then
        log "  note: preexisting downloading-like torrents remain in protected scope but did not newly flip this batch"
      fi

      if [[ "$N_BAD" -gt 0 ]]; then
        log ""
        log "WARNING: bad state detected in protected scope — stopping affected torrents and halting:"
        BAD_HASHES=$(python3 - "$TMPCHECK" << 'PYEOF' | tee -a "$LOG" | grep '^HASHES:' | sed 's/^HASHES://'
import json, sys
d = json.load(open(sys.argv[1]))
selected = []
for h, s, p in d.get('other_bad', []):
    selected.append((h, s, p))
    print(f'  {h}  {s}  {p:.4f}')
print('HASHES:' + '|'.join(h for h, s, p in selected))
PYEOF
)
        if [[ -n "$BAD_HASHES" ]]; then
          qb_action_best_effort pause "$BAD_HASHES" "stop request sent for"
        else
          log "  stop request skipped: no concrete bad-state hashes resolved"
        fi
        log ""
        log "HALTED — check the torrents listed above."
        echo "$BAD_HASHES" > "$TMPHALT"
        failures=$(( failures + N_BAD ))
        ramp_halted=true
        break
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
# run_guard_pass — never starts torrents; only detects/stops active download
# in protected watch scope.
# Returns:
#   0 => clean (no downloading-like in protected scope)
#   1 => error
#   2 => downloading-like detected (and stopped when --apply=true)
# ---------------------------------------------------------------------------
run_guard_pass() {
  if [[ "$USE_CACHE" != true ]]; then
    qb_login
  fi

  if ! fetch_torrents_info 3 1; then
    log "ERROR: guard pass unable to fetch torrent list"
    return 1
  fi

  build_ignore_hashes > "$TMPIGNORE" || true
  if ! build_watch_scope_before_today "$TMPJSON" "$TMPIGNORE" > "$TMPWATCH"; then
    log "ERROR: guard pass unable to derive protected watch scope"
    return 1
  fi

  if ! python3 - "$TMPJSON" "$TMPWATCH" "$GUARD_RECHECK_ALLOWLIST_FILE" "$GUARD_INCLUDE_CHECKINGDL" << 'PYEOF' > "$TMPCHECK"
import json, sys, time
from pathlib import Path
data = json.load(open(sys.argv[1]))
watch = set(open(sys.argv[2]).read().split())
allowlist_path = Path(sys.argv[3]).expanduser()
include_checking = str(sys.argv[4] or "").strip().lower() in {"1", "true", "yes", "on"}
now = int(time.time())
allowlist = {}
if allowlist_path.exists():
    try:
        raw = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            h = str(k or "").strip().lower()
            if len(h) != 40:
                continue
            try:
                exp = int(v)
            except Exception:
                continue
            if exp > now:
                allowlist[h] = exp
        # Prune stale/invalid entries on read.
        cleaned = {k: int(v) for k, v in allowlist.items() if int(v) > now}
        if cleaned != raw:
            try:
                allowlist_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = allowlist_path.with_suffix(allowlist_path.suffix + ".tmp")
                tmp.write_text(json.dumps(cleaned, sort_keys=True) + "\n", encoding="utf-8")
                tmp.replace(allowlist_path)
            except Exception:
                pass
download_bad = {'downloading', 'stalledDL', 'queuedDL', 'forcedDL', 'metaDL'}
if include_checking:
    download_bad.add('checkingDL')
bad = []
exempted = []
for t in data:
    h = str(t.get("hash", "")).strip()
    if not h or h not in watch:
        continue
    s = t.get("state", "")
    p = t.get("progress", 0)
    if h.lower() in allowlist:
        if s in download_bad:
            exempted.append([h, s, p, int(allowlist[h.lower()])])
        continue
    if s in download_bad:
        bad.append([h, s, p])
print(json.dumps({"downloading": bad, "allowlist_exempted": exempted, "allowlist_size": len(allowlist)}))
PYEOF
  then
    log "ERROR: guard pass unable to parse state payload"
    return 1
  fi

  local bad_count
  bad_count="$(python3 - "$TMPCHECK" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
print(len(d.get("downloading", [])))
PYEOF
)"
  local allowlist_exempt_count
  allowlist_exempt_count="$(python3 - "$TMPCHECK" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
print(len(d.get("allowlist_exempted", [])))
PYEOF
)"
  if [[ "$allowlist_exempt_count" -gt 0 ]]; then
    log "guard: allowlist exempted active rechecks: $allowlist_exempt_count file=$GUARD_RECHECK_ALLOWLIST_FILE"
  fi

  if [[ "$bad_count" -le 0 ]]; then
    log "guard: clean (no downloading-like in protected scope)"
    return 0
  fi

  log "guard: downloading-like detected in protected scope: $bad_count"
  local bad_hashes
  bad_hashes="$(python3 - "$TMPCHECK" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
rows = d.get("downloading", [])
for h, s, p in rows:
    print(f"  {h[:12]}  {s}  {p:.4f}")
print("HASHES:" + "|".join(h for h, _, _ in rows))
PYEOF
)"
  echo "$bad_hashes" | tee -a "$LOG" >/dev/null
  bad_hashes="$(echo "$bad_hashes" | awk -F'HASHES:' 'NF>1{print $2}' | tail -n1)"

  if [[ "$APPLY" == true && -n "$bad_hashes" ]]; then
    local stop_hashes="$bad_hashes"
    local suppressed_hashes=""
    if [[ "$GUARD_STOP_COOLDOWN" -gt 0 ]]; then
      local cooldown_lines
      cooldown_lines="$(python3 - "$GUARD_COOLDOWN_STATE" "$GUARD_STOP_COOLDOWN" "$bad_hashes" << 'PYEOF'
import json
import os
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1]).expanduser()
cooldown = max(0, int(sys.argv[2]))
raw_hashes = str(sys.argv[3] or "")
hashes = [h.strip().lower() for h in raw_hashes.split("|") if h.strip()]
now = int(time.time())

state = {}
if state_path.exists():
    try:
        obj = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            state = {str(k).lower(): int(v or 0) for k, v in obj.items()}
    except Exception:
        state = {}

stop = []
supp = []
for h in hashes:
    last = int(state.get(h, 0) or 0)
    if (now - last) >= cooldown:
        stop.append(h)
    else:
        supp.append(h)

for h in stop:
    state[h] = now

ttl = max(3600, cooldown * 20)
state = {
    str(k).lower(): int(v or 0)
    for k, v in state.items()
    if now - int(v or 0) <= ttl
}

state_path.parent.mkdir(parents=True, exist_ok=True)
tmp = state_path.with_suffix(state_path.suffix + ".tmp")
tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
os.replace(str(tmp), str(state_path))

print("STOP:" + "|".join(stop))
print("SUPP:" + "|".join(supp))
PYEOF
)"
      if [[ -n "$cooldown_lines" ]]; then
        stop_hashes="$(echo "$cooldown_lines" | awk -F'STOP:' 'NF>1{print $2}' | tail -n1)"
        suppressed_hashes="$(echo "$cooldown_lines" | awk -F'SUPP:' 'NF>1{print $2}' | tail -n1)"
      else
        log "guard: cooldown parser produced no output; falling back to stop all detected hashes"
        stop_hashes="$bad_hashes"
      fi
      local stop_count=0
      local suppress_count=0
      if [[ -n "$stop_hashes" ]]; then
        stop_count="$(awk -F'|' '{print NF}' <<<"$stop_hashes")"
      fi
      if [[ -n "$suppressed_hashes" ]]; then
        suppress_count="$(awk -F'|' '{print NF}' <<<"$suppressed_hashes")"
      fi
      log "guard: cooldown=${GUARD_STOP_COOLDOWN}s stop_now=${stop_count} suppressed=${suppress_count} state=${GUARD_COOLDOWN_STATE}"
    fi
    if [[ -n "$stop_hashes" ]]; then
      qb_action_best_effort pause "$stop_hashes" "guard: stop request sent for"
    else
      log "guard: stop suppressed by cooldown (no stop request sent this pass)"
    fi
  elif [[ "$APPLY" != true ]]; then
    log "guard: [dry-run] would stop detected downloading-like hashes"
  fi
  return 2
}

# ---------------------------------------------------------------------------
# One-shot mode (no --daemon)
# ---------------------------------------------------------------------------
if [[ "$DAEMON" == false ]]; then
  if [[ "$GUARD_ONLY" == true ]]; then
    if run_guard_pass; then
      exit 0
    else
      rc=$?
      if [[ "$rc" -eq 2 ]]; then
        exit 0
      fi
      exit "$rc"
    fi
  fi
  run_ramp_start
  exit $?
fi

# ---------------------------------------------------------------------------
# Daemon mode
# ---------------------------------------------------------------------------
echo "════════════════════════════════════════════════════════════"
echo "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
echo "daemon mode  apply=$APPLY  guard_only=$GUARD_ONLY  min-batch=$MIN_BATCH  poll=${POLL}s  cache=$USE_CACHE  cache_max_age=${CACHE_MAX_AGE}s  guard_stop_cooldown=${GUARD_STOP_COOLDOWN}s  guard_include_checkingdl=${GUARD_INCLUDE_CHECKINGDL}  guard_cooldown_state=${GUARD_COOLDOWN_STATE}  guard_allowlist_file=${GUARD_RECHECK_ALLOWLIST_FILE}  ignore_file=${IGNORE_HASHES_FILE:-${DEFAULT_IGNORE_HASHES_FILE}}"
echo "daemon log: $DAEMON_LOG"
echo "reset file:  $DAEMON_HALT_RESET"
echo "════════════════════════════════════════════════════════════"

{
  echo "════════════════════════════════════════════════════════════"
  echo "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
  echo "daemon mode  apply=$APPLY  guard_only=$GUARD_ONLY  min-batch=$MIN_BATCH  poll=${POLL}s  cache=$USE_CACHE  cache_max_age=${CACHE_MAX_AGE}s  guard_stop_cooldown=${GUARD_STOP_COOLDOWN}s  guard_include_checkingdl=${GUARD_INCLUDE_CHECKINGDL}  guard_cooldown_state=${GUARD_COOLDOWN_STATE}  guard_allowlist_file=${GUARD_RECHECK_ALLOWLIST_FILE}  ignore_file=${IGNORE_HASHES_FILE:-${DEFAULT_IGNORE_HASHES_FILE}}"
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

  if [[ "$GUARD_ONLY" == true ]]; then
    if run_guard_pass; then
      echo "$(date '+%F %T') [daemon] Guard pass clean" | tee -a "$DAEMON_LOG"
    else
      rc=$?
      RUN_TS="$(date +%Y%m%d-%H%M%S)"
      LOG="$LOGDIR/start-seeding-gradual-guard-${RUN_TS}.log"
      if [[ "$rc" -eq 2 ]]; then
        echo "$(date '+%F %T') [daemon] Guard pass stopped downloading-like torrents — log: $LOG" | tee -a "$DAEMON_LOG"
      else
        echo "$(date '+%F %T') [daemon] Guard pass error (rc=$rc) — log: $LOG" | tee -a "$DAEMON_LOG"
      fi
    fi
    sleep "$POLL"
    continue
  fi

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
