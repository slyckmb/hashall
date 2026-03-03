#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-15_regen-ordered-and-run-batch.sh [--regen-only] [--debug] [batch-script args...]

What it does:
  1) Rebuild eligible rehome hash list from current DB status report groups.
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
  - --debug enables extra regen diagnostics and qB debug logs in apply step.
USAGE
}

regen_only=0
debug_mode=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --regen-only)
      regen_only=1
      shift
      ;;
    --debug)
      debug_mode=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ "$debug_mode" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
  export REHOME_REGEN_DEBUG=1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mkdir -p $HOME/.logs/hashall/reports/rehome-pilot
HASHALL_SEMVER="$(PYTHONPATH=src python - <<'PY'
from hashall import __version__
print(__version__)
PY
)"
REHOME_SEMVER="$(PYTHONPATH=src python - <<'PY'
from rehome import __version__
print(__version__)
PY
)"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "tool_semver_hashall=${HASHALL_SEMVER} tool_semver_rehome=${REHOME_SEMVER} git_sha=${GIT_SHA}"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
hashes_file="$HOME/.logs/hashall/reports/rehome-pilot/rehome-eligible-ordered-${stamp}.txt"
report_file="$HOME/.logs/hashall/reports/rehome-pilot/rehome-eligible-ordered-${stamp}.tsv"
run_log="$HOME/.logs/hashall/reports/rehome-pilot/rehome-batch-run-${stamp}.log"

echo "phase=regenerate start=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z)"
echo "phase=regenerate status=loading_db"

PYTHONPATH=src python -u - <<'PY' "$hashes_file" "$report_file"
import sys
import os
from pathlib import Path
from collections import Counter

from hashall.model import connect_db
from hashall.qbittorrent import get_qbittorrent_client
from hashall.status_report import build_status_report

hashes_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])

db = Path("/home/michael/.hashall/catalog.db")
conn = connect_db(db, read_only=False, apply_migrations=False)
report = build_status_report(
    conn,
    roots_arg="/pool/data,/stash/media,/data/media",
    media_root="/data/media",
    pocket_depth=2,
    top_n=50000,
    recovery_prefix="/data/media/torrents/seeding/recovery_20260211",
)
groups = report.get("rehome_impact_groups", [])
print(f"phase=regenerate status=loaded_impact_groups total={len(groups)}", flush=True)

# Exclude payload groups currently tagged verify_failed in qB (manual intervention queue).
failed_payload_hashes = set()
try:
    qbit = get_qbittorrent_client()
    if qbit.test_connection() and qbit.login():
        failed_torrents = qbit.get_torrents(tag="rehome_verify_failed")
        for torrent in failed_torrents:
            row = conn.execute(
                """
                SELECT p.payload_hash
                FROM torrent_instances ti
                JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE ti.torrent_hash = ?
                LIMIT 1
                """,
                (torrent.hash,),
            ).fetchone()
            if row and row[0]:
                failed_payload_hashes.add(str(row[0]))
    else:
        print("phase=regenerate warning=verify_failed_probe_skipped reason=qb_unavailable", flush=True)
except Exception as e:
    print(f"phase=regenerate warning=verify_failed_probe_error detail={e}", flush=True)

eligible = []
blocked = []
reason_counter = Counter()
for idx, g in enumerate(groups, 1):
    payload_hash = str(g.get("payload_hash") or "").strip()
    if not payload_hash:
        continue
    recommendation = str(g.get("recommendation") or "").upper()
    reasons = g.get("block_reason_counts") or {}
    group_items = int(g.get("copies") or 0)
    payload_bytes = int(g.get("stash_total_bytes") or 0)
    stash_total_files = int(g.get("stash_total_files") or 0)

    if payload_hash in failed_payload_hashes:
        reason_counter.update(["verify_failed_tag"])
        blocked.append(
            {
                "payload_hash": payload_hash,
                "decision": "SKIP_VERIFY_FAILED",
                "reason": "verify_failed_tag",
                "group_items": group_items,
                "payload_bytes": payload_bytes,
            }
        )
        continue

    # Keep regular MOVE groups and add "copy-first" groups:
    # groups blocked only because pool copy is missing.
    if recommendation == "MOVE":
        decision = "MOVE_EXISTING"
    elif reasons and set(reasons.keys()) == {"pool_copy_missing"}:
        decision = "MOVE_COPY_FIRST"
    else:
        reason_counter.update(reasons.keys())
        blocked.append(
            {
                "payload_hash": payload_hash,
                "decision": recommendation or "SKIP",
                "reason": ",".join(sorted(reasons.keys())),
                "group_items": group_items,
                "payload_bytes": payload_bytes,
            }
        )
        continue

    eligible.append(
        {
            "payload_hash": payload_hash,
            "decision": decision,
            "group_items": group_items,
            "payload_bytes": payload_bytes,
            "stash_total_files": stash_total_files,
        }
    )
    if idx == 1 or idx % 50 == 0:
        print(
            f"phase=regenerate progress={idx}/{len(groups)} eligible={len(eligible)} blocked={len(blocked)}",
            flush=True,
        )

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
print(f"blocked_verify_failed={len(failed_payload_hashes)}")
if os.getenv("REHOME_REGEN_DEBUG", "0") == "1":
    top_reasons = ",".join(
        f"{k}:{v}" for k, v in reason_counter.most_common(8)
    ) or "none"
    print(f"debug_top_block_reasons={top_reasons}")
    if eligible:
        head = eligible[:5]
        print(
            "debug_top_eligible="
            + ",".join(f"{x['payload_hash'][:12]}:{x['group_items']}:{x['payload_bytes']}" for x in head)
        )
    if blocked:
        head_b = blocked[:5]
        print(
            "debug_top_blocked="
            + ",".join(f"{x['payload_hash'][:12]}:{x['reason']}" for x in head_b)
        )
PY
echo "phase=regenerate done=$(TZ=America/New_York date +%Y-%m-%dT%H:%M:%S%z)"

hash_file="$hashes_file"

if [[ ! -s "$hash_file" ]]; then
  echo "ERROR: no eligible hashes generated" >&2
  exit 40
fi

echo "hash_file=$hash_file"
echo "report_file=$report_file"
echo "run_log=$run_log"

if [[ "$regen_only" -eq 1 ]]; then
  echo "phase=run skipped=true reason=regen_only"
  exit 0
fi

{
  if [[ "$debug_mode" -eq 1 ]]; then
    echo "debug_mode=1 HASHALL_REHOME_QB_DEBUG=${HASHALL_REHOME_QB_DEBUG:-0} REHOME_REGEN_DEBUG=${REHOME_REGEN_DEBUG:-0}"
  fi
  echo "cmd=bin/rehome-10_apply-batch-with-guards.sh --hashes-file '$hash_file' $*"
  bin/rehome-10_apply-batch-with-guards.sh --hashes-file "$hash_file" "$@"
} 2>&1 | tee "$run_log"
