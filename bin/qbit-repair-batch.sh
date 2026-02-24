#!/usr/bin/env bash
# Batch repair of stoppedDL torrents.
# Discover candidates → rebuild hardlinks → ONE QB stop/start for all → parallel recheck.
#
# Fixes vs single-pair script:
#   - Skips same-save-path pairs (good_save == broken_save)
#   - Deletes incomplete files at old download_path BEFORE QB restart (prevents overwrite)
#   - One QB stop/start for entire batch (fast)
#   - Parallel recheck of all candidates
#   - No 90s verification: recheck→stoppedUP = success
#
# Usage: bin/qbit-repair-batch.sh [--limit N] [--apply]
set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
DB="${HOME}/.hashall/catalog.db"
BT_BACKUP="/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
QB_CONTAINER="qbittorrent_vpn"
WT="/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028"
SUCCESS_FILE="$WT/out/reports/qbit-triage/repair-consecutive-successes.txt"
TMPD="/tmp/qb_repair_batch"
mkdir -p "$WT/out/reports/qbit-triage" "$TMPD"

LIMIT=10
APPLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --apply) APPLY=true; shift ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT

qb_login() {
  curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
    --data-urlencode "username=$QB_USER" \
    --data-urlencode "password=$QB_PASS" >/dev/null
}
get_streak() { [[ -f "$SUCCESS_FILE" ]] && cat "$SUCCESS_FILE" || echo 0; }
set_streak() { echo "$1" > "$SUCCESS_FILE"; }

echo "════════════════════════════════════════════════════════════"
echo "qbit-repair-batch  apply=$APPLY  limit=$LIMIT  $(date '+%F %T')"
echo "════════════════════════════════════════════════════════════"

# ── P0: Discovery ─────────────────────────────────────────────────────────────
echo "▸ P0 discovery"
qb_login
curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPD/all_torrents.json"

python3 - "$DB" "$TMPD" "$LIMIT" << 'PYEOF'
import json, sqlite3, os, sys
from collections import defaultdict

db, tmpdir, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])

torrents = json.load(open(f"{tmpdir}/all_torrents.json"))
by_hash  = {t["hash"]: t for t in torrents}

good_hashes   = {t["hash"] for t in torrents if t["state"] == "stoppedUP" and t["progress"] >= 0.9999}
broken_hashes = {t["hash"] for t in torrents if t["state"] == "stoppedDL"}

con = sqlite3.connect(db)
def get_root_names(hashes):
    if not hashes: return {}
    ph = ",".join("?" * len(hashes))
    rows = con.execute(f"SELECT torrent_hash, root_name FROM torrent_instances WHERE torrent_hash IN ({ph})", list(hashes)).fetchall()
    return {h: n for h, n in rows}

good_names   = get_root_names(good_hashes)
broken_names = get_root_names(broken_hashes)

name_to_good = defaultdict(list)
for h, n in good_names.items():
    if n: name_to_good[n].append(h)

results = []
seen_broken = set()
for bh, bname in broken_names.items():
    if not bname or bh in seen_broken: continue
    good = name_to_good.get(bname, [])
    if not good: continue
    bt = by_hash[bh]
    broken_save = bt["save_path"]
    broken_dl   = bt.get("download_path", "") or ""
    for gh in good:
        gt = by_hash[gh]
        good_save = gt["save_path"]
        # SKIP same-save-path (same directory — no hardlink work needed, handled separately)
        if good_save == broken_save:
            continue
        gp, bp = good_save, broken_save
        if   gp.startswith("/pool/data")   and bp.startswith("/pool/data"):   same_fs = "pool-pool"
        elif gp.startswith("/stash/media") and bp.startswith("/stash/media"): same_fs = "stash-stash"
        elif gp.startswith("/data/media")  and bp.startswith("/data/media"):  same_fs = "stash-stash"
        else: same_fs = "cross-fs"
        results.append({
            "good_hash": gh, "broken_hash": bh,
            "same_fs": same_fs, "root_name": bname,
            "progress": bt["progress"],
            "good_save": good_save, "broken_save": broken_save, "broken_dl": broken_dl,
        })
        seen_broken.add(bh)
        break  # one good partner per broken hash

# Sort: same-fs first, then progress ASC
results.sort(key=lambda x: (0 if x["same_fs"] != "cross-fs" else 1, x["progress"]))
if limit: results = results[:limit]

json.dump(results, open(f"{tmpdir}/candidates.json", "w"), indent=2)
print(f"  {len(results)} candidates (skipping same-save-path pairs)")
for r in results:
    print(f"  {r['broken_hash'][:12]}  {r['same_fs']:12}  prog={r['progress']:.3f}  {r['root_name'][:55]}")
PYEOF

NCAN=$(python3 -c "import json; print(len(json.load(open('$TMPD/candidates.json'))))")
if [[ "$NCAN" -eq 0 ]]; then echo "No candidates. Exiting."; exit 0; fi
echo ""

# ── P1: Content analysis ──────────────────────────────────────────────────────
echo "▸ P1 content analysis"
qb_login 2>/dev/null || true

# Fetch QB files for all candidates in parallel
python3 -c "
import json
c = json.load(open('$TMPD/candidates.json'))
for r in c: print(r['good_hash'], r['broken_hash'])
" | while read -r GH BH; do
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/files?hash=$GH" > "$TMPD/gf_${GH}.json" &
  curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/files?hash=$BH" > "$TMPD/bf_${BH}.json" &
done
wait

python3 - "$DB" "$TMPD" << 'PYEOF'
import json, os, sqlite3, sys
from collections import Counter

db, tmpdir = sys.argv[1], sys.argv[2]
candidates = json.load(open(f"{tmpdir}/candidates.json"))
con = sqlite3.connect(db)

def _fs_table(abspath):
    """Return (table, prefix, rel) for a given absolute path, or None."""
    if abspath.startswith("/pool/data/"):
        return "files_231", "/pool/data/", abspath[len("/pool/data/"):]
    if abspath.startswith("/stash/media/"):
        return "files_44",  "/stash/media/", abspath[len("/stash/media/"):]
    if abspath.startswith("/data/media/"):
        return "files_44",  "/stash/media/", abspath[len("/data/media/"):]
    return None, None, None

def catalog_lookup(abspath):
    """Return (quick_hash, sha256) from DB for a given path, or (None, None)."""
    table, _, rel = _fs_table(abspath)
    if not table: return (None, None)
    row = con.execute(f"SELECT quick_hash, sha256 FROM {table} WHERE path=? AND status='active' LIMIT 1", (rel,)).fetchone()
    return (row[0], row[1]) if row else (None, None)

def catalog_qhash(abspath):
    return catalog_lookup(abspath)[0]

def catalog_find_by_qhash(qhash, abspath_hint):
    """Find any active file with given quick_hash on the same filesystem as abspath_hint.
    Returns absolute path of a DB-confirmed on-disk file, or None."""
    if not qhash: return None
    table, prefix, _ = _fs_table(abspath_hint)
    if not table: return None
    row = con.execute(f"SELECT path FROM {table} WHERE quick_hash=? AND status='active' LIMIT 1", (qhash,)).fetchone()
    if not row: return None
    candidate = prefix + row[0]
    return candidate if os.path.exists(candidate) else None

plan = []
for c in candidates:
    gh, bh = c["good_hash"], c["broken_hash"]
    good_save, broken_save = c["good_save"], c["broken_save"]
    same_fs = (c["same_fs"] != "cross-fs")

    try:
        good_files   = json.load(open(f"{tmpdir}/gf_{gh}.json"))
        broken_files = json.load(open(f"{tmpdir}/bf_{bh}.json"))
    except Exception as e:
        c["error"] = str(e); c["rebuild_files"] = []; plan.append(c); continue

    # Build good lookup: by QB basename (primary) and by index position (fallback)
    good_by_name = {}
    good_by_idx  = []
    for f in good_files:
        ap = os.path.join(good_save, f["name"])
        qh, sh = catalog_lookup(ap)
        entry = {"abs": ap, "qhash": qh, "sha256": sh, "size": f.get("size", -1)}
        good_by_name[os.path.basename(f["name"])] = entry
        good_by_idx.append(entry)

    # Pre-scan broken quick_hashes for dup detection
    broken_qhash_counts = Counter()
    for f in broken_files:
        qh = catalog_qhash(os.path.join(broken_save, f["name"]))
        if qh: broken_qhash_counts[qh] += 1

    rebuild_files = []
    if same_fs:
        for i, bf_qb in enumerate(broken_files):
            ap  = os.path.join(broken_save, bf_qb["name"])
            # DB lookup for broken file: quick_hash=fast-hash (partial content), sha256=full hash
            # DB is a pre-session scan snapshot — good evidence but not live truth.
            # sha256 may be NULL (backfill deferred); quick_hash present for all scanned files.
            bqh, bsh = catalog_lookup(ap)
            bsz = bf_qb.get("size", -1)

            # Primary: match by QB filename basename
            gf = good_by_name.get(os.path.basename(bf_qb["name"]))
            # Fallback: same index in QB file list + same size + DB-confirmed quick_hash on good
            # (handles cross-seed name variants like spaces-vs-dots; quick_hash gates the guess)
            if gf is None and i < len(good_by_idx) and bsz > 0 and good_by_idx[i]["size"] == bsz:
                cand = good_by_idx[i]
                if cand["qhash"]:  # DB confirms good file content known — not just size match
                    gf = cand

            if gf is None:
                rebuild_files.append({"bad": ap, "good": None, "action": "no_match"}); continue

            # Resolve best on-disk source: prefer QB-reported path; fall back to DB hash search
            good_src = gf["abs"] if os.path.exists(gf["abs"]) else catalog_find_by_qhash(gf["qhash"], gf["abs"])

            gqh, gsh = gf["qhash"], gf["sha256"]
            try:
                b_ino = os.stat(ap).st_ino if os.path.exists(ap) else 0
                g_ino = os.stat(good_src).st_ino if good_src and os.path.exists(good_src) else 0
            except: b_ino = g_ino = 0

            if b_ino and g_ino and b_ino == g_ino:
                action = "already_hardlinked"
            elif not os.path.exists(ap):
                action = "missing"
            else:
                # Classify existing broken file: prefer sha256 (full hash) over quick_hash (fast-hash)
                # sha256 is definitive; quick_hash is corroborating evidence (partial content only)
                if bsh and gsh:
                    action = "dup_copy" if bsh == gsh else "garbage"
                elif bqh and gqh:
                    if broken_qhash_counts.get(bqh, 0) > 1: action = "garbage"  # sparse placeholder
                    else: action = "dup_copy" if bqh == gqh else "garbage"
                else:
                    action = "unknown_keep"  # no DB evidence either way — leave it alone
            rebuild_files.append({"bad": ap, "good": good_src, "action": action})

    counts = Counter(f["action"] for f in rebuild_files)
    c["rebuild_files"] = rebuild_files
    c["summary"] = dict(counts)
    plan.append(c)
    print(f"  {bh[:12]}  {dict(counts)}")

json.dump(plan, open(f"{tmpdir}/plan.json", "w"), indent=2)
PYEOF
echo ""

# ── P2: Hardlink rebuild + cross-fs setLocation (QB running) ─────────────────
echo "▸ P2 hardlink rebuild"
if [[ "$APPLY" == true ]]; then
  # Cross-fs: setLocation broken → good's save_path
  python3 -c "
import json
plan = json.load(open('$TMPD/plan.json'))
for c in plan:
    if c['same_fs'] == 'cross-fs':
        print(c['broken_hash'] + '|' + c['good_save'])
" | while IFS='|' read -r BHASH TARGET; do
    HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/setLocation" \
      --data-urlencode "hashes=$BHASH" \
      --data-urlencode "location=$TARGET")
    echo "  setLocation [${BHASH:0:12}] → $TARGET: HTTP $HTTP"
  done

  # Same-fs: rebuild hardlinks
  python3 - "$TMPD" << 'PYEOF'
import json, os, sys
tmpdir = sys.argv[1]
plan = json.load(open(f"{tmpdir}/plan.json"))
rebuild_actions = {"garbage", "dup_copy", "missing"}
total = 0
for c in plan:
    if c["same_fs"] == "cross-fs": continue
    for f in c.get("rebuild_files", []):
        if f["action"] not in rebuild_actions: continue
        bad, good = f["bad"], f.get("good")
        if not good or not os.path.exists(good):
            print(f"  SKIP no good src: {os.path.basename(bad)}"); continue
        if os.path.exists(bad): os.remove(bad)
        os.makedirs(os.path.dirname(bad), exist_ok=True)
        os.link(good, bad)
        total += 1
print(f"  {total} hardlinks rebuilt")
PYEOF
else
  python3 -c "
import json
plan = json.load(open('$TMPD/plan.json'))
total = sum(1 for c in plan for f in c.get('rebuild_files',[]) if f['action'] in {'garbage','dup_copy','missing'})
cross = sum(1 for c in plan if c['same_fs']=='cross-fs')
print(f'  [dry-run] would rebuild {total} hardlinks, {cross} cross-fs setLocation')
"
fi
echo ""

# ── P3: Stop QB → delete incomplete + patch fastresumes → start QB ────────────
echo "▸ P3 QB stop window"

if [[ "$APPLY" == true ]]; then
  docker stop "$QB_CONTAINER" >/dev/null
  echo "  QB stopped"
fi

python3 - "$BT_BACKUP" "$APPLY" "$TMPD" << 'PYEOF'
import json, os, sys, shutil

bt_backup = sys.argv[1]
apply     = sys.argv[2] == "true"
tmpdir    = sys.argv[3]

def container_to_host(p):
    if not p: return ""
    if p.startswith('/incomplete_torrents'):
        return p.replace('/incomplete_torrents', '/dump/torrents/incomplete_vpn', 1)
    return p  # pool/data, stash/media, data/media all map 1:1 on host

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

plan = json.load(open(f"{tmpdir}/plan.json"))
for c in plan:
    h         = c["broken_hash"]
    root_name = c.get("root_name", "")
    fr        = os.path.join(bt_backup, h + ".fastresume")

    if not os.path.exists(fr):
        print(f"  [{h[:12]}] MISSING fastresume — skipping"); continue

    with open(fr, 'rb') as f: data = f.read()
    d, _ = bdecode(data)

    # Read old download_path from fastresume (fresh, not from QB API)
    old_b = d.get(b'qBt-downloadPath', b'')
    old   = old_b.decode('utf-8', errors='replace') if isinstance(old_b, bytes) else str(old_b)

    # Delete incomplete files BEFORE patching (prevents QB from moving them to save_path)
    # NOTE: qBittorrent container never mounts /stash; all stash paths appear as /data/media/
    #       Path string comparison is unreliable — use inode comparison instead.
    #       File paths come from QB's files API (bf_*.json), NOT from root_name assumption.
    if old:
        host_dl     = container_to_host(old)
        broken_save = c.get("broken_save", "")
        if host_dl:
            def same_inode(a, b):
                try:
                    return os.path.exists(a) and os.path.exists(b) and \
                           os.stat(a).st_ino == os.stat(b).st_ino and \
                           os.stat(a).st_dev == os.stat(b).st_dev
                except: return False

            def is_good_content(path):
                """Return True if path shares inode with any good/save file we know about."""
                for rf in c.get("rebuild_files", []):
                    gf = rf.get("good")
                    if gf and same_inode(path, gf):
                        return True
                # Also check the corresponding file at broken_save (live seed content)
                if broken_save:
                    rel = os.path.relpath(path, host_dl)
                    save_file = os.path.join(broken_save, rel)
                    if same_inode(path, save_file):
                        return True
                return False

            # Use QB file list to enumerate exact paths — never assume root_name layout
            try:
                broken_qb_files = json.load(open(f"{tmpdir}/bf_{h}.json"))
            except Exception:
                broken_qb_files = []

            deleted, skipped = 0, 0
            for qbf in broken_qb_files:
                target = os.path.join(host_dl, qbf["name"])
                if not os.path.exists(target):
                    continue
                if is_good_content(target):
                    skipped += 1
                elif apply:
                    os.remove(target)
                    deleted += 1
                else:
                    print(f"  [{h[:12]}] [dry-run] would delete: {os.path.basename(target)}")
            if apply and (deleted or skipped):
                print(f"  [{h[:12]}] deleted {deleted} incomplete file(s), skipped {skipped} (live content)")

    # Patch fastresume
    if not old:
        print(f"  [{h[:12]}] download_path already empty"); continue

    if apply:
        d[b'qBt-downloadPath'] = b''
        tmp = fr + '.tmp'
        with open(tmp, 'wb') as f: f.write(bencode(d))
        os.replace(tmp, fr)
        print(f"  [{h[:12]}] patched: cleared '{old}'")
    else:
        print(f"  [{h[:12]}] [dry-run] would clear '{old}'")
PYEOF

if [[ "$APPLY" == true ]]; then
  docker start "$QB_CONTAINER" >/dev/null
  echo -n "  waiting for QB API"
  while ! curl -fsS --max-time 3 "$QB_URL/api/v2/app/version" >/dev/null 2>&1; do echo -n "."; sleep 2; done
  echo " up"
  qb_login
fi
echo ""

# ── P4: Recheck all ───────────────────────────────────────────────────────────
echo "▸ P4 recheckTorrents"
HASH_LIST=$(python3 -c "import json; print('|'.join(c['broken_hash'] for c in json.load(open('$TMPD/plan.json'))))")
if [[ "$APPLY" == true ]]; then
  qb_login 2>/dev/null || true
  HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE" -X POST "$QB_URL/api/v2/torrents/recheck" \
    --data-urlencode "hashes=${HASH_LIST}")
  echo "  recheckTorrents ($NCAN hashes): HTTP $HTTP"
else
  echo "  [dry-run] would recheckTorrents for $NCAN hashes"
fi
echo ""

# ── P5: Monitor all ───────────────────────────────────────────────────────────
echo "▸ P5 monitor"
if [[ "$APPLY" == true ]]; then
  python3 - "$COOKIE" "$QB_URL" "$TMPD" << 'PYEOF'
import json, time, subprocess, sys, os

cookie, qb_url, tmpdir = sys.argv[1], sys.argv[2], sys.argv[3]
plan   = json.load(open(f"{tmpdir}/plan.json"))
hashes = [c["broken_hash"] for c in plan]
names  = {c["broken_hash"]: c["root_name"][:40] for c in plan}

TERMINAL = {"stoppedUP", "stoppedDL", "error", "missingFiles"}
CHECKING = {"checkingDL", "checkingUP", "checkingResumeData", "moving"}
results        = {}
pending_stopDL = {}  # hash -> timestamp first seen stoppedDL (re-poll grace)
last_progress  = {}  # hash -> last seen progress value
last_change    = {}  # hash -> time progress last changed (stagnation detection)
has_started    = set()  # hashes that have ever made progress > 0%
STAGNANT_SECS  = 600  # 10 min without progress change = genuine timeout (only if started)
SAFETY_END     = time.time() + 7200  # 2 hr hard safety cap

def get_states():
    raw = subprocess.run(["curl", "-fsS", "-b", cookie, f"{qb_url}/api/v2/torrents/info"],
                         capture_output=True, text=True).stdout
    try:    return {t["hash"]: t for t in json.loads(raw) if t["hash"] in set(hashes)}
    except: return {}

while time.time() < SAFETY_END:
    time.sleep(5)
    ts = get_states()
    now = time.time()
    parts, all_done = [], True
    for h in hashes:
        if h in results:
            parts.append(f"{'✓' if results[h]=='stoppedUP' else '✗'}{h[:8]}")
            continue
        t = ts.get(h, {})
        s, p = t.get("state", "?"), t.get("progress", 0)
        if s in TERMINAL:
            if s == "stoppedDL":
                # Transient stoppedDL: may be mid-transition to stoppedUP.
                # Re-poll after 10s before recording as failure.
                if h not in pending_stopDL:
                    pending_stopDL[h] = now
                    parts.append(f"?{h[:8]}=stpDL(wait)")
                    all_done = False
                elif now - pending_stopDL[h] >= 10:
                    results[h] = s
                    parts.append(f"✗{h[:8]}")
                else:
                    parts.append(f"?{h[:8]}=stpDL(wait)")
                    all_done = False
            else:
                results[h] = s
                parts.append(f"{'✓' if s=='stoppedUP' else '✗'}{h[:8]}")
        elif s in CHECKING:
            # Track progress to detect stagnation.
            # Stagnation timeout only fires if the torrent has STARTED (progress > 0%)
            # and then stopped — not while it's still queued at 0%.
            if p > 0:
                has_started.add(h)
            if last_progress.get(h) != p:
                last_progress[h] = p
                last_change[h] = now
            elif h not in last_change:
                last_change[h] = now
            stale_secs = now - last_change.get(h, now)
            if h in has_started and stale_secs >= STAGNANT_SECS:
                results[h] = "timeout"
                parts.append(f"✗{h[:8]}=stale{int(stale_secs//60)}m")
            else:
                parts.append(f"{h[:8]}={s[:7]}({p*100:.0f}%)")
                all_done = False
        else:
            # Unexpected active state — stop it
            subprocess.run(["curl", "-fsS", "-b", cookie, "-X", "POST",
                            f"{qb_url}/api/v2/torrents/stop",
                            "--data-urlencode", f"hashes={h}"],
                           capture_output=True)
            results[h] = f"stopped_active:{s}"
            parts.append(f"✗{h[:8]}")

    # Print up to 8 per line
    for i in range(0, len(parts), 8):
        prefix = f"  [{time.strftime('%H:%M:%S')}] " if i == 0 else "             "
        print(prefix + "  ".join(parts[i:i+8]))
    sys.stdout.flush()
    if all_done or len(results) == len(hashes): break

# Safety cap hit — remaining still checking = timeout
for h in hashes:
    if h not in results: results[h] = "timeout"

print("")
successes = sum(1 for s in results.values() if s == "stoppedUP")
failures  = len(results) - successes
for h in hashes:
    ok = results[h] == "stoppedUP"
    print(f"  {'✓' if ok else '✗'} {h[:12]}  {results[h]:<22}  {names[h]}")

json.dump({"results": results, "successes": successes, "failures": failures},
          open(f"{tmpdir}/results.json", "w"))
print(f"\n  successes={successes}  failures={failures}")
PYEOF
else
  echo "  [dry-run]"
fi
echo ""

# ── P6: Streak ────────────────────────────────────────────────────────────────
echo "▸ P6 streak"
if [[ "$APPLY" == true ]]; then
  N_OK=$(python3 -c "import json; r=json.load(open('$TMPD/results.json')); print(r['successes'])")
  N_FAIL=$(python3 -c "import json; r=json.load(open('$TMPD/results.json')); print(r['failures'])")
  STREAK=$(get_streak)
  if [[ "$N_FAIL" -eq 0 ]]; then
    STREAK=$(( STREAK + N_OK ))
    set_streak "$STREAK"
    echo "  ✓ ALL $N_OK SUCCEEDED  streak=$STREAK"
    [[ $STREAK -ge 10 ]] && echo "  ══ READY FOR BATCH MODE (10 consecutive) ══"
  else
    set_streak 0
    echo "  ✗ $N_FAIL FAILED  streak reset  (had $N_OK successes)"
  fi
else
  echo "  [dry-run]"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "DONE  $(date '+%F %T')"
echo "════════════════════════════════════════════════════════════"
