#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-15_regen-ordered-and-run-batch.sh [batch-script args...]

What it does:
  1) Rebuild eligible rehome hash list from current DB/planner decisions.
  2) Order hashes by:
       - group_items (torrent refs in payload hash group), DESC
       - payload_bytes (largest first), DESC
       - payload_hash (stable tie-break)
  3) Write outputs:
       - ordered hashes txt
       - ranked TSV report
  4) Run guarded batch apply script with tee log.

Notes:
  - Any args are forwarded to bin/rehome-10_apply-batch-with-guards.sh
  - Defaults (db/devices/space guard) come from the guarded batch script.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mkdir -p out/reports/rehome-pilot
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
hashes_file="out/reports/rehome-pilot/rehome-eligible-ordered-${stamp}.txt"
report_file="out/reports/rehome-pilot/rehome-eligible-ordered-${stamp}.tsv"
run_log="out/reports/rehome-pilot/rehome-batch-run-${stamp}.log"

PYTHONPATH=src python - <<'PY' "$hashes_file" "$report_file"
import sys
from pathlib import Path

from hashall.model import connect_db
from hashall.status_report import build_status_report

hashes_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])

db = "/home/michael/.hashall/catalog.db"
conn = connect_db(db, read_only=True, apply_migrations=False)
report = build_status_report(
    conn,
    roots_arg="/pool/data,/stash/media,/data/media",
    media_root="/data/media",
    pocket_depth=2,
    top_n=50000,
    recovery_prefix="/data/media/torrents/seeding/recovery_20260211",
)
groups = report.get("rehome_impact_groups", [])

eligible = []
for g in groups:
    payload_hash = str(g.get("payload_hash") or "").strip()
    if not payload_hash:
        continue
    recommendation = str(g.get("recommendation") or "").strip().upper()
    movable_bytes = int(g.get("movable_bytes") or 0)
    movable_pct = float(g.get("movable_pct_bytes") or 0.0)
    if recommendation != "MOVE":
        continue
    if movable_bytes <= 0:
        continue
    if movable_pct < 0.999999:
        continue
    eligible.append(
        {
            "payload_hash": payload_hash,
            "recommendation": recommendation,
            "group_items": int(g.get("copies") or 0),
            "payload_bytes": int(g.get("stash_total_bytes") or 0),
            "movable_bytes": movable_bytes,
            "movable_pct_bytes": movable_pct,
            "stash_total_files": int(g.get("stash_total_files") or 0),
        }
    )

eligible.sort(key=lambda x: (-x["group_items"], -x["payload_bytes"], x["payload_hash"]))

hashes_path.write_text("\n".join(x["payload_hash"] for x in eligible) + ("\n" if eligible else ""))
with report_path.open("w", encoding="utf-8") as f:
    f.write("rank\tpayload_hash\trecommendation\tgroup_items\tpayload_bytes\tpayload_gib\tmovable_bytes\tmovable_pct_bytes\tstash_total_files\n")
    for i, x in enumerate(eligible, 1):
        gib = x["payload_bytes"] / (1024 ** 3)
        f.write(
            f"{i}\t{x['payload_hash']}\t{x['recommendation']}\t{x['group_items']}\t{x['payload_bytes']}\t{gib:.2f}\t{x['movable_bytes']}\t{x['movable_pct_bytes']:.6f}\t{x['stash_total_files']}\n"
        )

conn.close()
print(f"hash_file={hashes_path}")
print(f"report_file={report_path}")
print(f"eligible_total={len(eligible)}")
PY

hash_file="$hashes_file"

if [[ ! -s "$hash_file" ]]; then
  echo "ERROR: no eligible hashes generated" >&2
  exit 40
fi

echo "hash_file=$hash_file"
echo "report_file=$report_file"
echo "run_log=$run_log"

{
  echo "cmd=bin/rehome-10_apply-batch-with-guards.sh --hashes-file '$hash_file' $*"
  bin/rehome-10_apply-batch-with-guards.sh --hashes-file "$hash_file" "$@"
} 2>&1 | tee "$run_log"
