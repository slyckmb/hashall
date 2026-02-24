#!/usr/bin/env bash
# Fix torrent save_path and/or clear the download_path (incomplete download location).
#
# The qBittorrent API setDownloadPath returns 400 for paths outside its configured
# defaults, so clearing download_path requires editing the .fastresume file on disk
# and restarting qBittorrent to reload it.
#
# Usage:
#   bin/qbit-fix-location.sh [OPTIONS] HASH [HASH2 ...]
#
# Options:
#   --save-path PATH    Update save_path via setLocation API (no restart needed)
#   --clear-dl-path     Clear qBt-downloadPath in .fastresume (requires QB restart)
#   --recheck           Trigger recheckTorrents after changes
#   --monitor N         After recheck, poll for N seconds; stop if torrent goes active
#   --apply             Execute changes (default: dry-run, print what would happen)
#
# Examples:
#   # Dry-run: show what would happen
#   bin/qbit-fix-location.sh --save-path /pool/data/seeds/cross-seed/TL --clear-dl-path --recheck abc123
#
#   # Clear download_path + recheck + monitor 120s on one hash
#   bin/qbit-fix-location.sh --clear-dl-path --recheck --monitor 120 --apply abc123
#
#   # Set new save path only (no restart needed)
#   bin/qbit-fix-location.sh --save-path /new/path --apply abc123 def456

set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
BT_BACKUP="/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
QB_CONTAINER="qbittorrent_vpn"

# ── parse args ─────────────────────────────────────────────────────────────────
SAVE_PATH=""
CLEAR_DL_PATH=false
DO_RECHECK=false
MONITOR_SECS=0
APPLY=false
HASHES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --save-path)    SAVE_PATH="$2"; shift 2 ;;
    --clear-dl-path) CLEAR_DL_PATH=true; shift ;;
    --recheck)      DO_RECHECK=true; shift ;;
    --monitor)      MONITOR_SECS="$2"; shift 2 ;;
    --apply)        APPLY=true; shift ;;
    --*)            echo "Unknown option: $1" >&2; exit 1 ;;
    *)              HASHES+=("$1"); shift ;;
  esac
done

if [[ ${#HASHES[@]} -eq 0 ]]; then
  echo "Usage: $0 [--save-path PATH] [--clear-dl-path] [--recheck] [--monitor N] [--apply] HASH [HASH2 ...]" >&2
  exit 1
fi

if [[ -z "$SAVE_PATH" && "$CLEAR_DL_PATH" == false ]]; then
  echo "ERROR: specify at least --save-path PATH or --clear-dl-path" >&2
  exit 1
fi

# ── QB auth helper ─────────────────────────────────────────────────────────────
COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}

qb_wait_up() {
  local tries=0
  while [[ $tries -lt 30 ]]; do
    if curl -fsS --max-time 3 "$QB_URL/api/v2/app/version" >/dev/null 2>&1; then
      qb_login
      return 0
    fi
    sleep 2
    (( tries++ )) || true
  done
  echo "ERROR: qBittorrent did not come back up within 60s" >&2
  return 1
}

qb_torrent_info() {
  local hash="$1"
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" | \
    python3 -c "
import sys,json
ts=[t for t in json.load(sys.stdin) if t['hash']=='$hash']
if not ts: print('NOT_FOUND'); sys.exit(0)
t=ts[0]
print(t['state'])
print(t.get('download_path',''))
print(t['save_path'])
print(t['progress'])
"
}

# ── fastresume patcher (Python, inline) ────────────────────────────────────────
py_patch_fastresume() {
  python3 - "$1" <<'PYEOF'
import sys, os

path = sys.argv[1]

def bdecode(data, idx=0):
    c = chr(data[idx])
    if c == 'i':
        end = data.index(b'e', idx+1)
        return int(data[idx+1:end]), end+1
    elif c == 'l':
        lst, idx = [], idx+1
        while chr(data[idx]) != 'e':
            v, idx = bdecode(data, idx)
            lst.append(v)
        return lst, idx+1
    elif c == 'd':
        d, idx = {}, idx+1
        while chr(data[idx]) != 'e':
            k, idx = bdecode(data, idx)
            v, idx = bdecode(data, idx)
            d[k] = v
        return d, idx+1
    else:
        colon = data.index(b':', idx)
        length = int(data[idx:colon])
        start = colon+1
        return data[start:start+length], start+length

def bencode(v):
    if isinstance(v, int):
        return b'i' + str(v).encode() + b'e'
    elif isinstance(v, bytes):
        return str(len(v)).encode() + b':' + v
    elif isinstance(v, str):
        enc = v.encode()
        return str(len(enc)).encode() + b':' + enc
    elif isinstance(v, list):
        return b'l' + b''.join(bencode(x) for x in v) + b'e'
    elif isinstance(v, dict):
        # keys must be sorted for bencoding
        result = b'd'
        for k in sorted(v.keys()):
            result += bencode(k) + bencode(v[k])
        return result + b'e'
    else:
        raise ValueError(f"cannot bencode {type(v)}: {v!r}")

if not os.path.exists(path):
    print(f"MISSING: {path}", file=sys.stderr)
    sys.exit(1)

with open(path, 'rb') as f:
    data = f.read()

d, _ = bdecode(data)

old_val = d.get(b'qBt-downloadPath', b'<absent>')
if isinstance(old_val, bytes):
    old_str = old_val.decode('utf-8', errors='replace')
else:
    old_str = str(old_val)

if old_val == b'' or old_val == b'<absent>':
    print(f"OK (already empty): qBt-downloadPath={old_str!r}")
    sys.exit(0)

# Clear it
d[b'qBt-downloadPath'] = b''

new_data = bencode(d)
# Write atomically
tmp = path + '.tmp'
with open(tmp, 'wb') as f:
    f.write(new_data)
os.replace(tmp, path)

print(f"CLEARED: qBt-downloadPath was {old_str!r} → now empty")
PYEOF
}

# ── print plan ─────────────────────────────────────────────────────────────────
echo "================================================================"
echo "qbit-fix-location  [APPLY=$APPLY]  $(date '+%F %T')"
echo "================================================================"
echo "Hashes:         ${#HASHES[@]}"
[[ -n "$SAVE_PATH" ]]         && echo "save-path:      $SAVE_PATH"
[[ "$CLEAR_DL_PATH" == true ]] && echo "clear-dl-path:  yes (requires QB restart)"
[[ "$DO_RECHECK" == true ]]   && echo "recheck:        yes"
[[ "$MONITOR_SECS" -gt 0 ]]   && echo "monitor:        ${MONITOR_SECS}s"
echo ""

# ── PHASE 1: setLocation (no restart needed) ───────────────────────────────────
if [[ -n "$SAVE_PATH" ]]; then
  echo "--- phase 1: setLocation ---"
  qb_login
  for HASH in "${HASHES[@]}"; do
    echo -n "  setLocation [$HASH] → $SAVE_PATH : "
    if [[ "$APPLY" == true ]]; then
      HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
        -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/setLocation" \
        --data-urlencode "hashes=${HASH}" \
        --data-urlencode "location=${SAVE_PATH}")
      echo "HTTP $HTTP"
    else
      echo "[dry-run]"
    fi
  done
  echo ""
fi

# ── PHASE 2: clear download_path in fastresume (requires QB restart) ───────────
if [[ "$CLEAR_DL_PATH" == true ]]; then
  echo "--- phase 2: clear qBt-downloadPath in .fastresume ---"

  # Preview what we'd do
  for HASH in "${HASHES[@]}"; do
    FR="$BT_BACKUP/${HASH}.fastresume"
    if [[ ! -f "$FR" ]]; then
      echo "  MISSING fastresume: $HASH"
      continue
    fi
    CURRENT_DL_PATH=$(python3 -c "
import sys
def bdecode(data, idx=0):
    c = chr(data[idx])
    if c == 'i':
        end = data.index(b'e', idx+1); return int(data[idx+1:end]), end+1
    elif c == 'l':
        lst, idx = [], idx+1
        while chr(data[idx]) != 'e': v, idx = bdecode(data, idx); lst.append(v)
        return lst, idx+1
    elif c == 'd':
        d, idx = {}, idx+1
        while chr(data[idx]) != 'e': k, idx = bdecode(data, idx); v, idx = bdecode(data, idx); d[k] = v
        return d, idx+1
    else:
        colon = data.index(b':', idx); length = int(data[idx:colon]); start = colon+1
        return data[start:start+length], start+length
with open('$FR','rb') as f: data=f.read()
d,_=bdecode(data)
v=d.get(b'qBt-downloadPath',b'')
print(v.decode('utf-8',errors='replace') if isinstance(v,bytes) else str(v))
" 2>/dev/null || echo "?")
    echo "  [$HASH] dl_path: '${CURRENT_DL_PATH}' → '' "
  done
  echo ""

  if [[ "$APPLY" == true ]]; then
    echo "  Stopping QB container: $QB_CONTAINER ..."
    docker stop "$QB_CONTAINER" >/dev/null
    echo "  QB stopped."
    echo ""

    for HASH in "${HASHES[@]}"; do
      FR="$BT_BACKUP/${HASH}.fastresume"
      echo -n "  patching $HASH : "
      py_patch_fastresume "$FR"
    done
    echo ""

    echo "  Starting QB container: $QB_CONTAINER ..."
    docker start "$QB_CONTAINER" >/dev/null
    echo -n "  Waiting for QB API"
    while ! curl -fsS --max-time 3 "$QB_URL/api/v2/app/version" >/dev/null 2>&1; do
      echo -n "."
      sleep 2
    done
    echo " up."
    qb_login
    echo ""

    # Verify the change stuck in qBittorrent's live state
    echo "  Verifying download_path in live QB state:"
    for HASH in "${HASHES[@]}"; do
      DL_PATH=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" | \
        python3 -c "
import sys,json
ts=[t for t in json.load(sys.stdin) if t['hash']=='$HASH']
print(ts[0].get('download_path','') if ts else 'NOT_FOUND')
" 2>/dev/null)
      if [[ -z "$DL_PATH" ]]; then
        echo "    [$HASH] download_path cleared OK"
      else
        echo "    [$HASH] WARNING: download_path still set: '$DL_PATH'"
      fi
    done
    echo ""
  fi
fi

# ── PHASE 3: recheckTorrents ───────────────────────────────────────────────────
if [[ "$DO_RECHECK" == true ]]; then
  echo "--- phase 3: recheckTorrents ---"
  HASH_LIST=$(printf '%s|' "${HASHES[@]}"); HASH_LIST="${HASH_LIST%|}"
  echo -n "  recheckTorrents (${#HASHES[@]} hashes) : "
  if [[ "$APPLY" == true ]]; then
    qb_login 2>/dev/null || true
    HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/recheck" \
      --data-urlencode "hashes=${HASH_LIST}")
    echo "HTTP $HTTP"
  else
    echo "[dry-run]"
  fi
  echo ""
fi

# ── PHASE 4: monitor + auto-stop if active ────────────────────────────────────
if [[ "$MONITOR_SECS" -gt 0 && "$APPLY" == true ]]; then
  echo "--- phase 4: monitor ${MONITOR_SECS}s, stop if active ---"
  END=$(( $(date +%s) + MONITOR_SECS ))

  declare -A FINAL_STATE
  for HASH in "${HASHES[@]}"; do FINAL_STATE[$HASH]="unknown"; done

  while [[ $(date +%s) -lt $END ]]; do
    sleep 5
    qb_login 2>/dev/null || true
    ALL_INFO=$(curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" 2>/dev/null)

    ALL_DONE=true
    for HASH in "${HASHES[@]}"; do
      STATE=$(echo "$ALL_INFO" | python3 -c "
import sys,json
ts=[t for t in json.load(sys.stdin) if t['hash']=='$HASH']
print(ts[0]['state'] if ts else 'not_found')
" 2>/dev/null)

      FINAL_STATE[$HASH]="$STATE"

      case "$STATE" in
        checkingDL|checkingUP|checkingResumeData)
          # Still rechecking — not done yet
          ALL_DONE=false
          ;;
        stoppedDL|stoppedUP|error|missingFiles|not_found)
          # Terminal / stable states — done
          ;;
        downloading|stalledDL|queuedDL|metaDL|\
        uploading|stalledUP|queuedUP|forcedUP|forcedDL)
          # Active state — stop it
          echo "  STOPPING [$HASH] — unexpected active state: $STATE"
          curl -sS -o /dev/null \
            -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=${HASH}"
          FINAL_STATE[$HASH]="stopped(was:$STATE)"
          ;;
        *)
          echo "  STOPPING [$HASH] — unknown state: $STATE (precautionary)"
          curl -sS -o /dev/null \
            -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=${HASH}"
          FINAL_STATE[$HASH]="stopped(was:$STATE)"
          ALL_DONE=false
          ;;
      esac
    done

    # Print progress line
    NOW=$(date '+%T')
    for HASH in "${HASHES[@]}"; do
      echo "  [$NOW] [$HASH] ${FINAL_STATE[$HASH]}"
    done

    if [[ "$ALL_DONE" == true ]]; then
      echo ""
      echo "  All torrents reached stable state — monitor done."
      break
    fi
  done

  echo ""
  echo "--- final states ---"
  for HASH in "${HASHES[@]}"; do
    echo "  [$HASH] ${FINAL_STATE[$HASH]}"
  done
  echo ""
fi

echo "================================================================"
echo "DONE  $(date '+%F %T')"
echo "================================================================"
