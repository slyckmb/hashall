#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-57_qb-missing-remediate.sh [options]

Options:
  --plan PATH               Remediation plan JSON (default: latest nohl-qb-missing-remediate-plan-*.json)
  --mode dryrun|apply       Execution mode (default: dryrun)
  --limit N                 Limit actions processed (default: 0 = all)
  --only-reason NAME        Filter actions by reason (repeatable)
  --resume 0|1              Resume torrents after remediation (default: 0)
  --max-apply-actions N     Safety cap for apply mode (default: 50)
  --force-large-apply       Override max-apply-actions safety cap
  --heartbeat-s N           Heartbeat interval seconds (default: 5)
  --poll-s N                Poll interval seconds (default: 2)
  --timeout-s N             Per-item verification timeout seconds (default: 60)
  --output-prefix NAME      Output prefix (default: nohl)
  --fast                    Fast mode annotation
  --debug                   Debug mode annotation
  -h, --help                Show help
USAGE
}

latest_plan() {
  local prefix="$1"
  ls -1t "out/reports/rehome-normalize/${prefix}-qb-missing-remediate-plan-"*.json 2>/dev/null | head -n1 || true
}

PLAN_JSON=""
MODE="dryrun"
LIMIT="0"
HEARTBEAT_S="5"
POLL_S="2"
TIMEOUT_S="60"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0
RESUME_AFTER_VERIFY="${REMEDIATE_RESUME_AFTER_VERIFY:-0}"
MAX_APPLY_ACTIONS="${REMEDIATE_MAX_APPLY_ACTIONS:-50}"
FORCE_LARGE_APPLY=0
ONLY_REASONS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) PLAN_JSON="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --only-reason) ONLY_REASONS+=("${2:-}"); shift 2 ;;
    --resume) RESUME_AFTER_VERIFY="${2:-}"; shift 2 ;;
    --max-apply-actions) MAX_APPLY_ACTIONS="${2:-}"; shift 2 ;;
    --force-large-apply) FORCE_LARGE_APPLY=1; shift ;;
    --heartbeat-s) HEARTBEAT_S="${2:-}"; shift 2 ;;
    --poll-s) POLL_S="${2:-}"; shift 2 ;;
    --timeout-s) TIMEOUT_S="${2:-}"; shift 2 ;;
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

if [[ "$MODE" != "dryrun" && "$MODE" != "apply" ]]; then
  echo "Invalid --mode value: $MODE (expected dryrun|apply)" >&2
  exit 2
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit value: $LIMIT" >&2
  exit 2
fi
if ! [[ "$HEARTBEAT_S" =~ ^[0-9]+$ ]] || [[ "$HEARTBEAT_S" -lt 1 ]]; then
  echo "Invalid --heartbeat-s value: $HEARTBEAT_S" >&2
  exit 2
fi
if ! [[ "$POLL_S" =~ ^[0-9]+$ ]] || [[ "$POLL_S" -lt 1 ]]; then
  echo "Invalid --poll-s value: $POLL_S" >&2
  exit 2
fi
if ! [[ "$TIMEOUT_S" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_S" -lt 1 ]]; then
  echo "Invalid --timeout-s value: $TIMEOUT_S" >&2
  exit 2
fi
if [[ "$RESUME_AFTER_VERIFY" != "0" && "$RESUME_AFTER_VERIFY" != "1" ]]; then
  echo "Invalid --resume value: $RESUME_AFTER_VERIFY" >&2
  exit 2
fi
if ! [[ "$MAX_APPLY_ACTIONS" =~ ^[0-9]+$ ]]; then
  echo "Invalid --max-apply-actions value: $MAX_APPLY_ACTIONS" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "$PLAN_JSON" ]]; then
  PLAN_JSON="$(latest_plan "$OUTPUT_PREFIX")"
fi
if [[ -z "$PLAN_JSON" || ! -f "$PLAN_JSON" ]]; then
  echo "Missing remediation plan; run rehome-56 first or pass --plan" >&2
  exit 3
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-qb-missing-remediate-${stamp}.log"
result_json="${log_dir}/${OUTPUT_PREFIX}-qb-missing-remediate-${stamp}.json"
ok_hashes="${log_dir}/${OUTPUT_PREFIX}-qb-missing-remediate-ok-${stamp}.txt"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-qb-missing-remediate-failed-${stamp}.txt"

if [[ "$DEBUG_MODE" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi

ONLY_REASONS_CSV=""
if [[ "${#ONLY_REASONS[@]}" -gt 0 ]]; then
  ONLY_REASONS_CSV="$(IFS=,; echo "${ONLY_REASONS[*]}")"
fi

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 57: qB missingFiles remediation"
echo "What this does: execute setLocation fixes from the remediation plan."
hr
echo "run_id=${stamp} step=qb-missing-remediate"
echo "config plan=${PLAN_JSON} mode=${MODE} limit=${LIMIT} resume=${RESUME_AFTER_VERIFY} max_apply_actions=${MAX_APPLY_ACTIONS} force_large_apply=${FORCE_LARGE_APPLY} heartbeat_s=${HEARTBEAT_S} poll_s=${POLL_S} timeout_s=${TIMEOUT_S} only_reasons=${ONLY_REASONS_CSV:-all} fast=${FAST_MODE} debug=${DEBUG_MODE}"

PYTHONPATH=src \
REMEDIATE_PLAN_JSON="$PLAN_JSON" \
REMEDIATE_MODE="$MODE" \
REMEDIATE_LIMIT="$LIMIT" \
REMEDIATE_ONLY_REASONS="$ONLY_REASONS_CSV" \
REMEDIATE_RESUME_AFTER_VERIFY="$RESUME_AFTER_VERIFY" \
REMEDIATE_MAX_APPLY_ACTIONS="$MAX_APPLY_ACTIONS" \
REMEDIATE_FORCE_LARGE_APPLY="$FORCE_LARGE_APPLY" \
REMEDIATE_HEARTBEAT_S="$HEARTBEAT_S" \
REMEDIATE_POLL_S="$POLL_S" \
REMEDIATE_TIMEOUT_S="$TIMEOUT_S" \
REMEDIATE_RESULT_JSON="$result_json" \
REMEDIATE_OK_HASHES="$ok_hashes" \
REMEDIATE_FAILED_HASHES="$failed_hashes" \
python - <<'PY'
import json
import os
import time
from datetime import datetime
from pathlib import Path

from hashall.qbittorrent import get_qbittorrent_client


def _norm(path: str) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(Path(path))


plan_path = Path(os.environ["REMEDIATE_PLAN_JSON"])
mode = os.environ.get("REMEDIATE_MODE", "dryrun")
limit = int(os.environ.get("REMEDIATE_LIMIT", "0") or 0)
resume_after_verify = os.environ.get("REMEDIATE_RESUME_AFTER_VERIFY", "0").strip() == "1"
max_apply_actions = int(os.environ.get("REMEDIATE_MAX_APPLY_ACTIONS", "50") or 50)
force_large_apply = os.environ.get("REMEDIATE_FORCE_LARGE_APPLY", "0").strip() == "1"
only_reasons = {
    item.strip()
    for item in os.environ.get("REMEDIATE_ONLY_REASONS", "").split(",")
    if item.strip()
}
heartbeat_s = int(os.environ.get("REMEDIATE_HEARTBEAT_S", "5") or 5)
poll_s = int(os.environ.get("REMEDIATE_POLL_S", "2") or 2)
timeout_s = int(os.environ.get("REMEDIATE_TIMEOUT_S", "60") or 60)
result_json = Path(os.environ["REMEDIATE_RESULT_JSON"])
ok_hashes_path = Path(os.environ["REMEDIATE_OK_HASHES"])
failed_hashes_path = Path(os.environ["REMEDIATE_FAILED_HASHES"])

plan = json.loads(plan_path.read_text(encoding="utf-8"))
actions = list(plan.get("actions", []))
if only_reasons:
    actions = [a for a in actions if str(a.get("reason") or "") in only_reasons]
if limit > 0:
    actions = actions[:limit]

print(f"actions_selected={len(actions)}")
if mode == "apply" and max_apply_actions > 0 and len(actions) > max_apply_actions and not force_large_apply:
    print(
        "guardrail_blocked "
        f"reason=too_many_apply_actions selected={len(actions)} "
        f"max_apply_actions={max_apply_actions} override=--force-large-apply"
    )
    raise SystemExit(4)
if actions:
    reason_counts = {}
    for action in actions:
        reason = str(action.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, total in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"reason_count reason={reason} total={total}")

results = []
ok_hashes = []
failed_hashes = []
resumed_count = 0
held_paused_count = 0

qb = None
if mode == "apply":
    qb = get_qbittorrent_client(
        base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
        username=os.getenv("QBIT_USER", "admin"),
        password=os.getenv("QBIT_PASS", "adminpass"),
    )

total = len(actions)
for idx, action in enumerate(actions, start=1):
    torrent_hash = str(action.get("torrent_hash", "")).lower()
    from_save = str(action.get("current_save_path", ""))
    to_save = str(action.get("target_save_path", ""))
    reason = str(action.get("reason", ""))
    confidence = float(action.get("confidence", 0.0) or 0.0)
    status = "dryrun"
    waited_s = 0
    error = ""
    verified = False

    print(
        f"item idx={idx}/{total} hash={torrent_hash[:16]} reason={reason} "
        f"confidence={confidence:.2f} from={from_save} to={to_save} mode={mode}"
    )

    if mode == "dryrun":
        results.append(
            {
                "torrent_hash": torrent_hash,
                "status": status,
                "reason": reason,
                "from_save_path": from_save,
                "target_save_path": to_save,
                "confidence": confidence,
            }
        )
        continue

    start = time.monotonic()
    paused = False
    try:
        if not qb.pause_torrent(torrent_hash):
            raise RuntimeError("pause_failed")
        paused = True
        if not qb.set_location(torrent_hash, to_save):
            raise RuntimeError("set_location_failed")

        expected = _norm(to_save)
        deadline = time.monotonic() + timeout_s
        next_heartbeat = time.monotonic() + heartbeat_s
        while time.monotonic() <= deadline:
            info = qb.get_torrent_info(torrent_hash)
            actual = _norm(str(getattr(info, "save_path", ""))) if info else ""
            if actual == expected:
                verified = True
                break
            now = time.monotonic()
            if now >= next_heartbeat:
                waited = int(now - start)
                print(
                    f"heartbeat idx={idx}/{total} hash={torrent_hash[:16]} "
                    f"waited_s={waited} expected={expected} actual={actual or 'unknown'}"
                )
                next_heartbeat = now + heartbeat_s
            time.sleep(poll_s)

        if not verified:
            raise RuntimeError("verify_timeout")
        status = "ok"
        ok_hashes.append(torrent_hash)
    except Exception as exc:
        status = "error"
        error = str(exc)
        failed_hashes.append(torrent_hash)
    finally:
        waited_s = int(time.monotonic() - start)
        if paused and resume_after_verify:
            if not qb.resume_torrent(torrent_hash):
                if status == "ok":
                    status = "error"
                    error = "resume_failed"
                elif error:
                    error = f"{error};resume_failed"
                else:
                    error = "resume_failed"
            else:
                resumed_count += 1
        elif paused:
            held_paused_count += 1

    print(
        f"result idx={idx}/{total} hash={torrent_hash[:16]} status={status} "
        f"waited_s={waited_s} error={error or 'none'}"
    )
    results.append(
        {
            "torrent_hash": torrent_hash,
            "status": status,
            "reason": reason,
            "from_save_path": from_save,
            "target_save_path": to_save,
            "confidence": confidence,
            "waited_s": waited_s,
            "verified": verified,
            "error": error or None,
        }
    )

summary = {
    "mode": mode,
    "selected_actions": total,
    "ok": sum(1 for r in results if r.get("status") == "ok"),
    "errors": sum(1 for r in results if r.get("status") == "error"),
    "dryrun": sum(1 for r in results if r.get("status") == "dryrun"),
    "resumed": resumed_count,
    "held_paused": held_paused_count,
}

result_obj = {
    "generated_at": datetime.now().isoformat(),
    "plan_path": str(plan_path),
    "summary": summary,
    "results": results,
}

result_json.write_text(json.dumps(result_obj, indent=2) + "\n", encoding="utf-8")
ok_hashes_path.write_text("\n".join(ok_hashes) + ("\n" if ok_hashes else ""), encoding="utf-8")
failed_hashes_path.write_text("\n".join(failed_hashes) + ("\n" if failed_hashes else ""), encoding="utf-8")

print(
    f"summary selected={summary['selected_actions']} ok={summary['ok']} "
    f"errors={summary['errors']} dryrun={summary['dryrun']} "
    f"resumed={summary['resumed']} held_paused={summary['held_paused']}"
)
print(f"result_json={result_json}")
print(f"ok_hashes={ok_hashes_path}")
print(f"failed_hashes={failed_hashes_path}")

if mode == "apply" and summary["errors"] > 0:
    raise SystemExit(1)
PY

hr
echo "Phase 57 complete: remediation run finished."
hr
echo "run_log=${run_log}"
echo "result_json=${result_json}"
echo "ok_hashes=${ok_hashes}"
echo "failed_hashes=${failed_hashes}"
