#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-101_nohl-basics-qb-candidate-mapping.sh [options]

Options:
  --baseline-json PATH     Stage 2 baseline JSON (default: latest)
  --db PATH                Catalog DB path (default: ~/.hashall/catalog.db)
  --output-prefix NAME     Output prefix (default: nohl)
  --limit N                Limit baseline entries (default: 0 = all)
  --fast                   Fast mode annotation
  --debug                  Debug mode annotation
  -h, --help               Show help
USAGE
}

latest_baseline() {
  ls -1t out/reports/rehome-normalize/nohl-qb-repair-baseline-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

BASELINE_JSON=""
DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST=1; shift ;;
    --debug) DEBUG=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$BASELINE_JSON" ]]; then
  BASELINE_JSON="$(latest_baseline)"
fi
if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing baseline JSON; run bin/rehome-100_nohl-basics-qb-repair-baseline.sh first." >&2
  exit 3
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-candidate-mapping-${stamp}.log"
json_out="${log_dir}/${OUTPUT_PREFIX}-qb-candidate-mapping-${stamp}.json"
tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-candidate-mapping-${stamp}.tsv"
confident_out="${log_dir}/${OUTPUT_PREFIX}-qb-candidate-confident-hashes-${stamp}.txt"
manual_out="${log_dir}/${OUTPUT_PREFIX}-qb-candidate-manual-only-hashes-${stamp}.txt"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 101: qB candidate mapping"
echo "What this does: rank target roots per hash from live filesystem and catalog evidence."
hr
echo "run_id=${stamp} step=basics-qb-candidate-mapping baseline_json=${BASELINE_JSON} db=${DB_PATH} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
MAP_BASELINE_JSON="$BASELINE_JSON" \
MAP_DB_PATH="$DB_PATH" \
MAP_LIMIT="$LIMIT" \
MAP_JSON_OUT="$json_out" \
MAP_TSV_OUT="$tsv_out" \
MAP_CONFIDENT_OUT="$confident_out" \
MAP_MANUAL_OUT="$manual_out" \
python - <<'PY'
import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

baseline_json = Path(os.environ["MAP_BASELINE_JSON"])
db_path = Path(os.environ["MAP_DB_PATH"])
limit = int(os.environ.get("MAP_LIMIT", "0") or 0)
json_out = Path(os.environ["MAP_JSON_OUT"])
tsv_out = Path(os.environ["MAP_TSV_OUT"])
confident_out = Path(os.environ["MAP_CONFIDENT_OUT"])
manual_out = Path(os.environ["MAP_MANUAL_OUT"])

obj = json.loads(baseline_json.read_text(encoding="utf-8"))
entries = list(obj.get("entries", []))
if limit > 0:
    entries = entries[:limit]

db_rows = {}
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        hashes = sorted(
            {
                str(e.get("hash", "")).lower()
                for e in entries
                if str(e.get("hash", "")).strip()
            }
        )
        if hashes:
            qmarks = ",".join("?" for _ in hashes)
            rows = conn.execute(
                f"""
                SELECT lower(ti.torrent_hash) AS torrent_hash,
                       ti.save_path AS db_save_path,
                       ti.root_name AS db_root_name,
                       p.root_path AS db_root_path,
                       p.payload_hash AS payload_hash
                FROM torrent_instances ti
                LEFT JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE lower(ti.torrent_hash) IN ({qmarks})
                """,
                hashes,
            ).fetchall()
            for r in rows:
                db_rows[r["torrent_hash"]] = {
                    "db_save_path": r["db_save_path"] or "",
                    "db_root_name": r["db_root_name"] or "",
                    "db_root_path": r["db_root_path"] or "",
                    "payload_hash": r["payload_hash"] or "",
                }
    finally:
        conn.close()

alias_pairs = [
    ("/data/media", "/stash/media"),
    ("/stash/media", "/data/media"),
]


def alias_swap(path: str) -> list[str]:
    out = []
    for src, dst in alias_pairs:
        if path == src:
            out.append(dst)
        elif path.startswith(src + "/"):
            out.append(dst + path[len(src) :])
    return out


mapped = []
confident_hashes = []
manual_hashes = []
for e in entries:
    torrent_hash = str(e.get("hash", "")).lower()
    save_path = str(e.get("save_path", "")).strip()
    content_path = str(e.get("content_path", "")).strip()
    db = db_rows.get(torrent_hash, {})
    candidates = {}

    def add_candidate(path: str, score: int, reason: str):
        if not path:
            return
        path = str(path).strip()
        if not path.startswith("/"):
            return
        cur = candidates.get(path)
        if cur is None or score > cur["score"]:
            candidates[path] = {"path": path, "score": score, "reason": reason}

    if save_path:
        add_candidate(save_path, 100, "save_path_exact")
        for swapped in alias_swap(save_path):
            add_candidate(swapped, 80, "save_path_alias")

    if content_path:
        cp = Path(content_path)
        croot = str(cp.parent if cp.suffix else cp)
        add_candidate(croot, 90 if cp.exists() else 50, "content_root")
        for swapped in alias_swap(croot):
            add_candidate(swapped, 70, "content_root_alias")
        if "cross-seed-link" in content_path or "/incomplete_torrents/" in content_path:
            add_candidate(croot, 30, "transient_content_path")

    db_root_path = str(db.get("db_root_path", "")).strip()
    db_save_path = str(db.get("db_save_path", "")).strip()
    if db_root_path:
        add_candidate(db_root_path, 95 if Path(db_root_path).exists() else 60, "db_root_path")
        for swapped in alias_swap(db_root_path):
            add_candidate(swapped, 75, "db_root_alias")
    if db_save_path:
        add_candidate(db_save_path, 85 if Path(db_save_path).exists() else 55, "db_save_path")
        for swapped in alias_swap(db_save_path):
            add_candidate(swapped, 70, "db_save_alias")

    ordered = sorted(candidates.values(), key=lambda c: (-c["score"], c["path"]))
    best = ordered[0] if ordered else None
    second = ordered[1] if len(ordered) > 1 else None
    confidence = "manual_only"
    if best:
        delta = best["score"] - (second["score"] if second else 0)
        best_exists = Path(best["path"]).exists()
        if best["score"] >= 85 and best_exists and delta >= 15:
            confidence = "confident"
        elif best["score"] >= 75 and delta >= 20:
            confidence = "likely"
        else:
            confidence = "ambiguous"
    if confidence == "confident":
        confident_hashes.append(torrent_hash)
    else:
        manual_hashes.append(torrent_hash)

    mapped.append(
        {
            "hash": torrent_hash,
            "state": e.get("state", ""),
            "progress": e.get("progress", 0),
            "amount_left": e.get("amount_left", 0),
            "save_path": save_path,
            "content_path": content_path,
            "db_root_path": db_root_path,
            "db_save_path": db_save_path,
            "payload_hash": db.get("payload_hash", ""),
            "best_candidate": best["path"] if best else "",
            "best_score": best["score"] if best else 0,
            "best_reason": best["reason"] if best else "",
            "candidate_count": len(ordered),
            "confidence": confidence,
            "candidates": ordered[:6],
        }
    )

summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "input_entries": len(entries),
    "mapped_entries": len(mapped),
    "confident": sum(1 for m in mapped if m["confidence"] == "confident"),
    "likely": sum(1 for m in mapped if m["confidence"] == "likely"),
    "ambiguous": sum(1 for m in mapped if m["confidence"] == "ambiguous"),
    "manual_only": sum(1 for m in mapped if m["confidence"] == "manual_only"),
}

payload = {"summary": summary, "entries": mapped}
json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

fieldnames = [
    "hash",
    "state",
    "progress",
    "amount_left",
    "confidence",
    "candidate_count",
    "best_score",
    "best_reason",
    "best_candidate",
    "save_path",
    "content_path",
    "db_root_path",
    "payload_hash",
]
with tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for row in mapped:
        writer.writerow({k: row.get(k, "") for k in fieldnames})

confident_out.write_text(
    "\n".join(sorted({h for h in confident_hashes if h})) + ("\n" if confident_hashes else ""),
    encoding="utf-8",
)
manual_out.write_text(
    "\n".join(sorted({h for h in manual_hashes if h})) + ("\n" if manual_hashes else ""),
    encoding="utf-8",
)

print(
    "summary "
    f"mapped={summary['mapped_entries']} "
    f"confident={summary['confident']} likely={summary['likely']} "
    f"ambiguous={summary['ambiguous']} manual_only={summary['manual_only']}"
)
print(f"json_output={json_out}")
print(f"tsv_output={tsv_out}")
print(f"confident_hashes={confident_out}")
print(f"manual_hashes={manual_out}")
PY

hr
echo "result=ok step=basics-qb-candidate-mapping run_log=${run_log}"
echo "json_output=${json_out}"
echo "tsv_output=${tsv_out}"
echo "confident_hashes=${confident_out}"
echo "manual_hashes=${manual_out}"
hr
