#!/usr/bin/env bash
# pd-triage.sh — read-only diagnostic for PD (stoppedDL/pausedDL) torrents.
# Version: 1.0.0
# Date:    2026-02-25
#
# Queries live QB API + catalog DB, outputs per-group report for every PD torrent.
# Reports: actual API state, catalog DB status, candidate match quality, save path
# relationship, inode overlap per file, and DIAGNOSIS (which failure modes apply).
#
# Failure modes identified:
#   Mode A — pausedDL state invisible to repair script (only checks stoppedDL)
#   Mode B — torrent not in catalog DB → root_name NULL, no fallback to API name
#   Mode C — fuzzy name mismatch (dots vs spaces, bracket styles)
#   Mode D — all files already_hardlinked (same inodes), fastresume stale; recheck would fix
#
# Read-only: no API writes, no DB writes, no filesystem changes.
#
# Usage: bin/pd-triage.sh [--hash HASH[,HASH...]]
#   --hash HASH  Limit output to specific broken hash(es) (comma-separated, prefix OK)
set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
DB="${HOME}/.hashall/catalog.db"

FILTER_HASHES=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hash) FILTER_HASHES="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

COOKIE=$(mktemp /tmp/qb.XXXXXX)
TMPD=$(mktemp -d /tmp/pd_triage.XXXXXX)
trap 'rm -rf "$TMPD" "$COOKIE"' EXIT

# ── Login ─────────────────────────────────────────────────────────────────────
curl -fsS --max-time 15 -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null

# ── Fetch all torrents ─────────────────────────────────────────────────────────
curl -fsS --max-time 30 -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > "$TMPD/all_torrents.json"

# ── Step 1: identify PD hashes and their good candidates ──────────────────────
python3 - "$DB" "$TMPD" "$FILTER_HASHES" << 'PYEOF'
import json, re, sqlite3, os, sys
from collections import defaultdict

db_path, tmpdir, filter_arg = sys.argv[1], sys.argv[2], sys.argv[3]
filter_prefixes = [h.strip() for h in filter_arg.split(",") if h.strip()] if filter_arg else []

torrents = json.load(open(f"{tmpdir}/all_torrents.json"))
by_hash  = {t["hash"]: t for t in torrents}

pd_torrents  = [t for t in torrents if t["state"] in ("stoppedDL", "pausedDL")]
good_hashes  = {t["hash"] for t in torrents
                if t["state"] in ("stoppedUP", "stalledUP", "uploading")
                and t["progress"] >= 0.9999}

if filter_prefixes:
    pd_torrents = [t for t in pd_torrents
                   if any(t["hash"].startswith(p) for p in filter_prefixes)]

con = sqlite3.connect(db_path)

def get_root_name(h):
    row = con.execute("SELECT root_name FROM torrent_instances WHERE torrent_hash=? LIMIT 1", (h,)).fetchone()
    return row[0] if row else None

def normalize_name(n):
    return re.sub(r'\s+', ' ', re.sub(r'[._]', ' ', n)).strip().lower()

# Index all good candidates
good_exact = defaultdict(list)   # catalog/API name → [hash]
good_norm  = defaultdict(list)   # normalized name   → [hash]
good_names_map = {}              # hash → display name
for gh in good_hashes:
    gt = by_hash[gh]
    n = get_root_name(gh) or gt["name"]
    good_names_map[gh] = n
    if n:
        good_exact[n].append(gh)
        good_norm[normalize_name(n)].append(gh)

# For each PD torrent, find all candidate hashes
hashes_needed = set()
pairs = []  # list of {bh, bname, bname_api, bstate, bprog, bsize, broken_save, broken_dl, mode_b, candidates}
for bt in pd_torrents:
    bh      = bt["hash"]
    bstate  = bt["state"]
    bprog   = bt["progress"]
    bsize   = bt.get("size", 0)
    bname_api = bt["name"]
    broken_save = bt["save_path"]
    broken_dl   = bt.get("download_path", "") or ""

    root_name = get_root_name(bh)
    mode_b    = (root_name is None)
    eff_name  = root_name or bname_api

    exact_cands = [(gh, "EXACT") for gh in good_exact.get(eff_name, [])]
    fuzzy_cands = [(gh, "FUZZY") for gh in good_norm.get(normalize_name(eff_name), [])
                   if gh not in {h for h, _ in exact_cands}]
    all_cands = exact_cands + fuzzy_cands

    for gh, _ in all_cands:
        hashes_needed.add(bh)
        hashes_needed.add(gh)

    pairs.append({
        "bh": bh, "bstate": bstate, "bprog": bprog, "bsize": bsize,
        "bname_api": bname_api, "root_name": root_name, "eff_name": eff_name,
        "mode_b": mode_b, "broken_save": broken_save, "broken_dl": broken_dl,
        "candidates": all_cands,
    })

# Write hashes that need file lists
with open(f"{tmpdir}/hashes_to_fetch.txt", "w") as f:
    f.write("\n".join(hashes_needed) + ("\n" if hashes_needed else ""))

# Write pairs for step 2
import json as _json
_json.dump({"pairs": pairs, "good_names_map": good_names_map}, open(f"{tmpdir}/triage_state.json", "w"), indent=2)
print(f"PD torrents: {len(pd_torrents)}  candidates to fetch file lists for: {len(hashes_needed)} hashes")
PYEOF

# ── Step 2: Fetch file lists in parallel ─────────────────────────────────────
CURL_PIDS=()
while IFS= read -r HASH; do
  [[ -z "$HASH" ]] && continue
  curl --max-time 30 -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/files?hash=$HASH" \
    > "$TMPD/files_${HASH}.json" 2>/dev/null || true &
  CURL_PIDS+=($!)
done < "$TMPD/hashes_to_fetch.txt"
for _pid in "${CURL_PIDS[@]:-}"; do [[ -n "$_pid" ]] && wait "$_pid" 2>/dev/null || true; done

# ── Step 3: Full analysis with inode checking ──────────────────────────────────
python3 - "$DB" "$TMPD" << 'PYEOF'
import json, os, re, sqlite3, sys
from collections import defaultdict

db_path, tmpdir = sys.argv[1], sys.argv[2]
torrents = json.load(open(f"{tmpdir}/all_torrents.json"))
by_hash  = {t["hash"]: t for t in torrents}

state_data   = json.load(open(f"{tmpdir}/triage_state.json"))
pairs        = state_data["pairs"]
good_names_map = state_data["good_names_map"]

def fs_label(good_save, broken_save):
    if good_save == broken_save: return "same-save"
    gp, bp = good_save, broken_save
    if   gp.startswith("/pool/data")   and bp.startswith("/pool/data"):   return "pool-pool"
    elif gp.startswith("/stash/media") and bp.startswith("/stash/media"): return "stash-stash"
    elif gp.startswith("/data/media")  and bp.startswith("/data/media"):  return "stash-stash"
    return "cross-fs"

def inode_overlap(bh, gh, broken_save, good_save, label):
    """
    Compare file inodes between broken torrent and good torrent.
    Returns (shared_count, total_broken_files, error_str_or_None).
    Only meaningful for same-fs pairs (hardlinks can't cross filesystems).
    """
    if label == "cross-fs":
        return None, None, "cross-fs (no hardlinks)"
    bfiles_path = f"{tmpdir}/files_{bh}.json"
    gfiles_path = f"{tmpdir}/files_{gh}.json"
    if not os.path.exists(bfiles_path):
        return None, None, "no broken file list"
    try:
        b_files = json.load(open(bfiles_path))
    except Exception as e:
        return None, None, f"broken file list parse error: {e}"

    # Build inode set for good torrent files
    good_inodes = set()
    if os.path.exists(gfiles_path):
        try:
            for f in json.load(open(gfiles_path)):
                gp = os.path.join(good_save, f["name"])
                try:
                    st = os.stat(gp)
                    good_inodes.add((st.st_dev, st.st_ino))
                except OSError:
                    pass
        except Exception:
            pass

    shared, total = 0, 0
    for f in b_files:
        bp = os.path.join(broken_save, f["name"])
        total += 1
        try:
            st = os.stat(bp)
            if (st.st_dev, st.st_ino) in good_inodes:
                shared += 1
        except OSError:
            pass

    return shared, total, None

W = 72
print(f"{'═'*W}")
print(f"PD TORRENT TRIAGE  (stoppedDL / pausedDL candidates)")
print(f"Total PD torrents: {len(pairs)}")
print(f"{'═'*W}")

for p in pairs:
    bh          = p["bh"]
    bstate      = p["bstate"]
    bprog       = p["bprog"]
    bname_api   = p["bname_api"]
    root_name   = p["root_name"]
    eff_name    = p["eff_name"]
    mode_b      = p["mode_b"]
    broken_save = p["broken_save"]
    broken_dl   = p["broken_dl"]
    candidates  = p["candidates"]   # [(good_hash, "EXACT"/"FUZZY"), ...]

    print(f"\n{'─'*W}")
    print(f"HASH:    {bh[:12]}  STATE: {bstate}  PROG: {bprog:.4f}")
    print(f"NAME:    {bname_api[:W-9]}")
    if mode_b:
        print(f"CATALOG: ✗ NULL — not in torrent_instances (Mode B)")
    else:
        print(f"CATALOG: ✓ root_name = {root_name[:W-18]}")
    print(f"SAVE:    {broken_save}")
    if broken_dl:
        print(f"DL_PATH: {broken_dl}")

    if not candidates:
        print(f"CANDS:   none found")
        modes = []
        if bstate == "pausedDL":
            modes.append("A (pausedDL invisible)")
        if mode_b:
            modes.append("B (not in catalog)")
        modes.append("— no matching good torrent found (C possible or not yet seeded)")
        print(f"DIAGNOSIS: {' + '.join(modes)}")
        continue

    print(f"CANDS:   {len(candidates)} found")

    mode_d_triggered = False
    for gh, match_type in candidates:
        gt = by_hash.get(gh)
        if not gt:
            print(f"  {gh[:12]}  {match_type:<5}  [not in torrent list]")
            continue
        good_save = gt["save_path"]
        label     = fs_label(good_save, broken_save)
        shared, total, err = inode_overlap(bh, gh, broken_save, good_save, label)

        if err:
            inode_str = f"inodes=({err})"
        else:
            inode_str = f"inodes={shared}/{total}"
            if total and total > 0 and shared == total and not broken_dl:
                mode_d_triggered = True

        fuzzy_flag = "  [Mode C: fuzzy name]" if match_type == "FUZZY" else ""
        gname = good_names_map.get(gh, gt["name"])
        print(f"  {gh[:12]}  {match_type:<5}  {label:<12}  {inode_str}{fuzzy_flag}")
        print(f"           good_save={good_save}")
        if match_type == "FUZZY":
            print(f"           good_name={gname[:W-22]}")

    # Compose diagnosis
    modes = []
    if bstate == "pausedDL":
        modes.append("A (pausedDL invisible to repair script)")
    if mode_b:
        modes.append("B (not in catalog — repair script would skip)")
    fuzzy_only = candidates and all(mt == "FUZZY" for _, mt in candidates)
    if fuzzy_only:
        modes.append("C (fuzzy name match only — exact match fails)")
    if mode_d_triggered:
        modes.append("D (all files inode-shared, no download_path → recheck would fix)")
    if not modes:
        modes.append("none — should match via current repair script")
    print(f"DIAGNOSIS: {' + '.join(modes)}")

print(f"\n{'═'*W}")
PYEOF
