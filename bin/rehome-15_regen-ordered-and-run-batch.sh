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

import sqlite3
from rehome.planner import DemotionPlanner

hashes_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])

db = "/home/michael/.hashall/catalog.db"
stash_device = 49
pool_device = 44

planner = DemotionPlanner(
    catalog_path=Path(db),
    seeding_roots=["/stash/media", "/data/media", "/pool/data"],
    library_roots=["/stash/media", "/data/media"],
    stash_device=stash_device,
    pool_device=pool_device,
    stash_seeding_root="/stash/media/torrents/seeding",
    pool_seeding_root="/pool/data/seeds",
    pool_payload_root="/pool/data/seeds",
)
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT
      p.payload_hash,
      COUNT(DISTINCT ti.torrent_hash) AS group_items,
      COALESCE(SUM(CASE WHEN p.device_id = ? AND p.status='complete' THEN p.total_bytes ELSE 0 END), 0) AS payload_bytes,
      COALESCE(SUM(CASE WHEN p.device_id = ? AND p.status='complete' THEN p.file_count ELSE 0 END), 0) AS stash_total_files
    FROM payloads p
    JOIN torrent_instances ti ON ti.payload_id = p.payload_id
    WHERE p.payload_hash IS NOT NULL
    GROUP BY p.payload_hash
    HAVING SUM(CASE WHEN p.device_id = ? AND p.status='complete' THEN 1 ELSE 0 END) > 0
    """,
    (stash_device, stash_device, stash_device),
).fetchall()

eligible = []
blocked = []
for idx, r in enumerate(rows, 1):
    payload_hash = str(r["payload_hash"] or "").strip()
    if not payload_hash:
        continue
    try:
        plan = planner.plan_batch_demotion_by_payload_hash(payload_hash)
    except Exception as exc:
        blocked.append(
            {
                "payload_hash": payload_hash,
                "decision": "ERROR",
                "reason": str(exc).strip()[:300],
                "group_items": int(r["group_items"] or 0),
                "payload_bytes": int(r["payload_bytes"] or 0),
            }
        )
        continue
    decision = str(plan.get("decision") or "").upper()
    if decision not in {"MOVE", "REUSE"}:
        reasons = plan.get("reasons") or []
        blocked.append(
            {
                "payload_hash": payload_hash,
                "decision": decision or "BLOCK",
                "reason": str(reasons[0])[:300] if reasons else "",
                "group_items": int(r["group_items"] or 0),
                "payload_bytes": int(r["payload_bytes"] or 0),
            }
        )
        continue
    eligible.append(
        {
            "payload_hash": payload_hash,
            "decision": decision,
            "group_items": int(r["group_items"] or 0),
            "payload_bytes": int(r["payload_bytes"] or 0),
            "stash_total_files": int(r["stash_total_files"] or 0),
        }
    )
    if idx % 100 == 0:
        print(f"progress={idx}/{len(rows)} eligible={len(eligible)} blocked={len(blocked)}")

eligible.sort(key=lambda x: (-x["group_items"], -x["payload_bytes"], x["payload_hash"]))
blocked.sort(key=lambda x: (-x["group_items"], -x["payload_bytes"], x["payload_hash"]))

hashes_path.write_text("\n".join(x["payload_hash"] for x in eligible) + ("\n" if eligible else ""))
with report_path.open("w", encoding="utf-8") as f:
    f.write("rank\tpayload_hash\tdecision\tgroup_items\tpayload_bytes\tpayload_gib\tstash_total_files\n")
    for i, x in enumerate(eligible, 1):
        gib = x["payload_bytes"] / (1024 ** 3)
        f.write(
            f"{i}\t{x['payload_hash']}\t{x['decision']}\t{x['group_items']}\t{x['payload_bytes']}\t{gib:.2f}\t{x['stash_total_files']}\n"
        )
    f.write("\n# BLOCKED_OR_ERROR\n")
    f.write("payload_hash\tdecision\tgroup_items\tpayload_bytes\treason\n")
    for x in blocked[:2000]:
        reason = str(x["reason"]).replace("\t", " ").replace("\n", " ")
        f.write(f"{x['payload_hash']}\t{x['decision']}\t{x['group_items']}\t{x['payload_bytes']}\t{reason}\n")

conn.close()
print(f"hash_file={hashes_path}")
print(f"report_file={report_path}")
print(f"eligible_total={len(eligible)}")
print(f"blocked_total={len(blocked)}")
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
