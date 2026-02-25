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
  --poll-s N               Poll interval seconds (default: 2)
  --timeout-s N            Per-item timeout seconds (default: 1200)
  --heartbeat-s N          Heartbeat interval seconds (default: 10)
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

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MAPPING_JSON=""
BASELINE_JSON=""
MODE="${MODE:-dryrun}"
LIMIT="${LIMIT:-3}"
POLL_S="${POLL_S:-2}"
TIMEOUT_S="${TIMEOUT_S:-1200}"
HEARTBEAT_S="${HEARTBEAT_S:-10}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --poll-s) POLL_S="${2:-}"; shift 2 ;;
    --timeout-s) TIMEOUT_S="${2:-}"; shift 2 ;;
    --heartbeat-s) HEARTBEAT_S="${2:-}"; shift 2 ;;
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
for n in "$LIMIT" "$POLL_S" "$TIMEOUT_S" "$HEARTBEAT_S"; do
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "Numeric option required; got: $n" >&2
    exit 2
  fi
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
echo "run_id=${stamp} step=basics-qb-repair-pilot mode=${MODE} limit=${LIMIT} poll_s=${POLL_S} timeout_s=${TIMEOUT_S} heartbeat_s=${HEARTBEAT_S} mapping_json=${MAPPING_JSON} baseline_json=${BASELINE_JSON} fast=${FAST} debug=${DEBUG}"

PYTHONPATH=src \
PILOT_MAPPING_JSON="$MAPPING_JSON" \
PILOT_BASELINE_JSON="$BASELINE_JSON" \
PILOT_PLAN_JSON="$plan_json" \
PILOT_RESULT_JSON="$result_json" \
PILOT_LIMIT="$LIMIT" \
PILOT_MODE="$MODE" \
PILOT_POLL_S="$POLL_S" \
PILOT_TIMEOUT_S="$TIMEOUT_S" \
PILOT_HEARTBEAT_S="$HEARTBEAT_S" \
python -u - <<'PY'
import json
import os
import time
from pathlib import Path
import glob

from hashall.qbittorrent import get_qbittorrent_client

mapping_json = Path(os.environ["PILOT_MAPPING_JSON"])
baseline_json = Path(os.environ["PILOT_BASELINE_JSON"])
plan_json = Path(os.environ["PILOT_PLAN_JSON"])
result_json = Path(os.environ["PILOT_RESULT_JSON"])
limit = int(os.environ.get("PILOT_LIMIT", "3") or 3)
mode = os.environ.get("PILOT_MODE", "dryrun").strip().lower()
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

qb = get_qbittorrent_client()
if not qb.test_connection() or not qb.login():
    qb = None

eligible = []
rejected = []
for e in confident:
    h = str(e.get("hash", "")).lower()
    target = str(e.get("best_candidate", "") or "").strip()
    current_save = str(e.get("_save_path", "") or "").strip()
    recoverable = bool(e.get("recoverable", False))
    same_path = bool(target and current_save and target == current_save)
    best_evidence = list(e.get("best_evidence", []) or [])
    best_expected = list(e.get("best_expected_matches", []) or [])
    evidence = sorted({str(x) for x in (best_evidence + best_expected) if str(x).strip()})

    reasons = []
    if not target.startswith("/"):
        reasons.append("invalid_target_path")
    if same_path:
        reasons.append("target_equals_current_save_path")
    if not recoverable:
        reasons.append("mapping_not_recoverable")
    if not evidence:
        reasons.append("missing_recoverability_evidence")
    if qb is not None and target:
        info = qb.get_torrent_info(h)
        if info is not None:
            live_state = (getattr(info, "state", "") or "").lower()
            live_save = str(getattr(info, "save_path", "") or "").strip()
            if live_state == "stoppedup" and live_save == target:
                reasons.append("already_normalized_stoppedup_same_path")
            elif h in handled_stoppedup and live_save == target:
                reasons.append("already_normalized_stoppedup_same_path")

    if reasons:
        rejected.append(
            {
                "hash": h,
                "name": str(e.get("_name", "")),
                "state": str(e.get("_state", "")),
                "current_save_path": current_save,
                "target_save_path": target,
                "reason": ",".join(reasons),
            }
        )
        continue

    e["_best_evidence"] = evidence
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
    plan_rows.append(
        {
            "hash": str(e.get("hash", "")).lower(),
            "name": str(e.get("_name", "")),
            "size": int(e.get("_size", 0)),
            "state": str(e.get("_state", "")),
            "current_save_path": str(e.get("_save_path", "")),
            "target_save_path": str(e.get("best_candidate", "")),
            "best_reason": str(e.get("best_reason", "")),
            "best_score": int(e.get("best_score", 0) or 0),
            "best_evidence": list(e.get("_best_evidence", [])),
        }
    )

plan_payload = {
    "summary": {
        "selected": len(plan_rows),
        "mode": mode,
        "eligible": len(eligible),
        "rejected": len(rejected),
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

if not apply_mode:
    result_payload = {"summary": {"selected": len(plan_rows), "mode": mode, "ok": 0, "errors": 0}, "results": []}
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

def state_lower(info):
    return str(getattr(info, "state", "") or "").lower()

for idx, row in enumerate(plan_rows, start=1):
    h = row["hash"]
    target = str(row["target_save_path"] or "").strip()
    current_save = str(row.get("current_save_path", "") or "").strip()
    item = {"hash": h, "target_save_path": target, "status": "error", "error": "", "elapsed_s": 0}
    start = time.monotonic()
    print(f"pilot_start idx={idx}/{len(plan_rows)} hash={h[:8]} current={current_save} target={target}")
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
            print(
                f"pilot_warn hash={h[:8]} phase=wait_moving_clear "
                f"content_path_mismatch content_path={content_path_after_move}"
            )

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

            # qB can accept setLocation+recheck but remain stuck in stoppedDL with unchanged totals.
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

        item["status"] = "ok"
        item["final_state"] = final_state
        ok += 1
        print(f"pilot_ok idx={idx}/{len(plan_rows)} hash={h[:8]} final_state={final_state}")
    except Exception as exc:
        item["error"] = str(exc)
        errors += 1
        print(f"pilot_error idx={idx}/{len(plan_rows)} hash={h[:8]} error={exc}")
        try:
            qb.pause_torrent(h)
        except Exception:
            pass
    finally:
        item["elapsed_s"] = int(time.monotonic() - start)
        results.append(item)

result_payload = {
    "summary": {"selected": len(plan_rows), "mode": mode, "ok": ok, "errors": errors},
    "results": results,
}
result_json.write_text(json.dumps(result_payload, indent=2) + "\n", encoding="utf-8")
print(f"summary selected={len(plan_rows)} mode=apply ok={ok} errors={errors} result_json={result_json}")
if errors:
    raise SystemExit(2)
PY

hr
echo "result=ok step=basics-qb-repair-pilot run_log=${run_log}"
echo "plan_json=${plan_json}"
echo "result_json=${result_json}"
hr
