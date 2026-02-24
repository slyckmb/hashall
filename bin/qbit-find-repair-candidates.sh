#!/usr/bin/env bash
# Find stoppedDL torrents that have a stoppedUP 100% partner with the same root_name.
# Outputs: good_hash broken_hash same_fs root_name
#
# Usage: bin/qbit-find-repair-candidates.sh [--limit N]
set -euo pipefail

source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null
QB_URL="http://localhost:9003"
DB="${HOME}/.hashall/catalog.db"
LIMIT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

COOKIE=$(mktemp /tmp/qb.XXXXXX)
trap 'rm -f "$COOKIE"' EXIT
curl -fsS -c "$COOKIE" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QBITTORRENTAPI_USERNAME" \
  --data-urlencode "password=$QBITTORRENTAPI_PASSWORD" >/dev/null

curl -fsS -b "$COOKIE" "$QB_URL/api/v2/torrents/info" > /tmp/qb_candidates_all.json

python3 << 'EOF'
import json, sqlite3, os, sys

DB = os.path.expanduser("~/.hashall/catalog.db")
LIMIT = int(os.environ.get("LIMIT","0"))

with open("/tmp/qb_candidates_all.json") as f:
    torrents = json.load(f)

by_hash = {t["hash"]: t for t in torrents}

# stoppedUP at 100%
good_hashes = {t["hash"] for t in torrents
               if t["state"] == "stoppedUP" and t["progress"] >= 0.9999}
# stoppedDL
broken_hashes = {t["hash"] for t in torrents if t["state"] == "stoppedDL"}

con = sqlite3.connect(DB)

# Get root_name for all relevant hashes
def get_root_names(hashes):
    if not hashes: return {}
    ph = ",".join("?" * len(hashes))
    rows = con.execute(
        f"SELECT torrent_hash, root_name FROM torrent_instances WHERE torrent_hash IN ({ph})",
        list(hashes)
    ).fetchall()
    return {h: n for h, n in rows}

good_names  = get_root_names(good_hashes)
broken_names = get_root_names(broken_hashes)

# Invert: root_name → list of good_hashes
from collections import defaultdict
name_to_good = defaultdict(list)
for h, n in good_names.items():
    if n: name_to_good[n].append(h)

results = []
for bh, bname in broken_names.items():
    if not bname: continue
    good = name_to_good.get(bname, [])
    if not good: continue
    for gh in good:
        gt = by_hash[gh]
        bt = by_hash[bh]
        # Determine same filesystem
        gp = gt["save_path"]
        bp = bt["save_path"]
        if gp.startswith("/pool/data") and bp.startswith("/pool/data"):
            same_fs = "pool-pool"
        elif gp.startswith("/data/media") and bp.startswith("/data/media"):
            same_fs = "stash-stash"
        elif gp.startswith("/stash/media") and bp.startswith("/stash/media"):
            same_fs = "stash-stash"
        else:
            same_fs = "cross-fs"
        results.append((gh, bh, same_fs, bname, bt["progress"]))

# Sort: same-fs first, then by progress ascending (most broken first)
results.sort(key=lambda x: (0 if x[2] != "cross-fs" else 1, x[4]))

if LIMIT:
    results = results[:LIMIT]

print(f"# good_hash broken_hash same_fs progress root_name")
for gh, bh, fs, name, prog in results:
    print(f"{gh} {bh} {fs} {prog:.3f} {name}")
EOF
