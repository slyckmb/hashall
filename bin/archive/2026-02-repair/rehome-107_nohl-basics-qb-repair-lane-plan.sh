#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-107_nohl-basics-qb-repair-lane-plan.sh [options]

What this does:
  Read a Phase 106 hash/root report and classify each hash into execution lanes:
  - route_found: safe direct rehome target identified
  - build_from_sibling: sibling payload exists, may be used to reconstruct payload
  - true_missing: no safe route and no viable sibling source

Options:
  --hash-root-json PATH   Phase 106 hash/root JSON (default: latest)
  --output-prefix NAME    Output prefix (default: nohl)
  --limit N               Limit hashes processed (default: 0 = all)
  --route-top-n N         Keep top N route candidates per hash in report (default: 3)
  --fast                  Fast mode annotation
  --debug                 Debug mode annotation
  -h, --help              Show help
USAGE
}

latest_hash_root_report() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-hash-root-report-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

HASH_ROOT_JSON=""
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
ROUTE_TOP_N="${ROUTE_TOP_N:-3}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hash-root-json) HASH_ROOT_JSON="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --route-top-n) ROUTE_TOP_N="${2:-}"; shift 2 ;;
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

if [[ -z "$HASH_ROOT_JSON" ]]; then
  HASH_ROOT_JSON="$(latest_hash_root_report)"
fi
if [[ -z "$HASH_ROOT_JSON" || ! -f "$HASH_ROOT_JSON" ]]; then
  echo "Missing hash/root JSON; run bin/rehome-106_nohl-basics-qb-hash-root-report.sh first." >&2
  exit 3
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi
if ! [[ "$ROUTE_TOP_N" =~ ^[0-9]+$ ]] || [[ "$ROUTE_TOP_N" -lt 1 ]]; then
  echo "Invalid --route-top-n: $ROUTE_TOP_N" >&2
  exit 2
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-repair-lane-plan-${stamp}.log"
lane_json_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-plan-${stamp}.json"
lane_tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-plan-${stamp}.tsv"
lane_md_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-plan-${stamp}.md"
lane_route_hashes_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-route-found-hashes-${stamp}.txt"
lane_sibling_hashes_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-build-from-sibling-hashes-${stamp}.txt"
lane_missing_hashes_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-lane-true-missing-hashes-${stamp}.txt"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 107: qB repair lane planner"
echo "What this does: classify hashes into route_found/build_from_sibling/true_missing lanes."
hr
echo "run_id=${stamp} step=basics-qb-repair-lane-plan hash_root_json=${HASH_ROOT_JSON} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} route_top_n=${ROUTE_TOP_N} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
LANE_HASH_ROOT_JSON="$HASH_ROOT_JSON" \
LANE_LIMIT="$LIMIT" \
LANE_ROUTE_TOP_N="$ROUTE_TOP_N" \
LANE_JSON_OUT="$lane_json_out" \
LANE_TSV_OUT="$lane_tsv_out" \
LANE_MD_OUT="$lane_md_out" \
LANE_ROUTE_HASHES_OUT="$lane_route_hashes_out" \
LANE_SIBLING_HASHES_OUT="$lane_sibling_hashes_out" \
LANE_MISSING_HASHES_OUT="$lane_missing_hashes_out" \
python - <<'PY'
import csv
import json
import os
from datetime import datetime
from pathlib import Path

hash_root_json = Path(os.environ["LANE_HASH_ROOT_JSON"])
limit = int(os.environ.get("LANE_LIMIT", "0") or 0)
route_top_n = max(1, int(os.environ.get("LANE_ROUTE_TOP_N", "3") or 3))

lane_json_out = Path(os.environ["LANE_JSON_OUT"])
lane_tsv_out = Path(os.environ["LANE_TSV_OUT"])
lane_md_out = Path(os.environ["LANE_MD_OUT"])
lane_route_hashes_out = Path(os.environ["LANE_ROUTE_HASHES_OUT"])
lane_sibling_hashes_out = Path(os.environ["LANE_SIBLING_HASHES_OUT"])
lane_missing_hashes_out = Path(os.environ["LANE_MISSING_HASHES_OUT"])

payload = json.loads(hash_root_json.read_text(encoding="utf-8"))
rows = [r for r in payload.get("hashes", []) if str(r.get("hash", "")).strip()]
if limit > 0:
    rows = rows[:limit]


def _score_candidate(cand: dict, torrent_hash: str) -> int:
    score = int(cand.get("score", 0) or 0)
    owners = set(cand.get("owner_hashes", []) or [])
    if torrent_hash in owners:
        score += 60
    if not cand.get("owner_conflicts"):
        score += 25
    tracker_match = str(cand.get("tracker_path_match", "") or "")
    if tracker_match == "exact":
        score += 20
    elif tracker_match == "mismatch":
        score -= 20
    if cand.get("path_exists"):
        score += 10
    return score


entries = []
route_hashes = []
sibling_hashes = []
missing_hashes = []

for row in rows:
    torrent_hash = str(row.get("hash", "")).lower().strip()
    if not torrent_hash:
        continue

    candidates = [c for c in row.get("candidates", []) if isinstance(c, dict)]
    candidates = sorted(
        candidates,
        key=lambda c: (
            -_score_candidate(c, torrent_hash),
            int(c.get("rank", 999999) or 999999),
            str(c.get("path", "")),
        ),
    )
    route_candidates = [
        c
        for c in candidates
        if bool(c.get("path_exists"))
        and not (c.get("owner_conflicts") or [])
        and bool(c.get("route_eligible", False))
    ]
    sibling_candidates = [
        c
        for c in candidates
        if bool(c.get("path_exists")) and any(h != torrent_hash for h in (c.get("owner_hashes") or []))
    ]

    lane = "true_missing"
    reason = "no_path_candidates"
    selected = None
    sibling_source_hash = ""
    sibling_source_path = ""
    action = "manual_investigation_or_restore_from_backup"

    if route_candidates:
        lane = "route_found"
        selected = route_candidates[0]
        reason = "route_eligible_candidate_available"
        target_path = str(selected.get("path", "") or "")
        current_save = str(row.get("qb_save_path", "") or "")
        action = "recheck_only" if current_save and current_save == target_path else "set_location_recheck"
        route_hashes.append(torrent_hash)
    elif sibling_candidates:
        lane = "build_from_sibling"
        selected = sibling_candidates[0]
        reason = "sibling_owner_exists_at_candidate_path"
        owners = [h for h in (selected.get("owner_hashes") or []) if h != torrent_hash]
        sibling_source_hash = owners[0] if owners else ""
        sibling_source_path = str(selected.get("path", "") or "")
        action = "build_payload_from_sibling_then_rehome"
        sibling_hashes.append(torrent_hash)
    else:
        missing_hashes.append(torrent_hash)

    top_candidates = []
    for idx, cand in enumerate(candidates[:route_top_n], start=1):
        top_candidates.append(
            {
                "rank": idx,
                "path": str(cand.get("path", "") or ""),
                "score": _score_candidate(cand, torrent_hash),
                "owner_hashes": list(cand.get("owner_hashes", []) or []),
                "owner_conflicts": list(cand.get("owner_conflicts", []) or []),
                "tracker_path_match": str(cand.get("tracker_path_match", "") or ""),
                "route_eligible": bool(cand.get("route_eligible", False)),
                "path_exists": bool(cand.get("path_exists")),
            }
        )

    entries.append(
        {
            "hash": torrent_hash,
            "name": str(row.get("name", "") or ""),
            "state": str(row.get("state", "") or ""),
            "progress": float(row.get("progress", 0.0) or 0.0),
            "amount_left": int(row.get("amount_left", 0) or 0),
            "tracker_key": str(row.get("tracker_key", "") or ""),
            "category": str(row.get("category", "") or ""),
            "qb_save_path": str(row.get("qb_save_path", "") or ""),
            "qb_content_path": str(row.get("qb_content_path", "") or ""),
            "lane": lane,
            "lane_reason": reason,
            "action": action,
            "selected_target_path": str((selected or {}).get("path", "") or ""),
            "selected_target_score": int(_score_candidate(selected, torrent_hash) if selected else 0),
            "selected_owner_hashes": list((selected or {}).get("owner_hashes", []) or []),
            "selected_owner_conflicts": list((selected or {}).get("owner_conflicts", []) or []),
            "sibling_source_hash": sibling_source_hash,
            "sibling_source_path": sibling_source_path,
            "candidates_top_n": top_candidates,
        }
    )


summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "hashes": len(entries),
    "route_found": sum(1 for e in entries if e.get("lane") == "route_found"),
    "build_from_sibling": sum(1 for e in entries if e.get("lane") == "build_from_sibling"),
    "true_missing": sum(1 for e in entries if e.get("lane") == "true_missing"),
    "route_top_n": int(route_top_n),
}

out = {"summary": summary, "entries": entries}
lane_json_out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

fields = [
    "hash",
    "lane",
    "action",
    "state",
    "tracker_key",
    "category",
    "qb_save_path",
    "selected_target_path",
    "selected_target_score",
    "sibling_source_hash",
    "sibling_source_path",
    "lane_reason",
]
with lane_tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    for row in entries:
        writer.writerow({k: row.get(k, "") for k in fields})

lane_route_hashes_out.write_text("\n".join(route_hashes) + ("\n" if route_hashes else ""), encoding="utf-8")
lane_sibling_hashes_out.write_text("\n".join(sibling_hashes) + ("\n" if sibling_hashes else ""), encoding="utf-8")
lane_missing_hashes_out.write_text("\n".join(missing_hashes) + ("\n" if missing_hashes else ""), encoding="utf-8")

md_lines = [
    "# Phase 107 Repair Lane Plan",
    "",
    f"Generated: {summary['generated_at']}",
    "",
    "## Summary",
    f"- Hashes: {summary['hashes']}",
    f"- route_found: {summary['route_found']}",
    f"- build_from_sibling: {summary['build_from_sibling']}",
    f"- true_missing: {summary['true_missing']}",
    "",
    "## Next Actions",
    "- route_found: feed these hashes into Phase 102 apply first.",
    "- build_from_sibling: run sibling reconstruction before Phase 102 apply.",
    "- true_missing: treat as restore/delete/manual cases.",
]
lane_md_out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

print(
    "summary "
    f"hashes={summary['hashes']} "
    f"route_found={summary['route_found']} "
    f"build_from_sibling={summary['build_from_sibling']} "
    f"true_missing={summary['true_missing']}"
)
print(f"json_output={lane_json_out}")
print(f"tsv_output={lane_tsv_out}")
print(f"md_output={lane_md_out}")
print(f"route_hashes={lane_route_hashes_out}")
print(f"sibling_hashes={lane_sibling_hashes_out}")
print(f"missing_hashes={lane_missing_hashes_out}")
PY

hr
echo "result=ok step=basics-qb-repair-lane-plan run_log=${run_log}"
echo "json_output=${lane_json_out}"
echo "tsv_output=${lane_tsv_out}"
echo "md_output=${lane_md_out}"
echo "route_hashes=${lane_route_hashes_out}"
echo "sibling_hashes=${lane_sibling_hashes_out}"
echo "missing_hashes=${lane_missing_hashes_out}"
hr
