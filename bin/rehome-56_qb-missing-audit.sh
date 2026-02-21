#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-56_qb-missing-audit.sh [options]

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --input-json PATH         Optional qB torrents JSON input (skip live API when provided)
  --manifest PATH           Optional plan manifest for context (default: latest nohl-plan-manifest-*.json)
  --apply-failed PATH       Optional apply-failed payload hashes file (default: latest)
  --apply-deferred PATH     Optional apply-deferred payload hashes file (default: latest)
  --followup PATH           Optional followup JSON file (default: latest nohl-followup-*.json)
  --stash-root PATH         Stash root alias A (default: /stash/media)
  --data-root PATH          Stash root alias B (default: /data/media)
  --pool-root PATH          Pool root (default: /pool/data)
  --limit N                 Limit missing torrents analyzed (default: 0 = all)
  --output-prefix NAME      Output prefix (default: nohl)
  --fast                    Fast mode annotation
  --debug                   Debug mode annotation
  -h, --help                Show help
USAGE
}

latest_file() {
  local pattern="$1"
  ls -1t $pattern 2>/dev/null | head -n1 || true
}

DB_PATH="/home/michael/.hashall/catalog.db"
INPUT_JSON=""
MANIFEST_JSON=""
APPLY_FAILED_PATH=""
APPLY_DEFERRED_PATH=""
FOLLOWUP_JSON=""
STASH_ROOT="/stash/media"
DATA_ROOT="/data/media"
POOL_ROOT="/pool/data"
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --input-json) INPUT_JSON="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_JSON="${2:-}"; shift 2 ;;
    --apply-failed) APPLY_FAILED_PATH="${2:-}"; shift 2 ;;
    --apply-deferred) APPLY_DEFERRED_PATH="${2:-}"; shift 2 ;;
    --followup) FOLLOWUP_JSON="${2:-}"; shift 2 ;;
    --stash-root) STASH_ROOT="${2:-}"; shift 2 ;;
    --data-root) DATA_ROOT="${2:-}"; shift 2 ;;
    --pool-root) POOL_ROOT="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit value: $LIMIT" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "$MANIFEST_JSON" ]]; then
  MANIFEST_JSON="$(latest_file "out/reports/rehome-normalize/${OUTPUT_PREFIX}-plan-manifest-*.json")"
fi
if [[ -z "$APPLY_FAILED_PATH" ]]; then
  APPLY_FAILED_PATH="$(latest_file "out/reports/rehome-normalize/${OUTPUT_PREFIX}-payload-hashes-apply-failed-*.txt")"
fi
if [[ -z "$APPLY_DEFERRED_PATH" ]]; then
  APPLY_DEFERRED_PATH="$(latest_file "out/reports/rehome-normalize/${OUTPUT_PREFIX}-payload-hashes-apply-deferred-*.txt")"
fi
if [[ -z "$FOLLOWUP_JSON" ]]; then
  FOLLOWUP_JSON="$(latest_file "out/reports/rehome-normalize/${OUTPUT_PREFIX}-followup-*.json")"
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-qb-missing-audit-${stamp}.log"
audit_json="${log_dir}/${OUTPUT_PREFIX}-qb-missing-audit-${stamp}.json"
audit_tsv="${log_dir}/${OUTPUT_PREFIX}-qb-missing-audit-${stamp}.tsv"
plan_json="${log_dir}/${OUTPUT_PREFIX}-qb-missing-remediate-plan-${stamp}.json"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 56: qB missingFiles audit"
echo "What this does: classify missingFiles torrents and build a targeted remediation plan."
hr
echo "run_id=${stamp} step=qb-missing-audit"
echo "config db=${DB_PATH} input_json=${INPUT_JSON:-live_api} manifest=${MANIFEST_JSON:-none} apply_failed=${APPLY_FAILED_PATH:-none} apply_deferred=${APPLY_DEFERRED_PATH:-none} followup=${FOLLOWUP_JSON:-none} stash_root=${STASH_ROOT} data_root=${DATA_ROOT} pool_root=${POOL_ROOT} limit=${LIMIT} fast=${FAST_MODE} debug=${DEBUG_MODE}"

PYTHONPATH=src \
AUDIT_DB_PATH="$DB_PATH" \
AUDIT_INPUT_JSON="$INPUT_JSON" \
AUDIT_MANIFEST_JSON="$MANIFEST_JSON" \
AUDIT_APPLY_FAILED_PATH="$APPLY_FAILED_PATH" \
AUDIT_APPLY_DEFERRED_PATH="$APPLY_DEFERRED_PATH" \
AUDIT_FOLLOWUP_JSON="$FOLLOWUP_JSON" \
AUDIT_STASH_ROOT="$STASH_ROOT" \
AUDIT_DATA_ROOT="$DATA_ROOT" \
AUDIT_POOL_ROOT="$POOL_ROOT" \
AUDIT_LIMIT="$LIMIT" \
AUDIT_JSON_OUT="$audit_json" \
AUDIT_TSV_OUT="$audit_tsv" \
AUDIT_PLAN_JSON_OUT="$plan_json" \
AUDIT_FAST="$FAST_MODE" \
AUDIT_DEBUG="$DEBUG_MODE" \
python - <<'PY'
import csv
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from hashall.qbittorrent import get_qbittorrent_client


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_hash_file(path: str) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    return {
        line.strip().lower()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _read_followup(path: str) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    obj = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for entry in obj.get("entries", []):
        outcome = str(entry.get("outcome") or "")
        for torrent_hash in entry.get("candidate_torrents") or []:
            if torrent_hash:
                out[str(torrent_hash).lower()] = outcome
    return out


def _swap_alias(path: str, from_root: str, to_root: str) -> Optional[str]:
    if not path:
        return None
    from_root_clean = from_root.rstrip("/")
    to_root_clean = to_root.rstrip("/")
    if path == from_root_clean:
        return to_root_clean
    prefix = from_root_clean + "/"
    if path.startswith(prefix):
        return to_root_clean + path[len(from_root_clean):]
    return None


def _tags_set(raw: str) -> set[str]:
    return {part.strip() for part in str(raw or "").split(",") if part.strip()}


def _exists(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:
        return False


def _load_torrents(input_json: str) -> List[dict]:
    if input_json:
        p = Path(input_json)
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            rows = obj.get("torrents", [])
        else:
            rows = obj
        torrents = []
        for row in rows:
            torrents.append(
                {
                    "hash": str(row.get("hash", "")).lower(),
                    "name": str(row.get("name", "")),
                    "save_path": str(row.get("save_path", "")),
                    "content_path": str(row.get("content_path", "")),
                    "category": str(row.get("category", "")),
                    "tags": str(row.get("tags", "")),
                    "state": str(row.get("state", "")),
                    "size": int(row.get("size", 0) or 0),
                    "progress": float(row.get("progress", 0.0) or 0.0),
                }
            )
        return torrents

    qb = get_qbittorrent_client(
        base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
        username=os.getenv("QBIT_USER", "admin"),
        password=os.getenv("QBIT_PASS", "adminpass"),
    )
    rows = qb.get_torrents()
    torrents = []
    for row in rows:
        torrents.append(
            {
                "hash": str(row.hash).lower(),
                "name": str(row.name or ""),
                "save_path": str(row.save_path or ""),
                "content_path": str(row.content_path or ""),
                "category": str(row.category or ""),
                "tags": str(row.tags or ""),
                "state": str(row.state or ""),
                "size": int(row.size or 0),
                "progress": float(row.progress or 0.0),
            }
        )
    return torrents


db_path = os.environ["AUDIT_DB_PATH"]
input_json = os.environ.get("AUDIT_INPUT_JSON", "").strip()
manifest_json = os.environ.get("AUDIT_MANIFEST_JSON", "").strip()
apply_failed_path = os.environ.get("AUDIT_APPLY_FAILED_PATH", "").strip()
apply_deferred_path = os.environ.get("AUDIT_APPLY_DEFERRED_PATH", "").strip()
followup_json = os.environ.get("AUDIT_FOLLOWUP_JSON", "").strip()
stash_root = os.environ.get("AUDIT_STASH_ROOT", "/stash/media").rstrip("/")
data_root = os.environ.get("AUDIT_DATA_ROOT", "/data/media").rstrip("/")
pool_root = os.environ.get("AUDIT_POOL_ROOT", "/pool/data").rstrip("/")
limit = int(os.environ.get("AUDIT_LIMIT", "0") or 0)
audit_json_out = Path(os.environ["AUDIT_JSON_OUT"])
audit_tsv_out = Path(os.environ["AUDIT_TSV_OUT"])
plan_json_out = Path(os.environ["AUDIT_PLAN_JSON_OUT"])
fast_mode = _bool(os.environ.get("AUDIT_FAST", "0"))
debug_mode = _bool(os.environ.get("AUDIT_DEBUG", "0"))

torrents = _load_torrents(input_json)
missing_rows = [row for row in torrents if "missing" in str(row.get("state", "")).lower()]
if limit > 0:
    missing_rows = missing_rows[:limit]

missing_hashes = [str(row.get("hash", "")).lower() for row in missing_rows if row.get("hash")]
missing_hash_set = set(missing_hashes)

apply_failed_payloads = _read_hash_file(apply_failed_path)
apply_deferred_payloads = _read_hash_file(apply_deferred_path)
followup_by_hash = _read_followup(followup_json)

db_rows_by_hash: dict[str, dict] = {}
if Path(db_path).exists() and missing_hashes:
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" for _ in missing_hashes)
        query = f"""
            SELECT lower(ti.torrent_hash) AS torrent_hash,
                   ti.payload_id,
                   ti.save_path AS db_save_path,
                   ti.root_name AS db_root_name,
                   p.payload_hash,
                   p.root_path AS db_root_path,
                   p.device_id AS db_device_id,
                   p.status AS db_status
            FROM torrent_instances ti
            LEFT JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) IN ({placeholders})
        """
        for row in conn.execute(query, missing_hashes):
            db_rows_by_hash[str(row[0])] = {
                "payload_id": row[1],
                "db_save_path": row[2],
                "db_root_name": row[3],
                "payload_hash": row[4],
                "db_root_path": row[5],
                "db_device_id": row[6],
                "db_status": row[7],
            }
    finally:
        conn.close()

existing_by_root: dict[str, list[dict]] = defaultdict(list)
for row in torrents:
    content_path = str(row.get("content_path") or "")
    if not content_path:
        continue
    if not _exists(content_path):
        continue
    root_name = Path(content_path).name
    existing_by_root[root_name].append(
        {
            "hash": str(row.get("hash", "")).lower(),
            "save_path": str(row.get("save_path", "")),
            "content_path": content_path,
            "state": str(row.get("state", "")),
            "tags": str(row.get("tags", "")),
            "size": int(row.get("size", 0) or 0),
        }
    )

entries: list[dict] = []
actions: list[dict] = []
class_counter: Counter[str] = Counter()
action_reason_counter: Counter[str] = Counter()

for row in missing_rows:
    torrent_hash = str(row.get("hash", "")).lower()
    save_path = str(row.get("save_path", ""))
    content_path = str(row.get("content_path", ""))
    tags = _tags_set(str(row.get("tags", "")))
    db = db_rows_by_hash.get(torrent_hash, {})
    db_payload_hash = str(db.get("payload_hash") or "").lower()

    save_exists = _exists(save_path)
    content_exists = _exists(content_path)
    db_root_path = str(db.get("db_root_path") or "")
    db_root_exists = _exists(db_root_path)

    alias_save_candidates = []
    alias_save_a = _swap_alias(save_path, stash_root, data_root)
    alias_save_b = _swap_alias(save_path, data_root, stash_root)
    if alias_save_a:
        alias_save_candidates.append(alias_save_a)
    if alias_save_b:
        alias_save_candidates.append(alias_save_b)
    alias_save_existing = [p for p in alias_save_candidates if _exists(p)]

    alias_content_candidates = []
    alias_content_a = _swap_alias(content_path, stash_root, data_root)
    alias_content_b = _swap_alias(content_path, data_root, stash_root)
    if alias_content_a:
        alias_content_candidates.append(alias_content_a)
    if alias_content_b:
        alias_content_candidates.append(alias_content_b)
    alias_content_existing = [p for p in alias_content_candidates if _exists(p)]

    root_name = Path(content_path).name if content_path else str(db.get("db_root_name") or "")
    missing_size = int(row.get("size", 0) or 0)
    root_candidates = [
        c for c in existing_by_root.get(root_name, [])
        if c.get("hash") != torrent_hash
    ] if root_name else []
    size_matched_candidates = [
        c for c in root_candidates
        if missing_size <= 0
        or int(c.get("size", 0) or 0) <= 0
        or int(c.get("size", 0) or 0) == missing_size
    ]
    unique_candidate_save_paths = sorted(
        {str(c.get("save_path", "")) for c in size_matched_candidates if c.get("save_path")}
    )

    root_cause = "content_missing_no_candidate"
    proposed_action = None
    action_reason = ""
    confidence = 0.0

    if content_exists:
        root_cause = "qb_false_missing_content_exists"
    elif alias_save_existing:
        root_cause = "alias_path_mismatch"
        proposed_action = {
            "action": "set_location",
            "target_save_path": alias_save_existing[0],
        }
        action_reason = "alias_path_mismatch"
        confidence = 0.95
    elif len(unique_candidate_save_paths) == 1:
        root_cause = "root_name_relink_candidate"
        proposed_action = {
            "action": "set_location",
            "target_save_path": unique_candidate_save_paths[0],
        }
        action_reason = "root_name_unique_candidate"
        confidence = 0.75
    elif root_candidates and not size_matched_candidates:
        root_cause = "root_name_size_mismatch"
    elif len(unique_candidate_save_paths) > 1:
        root_cause = "ambiguous_root_name_candidates"
    elif not db_payload_hash and str(db.get("db_status") or "").lower() == "incomplete":
        root_cause = "db_incomplete_missing_payload"
    elif save_exists and not content_exists:
        root_cause = "save_exists_content_missing"

    class_counter[root_cause] += 1

    if proposed_action:
        action_reason_counter[action_reason] += 1
        actions.append(
            {
                "torrent_hash": torrent_hash,
                "current_save_path": save_path,
                "target_save_path": proposed_action["target_save_path"],
                "root_name": root_name,
                "root_cause": root_cause,
                "reason": action_reason,
                "confidence": confidence,
                "state": str(row.get("state", "")),
                "tags": sorted(tags),
            }
        )

    entry = {
        "torrent_hash": torrent_hash,
        "name": str(row.get("name", "")),
        "state": str(row.get("state", "")),
        "progress": float(row.get("progress", 0.0) or 0.0),
        "save_path": save_path,
        "content_path": content_path,
        "root_name": root_name,
        "tags": sorted(tags),
        "root_cause": root_cause,
        "save_exists": save_exists,
        "content_exists": content_exists,
        "db_root_exists": db_root_exists,
        "alias_save_existing": alias_save_existing,
        "alias_content_existing": alias_content_existing,
        "same_root_name_candidates": root_candidates[:10],
        "same_root_name_candidate_count": len(root_candidates),
        "size_matched_candidate_count": len(size_matched_candidates),
        "size_bytes": missing_size,
        "db_payload_id": db.get("payload_id"),
        "db_payload_hash": db_payload_hash or None,
        "db_device_id": db.get("db_device_id"),
        "db_status": db.get("db_status"),
        "db_root_path": db_root_path or None,
        "in_latest_apply_failed_payload_group": bool(db_payload_hash and db_payload_hash in apply_failed_payloads),
        "in_latest_apply_deferred_payload_group": bool(db_payload_hash and db_payload_hash in apply_deferred_payloads),
        "followup_outcome": followup_by_hash.get(torrent_hash),
        "likely_rehome_related": any(tag.startswith("rehome") for tag in tags),
        "proposed_action": proposed_action,
    }
    entries.append(entry)

entries.sort(key=lambda item: (item["root_cause"], item["torrent_hash"]))
actions.sort(key=lambda item: (-(item.get("confidence") or 0.0), item["torrent_hash"]))

summary = {
    "total_torrents": len(torrents),
    "missing_total": len(missing_rows),
    "actionable_total": len(actions),
    "class_counts": dict(class_counter),
    "action_reason_counts": dict(action_reason_counter),
    "with_rehome_tag": sum(1 for e in entries if e["likely_rehome_related"]),
    "with_payload_hash": sum(1 for e in entries if e["db_payload_hash"]),
    "without_payload_hash": sum(1 for e in entries if not e["db_payload_hash"]),
    "save_exists_content_missing": sum(1 for e in entries if e["save_exists"] and not e["content_exists"]),
    "apply_failed_payload_match": sum(1 for e in entries if e["in_latest_apply_failed_payload_group"]),
    "apply_deferred_payload_match": sum(1 for e in entries if e["in_latest_apply_deferred_payload_group"]),
    "followup_failed_match": sum(1 for e in entries if e["followup_outcome"] == "failed"),
}

audit_obj = {
    "generated_at": datetime.now().isoformat(),
    "source": "input_json" if input_json else "live_qb_api",
    "config": {
        "db": db_path,
        "input_json": input_json or None,
        "stash_root": stash_root,
        "data_root": data_root,
        "pool_root": pool_root,
        "limit": limit,
        "fast_mode": fast_mode,
        "debug_mode": debug_mode,
    },
    "artifacts": {
        "manifest": manifest_json or None,
        "apply_failed_payload_hashes": apply_failed_path or None,
        "apply_deferred_payload_hashes": apply_deferred_path or None,
        "followup_json": followup_json or None,
    },
    "summary": summary,
    "entries": entries,
}

plan_obj = {
    "generated_at": datetime.now().isoformat(),
    "source_audit": str(audit_json_out),
    "mode": "set_location_only",
    "summary": {
        "actions_total": len(actions),
        "actionable_classes": dict(action_reason_counter),
        "manual_review_total": len(entries) - len(actions),
    },
    "actions": actions,
}

audit_json_out.write_text(json.dumps(audit_obj, indent=2) + "\n", encoding="utf-8")
plan_json_out.write_text(json.dumps(plan_obj, indent=2) + "\n", encoding="utf-8")

with audit_tsv_out.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(
        [
            "torrent_hash",
            "state",
            "root_cause",
            "save_exists",
            "content_exists",
            "db_payload_hash",
            "db_status",
            "save_path",
            "content_path",
            "action",
            "target_save_path",
        ]
    )
    for entry in entries:
        action = entry.get("proposed_action") or {}
        writer.writerow(
            [
                entry.get("torrent_hash", ""),
                entry.get("state", ""),
                entry.get("root_cause", ""),
                "1" if entry.get("save_exists") else "0",
                "1" if entry.get("content_exists") else "0",
                entry.get("db_payload_hash") or "",
                entry.get("db_status") or "",
                entry.get("save_path") or "",
                entry.get("content_path") or "",
                action.get("action", ""),
                action.get("target_save_path", ""),
            ]
        )

print(f"summary missing_total={summary['missing_total']} actionable_total={summary['actionable_total']} with_rehome_tag={summary['with_rehome_tag']} without_payload_hash={summary['without_payload_hash']}")
for key, value in sorted(class_counter.items(), key=lambda item: (-item[1], item[0])):
    print(f"class_count root_cause={key} total={value}")
print(f"audit_json={audit_json_out}")
print(f"audit_tsv={audit_tsv_out}")
print(f"plan_json={plan_json_out}")
PY

hr
echo "Phase 56 complete: missing-files audit and remediation plan generated."
hr
echo "run_log=${run_log}"
echo "audit_json=${audit_json}"
echo "audit_tsv=${audit_tsv}"
echo "plan_json=${plan_json}"
