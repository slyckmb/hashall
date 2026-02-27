#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-102_nohl-basics-qb-repair-pilot.sh [options]

Options:
  --mapping-json PATH      Stage 3 candidate mapping JSON (default: latest)
  --baseline-json PATH     Stage 2 baseline JSON (default: latest)
  --mode MODE              dryrun | apply (default: dryrun)
  --limit N                Max pilot torrents (default: 3)
  --selection-mode MODE    auto | pilot | throughput (default: auto)
  --candidate-top-n N      Candidate attempts per hash (default: 1)
  --candidate-fallback     Try next-ranked candidate when candidate-sensitive failures occur
  --candidate-max-seconds N  Max seconds per candidate attempt before fail-fast (default: 300)
  --item-max-seconds N     Max seconds per hash across all candidate attempts (default: 900)
  --candidate-failure-cache-json PATH
                            JSON cache of known bad (hash,path) candidates across rounds
  --candidate-failure-cache-threshold N
                            Skip candidate after this many cached failures (default: 1)
  --poll-s N               Poll interval seconds (default: 2)
  --timeout-s N            Per-item timeout seconds (default: 1200)
  --heartbeat-s N          Heartbeat interval seconds (default: 10)
  --batch-size N           Apply-mode items per batch wave (default: 10)
  --ownership-audit-json PATH  Phase 103 ownership audit JSON (default: latest on apply)
  --allow-ownership-conflicts  Bypass Phase 103 conflict gate on apply
  --output-prefix NAME     Output prefix (default: nohl)
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

latest_ownership_audit() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-qb-payload-ownership-audit-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MAPPING_JSON=""
BASELINE_JSON=""
MODE="${MODE:-dryrun}"
LIMIT="${LIMIT:-3}"
SELECTION_MODE="${SELECTION_MODE:-auto}"
CANDIDATE_TOP_N="${CANDIDATE_TOP_N:-1}"
CANDIDATE_FALLBACK="${CANDIDATE_FALLBACK:-0}"
CANDIDATE_MAX_SECONDS="${CANDIDATE_MAX_SECONDS:-300}"
ITEM_MAX_SECONDS="${ITEM_MAX_SECONDS:-900}"
CANDIDATE_FAILURE_CACHE_JSON="${CANDIDATE_FAILURE_CACHE_JSON:-}"
CANDIDATE_FAILURE_CACHE_THRESHOLD="${CANDIDATE_FAILURE_CACHE_THRESHOLD:-1}"
POLL_S="${POLL_S:-2}"
TIMEOUT_S="${TIMEOUT_S:-1200}"
HEARTBEAT_S="${HEARTBEAT_S:-10}"
BATCH_SIZE="${BATCH_SIZE:-10}"
OWNERSHIP_AUDIT_JSON="${OWNERSHIP_AUDIT_JSON:-}"
ALLOW_OWNERSHIP_CONFLICTS="${ALLOW_OWNERSHIP_CONFLICTS:-0}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --selection-mode) SELECTION_MODE="${2:-}"; shift 2 ;;
    --candidate-top-n) CANDIDATE_TOP_N="${2:-}"; shift 2 ;;
    --candidate-fallback) CANDIDATE_FALLBACK=1; shift ;;
    --no-candidate-fallback) CANDIDATE_FALLBACK=0; shift ;;
    --candidate-max-seconds) CANDIDATE_MAX_SECONDS="${2:-}"; shift 2 ;;
    --item-max-seconds) ITEM_MAX_SECONDS="${2:-}"; shift 2 ;;
    --candidate-failure-cache-json) CANDIDATE_FAILURE_CACHE_JSON="${2:-}"; shift 2 ;;
    --candidate-failure-cache-threshold) CANDIDATE_FAILURE_CACHE_THRESHOLD="${2:-}"; shift 2 ;;
    --poll-s) POLL_S="${2:-}"; shift 2 ;;
    --timeout-s) TIMEOUT_S="${2:-}"; shift 2 ;;
    --heartbeat-s) HEARTBEAT_S="${2:-}"; shift 2 ;;
    --batch-size) BATCH_SIZE="${2:-}"; shift 2 ;;
    --ownership-audit-json) OWNERSHIP_AUDIT_JSON="${2:-}"; shift 2 ;;
    --allow-ownership-conflicts) ALLOW_OWNERSHIP_CONFLICTS=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
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

if [[ "$MODE" != "dryrun" && "$MODE" != "apply" ]]; then
  echo "Invalid --mode: $MODE" >&2
  exit 2
fi
if [[ "$SELECTION_MODE" != "auto" && "$SELECTION_MODE" != "pilot" && "$SELECTION_MODE" != "throughput" ]]; then
  echo "Invalid --selection-mode: $SELECTION_MODE (expected auto|pilot|throughput)" >&2
  exit 2
fi
for n in "$LIMIT" "$CANDIDATE_TOP_N" "$CANDIDATE_MAX_SECONDS" "$ITEM_MAX_SECONDS" "$CANDIDATE_FAILURE_CACHE_THRESHOLD" "$POLL_S" "$TIMEOUT_S" "$HEARTBEAT_S" "$BATCH_SIZE"; do
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
done
if [[ "$CANDIDATE_TOP_N" -lt 1 ]]; then
  echo "--candidate-top-n must be >=1" >&2
  exit 2
fi
if [[ "$BATCH_SIZE" -lt 1 ]]; then
  echo "--batch-size must be >=1" >&2
  exit 2
fi
if [[ "$CANDIDATE_MAX_SECONDS" -lt 30 ]]; then
  echo "--candidate-max-seconds must be >=30" >&2
  exit 2
fi
if [[ "$ITEM_MAX_SECONDS" -lt "$CANDIDATE_MAX_SECONDS" ]]; then
  echo "--item-max-seconds must be >= --candidate-max-seconds" >&2
  exit 2
fi
if [[ "$CANDIDATE_FAILURE_CACHE_THRESHOLD" -lt 1 ]]; then
  echo "--candidate-failure-cache-threshold must be >=1" >&2
  exit 2
fi

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
if [[ "$MODE" == "apply" && "$ALLOW_OWNERSHIP_CONFLICTS" != "1" ]]; then
  if [[ -z "$OWNERSHIP_AUDIT_JSON" ]]; then
    OWNERSHIP_AUDIT_JSON="$(latest_ownership_audit)"
  fi
  if [[ -z "$OWNERSHIP_AUDIT_JSON" || ! -f "$OWNERSHIP_AUDIT_JSON" ]]; then
    echo "Missing ownership audit JSON; run bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh first." >&2
    exit 3
  fi
  python - "$OWNERSHIP_AUDIT_JSON" <<'PY'
import json
import sys
from pathlib import Path
audit = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
summary = audit.get("summary", {})
conflicts = int(summary.get("conflict_count", summary.get("conflict_hashes", 0)) or 0)
if conflicts > 0:
    print(
        f"Ownership audit conflict gate blocked apply: conflict_count={conflicts} "
        f"audit_json={sys.argv[1]}"
    )
    raise SystemExit(2)
print(f"ownership_gate ok conflict_count={conflicts} audit_json={sys.argv[1]}")
PY
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-repair-pilot-${stamp}.log"
plan_json="${log_dir}/${OUTPUT_PREFIX}-qb-repair-pilot-plan-${stamp}.json"
result_json="${log_dir}/${OUTPUT_PREFIX}-qb-repair-pilot-result-${stamp}.json"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 102: qB repair pilot transaction"
echo "What this does: run 1-by-1 repair transaction on small/medium/large confident items."
hr
echo "run_id=${stamp} step=basics-qb-repair-pilot mode=${MODE} limit=${LIMIT} selection_mode=${SELECTION_MODE} candidate_top_n=${CANDIDATE_TOP_N} candidate_fallback=${CANDIDATE_FALLBACK} candidate_max_s=${CANDIDATE_MAX_SECONDS} item_max_s=${ITEM_MAX_SECONDS} candidate_failure_cache_json=${CANDIDATE_FAILURE_CACHE_JSON:-none} candidate_failure_cache_threshold=${CANDIDATE_FAILURE_CACHE_THRESHOLD} poll_s=${POLL_S} timeout_s=${TIMEOUT_S} heartbeat_s=${HEARTBEAT_S} batch_size=${BATCH_SIZE} mapping_json=${MAPPING_JSON} baseline_json=${BASELINE_JSON} ownership_audit_json=${OWNERSHIP_AUDIT_JSON:-none} allow_ownership_conflicts=${ALLOW_OWNERSHIP_CONFLICTS} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
PILOT_MAPPING_JSON="$MAPPING_JSON" \
PILOT_BASELINE_JSON="$BASELINE_JSON" \
PILOT_PLAN_JSON="$plan_json" \
PILOT_RESULT_JSON="$result_json" \
PILOT_LIMIT="$LIMIT" \
PILOT_MODE="$MODE" \
PILOT_SELECTION_MODE="$SELECTION_MODE" \
PILOT_CANDIDATE_TOP_N="$CANDIDATE_TOP_N" \
PILOT_CANDIDATE_FALLBACK="$CANDIDATE_FALLBACK" \
PILOT_CANDIDATE_MAX_SECONDS="$CANDIDATE_MAX_SECONDS" \
PILOT_ITEM_MAX_SECONDS="$ITEM_MAX_SECONDS" \
PILOT_CANDIDATE_FAILURE_CACHE_JSON="$CANDIDATE_FAILURE_CACHE_JSON" \
PILOT_CANDIDATE_FAILURE_CACHE_THRESHOLD="$CANDIDATE_FAILURE_CACHE_THRESHOLD" \
PILOT_POLL_S="$POLL_S" \
PILOT_TIMEOUT_S="$TIMEOUT_S" \
PILOT_HEARTBEAT_S="$HEARTBEAT_S" \
PILOT_BATCH_SIZE="$BATCH_SIZE" \
python -u - <<'PY'
import glob
import json
import os
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from hashall.qbittorrent import get_qbittorrent_client

mapping_json = Path(os.environ["PILOT_MAPPING_JSON"])
baseline_json = Path(os.environ["PILOT_BASELINE_JSON"])
plan_json = Path(os.environ["PILOT_PLAN_JSON"])
result_json = Path(os.environ["PILOT_RESULT_JSON"])
limit = int(os.environ.get("PILOT_LIMIT", "3") or 3)
mode = os.environ.get("PILOT_MODE", "dryrun").strip().lower()
selection_mode = os.environ.get("PILOT_SELECTION_MODE", "auto").strip().lower()
candidate_top_n = max(1, int(os.environ.get("PILOT_CANDIDATE_TOP_N", "1") or 1))
candidate_fallback_enabled = os.environ.get("PILOT_CANDIDATE_FALLBACK", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
candidate_max_s = max(30, int(os.environ.get("PILOT_CANDIDATE_MAX_SECONDS", "300") or 300))
item_max_s = max(candidate_max_s, int(os.environ.get("PILOT_ITEM_MAX_SECONDS", "900") or 900))
candidate_failure_cache_threshold = max(
    1, int(os.environ.get("PILOT_CANDIDATE_FAILURE_CACHE_THRESHOLD", "1") or 1)
)
candidate_failure_cache_path_raw = str(os.environ.get("PILOT_CANDIDATE_FAILURE_CACHE_JSON", "") or "").strip()
candidate_failure_cache_path = Path(candidate_failure_cache_path_raw) if candidate_failure_cache_path_raw else None
poll_s = max(1, int(os.environ.get("PILOT_POLL_S", "2") or 2))
timeout_s = max(60, int(os.environ.get("PILOT_TIMEOUT_S", "1200") or 1200))
heartbeat_s = max(5, int(os.environ.get("PILOT_HEARTBEAT_S", "10") or 10))
batch_size = max(1, int(os.environ.get("PILOT_BATCH_SIZE", "10") or 10))
apply_mode = mode == "apply"

candidate_failure_cache: dict[str, dict[str, dict]] = {}
candidate_failure_cache_dirty = False
cache_skipped_candidates = 0
if candidate_failure_cache_path and candidate_failure_cache_path.exists():
    try:
        raw_cache = json.loads(candidate_failure_cache_path.read_text(encoding="utf-8"))
        if isinstance(raw_cache, dict) and isinstance(raw_cache.get("entries"), dict):
            raw_cache = raw_cache.get("entries", {})
        if isinstance(raw_cache, dict):
            for h, by_path in raw_cache.items():
                h_key = str(h or "").lower().strip()
                if not h_key or not isinstance(by_path, dict):
                    continue
                norm_by_path = {}
                for path_key, meta in by_path.items():
                    p_key = str(path_key or "").strip()
                    if not p_key:
                        continue
                    if isinstance(meta, dict):
                        norm_by_path[p_key] = dict(meta)
                    else:
                        norm_by_path[p_key] = {"count": int(meta or 0)}
                if norm_by_path:
                    candidate_failure_cache[h_key] = norm_by_path
    except Exception:
        candidate_failure_cache = {}


def candidate_cached_failure_count(torrent_hash: str, target_path: str) -> int:
    per_hash = candidate_failure_cache.get(str(torrent_hash or "").lower().strip(), {})
    item = per_hash.get(str(target_path or "").strip(), {})
    if not isinstance(item, dict):
        try:
            return int(item or 0)
        except Exception:
            return 0
    try:
        return int(item.get("count", 0) or 0)
    except Exception:
        return 0


mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
baseline = json.loads(baseline_json.read_text(encoding="utf-8"))
by_hash = {
    str(e.get("hash", "")).lower(): e
    for e in baseline.get("entries", [])
    if str(e.get("hash", "")).strip()
}
confident = [
    e for e in mapping.get("entries", [])
    if str(e.get("confidence", "")).lower() == "confident"
]
for e in confident:
    h = str(e.get("hash", "")).lower()
    b = by_hash.get(h, {})
    e["_size"] = int(b.get("size", 0) or 0)
    e["_name"] = str(b.get("name", "") or "")
    e["_state"] = str(b.get("state", "") or "")
    e["_save_path"] = str(b.get("save_path", "") or str(e.get("save_path", "") or ""))

if not confident:
    payload = {"summary": {"selected": 0, "reason": "no_confident_candidates"}, "plan": [], "results": []}
    plan_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    result_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("summary selected=0 reason=no_confident_candidates")
    raise SystemExit(0)

handled_stoppedup = set()
for result_path in sorted(glob.glob(str(mapping_json.parent / "*-qb-repair-pilot-result-*.json")), reverse=True)[:25]:
    try:
        payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
    except Exception:
        continue
    for item in payload.get("results", []):
        if str(item.get("final_state", "")).lower() == "stoppedup":
            h = str(item.get("hash", "")).lower().strip()
            if h:
                handled_stoppedup.add(h)

def normalized_candidates(entry: dict) -> list[dict]:
    out = []
    seen = set()
    raw = entry.get("candidates", [])
    if isinstance(raw, list):
        for cand in raw:
            if not isinstance(cand, dict):
                continue
            path = str(cand.get("path", "")).strip()
            if not path.startswith("/") or path in seen:
                continue
            seen.add(path)
            out.append(
                {
                    "path": path,
                    "payload_root": str(cand.get("payload_root", "") or "").strip(),
                    "score": int(cand.get("score", 0) or 0),
                    "reason": str(cand.get("reason", "") or ""),
                    "rank": int(cand.get("rank", len(out) + 1) or len(out) + 1),
                }
            )
    best = str(entry.get("best_candidate", "") or "").strip()
    if best.startswith("/") and best not in seen:
        out.insert(
            0,
            {
                "path": best,
                "payload_root": str(entry.get("best_payload_root", "") or "").strip(),
                "score": int(entry.get("best_score", 0) or 0),
                "reason": str(entry.get("best_reason", "") or ""),
                "rank": 1,
            },
        )
    for idx, cand in enumerate(out, start=1):
        cand["rank"] = idx
    return out[:candidate_top_n]


qb = get_qbittorrent_client()
if not qb.test_connection() or not qb.login():
    qb = None

eligible = []
rejected = []
for e in confident:
    h = str(e.get("hash", "")).lower()
    current_save = str(e.get("_save_path", "") or "").strip()
    recoverable = bool(e.get("recoverable", False))
    candidate_rows = normalized_candidates(e)
    best_evidence = list(e.get("best_evidence", []) or [])
    best_expected = list(e.get("best_expected_matches", []) or [])
    evidence = sorted({str(x) for x in (best_evidence + best_expected) if str(x).strip()})

    reasons = []
    if not recoverable:
        reasons.append("mapping_not_recoverable")
    if not evidence:
        reasons.append("missing_recoverability_evidence")
    if not candidate_rows:
        reasons.append("no_ranked_candidates")
    valid_candidates = []
    skipped_by_cache = 0
    for cand in candidate_rows:
        cpath = str(cand.get("path", "")).strip()
        if not cpath.startswith("/"):
            continue
        if not Path(cpath).exists():
            continue
        cached_failures = candidate_cached_failure_count(h, cpath)
        if cached_failures >= candidate_failure_cache_threshold:
            skipped_by_cache += 1
            cache_skipped_candidates += 1
            continue
        cand_row = dict(cand)
        cand_row["mode"] = "recheck_only" if current_save and cpath == current_save else "move"
        cand_row["cached_failures"] = int(cached_failures)
        valid_candidates.append(cand_row)
    if not valid_candidates:
        if skipped_by_cache and skipped_by_cache >= len(candidate_rows):
            reasons.append("all_candidates_blocked_by_failure_cache")
        else:
            reasons.append("no_preflight_valid_candidates")
    if qb is not None and valid_candidates:
        info = qb.get_torrent_info(h)
        if info is not None:
            live_state = (getattr(info, "state", "") or "").lower()
            live_save = str(getattr(info, "save_path", "") or "").strip()
            candidate_paths = {str(c.get("path", "")).strip() for c in valid_candidates}
            if live_state == "stoppedup" and live_save in candidate_paths:
                reasons.append("already_normalized_stoppedup_candidate_path")
            elif h in handled_stoppedup and live_save in candidate_paths:
                reasons.append("already_normalized_stoppedup_candidate_path")

    if reasons:
        rejected.append(
            {
                "hash": h,
                "name": str(e.get("_name", "")),
                "state": str(e.get("_state", "")),
                "current_save_path": current_save,
                "target_save_path": str(e.get("best_candidate", "") or ""),
                "reason": ",".join(reasons),
            }
        )
        continue

    e["_best_evidence"] = evidence
    e["_candidate_rows"] = valid_candidates
    eligible.append(e)

if not eligible:
    payload = {
        "summary": {
            "selected": 0,
            "reason": "no_preflight_eligible_candidates",
            "rejected": len(rejected),
        },
        "plan": [],
        "rejected": rejected,
        "results": [],
    }
    plan_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    result_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"summary selected=0 reason=no_preflight_eligible_candidates rejected={len(rejected)}")
    raise SystemExit(0)

def primary_candidate_score(entry: dict) -> int:
    rows = list(entry.get("_candidate_rows", []))
    if not rows:
        return 0
    return int(rows[0].get("score", 0) or 0)


def candidate_mode_rank(candidate: dict) -> int:
    mode = str(candidate.get("mode", "") or "").strip().lower()
    if mode == "move":
        return 0
    if mode == "recheck_only":
        return 1
    return 2


def primary_candidate_mode_rank(entry: dict) -> int:
    rows = list(entry.get("_candidate_rows", []))
    if not rows:
        return 2
    return candidate_mode_rank(rows[0])


effective_selection_mode = selection_mode
if effective_selection_mode == "auto":
    effective_selection_mode = "throughput" if apply_mode else "pilot"

if apply_mode and effective_selection_mode == "throughput":
    for e in eligible:
        rows = list(e.get("_candidate_rows", []))
        rows = sorted(
            rows,
            key=lambda c: (
                candidate_mode_rank(c),
                -int(c.get("score", 0) or 0),
                int(c.get("rank", 0) or 0),
                str(c.get("path", "")),
            ),
        )
        for idx, cand in enumerate(rows, start=1):
            cand["rank"] = idx
        e["_candidate_rows"] = rows

if effective_selection_mode == "throughput":
    eligible = sorted(
        eligible,
        key=lambda e: (
            primary_candidate_mode_rank(e),
            int(e.get("_size", 0)),
            -primary_candidate_score(e),
            -len(list(e.get("_best_evidence", []))),
            str(e.get("hash", "")),
        ),
    )
    selected = eligible[:limit]
else:
    eligible = sorted(eligible, key=lambda e: (int(e.get("_size", 0)), str(e.get("hash", ""))))
    indices = sorted(set([0, len(eligible) // 2, len(eligible) - 1]))
    selected = [eligible[i] for i in indices][:limit]
    if len(selected) < limit:
        for e in eligible:
            if e in selected:
                continue
            selected.append(e)
            if len(selected) >= limit:
                break

plan_rows = []
for e in selected:
    ranked = list(e.get("_candidate_rows", []))
    first = ranked[0] if ranked else {}
    plan_rows.append(
        {
            "hash": str(e.get("hash", "")).lower(),
            "name": str(e.get("_name", "")),
            "size": int(e.get("_size", 0)),
            "state": str(e.get("_state", "")),
            "current_save_path": str(e.get("_save_path", "")),
            "target_save_path": str(first.get("path", "") or e.get("best_candidate", "")),
            "target_payload_root": str(first.get("payload_root", "") or e.get("best_payload_root", "")),
            "best_reason": str(e.get("best_reason", "")),
            "best_score": int(e.get("best_score", 0) or 0),
            "primary_candidate_score": primary_candidate_score(e),
            "best_evidence": list(e.get("_best_evidence", [])),
            "candidates": ranked,
        }
    )

plan_payload = {
    "summary": {
        "selected": len(plan_rows),
        "mode": mode,
        "eligible": len(eligible),
        "rejected": len(rejected),
        "selection_mode": effective_selection_mode,
        "candidate_top_n": candidate_top_n,
        "candidate_fallback": int(candidate_fallback_enabled),
        "candidate_max_seconds": candidate_max_s,
        "item_max_seconds": item_max_s,
        "candidate_failure_cache_json": str(candidate_failure_cache_path) if candidate_failure_cache_path else "",
        "candidate_failure_cache_threshold": int(candidate_failure_cache_threshold),
        "candidate_failure_cache_skipped": int(cache_skipped_candidates),
    },
    "plan": plan_rows,
    "rejected": rejected,
}
plan_json.write_text(json.dumps(plan_payload, indent=2) + "\n", encoding="utf-8")
print(f"pilot_plan selected={len(plan_rows)} eligible={len(eligible)} rejected={len(rejected)} plan_json={plan_json}")
for idx, row in enumerate(plan_rows, start=1):
    print(
        f"pilot_item idx={idx}/{len(plan_rows)} hash={row['hash'][:8]} "
        f"size={row['size']} state={row['state']} current={row['current_save_path']} target={row['target_save_path']}"
    )
    for cand in row.get("candidates", [])[:candidate_top_n]:
        print(
            f"pilot_candidate hash={row['hash'][:8]} rank={int(cand.get('rank', 0) or 0)} "
            f"score={int(cand.get('score', 0) or 0)} target={str(cand.get('path', ''))}"
        )

if not apply_mode:
    result_payload = {
        "summary": {
            "selected": len(plan_rows),
        "mode": mode,
        "ok": 0,
        "errors": 0,
        "selection_mode": effective_selection_mode,
        "candidate_top_n": candidate_top_n,
        "candidate_fallback": int(candidate_fallback_enabled),
        "candidate_max_seconds": candidate_max_s,
        "item_max_seconds": item_max_s,
        "candidate_failure_cache_json": str(candidate_failure_cache_path) if candidate_failure_cache_path else "",
        "candidate_failure_cache_threshold": int(candidate_failure_cache_threshold),
        "candidate_failure_cache_skipped": int(cache_skipped_candidates),
    },
        "results": [],
    }
    result_json.write_text(json.dumps(result_payload, indent=2) + "\n", encoding="utf-8")
    print(f"summary selected={len(plan_rows)} mode=dryrun ok=0 errors=0 result_json={result_json}")
    raise SystemExit(0)

qb = get_qbittorrent_client(
    base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
    username=os.getenv("QBIT_USER", "admin"),
    password=os.getenv("QBIT_PASS", "adminpass"),
)

results = []
stats = {"ok": 0, "errors": 0, "fallback_used": 0}
rank_histogram = Counter()
failure_buckets = Counter()


def state_lower(info):
    return str(getattr(info, "state", "") or "").lower()


def is_complete_payload_state(info) -> bool:
    if info is None:
        return False
    st = state_lower(info)
    progress = float(getattr(info, "progress", 0.0) or 0.0)
    amount_left = int(getattr(info, "amount_left", 0) or 0)
    if progress < 0.9999 or amount_left > 0:
        return False
    if st.startswith("checking"):
        return False
    if st in {"downloading", "stalleddl", "missingfiles", "moving"}:
        return False
    return True


def should_try_next_candidate(error_text: str, attempt_mode: str = "move") -> bool:
    if (
        error_text.startswith("content_path_mismatch_post_move:")
        or error_text.startswith("set_location_failed")
        or error_text.startswith("invalid_target_path")
        or error_text.startswith("timeout_wait_moving_clear")
        or error_text.startswith("missing_torrent_info")
        or error_text.startswith("candidate_budget_exceeded:")
        or error_text.startswith("conflict_target_payload_root_claimed:")
        or error_text.startswith("recheck_only_stuck_terminal")
    ):
        return True

    if str(attempt_mode or "").lower() == "recheck_only":
        return (
            error_text.startswith("stuck_terminal_after_recovery")
            or error_text.startswith("bad_terminal_state:downloading")
            or error_text.startswith("bad_terminal_state:stalleddl")
            or error_text.startswith("final_state_not_stoppedup:")
        )
    return False


def failure_bucket(error_text: str) -> str:
    if error_text.startswith("bad_terminal_state:"):
        return error_text
    if error_text.startswith("content_path_mismatch_post_move:"):
        return "content_path_mismatch_post_move"
    if error_text.startswith("candidate_budget_exceeded:"):
        return "candidate_budget_exceeded"
    if error_text.startswith("recheck_only_stuck_terminal"):
        return "recheck_only_stuck_terminal"
    return error_text.split(":", 1)[0]


def fetch_infos(hashes: list[str]) -> dict[str, object]:
    wanted = [str(h or "").lower().strip() for h in hashes if str(h or "").strip()]
    if not wanted:
        return {}
    out: dict[str, object] = {}
    try:
        if hasattr(qb, "get_torrents_by_hashes"):
            bulk = qb.get_torrents_by_hashes(wanted)  # type: ignore[attr-defined]
            if isinstance(bulk, dict):
                for h, info in bulk.items():
                    key = str(h or "").lower().strip()
                    if key:
                        out[key] = info
    except Exception:
        out = {}
    if len(out) >= len(wanted):
        return out
    for h in wanted:
        if h in out:
            continue
        try:
            info = qb.get_torrent_info(h)
        except Exception:
            info = None
        if info is not None:
            out[h] = info
    return out


def clean_attempt_output(attempt: dict) -> dict:
    return {k: v for k, v in attempt.items() if not k.startswith("_")}


def should_cache_candidate_failure(error_text: str) -> bool:
    return (
        error_text.startswith("content_path_mismatch_post_move:")
        or error_text.startswith("recheck_only_stuck_terminal")
        or error_text.startswith("stuck_terminal_after_recovery")
        or error_text.startswith("bad_terminal_state:downloading")
        or error_text.startswith("bad_terminal_state:stalleddl")
        or error_text.startswith("final_state_not_stoppedup:")
        or error_text.startswith("candidate_budget_exceeded:")
    )


def record_candidate_failure(torrent_hash: str, target_path: str, error_text: str) -> None:
    global candidate_failure_cache_dirty
    if not candidate_failure_cache_path:
        return
    if not should_cache_candidate_failure(error_text):
        return
    h_key = str(torrent_hash or "").lower().strip()
    p_key = str(target_path or "").strip()
    if not h_key or not p_key.startswith("/"):
        return
    by_hash = candidate_failure_cache.setdefault(h_key, {})
    meta = by_hash.get(p_key)
    if not isinstance(meta, dict):
        meta = {"count": int(meta or 0)}
    count = int(meta.get("count", 0) or 0) + 1
    meta["count"] = count
    errors = meta.get("errors")
    if not isinstance(errors, dict):
        errors = {}
    bucket = failure_bucket(error_text)
    errors[bucket] = int(errors.get(bucket, 0) or 0) + 1
    meta["errors"] = errors
    meta["last_error"] = error_text
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    by_hash[p_key] = meta
    candidate_failure_cache_dirty = True


row_by_hash = {}
item_by_hash = {}
claimed_payload_owner: dict[str, str] = {}
for idx, row in enumerate(plan_rows, start=1):
    h = str(row.get("hash", "")).lower()
    candidates = list(row.get("candidates", []))
    if not candidates and str(row.get("target_save_path", "")).strip().startswith("/"):
        candidates = [
            {
                "rank": 1,
                "path": str(row.get("target_save_path", "")).strip(),
                "payload_root": str(row.get("target_payload_root", "")).strip(),
                "score": int(row.get("best_score", 0) or 0),
                "reason": str(row.get("best_reason", "") or ""),
            }
        ]
    row["_idx"] = idx
    row["_hash"] = h
    row["_current_save"] = str(row.get("current_save_path", "") or "").strip()
    row["_candidates"] = candidates
    row["_next_candidate_idx"] = 0
    row_by_hash[h] = row

    first_target = str(candidates[0].get("path", "") if candidates else row.get("target_save_path", "")).strip()
    print(f"pilot_start idx={idx}/{len(plan_rows)} hash={h[:8]} current={row['_current_save']} target={first_target}")
    item_by_hash[h] = {
        "hash": h,
        "target_save_path": "",
        "target_payload_root": "",
        "status": "pending",
        "error": "",
        "candidate_rank_used": 0,
        "attempts": [],
        "elapsed_s": 0,
        "_idx": idx,
        "_started": time.monotonic(),
        "_deadline": time.monotonic() + item_max_s,
    }


def fail_attempt(h: str, attempt: dict, error_text: str, queue: deque[str]) -> None:
    row = row_by_hash[h]
    item = item_by_hash[h]
    rank = int(attempt.get("rank", 0) or 0)
    attempt["error"] = error_text
    attempt["elapsed_s"] = int(time.monotonic() - float(attempt.get("_started", time.monotonic())))
    record_candidate_failure(
        h,
        str(attempt.get("target_save_path", "") or ""),
        error_text,
    )
    claimed_root = str(attempt.get("_claimed_payload_root", "") or "").strip()
    if claimed_root and claimed_payload_owner.get(claimed_root) == h:
        claimed_payload_owner.pop(claimed_root, None)
    failure_buckets[failure_bucket(error_text)] += 1
    print(f"pilot_attempt_error hash={h[:8]} rank={rank} error={error_text}")
    try:
        qb.pause_torrent(h)
    except Exception:
        pass
    has_next = int(row.get("_next_candidate_idx", 0)) + 1 < len(row.get("_candidates", []))
    within_item_budget = time.monotonic() < float(item.get("_deadline", time.monotonic() + item_max_s))
    attempt_mode = str(attempt.get("mode", "move") or "move")
    if candidate_fallback_enabled and has_next and within_item_budget and should_try_next_candidate(
        error_text,
        attempt_mode,
    ):
        stats["fallback_used"] += 1
        attempt["status"] = "fallback"
        row["_next_candidate_idx"] = int(row.get("_next_candidate_idx", 0)) + 1
        print(
            f"pilot_fallback hash={h[:8]} from_rank={rank} "
            f"to_rank={int(row['_next_candidate_idx']) + 1} reason={error_text}"
        )
        queue.append(h)
    else:
        attempt["status"] = "error"
        item["status"] = "error"
        item["error"] = error_text
        item["target_save_path"] = str(attempt.get("target_save_path", "") or "")
        item["target_payload_root"] = str(attempt.get("target_payload_root", "") or "")
        item["elapsed_s"] = int(time.monotonic() - float(item.get("_started", time.monotonic())))
        stats["errors"] += 1
        print(f"pilot_error idx={item['_idx']}/{len(plan_rows)} hash={h[:8]} error={error_text}")
    item["attempts"].append(clean_attempt_output(attempt))


def ok_attempt(h: str, attempt: dict, final_state: str) -> None:
    item = item_by_hash[h]
    rank = int(attempt.get("rank", 0) or 0)
    attempt["status"] = "ok"
    attempt["final_state"] = final_state
    attempt["elapsed_s"] = int(time.monotonic() - float(attempt.get("_started", time.monotonic())))
    item["attempts"].append(clean_attempt_output(attempt))
    item["status"] = "ok"
    item["final_state"] = final_state
    item["target_save_path"] = str(attempt.get("target_save_path", "") or "")
    item["target_payload_root"] = str(attempt.get("target_payload_root", "") or "")
    item["candidate_rank_used"] = rank
    item["elapsed_s"] = int(time.monotonic() - float(item.get("_started", time.monotonic())))
    claimed_root = str(attempt.get("target_payload_root", "") or "").strip()
    if claimed_root:
        claimed_payload_owner[claimed_root] = h
    stats["ok"] += 1
    rank_histogram[str(rank)] += 1
    print(f"pilot_ok idx={item['_idx']}/{len(plan_rows)} hash={h[:8]} final_state={final_state} rank={rank}")


def batch_action(hashes: list[str], bulk_call, single_call, phase_name: str) -> tuple[set[str], dict[str, str]]:
    ok_hashes: set[str] = set()
    failures: dict[str, str] = {}
    if not hashes:
        return ok_hashes, failures
    if bulk_call(hashes):
        ok_hashes = set(hashes)
    else:
        print(
            f"pilot_batch phase={phase_name} bulk_failed requested={len(hashes)} "
            f"fallback=single"
        )
        for h in hashes:
            if single_call(h):
                ok_hashes.add(h)
            else:
                failures[h] = f"{phase_name}_failed"
    print(f"pilot_batch phase={phase_name} requested={len(hashes)} ok={len(ok_hashes)}")
    return ok_hashes, failures


queue: deque[str] = deque([str(row.get("hash", "")).lower() for row in plan_rows])
wave_no = 0

while queue:
    wave = []
    seen_wave = set()
    while queue and len(wave) < batch_size:
        h = queue.popleft()
        if not h or h in seen_wave:
            continue
        item = item_by_hash.get(h)
        if item is None or str(item.get("status", "")) in {"ok", "error"}:
            continue
        now = time.monotonic()
        if now >= float(item.get("_deadline", now + item_max_s)):
            item["status"] = "error"
            item["error"] = "item_budget_exceeded"
            item["elapsed_s"] = int(now - float(item.get("_started", now)))
            stats["errors"] += 1
            print(f"pilot_error idx={item['_idx']}/{len(plan_rows)} hash={h[:8]} error=item_budget_exceeded")
            continue
        wave.append(h)
        seen_wave.add(h)
    if not wave:
        continue

    wave_no += 1
    print(f"pilot_batch wave={wave_no} size={len(wave)}")

    attempts: dict[str, dict] = {}
    active_for_pause: list[str] = []
    for h in wave:
        row = row_by_hash[h]
        candidates = list(row.get("_candidates", []))
        attempt_idx = int(row.get("_next_candidate_idx", 0))
        if attempt_idx >= len(candidates):
            attempt = {
                "rank": attempt_idx + 1,
                "target_save_path": "",
                "target_payload_root": "",
                "status": "error",
                "error": "",
                "elapsed_s": 0,
                "_started": time.monotonic(),
                "_deadline": min(
                    float(item_by_hash[h].get("_deadline", time.monotonic() + item_max_s)),
                    time.monotonic() + candidate_max_s,
                ),
            }
            fail_attempt(h, attempt, "no_more_candidates", queue)
            continue

        candidate = candidates[attempt_idx]
        target = str(candidate.get("path", "")).strip()
        attempt = {
            "rank": attempt_idx + 1,
            "target_save_path": target,
            "target_payload_root": str(candidate.get("payload_root", "")).strip(),
            "mode": str(candidate.get("mode", "move") or "move"),
            "status": "error",
            "error": "",
            "elapsed_s": 0,
            "_started": time.monotonic(),
            "_deadline": min(
                float(item_by_hash[h].get("_deadline", time.monotonic() + item_max_s)),
                time.monotonic() + candidate_max_s,
            ),
        }
        attempts[h] = attempt
        print(
            f"pilot_attempt hash={h[:8]} rank={attempt['rank']}/{len(candidates)} "
            f"target={target} score={int(candidate.get('score', 0) or 0)} "
            f"mode={attempt['mode']}"
        )
        payload_root = str(attempt.get("target_payload_root", "") or "").strip()
        if payload_root:
            owner = claimed_payload_owner.get(payload_root)
            if owner and owner != h:
                fail_attempt(
                    h,
                    attempt,
                    f"conflict_target_payload_root_claimed:{owner[:8]}",
                    queue,
                )
                del attempts[h]
                continue
            claimed_payload_owner[payload_root] = h
            attempt["_claimed_payload_root"] = payload_root
        current_save = str(row.get("_current_save", "") or "")
        if not target.startswith("/"):
            fail_attempt(h, attempt, "invalid_target_path", queue)
            del attempts[h]
            continue
        active_for_pause.append(h)

    paused_ok, pause_failures = batch_action(
        active_for_pause,
        qb.pause_torrents,
        qb.pause_torrent,
        "pause",
    )
    for h, err in pause_failures.items():
        attempt = attempts.get(h)
        if attempt is not None:
            fail_attempt(h, attempt, err, queue)
            attempts.pop(h, None)
    for h in sorted(paused_ok, key=lambda x: item_by_hash[x]["_idx"]):
        print(f"pilot_step hash={h[:8]} phase=pause ok=1")

    ready_for_recheck = []
    moving_pending: dict[str, dict] = {}
    moved_info: dict[str, object] = {}
    for h in sorted(paused_ok, key=lambda x: item_by_hash[x]["_idx"]):
        if h not in attempts:
            continue
        target = str(attempts[h].get("target_save_path", "") or "")
        current_save = str(row_by_hash[h].get("_current_save", "") or "")
        attempt_mode = str(attempts[h].get("mode", "move") or "move")
        if attempt_mode == "recheck_only" or (current_save and current_save == target):
            attempts[h]["mode"] = "recheck_only"
            print(
                f"pilot_step hash={h[:8]} phase=set_location "
                "skipped=1 reason=target_equals_current_save_path"
            )
            ready_for_recheck.append(h)
            continue
        if not qb.set_location(h, target):
            fail_attempt(h, attempts[h], "set_location_failed", queue)
            attempts.pop(h, None)
            continue
        print(f"pilot_step hash={h[:8]} phase=set_location ok=1")
        moving_pending[h] = {
            "deadline": min(
                time.monotonic() + timeout_s,
                float(attempts[h].get("_deadline", time.monotonic() + candidate_max_s)),
            ),
            "last_hb": 0.0,
        }

    while moving_pending:
        now = time.monotonic()
        info_map = fetch_infos(list(moving_pending.keys()))
        for h in list(moving_pending.keys()):
            state = moving_pending[h]
            if now >= float(state["deadline"]):
                fail_attempt(h, attempts[h], "candidate_budget_exceeded:wait_moving_clear", queue)
                attempts.pop(h, None)
                moving_pending.pop(h, None)
                continue
            info = info_map.get(h)
            if info is None:
                fail_attempt(h, attempts[h], "missing_torrent_info", queue)
                attempts.pop(h, None)
                moving_pending.pop(h, None)
                continue
            st = state_lower(info)
            save_path = str(getattr(info, "save_path", "") or "")
            target = str(attempts[h].get("target_save_path", "") or "")
            if "moving" not in st and save_path == target:
                print(f"pilot_step hash={h[:8]} phase=wait_moving_clear ok=1")
                moved_info[h] = info
                moving_pending.pop(h, None)
                continue
            if now - float(state["last_hb"]) >= heartbeat_s:
                elapsed = int(now - float(item_by_hash[h].get("_started", now)))
                print(
                    f"pilot_wait hash={h[:8]} phase=wait_moving_clear state={st} "
                    f"save_path={save_path} elapsed_s={elapsed}"
                )
                state["last_hb"] = now
        if moving_pending:
            time.sleep(poll_s)

    for h, info in moved_info.items():
        if h not in attempts:
            continue
        target = str(attempts[h].get("target_save_path", "") or "")
        content_path_after_move = str(getattr(info, "content_path", "") or "")
        if content_path_after_move and not content_path_after_move.startswith(target):
            mismatch_error = f"content_path_mismatch_post_move:{content_path_after_move}"
            print(
                f"pilot_failfast hash={h[:8]} phase=post_move "
                f"content_path_mismatch content_path={content_path_after_move}"
            )
            fail_attempt(h, attempts[h], mismatch_error, queue)
            attempts.pop(h, None)
            continue
        ready_for_recheck.append(h)

    recheck_ok, recheck_failures = batch_action(
        ready_for_recheck,
        qb.recheck_torrents,
        qb.recheck_torrent,
        "recheck",
    )
    for h, err in recheck_failures.items():
        attempt = attempts.get(h)
        if attempt is not None:
            fail_attempt(h, attempt, err, queue)
            attempts.pop(h, None)
    for h in sorted(recheck_ok, key=lambda x: item_by_hash[x]["_idx"]):
        print(f"pilot_step hash={h[:8]} phase=recheck ok=1")

    terminal_pending: dict[str, dict] = {}
    stuck_window_s = max(30, heartbeat_s * 2)
    for h in recheck_ok:
        if h not in attempts:
            continue
        terminal_pending[h] = {
            "deadline": min(
                time.monotonic() + timeout_s,
                float(attempts[h].get("_deadline", time.monotonic() + candidate_max_s)),
            ),
            "last_hb": 0.0,
            "last_signature": None,
            "last_change": time.monotonic(),
            "recovery_attempted": False,
            "recovery_deadline": None,
        }

    terminal_ok = []
    while terminal_pending:
        now = time.monotonic()
        info_map = fetch_infos(list(terminal_pending.keys()))
        for h in list(terminal_pending.keys()):
            tstate = terminal_pending[h]
            if now >= float(tstate["deadline"]):
                fail_attempt(h, attempts[h], "candidate_budget_exceeded:wait_terminal", queue)
                attempts.pop(h, None)
                terminal_pending.pop(h, None)
                continue

            info = info_map.get(h)
            if info is None:
                fail_attempt(h, attempts[h], "missing_torrent_info", queue)
                attempts.pop(h, None)
                terminal_pending.pop(h, None)
                continue

            st = state_lower(info)
            progress = float(getattr(info, "progress", 0.0) or 0.0)
            amount_left = int(getattr(info, "amount_left", 0) or 0)
            signature = (st, round(progress, 4), amount_left)
            if signature != tstate["last_signature"]:
                tstate["last_signature"] = signature
                tstate["last_change"] = now

            if (
                progress >= 0.9999
                and amount_left == 0
                and not st.startswith("checking")
                and st not in {"downloading", "stalleddl", "moving", "missingfiles"}
            ):
                print(f"pilot_step hash={h[:8]} phase=wait_terminal ok=1")
                terminal_ok.append(h)
                terminal_pending.pop(h, None)
                continue

            if st in {"downloading", "stalleddl", "missingfiles"}:
                fail_attempt(h, attempts[h], f"bad_terminal_state:{st}", queue)
                attempts.pop(h, None)
                terminal_pending.pop(h, None)
                continue

            if st == "stoppeddl" and amount_left > 0 and (now - float(tstate["last_change"]) >= stuck_window_s):
                attempt_mode = str(attempts[h].get("mode", "move") or "move")
                if attempt_mode == "recheck_only":
                    fail_attempt(h, attempts[h], "recheck_only_stuck_terminal", queue)
                    attempts.pop(h, None)
                    terminal_pending.pop(h, None)
                    continue
                if tstate["recovery_deadline"] is not None and now >= float(tstate["recovery_deadline"]):
                    fail_attempt(h, attempts[h], "stuck_terminal_after_recovery", queue)
                    attempts.pop(h, None)
                    terminal_pending.pop(h, None)
                    continue
                if not bool(tstate["recovery_attempted"]):
                    elapsed = int(now - float(item_by_hash[h].get("_started", now)))
                    print(
                        f"pilot_step hash={h[:8]} phase=stuck_recovery "
                        f"action=resume_pause_recheck elapsed_s={elapsed}"
                    )
                    if not qb.resume_torrent(h):
                        fail_attempt(h, attempts[h], "stuck_recovery_resume_failed", queue)
                        attempts.pop(h, None)
                        terminal_pending.pop(h, None)
                        continue
                    time.sleep(min(2, poll_s))
                    if not qb.pause_torrent(h):
                        fail_attempt(h, attempts[h], "stuck_recovery_pause_failed", queue)
                        attempts.pop(h, None)
                        terminal_pending.pop(h, None)
                        continue
                    if not qb.recheck_torrent(h):
                        fail_attempt(h, attempts[h], "stuck_recovery_recheck_failed", queue)
                        attempts.pop(h, None)
                        terminal_pending.pop(h, None)
                        continue
                    tstate["recovery_attempted"] = True
                    tstate["recovery_deadline"] = now + stuck_window_s
                    tstate["last_signature"] = None
                    tstate["last_change"] = now
                    continue

            if now - float(tstate["last_hb"]) >= heartbeat_s:
                elapsed = int(now - float(item_by_hash[h].get("_started", now)))
                print(
                    f"pilot_wait hash={h[:8]} phase=wait_terminal state={st} "
                    f"progress={progress:.4f} left={amount_left} elapsed_s={elapsed}"
                )
                tstate["last_hb"] = now
        if terminal_pending:
            time.sleep(poll_s)

    final_pause_ok, final_pause_failures = batch_action(
        terminal_ok,
        qb.pause_torrents,
        qb.pause_torrent,
        "final_pause",
    )
    for h, err in final_pause_failures.items():
        attempt = attempts.get(h)
        if attempt is not None:
            fail_attempt(h, attempt, err, queue)
            attempts.pop(h, None)

    for h in sorted(final_pause_ok, key=lambda x: item_by_hash[x]["_idx"]):
        attempt = attempts.get(h)
        if attempt is None:
            continue
        final = qb.get_torrent_info(h)
        final_state = state_lower(final) if final is not None else "missing"
        if final_state != "stoppedup":
            if is_complete_payload_state(final):
                # Final pause can race with qB auto-management; treat complete seeding state as success.
                # stalledup is a valid seeding-ready terminal state and should be silent success.
                if final_state != "stalledup":
                    attempt["warning"] = f"final_state_nonpaused:{final_state}"
                    print(
                        f"pilot_warn hash={h[:8]} phase=final_verify "
                        f"nonpaused_complete_state={final_state}"
                    )
            else:
                retry_paused = qb.pause_torrent(h)
                if retry_paused:
                    final = qb.get_torrent_info(h)
                    final_state = state_lower(final) if final is not None else "missing"
                if final_state != "stoppedup" and not is_complete_payload_state(final):
                    fail_attempt(h, attempt, f"final_state_not_stoppedup:{final_state}", queue)
                    attempts.pop(h, None)
                    continue
                if final_state != "stoppedup":
                    if final_state != "stalledup":
                        attempt["warning"] = f"final_state_nonpaused:{final_state}"
                        print(
                            f"pilot_warn hash={h[:8]} phase=final_verify "
                            f"nonpaused_complete_state={final_state}"
                        )
        ok_attempt(h, attempt, final_state)
        attempts.pop(h, None)

for row in plan_rows:
    h = str(row.get("hash", "")).lower()
    item = item_by_hash[h]
    if str(item.get("status", "")) not in {"ok", "error"}:
        item["status"] = "error"
        item["error"] = "unfinished_attempt"
        item["elapsed_s"] = int(time.monotonic() - float(item.get("_started", time.monotonic())))
        stats["errors"] += 1
        print(f"pilot_error idx={item['_idx']}/{len(plan_rows)} hash={h[:8]} error=unfinished_attempt")
    item.pop("_started", None)
    item.pop("_idx", None)
    results.append(item)

ok = int(stats["ok"])
errors = int(stats["errors"])
fallback_used = int(stats["fallback_used"])

result_payload = {
    "summary": {
        "selected": len(plan_rows),
        "mode": mode,
        "ok": ok,
        "errors": errors,
        "selection_mode": effective_selection_mode,
        "batch_size": batch_size,
        "candidate_top_n": candidate_top_n,
        "candidate_fallback": int(candidate_fallback_enabled),
        "candidate_max_seconds": candidate_max_s,
        "item_max_seconds": item_max_s,
        "candidate_failure_cache_json": str(candidate_failure_cache_path) if candidate_failure_cache_path else "",
        "candidate_failure_cache_threshold": int(candidate_failure_cache_threshold),
        "candidate_failure_cache_skipped": int(cache_skipped_candidates),
        "fallback_used": int(fallback_used),
        "candidate_rank_histogram": dict(rank_histogram),
        "failure_buckets": dict(failure_buckets),
        "avg_elapsed_s": int(sum(int(r.get("elapsed_s", 0) or 0) for r in results) / max(1, len(results))),
    },
    "results": results,
}

if candidate_failure_cache_path:
    cache_payload = {
        "meta": {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "threshold": int(candidate_failure_cache_threshold),
        },
        "entries": candidate_failure_cache,
    }
    candidate_failure_cache_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_failure_cache_path.write_text(
        json.dumps(cache_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

result_json.write_text(json.dumps(result_payload, indent=2) + "\n", encoding="utf-8")
print(
    f"summary selected={len(plan_rows)} mode=apply ok={ok} errors={errors} "
    f"fallback_used={fallback_used} result_json={result_json}"
)
if errors:
    raise SystemExit(2)
PY

hr
echo "result=ok step=basics-qb-repair-pilot run_log=${run_log}"
echo "plan_json=${plan_json}"
echo "result_json=${result_json}"
hr
