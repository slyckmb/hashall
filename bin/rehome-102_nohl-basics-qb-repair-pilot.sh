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
  --candidate-top-n N      Candidate attempts per hash (default: 1)
  --candidate-fallback     Try next-ranked candidate when candidate-sensitive failures occur
  --poll-s N               Poll interval seconds (default: 2)
  --timeout-s N            Per-item timeout seconds (default: 1200)
  --heartbeat-s N          Heartbeat interval seconds (default: 10)
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
CANDIDATE_TOP_N="${CANDIDATE_TOP_N:-1}"
CANDIDATE_FALLBACK="${CANDIDATE_FALLBACK:-0}"
POLL_S="${POLL_S:-2}"
TIMEOUT_S="${TIMEOUT_S:-1200}"
HEARTBEAT_S="${HEARTBEAT_S:-10}"
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
    --candidate-top-n) CANDIDATE_TOP_N="${2:-}"; shift 2 ;;
    --candidate-fallback) CANDIDATE_FALLBACK=1; shift ;;
    --no-candidate-fallback) CANDIDATE_FALLBACK=0; shift ;;
    --poll-s) POLL_S="${2:-}"; shift 2 ;;
    --timeout-s) TIMEOUT_S="${2:-}"; shift 2 ;;
    --heartbeat-s) HEARTBEAT_S="${2:-}"; shift 2 ;;
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
for n in "$LIMIT" "$CANDIDATE_TOP_N" "$POLL_S" "$TIMEOUT_S" "$HEARTBEAT_S"; do
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
done
if [[ "$CANDIDATE_TOP_N" -lt 1 ]]; then
  echo "--candidate-top-n must be >=1" >&2
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
echo "run_id=${stamp} step=basics-qb-repair-pilot mode=${MODE} limit=${LIMIT} candidate_top_n=${CANDIDATE_TOP_N} candidate_fallback=${CANDIDATE_FALLBACK} poll_s=${POLL_S} timeout_s=${TIMEOUT_S} heartbeat_s=${HEARTBEAT_S} mapping_json=${MAPPING_JSON} baseline_json=${BASELINE_JSON} ownership_audit_json=${OWNERSHIP_AUDIT_JSON:-none} allow_ownership_conflicts=${ALLOW_OWNERSHIP_CONFLICTS} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
PILOT_MAPPING_JSON="$MAPPING_JSON" \
PILOT_BASELINE_JSON="$BASELINE_JSON" \
PILOT_PLAN_JSON="$plan_json" \
PILOT_RESULT_JSON="$result_json" \
PILOT_LIMIT="$LIMIT" \
PILOT_MODE="$MODE" \
PILOT_CANDIDATE_TOP_N="$CANDIDATE_TOP_N" \
PILOT_CANDIDATE_FALLBACK="$CANDIDATE_FALLBACK" \
PILOT_POLL_S="$POLL_S" \
PILOT_TIMEOUT_S="$TIMEOUT_S" \
PILOT_HEARTBEAT_S="$HEARTBEAT_S" \
python -u - <<'PY'
import glob
import json
import os
import time
from collections import Counter
from pathlib import Path

from hashall.qbittorrent import get_qbittorrent_client

mapping_json = Path(os.environ["PILOT_MAPPING_JSON"])
baseline_json = Path(os.environ["PILOT_BASELINE_JSON"])
plan_json = Path(os.environ["PILOT_PLAN_JSON"])
result_json = Path(os.environ["PILOT_RESULT_JSON"])
limit = int(os.environ.get("PILOT_LIMIT", "3") or 3)
mode = os.environ.get("PILOT_MODE", "dryrun").strip().lower()
candidate_top_n = max(1, int(os.environ.get("PILOT_CANDIDATE_TOP_N", "1") or 1))
candidate_fallback_enabled = os.environ.get("PILOT_CANDIDATE_FALLBACK", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
poll_s = max(1, int(os.environ.get("PILOT_POLL_S", "2") or 2))
timeout_s = max(60, int(os.environ.get("PILOT_TIMEOUT_S", "1200") or 1200))
heartbeat_s = max(5, int(os.environ.get("PILOT_HEARTBEAT_S", "10") or 10))
apply_mode = mode == "apply"

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
    for cand in candidate_rows:
        cpath = str(cand.get("path", "")).strip()
        if not cpath.startswith("/"):
            continue
        if current_save and cpath == current_save:
            continue
        if not Path(cpath).exists():
            continue
        valid_candidates.append(cand)
    if not valid_candidates:
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
        "candidate_top_n": candidate_top_n,
        "candidate_fallback": int(candidate_fallback_enabled),
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
            "candidate_top_n": candidate_top_n,
            "candidate_fallback": int(candidate_fallback_enabled),
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
ok = 0
errors = 0
fallback_used = 0
rank_histogram = Counter()
failure_buckets = Counter()

def state_lower(info):
    return str(getattr(info, "state", "") or "").lower()

def should_try_next_candidate(error_text: str) -> bool:
    return (
        error_text.startswith("content_path_mismatch_post_move:")
        or error_text.startswith("bad_terminal_state:")
        or error_text.startswith("stuck_terminal_after_recovery")
        or error_text.startswith("timeout_wait_terminal")
        or error_text.startswith("final_state_not_stoppedup:")
    )


def failure_bucket(error_text: str) -> str:
    if error_text.startswith("bad_terminal_state:"):
        return error_text
    if error_text.startswith("content_path_mismatch_post_move:"):
        return "content_path_mismatch_post_move"
    return error_text.split(":", 1)[0]


for idx, row in enumerate(plan_rows, start=1):
    h = row["hash"]
    current_save = str(row.get("current_save_path", "") or "").strip()
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
    first_target = str(candidates[0].get("path", "") if candidates else row.get("target_save_path", "")).strip()
    item = {
        "hash": h,
        "target_save_path": "",
        "target_payload_root": "",
        "status": "error",
        "error": "",
        "candidate_rank_used": 0,
        "attempts": [],
        "elapsed_s": 0,
    }
    start = time.monotonic()
    print(f"pilot_start idx={idx}/{len(plan_rows)} hash={h[:8]} current={current_save} target={first_target}")
    for attempt_idx, candidate in enumerate(candidates, start=1):
        target = str(candidate.get("path", "")).strip()
        attempt = {
            "rank": attempt_idx,
            "target_save_path": target,
            "target_payload_root": str(candidate.get("payload_root", "")).strip(),
            "status": "error",
            "error": "",
            "elapsed_s": 0,
        }
        attempt_start = time.monotonic()
        print(
            f"pilot_attempt hash={h[:8]} rank={attempt_idx}/{len(candidates)} "
            f"target={target} score={int(candidate.get('score', 0) or 0)}"
        )
        try:
            if not target.startswith("/"):
                raise RuntimeError("invalid_target_path")
            if current_save and current_save == target:
                raise RuntimeError("preflight_target_equals_current_save_path")

            if not qb.pause_torrent(h):
                raise RuntimeError("pause_failed")
            print(f"pilot_step hash={h[:8]} phase=pause ok=1")

            if not qb.set_location(h, target):
                raise RuntimeError("set_location_failed")
            print(f"pilot_step hash={h[:8]} phase=set_location ok=1")

            deadline = time.monotonic() + timeout_s
            last_hb = 0.0
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError("timeout_wait_moving_clear")
                info = qb.get_torrent_info(h)
                if info is None:
                    raise RuntimeError("missing_torrent_info")
                st = state_lower(info)
                save_path = str(getattr(info, "save_path", "") or "")
                if "moving" not in st and save_path == target:
                    break
                if now - last_hb >= heartbeat_s:
                    print(
                        f"pilot_wait hash={h[:8]} phase=wait_moving_clear state={st} "
                        f"save_path={save_path} elapsed_s={int(now - start)}"
                    )
                    last_hb = now
                time.sleep(poll_s)
            print(f"pilot_step hash={h[:8]} phase=wait_moving_clear ok=1")
            content_path_after_move = str(getattr(info, "content_path", "") or "")
            if content_path_after_move and not content_path_after_move.startswith(target):
                raise RuntimeError(f"content_path_mismatch_post_move:{content_path_after_move}")

            if not qb.recheck_torrent(h):
                raise RuntimeError("recheck_failed")
            print(f"pilot_step hash={h[:8]} phase=recheck ok=1")

            deadline = time.monotonic() + timeout_s
            last_hb = 0.0
            stuck_window_s = max(45, heartbeat_s * 3)
            recovery_attempted = False
            recovery_deadline = None
            last_terminal_signature = None
            last_terminal_change = time.monotonic()
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError("timeout_wait_terminal")
                info = qb.get_torrent_info(h)
                if info is None:
                    raise RuntimeError("missing_torrent_info")
                st = state_lower(info)
                progress = float(getattr(info, "progress", 0.0) or 0.0)
                amount_left = int(getattr(info, "amount_left", 0) or 0)
                terminal_signature = (st, round(progress, 4), amount_left)
                if terminal_signature != last_terminal_signature:
                    last_terminal_signature = terminal_signature
                    last_terminal_change = now
                if progress >= 0.9999 and amount_left == 0 and not st.startswith("checking") and st not in {"downloading", "stalleddl", "moving", "missingfiles"}:
                    break
                if st in {"downloading", "stalleddl", "missingfiles"}:
                    raise RuntimeError(f"bad_terminal_state:{st}")

                if st == "stoppeddl" and amount_left > 0 and (now - last_terminal_change >= stuck_window_s):
                    if recovery_deadline is not None and now >= recovery_deadline:
                        raise RuntimeError("stuck_terminal_after_recovery")
                    if not recovery_attempted:
                        print(
                            f"pilot_step hash={h[:8]} phase=stuck_recovery "
                            f"action=resume_pause_recheck elapsed_s={int(now - start)}"
                        )
                        if not qb.resume_torrent(h):
                            raise RuntimeError("stuck_recovery_resume_failed")
                        time.sleep(min(2, poll_s))
                        if not qb.pause_torrent(h):
                            raise RuntimeError("stuck_recovery_pause_failed")
                        if not qb.recheck_torrent(h):
                            raise RuntimeError("stuck_recovery_recheck_failed")
                        recovery_attempted = True
                        recovery_deadline = now + stuck_window_s
                        last_terminal_signature = None
                        last_terminal_change = now
                        continue

                if now - last_hb >= heartbeat_s:
                    print(
                        f"pilot_wait hash={h[:8]} phase=wait_terminal state={st} "
                        f"progress={progress:.4f} left={amount_left} elapsed_s={int(now - start)}"
                    )
                    last_hb = now
                time.sleep(poll_s)
            print(f"pilot_step hash={h[:8]} phase=wait_terminal ok=1")

            if not qb.pause_torrent(h):
                raise RuntimeError("final_pause_failed")
            final = qb.get_torrent_info(h)
            final_state = state_lower(final) if final is not None else "missing"
            if final_state != "stoppedup":
                raise RuntimeError(f"final_state_not_stoppedup:{final_state}")

            attempt["status"] = "ok"
            attempt["final_state"] = final_state
            item["status"] = "ok"
            item["final_state"] = final_state
            item["target_save_path"] = target
            item["target_payload_root"] = attempt["target_payload_root"]
            item["candidate_rank_used"] = attempt_idx
            rank_histogram[str(attempt_idx)] += 1
            ok += 1
            print(f"pilot_ok idx={idx}/{len(plan_rows)} hash={h[:8]} final_state={final_state} rank={attempt_idx}")
            break
        except Exception as exc:
            error_text = str(exc)
            attempt["error"] = error_text
            failure_buckets[failure_bucket(error_text)] += 1
            print(f"pilot_attempt_error hash={h[:8]} rank={attempt_idx} error={error_text}")
            try:
                qb.pause_torrent(h)
            except Exception:
                pass
            has_next = attempt_idx < len(candidates)
            if candidate_fallback_enabled and has_next and should_try_next_candidate(error_text):
                fallback_used += 1
                print(
                    f"pilot_fallback hash={h[:8]} from_rank={attempt_idx} "
                    f"to_rank={attempt_idx + 1} reason={error_text}"
                )
                attempt["status"] = "fallback"
            else:
                item["error"] = error_text
                item["target_save_path"] = target
                item["target_payload_root"] = attempt["target_payload_root"]
                break
        finally:
            attempt["elapsed_s"] = int(time.monotonic() - attempt_start)
            item["attempts"].append(attempt)

    if item["status"] != "ok":
        errors += 1
        print(f"pilot_error idx={idx}/{len(plan_rows)} hash={h[:8]} error={item.get('error', 'unknown')}")
        try:
            qb.pause_torrent(h)
        except Exception:
            pass
    item["elapsed_s"] = int(time.monotonic() - start)
    results.append(item)

result_payload = {
    "summary": {
        "selected": len(plan_rows),
        "mode": mode,
        "ok": ok,
        "errors": errors,
        "candidate_top_n": candidate_top_n,
        "candidate_fallback": int(candidate_fallback_enabled),
        "fallback_used": int(fallback_used),
        "candidate_rank_histogram": dict(rank_histogram),
        "failure_buckets": dict(failure_buckets),
        "avg_elapsed_s": int(sum(int(r.get("elapsed_s", 0) or 0) for r in results) / max(1, len(results))),
    },
    "results": results,
}
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
