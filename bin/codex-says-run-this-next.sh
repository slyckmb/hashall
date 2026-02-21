#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/codex-says-run-this-next.sh [options]

Options:
  --min-free-pct N         Override pool minimum free percent for nohl-restart mode
                           (sets REHOME_NOHL_MIN_FREE_PCT for this invocation).
  REHOME_PROCESS_MODE=nohl-missing-recheck
                           Print/run missing-torrent recheck workflow commands.
  -h, --help               Show this help.
USAGE
}

CLI_NOHL_MIN_FREE_PCT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --min-free-pct|--pool-min-free-pct)
      CLI_NOHL_MIN_FREE_PCT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$CLI_NOHL_MIN_FREE_PCT" ]]; then
  if ! [[ "$CLI_NOHL_MIN_FREE_PCT" =~ ^[0-9]+$ ]]; then
    echo "Invalid --min-free-pct value: $CLI_NOHL_MIN_FREE_PCT" >&2
    exit 2
  fi
  export REHOME_NOHL_MIN_FREE_PCT="$CLI_NOHL_MIN_FREE_PCT"
fi

stamp="$(date +%Y%m%d-%H%M%S)"
run_log="out/reports/rehome-normalize/codex-says-run-this-next-${stamp}.log"
mkdir -p out/reports/rehome-normalize
exec > >(tee -a "$run_log") 2>&1

resolve_latest_plan() {
  ls -1t out/reports/rehome-normalize/rehome-plan-normalize-*.json rehome-plan-normalize-*.json 2>/dev/null | head -n1
}

print_plan_summary() {
  local plan="$1"
  echo "USING_PLAN=$plan"
  jq -r '.summary' "$plan"
  jq -r '.plans | length as $n | "plan_count=\($n)"' "$plan"
}

sanitize_plan_live_torrents() {
  local input_plan="$1"
  local output_plan="$2"
  PYTHONPATH=src INPUT_PLAN="$input_plan" OUTPUT_PLAN="$output_plan" python - <<'PY'
import json
import os
from pathlib import Path
from collections import Counter
from hashall.qbittorrent import QBittorrentClient

in_path = Path(os.environ["INPUT_PLAN"])
out_path = Path(os.environ["OUTPUT_PLAN"])
data = json.loads(in_path.read_text())

qb = QBittorrentClient(
    base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
    username=os.getenv("QBIT_USER", "admin"),
    password=os.getenv("QBIT_PASS", "adminpass"),
)
live_filter_enabled = os.getenv("REHOME_SANITIZE_LIVE", "0").strip().lower() in {"1", "true", "yes", "on"}
live = set()
if live_filter_enabled:
    torrents = qb.get_torrents()
    live = {t.hash.lower() for t in torrents}
files_ok = {}

def hash_has_files(h: str) -> bool:
    if not live_filter_enabled:
        return True
    key = str(h).lower()
    if key in files_ok:
        return files_ok[key]
    files = qb.get_torrent_files(key)
    ok = len(files) > 0
    files_ok[key] = ok
    return ok

def summarize_path(path: Path) -> tuple[int, int]:
    if not path.exists():
        return (-1, -1)
    if path.is_file():
        return (1, int(path.stat().st_size))

    file_count = 0
    total_bytes = 0
    for item in path.rglob("*"):
        if item.is_file():
            file_count += 1
            total_bytes += int(item.stat().st_size)
    return (file_count, total_bytes)

def choose_single_file_path(plan: dict, key: str) -> str | None:
    try:
        file_count = int(plan.get("file_count") or 0)
    except (TypeError, ValueError):
        return None
    if file_count != 1:
        return None

    raw_path = str(plan.get(key, "")).strip()
    if not raw_path:
        return None
    path = Path(raw_path)

    candidate_names = []
    source_name = Path(str(plan.get("source_path", "")).strip()).name
    if source_name:
        candidate_names.append(source_name)

    roots = [
        str(v.get("root_name", "")).strip()
        for v in (plan.get("view_targets") or [])
        if isinstance(v, dict) and v.get("root_name")
    ]
    for root, _count in Counter(r for r in roots if Path(r).suffix).most_common():
        if root not in candidate_names:
            candidate_names.append(root)

    if path.exists() and path.is_file():
        return str(path)

    candidates: list[Path] = []
    parent = path.parent
    if parent.exists():
        if path.exists() and path.is_dir():
            for sibling in parent.glob(f"{path.name}.*"):
                if sibling.is_file():
                    candidates.append(sibling)
        for name in candidate_names:
            candidates.append(parent / name)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None

def verify_reuse_target(plan: dict) -> bool:
    if str(plan.get("decision", "")).upper() != "REUSE":
        return True
    try:
        expected_files = int(plan.get("file_count") or 0)
        expected_bytes = int(plan.get("total_bytes") or 0)
    except (TypeError, ValueError):
        return False
    target = Path(str(plan.get("target_path", "")).strip())
    actual_files, actual_bytes = summarize_path(target)
    return actual_files == expected_files and actual_bytes == expected_bytes

def plan_score(plan: dict) -> int:
    score = 0
    try:
        score += len(plan.get("affected_torrents") or [])
    except Exception:
        pass
    target = Path(str(plan.get("target_path", "")).strip())
    if target.exists():
        if target.is_file():
            score += 40
        elif target.is_dir():
            score += 10
    elif target.suffix:
        score += 5
    source = Path(str(plan.get("source_path", "")).strip())
    if source.exists():
        if source.is_file():
            score += 8
        elif source.is_dir():
            score += 2
    if plan.get("normalization", {}).get("fallback_used"):
        score -= 1
    return score

plans_in = data.get("plans", [])
plans_live = []
plans_out = []
trimmed = 0
dropped = 0
stale_files = 0
rewritten_targets = 0
invalid_targets = 0
deduped = 0
for p in plans_in:
    affected = []
    for h in p.get("affected_torrents", []):
        h_key = str(h).lower()
        if live_filter_enabled and h_key not in live:
            continue
        if not hash_has_files(h_key):
            stale_files += 1
            continue
        affected.append(h_key)
    if len(affected) != len(p.get("affected_torrents", [])):
        trimmed += 1
    primary = str(p.get("torrent_hash", "")).lower()
    if live_filter_enabled and primary and (primary not in live or not hash_has_files(primary)) and affected:
        p["torrent_hash"] = affected[0]
    p["affected_torrents"] = affected
    if not p["affected_torrents"]:
        dropped += 1
        continue

    adjusted_target = choose_single_file_path(p, "target_path")
    if adjusted_target and adjusted_target != str(p.get("target_path", "")):
        p["target_path"] = adjusted_target
        rewritten_targets += 1

    adjusted_source = choose_single_file_path(p, "source_path")
    if adjusted_source and adjusted_source != str(p.get("source_path", "")):
        p["source_path"] = adjusted_source

    if not verify_reuse_target(p):
        invalid_targets += 1
        print(
            "sanitize_drop reason=target_mismatch "
            f"payload={str(p.get('payload_hash', ''))[:16]} "
            f"target={p.get('target_path', '')}"
        )
        continue

    plans_live.append(p)

best_by_key: dict[tuple[str, str], dict] = {}
order: list[tuple[str, str]] = []
for p in plans_live:
    key = (
        str(p.get("decision", "")).upper(),
        str(p.get("payload_hash") or p.get("payload_id") or ""),
    )
    score = plan_score(p)
    if key not in best_by_key:
        best_by_key[key] = {"score": score, "plan": p}
        order.append(key)
        continue
    deduped += 1
    if score > int(best_by_key[key]["score"]):
        best_by_key[key] = {"score": score, "plan": p}

for key in order:
    plans_out.append(best_by_key[key]["plan"])

data["plans"] = plans_out
summary = data.get("summary", {})
summary["candidates"] = len(plans_out)
summary["decision_reuse"] = sum(1 for p in plans_out if p.get("decision") == "REUSE")
summary["decision_move"] = sum(1 for p in plans_out if p.get("decision") == "MOVE")
summary["fallback_used"] = sum(
    1 for p in plans_out if p.get("normalization", {}).get("fallback_used")
)
summary["review_required"] = sum(
    1 for p in plans_out if p.get("normalization", {}).get("review_required")
)
data["summary"] = summary

out_path.write_text(json.dumps(data, indent=2) + "\n")
print(
    "sanitize_live_torrents "
    f"input={len(plans_in)} output={len(plans_out)} trimmed={trimmed} "
    f"dropped={dropped} stale_files={stale_files} invalid_target={invalid_targets} "
    f"rewritten_target={rewritten_targets} deduped={deduped} "
    f"live_filter={'enabled' if live_filter_enabled else 'disabled'} live={len(live)}"
)
PY
}

run_with_heartbeat() {
  local step_label="$1"
  shift

  local interval="${REHOME_PROGRESS_HEARTBEAT_SECONDS:-15}"
  if ! [[ "$interval" =~ ^[0-9]+$ ]] || [[ "$interval" -lt 5 ]]; then
    interval=15
  fi

  local elapsed=0
  local rc=0
  local cmd_str
  printf -v cmd_str '%q ' "$@"
  hr
  echo "Phase start: ${step_label}"
  echo "Command: ${cmd_str% }"
  echo "Heartbeat: every ${interval}s"
  hr
  echo "dispatch step=${step_label} heartbeat_s=${interval} cmd=${cmd_str% }"

  "$@" &
  local pid=$!

  while kill -0 "$pid" 2>/dev/null; do
    sleep "$interval"
    elapsed=$((elapsed + interval))
    if kill -0 "$pid" 2>/dev/null; then
      echo "heartbeat step=${step_label} elapsed_s=${elapsed}"
    fi
  done

  wait "$pid" || rc=$?
  echo "dispatch step=${step_label} rc=${rc} elapsed_s=${elapsed}"
  hr
  if [[ "$rc" -eq 0 ]]; then
    echo "Phase result: ${step_label} completed successfully in ${elapsed}s."
  else
    echo "Phase result: ${step_label} failed with rc=${rc} after ${elapsed}s."
  fi
  hr
  return "$rc"
}

run_nohl_restart_lane() {
  local min_free_pct="${REHOME_NOHL_MIN_FREE_PCT:-20}"
  local limit="${REHOME_NOHL_LIMIT:-0}"
  local do_apply="${REHOME_NOHL_APPLY:-0}"
  local cleanup="${REHOME_NOHL_FOLLOWUP_CLEANUP:-1}"
  local print_torrents="${REHOME_NOHL_FOLLOWUP_PRINT_TORRENTS:-0}"
  local execute="${REHOME_NOHL_EXECUTE:-0}"
  local resume="${REHOME_NOHL_RESUME:-1}"
  local output_prefix="${REHOME_NOHL_OUTPUT_PREFIX:-nohl}"
  local fast_mode="${REHOME_NOHL_FAST:-1}"
  local debug_mode="${REHOME_NOHL_DEBUG:-0}"
  local hb_seconds="${REHOME_NOHL_HEARTBEAT_SECONDS:-5}"
  local fast_arg=""
  local debug_arg=""
  [[ "$fast_mode" == "1" ]] && fast_arg="--fast"
  [[ "$debug_mode" == "1" ]] && debug_arg="--debug"
  export REHOME_PROGRESS_HEARTBEAT_SECONDS="$hb_seconds"

  hr
  echo "Run mode: nohl restart"
  echo "Live apply: ${do_apply} | Execute phases: ${execute} | Fast: ${fast_mode} | Debug: ${debug_mode} | Heartbeat: ${hb_seconds}s"
  echo "Safety guard: minimum pool free space ${min_free_pct}%"
  hr
  echo "mode=nohl-restart min_free_pct=${min_free_pct} limit=${limit} execute=${execute} apply=${do_apply} resume=${resume} fast=${fast_mode} debug=${debug_mode} heartbeat_s=${hb_seconds}"
  echo "recommended_commands_begin"
  echo "REHOME_PROCESS_MODE=nohl-restart REHOME_NOHL_EXECUTE=1 REHOME_NOHL_APPLY=1 REHOME_NOHL_RESUME=${resume} REHOME_NOHL_FAST=${fast_mode} REHOME_NOHL_DEBUG=${debug_mode} REHOME_NOHL_HEARTBEAT_SECONDS=${hb_seconds} bin/codex-says-run-this-next.sh --min-free-pct ${min_free_pct}"
  echo "bin/rehome-30_nohl-discover-and-rank.sh --output-prefix ${output_prefix} --min-free-pct ${min_free_pct} --limit ${limit} ${fast_arg} ${debug_arg}"
  echo "bin/rehome-40_nohl-build-group-plan.sh --output-prefix ${output_prefix} --limit ${limit} --resume ${resume} ${fast_arg} ${debug_arg}"
  echo "bin/rehome-50_nohl-dryrun-group-batch.sh --output-prefix ${output_prefix} --min-free-pct ${min_free_pct} --limit ${limit} ${fast_arg} ${debug_arg}"
  echo "bin/rehome-60_nohl-apply-group-batch.sh --output-prefix ${output_prefix} --min-free-pct ${min_free_pct} --limit ${limit} ${fast_arg} ${debug_arg}"
  echo "bin/rehome-70_nohl-followup-and-reconcile.sh --output-prefix ${output_prefix} --cleanup ${cleanup} --print-torrents ${print_torrents} ${fast_arg} ${debug_arg}"
  echo "bin/rehome-80_nohl-report-and-next-batch.sh --output-prefix ${output_prefix} ${fast_arg} ${debug_arg}"
  echo "recommended_commands_end"

  if [[ "$execute" != "1" ]]; then
    echo "nohl_restart execute=0 status=printed_only"
    return 0
  fi

  run_with_heartbeat "30 nohl-discover-rank" \
    bin/rehome-30_nohl-discover-and-rank.sh \
    --output-prefix "$output_prefix" \
    --min-free-pct "$min_free_pct" \
    --limit "$limit" \
    ${fast_arg:+$fast_arg} \
    ${debug_arg:+$debug_arg}

  run_with_heartbeat "40 nohl-build-group-plan" \
    bin/rehome-40_nohl-build-group-plan.sh \
    --output-prefix "$output_prefix" \
    --limit "$limit" \
    --resume "$resume" \
    ${fast_arg:+$fast_arg} \
    ${debug_arg:+$debug_arg}

  run_with_heartbeat "50 nohl-dryrun-group-batch" \
    bin/rehome-50_nohl-dryrun-group-batch.sh \
    --output-prefix "$output_prefix" \
    --min-free-pct "$min_free_pct" \
    --limit "$limit" \
    ${fast_arg:+$fast_arg} \
    ${debug_arg:+$debug_arg}

  if [[ "$do_apply" == "1" ]]; then
    run_with_heartbeat "60 nohl-apply-group-batch" \
      bin/rehome-60_nohl-apply-group-batch.sh \
      --output-prefix "$output_prefix" \
      --min-free-pct "$min_free_pct" \
      --limit "$limit" \
      ${fast_arg:+$fast_arg} \
      ${debug_arg:+$debug_arg}
  else
    echo "step=60 nohl-apply-group-batch status=skipped reason=apply_disabled"
  fi

  run_with_heartbeat "70 nohl-followup-reconcile" \
    bin/rehome-70_nohl-followup-and-reconcile.sh \
    --output-prefix "$output_prefix" \
    --cleanup "$cleanup" \
    --print-torrents "$print_torrents" \
    ${fast_arg:+$fast_arg} \
    ${debug_arg:+$debug_arg}

  run_with_heartbeat "80 nohl-report-next-batch" \
    bin/rehome-80_nohl-report-and-next-batch.sh \
    --output-prefix "$output_prefix" \
    ${fast_arg:+$fast_arg} \
    ${debug_arg:+$debug_arg}

  echo "nohl_restart done=1"
}

run_nohl_missing_recheck_lane() {
  local output_prefix="${REHOME_NOHL_OUTPUT_PREFIX:-nohl}"
  local execute="${REHOME_MISSING_RECHECK_EXECUTE:-0}"
  local fast_mode="${REHOME_NOHL_FAST:-1}"
  local debug_mode="${REHOME_NOHL_DEBUG:-1}"
  local recheck_sleep_s="${REHOME_MISSING_RECHECK_SLEEP_SECONDS:-120}"
  local qbit_url="${QBIT_URL:-http://localhost:9003}"
  local qbit_user="${QBIT_USER:-admin}"
  local qbit_pass="${QBIT_PASS:-adminpass}"
  local fast_arg=""
  local debug_arg=""
  [[ "$fast_mode" == "1" ]] && fast_arg="--fast"
  [[ "$debug_mode" == "1" ]] && debug_arg="--debug"

  hr
  echo "Run mode: nohl missing recheck"
  echo "Execute phases: ${execute} | Fast: ${fast_mode} | Debug: ${debug_mode} | Sleep after recheck: ${recheck_sleep_s}s"
  hr
  echo "mode=nohl-missing-recheck execute=${execute} output_prefix=${output_prefix} fast=${fast_mode} debug=${debug_mode} sleep_s=${recheck_sleep_s}"
  echo "recommended_commands_begin"
  echo "bin/rehome-95_nohl-basics-qb-missing-audit.sh ${fast_arg} ${debug_arg}"
  echo "bin/rehome-96_nohl-basics-qb-missing-remediate-dryrun.sh ${fast_arg} ${debug_arg}"
  echo "AUDIT=\$(ls -1t out/reports/rehome-normalize/${output_prefix}-qb-missing-audit-*.json | head -n1)"
  echo "HASH_FILE=out/reports/rehome-normalize/${output_prefix}-qb-missing-hashes-\$(TZ=America/New_York date +%Y%m%d-%H%M%S).txt"
  echo "jq -r '.entries[].torrent_hash' \"\$AUDIT\" | sort -u > \"\$HASH_FILE\""
  echo "source /mnt/config/secrets/qbittorrent/api.env 2>/dev/null || true"
  echo "QBIT_URL=\"${qbit_url}\" QBIT_USER=\"${qbit_user}\" QBIT_PASS=\"${qbit_pass}\" HASH_FILE=\"\$HASH_FILE\" bash -lc 'curl -fsS -c /tmp/qb.cookie --data-urlencode \"username=\$QBIT_USER\" --data-urlencode \"password=\$QBIT_PASS\" \"\$QBIT_URL/api/v2/auth/login\" && HASHES=\$(paste -sd\"|\" \"\$HASH_FILE\") && curl -fsS -b /tmp/qb.cookie --data-urlencode \"hashes=\$HASHES\" \"\$QBIT_URL/api/v2/torrents/recheck\"'"
  echo "sleep ${recheck_sleep_s}"
  echo "bin/rehome-95_nohl-basics-qb-missing-audit.sh ${fast_arg} ${debug_arg}"
  echo "bin/rehome-96_nohl-basics-qb-missing-remediate-dryrun.sh ${fast_arg} ${debug_arg}"
  echo "recommended_commands_end"

  if [[ "$execute" != "1" ]]; then
    echo "nohl_missing_recheck execute=0 status=printed_only"
    return 0
  fi

  bin/rehome-95_nohl-basics-qb-missing-audit.sh ${fast_arg:+$fast_arg} ${debug_arg:+$debug_arg}
  bin/rehome-96_nohl-basics-qb-missing-remediate-dryrun.sh ${fast_arg:+$fast_arg} ${debug_arg:+$debug_arg}

  local audit_file
  audit_file="$(ls -1t "out/reports/rehome-normalize/${output_prefix}-qb-missing-audit-"*.json 2>/dev/null | head -n1 || true)"
  if [[ -z "$audit_file" || ! -f "$audit_file" ]]; then
    echo "missing_audit_json_for_recheck output_prefix=${output_prefix}" >&2
    return 2
  fi
  local hash_file="out/reports/rehome-normalize/${output_prefix}-qb-missing-hashes-${stamp}.txt"
  jq -r '.entries[].torrent_hash' "$audit_file" | sort -u > "$hash_file"
  echo "recheck_hash_file=${hash_file}"
  local hash_count
  hash_count="$(wc -l < "$hash_file" | tr -d ' ')"
  if [[ "${hash_count:-0}" -eq 0 ]]; then
    echo "nohl_missing_recheck status=skip reason=no_missing_hashes"
    return 0
  fi

  source /mnt/config/secrets/qbittorrent/api.env 2>/dev/null || true
  : "${QBIT_URL:=${qbit_url}}" "${QBIT_USER:=${qbit_user}}" "${QBIT_PASS:=${qbit_pass}}"

  curl -fsS -c /tmp/qb.cookie \
    --data-urlencode "username=${QBIT_USER}" \
    --data-urlencode "password=${QBIT_PASS}" \
    "${QBIT_URL}/api/v2/auth/login" >/dev/null
  local hashes
  hashes="$(paste -sd'|' "$hash_file")"
  curl -fsS -b /tmp/qb.cookie \
    --data-urlencode "hashes=${hashes}" \
    "${QBIT_URL}/api/v2/torrents/recheck" >/dev/null
  echo "recheck_requested hashes=${hash_count} qbit_url=${QBIT_URL}"
  sleep "$recheck_sleep_s"

  bin/rehome-95_nohl-basics-qb-missing-audit.sh ${fast_arg:+$fast_arg} ${debug_arg:+$debug_arg}
  bin/rehome-96_nohl-basics-qb-missing-remediate-dryrun.sh ${fast_arg:+$fast_arg} ${debug_arg:+$debug_arg}

  echo "nohl_missing_recheck done=1"
}

stage0_relocate_pool_to_seeds_via_qb() {
  local scope_root="$1"
  local source_root="$2"
  local seeds_root="$3"
  local apply_mode="$4"
  local min_progress="$5"
  local wait_seconds="$6"
  local heartbeat_seconds="$7"
  local poll_seconds="$8"
  local stuck_seconds="$9"

  PYTHONPATH=src \
    STAGE0_SCOPE_ROOT="$scope_root" \
    STAGE0_SOURCE_ROOT="$source_root" \
    STAGE0_SEEDS_ROOT="$seeds_root" \
    STAGE0_APPLY_MODE="$apply_mode" \
    STAGE0_MIN_PROGRESS="$min_progress" \
    STAGE0_WAIT_SECONDS="$wait_seconds" \
    STAGE0_HEARTBEAT_SECONDS="$heartbeat_seconds" \
    STAGE0_POLL_SECONDS="$poll_seconds" \
    STAGE0_STUCK_SECONDS="$stuck_seconds" \
    python -u - <<'PY'
import os
import time
from pathlib import Path
from hashall.qbittorrent import QBittorrentClient


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


scope_root = _canonical(os.environ.get("STAGE0_SCOPE_ROOT", "/pool"))
source_root = _canonical(os.environ.get("STAGE0_SOURCE_ROOT", "/pool/data"))
seeds_root = _canonical(os.environ.get("STAGE0_SEEDS_ROOT", "/pool/data/seeds"))
apply_mode = str(os.environ.get("STAGE0_APPLY_MODE", "1")).strip().lower() in {"1", "true", "yes", "on"}
min_progress = float(os.environ.get("STAGE0_MIN_PROGRESS", "1.0"))
wait_seconds = max(10, int(float(os.environ.get("STAGE0_WAIT_SECONDS", "1800"))))
heartbeat_seconds = max(5, int(float(os.environ.get("STAGE0_HEARTBEAT_SECONDS", "15"))))
poll_seconds = max(1, int(float(os.environ.get("STAGE0_POLL_SECONDS", "2"))))
stuck_seconds = max(30, int(float(os.environ.get("STAGE0_STUCK_SECONDS", "120"))))

qb = QBittorrentClient(
    base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
    username=os.getenv("QBIT_USER", "admin"),
    password=os.getenv("QBIT_PASS", "adminpass"),
)

print("step=0 legacy-qb-relocate-fetch status=start", flush=True)
torrents = qb.get_torrents()
print(f"step=0 legacy-qb-relocate-fetch status=done torrents_total={len(torrents)}", flush=True)
total = len(torrents)
print(
    "step=0 legacy-qb-relocate "
    f"mode={'apply' if apply_mode else 'dryrun'} "
    f"scope={scope_root} source={source_root} target={seeds_root} "
    f"min_progress={min_progress:.3f} torrents_total={total} "
    f"wait_seconds={wait_seconds} heartbeat_seconds={heartbeat_seconds} "
    f"poll_seconds={poll_seconds} stuck_seconds={stuck_seconds}"
)

candidates = []
checked = 0
skipped_not_pool = 0
skipped_in_seeds = 0
skipped_not_complete = 0
skipped_out_of_source = 0
for t in torrents:
    checked += 1
    if checked % 500 == 0 or checked == total:
        print(
            f"  stage0_scan checked={checked}/{total} "
            f"candidates={len(candidates)} skipped_not_pool={skipped_not_pool} "
            f"skipped_in_seeds={skipped_in_seeds} skipped_not_complete={skipped_not_complete}"
        )

    save_path_raw = str(getattr(t, "save_path", "") or "").strip()
    if not save_path_raw:
        continue
    save_path = _canonical(save_path_raw)
    if not _is_under(save_path, scope_root):
        skipped_not_pool += 1
        continue
    if _is_under(save_path, seeds_root):
        skipped_in_seeds += 1
        continue
    if float(getattr(t, "progress", 0.0) or 0.0) < min_progress:
        skipped_not_complete += 1
        continue
    if not _is_under(save_path, source_root):
        skipped_out_of_source += 1
        continue

    rel = save_path.relative_to(source_root)
    target_save = seeds_root / rel
    if save_path == target_save:
        continue
    candidates.append(
        {
            "hash": str(getattr(t, "hash", "")).lower(),
            "name": str(getattr(t, "name", "") or ""),
            "save_path": save_path,
            "target_save": target_save,
            "auto_tmm": bool(getattr(t, "auto_tmm", False)),
            "state": str(getattr(t, "state", "") or ""),
            "progress": float(getattr(t, "progress", 0.0) or 0.0),
        }
    )

print(
    "step=0 legacy-qb-relocate-plan "
    f"candidates={len(candidates)} skipped_not_pool={skipped_not_pool} "
    f"skipped_in_seeds={skipped_in_seeds} skipped_not_complete={skipped_not_complete} "
    f"skipped_out_of_source={skipped_out_of_source}"
)

if not candidates:
    raise SystemExit(0)

for idx, c in enumerate(candidates[:20], start=1):
    print(
        f"  stage0_plan idx={idx}/{len(candidates)} "
        f"hash={c['hash'][:16]} state={c['state']} progress={c['progress']:.3f} "
        f"from={c['save_path']} to={c['target_save']}"
    )
if len(candidates) > 20:
    print(f"  stage0_plan_more count={len(candidates) - 20}")

if not apply_mode:
    raise SystemExit(0)

moved = 0
failed = 0
for idx, c in enumerate(candidates, start=1):
    h = c["hash"]
    src = c["save_path"]
    dst = c["target_save"]
    dst.mkdir(parents=True, exist_ok=True)
    auto_tmm = bool(c["auto_tmm"])
    print(f"  stage0_move idx={idx}/{len(candidates)} hash={h[:16]} from={src} to={dst}")
    try:
        if auto_tmm:
            qb.set_auto_management(h, False)
        if not qb.pause_torrent(h):
            raise RuntimeError("pause_failed")
        if not qb.set_location(h, str(dst)):
            raise RuntimeError("set_location_failed")

        deadline = time.monotonic() + wait_seconds
        last_beat = 0.0
        start_wait = time.monotonic()
        stuck_start = start_wait
        moved_ok = False
        while time.monotonic() < deadline:
            info = qb.get_torrent_info(h)
            now = time.monotonic()
            state = getattr(info, "state", "unknown") if info else "missing"
            progress = getattr(info, "progress", 0.0) if info else 0.0
            save_path = getattr(info, "save_path", "") if info else ""
            if info and str(info.save_path or "").strip():
                actual = _canonical(str(info.save_path))
                if actual == dst:
                    moved_ok = True
                    break
                if actual != src:
                    stuck_start = now
            state_l = str(state).lower()
            if "moving" in state_l:
                stuck_start = now
            if now - stuck_start >= stuck_seconds:
                raise RuntimeError(
                    f"save_path_stuck state={state} save_path={save_path} "
                    f"stuck_s={int(now - stuck_start)}"
                )
            if now - last_beat >= heartbeat_seconds:
                print(
                    f"    stage0_wait hash={h[:16]} state={state} "
                    f"progress={float(progress):.3f} save_path={save_path} "
                    f"waited_s={int(now - start_wait)}/{wait_seconds} "
                    f"stuck_s={int(now - stuck_start)}/{stuck_seconds}"
                )
                last_beat = now
            time.sleep(poll_seconds)

        if not moved_ok:
            raise RuntimeError("wait_for_save_path_timeout")

        if not qb.resume_torrent(h):
            raise RuntimeError("resume_failed")
        if auto_tmm:
            qb.set_auto_management(h, True)
        moved += 1
        print(f"  stage0_move_ok idx={idx}/{len(candidates)} hash={h[:16]}")
    except Exception as exc:
        failed += 1
        print(f"  stage0_move_error idx={idx}/{len(candidates)} hash={h[:16]} error={exc}")
        try:
            qb.resume_torrent(h)
        except Exception:
            pass
        if auto_tmm:
            try:
                qb.set_auto_management(h, True)
            except Exception:
                pass

print(f"step=0 legacy-qb-relocate-summary moved={moved} failed={failed} candidates={len(candidates)}")
if failed:
    raise SystemExit(2)
PY
}

echo "run_log=$run_log"

PROCESS_MODE="${REHOME_PROCESS_MODE:-frozen-one-pass}"
if [[ "$PROCESS_MODE" == "nohl-restart" ]]; then
  run_nohl_restart_lane
  echo "done=1 mode=nohl-restart run_log=$run_log"
  exit 0
fi
if [[ "$PROCESS_MODE" == "nohl-missing-recheck" ]]; then
  run_nohl_missing_recheck_lane
  echo "done=1 mode=nohl-missing-recheck run_log=$run_log"
  exit 0
fi

LEGACY_CROSS_SEED_ROOT="/pool/data/cross-seed"

LIMIT="${REHOME_NORMALIZE_LIMIT:-50}"
POOL_ROOT="${REHOME_NORMALIZE_POOL_ROOT:-/pool/data/seeds}"
STASH_ROOT="${REHOME_NORMALIZE_STASH_ROOT:-/stash/media/torrents/seeding}"
POOL_DEVICE="${REHOME_POOL_DEVICE:-44}"
LEGACY_MIGRATE="${REHOME_STAGE0_MIGRATE_LEGACY:-1}"
STAGE0_SCOPE_ROOT="${REHOME_STAGE0_SCOPE_ROOT:-/pool}"
STAGE0_SOURCE_ROOT="${REHOME_STAGE0_SOURCE_ROOT:-/pool/data}"
STAGE0_APPLY_MODE="${REHOME_STAGE0_APPLY:-1}"
STAGE0_MIN_PROGRESS="${REHOME_STAGE0_MIN_PROGRESS:-1.0}"
STAGE0_WAIT_SECONDS="${REHOME_STAGE0_WAIT_SECONDS:-1800}"
STAGE0_HEARTBEAT_SECONDS="${REHOME_STAGE0_HEARTBEAT_SECONDS:-5}"
STAGE0_POLL_SECONDS="${REHOME_STAGE0_POLL_SECONDS:-2}"
STAGE0_STUCK_SECONDS="${REHOME_STAGE0_STUCK_SECONDS:-120}"
HASH_PROGRESS="${PAYLOAD_HASH_PROGRESS:-auto}"
case "${HASH_PROGRESS}" in
  auto|minimal|full) ;;
  *)
    echo "warning=invalid_hash_progress value=${HASH_PROGRESS} fallback=auto"
    HASH_PROGRESS="auto"
    ;;
esac
RUN_RECOVERY_STEPS="${REHOME_NORMALIZE_RUN_RECOVERY:-0}"
CLEANUP_DUPLICATE="${REHOME_CLEANUP_DUPLICATE_PAYLOAD:-1}"

echo "mode=frozen-one-pass limit=${LIMIT} pool_root=${POOL_ROOT} pool_device=${POOL_DEVICE}"
echo "sanitize_live_filter=${REHOME_SANITIZE_LIVE:-0} recovery_steps=${RUN_RECOVERY_STEPS} cleanup_duplicate=${CLEANUP_DUPLICATE} stage0_legacy_migrate=${LEGACY_MIGRATE}"
echo "progress_heartbeat_s=${REHOME_PROGRESS_HEARTBEAT_SECONDS:-15}"
echo "stage0_wait_seconds=${STAGE0_WAIT_SECONDS} stage0_heartbeat_seconds=${STAGE0_HEARTBEAT_SECONDS} stage0_poll_seconds=${STAGE0_POLL_SECONDS} stage0_stuck_seconds=${STAGE0_STUCK_SECONDS}"

if [[ "$LEGACY_MIGRATE" == "1" ]]; then
  run_with_heartbeat "0 legacy-qb-relocate" \
    stage0_relocate_pool_to_seeds_via_qb \
    "$STAGE0_SCOPE_ROOT" \
    "$STAGE0_SOURCE_ROOT" \
    "$POOL_ROOT" \
    "$STAGE0_APPLY_MODE" \
    "$STAGE0_MIN_PROGRESS" \
    "$STAGE0_WAIT_SECONDS" \
    "$STAGE0_HEARTBEAT_SECONDS" \
    "$STAGE0_POLL_SECONDS" \
    "$STAGE0_STUCK_SECONDS"
else
  legacy_bytes="$(du -sb "$LEGACY_CROSS_SEED_ROOT" 2>/dev/null | awk '{print $1}')"
  if [[ "${legacy_bytes:-0}" -gt 0 ]]; then
    echo "warning=legacy_cross_seed_not_migrated root=$LEGACY_CROSS_SEED_ROOT bytes=$legacy_bytes"
  fi
  echo "step=0 legacy-migrate status=skip reason=disabled"
fi

echo "step=sync-snapshot"
run_with_heartbeat "sync-snapshot payload-sync" \
  make payload-sync \
  PAYLOAD_PATH_PREFIXES="${POOL_ROOT}" \
  PAYLOAD_UPGRADE_MISSING=1 \
  PAYLOAD_PARALLEL=1 \
  PAYLOAD_LOW_PRIORITY=1 \
  PAYLOAD_HASH_PROGRESS="${HASH_PROGRESS}"

PLAN="out/reports/rehome-normalize/rehome-plan-normalize-frozen-${stamp}.json"
echo "step=plan-from-db"
run_with_heartbeat "plan-from-db normalize-plan" \
  make rehome-normalize-plan \
  REHOME_POOL_DEVICE="${POOL_DEVICE}" \
  REHOME_NORMALIZE_POOL_ROOT="${POOL_ROOT}" \
  REHOME_NORMALIZE_STASH_ROOT="${STASH_ROOT}" \
  REHOME_NORMALIZE_FLAT_ONLY=0 \
  REHOME_NORMALIZE_REFRESH=0 \
  REHOME_NORMALIZE_PRINT_SKIPPED=1 \
  REHOME_NORMALIZE_LIMIT="${LIMIT}" \
  REHOME_NORMALIZE_OUTPUT="${PLAN}"
print_plan_summary "$PLAN"

skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
if [[ "$skipped" -gt 0 && "$RUN_RECOVERY_STEPS" == "1" ]]; then
  echo "step=21 recover-skipped-and-replan"
  run_with_heartbeat "21 recover-skipped-and-replan" \
    bin/rehome-21_normalize-recover-skipped-and-replan_with-logs.sh --plan "$PLAN" --limit "$LIMIT" --all-mismatches
  PLAN="$(resolve_latest_plan)"
  print_plan_summary "$PLAN"

  skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
  if [[ "$skipped" -gt 0 ]]; then
    echo "step=22 scan-sync-replan"
    run_with_heartbeat "22 scan-sync-replan" \
      bin/rehome-22_normalize-scan-sync-replan_with-logs.sh --plan "$PLAN" --scan-hash-mode upgrade --limit "$LIMIT" --all-mismatches
    PLAN="$(resolve_latest_plan)"
    print_plan_summary "$PLAN"
  fi

  skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
  if [[ "$skipped" -gt 0 ]]; then
    echo "step=23 live-prefix-hash-sync-replan"
    run_with_heartbeat "23 live-prefix-hash-sync-replan" \
      bin/rehome-23_normalize-live-prefix-hash-sync-replan_with-logs.sh --plan "$PLAN" --hash-progress full --limit "$LIMIT" --all-mismatches
    PLAN="$(resolve_latest_plan)"
    print_plan_summary "$PLAN"
  fi
elif [[ "$skipped" -gt 0 ]]; then
  echo "note=skipped_payloads_present count=${skipped} recovery_steps=disabled"
fi

echo "step=apply-dry"
PLAN_READY="out/reports/rehome-normalize/$(basename "${PLAN%.json}")-live.json"
sanitize_plan_live_torrents "$PLAN" "$PLAN_READY"
print_plan_summary "$PLAN_READY"
if [[ "$(jq -r '.plans | length' "$PLAN_READY")" -eq 0 ]]; then
  echo "No live plan entries remain after sanitization; aborting."
  exit 1
fi
run_with_heartbeat "apply-dry rehome-apply-dry" \
  make rehome-apply-dry REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD="$CLEANUP_DUPLICATE"
echo "step=apply-live"
run_with_heartbeat "apply-live rehome-apply" \
  make rehome-apply REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD="$CLEANUP_DUPLICATE"
echo "step=followup"
run_with_heartbeat "followup rehome-followup" \
  make rehome-followup REHOME_RECHECK_PATH=/pool/data/seeds
missing_source_skips="$(rg -c 'cleanup_duplicate skip reason=missing_source' "$run_log" || true)"
manual_actions="$(rg -c 'MANUAL_ACTION_REQUIRED' "$run_log" || true)"
echo "post_summary missing_source_skips=${missing_source_skips:-0} manual_actions=${manual_actions:-0}"
if rg -q '^payload=.* outcome=pending' "$run_log"; then
  echo "post_summary pending_payloads_begin"
  rg '^payload=.* outcome=pending' "$run_log"
  echo "post_summary pending_payloads_end"
fi
echo "done=1 plan_used=$PLAN_READY source_plan=$PLAN run_log=$run_log"
