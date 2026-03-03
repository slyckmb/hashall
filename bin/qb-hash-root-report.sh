#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/qb-hash-root-report.sh [options]

What this does:
  Build per-hash and per-root ownership reports from Phase 100/101 data,
  including tracker/category hints, candidate roots, and active owner hashes.

Options:
  --mapping-json PATH      Phase 101 mapping JSON (default: latest)
  --baseline-json PATH     Phase 100 baseline JSON (default: latest)
  --db PATH                Catalog DB path (default: ~/.hashall/catalog.db)
  --output-prefix NAME     Output prefix (default: nohl)
  --limit N                Limit hashes processed (default: 0 = all)
  --candidate-top-n N      Max candidates per hash in reports (default: 25)
  --include-db-discovery   Add DB-discovered sibling roots by root-name (default: on)
  --no-db-discovery        Disable DB-discovered sibling roots
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
CANDIDATE_TOP_N="${CANDIDATE_TOP_N:-25}"
INCLUDE_DB_DISCOVERY="${INCLUDE_DB_DISCOVERY:-1}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --candidate-top-n) CANDIDATE_TOP_N="${2:-}"; shift 2 ;;
    --include-db-discovery) INCLUDE_DB_DISCOVERY=1; shift ;;
    --no-db-discovery) INCLUDE_DB_DISCOVERY=0; shift ;;
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
  echo "Missing mapping JSON (from archived nohl-basics pipeline, no longer generated)." >&2
  exit 3
fi
if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing baseline JSON (from archived nohl-basics pipeline, no longer generated)." >&2
  exit 3
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi
if ! [[ "$CANDIDATE_TOP_N" =~ ^[0-9]+$ ]] || [[ "$CANDIDATE_TOP_N" -lt 1 ]]; then
  echo "Invalid --candidate-top-n: $CANDIDATE_TOP_N" >&2
  exit 2
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-hash-root-report-${stamp}.log"
hash_json_out="${log_dir}/${OUTPUT_PREFIX}-qb-hash-root-report-${stamp}.json"
root_json_out="${log_dir}/${OUTPUT_PREFIX}-qb-root-ownership-report-${stamp}.json"
hash_ndjson_out="${log_dir}/${OUTPUT_PREFIX}-qb-hash-root-report-${stamp}.ndjson"
hash_tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-hash-root-report-${stamp}.tsv"
root_tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-root-ownership-report-${stamp}.tsv"
summary_md_out="${log_dir}/${OUTPUT_PREFIX}-qb-hash-root-report-${stamp}.md"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 106: qB hash/root report"
echo "What this does: emit per-hash candidate roots and per-root ownership/conflict reports."
hr
echo "run_id=${stamp} step=basics-qb-hash-root-report mapping_json=${MAPPING_JSON} baseline_json=${BASELINE_JSON} db=${DB_PATH} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} candidate_top_n=${CANDIDATE_TOP_N} include_db_discovery=${INCLUDE_DB_DISCOVERY} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
REPORT_MAPPING_JSON="$MAPPING_JSON" \
REPORT_BASELINE_JSON="$BASELINE_JSON" \
REPORT_DB_PATH="$DB_PATH" \
REPORT_LIMIT="$LIMIT" \
REPORT_CANDIDATE_TOP_N="$CANDIDATE_TOP_N" \
REPORT_INCLUDE_DB_DISCOVERY="$INCLUDE_DB_DISCOVERY" \
REPORT_HASH_JSON_OUT="$hash_json_out" \
REPORT_ROOT_JSON_OUT="$root_json_out" \
REPORT_HASH_NDJSON_OUT="$hash_ndjson_out" \
REPORT_HASH_TSV_OUT="$hash_tsv_out" \
REPORT_ROOT_TSV_OUT="$root_tsv_out" \
REPORT_SUMMARY_MD_OUT="$summary_md_out" \
python - <<'PY'
import csv
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

mapping_json = Path(os.environ["REPORT_MAPPING_JSON"])
baseline_json = Path(os.environ["REPORT_BASELINE_JSON"])
db_path = Path(os.environ["REPORT_DB_PATH"])
limit = int(os.environ.get("REPORT_LIMIT", "0") or 0)
candidate_top_n = max(1, int(os.environ.get("REPORT_CANDIDATE_TOP_N", "25") or 25))
include_db_discovery = os.environ.get("REPORT_INCLUDE_DB_DISCOVERY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
hash_json_out = Path(os.environ["REPORT_HASH_JSON_OUT"])
root_json_out = Path(os.environ["REPORT_ROOT_JSON_OUT"])
hash_ndjson_out = Path(os.environ["REPORT_HASH_NDJSON_OUT"])
hash_tsv_out = Path(os.environ["REPORT_HASH_TSV_OUT"])
root_tsv_out = Path(os.environ["REPORT_ROOT_TSV_OUT"])
summary_md_out = Path(os.environ["REPORT_SUMMARY_MD_OUT"])

mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
baseline = json.loads(baseline_json.read_text(encoding="utf-8"))

entries = [row for row in mapping.get("entries", []) if str(row.get("hash", "")).strip()]
if limit > 0:
    entries = entries[:limit]

baseline_entries = [row for row in baseline.get("entries", []) if str(row.get("hash", "")).strip()]
baseline_by_hash = {
    str(row.get("hash", "")).lower(): row
    for row in baseline_entries
}


def clean_name(raw: str) -> str:
    val = str(raw or "").strip()
    if not val:
        return ""
    if "/" in val or val in {".", ".."}:
        return ""
    return val


def normalize_tracker_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("(api)", " ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def split_tags(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part and part.strip()]


def tracker_component_from_path(path: str) -> str:
    parts = list(Path(str(path or "").strip()).parts)
    for idx, part in enumerate(parts):
        if str(part).lower() in {"cross-seed", "cross_seed", "crossseed"} and idx + 1 < len(parts):
            return str(parts[idx + 1]).strip()
    return ""


def contains_path(root: str, target: str) -> bool:
    r = str(Path(root))
    t = str(Path(target))
    return t == r or t.startswith(r + "/")


def normalize_candidates(entry: dict, top_n: int) -> list[dict]:
    out = []
    seen = set()
    raw = entry.get("candidates", [])
    if isinstance(raw, list):
        for cand in raw:
            if not isinstance(cand, dict):
                continue
            path = str(cand.get("path", "")).strip()
            if not path.startswith("/"):
                continue
            norm_path = str(Path(path))
            if norm_path in seen:
                continue
            seen.add(norm_path)
            out.append(
                {
                    "path": norm_path,
                    "payload_root": str(cand.get("payload_root", "") or "").strip(),
                    "score": int(cand.get("score", 0) or 0),
                    "rank": int(cand.get("rank", len(out) + 1) or len(out) + 1),
                    "reason": str(cand.get("reason", "") or ""),
                    "score_breakdown": dict(cand.get("score_breakdown", {}) or {}),
                    "manifest_match_count": int(cand.get("manifest_match_count", 0) or 0),
                    "manifest_size_match_count": int(cand.get("manifest_size_match_count", 0) or 0),
                    "tracker_match": int(cand.get("tracker_match", 0) or 0),
                    "evidence": list(cand.get("evidence", []) or []),
                    "expected_matches": list(cand.get("expected_matches", []) or []),
                    "sources": ["phase101_mapping"],
                }
            )
    best = str(entry.get("best_candidate", "") or "").strip()
    if best.startswith("/"):
        best_path = str(Path(best))
        if best_path not in seen:
            out.insert(
                0,
                {
                    "path": best_path,
                    "payload_root": str(entry.get("best_payload_root", "") or "").strip(),
                    "score": int(entry.get("best_score", 0) or 0),
                    "rank": 1,
                    "reason": str(entry.get("best_reason", "") or ""),
                    "score_breakdown": dict(entry.get("best_score_breakdown", {}) or {}),
                    "manifest_match_count": int(entry.get("best_manifest_match_count", 0) or 0),
                    "manifest_size_match_count": int(entry.get("best_manifest_size_match_count", 0) or 0),
                    "tracker_match": int(entry.get("best_tracker_match", 0) or 0),
                    "evidence": list(entry.get("best_evidence", []) or []),
                    "expected_matches": list(entry.get("best_expected_matches", []) or []),
                    "sources": ["phase101_best_candidate"],
                },
            )
    for idx, cand in enumerate(out, start=1):
        cand["rank"] = idx
    return out[:top_n]


def root_hint_for(entry: dict, baseline_row: dict) -> str:
    hint = clean_name(entry.get("root_name_hint", ""))
    if hint:
        return hint
    cp = str(entry.get("content_path", "") or baseline_row.get("content_path", "") or "").strip()
    if cp:
        return clean_name(Path(cp).name)
    name = clean_name(entry.get("name", "") or baseline_row.get("name", ""))
    if name:
        return name
    return ""


root_names_needed = set()
for entry in entries:
    h = str(entry.get("hash", "")).lower()
    b = baseline_by_hash.get(h, {})
    root_hint = root_hint_for(entry, b)
    if root_hint:
        root_names_needed.add(root_hint)
    for item in list(entry.get("expected_names", []) or []):
        name = clean_name(item)
        if name:
            root_names_needed.add(name)


peer_rows_by_root_name: dict[str, list[dict]] = defaultdict(list)
payload_rows_by_root_name: dict[str, list[dict]] = defaultdict(list)
db_owner_by_save_path: dict[str, set[str]] = defaultdict(set)
db_owner_by_payload_parent: dict[str, set[str]] = defaultdict(set)

if include_db_discovery and db_path.exists():
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if root_names_needed:
        qmarks = ",".join("?" for _ in sorted(root_names_needed))
        rows = conn.execute(
            f"""
            SELECT
                lower(ti.torrent_hash) AS torrent_hash,
                ti.save_path AS save_path,
                ti.root_name AS root_name,
                p.root_path AS payload_root_path,
                p.status AS payload_status
            FROM torrent_instances ti
            LEFT JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE ti.root_name IN ({qmarks})
            """,
            sorted(root_names_needed),
        ).fetchall()
        for row in rows:
            root_name = clean_name(row["root_name"] or "")
            if not root_name:
                continue
            item = {
                "torrent_hash": str(row["torrent_hash"] or "").lower(),
                "save_path": str(row["save_path"] or "").strip(),
                "payload_root_path": str(row["payload_root_path"] or "").strip(),
                "payload_status": str(row["payload_status"] or "").strip().lower() or "unknown",
            }
            peer_rows_by_root_name[root_name].append(item)
            if item["save_path"].startswith("/") and item["torrent_hash"]:
                db_owner_by_save_path[str(Path(item["save_path"]))].add(item["torrent_hash"])
            if item["payload_root_path"].startswith("/") and item["torrent_hash"]:
                db_owner_by_payload_parent[str(Path(item["payload_root_path"]).parent)].add(item["torrent_hash"])

        payload_rows = conn.execute(
            """
            SELECT root_path, status, payload_hash
            FROM payloads
            WHERE root_path IS NOT NULL AND root_path != ''
            """
        ).fetchall()
        for row in payload_rows:
            root_path = str(row["root_path"] or "").strip()
            if not root_path.startswith("/"):
                continue
            root_name = clean_name(Path(root_path).name)
            if root_name not in root_names_needed:
                continue
            payload_rows_by_root_name[root_name].append(
                {
                    "root_path": str(Path(root_path)),
                    "status": str(row["status"] or "").strip().lower() or "unknown",
                    "payload_hash": str(row["payload_hash"] or "").strip(),
                }
            )
    conn.close()


qb_owner_cache: dict[str, list[str]] = {}


def qb_owner_hashes_for_root(root_path: str) -> list[str]:
    root = str(Path(root_path))
    cached = qb_owner_cache.get(root)
    if cached is not None:
        return cached
    owners = set()
    for row in baseline_entries:
        h = str(row.get("hash", "")).lower().strip()
        if not h:
            continue
        save_path = str(row.get("save_path", "") or "").strip()
        content_path = str(row.get("content_path", "") or "").strip()
        if save_path and str(Path(save_path)) == root:
            owners.add(h)
            continue
        if content_path and contains_path(root, content_path):
            owners.add(h)
    out = sorted(owners)
    qb_owner_cache[root] = out
    return out


hash_rows = []
root_rows: dict[str, dict] = {}

for entry in entries:
    torrent_hash = str(entry.get("hash", "")).lower().strip()
    if not torrent_hash:
        continue
    baseline_row = baseline_by_hash.get(torrent_hash, {})

    state = str(entry.get("state", "") or baseline_row.get("state", "") or "")
    progress = float(entry.get("progress", baseline_row.get("progress", 0.0)) or 0.0)
    amount_left = int(entry.get("amount_left", baseline_row.get("amount_left", 0)) or 0)
    qb_save_path = str(entry.get("save_path", "") or baseline_row.get("save_path", "") or "").strip()
    qb_content_path = str(entry.get("content_path", "") or baseline_row.get("content_path", "") or "").strip()
    category = str(entry.get("category", "") or baseline_row.get("category", "") or "").strip()
    tracker_name = str(entry.get("tracker_name", "") or baseline_row.get("tracker_name", "") or "").strip()
    tracker_key = normalize_tracker_key(entry.get("tracker_key", "") or baseline_row.get("tracker_key", ""))
    if not tracker_key and tracker_name:
        tracker_key = normalize_tracker_key(tracker_name)
    if not tracker_key:
        tracker_key = normalize_tracker_key(tracker_component_from_path(qb_save_path or qb_content_path))
    if not tracker_key:
        for tag in split_tags(entry.get("tags", "") or baseline_row.get("tags", "")):
            norm = normalize_tracker_key(tag)
            if norm and norm not in {
                "crossseed",
                "rehome",
                "rehomeverifypending",
                "rehomeverifyok",
                "rehomeverifyfailed",
            }:
                tracker_key = norm
                break

    root_name_hint = root_hint_for(entry, baseline_row)
    manifest_file_count = int(entry.get("manifest_file_count", 0) or 0)
    manifest_total_bytes = int(entry.get("manifest_total_bytes", 0) or 0)
    manifest_sample_count = int(entry.get("manifest_sample_count", 0) or 0)

    candidates_by_path: dict[str, dict] = {}

    def add_candidate(candidate: dict) -> None:
        path = str(candidate.get("path", "") or "").strip()
        if not path.startswith("/"):
            return
        path = str(Path(path))
        existing = candidates_by_path.get(path)
        payload_root = str(candidate.get("payload_root", "") or "").strip()
        source = str(candidate.get("source", "") or "").strip() or "unknown"
        reason = str(candidate.get("reason", "") or "").strip()
        rank = int(candidate.get("rank", 0) or 0)
        score = int(candidate.get("score", 0) or 0)
        score_breakdown = dict(candidate.get("score_breakdown", {}) or {})
        if existing is None:
            candidates_by_path[path] = {
                "path": path,
                "payload_root": payload_root,
                "rank": rank if rank > 0 else 999999,
                "score": score,
                "reason": reason,
                "score_breakdown": score_breakdown,
                "manifest_match_count": int(candidate.get("manifest_match_count", 0) or 0),
                "manifest_size_match_count": int(candidate.get("manifest_size_match_count", 0) or 0),
                "tracker_match": int(candidate.get("tracker_match", 0) or 0),
                "sources": [source],
                "evidence": list(candidate.get("evidence", []) or []),
                "expected_matches": list(candidate.get("expected_matches", []) or []),
            }
            return
        existing["score"] = max(int(existing.get("score", 0) or 0), score)
        existing["rank"] = min(int(existing.get("rank", 999999) or 999999), rank if rank > 0 else 999999)
        if payload_root and not str(existing.get("payload_root", "") or "").startswith("/"):
            existing["payload_root"] = payload_root
        if source and source not in existing["sources"]:
            existing["sources"].append(source)
        if reason and reason not in [p.strip() for p in str(existing.get("reason", "") or "").split(",") if p.strip()]:
            if existing["reason"]:
                existing["reason"] = f"{existing['reason']},{reason}"
            else:
                existing["reason"] = reason
        existing["manifest_match_count"] = max(
            int(existing.get("manifest_match_count", 0) or 0),
            int(candidate.get("manifest_match_count", 0) or 0),
        )
        existing["manifest_size_match_count"] = max(
            int(existing.get("manifest_size_match_count", 0) or 0),
            int(candidate.get("manifest_size_match_count", 0) or 0),
        )
        existing["tracker_match"] = max(
            int(existing.get("tracker_match", 0) or 0),
            int(candidate.get("tracker_match", 0) or 0),
        )
        for ev in list(candidate.get("evidence", []) or []):
            if ev not in existing["evidence"]:
                existing["evidence"].append(ev)
        for m in list(candidate.get("expected_matches", []) or []):
            if m not in existing["expected_matches"]:
                existing["expected_matches"].append(m)
        for k, v in score_breakdown.items():
            if k not in existing["score_breakdown"]:
                existing["score_breakdown"][k] = v

    for cand in normalize_candidates(entry, candidate_top_n):
        add_candidate({
            **cand,
            "source": "phase101_mapping",
        })

    if include_db_discovery:
        root_names = []
        if root_name_hint:
            root_names.append(root_name_hint)
        for x in list(entry.get("expected_names", []) or []):
            name = clean_name(x)
            if name and name not in root_names:
                root_names.append(name)

        for name in root_names:
            for peer in peer_rows_by_root_name.get(name, []):
                save_path = str(peer.get("save_path", "") or "").strip()
                if save_path.startswith("/"):
                    add_candidate(
                        {
                            "path": save_path,
                            "payload_root": "",
                            "score": 92,
                            "rank": 9000,
                            "reason": f"db_peer_save:{name}",
                            "source": "db_peer_save_path",
                            "evidence": [f"db_peer_hash:{str(peer.get('torrent_hash', ''))[:12]}"],
                            "expected_matches": [name],
                        }
                    )
                payload_root = str(peer.get("payload_root_path", "") or "").strip()
                if payload_root.startswith("/"):
                    add_candidate(
                        {
                            "path": str(Path(payload_root).parent),
                            "payload_root": payload_root,
                            "score": 110 if str(peer.get("payload_status", "")).lower() == "complete" else 98,
                            "rank": 9000,
                            "reason": f"db_peer_payload_parent:{name}",
                            "source": "db_peer_payload_parent",
                            "evidence": [f"db_peer_hash:{str(peer.get('torrent_hash', ''))[:12]}"],
                            "expected_matches": [name],
                        }
                    )
            for payload_row in payload_rows_by_root_name.get(name, []):
                payload_root = str(payload_row.get("root_path", "") or "").strip()
                if not payload_root.startswith("/"):
                    continue
                add_candidate(
                    {
                        "path": str(Path(payload_root).parent),
                        "payload_root": payload_root,
                        "score": 114 if str(payload_row.get("status", "")).lower() == "complete" else 100,
                        "rank": 9000,
                        "reason": f"db_payload_root_parent:{name}",
                        "source": "db_payload_root_parent",
                        "evidence": [f"db_payload_hash:{str(payload_row.get('payload_hash', ''))[:16]}"],
                        "expected_matches": [name],
                    }
                )

    candidates = sorted(
        candidates_by_path.values(),
        key=lambda row: (-int(row.get("score", 0) or 0), int(row.get("rank", 999999) or 999999), str(row.get("path", ""))),
    )[:candidate_top_n]

    for idx, cand in enumerate(candidates, start=1):
        cand["rank"] = idx
        path = str(cand.get("path", "") or "")
        path_exists = Path(path).exists()
        cand["path_exists"] = bool(path_exists)
        qb_owners = set(qb_owner_hashes_for_root(path))
        db_owners = set(db_owner_by_save_path.get(path, set())) | set(db_owner_by_payload_parent.get(path, set()))
        owners = sorted(qb_owners | db_owners)
        owner_conflicts = sorted([h for h in owners if h != torrent_hash])
        tracker_component = normalize_tracker_key(tracker_component_from_path(path))
        tracker_match_state = "none"
        if tracker_component and tracker_key and tracker_component == tracker_key:
            tracker_match_state = "exact"
        elif tracker_component and tracker_key and tracker_component != tracker_key:
            tracker_match_state = "mismatch"
        elif tracker_component:
            tracker_match_state = "partial"

        cand["owner_hashes_qb"] = sorted(qb_owners)
        cand["owner_hashes_db"] = sorted(db_owners)
        cand["owner_hashes"] = owners
        cand["owner_conflicts"] = owner_conflicts
        cand["tracker_component"] = tracker_component
        cand["tracker_path_match"] = tracker_match_state
        cand["route_eligible"] = bool(path_exists and not owner_conflicts)

        root = root_rows.setdefault(
            path,
            {
                "root_path": path,
                "candidate_hashes": set(),
                "tracker_keys": set(),
                "categories": set(),
                "owner_hashes_qb": set(),
                "owner_hashes_db": set(),
                "owner_hashes": set(),
                "sample_payload_roots": set(),
                "sample_reasons": set(),
            },
        )
        root["candidate_hashes"].add(torrent_hash)
        if tracker_key:
            root["tracker_keys"].add(tracker_key)
        if category:
            root["categories"].add(category)
        root["owner_hashes_qb"].update(qb_owners)
        root["owner_hashes_db"].update(db_owners)
        root["owner_hashes"].update(owners)
        payload_root = str(cand.get("payload_root", "") or "").strip()
        if payload_root:
            root["sample_payload_roots"].add(payload_root)
        for reason in [r.strip() for r in str(cand.get("reason", "") or "").split(",") if r.strip()]:
            root["sample_reasons"].add(reason)

    hash_rows.append(
        {
            "hash": torrent_hash,
            "name": str(entry.get("name", "") or baseline_row.get("name", "")),
            "state": state,
            "progress": progress,
            "amount_left": amount_left,
            "tracker_key": tracker_key,
            "tracker_name": tracker_name,
            "category": category,
            "tags": str(entry.get("tags", "") or baseline_row.get("tags", "")),
            "qb_save_path": qb_save_path,
            "qb_content_path": qb_content_path,
            "root_name_hint": root_name_hint,
            "manifest_file_count": manifest_file_count,
            "manifest_total_bytes": manifest_total_bytes,
            "manifest_sample_count": manifest_sample_count,
            "candidate_count": len(candidates),
            "routeable_candidate_count": sum(1 for c in candidates if bool(c.get("route_eligible"))),
            "confidence": str(entry.get("confidence", "")),
            "decision": str(entry.get("decision", "")),
            "candidates": candidates,
        }
    )

serialized_roots = []
for path, row in sorted(root_rows.items()):
    candidate_hashes = sorted(row["candidate_hashes"])
    owner_hashes = sorted(row["owner_hashes"])
    owner_conflicts = sorted([h for h in owner_hashes if h not in row["candidate_hashes"]])
    conflict_types = []
    if len(candidate_hashes) > 1:
        conflict_types.append("shared_candidate_root")
    if len(owner_hashes) > 1:
        conflict_types.append("shared_live_owner")
    if owner_conflicts:
        conflict_types.append("owner_mismatch")
    if candidate_hashes and owner_hashes and set(candidate_hashes).isdisjoint(set(owner_hashes)):
        conflict_types.append("candidate_owner_disjoint")
    serialized_roots.append(
        {
            "root_path": path,
            "candidate_hashes": candidate_hashes,
            "tracker_keys": sorted(row["tracker_keys"]),
            "categories": sorted(row["categories"]),
            "owner_hashes_qb": sorted(row["owner_hashes_qb"]),
            "owner_hashes_db": sorted(row["owner_hashes_db"]),
            "owner_hashes": owner_hashes,
            "owner_conflicts": owner_conflicts,
            "sample_payload_roots": sorted(row["sample_payload_roots"]),
            "sample_reasons": sorted(row["sample_reasons"]),
            "conflict_types": conflict_types,
        }
    )

summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "hashes": len(hash_rows),
    "roots": len(serialized_roots),
    "hashes_with_no_candidates": sum(1 for row in hash_rows if int(row.get("candidate_count", 0) or 0) == 0),
    "hashes_with_routeable_candidates": sum(1 for row in hash_rows if int(row.get("routeable_candidate_count", 0) or 0) > 0),
    "roots_with_conflicts": sum(1 for row in serialized_roots if row.get("conflict_types")),
    "roots_with_shared_candidates": sum(
        1 for row in serialized_roots if "shared_candidate_root" in set(row.get("conflict_types", []))
    ),
    "roots_with_owner_mismatch": sum(
        1 for row in serialized_roots if "owner_mismatch" in set(row.get("conflict_types", []))
    ),
    "input_mapping_entries": len(entries),
    "include_db_discovery": bool(include_db_discovery),
    "candidate_top_n": int(candidate_top_n),
}

payload = {
    "summary": summary,
    "hashes": hash_rows,
    "roots": serialized_roots,
}

hash_json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
root_json_out.write_text(json.dumps({"summary": summary, "roots": serialized_roots}, indent=2) + "\n", encoding="utf-8")

with hash_ndjson_out.open("w", encoding="utf-8") as fh:
    for row in hash_rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

hash_tsv_fields = [
    "hash",
    "state",
    "tracker_key",
    "category",
    "qb_save_path",
    "qb_content_path",
    "root_name_hint",
    "candidate_count",
    "routeable_candidate_count",
    "best_candidate_path",
    "best_candidate_score",
    "best_candidate_owner_hashes",
]
with hash_tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=hash_tsv_fields, delimiter="\t")
    writer.writeheader()
    for row in hash_rows:
        best = row.get("candidates", [None])[0] if row.get("candidates") else None
        writer.writerow(
            {
                "hash": row.get("hash", ""),
                "state": row.get("state", ""),
                "tracker_key": row.get("tracker_key", ""),
                "category": row.get("category", ""),
                "qb_save_path": row.get("qb_save_path", ""),
                "qb_content_path": row.get("qb_content_path", ""),
                "root_name_hint": row.get("root_name_hint", ""),
                "candidate_count": row.get("candidate_count", 0),
                "routeable_candidate_count": row.get("routeable_candidate_count", 0),
                "best_candidate_path": (best or {}).get("path", "") if isinstance(best, dict) else "",
                "best_candidate_score": (best or {}).get("score", 0) if isinstance(best, dict) else 0,
                "best_candidate_owner_hashes": ",".join((best or {}).get("owner_hashes", []) or []) if isinstance(best, dict) else "",
            }
        )

root_tsv_fields = [
    "root_path",
    "candidate_hashes",
    "owner_hashes_qb",
    "owner_hashes_db",
    "owner_hashes",
    "owner_conflicts",
    "conflict_types",
    "tracker_keys",
]
with root_tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=root_tsv_fields, delimiter="\t")
    writer.writeheader()
    for row in serialized_roots:
        writer.writerow(
            {
                "root_path": row.get("root_path", ""),
                "candidate_hashes": ",".join(row.get("candidate_hashes", []) or []),
                "owner_hashes_qb": ",".join(row.get("owner_hashes_qb", []) or []),
                "owner_hashes_db": ",".join(row.get("owner_hashes_db", []) or []),
                "owner_hashes": ",".join(row.get("owner_hashes", []) or []),
                "owner_conflicts": ",".join(row.get("owner_conflicts", []) or []),
                "conflict_types": ",".join(row.get("conflict_types", []) or []),
                "tracker_keys": ",".join(row.get("tracker_keys", []) or []),
            }
        )

md_lines = [
    "# Phase 106 Hash/Root Report",
    "",
    f"Generated: {summary['generated_at']}",
    "",
    "## Summary",
    f"- Hashes: {summary['hashes']}",
    f"- Roots: {summary['roots']}",
    f"- Hashes with routeable candidates: {summary['hashes_with_routeable_candidates']}",
    f"- Hashes with no candidates: {summary['hashes_with_no_candidates']}",
    f"- Roots with conflicts: {summary['roots_with_conflicts']}",
    f"- Roots with owner mismatch: {summary['roots_with_owner_mismatch']}",
    "",
    "## Top Conflict Roots",
]
conflict_roots = [row for row in serialized_roots if row.get("conflict_types")]
for row in conflict_roots[:20]:
    md_lines.append(
        f"- `{row['root_path']}` candidates={len(row.get('candidate_hashes', []))} owners={len(row.get('owner_hashes', []))} conflicts={','.join(row.get('conflict_types', []))}"
    )
if not conflict_roots:
    md_lines.append("- none")
md_lines.append("")
summary_md_out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

print(
    "summary "
    f"hashes={summary['hashes']} "
    f"roots={summary['roots']} "
    f"routeable_hashes={summary['hashes_with_routeable_candidates']} "
    f"roots_with_conflicts={summary['roots_with_conflicts']}"
)
print(f"json_output={hash_json_out}")
print(f"root_json_output={root_json_out}")
print(f"hash_ndjson_output={hash_ndjson_out}")
print(f"hash_tsv_output={hash_tsv_out}")
print(f"root_tsv_output={root_tsv_out}")
print(f"summary_md_output={summary_md_out}")
PY

hr
echo "result=ok step=basics-qb-hash-root-report run_log=${run_log}"
echo "json_output=${hash_json_out}"
echo "root_json_output=${root_json_out}"
echo "hash_ndjson_output=${hash_ndjson_out}"
echo "hash_tsv_output=${hash_tsv_out}"
echo "root_tsv_output=${root_tsv_out}"
echo "summary_md_output=${summary_md_out}"
hr
