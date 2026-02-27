#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-108_nohl-basics-qb-build-strict-map.sh [options]

What this does:
  Build a deterministic, high-confidence Phase 102 mapping by applying
  strict gates and quarantining hashes with known repeated failure modes.

Strict gates:
  - drop hashes blocked by selected Phase 103 conflict types
  - drop hashes with /incomplete_torrents content_path (from baseline)
  - drop hashes quarantined by failure cache / recent pilot results
  - require unique best target path (optional; on by default)
  - require best-vs-second score gap (default: 20)
  - require minimum best score when only one candidate exists (default: 170)

Options:
  --mapping-json PATH            Phase 101 mapping JSON (default: latest nohl file)
  --baseline-json PATH           Phase 100 baseline JSON (default: latest nohl file)
  --audit-json PATH              Phase 103 audit JSON (default: latest nohl file)
  --failure-cache-json PATH      Failure cache JSON (default: /tmp/nohl-route-failure-cache.json)
  --result-glob GLOB             Pilot result JSON glob (default: latest 40 in nohl reports dir)
  --quarantine-threshold N       Quarantine after N matched failures (default: 1)
  --block-conflict-types CSV     Conflict types to block (default: all audit conflicts)
  --block-failure-types CSV      Failure types to quarantine (default: content_path_mismatch_post_move,recheck_only_stuck_terminal,candidate_budget_exceeded,item_budget_exceeded,bad_terminal_state)
  --min-score-gap N              Min (best_score - second_score) (default: 20)
  --min-best-score N             Min best score when only one candidate exists (default: 170)
  --require-unique-target        Require best target path used by exactly one hash (default: on)
  --no-require-unique-target     Disable unique best target requirement
  --exclude-incomplete-content   Exclude hashes where baseline content_path is under /incomplete_torrents (default: on)
  --no-exclude-incomplete-content
  --strict-map PATH              Output strict mapping JSON (default: /tmp/nohl-qb-candidate-mapping-strict-<stamp>.json)
  --quarantine-json PATH         Output quarantine report JSON (default: /tmp/nohl-qb-strict-quarantine-<stamp>.json)
  --hashes-txt PATH              Output strict hash list (default: /tmp/nohl-qb-strict-hashes-<stamp>.txt)
  --quarantine-hashes-txt PATH   Output quarantined hash list (default: /tmp/nohl-qb-strict-quarantine-hashes-<stamp>.txt)
  --list-conflict-types          Print conflict types found in audit and exit
  -h, --help                     Show help
USAGE
}

latest_mapping() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-candidate-mapping-*.json 2>/dev/null | head -n1 || true
}

latest_baseline() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-repair-baseline-*.json 2>/dev/null | head -n1 || true
}

latest_audit() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-payload-ownership-audit-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MAPPING_JSON=""
BASELINE_JSON=""
AUDIT_JSON=""
FAILURE_CACHE_JSON="/tmp/nohl-route-failure-cache.json"
RESULT_GLOB="$HOME/.logs/hashall/reports/rehome-normalize/*qb-repair-pilot-result-*.json"
QUARANTINE_THRESHOLD=1
BLOCK_CONFLICT_TYPES=""
BLOCK_FAILURE_TYPES="content_path_mismatch_post_move,recheck_only_stuck_terminal,candidate_budget_exceeded,item_budget_exceeded,bad_terminal_state"
MIN_SCORE_GAP=20
MIN_BEST_SCORE=170
REQUIRE_UNIQUE_TARGET=1
EXCLUDE_INCOMPLETE_CONTENT=1
STRICT_MAP=""
QUARANTINE_JSON=""
HASHES_TXT=""
QUARANTINE_HASHES_TXT=""
LIST_CONFLICT_TYPES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --audit-json) AUDIT_JSON="${2:-}"; shift 2 ;;
    --failure-cache-json) FAILURE_CACHE_JSON="${2:-}"; shift 2 ;;
    --result-glob) RESULT_GLOB="${2:-}"; shift 2 ;;
    --quarantine-threshold) QUARANTINE_THRESHOLD="${2:-}"; shift 2 ;;
    --block-conflict-types) BLOCK_CONFLICT_TYPES="${2:-}"; shift 2 ;;
    --block-failure-types) BLOCK_FAILURE_TYPES="${2:-}"; shift 2 ;;
    --min-score-gap) MIN_SCORE_GAP="${2:-}"; shift 2 ;;
    --min-best-score) MIN_BEST_SCORE="${2:-}"; shift 2 ;;
    --require-unique-target) REQUIRE_UNIQUE_TARGET=1; shift ;;
    --no-require-unique-target) REQUIRE_UNIQUE_TARGET=0; shift ;;
    --exclude-incomplete-content) EXCLUDE_INCOMPLETE_CONTENT=1; shift ;;
    --no-exclude-incomplete-content) EXCLUDE_INCOMPLETE_CONTENT=0; shift ;;
    --strict-map) STRICT_MAP="${2:-}"; shift 2 ;;
    --quarantine-json) QUARANTINE_JSON="${2:-}"; shift 2 ;;
    --hashes-txt) HASHES_TXT="${2:-}"; shift 2 ;;
    --quarantine-hashes-txt) QUARANTINE_HASHES_TXT="${2:-}"; shift 2 ;;
    --list-conflict-types) LIST_CONFLICT_TYPES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for n in "$QUARANTINE_THRESHOLD" "$MIN_SCORE_GAP" "$MIN_BEST_SCORE"; do
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
done
if [[ "$QUARANTINE_THRESHOLD" -lt 1 ]]; then
  echo "--quarantine-threshold must be >=1" >&2
  exit 2
fi

if [[ -z "$MAPPING_JSON" ]]; then
  MAPPING_JSON="$(latest_mapping)"
fi
if [[ -z "$BASELINE_JSON" ]]; then
  BASELINE_JSON="$(latest_baseline)"
fi
if [[ -z "$AUDIT_JSON" ]]; then
  AUDIT_JSON="$(latest_audit)"
fi
if [[ -z "$MAPPING_JSON" || ! -f "$MAPPING_JSON" ]]; then
  echo "Missing/invalid --mapping-json" >&2
  exit 3
fi
if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing/invalid --baseline-json" >&2
  exit 3
fi
if [[ -z "$AUDIT_JSON" || ! -f "$AUDIT_JSON" ]]; then
  echo "Missing/invalid --audit-json" >&2
  exit 3
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$STRICT_MAP" ]]; then
  STRICT_MAP="/tmp/nohl-qb-candidate-mapping-strict-${STAMP}.json"
fi
if [[ -z "$QUARANTINE_JSON" ]]; then
  QUARANTINE_JSON="/tmp/nohl-qb-strict-quarantine-${STAMP}.json"
fi
if [[ -z "$HASHES_TXT" ]]; then
  HASHES_TXT="/tmp/nohl-qb-strict-hashes-${STAMP}.txt"
fi
if [[ -z "$QUARANTINE_HASHES_TXT" ]]; then
  QUARANTINE_HASHES_TXT="/tmp/nohl-qb-strict-quarantine-hashes-${STAMP}.txt"
fi

python3 - "$MAPPING_JSON" "$BASELINE_JSON" "$AUDIT_JSON" "$FAILURE_CACHE_JSON" "$RESULT_GLOB" "$QUARANTINE_THRESHOLD" "$BLOCK_CONFLICT_TYPES" "$BLOCK_FAILURE_TYPES" "$MIN_SCORE_GAP" "$MIN_BEST_SCORE" "$REQUIRE_UNIQUE_TARGET" "$EXCLUDE_INCOMPLETE_CONTENT" "$STRICT_MAP" "$QUARANTINE_JSON" "$HASHES_TXT" "$QUARANTINE_HASHES_TXT" "$LIST_CONFLICT_TYPES" <<'PY'
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

mapping_path = Path(sys.argv[1])
baseline_path = Path(sys.argv[2])
audit_path = Path(sys.argv[3])
failure_cache_path = Path(sys.argv[4])
result_glob = str(sys.argv[5])
quarantine_threshold = int(sys.argv[6])
block_conflict_csv = str(sys.argv[7] or "").strip()
block_failure_csv = str(sys.argv[8] or "").strip()
min_score_gap = int(sys.argv[9])
min_best_score = int(sys.argv[10])
require_unique_target = str(sys.argv[11]).strip() in {"1", "true", "yes", "on"}
exclude_incomplete_content = str(sys.argv[12]).strip() in {"1", "true", "yes", "on"}
strict_map_out = Path(sys.argv[13])
quarantine_json_out = Path(sys.argv[14])
hashes_txt_out = Path(sys.argv[15])
quarantine_hashes_txt_out = Path(sys.argv[16])
list_conflict_types = str(sys.argv[17]).strip() in {"1", "true", "yes", "on"}

mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
audit = json.loads(audit_path.read_text(encoding="utf-8"))

entries = [row for row in mapping.get("entries", []) if str(row.get("hash", "")).strip()]
baseline_by_hash = {
    str(row.get("hash", "")).lower(): row
    for row in baseline.get("entries", [])
    if str(row.get("hash", "")).strip()
}

conflicts_by_hash = {}
all_conflict_types = set()
for row in audit.get("conflicts", []):
    h = str(row.get("hash", "")).lower().strip()
    if not h:
        continue
    types = {
        str(x).strip()
        for x in (row.get("conflicts") or [])
        if str(x).strip()
    }
    if not types:
        continue
    conflicts_by_hash[h] = types
    all_conflict_types.update(types)

if list_conflict_types:
    for item in sorted(all_conflict_types):
        print(item)
    raise SystemExit(0)

if not block_conflict_csv or block_conflict_csv.lower() == "all":
    blocked_conflict_types = set(all_conflict_types)
else:
    blocked_conflict_types = {
        p.strip()
        for p in block_conflict_csv.split(",")
        if p.strip()
    }

blocked_failure_types = {
    p.strip()
    for p in block_failure_csv.split(",")
    if p.strip()
}

quarantine_counts = Counter()
quarantine_detail = defaultdict(lambda: defaultdict(int))

if failure_cache_path.exists():
    cache = json.loads(failure_cache_path.read_text(encoding="utf-8"))
    entries_map = cache.get("entries", cache if isinstance(cache, dict) else {})
    if isinstance(entries_map, dict):
        for torrent_hash, path_map in entries_map.items():
            h = str(torrent_hash).lower().strip()
            if len(h) != 40:
                continue
            if not isinstance(path_map, dict):
                continue
            for _path, rec in path_map.items():
                if not isinstance(rec, dict):
                    continue
                count = int(rec.get("count", 0) or 0)
                err_map = rec.get("errors", {}) or {}
                for err_type, err_count in err_map.items():
                    err_key = str(err_type).strip().split(":", 1)[0]
                    if err_key in blocked_failure_types:
                        quarantine_counts[h] += int(err_count or 0) or count or 1
                        quarantine_detail[h][err_key] += int(err_count or 0) or count or 1

result_paths = sorted(glob.glob(result_glob))
if result_paths:
    for path in result_paths[-40:]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in payload.get("results", []):
            h = str(row.get("hash", "")).lower().strip()
            if len(h) != 40:
                continue
            if str(row.get("status", "")).lower() != "error":
                continue
            err = str(row.get("error", "")).strip().split(":", 1)[0]
            if err in blocked_failure_types:
                quarantine_counts[h] += 1
                quarantine_detail[h][err] += 1

quarantined_hashes = {
    h for h, c in quarantine_counts.items()
    if c >= quarantine_threshold
}

best_target_counts = Counter()
for row in entries:
    p = str(row.get("best_candidate", "")).strip()
    if p.startswith("/"):
        best_target_counts[p] += 1

kept = []
quarantine_rows = []
drop_reasons = Counter()

for row in entries:
    h = str(row.get("hash", "")).lower().strip()
    if not h:
        continue

    reasons = []
    details = {}

    if str(row.get("confidence", "")).lower() != "confident":
        reasons.append("not_confident")

    blocked = conflicts_by_hash.get(h, set()) & blocked_conflict_types
    if blocked:
        reasons.append("blocked_conflict_types")
        details["blocked_conflicts"] = sorted(blocked)

    b = baseline_by_hash.get(h, {})
    content_path = str(b.get("content_path", "")).strip()
    if exclude_incomplete_content and content_path.startswith("/incomplete_torrents/"):
        reasons.append("content_path_in_incomplete_torrents")
        details["content_path"] = content_path

    if h in quarantined_hashes:
        reasons.append("quarantined_by_failure_history")
        details["failure_counts"] = dict(quarantine_detail.get(h, {}))
        details["failure_total"] = int(quarantine_counts.get(h, 0))

    best_target = str(row.get("best_candidate", "")).strip()
    if not best_target.startswith("/"):
        reasons.append("missing_best_target")
    elif require_unique_target and best_target_counts.get(best_target, 0) != 1:
        reasons.append("best_target_not_unique")
        details["best_target_shared_count"] = int(best_target_counts.get(best_target, 0))

    candidates = [c for c in (row.get("candidates") or []) if isinstance(c, dict)]
    ranked = sorted(candidates, key=lambda c: int(c.get("rank", 999999) or 999999))
    best_score = int(row.get("best_score", 0) or 0)
    if ranked:
        best_score = int(ranked[0].get("score", best_score) or best_score)
    second_score = int(ranked[1].get("score", 0) or 0) if len(ranked) > 1 else None

    if second_score is not None:
        gap = best_score - second_score
        if gap < min_score_gap:
            reasons.append("score_gap_too_small")
            details["score_gap"] = int(gap)
            details["best_score"] = int(best_score)
            details["second_score"] = int(second_score)
    else:
        if best_score < min_best_score:
            reasons.append("single_candidate_low_score")
            details["best_score"] = int(best_score)

    if reasons:
        quarantine_rows.append(
            {
                "hash": h,
                "name": str(row.get("name", "")),
                "reasons": reasons,
                "details": details,
                "best_candidate": best_target,
                "best_score": int(best_score),
                "state": str(row.get("state", "")),
            }
        )
        for r in reasons:
            drop_reasons[r] += 1
        continue

    kept.append(row)

out = dict(mapping)
out["entries"] = kept
out["_strict_source_mapping_json"] = str(mapping_path)
out["_strict_source_baseline_json"] = str(baseline_path)
out["_strict_source_audit_json"] = str(audit_path)
out["_strict_source_failure_cache_json"] = str(failure_cache_path)
out["_strict_quarantine_threshold"] = int(quarantine_threshold)
out["_strict_block_conflict_types"] = sorted(blocked_conflict_types)
out["_strict_block_failure_types"] = sorted(blocked_failure_types)
out["_strict_require_unique_target"] = bool(require_unique_target)
out["_strict_exclude_incomplete_content"] = bool(exclude_incomplete_content)
out["_strict_min_score_gap"] = int(min_score_gap)
out["_strict_min_best_score"] = int(min_best_score)
out["_strict_filtered_entry_count"] = len(kept)
out["_strict_quarantined_entry_count"] = len(quarantine_rows)

strict_map_out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

quarantine_payload = {
    "summary": {
        "source_mapping_entries": len(entries),
        "strict_entries": len(kept),
        "quarantined_entries": len(quarantine_rows),
        "drop_reasons": dict(drop_reasons),
        "blocked_conflict_types": sorted(blocked_conflict_types),
        "blocked_failure_types": sorted(blocked_failure_types),
        "quarantine_threshold": int(quarantine_threshold),
        "require_unique_target": bool(require_unique_target),
        "exclude_incomplete_content": bool(exclude_incomplete_content),
        "min_score_gap": int(min_score_gap),
        "min_best_score": int(min_best_score),
    },
    "quarantine": quarantine_rows,
}
quarantine_json_out.write_text(json.dumps(quarantine_payload, indent=2) + "\n", encoding="utf-8")

strict_hashes = sorted(str(row.get("hash", "")).lower() for row in kept if str(row.get("hash", "")).strip())
quarantine_hashes = sorted(str(row.get("hash", "")).lower() for row in quarantine_rows if str(row.get("hash", "")).strip())
hashes_txt_out.write_text("\n".join(strict_hashes) + ("\n" if strict_hashes else ""), encoding="utf-8")
quarantine_hashes_txt_out.write_text("\n".join(quarantine_hashes) + ("\n" if quarantine_hashes else ""), encoding="utf-8")

print(f"mapping_entries={len(entries)}")
print(f"strict_entries={len(kept)}")
print(f"quarantined_entries={len(quarantine_rows)}")
print("drop_reasons=" + ",".join(f"{k}:{v}" for k, v in sorted(drop_reasons.items())))
print("blocked_conflict_types=" + ",".join(sorted(blocked_conflict_types)))
print("blocked_failure_types=" + ",".join(sorted(blocked_failure_types)))
print(f"strict_map={strict_map_out}")
print(f"quarantine_json={quarantine_json_out}")
print(f"hashes_txt={hashes_txt_out}")
print(f"quarantine_hashes_txt={quarantine_hashes_txt_out}")
PY

if [[ "$LIST_CONFLICT_TYPES" -eq 1 ]]; then
  exit 0
fi

echo "next_dryrun=bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10 --selection-mode pilot --batch-size 5 --candidate-top-n 3 --candidate-fallback --mapping-json ${STRICT_MAP} --baseline-json ${BASELINE_JSON}"
