#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh [options]

Options:
  --mapping-json PATH      Phase 101 candidate mapping JSON (default: latest)
  --baseline-json PATH     Phase 100 baseline JSON (default: latest)
  --db PATH                Catalog DB path (default: ~/.hashall/catalog.db)
  --output-prefix NAME     Output prefix (default: nohl)
  --limit N                Limit entries audited (default: 0 = all)
  --fast                   Fast mode annotation
  --debug                  Debug mode annotation
  -h, --help               Show help
USAGE
}

latest_mapping() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-qb-candidate-mapping-*.json 2>/dev/null | head -n1 || true
}

latest_baseline() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-qb-repair-baseline-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MAPPING_JSON=""
BASELINE_JSON=""
DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
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

if [[ -z "$MAPPING_JSON" ]]; then
  MAPPING_JSON="$(latest_mapping)"
fi
if [[ -z "$BASELINE_JSON" ]]; then
  BASELINE_JSON="$(latest_baseline)"
fi
if [[ -z "$MAPPING_JSON" || ! -f "$MAPPING_JSON" ]]; then
  echo "Missing mapping JSON; run bin/rehome-101_nohl-basics-qb-candidate-mapping.sh first." >&2
  exit 3
fi
if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing baseline JSON; run bin/rehome-100_nohl-basics-qb-repair-baseline.sh first." >&2
  exit 3
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-payload-ownership-audit-${stamp}.log"
json_out="${log_dir}/${OUTPUT_PREFIX}-qb-payload-ownership-audit-${stamp}.json"
tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-payload-ownership-audit-${stamp}.tsv"
hashes_out="${log_dir}/${OUTPUT_PREFIX}-qb-payload-ownership-conflict-hashes-${stamp}.txt"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 103: qB payload ownership audit"
echo "What this does: enforce one-hash-per-payload ownership before Phase 102 apply."
hr
echo "run_id=${stamp} step=basics-qb-payload-ownership-audit mapping_json=${MAPPING_JSON} baseline_json=${BASELINE_JSON} db=${DB_PATH} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
AUDIT_MAPPING_JSON="$MAPPING_JSON" \
AUDIT_BASELINE_JSON="$BASELINE_JSON" \
AUDIT_DB_PATH="$DB_PATH" \
AUDIT_LIMIT="$LIMIT" \
AUDIT_JSON_OUT="$json_out" \
AUDIT_TSV_OUT="$tsv_out" \
AUDIT_HASHES_OUT="$hashes_out" \
python - <<'PY'
import csv
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

mapping_json = Path(os.environ["AUDIT_MAPPING_JSON"])
baseline_json = Path(os.environ["AUDIT_BASELINE_JSON"])
db_path = Path(os.environ["AUDIT_DB_PATH"])
limit = int(os.environ.get("AUDIT_LIMIT", "0") or 0)
json_out = Path(os.environ["AUDIT_JSON_OUT"])
tsv_out = Path(os.environ["AUDIT_TSV_OUT"])
hashes_out = Path(os.environ["AUDIT_HASHES_OUT"])

mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
baseline_by_hash = {
    str(e.get("hash", "")).lower(): e
    for e in baseline.get("entries", [])
    if str(e.get("hash", "")).strip()
}
entries = [e for e in mapping.get("entries", []) if str(e.get("hash", "")).strip()]
if limit > 0:
    entries = entries[:limit]

cross_seed_markers = {"cross-seed", "cross_seed", "crossseed"}


def normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("(api)", " ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def tracker_component_from_path(path: str) -> str:
    parts = list(Path(str(path or "").strip()).parts)
    for idx, part in enumerate(parts):
        if str(part).lower() in cross_seed_markers and idx + 1 < len(parts):
            return str(parts[idx + 1]).strip()
    return ""


def derive_target_payload_root(entry: dict) -> str:
    best_payload_root = str(entry.get("best_payload_root", "")).strip()
    if best_payload_root.startswith("/"):
        return str(Path(best_payload_root))
    target = str(entry.get("best_candidate", "")).strip()
    root_hint = str(entry.get("root_name_hint", "")).strip()
    if target.startswith("/") and root_hint:
        return str(Path(target) / root_hint)
    return ""


audited = []
target_payload_to_hashes = defaultdict(list)
old_payload_targets = defaultdict(list)
target_payload_roots = set()
for entry in entries:
    if str(entry.get("confidence", "")).lower() != "confident":
        continue
    torrent_hash = str(entry.get("hash", "")).lower().strip()
    if not torrent_hash:
        continue
    target_save_path = str(entry.get("best_candidate", "")).strip()
    if not target_save_path.startswith("/"):
        continue
    current_payload_root = str(entry.get("current_payload_root", "")).strip()
    if not current_payload_root:
        baseline_row = baseline_by_hash.get(torrent_hash, {})
        current_payload_root = str(baseline_row.get("content_path", "")).strip()
    target_payload_root = derive_target_payload_root(entry)
    row = {
        "hash": torrent_hash,
        "name": str(entry.get("name", "") or baseline_by_hash.get(torrent_hash, {}).get("name", "")),
        "state": str(entry.get("state", "") or baseline_by_hash.get(torrent_hash, {}).get("state", "")),
        "category": str(entry.get("category", "") or baseline_by_hash.get(torrent_hash, {}).get("category", "")),
        "tracker_key": str(entry.get("tracker_key", "")).strip(),
        "tracker_name": str(entry.get("tracker_name", "")).strip(),
        "current_save_path": str(entry.get("save_path", "") or baseline_by_hash.get(torrent_hash, {}).get("save_path", "")),
        "current_payload_root": current_payload_root,
        "target_save_path": target_save_path,
        "target_payload_root": target_payload_root,
        "best_score": int(entry.get("best_score", 0) or 0),
        "conflicts": [],
        "conflict_detail": [],
    }
    audited.append(row)
    if target_payload_root:
        target_payload_to_hashes[target_payload_root].append(torrent_hash)
        target_payload_roots.add(target_payload_root)
    if current_payload_root:
        old_payload_targets[current_payload_root].append(torrent_hash)

db_owner_by_payload = defaultdict(set)
if db_path.exists() and target_payload_roots:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    qmarks = ",".join("?" for _ in sorted(target_payload_roots))
    rows = conn.execute(
        f"""
        SELECT lower(ti.torrent_hash) AS torrent_hash, p.root_path AS root_path
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE p.root_path IN ({qmarks})
        """,
        sorted(target_payload_roots),
    ).fetchall()
    conn.close()
    for row in rows:
        root = str(row["root_path"] or "").strip()
        owner_hash = str(row["torrent_hash"] or "").lower().strip()
        if root and owner_hash:
            db_owner_by_payload[root].add(owner_hash)

counts = Counter()
conflict_hashes = set()
target_payload_set = {str(r.get("target_payload_root", "")) for r in audited if str(r.get("target_payload_root", ""))}
for row in audited:
    target_payload_root = str(row.get("target_payload_root", "")).strip()
    current_payload_root = str(row.get("current_payload_root", "")).strip()
    category = str(row.get("category", "")).strip()
    tracker_key = normalize_token(str(row.get("tracker_key", "")).strip())
    target_save_path = str(row.get("target_save_path", "")).strip()

    target_hashes = target_payload_to_hashes.get(target_payload_root, [])
    if target_payload_root and len(target_hashes) > 1:
        row["conflicts"].append("shared_target_payload")
        row["conflict_detail"].append(f"shared_with={','.join(sorted(set(target_hashes)))}")
        counts["shared_target_payload"] += 1

    db_owners = sorted(db_owner_by_payload.get(target_payload_root, set()))
    if target_payload_root and db_owners and any(owner != row["hash"] for owner in db_owners):
        row["conflicts"].append("target_owned_by_other_hash")
        row["conflict_detail"].append(f"db_owners={','.join(db_owners)}")
        counts["target_owned_by_other_hash"] += 1

    cross_component = normalize_token(tracker_component_from_path(target_save_path))
    target_tail = normalize_token(Path(target_save_path).name)
    category_key = normalize_token(category)
    is_cross_seed = category.lower() in cross_seed_markers
    if tracker_key:
        if is_cross_seed:
            if not cross_component or cross_component != tracker_key:
                row["conflicts"].append("tracker_category_mismatch")
                row["conflict_detail"].append(
                    f"expected_cross_seed_tracker={tracker_key} actual={cross_component or 'none'}"
                )
                counts["tracker_category_mismatch"] += 1
        else:
            if target_tail and target_tail != tracker_key:
                row["conflicts"].append("tracker_category_mismatch")
                row["conflict_detail"].append(
                    f"expected_tracker_folder={tracker_key} actual={target_tail}"
                )
                counts["tracker_category_mismatch"] += 1
    elif category_key and not is_cross_seed and target_tail and target_tail != category_key:
        row["conflicts"].append("tracker_category_mismatch")
        row["conflict_detail"].append(
            f"expected_category_folder={category_key} actual={target_tail}"
        )
        counts["tracker_category_mismatch"] += 1

    if current_payload_root and target_payload_root and current_payload_root != target_payload_root:
        if current_payload_root not in target_payload_set:
            row["conflicts"].append("old_payload_orphan_risk")
            row["conflict_detail"].append("current_payload_not_selected_as_any_target")
            counts["old_payload_orphan_risk"] += 1

    if row["conflicts"]:
        conflict_hashes.add(str(row["hash"]))

for row in audited:
    row["conflicts"] = sorted(set(row["conflicts"]))
    row["conflict_detail"] = sorted(set(row["conflict_detail"]))

summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "input_entries": len(entries),
    "audited_entries": len(audited),
    "conflict_count": len(conflict_hashes),
    "shared_target_payload_conflicts": int(counts.get("shared_target_payload", 0)),
    "target_owned_by_other_hash_conflicts": int(counts.get("target_owned_by_other_hash", 0)),
    "tracker_category_mismatch_conflicts": int(counts.get("tracker_category_mismatch", 0)),
    "old_payload_orphan_risk_conflicts": int(counts.get("old_payload_orphan_risk", 0)),
}

payload = {
    "summary": summary,
    "entries": audited,
    "conflicts": [r for r in audited if r.get("conflicts")],
}
json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

fieldnames = [
    "hash",
    "state",
    "category",
    "tracker_key",
    "current_save_path",
    "current_payload_root",
    "target_save_path",
    "target_payload_root",
    "best_score",
    "conflicts",
    "conflict_detail",
]
with tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for row in audited:
        out = dict(row)
        out["conflicts"] = ",".join(row.get("conflicts", []))
        out["conflict_detail"] = ";".join(row.get("conflict_detail", []))
        writer.writerow({k: out.get(k, "") for k in fieldnames})

hashes_out.write_text(
    "\n".join(sorted(conflict_hashes)) + ("\n" if conflict_hashes else ""),
    encoding="utf-8",
)

print(
    "summary "
    f"audited={summary['audited_entries']} "
    f"conflict_count={summary['conflict_count']} "
    f"shared_target_payload={summary['shared_target_payload_conflicts']} "
    f"target_owned_by_other_hash={summary['target_owned_by_other_hash_conflicts']} "
    f"tracker_category_mismatch={summary['tracker_category_mismatch_conflicts']} "
    f"old_payload_orphan_risk={summary['old_payload_orphan_risk_conflicts']}"
)
print(f"json_output={json_out}")
print(f"tsv_output={tsv_out}")
print(f"conflict_hashes={hashes_out}")
if summary["conflict_count"] > 0:
    raise SystemExit(2)
PY

hr
echo "result=ok step=basics-qb-payload-ownership-audit run_log=${run_log}"
echo "json_output=${json_out}"
echo "tsv_output=${tsv_out}"
echo "conflict_hashes=${hashes_out}"
hr
