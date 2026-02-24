#!/usr/bin/env bash
# qbit-start-seeding-gradual.sh — gradually start stoppedUP torrents in escalating batches.
# Version: 1.0.1
# Date:    2026-02-24
#
# After each batch waits for state to settle, then checks no torrent flipped
# to a downloading/broken state. On any bad state: immediately stops the
# affected torrents and halts.
# Safe by default: dry-run unless --apply is passed.
# Idempotent: only targets stoppedUP (100%) torrents; already-started ones
# are stalledUP/uploading and are skipped automatically.
#
# Usage: bin/qbit-start-seeding-gradual.sh [--apply] [--resume]
#   --apply   Execute changes (dry-run if omitted)
#   --resume  Skip torrents already in stalledUP/uploading/queuedUP
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SCRIPT_VERSION="1.0.1"
SCRIPT_DATE="2026-02-24"

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"

WT="/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028"
LOGDIR="$WT/out/reports/qbit-triage"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/start-seeding-gradual-$(date +%Y%m%d-%H%M%S).log"

APPLY=false
RESUME=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)  APPLY=true; shift ;;
    --resume) RESUME=true; shift ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

COOKIE=$(mktemp /tmp/qb.XXXXXX)
TMPJSON=$(mktemp /tmp/qb_sg.XXXXXX)
TMPWATCH=$(mktemp /tmp/qb_sg_watch.XXXXXX)   # newline-separated started hashes
trap 'rm -f "$COOKIE" "$TMPJSON" "$TMPWATCH"' EXIT

log() { echo "$*" | tee -a "$LOG"; }

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}

qb_login

log "════════════════════════════════════════════════════════════"
log "$SCRIPT_NAME  v$SCRIPT_VERSION  ($SCRIPT_DATE)  $(date '+%F %T')"
log "apply=$APPLY  resume=$RESUME"
log "════════════════════════════════════════════════════════════"

# Fetch all torrents into temp file (avoids stdin conflicts with Python heredocs)
curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPJSON"

# Collect stoppedUP hashes (100% progress, not seeding yet)
CANDIDATES=$(python3 - "$TMPJSON" "$RESUME" << 'PYEOF'
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
if [[ "$TOTAL" -eq 0 ]]; then log "Nothing to start."; exit 0; fi

# Escalating batch sizes
BATCH_SIZES=(1 2 5 10 25 50 100 250 500 1000 9999)
SETTLE_SECS=45          # wait after start before checking
BAD_STATES="checkingDL|downloading|stalledDL|missingFiles|error"

# States that mean "is downloading content" — the critical failure mode
IS_DOWNLOADING='checkingDL|downloading|stalledDL|stoppedDL'

total_started=0
failures=0

mapfile -t all_hashes < <(echo "$CANDIDATES")

log ""
log "Batch plan: ${BATCH_SIZES[*]}"
log "Settle wait: ${SETTLE_SECS}s per batch"
log ""

offset=0
batch_num=0
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
    if s in download_bad or (s == 'stoppedDL' and p < 0.9999):
        results['downloading'].append([t['hash'][:12], s, p])
    elif s in other_bad:
        results['other_bad'].append([t['hash'][:12], s, p])
    elif s == 'stoppedUP':
        results['still_stopped'].append([t['hash'][:12], s, p])
    else:
        results['ok'].append(t['hash'][:12])
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
            log "⚠️  DOWNLOADING DETECTED — stopping affected torrents immediately:"
            BAD_HASHES=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
lines = [f'  {h}  {s}  {p:.4f}' for h,s,p in d['downloading']]
print('\n'.join(lines))
print('HASHES:' + '|'.join(h for h,s,p in d['downloading']))
" "$CHECK" | tee -a "$LOG" | grep '^HASHES:' | sed 's/^HASHES://')
            # Stop the bad ones
            curl -fsS -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
                --data-urlencode "hashes=$BAD_HASHES" >/dev/null 2>&1 || true
            log ""
            log "HALTED — check the torrents listed above."
            failures=$(( failures + N_DL ))
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
