#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-30_nohl-discover-and-rank.sh [options]

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --qbit-url URL            qBittorrent URL (default: env QBIT_URL or http://localhost:9003)
  --qbit-user USER          qBittorrent user (default: env QBIT_USER or admin)
  --qbit-pass PASS          qBittorrent pass (default: env QBIT_PASS or adminpass)
  --tag NAME                qB tag filter (default: ~noHL)
  --stash-prefix PATH       Source alias prefix (repeatable; default: /stash/media and /data/media)
  --pool-seeds-root PATH    Pool seeds root to exclude (default: /pool/data/seeds)
  --pool-name NAME          ZFS pool name for free-space snapshot (default: pool)
  --min-free-pct N          Advisory free-space floor in report (default: 20)
  --limit N                 Limit ranked eligible groups (default: 0 = all)
  --fast                    Fast mode (skip heavy status-report enrichment)
  --debug                   Debug mode (verbose config + qB debug env)
  --output-prefix NAME      Output file prefix (default: nohl)
  -h, --help                Show help
USAGE
}

DB_PATH="/home/michael/.hashall/catalog.db"
QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
TAG_NAME="~noHL"
POOL_SEEDS_ROOT="/pool/data/seeds"
POOL_NAME="pool"
MIN_FREE_PCT="20"
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0
declare -a STASH_PREFIXES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --qbit-url) QBIT_URL="${2:-}"; shift 2 ;;
    --qbit-user) QBIT_USER="${2:-}"; shift 2 ;;
    --qbit-pass) QBIT_PASS="${2:-}"; shift 2 ;;
    --tag) TAG_NAME="${2:-}"; shift 2 ;;
    --stash-prefix) STASH_PREFIXES+=("${2:-}"); shift 2 ;;
    --pool-seeds-root) POOL_SEEDS_ROOT="${2:-}"; shift 2 ;;
    --pool-name) POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ${#STASH_PREFIXES[@]} -eq 0 ]]; then
  STASH_PREFIXES=("/stash/media" "/data/media")
fi
if [[ "$DEBUG_MODE" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-discover-rank-${stamp}.log"
json_out="${log_dir}/${OUTPUT_PREFIX}-discover-${stamp}.json"
hashes_out="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-ranked-${stamp}.txt"
tsv_out="${log_dir}/${OUTPUT_PREFIX}-payload-groups-ranked-${stamp}.tsv"

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

{
  hr
  echo "Phase 30: Discover and rank noHL payload groups"
  echo "What this does: find ~noHL torrents on stash paths, map to payload groups, rank largest impact first."
  hr
  echo "tool_semver_hashall=${HASHALL_SEMVER} tool_semver_rehome=${REHOME_SEMVER} git_sha=${GIT_SHA}"
  echo "run_id=${stamp} step=nohl-discover-and-rank"
  echo "config db=${DB_PATH} qbit_url=${QBIT_URL} tag=${TAG_NAME} pool_seeds_root=${POOL_SEEDS_ROOT} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT} limit=${LIMIT} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  echo "config stash_prefixes=$(IFS=,; echo "${STASH_PREFIXES[*]}")"
  STASH_PREFIXES_CSV="$(IFS=,; echo "${STASH_PREFIXES[*]}")" \
  PYTHONPATH=src python -u - <<'PY' "$DB_PATH" "$QBIT_URL" "$QBIT_USER" "$QBIT_PASS" "$TAG_NAME" "$POOL_SEEDS_ROOT" "$LIMIT" "$MIN_FREE_PCT" "$POOL_NAME" "$json_out" "$hashes_out" "$tsv_out" "$FAST_MODE" "$DEBUG_MODE"
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from hashall.qbittorrent import QBittorrentClient
from hashall.status_report import build_status_report
from rehome.nohl_restart import filter_nohl_candidates, sort_payload_groups

(
    db_path,
    qbit_url,
    qbit_user,
    qbit_pass,
    tag_name,
    pool_seeds_root,
    limit_raw,
    min_free_pct_raw,
    pool_name,
    json_out,
    hashes_out,
    tsv_out,
    fast_mode_raw,
    debug_mode_raw,
) = sys.argv[1:15]

stash_prefixes = [p for p in str(__import__("os").environ.get("STASH_PREFIXES_CSV", "")).split(",") if p]
limit = max(0, int(limit_raw))
min_free_pct = int(min_free_pct_raw)
fast_mode = str(fast_mode_raw).strip() == "1"
debug_mode = str(debug_mode_raw).strip() == "1"
db = Path(db_path)

qb = QBittorrentClient(base_url=qbit_url, username=qbit_user, password=qbit_pass)
torrents = qb.get_torrents(tag=tag_name)
rows = [{"hash": t.hash, "save_path": t.save_path, "tags": t.tags} for t in torrents]
selected = filter_nohl_candidates(
    rows,
    tag=tag_name,
    stash_prefixes=stash_prefixes,
    pool_seeds_root=pool_seeds_root,
)
selected_hashes = sorted({item.torrent_hash for item in selected})

conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

payload_to_torrents: dict[str, set[str]] = defaultdict(set)
if selected_hashes:
    chunk_size = 500
    for i in range(0, len(selected_hashes), chunk_size):
        chunk = selected_hashes[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        query = f"""
            SELECT lower(ti.torrent_hash) AS torrent_hash, p.payload_hash
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) IN ({placeholders})
              AND p.payload_hash IS NOT NULL
              AND p.payload_hash != ''
              AND p.status = 'complete'
        """
        for row in conn.execute(query, chunk).fetchall():
            payload_hash = str(row["payload_hash"] or "").strip()
            torrent_hash = str(row["torrent_hash"] or "").strip().lower()
            if payload_hash and torrent_hash:
                payload_to_torrents[payload_hash].add(torrent_hash)

impact_index = {}
if not fast_mode:
    report = build_status_report(
        conn,
        roots_arg="/pool/data,/stash/media,/data/media",
        media_root="/data/media",
        pocket_depth=2,
        top_n=50000,
        recovery_prefix="/data/media/torrents/seeding/recovery_20260211",
    )
    impact_index = {
        str(item.get("payload_hash") or "").strip(): item
        for item in (report.get("rehome_impact_groups") or [])
        if str(item.get("payload_hash") or "").strip()
    }

rank_rows: list[dict] = []
for payload_hash, torrent_set in payload_to_torrents.items():
    impact = impact_index.get(payload_hash, {})
    reasons = dict(impact.get("block_reason_counts") or {})
    recommendation = str(impact.get("recommendation") or "").upper()
    eligible = recommendation == "MOVE" or set(reasons.keys()) == {"pool_copy_missing"} or not recommendation

    group_items = int(impact.get("copies") or len(torrent_set))
    payload_bytes = int(impact.get("stash_total_bytes") or 0)
    if payload_bytes <= 0:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(total_bytes), 0)
            FROM payloads
            WHERE payload_hash = ?
              AND status = 'complete'
              AND (
                root_path LIKE '/stash/media/%'
                OR root_path LIKE '/data/media/%'
              )
            """,
            (payload_hash,),
        ).fetchone()
        payload_bytes = int((row[0] if row else 0) or 0)
    if payload_bytes <= 0:
        row = conn.execute(
            "SELECT COALESCE(MAX(total_bytes), 0) FROM payloads WHERE payload_hash = ? AND status = 'complete'",
            (payload_hash,),
        ).fetchone()
        payload_bytes = int((row[0] if row else 0) or 0)

    rank_rows.append(
        {
            "payload_hash": payload_hash,
            "group_items": group_items,
            "payload_bytes": payload_bytes,
            "selected_torrents": len(torrent_set),
            "recommendation": recommendation or "UNKNOWN",
            "block_reasons": reasons,
            "eligible": bool(eligible),
        }
    )

ranked_all = sort_payload_groups(rank_rows)
ranked_eligible = [row for row in ranked_all if row.get("eligible")]
if limit > 0:
    ranked_eligible = ranked_eligible[:limit]

Path(hashes_out).write_text(
    "\n".join(row["payload_hash"] for row in ranked_eligible) + ("\n" if ranked_eligible else ""),
    encoding="utf-8",
)

with Path(tsv_out).open("w", encoding="utf-8") as f:
    f.write(
        "rank\tpayload_hash\teligible\trecommendation\tgroup_items\tpayload_bytes\tpayload_gib\tselected_torrents\tblock_reasons\n"
    )
    for idx, row in enumerate(ranked_all, start=1):
        gib = float(row["payload_bytes"]) / float(1024 ** 3)
        reasons = ",".join(sorted((row.get("block_reasons") or {}).keys())) or "-"
        f.write(
            f"{idx}\t{row['payload_hash']}\t{int(bool(row['eligible']))}\t{row['recommendation']}\t"
            f"{row['group_items']}\t{row['payload_bytes']}\t{gib:.2f}\t{row['selected_torrents']}\t{reasons}\n"
        )

pool_free_pct = None
try:
    cap = (
        subprocess.check_output(["zpool", "list", "-H", "-o", "cap", pool_name], text=True)
        .strip()
        .replace("%", "")
        .strip()
    )
    used = int(cap)
    pool_free_pct = 100 - used
except Exception:
    pool_free_pct = None

summary = {
    "total_torrents": len(torrents),
    "selected_nohl_torrents": len(selected_hashes),
    "selected_payload_groups": len(payload_to_torrents),
    "eligible_payload_groups": len([r for r in ranked_all if r.get("eligible")]),
    "eligible_after_limit": len(ranked_eligible),
    "pool_free_pct": pool_free_pct,
    "min_free_pct": min_free_pct,
    "fast_mode": fast_mode,
    "debug_mode": debug_mode,
}
payload = {
    "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
    "db": str(db),
    "qbit_url": qbit_url,
    "tag": tag_name,
    "stash_prefixes": stash_prefixes,
    "pool_seeds_root": pool_seeds_root,
    "summary": summary,
    "eligible_ranked": ranked_eligible,
    "ranked_all": ranked_all,
}
Path(json_out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
conn.close()

print(
    f"summary total_torrents={summary['total_torrents']} selected_nohl_torrents={summary['selected_nohl_torrents']} "
    f"selected_payload_groups={summary['selected_payload_groups']} eligible_payload_groups={summary['eligible_payload_groups']} "
    f"eligible_after_limit={summary['eligible_after_limit']} pool_free_pct={summary['pool_free_pct']} min_free_pct={summary['min_free_pct']}"
)
if debug_mode:
    print(f"debug selected_hashes_sample={selected_hashes[:10]}")
print(f"json_output={json_out}")
print(f"hashes_output={hashes_out}")
print(f"tsv_output={tsv_out}")
PY
  if [[ -f "$json_out" ]]; then
    total_torrents="$(jq -r '.summary.total_torrents // 0' "$json_out")"
    selected_torrents="$(jq -r '.summary.selected_nohl_torrents // 0' "$json_out")"
    payload_groups="$(jq -r '.summary.selected_payload_groups // 0' "$json_out")"
    eligible_groups="$(jq -r '.summary.eligible_after_limit // 0' "$json_out")"
    pool_free="$(jq -r '.summary.pool_free_pct // "unknown"' "$json_out")"
    hr
    echo "Phase 30 complete: scanned ${total_torrents} tagged torrents, selected ${selected_torrents}, grouped into ${payload_groups}, queued ${eligible_groups}. pool_free_pct=${pool_free}"
    hr
  fi
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "json_output=${json_out}"
echo "hashes_output=${hashes_out}"
echo "tsv_output=${tsv_out}"
