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
unresolved_out="${log_dir}/${OUTPUT_PREFIX}-qb-candidate-unresolved-hashes-${stamp}.txt"

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
MAP_UNRESOLVED_OUT="$unresolved_out" \
python - <<'PY'
import csv
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

baseline_json = Path(os.environ["MAP_BASELINE_JSON"])
db_path = Path(os.environ["MAP_DB_PATH"])
limit = int(os.environ.get("MAP_LIMIT", "0") or 0)
json_out = Path(os.environ["MAP_JSON_OUT"])
tsv_out = Path(os.environ["MAP_TSV_OUT"])
confident_out = Path(os.environ["MAP_CONFIDENT_OUT"])
manual_out = Path(os.environ["MAP_MANUAL_OUT"])
unresolved_out = Path(os.environ["MAP_UNRESOLVED_OUT"])
allowed_roots_raw = os.environ.get(
    "MAP_ALLOWED_ROOTS",
    "/data/media/torrents/seeding,/pool/data,/mnt/hotspare6tb",
)
enable_discovery_scan = os.environ.get("MAP_ENABLE_DISCOVERY_SCAN", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
allowed_roots = []
for raw_root in allowed_roots_raw.split(","):
    root = str(Path(raw_root.strip() or "."))
    if not root or root == "." or not root.startswith("/"):
        continue
    if root in [str(x) for x in allowed_roots]:
        continue
    allowed_roots.append(Path(root))
if not allowed_roots:
    raise SystemExit("No valid allowed roots; set MAP_ALLOWED_ROOTS with absolute paths.")
allowed_root_strs = [str(p) for p in allowed_roots]

obj = json.loads(baseline_json.read_text(encoding="utf-8"))
entries = list(obj.get("entries", []))
if limit > 0:
    entries = entries[:limit]

db_rows = {}
db_conn = None
peer_rows_by_root_name = defaultdict(list)
payload_roots_by_root_name = defaultdict(list)
device_mount_by_id = {}
files_tables = []
catalog_hits_cache = {}
if db_path.exists():
    db_conn = sqlite3.connect(str(db_path))
    db_conn.row_factory = sqlite3.Row
    hashes = sorted(
        {
            str(e.get("hash", "")).lower()
            for e in entries
            if str(e.get("hash", "")).strip()
        }
    )
    if hashes:
        qmarks = ",".join("?" for _ in hashes)
        rows = db_conn.execute(
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


def is_under_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def is_allowed_path(path: str) -> bool:
    norm = str(Path(path))
    return any(is_under_root(norm, root) for root in allowed_root_strs)


def clean_name(raw: str) -> str:
    val = str(raw or "").strip()
    if not val:
        return ""
    if "/" in val or val in {".", ".."}:
        return ""
    return val


def expected_names_for(entry: dict, db_entry: dict) -> list[str]:
    names: list[str] = []

    def add(raw: str):
        name = clean_name(raw)
        if name and name not in names:
            names.append(name)

    add(db_entry.get("db_root_name", ""))
    cp = str(entry.get("content_path", "")).strip()
    if cp:
        add(Path(cp).name)
    add(entry.get("name", ""))
    db_root_path = str(db_entry.get("db_root_path", "")).strip()
    if db_root_path:
        add(Path(db_root_path).name)
    return names


expected_names_by_hash = {}
needed_names = set()
for e in entries:
    h = str(e.get("hash", "")).lower()
    db = db_rows.get(h, {})
    names = expected_names_for(e, db)
    expected_names_by_hash[h] = names
    needed_names.update(names)


def _parse_device_id(table_name: str) -> int | None:
    if not table_name.startswith("files_"):
        return None
    part = table_name.split("_", 1)[1]
    if not part.isdigit():
        return None
    return int(part)


def to_catalog_abs_path(table_name: str, raw_path: str) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return ""
    if path.startswith("/"):
        return str(Path(path))
    device_id = _parse_device_id(table_name)
    if device_id is None:
        return ""
    mount_point = str(device_mount_by_id.get(device_id) or "").strip()
    if not mount_point or not mount_point.startswith("/"):
        return ""
    return str(Path(mount_point) / path)


if db_conn is not None:
    for row in db_conn.execute(
        """
        SELECT device_id, preferred_mount_point, mount_point
        FROM devices
        """
    ).fetchall():
        did = int(row["device_id"])
        mount = str(row["preferred_mount_point"] or row["mount_point"] or "").strip()
        if mount and mount.startswith("/"):
            device_mount_by_id[did] = mount

    for row in db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'files_%' ORDER BY name"
    ).fetchall():
        table_name = str(row["name"] or "").strip()
        if _parse_device_id(table_name) is None:
            continue
        files_tables.append(table_name)

    needed_list = sorted(n for n in needed_names if n)
    if needed_list:
        qmarks = ",".join("?" for _ in needed_list)
        peer_rows = db_conn.execute(
            f"""
            SELECT
                ti.root_name AS root_name,
                lower(ti.torrent_hash) AS torrent_hash,
                ti.save_path AS save_path,
                p.root_path AS payload_root_path,
                p.status AS payload_status
            FROM torrent_instances ti
            LEFT JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE ti.root_name IN ({qmarks})
            """,
            needed_list,
        ).fetchall()
        for row in peer_rows:
            root_name = clean_name(row["root_name"] or "")
            if not root_name:
                continue
            peer_rows_by_root_name[root_name].append(
                {
                    "torrent_hash": str(row["torrent_hash"] or "").lower(),
                    "save_path": str(row["save_path"] or ""),
                    "payload_root_path": str(row["payload_root_path"] or ""),
                    "payload_status": str(row["payload_status"] or ""),
                }
            )

        payload_rows = db_conn.execute(
            """
            SELECT root_path, status, total_bytes, payload_hash
            FROM payloads
            WHERE root_path IS NOT NULL AND root_path != ''
            """
        ).fetchall()
        needed_name_set = set(needed_list)
        for row in payload_rows:
            root_path = str(row["root_path"] or "").strip()
            if not root_path:
                continue
            root_name = clean_name(Path(root_path).name)
            if root_name not in needed_name_set:
                continue
            payload_roots_by_root_name[root_name].append(
                {
                    "root_path": root_path,
                    "status": str(row["status"] or "").strip().lower() or "unknown",
                    "total_bytes": int(row["total_bytes"] or 0),
                    "payload_hash": str(row["payload_hash"] or "").strip(),
                }
            )


def catalog_hits_for_name(name: str) -> list[dict]:
    target = clean_name(name)
    if not target:
        return []
    cached = catalog_hits_cache.get(target)
    if cached is not None:
        return cached
    hits = []
    if db_conn is None or not files_tables:
        catalog_hits_cache[target] = hits
        return hits

    seen = set()
    for table_name in files_tables:
        for pattern, match_mode, base_score in [
            (f"%/{target}", "exact_file", 130),
            (f"%/{target}/%", "root_dir", 118),
        ]:
            rows = db_conn.execute(
                f"""
                SELECT path, status
                FROM {table_name}
                WHERE path LIKE ?
                LIMIT 256
                """,
                (pattern,),
            ).fetchall()
            for row in rows:
                abs_path = to_catalog_abs_path(table_name, row["path"] or "")
                if not abs_path:
                    continue
                status = str(row["status"] or "").strip().lower() or "unknown"
                candidate_path = ""
                if match_mode == "exact_file":
                    candidate_path = str(Path(abs_path).parent)
                else:
                    token = f"/{target}/"
                    idx = abs_path.find(token)
                    if idx > 0:
                        candidate_path = abs_path[:idx]
                if not candidate_path or not candidate_path.startswith("/"):
                    continue
                key = (candidate_path, status, match_mode)
                if key in seen:
                    continue
                seen.add(key)
                score = base_score if status == "active" else (base_score - 20)
                hits.append(
                    {
                        "path": candidate_path,
                        "score": score,
                        "match_mode": match_mode,
                        "status": status,
                        "table": table_name,
                    }
                )
    catalog_hits_cache[target] = hits
    return hits

discovered_roots = defaultdict(list)
if enable_discovery_scan:
    print(
        f"discovery_scan_start needed_names={len(needed_names)} "
        f"allowed_roots={','.join(allowed_root_strs)}"
    )
    if needed_names:
        for root in allowed_roots:
            if not root.exists():
                print(f"discovery_root path={root} exists=0 hits=0")
                continue
            hits = 0
            for dirpath, dirnames, filenames in os.walk(root):
                for d in dirnames:
                    if d in needed_names:
                        discovered_roots[d].append(str(Path(dirpath) / d))
                        hits += 1
                for f in filenames:
                    if f in needed_names:
                        discovered_roots[f].append(str(Path(dirpath) / f))
                        hits += 1
            print(f"discovery_root path={root} exists=1 hits={hits}")
        discovered_name_count = sum(1 for n in needed_names if discovered_roots.get(n))
    else:
        discovered_name_count = 0
    print(f"discovery_scan_done matched_names={discovered_name_count}")
else:
    discovered_name_count = 0
    print(
        f"discovery_scan_skipped policy=db_first enable_discovery_scan={int(enable_discovery_scan)} "
        f"allowed_roots={','.join(allowed_root_strs)}"
    )


mapped = []
confident_hashes = []
unresolved_hashes = []
for e in entries:
    torrent_hash = str(e.get("hash", "")).lower()
    save_path = str(e.get("save_path", "")).strip()
    content_path = str(e.get("content_path", "")).strip()
    state = str(e.get("state", "")).strip()
    state_l = state.lower()
    progress = float(e.get("progress", 0.0) or 0.0)
    amount_left = int(e.get("amount_left", 0) or 0)
    is_incomplete = (
        progress < 0.9999
        or amount_left > 0
        or state_l in {"stoppeddl", "missingfiles", "downloading", "stalleddl"}
    )
    db = db_rows.get(torrent_hash, {})
    expected_names = expected_names_by_hash.get(torrent_hash, [])
    candidates = {}
    rejected = []

    def add_candidate(path: str, score: int, reason: str, evidence: list[str] | None = None):
        if not path:
            return
        path = str(Path(str(path).strip()))
        if not path.startswith("/"):
            return
        if not is_allowed_path(path):
            return
        if not Path(path).exists():
            return
        cur = candidates.get(path)
        if cur is None:
            candidates[path] = {
                "path": path,
                "score": int(score),
                "reasons": [reason],
                "evidence": set(evidence or []),
                "expected_matches": set(),
            }
            return
        if score > cur["score"]:
            cur["score"] = int(score)
        if reason not in cur["reasons"]:
            cur["reasons"].append(reason)
        for ev in evidence or []:
            cur["evidence"].add(ev)

    if save_path:
        add_candidate(save_path, 35, "current_save_path")
        for swapped in alias_swap(save_path):
            add_candidate(swapped, 30, "current_save_path_alias")

    if content_path:
        cp = Path(content_path.strip())
        if cp.exists():
            add_candidate(
                str(cp.parent),
                95,
                "content_path_exists",
                [f"content_exists:{cp.name}"],
            )
        for swapped in alias_swap(content_path):
            sp = Path(swapped)
            if sp.exists():
                add_candidate(
                    str(sp.parent),
                    90,
                    "content_path_alias_exists",
                    [f"content_alias_exists:{sp.name}"],
                )

    db_root_path = str(db.get("db_root_path", "")).strip()
    db_save_path = str(db.get("db_save_path", "")).strip()
    if db_root_path:
        rp = Path(db_root_path)
        if rp.exists():
            add_candidate(
                str(rp.parent),
                110,
                "db_root_path_exists",
                [f"db_root_exists:{rp.name}"],
            )
        for swapped in alias_swap(db_root_path):
            srp = Path(swapped)
            if srp.exists():
                add_candidate(
                    str(srp.parent),
                    100,
                    "db_root_alias_exists",
                    [f"db_root_alias_exists:{srp.name}"],
                )
    if db_save_path:
        if Path(db_save_path).exists():
            add_candidate(db_save_path, 80, "db_save_path_exists")
        for swapped in alias_swap(db_save_path):
            if Path(swapped).exists():
                add_candidate(swapped, 75, "db_save_alias_exists")

    for name in expected_names:
        for payload_row in payload_roots_by_root_name.get(name, []):
            root_path = str(payload_row.get("root_path", "")).strip()
            status = str(payload_row.get("status", "")).strip().lower() or "unknown"
            payload_hash = str(payload_row.get("payload_hash", "")).strip()
            total_bytes = int(payload_row.get("total_bytes", 0) or 0)
            evidence = [f"payload_root_name:{name}", f"payload_status:{status}"]
            if payload_hash:
                evidence.append(f"payload_hash:{payload_hash[:16]}")
            if total_bytes > 0:
                evidence.append(f"payload_bytes:{total_bytes}")
            base_score = 142 if status == "complete" else 106
            rp = Path(root_path)
            if rp.exists():
                add_candidate(
                    str(rp.parent),
                    base_score,
                    "payload_root_path_exists",
                    evidence,
                )
            for swapped in alias_swap(root_path):
                srp = Path(swapped)
                if srp.exists():
                    add_candidate(
                        str(srp.parent),
                        base_score - 4,
                        "payload_root_alias_exists",
                        evidence,
                    )

    for name in expected_names:
        for peer in peer_rows_by_root_name.get(name, []):
            peer_hash = str(peer.get("torrent_hash", ""))
            peer_save_path = str(peer.get("save_path", "")).strip()
            if peer_save_path:
                add_candidate(
                    peer_save_path,
                    88,
                    "peer_root_name_save_path",
                    [f"peer_root_name:{name}", f"peer_hash:{peer_hash[:12]}"],
                )
                for swapped in alias_swap(peer_save_path):
                    add_candidate(
                        swapped,
                        84,
                        "peer_root_name_save_path_alias",
                        [f"peer_root_name:{name}", f"peer_hash:{peer_hash[:12]}"],
                    )

            peer_root_path = str(peer.get("payload_root_path", "")).strip()
            peer_status = str(peer.get("payload_status", "")).strip().lower() or "unknown"
            if peer_root_path:
                pr = Path(peer_root_path)
                if pr.exists():
                    add_candidate(
                        str(pr.parent),
                        114 if peer_status == "complete" else 102,
                        "peer_payload_root_exists",
                        [f"peer_root_name:{name}", f"peer_payload_status:{peer_status}"],
                    )
                for swapped in alias_swap(peer_root_path):
                    spr = Path(swapped)
                    if spr.exists():
                        add_candidate(
                            str(spr.parent),
                            108 if peer_status == "complete" else 96,
                            "peer_payload_root_alias_exists",
                            [f"peer_root_name:{name}", f"peer_payload_status:{peer_status}"],
                        )

    for name in expected_names:
        for hit in discovered_roots.get(name, []):
            hp = Path(hit)
            if hp.exists():
                add_candidate(
                    str(hp.parent),
                    120,
                    "name_discovery",
                    [f"name_match:{name}"],
                )

    needs_catalog_probe = (not candidates) or all(
        (not c["evidence"] and not c["expected_matches"]) for c in candidates.values()
    )
    if needs_catalog_probe:
        for name in expected_names:
            for hit in catalog_hits_for_name(name):
                evidence = [
                    f"catalog_{hit['match_mode']}:{name}",
                    f"catalog_status:{hit['status']}",
                    f"catalog_table:{hit['table']}",
                ]
                add_candidate(hit["path"], int(hit["score"]), "catalog_files_table_match", evidence)
                for swapped in alias_swap(hit["path"]):
                    add_candidate(
                        swapped,
                        int(hit["score"]) - 6,
                        "catalog_files_table_alias",
                        evidence,
                    )

    for cand in candidates.values():
        cpath = Path(cand["path"])
        for expected_name in expected_names:
            if (cpath / expected_name).exists():
                cand["expected_matches"].add(expected_name)
        if cand["expected_matches"]:
            cand["score"] += 25 + min(10, 2 * len(cand["expected_matches"]))
            cand["evidence"].add("expected_name_exists")
        if cand["path"] == save_path and is_incomplete:
            if cand["expected_matches"]:
                cand["score"] -= 10
                cand["reasons"].append("same_save_path_incomplete_penalty")
            else:
                cand["score"] -= 50
                cand["reasons"].append("same_save_path_no_expected_root_penalty")

    valid = []
    for cand in candidates.values():
        reject_reasons = []
        same_path_reject = False
        if cand["path"] == save_path and is_incomplete and not cand["expected_matches"]:
            reject_reasons.append("same_save_path_no_expected_root")
            same_path_reject = True
        if not same_path_reject and not cand["evidence"] and not cand["expected_matches"]:
            reject_reasons.append("missing_recoverability_evidence")
        if reject_reasons:
            rejected.append(
                {
                    "path": cand["path"],
                    "score": cand["score"],
                    "reason": ",".join(cand["reasons"]),
                    "rejected": ",".join(reject_reasons),
                }
            )
            continue
        valid.append(cand)

    ordered = sorted(valid, key=lambda c: (-c["score"], c["path"]))
    best = ordered[0] if ordered else None
    decision = "UNRESOLVED"
    confidence = "unresolved"
    skip_reason = ""
    if best:
        confidence = "confident"
        decision = "MAP"
    elif rejected:
        same_path_only = all(r.get("rejected") == "same_save_path_no_expected_root" for r in rejected)
        same_path = all(r.get("path") == save_path for r in rejected)
        if same_path_only and same_path and save_path and Path(save_path).exists():
            confidence = "skip"
            decision = "SKIP"
            skip_reason = "already_in_place_unproven_root"

    if best is not None:
        confident_hashes.append(torrent_hash)
    elif confidence == "unresolved":
        unresolved_hashes.append(torrent_hash)

    mapped.append(
        {
            "hash": torrent_hash,
            "name": str(e.get("name", "")),
            "state": state,
            "progress": progress,
            "amount_left": amount_left,
            "save_path": save_path,
            "content_path": content_path,
            "db_root_path": db_root_path,
            "db_save_path": db_save_path,
            "expected_names": expected_names,
            "recoverable": bool(best is not None),
            "same_as_save_path": bool(best and best["path"] == save_path),
            "decision": decision,
            "skip_reason": skip_reason,
            "best_evidence": sorted(best["evidence"]) if best else [],
            "best_expected_matches": sorted(best["expected_matches"]) if best else [],
            "payload_hash": db.get("payload_hash", ""),
            "best_candidate": best["path"] if best else "",
            "best_score": best["score"] if best else 0,
            "best_reason": ",".join(best["reasons"]) if best else "",
            "candidate_count": len(ordered),
            "invalid_candidate_count": len(rejected),
            "confidence": confidence,
            "candidates": [
                {
                    "path": c["path"],
                    "score": c["score"],
                    "reason": ",".join(c["reasons"]),
                    "evidence": sorted(c["evidence"]),
                    "expected_matches": sorted(c["expected_matches"]),
                }
                for c in ordered[:6]
            ],
            "rejected_candidates": rejected[:6],
        }
    )

if db_conn is not None:
    db_conn.close()

summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "input_entries": len(entries),
    "mapped_entries": len(mapped),
    "confident": sum(1 for m in mapped if m["confidence"] == "confident"),
    "likely": 0,
    "ambiguous": 0,
    "manual_only": 0,
    "unresolved": sum(1 for m in mapped if m["confidence"] == "unresolved"),
    "allowed_roots": allowed_root_strs,
    "policy": "no_manual_queue_under_known_roots",
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
    "invalid_candidate_count",
    "best_score",
    "best_reason",
    "best_candidate",
    "same_as_save_path",
    "recoverable",
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
    "",
    encoding="utf-8",
)
unresolved_out.write_text(
    "\n".join(sorted({h for h in unresolved_hashes if h})) + ("\n" if unresolved_hashes else ""),
    encoding="utf-8",
)

print(
    "summary "
    f"mapped={summary['mapped_entries']} "
    f"confident={summary['confident']} likely={summary['likely']} "
    f"ambiguous={summary['ambiguous']} manual_only={summary['manual_only']} "
    f"unresolved={summary['unresolved']}"
)
print(f"json_output={json_out}")
print(f"tsv_output={tsv_out}")
print(f"confident_hashes={confident_out}")
print(f"manual_hashes={manual_out}")
print(f"unresolved_hashes={unresolved_out}")
if summary["unresolved"] > 0:
    print(f"error unresolved={summary['unresolved']} policy=no_manual_queue_under_known_roots")
    raise SystemExit(2)
PY

hr
echo "result=ok step=basics-qb-candidate-mapping run_log=${run_log}"
echo "json_output=${json_out}"
echo "tsv_output=${tsv_out}"
echo "confident_hashes=${confident_out}"
echo "manual_hashes=${manual_out}"
echo "unresolved_hashes=${unresolved_out}"
hr
