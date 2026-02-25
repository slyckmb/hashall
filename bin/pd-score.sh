#!/usr/bin/env bash
# pd-score.sh — tier-score all stoppedDL/pausedDL torrents for batch automation.
# Version: 1.0.0
# Date:    2026-02-25
#
# Classifies every PD torrent into one of four tiers and assigns a confidence
# score within each tier.  Outputs a human-readable summary + JSON report.
#
# Tiers:
#   1 (score 90-100): EXACT QB match + progress ≥ 99%
#                     → qbit-repair-batch.sh --limit N --apply
#   2 (score 60-89):  EXACT or FUZZY QB match (any progress)
#                     → qbit-repair-batch.sh --limit N --apply  (or --same-save)
#   3 (score 10-59):  No QB match, progress ≥ 10%
#                     → investigate: partial cross-seed with real data on disk
#   4 (score  0-9):   No QB match, progress < 10%
#                     → nohl-basics workflow (rehome-100/101/102), not this script
#
# Score within Tier 3 is based on disk_completion (actual bytes / expected bytes)
# — higher score = more data present, higher chance a recheck would succeed.
#
# Usage: bin/pd-score.sh [--tier N] [--json FILE] [-q]
#   --tier N     Print only hashes for tier N (for piping to other tools)
#   --json FILE  Write full JSON report to FILE instead of default log path
#   -q           Quiet: suppress per-torrent lines, print summary only
set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
DB="${HOME}/.hashall/catalog.db"
LOGDIR="${HOME}/.logs/hashall/reports/qbit-triage"
mkdir -p "$LOGDIR"

FILTER_TIER=""
JSON_OUT=""
QUIET=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier)  FILTER_TIER="$2"; shift 2 ;;
    --json)  JSON_OUT="$2"; shift 2 ;;
    -q)      QUIET=true; shift ;;
    -h|--help) sed -n '2,28p' "$0" | grep '^#' | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$JSON_OUT" ]] && JSON_OUT="$LOGDIR/pd-score-$(date +%Y%m%d-%H%M%S).json"

COOKIE=$(mktemp /tmp/qb.XXXXXX)
TMPD=$(mktemp -d /tmp/pd_score.XXXXXX)
trap 'rm -rf "$TMPD" "$COOKIE"' EXIT

# ── Login + fetch all torrents ────────────────────────────────────────────────
curl -fsS --max-time 15 -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null

curl -fsS --max-time 30 -b "$COOKIE" "$QB_URL/api/v2/torrents/info" \
  > "$TMPD/all_torrents.json"

# ── Step 1: classify tiers, identify file lists needed ────────────────────────
python3 - "$DB" "$TMPD" << 'PYEOF'
import json, re, sqlite3, os, sys
from collections import defaultdict

db_path, tmpdir = sys.argv[1], sys.argv[2]
torrents  = json.load(open(f"{tmpdir}/all_torrents.json"))
by_hash   = {t["hash"]: t for t in torrents}

pd = [t for t in torrents if t["state"] in ("stoppedDL", "pausedDL")]
good_hashes = {t["hash"] for t in torrents
               if t["state"] in ("stoppedUP", "stalledUP", "uploading")
               and t["progress"] >= 0.9999}

con = sqlite3.connect(db_path)

def catalog_name(h):
    r = con.execute("SELECT root_name FROM torrent_instances WHERE torrent_hash=? LIMIT 1", (h,)).fetchone()
    return r[0] if r else None

def normalize(n):
    return re.sub(r'\s+', ' ', re.sub(r'[._]', ' ', n)).strip().lower()

def fs_label(gs, bs):
    if gs == bs: return "same-save"
    if   gs.startswith("/pool/data")   and bs.startswith("/pool/data"):   return "pool-pool"
    elif gs.startswith("/stash/media") and bs.startswith("/stash/media"): return "stash-stash"
    elif gs.startswith("/data/media")  and bs.startswith("/data/media"):  return "stash-stash"
    return "cross-fs"

# Index good-pool names
good_exact = defaultdict(list)
good_norm  = defaultdict(list)
good_names = {}
for gh in good_hashes:
    n = catalog_name(gh) or by_hash[gh]["name"]
    good_names[gh] = n
    good_exact[n].append(gh)
    good_norm[normalize(n)].append(gh)

def score_tier12(t, match_type, gh):
    """Score a torrent that has a QB partner."""
    p   = t["progress"]
    gs  = by_hash[gh]["save_path"]
    bs  = t["save_path"]
    fsl = fs_label(gs, bs)
    dl  = t.get("download_path", "") or ""

    if match_type == "EXACT" and p >= 0.99:
        tier  = 1
        score = 90
        score += 5 if not dl else 0        # clean state bonus
        score += 5 if p >= 0.9999 else 2   # full vs near-full
    elif match_type == "EXACT":
        tier  = 2
        score = 70
        score += 10 if fsl in ("pool-pool", "stash-stash") else 5 if fsl == "same-save" else 0
        score += 5  if p >= 0.90 else 2 if p >= 0.50 else 0
    else:  # FUZZY
        tier  = 2
        score = 60
        score += 8  if fsl in ("pool-pool", "stash-stash") else 4 if fsl == "same-save" else 0
        score += 5  if p >= 0.90 else 2 if p >= 0.50 else 0

    # Mode detection (informational)
    modes = []
    if t["state"] == "pausedDL":     modes.append("A")
    if not catalog_name(t["hash"]):  modes.append("B")
    if match_type == "FUZZY":        modes.append("C")

    return tier, min(score, 100), fsl, modes

# Classify all PD torrents
classified = []
need_files  = []  # hashes that need file-list fetch (Tier 3 only)

for t in pd:
    h   = t["hash"]
    p   = t["progress"]
    eff = catalog_name(h) or t["name"]
    ex  = good_exact.get(eff, [])
    fz  = [x for x in good_norm.get(normalize(eff), []) if x not in ex]

    if ex or fz:
        mt   = "EXACT" if ex else "FUZZY"
        gh   = (ex or fz)[0]
        tier, score, fsl, modes = score_tier12(t, mt, gh)
        classified.append({
            "hash": h, "name": t["name"], "state": t["state"],
            "progress": p, "tier": tier, "score": score,
            "match_type": mt, "good_hash": gh, "good_name": good_names.get(gh),
            "fs_label": fsl, "disk_completion": None, "modes": modes,
            "save_path": t["save_path"],
            "dl_path": t.get("download_path", "") or "",
        })
    elif p >= 0.10:
        classified.append({
            "hash": h, "name": t["name"], "state": t["state"],
            "progress": p, "tier": 3, "score": -1,  # filled in step 3
            "match_type": "NONE", "good_hash": None, "good_name": None,
            "fs_label": None, "disk_completion": None, "modes": [],
            "save_path": t["save_path"],
            "dl_path": t.get("download_path", "") or "",
        })
        need_files.append(h)
    else:
        score = 1 if os.path.isdir(t["save_path"]) else 0
        classified.append({
            "hash": h, "name": t["name"], "state": t["state"],
            "progress": p, "tier": 4, "score": score,
            "match_type": "NONE", "good_hash": None, "good_name": None,
            "fs_label": None, "disk_completion": None, "modes": [],
            "save_path": t["save_path"],
            "dl_path": t.get("download_path", "") or "",
        })

json.dump(classified, open(f"{tmpdir}/classified.json", "w"), indent=2)

with open(f"{tmpdir}/need_files.txt", "w") as f:
    f.write("\n".join(need_files) + ("\n" if need_files else ""))

t1 = sum(1 for c in classified if c["tier"]==1)
t2 = sum(1 for c in classified if c["tier"]==2)
t3 = sum(1 for c in classified if c["tier"]==3)
t4 = sum(1 for c in classified if c["tier"]==4)
print(f"  classified: T1={t1}  T2={t2}  T3={t3}  T4={t4}  (fetching file lists for {len(need_files)} Tier-3 hashes)")
PYEOF

# ── Step 2: fetch file lists for Tier 3 only (usually handful) ───────────────
CURL_PIDS=()
while IFS= read -r HASH; do
  [[ -z "$HASH" ]] && continue
  curl --max-time 30 -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/files?hash=$HASH" \
    > "$TMPD/files_${HASH}.json" 2>/dev/null || true &
  CURL_PIDS+=($!)
done < "$TMPD/need_files.txt"
for _pid in "${CURL_PIDS[@]:-}"; do [[ -n "$_pid" ]] && wait "$_pid" 2>/dev/null || true; done

# ── Step 3: disk-completion scoring for Tier 3, final output ─────────────────
python3 - "$TMPD" "$JSON_OUT" "$FILTER_TIER" "$QUIET" << 'PYEOF'
import json, os, sys, datetime

tmpdir, json_out, filter_tier, quiet = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "true"
classified = json.load(open(f"{tmpdir}/classified.json"))

# ── Disk-completion scoring for Tier 3 ────────────────────────────────────────
def disk_completion(h, save_path, dl_path):
    """
    Compute fraction of torrent content actually present on disk.
    Uses QB file list (relative paths) + stat.
    Returns (completion_fraction, bytes_on_disk, bytes_expected).
    """
    fpath = f"{tmpdir}/files_{h}.json"
    if not os.path.exists(fpath):
        return None, 0, 0
    try:
        files = json.load(open(fpath))
    except Exception:
        return None, 0, 0

    got, total = 0, 0
    for f in files:
        exp = f.get("size", 0)
        total += exp
        # Check save_path first, then dl_path
        for base in filter(None, [save_path, dl_path]):
            p = os.path.join(base, f["name"])
            try:
                got += min(os.path.getsize(p), exp)
                break
            except OSError:
                pass
    if total == 0:
        return None, 0, 0
    return got / total, got, total

def score_tier3(c):
    """Compute score 10-59 for a Tier-3 torrent based on disk content."""
    h  = c["hash"]
    p  = c["progress"]
    sp = c["save_path"]
    dl = c["dl_path"]

    frac, got, exp = disk_completion(h, sp, dl)
    if frac is None:
        # No file list: fall back to QB progress
        frac = p

    c["disk_completion"] = round(frac, 4)

    score = 10
    score += int(min(40, frac * 40))      # 0-40 pts: how much data on disk
    score += 5 if p >= 0.90 else 2        # QB progress corroboration
    score += 4 if not dl else 2           # dl_path cleared is a good sign

    return min(score, 59)

for c in classified:
    if c["tier"] == 3:
        c["score"] = score_tier3(c)

# ── Determine recommended action per tier ────────────────────────────────────
ACTIONS = {
    1: "qbit-repair-batch.sh --limit N --apply",
    2: "qbit-repair-batch.sh --limit N --apply  (same-save pairs: add --same-save)",
    3: "inspect disk content; recheck manually if files present",
    4: "nohl-basics workflow (rehome-100/101/102) — not this script",
}

# ── Build output report ───────────────────────────────────────────────────────
tiers = {1:[], 2:[], 3:[], 4:[]}
for c in classified:
    tiers[c["tier"]].append(c)

# Sort each tier by score descending
for t in tiers.values():
    t.sort(key=lambda x: -x["score"])

report = {
    "generated_at": datetime.datetime.now().isoformat(),
    "tier_summary": {},
    "torrents": sorted(classified, key=lambda c: (c["tier"], -c["score"])),
}
for n, tlist in tiers.items():
    scores = [c["score"] for c in tlist]
    report["tier_summary"][str(n)] = {
        "count":    len(tlist),
        "score_range": f"{min(scores)}-{max(scores)}" if scores else "—",
        "action":   ACTIONS[n],
    }

with open(json_out, "w") as f:
    json.dump(report, f, indent=2)

# ── Human-readable output ─────────────────────────────────────────────────────
W = 72
print(f"\n{'═'*W}")
print(f"PD SCORE REPORT  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"{'═'*W}")
print(f"\n{'Tier':<6}{'Count':>6}  {'Score range':<14}  Action")
print(f"{'─'*W}")
labels = {
    1: "T1  EXACT ≥99%   → repair now",
    2: "T2  has QB match → repair now",
    3: "T3  partial data → investigate",
    4: "T4  no data      → nohl-basics",
}
for n in (1,2,3,4):
    s = report["tier_summary"][str(n)]
    print(f"  {n}   {s['count']:>6}  {s['score_range']:<14}  {labels[n]}")

print(f"{'─'*W}")
total = sum(s["count"] for s in report["tier_summary"].values())
print(f"       {total:>6}  total PD torrents")

# Per-tier detail
for tier_num in (1, 2, 3):
    tlist = tiers[tier_num]
    if not tlist: continue
    print(f"\n── Tier {tier_num} ({'%d' % len(tlist)} torrents) {'─'*(W-18)}")

    if tier_num == 1:
        for c in tlist:
            print(f"  [{c['score']:3}] {c['hash'][:12]}  {c['match_type']:<5}  {c['fs_label']:<12}  prog={c['progress']:.4f}  {c['name'][:35]}")

    elif tier_num == 2:
        # Group by same-save vs other for run instructions
        same_save = [c for c in tlist if c["fs_label"] == "same-save"]
        other     = [c for c in tlist if c["fs_label"] != "same-save"]
        if same_save:
            print(f"  Same-save ({len(same_save)}) — run with --same-save:")
            for c in same_save:
                modes = "+".join(c["modes"]) if c["modes"] else "—"
                print(f"    [{c['score']:3}] {c['hash'][:12]}  {c['match_type']:<5}  modes={modes:<4}  prog={c['progress']:.3f}  {c['name'][:35]}")
        if other:
            print(f"  Cross-fs/same-fs ({len(other)}) — run without --same-save:")
            for c in other:
                modes = "+".join(c["modes"]) if c["modes"] else "—"
                print(f"    [{c['score']:3}] {c['hash'][:12]}  {c['match_type']:<5}  {c['fs_label']:<12}  modes={modes:<4}  prog={c['progress']:.3f}  {c['name'][:32]}")

    elif tier_num == 3:
        for c in tlist:
            dc = f"{c['disk_completion']:.1%}" if c["disk_completion"] is not None else "?"
            dl = f"  dl={c['dl_path'][:30]}" if c["dl_path"] else ""
            print(f"  [{c['score']:3}] {c['hash'][:12]}  disk={dc:<6}  qb_prog={c['progress']:.3f}  {c['name'][:38]}{dl}")

# Tier 4 summary only (too many to list)
print(f"\n── Tier 4 ({len(tiers[4])} torrents) {'─'*(W-20)}")
print(f"  All at <10% progress, no QB partner found.")
print(f"  These are cross-seed slots waiting for the nohl-basics workflow.")
# Show save_path distribution
from collections import Counter
sp_roots = Counter()
for c in tiers[4]:
    sp = c["save_path"]
    # Extract the seeding category from path
    parts = sp.rstrip("/").split("/")
    label = "/".join(parts[-2:]) if len(parts)>=2 else sp
    sp_roots[label] += 1
print(f"  Top save-path groups:")
for path, cnt in sp_roots.most_common(8):
    print(f"    {cnt:>5}  {path}")

print(f"\n{'═'*W}")
print(f"Report: {json_out}")
print(f"{'═'*W}\n")

# ── --tier N: print matching hashes ──────────────────────────────────────────
if filter_tier:
    n = int(filter_tier)
    for c in tiers.get(n, []):
        print(c["hash"])
PYEOF

~/.ai-sessions/session-helper.sh claude file "$JSON_OUT" created 2>/dev/null || true
