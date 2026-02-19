#!/usr/bin/env bash
set -euo pipefail

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

stage0_migrate_legacy_cross_seed() {
  local src_root="$1"
  local dst_root="$2"

  if [[ ! -d "$src_root" ]]; then
    echo "step=0 legacy-migrate status=skip reason=missing_source root=$src_root"
    return 0
  fi

  local src_bytes_before
  src_bytes_before="$(du -sb "$src_root" 2>/dev/null | awk '{print $1}')"
  if [[ "${src_bytes_before:-0}" -eq 0 ]]; then
    echo "step=0 legacy-migrate status=skip reason=empty_source root=$src_root"
    return 0
  fi

  mkdir -p "$dst_root"

  local rsync_bin
  rsync_bin="$(command -v rsync || true)"
  if [[ -z "$rsync_bin" ]]; then
    echo "step=0 legacy-migrate status=error reason=rsync_missing"
    return 1
  fi

  echo "step=0 legacy-migrate source=$src_root target=$dst_root mode=real"
  local moved_trackers=0
  local merged_trackers=0
  local conflict_trackers=0
  local failed_trackers=0

  shopt -s nullglob dotglob
  for src_tracker in "$src_root"/*; do
    [[ -e "$src_tracker" ]] || continue
    local tracker_name
    tracker_name="$(basename "$src_tracker")"
    local dst_tracker="$dst_root/$tracker_name"

    if [[ ! -e "$dst_tracker" ]]; then
      if mv "$src_tracker" "$dst_tracker"; then
        moved_trackers=$((moved_trackers + 1))
        echo "  stage0_tracker tracker=$tracker_name action=mv status=ok"
      else
        failed_trackers=$((failed_trackers + 1))
        echo "  stage0_tracker tracker=$tracker_name action=mv status=error"
      fi
      continue
    fi

    if [[ -d "$src_tracker" && -d "$dst_tracker" ]]; then
      echo "  stage0_tracker tracker=$tracker_name action=merge status=running"
      if "$rsync_bin" -a --ignore-existing --remove-source-files "$src_tracker"/ "$dst_tracker"/; then
        merged_trackers=$((merged_trackers + 1))
        find "$src_tracker" -type d -empty -delete 2>/dev/null || true
        rmdir "$src_tracker" 2>/dev/null || true
        if [[ -d "$src_tracker" ]]; then
          local remaining_files
          remaining_files="$(find "$src_tracker" -type f 2>/dev/null | wc -l | tr -d '[:space:]')"
          if [[ "${remaining_files:-0}" -gt 0 ]]; then
            conflict_trackers=$((conflict_trackers + 1))
            echo "  stage0_tracker tracker=$tracker_name action=merge status=conflict remaining_files=$remaining_files path=$src_tracker"
          else
            rmdir "$src_tracker" 2>/dev/null || true
            echo "  stage0_tracker tracker=$tracker_name action=merge status=ok"
          fi
        else
          echo "  stage0_tracker tracker=$tracker_name action=merge status=ok"
        fi
      else
        failed_trackers=$((failed_trackers + 1))
        echo "  stage0_tracker tracker=$tracker_name action=merge status=error"
      fi
      continue
    fi

    failed_trackers=$((failed_trackers + 1))
    echo "  stage0_tracker tracker=$tracker_name action=type_conflict status=error source=$src_tracker target=$dst_tracker"
  done
  shopt -u nullglob dotglob

  local src_bytes_after dst_bytes_after
  src_bytes_after="$(du -sb "$src_root" 2>/dev/null | awk '{print $1}')"
  dst_bytes_after="$(du -sb "$dst_root" 2>/dev/null | awk '{print $1}')"
  echo "step=0 legacy-migrate-summary moved_trackers=$moved_trackers merged_trackers=$merged_trackers conflict_trackers=$conflict_trackers failed_trackers=$failed_trackers src_bytes_before=${src_bytes_before:-0} src_bytes_after=${src_bytes_after:-0} dst_bytes_after=${dst_bytes_after:-0}"
}

echo "run_log=$run_log"

LEGACY_CROSS_SEED_ROOT="/pool/data/cross-seed"

LIMIT="${REHOME_NORMALIZE_LIMIT:-50}"
POOL_ROOT="${REHOME_NORMALIZE_POOL_ROOT:-/pool/data/seeds}"
STASH_ROOT="${REHOME_NORMALIZE_STASH_ROOT:-/stash/media/torrents/seeding}"
POOL_DEVICE="${REHOME_POOL_DEVICE:-44}"
LEGACY_MIGRATE="${REHOME_STAGE0_MIGRATE_LEGACY:-1}"
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

if [[ "$LEGACY_MIGRATE" == "1" ]]; then
  stage0_migrate_legacy_cross_seed "$LEGACY_CROSS_SEED_ROOT" "${POOL_ROOT%/}/cross-seed"
else
  legacy_bytes="$(du -sb "$LEGACY_CROSS_SEED_ROOT" 2>/dev/null | awk '{print $1}')"
  if [[ "${legacy_bytes:-0}" -gt 0 ]]; then
    echo "warning=legacy_cross_seed_not_migrated root=$LEGACY_CROSS_SEED_ROOT bytes=$legacy_bytes"
  fi
  echo "step=0 legacy-migrate status=skip reason=disabled"
fi

echo "step=sync-snapshot"
make payload-sync \
  PAYLOAD_PATH_PREFIXES="${POOL_ROOT}" \
  PAYLOAD_UPGRADE_MISSING=1 \
  PAYLOAD_PARALLEL=1 \
  PAYLOAD_LOW_PRIORITY=1 \
  PAYLOAD_HASH_PROGRESS="${HASH_PROGRESS}"

PLAN="out/reports/rehome-normalize/rehome-plan-normalize-frozen-${stamp}.json"
echo "step=plan-from-db"
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
  bin/rehome-21_normalize-recover-skipped-and-replan_with-logs.sh --plan "$PLAN" --limit "$LIMIT" --all-mismatches
  PLAN="$(resolve_latest_plan)"
  print_plan_summary "$PLAN"

  skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
  if [[ "$skipped" -gt 0 ]]; then
    echo "step=22 scan-sync-replan"
    bin/rehome-22_normalize-scan-sync-replan_with-logs.sh --plan "$PLAN" --scan-hash-mode upgrade --limit "$LIMIT" --all-mismatches
    PLAN="$(resolve_latest_plan)"
    print_plan_summary "$PLAN"
  fi

  skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
  if [[ "$skipped" -gt 0 ]]; then
    echo "step=23 live-prefix-hash-sync-replan"
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
make rehome-apply-dry REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD="$CLEANUP_DUPLICATE"
echo "step=apply-live"
make rehome-apply REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD="$CLEANUP_DUPLICATE"
echo "step=followup"
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
