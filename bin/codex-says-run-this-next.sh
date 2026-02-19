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
from hashall.qbittorrent import QBittorrentClient

in_path = Path(os.environ["INPUT_PLAN"])
out_path = Path(os.environ["OUTPUT_PLAN"])
data = json.loads(in_path.read_text())

qb = QBittorrentClient(
    base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
    username=os.getenv("QBIT_USER", "admin"),
    password=os.getenv("QBIT_PASS", "adminpass"),
)
torrents = qb.get_torrents()
live = {t.hash.lower() for t in torrents}
files_ok = {}

def hash_has_files(h: str) -> bool:
    key = str(h).lower()
    if key in files_ok:
        return files_ok[key]
    files = qb.get_torrent_files(key)
    ok = len(files) > 0
    files_ok[key] = ok
    return ok

plans_in = data.get("plans", [])
plans_out = []
trimmed = 0
dropped = 0
stale_files = 0
for p in plans_in:
    affected = []
    for h in p.get("affected_torrents", []):
        h_key = str(h).lower()
        if h_key not in live:
            continue
        if not hash_has_files(h_key):
            stale_files += 1
            continue
        affected.append(h_key)
    if len(affected) != len(p.get("affected_torrents", [])):
        trimmed += 1
    primary = str(p.get("torrent_hash", "")).lower()
    if primary and (primary not in live or not hash_has_files(primary)) and affected:
        p["torrent_hash"] = affected[0]
    p["affected_torrents"] = affected
    if not p["affected_torrents"]:
        dropped += 1
        continue
    plans_out.append(p)

data["plans"] = plans_out
summary = data.get("summary", {})
summary["candidates"] = len(plans_out)
summary["decision_reuse"] = sum(1 for p in plans_out if p.get("decision") == "REUSE")
summary["decision_move"] = sum(1 for p in plans_out if p.get("decision") == "MOVE")
data["summary"] = summary

out_path.write_text(json.dumps(data, indent=2) + "\n")
print(
    "sanitize_live_torrents "
    f"input={len(plans_in)} output={len(plans_out)} trimmed={trimmed} "
    f"dropped={dropped} stale_files={stale_files} live={len(live)}"
)
PY
}

echo "run_log=$run_log"

LEGACY_CROSS_SEED_ROOT="/pool/data/cross-seed"
if [[ -d "$LEGACY_CROSS_SEED_ROOT" ]]; then
  legacy_bytes="$(du -sb "$LEGACY_CROSS_SEED_ROOT" 2>/dev/null | awk '{print $1}')"
  if [[ "${legacy_bytes:-0}" -gt 0 ]]; then
    echo "warning=legacy_cross_seed_not_migrated root=$LEGACY_CROSS_SEED_ROOT bytes=$legacy_bytes"
    echo "note=this workflow normalizes /pool/data/seeds only; legacy /pool/data/cross-seed migration is separate"
  fi
fi

echo "step=20 normalize-refresh-plan"
bin/rehome-20_normalize-refresh-plan_with-logs.sh --limit 50 --all-mismatches
PLAN="$(resolve_latest_plan)"
print_plan_summary "$PLAN"

skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
if [[ "$skipped" -gt 0 ]]; then
  echo "step=21 recover-skipped-and-replan"
  bin/rehome-21_normalize-recover-skipped-and-replan_with-logs.sh --plan "$PLAN" --limit 50 --all-mismatches
  PLAN="$(resolve_latest_plan)"
  print_plan_summary "$PLAN"
fi

skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
if [[ "$skipped" -gt 0 ]]; then
  echo "step=22 scan-sync-replan"
  bin/rehome-22_normalize-scan-sync-replan_with-logs.sh --plan "$PLAN" --scan-hash-mode upgrade --limit 50 --all-mismatches
  PLAN="$(resolve_latest_plan)"
  print_plan_summary "$PLAN"
fi

skipped="$(jq -r '.summary.skipped // 0' "$PLAN")"
if [[ "$skipped" -gt 0 ]]; then
  echo "step=23 live-prefix-hash-sync-replan"
  bin/rehome-23_normalize-live-prefix-hash-sync-replan_with-logs.sh --plan "$PLAN" --hash-progress full --limit 50 --all-mismatches
  PLAN="$(resolve_latest_plan)"
  print_plan_summary "$PLAN"
fi

echo "step=apply-dry"
PLAN_READY="out/reports/rehome-normalize/$(basename "${PLAN%.json}")-live.json"
sanitize_plan_live_torrents "$PLAN" "$PLAN_READY"
print_plan_summary "$PLAN_READY"
if [[ "$(jq -r '.plans | length' "$PLAN_READY")" -eq 0 ]]; then
  echo "No live plan entries remain after sanitization; aborting."
  exit 1
fi
make rehome-apply-dry REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD=1
echo "step=apply-live"
make rehome-apply REHOME_PLAN="$PLAN_READY" REHOME_CLEANUP_DUPLICATE_PAYLOAD=1
echo "step=followup"
make rehome-followup REHOME_RECHECK_PATH=/pool/data/seeds
echo "done=1 plan_used=$PLAN_READY source_plan=$PLAN run_log=$run_log"
