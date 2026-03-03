#!/usr/bin/env bash
# Repair a broken torrent (stoppedDL) using a good torrent (stoppedUP 100%)
# from the same payload group.
#
# Usage: bin/qbit-repair-payload-group.sh --good HASH --broken HASH [--apply]
#
# Phases:
#   1. Validate (QB state)
#   2. Content analysis (catalog quick_hash per file)
#   3. Hardlink rebuild (same-fs: rm garbage, ln from good; cross-fs: setLocation)
#   4. QB fix (setLocation + clear qBt-downloadPath via fastresume + QB restart)
#   5. Recheck + monitor
#   6. Start + stable-seed verify (90s)
#   7. Track consecutive successes (resets on failure)
set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
DB="${HOME}/.hashall/catalog.db"
BT_BACKUP="/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
QB_CONTAINER="qbittorrent_vpn"
SUCCESS_FILE="$HOME/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt"
mkdir -p "$HOME/.logs/hashall/reports/qbit-triage"

GOOD_HASH=""
BROKEN_HASH=""
APPLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --good)   GOOD_HASH="$2"; shift 2 ;;
    --broken) BROKEN_HASH="$2"; shift 2 ;;
    --apply)  APPLY=true; shift ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done
[[ -z "$GOOD_HASH" || -z "$BROKEN_HASH" ]] && { echo "need --good and --broken" >&2; exit 1; }

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

LOGDIR="$HOME/.logs/hashall/reports/qbit-triage"
LOGFILE="$LOGDIR/qbit-repair-payload-$(date +%Y%m%d-%H%M%S)-${BROKEN_HASH:0:12}.log"
mkdir -p "$LOGDIR"
exec > >(tee -a "$LOGFILE") 2>&1
echo "Log: $LOGFILE"

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}
qb_info() { # $1=hash → prints JSON object
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" | \
    python3 -c "import sys,json; ts=[t for t in json.load(sys.stdin) if t['hash']=='$1']; print(json.dumps(ts[0]) if ts else 'null')"
}
qb_files() { # $1=hash → JSON array of {name,size}
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/files?hash=$1"
}
qb_wait_up() {
  local i=0
  while [[ $i -lt 30 ]]; do
    curl -fsS --max-time 3 "$QB_URL/api/v2/app/version" >/dev/null 2>&1 && { qb_login; return 0; }
    sleep 2; (( i++ )) || true
  done
  echo "QB did not come up" >&2; return 1
}

# ── bencode fastresume patcher ─────────────────────────────────────────────────
patch_fastresume() { # $1=fastresume_path
  python3 - "$1" << 'PYEOF'
import sys, os
path = sys.argv[1]
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
        colon = data.index(b':', idx); n = int(data[idx:colon]); s = colon+1
        return data[s:s+n], s+n
def bencode(v):
    if isinstance(v, int): return b'i'+str(v).encode()+b'e'
    elif isinstance(v, (bytes, bytearray)): return str(len(v)).encode()+b':'+bytes(v)
    elif isinstance(v, str): e=v.encode(); return str(len(e)).encode()+b':'+e
    elif isinstance(v, list): return b'l'+b''.join(bencode(x) for x in v)+b'e'
    elif isinstance(v, dict):
        r=b'd'
        for k in sorted(v.keys()): r+=bencode(k)+bencode(v[k])
        return r+b'e'
    raise ValueError(f"cannot bencode {type(v)}")
if not os.path.exists(path):
    print(f"MISSING {path}"); sys.exit(1)
with open(path,'rb') as f: data=f.read()
d,_=bdecode(data)
old=d.get(b'qBt-downloadPath',b'')
if isinstance(old,bytes): old_s=old.decode('utf-8',errors='replace')
else: old_s=str(old)
if not old_s:
    print("already empty"); sys.exit(0)
d[b'qBt-downloadPath']=b''
tmp=path+'.tmp'
with open(tmp,'wb') as f: f.write(bencode(d))
os.replace(tmp,path)
print(f"cleared: was '{old_s}'")
PYEOF
}

# ── catalog quick_hash lookup ──────────────────────────────────────────────────
catalog_qhash() { # $1=abs_path → quick_hash or ""
  local p="$1"
  local rel
  if [[ "$p" == /pool/data/* ]]; then
    rel="${p#/pool/data/}"
    sqlite3 "$DB" "SELECT COALESCE(quick_hash,'') FROM files_231 WHERE path='${rel}' AND status='active' LIMIT 1" 2>/dev/null || echo ""
  elif [[ "$p" == /stash/media/* ]]; then
    rel="${p#/stash/media/}"
    sqlite3 "$DB" "SELECT COALESCE(quick_hash,'') FROM files_44 WHERE path='${rel}' AND status='active' LIMIT 1" 2>/dev/null || echo ""
  else
    echo ""
  fi
}

# ── consecutive success counter ───────────────────────────────────────────────
get_streak() { [[ -f "$SUCCESS_FILE" ]] && cat "$SUCCESS_FILE" || echo 0; }
set_streak() { echo "$1" > "$SUCCESS_FILE"; }

# ══════════════════════════════════════════════════════════════════════════════
echo "━━━ REPAIR  good=${GOOD_HASH:0:12}  broken=${BROKEN_HASH:0:12}  apply=$APPLY ━━━"

# ── Phase 1: Validate ─────────────────────────────────────────────────────────
echo "▸ P1 validate"
qb_login
GOOD_JSON=$(qb_info "$GOOD_HASH")
BROKEN_JSON=$(qb_info "$BROKEN_HASH")

if [[ "$GOOD_JSON" == "null" ]]; then echo "FAIL: good hash not in QB"; exit 1; fi
if [[ "$BROKEN_JSON" == "null" ]]; then echo "FAIL: broken hash not in QB"; exit 1; fi

GOOD_STATE=$(echo "$GOOD_JSON"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])")
BROKEN_STATE=$(echo "$BROKEN_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])")
GOOD_PROG=$(echo "$GOOD_JSON"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['progress'])")

if [[ "$GOOD_STATE" != "stoppedUP" ]]; then echo "FAIL: good is $GOOD_STATE (need stoppedUP)"; exit 1; fi
if [[ "$BROKEN_STATE" != "stoppedDL" ]]; then echo "WARN: broken is $BROKEN_STATE (expected stoppedDL)"; fi

GOOD_SAVE=$(echo "$GOOD_JSON"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['save_path'])")
BROKEN_SAVE=$(echo "$BROKEN_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['save_path'])")
BROKEN_DLPATH=$(echo "$BROKEN_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('download_path','') or '')")
echo "  good  save=$GOOD_SAVE"
echo "  broken save=$BROKEN_SAVE  dl_path='$BROKEN_DLPATH'"

# Same filesystem?
SAME_FS=false
if   [[ "$GOOD_SAVE" == /pool/data/*   && "$BROKEN_SAVE" == /pool/data/* ]];   then SAME_FS=true; FS_TYPE="pool-pool"
elif [[ "$GOOD_SAVE" == /stash/media/* && "$BROKEN_SAVE" == /stash/media/* ]]; then SAME_FS=true; FS_TYPE="stash-stash"
elif [[ "$GOOD_SAVE" == /data/media/*  && "$BROKEN_SAVE" == /data/media/* ]];  then SAME_FS=true; FS_TYPE="stash-stash"
else FS_TYPE="cross-fs"; fi
echo "  fs=$FS_TYPE  same_fs=$SAME_FS"

# ── Phase 2: Content analysis ─────────────────────────────────────────────────
echo "▸ P2 content analysis"

# Get file list from QB, save to temp files
qb_login 2>/dev/null || true
qb_files "$GOOD_HASH"   > /tmp/repair_good_files.json
qb_files "$BROKEN_HASH" > /tmp/repair_broken_files.json

python3 /dev/fd/3 3<< PYEOF > /tmp/repair_plan.json
import json, os, sys

good_save   = """$GOOD_SAVE"""
broken_save = """$BROKEN_SAVE"""
same_fs     = $([[ "$SAME_FS" == "true" ]] && echo "True" || echo "False")
db = os.path.expanduser("~/.hashall/catalog.db")

good_files   = json.load(open("/tmp/repair_good_files.json"))
broken_files = json.load(open("/tmp/repair_broken_files.json"))

def abs_path(save, rel):
    return os.path.join(save, rel)

def catalog_qhash(abspath):
    import sqlite3
    con = sqlite3.connect(db)
    if abspath.startswith("/pool/data/"):
        rel = abspath[len("/pool/data/"):]
        row = con.execute("SELECT quick_hash FROM files_231 WHERE path=? AND status='active' LIMIT 1", (rel,)).fetchone()
    elif abspath.startswith("/stash/media/"):
        rel = abspath[len("/stash/media/"):]
        row = con.execute("SELECT quick_hash FROM files_44 WHERE path=? AND status='active' LIMIT 1", (rel,)).fetchone()
    elif abspath.startswith("/data/media/"):
        rel = "torrents/" + abspath[len("/data/media/torrents/"):]
        row = con.execute("SELECT quick_hash FROM files_44 WHERE path=? AND status='active' LIMIT 1", (rel,)).fetchone()
    else:
        row = None
    con.close()
    return row[0] if row and row[0] else None

# Build lookup by filename (basename of relative path)
# QB files API gives {name: relative_path_from_save_path, size: bytes}
good_by_name   = {}
for f in good_files:
    name = f["name"]
    ap   = abs_path(good_save, name)
    qh   = catalog_qhash(ap)
    good_by_name[os.path.basename(name)] = {"rel": name, "abs": ap, "size": f["size"], "qhash": qh}

broken_by_name = {}
for f in broken_files:
    name = f["name"]
    ap   = abs_path(broken_save, name)
    qh   = catalog_qhash(ap)
    broken_by_name[os.path.basename(name)] = {"rel": name, "abs": ap, "size": f["size"], "qhash": qh}

# Detect garbage: quick_hash appearing >1 times in broken = placeholder
from collections import Counter
broken_qhash_counts = Counter(v["qhash"] for v in broken_by_name.values() if v["qhash"])

plan = []
for bname, bf in broken_by_name.items():
    gf = good_by_name.get(bname)
    if gf is None:
        plan.append({"file": bname, "broken_abs": bf["abs"], "good_abs": None,
                      "action": "no_good_match", "broken_qhash": bf["qhash"], "good_qhash": None})
        continue

    bqh = bf["qhash"]
    gqh = gf["qhash"]

    # Already hardlinked?
    try:
        b_inode = os.stat(bf["abs"]).st_ino if os.path.exists(bf["abs"]) else 0
        g_inode = os.stat(gf["abs"]).st_ino if os.path.exists(gf["abs"]) else 0
    except: b_inode = g_inode = 0

    if b_inode and g_inode and b_inode == g_inode:
        action = "already_hardlinked"
    elif bqh and gqh and bqh == gqh:
        action = "dup_copy"   # same content, different inode → replace with hardlink
    elif not os.path.exists(bf["abs"]):
        action = "missing"    # file doesn't exist → create hardlink
    elif bqh and broken_qhash_counts.get(bqh, 0) > 1:
        action = "garbage"    # same qhash as other broken files = placeholder
    elif bqh != gqh and bqh is not None and gqh is not None:
        action = "garbage"    # qhash doesn't match good
    else:
        action = "unknown_keep"  # can't determine, leave as-is

    plan.append({
        "file": bname,
        "broken_abs": bf["abs"],
        "good_abs": gf["abs"],
        "action": action,
        "broken_qhash": bqh,
        "good_qhash": gqh,
        "same_inode": b_inode == g_inode if b_inode and g_inode else False,
    })

print(json.dumps(plan, indent=2))
PYEOF

python3 << 'PYEOF'
import json
plan = json.load(open("/tmp/repair_plan.json"))
from collections import Counter
counts = Counter(p["action"] for p in plan)
print(f"  files: {len(plan)}  " + "  ".join(f"{k}={v}" for k,v in sorted(counts.items())))
for p in plan:
    if p["action"] not in ("already_hardlinked",):
        print(f"    {p['action']:20} {p['file'][:60]}")
PYEOF

# ── Phase 3: Hardlink rebuild ─────────────────────────────────────────────────
echo "▸ P3 hardlink rebuild  same_fs=$SAME_FS"

if [[ "$SAME_FS" == "true" ]]; then
  if [[ "$APPLY" == true ]]; then
    python3 << 'PYEOF'
import json, os

plan = json.load(open("/tmp/repair_plan.json"))
rebuild_actions = {"garbage", "dup_copy", "missing"}

for p in plan:
    if p["action"] not in rebuild_actions:
        continue
    bad = p["broken_abs"]
    good = p["good_abs"]
    if not good or not os.path.exists(good):
        print(f"  SKIP (no good file): {p['file']}")
        continue
    # Remove broken file if it exists
    if os.path.exists(bad):
        os.remove(bad)
        print(f"  rm  {os.path.basename(bad)}")
    # Create hardlink
    os.makedirs(os.path.dirname(bad), exist_ok=True)
    os.link(good, bad)
    print(f"  ln  {os.path.basename(good)} → {os.path.dirname(bad)}")
print("  hardlink rebuild done")
PYEOF
  else
    echo "  [dry-run] would rebuild hardlinks for garbage/dup_copy/missing files"
  fi
else
  # Cross-filesystem: setLocation to good's save_path
  echo "  cross-fs: will setLocation broken → $GOOD_SAVE"
  BROKEN_SAVE="$GOOD_SAVE"
fi

# ── Phase 4: QB fix ────────────────────────────────────────────────────────────
echo "▸ P4 QB fix"

if [[ "$APPLY" == true ]]; then
  # setLocation (update save_path if needed or if cross-fs)
  if [[ "$SAME_FS" == "false" ]] || [[ "$BROKEN_SAVE" != "$GOOD_SAVE" ]]; then
    HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/setLocation" \
      --data-urlencode "hashes=${BROKEN_HASH}" \
      --data-urlencode "location=${BROKEN_SAVE}")
    echo "  setLocation HTTP $HTTP"
  else
    echo "  setLocation: save_path already correct"
  fi

  # Stop QB, patch fastresume, start QB
  FR="$BT_BACKUP/${BROKEN_HASH}.fastresume"
  if [[ -f "$FR" ]]; then
    echo "  stopping QB..."
    docker stop "$QB_CONTAINER" >/dev/null
    echo -n "  patching fastresume: "
    patch_fastresume "$FR"
    echo "  starting QB..."
    docker start "$QB_CONTAINER" >/dev/null
    echo -n "  waiting for QB API"
    while ! curl -fsS --max-time 3 "$QB_URL/api/v2/app/version" >/dev/null 2>&1; do echo -n "."; sleep 2; done
    echo " up"
    qb_login
    # Verify
    LIVE_DLPATH=$(qb_info "$BROKEN_HASH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('download_path','') or '')" 2>/dev/null || echo "?")
    [[ -z "$LIVE_DLPATH" ]] && echo "  download_path cleared OK" || echo "  WARN: download_path still '$LIVE_DLPATH'"
  else
    echo "  WARN: no fastresume at $FR"
  fi
else
  echo "  [dry-run] would setLocation + stop QB + patch fastresume + start QB"
fi

# ── Phase 5: Recheck + monitor ────────────────────────────────────────────────
echo "▸ P5 recheck + monitor"
if [[ "$APPLY" == true ]]; then
  qb_login 2>/dev/null || true
  HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/recheck" \
    --data-urlencode "hashes=${BROKEN_HASH}")
  echo "  recheckTorrents HTTP $HTTP"

  FINAL_STATE=""
  END=$(( $(date +%s) + 600 ))  # 10 min timeout
  while [[ $(date +%s) -lt $END ]]; do
    sleep 5
    qb_login 2>/dev/null || true
    STATE=$(qb_info "$BROKEN_HASH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'],d['progress'])" 2>/dev/null || echo "error 0")
    S=$(echo "$STATE" | cut -d' ' -f1)
    P=$(echo "$STATE" | cut -d' ' -f2)
    echo "  [$(date '+%T')] $S  $(python3 -c "print(f'{float(\"$P\")*100:.1f}%')" 2>/dev/null)"
    case "$S" in
      checkingDL|checkingUP|checkingResumeData) continue ;;
      stoppedUP)  FINAL_STATE="stoppedUP";  break ;;
      stoppedDL)  FINAL_STATE="stoppedDL:$P"; break ;;
      downloading|stalledDL|queuedDL|uploading|stalledUP|forcedUP|forcedDL|queuedUP)
        echo "  STOPPING unexpected active state: $S"
        curl -sS -o /dev/null -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
          --data-urlencode "hashes=${BROKEN_HASH}"
        FINAL_STATE="stopped_active:$S"; break ;;
      *) FINAL_STATE="unknown:$S"; break ;;
    esac
  done
  [[ -z "$FINAL_STATE" ]] && FINAL_STATE="timeout"
  echo "  recheck result: $FINAL_STATE"
else
  echo "  [dry-run] would recheckTorrents and monitor"
  FINAL_STATE="dry-run"
fi

# ── Phase 6: Start + stable-seed verify ───────────────────────────────────────
SUCCESS=false
if [[ "$APPLY" == true ]]; then
  echo "▸ P6 start + verify"
  if [[ "$FINAL_STATE" == "stoppedUP" ]]; then
    qb_login 2>/dev/null || true
    RESUME_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/resume" \
      --data-urlencode "hashes=${BROKEN_HASH}")
    if [[ "$RESUME_HTTP" == "404" ]]; then
      RESUME_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
        -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/start" \
        --data-urlencode "hashes=${BROKEN_HASH}")
    fi
    echo "  resume/start HTTP $RESUME_HTTP"
    echo "  resumed — monitoring 90s for stable UP..."
    VERIFY_END=$(( $(date +%s) + 90 ))
    CLEAN=true
    while [[ $(date +%s) -lt $VERIFY_END ]]; do
      sleep 5
      qb_login 2>/dev/null || true
      S=$(qb_info "$BROKEN_HASH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])" 2>/dev/null || echo "error")
      echo "  [$(date '+%T')] $S"
      case "$S" in
        stalledUP|uploading|queuedUP) ;;  # good
        stoppedUP) ;;  # also fine (no peers)
        downloading|stalledDL|forcedDL|queuedDL)
          echo "  FAIL: went to download state $S — stopping"
          curl -sS -o /dev/null -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=${BROKEN_HASH}"
          CLEAN=false; break ;;
        error|missingFiles)
          echo "  FAIL: $S — stopping"
          curl -sS -o /dev/null -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
            --data-urlencode "hashes=${BROKEN_HASH}"
          CLEAN=false; break ;;
      esac
    done
    if [[ "$CLEAN" == true ]]; then
      # Stop it after verification — leave stopped for user to manage
      curl -sS -o /dev/null -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/stop" \
        --data-urlencode "hashes=${BROKEN_HASH}"
      echo "  stopped after verification"
      SUCCESS=true
    fi
  else
    echo "  SKIP: recheck did not reach stoppedUP ($FINAL_STATE)"
  fi
else
  echo "▸ P6 [dry-run]"
fi

# ── Phase 7: Track streak ─────────────────────────────────────────────────────
echo "▸ P7 streak"
STREAK=$(get_streak)
if [[ "$SUCCESS" == true ]]; then
  STREAK=$(( STREAK + 1 ))
  set_streak "$STREAK"
  echo "  ✓ SUCCESS  streak=$STREAK"
  [[ $STREAK -ge 10 ]] && echo "  ══ READY FOR BATCH (10 consecutive) ══"
else
  [[ "$APPLY" == true ]] && { set_streak 0; echo "  ✗ FAIL  streak reset"; } || echo "  [dry-run]"
fi
echo "━━━ DONE ━━━"
