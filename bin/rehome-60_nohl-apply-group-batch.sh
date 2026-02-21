#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-60_nohl-apply-group-batch.sh [options]

Options:
  --plans-file PATH         Dryrun-ready plans TSV (default: latest nohl-payload-plans-dryrun-ready-*.tsv)
  --hashes-file PATH        Dryrun-ready payload hash file (fallback if plans TSV missing)
  --manifest PATH           Plan manifest JSON for hash->plan lookup (fallback mode)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-name NAME          ZFS pool name to guard (default: pool)
  --min-free-pct N          Minimum required free percent on pool (default: 20)
  --spot-check N            Spot-check files during apply (default: 0)
  --debug                   Enable HASHALL_REHOME_QB_DEBUG=1
  --limit N                 Limit plan rows to process (default: 0 = all)
  --fast                    Fast mode annotation in logs
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_ready_plans() {
  ls -1t out/reports/rehome-normalize/nohl-payload-plans-dryrun-ready-*.tsv 2>/dev/null | head -n1
}

latest_ready_hashes() {
  ls -1t out/reports/rehome-normalize/nohl-payload-hashes-dryrun-ready-*.txt 2>/dev/null | head -n1
}

latest_manifest() {
  local prefix="$1"
  ls -1t "out/reports/rehome-normalize/${prefix}-plan-manifest-"*.json 2>/dev/null | head -n1
}

PLANS_FILE=""
HASHES_FILE=""
MANIFEST_JSON=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_NAME="pool"
MIN_FREE_PCT="20"
SPOT_CHECK="0"
DEBUG_MODE=0
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plans-file) PLANS_FILE="${2:-}"; shift 2 ;;
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_JSON="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-name) POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --spot-check) SPOT_CHECK="${2:-}"; shift 2 ;;
    --debug) DEBUG_MODE=1; shift ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "$PLANS_FILE" ]]; then
  PLANS_FILE="$(latest_ready_plans)"
fi
if [[ -z "$HASHES_FILE" ]]; then
  HASHES_FILE="$(latest_ready_hashes)"
fi
if [[ -z "$MANIFEST_JSON" ]]; then
  MANIFEST_JSON="$(latest_manifest "$OUTPUT_PREFIX")"
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-apply-group-batch-${stamp}.log"
queue_tsv="${log_dir}/${OUTPUT_PREFIX}-apply-queue-${stamp}.tsv"
ok_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-ok-${stamp}.txt"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-failed-${stamp}.txt"
deferred_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-apply-deferred-${stamp}.txt"
> "$ok_hashes"
> "$failed_hashes"
> "$deferred_hashes"

if [[ -n "$PLANS_FILE" && -f "$PLANS_FILE" ]]; then
  awk -F'\t' 'NF >= 2 {print $1 "\t" $2}' "$PLANS_FILE" > "$queue_tsv"
elif [[ -n "$HASHES_FILE" && -f "$HASHES_FILE" && -n "$MANIFEST_JSON" && -f "$MANIFEST_JSON" ]]; then
  HASHES_FILE_REAL="$HASHES_FILE" MANIFEST_JSON_REAL="$MANIFEST_JSON" QUEUE_TSV="$queue_tsv" python - <<'PY'
import json
import os
from pathlib import Path

hashes = [
    line.strip().lower()
    for line in Path(os.environ["HASHES_FILE_REAL"]).read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
]
manifest = json.loads(Path(os.environ["MANIFEST_JSON_REAL"]).read_text(encoding="utf-8"))
entries = {}
for item in manifest.get("entries", []):
    payload_hash = str(item.get("payload_hash") or "").strip().lower()
    if payload_hash and str(item.get("status") or "") == "ok" and str(item.get("plan_path") or ""):
        entries[payload_hash] = str(item.get("plan_path"))

out = Path(os.environ["QUEUE_TSV"])
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as handle:
    for payload_hash in hashes:
        plan_path = entries.get(payload_hash, "")
        if plan_path:
            handle.write(f"{payload_hash}\t{plan_path}\n")
PY
else
  echo "Missing plans file; run rehome-50 first or pass --plans-file" >&2
  exit 3
fi

if [[ "$LIMIT" -gt 0 ]]; then
  head -n "$LIMIT" "$queue_tsv" > "${queue_tsv}.tmp"
  mv "${queue_tsv}.tmp" "$queue_tsv"
fi

if [[ ! -s "$queue_tsv" ]]; then
  echo "No plans to apply" >&2
  exit 4
fi

if [[ "$DEBUG_MODE" -eq 1 ]]; then
  export HASHALL_REHOME_QB_DEBUG=1
fi

pool_free_pct() {
  local used_pct free_pct
  used_pct="$(zpool list -H -o cap "$POOL_NAME" | tr -d ' %')"
  free_pct=$((100 - used_pct))
  echo "$free_pct"
}

assert_pool_space() {
  local context="${1:-runtime}"
  local free_pct
  free_pct="$(pool_free_pct)"
  if (( free_pct < MIN_FREE_PCT )); then
    echo "gate=pool_space context=${context} status=blocked free_pct=${free_pct} required_min=${MIN_FREE_PCT}"
    return 1
  fi
  echo "pool_free_pct=${free_pct} required_min=${MIN_FREE_PCT}"
}

ok=0
failed=0
deferred=0
processed=0
aborted=0
abort_reason="none"
exit_code=0

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 60: Live apply for dryrun-approved groups"
echo "What this does: execute existing dryrun-approved plan files."
hr
echo "run_id=${stamp} step=nohl-apply-group-batch"
echo "config queue=${queue_tsv} db=${DB_PATH} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT} spot_check=${SPOT_CHECK} fast=${FAST_MODE} debug=${DEBUG_MODE}"

total="$(wc -l < "$queue_tsv" | tr -d ' ')"
if ! assert_pool_space "preflight"; then
  awk -F'\t' 'NF >= 1 {print $1}' "$queue_tsv" | sed '/^$/d' > "$deferred_hashes"
  deferred="$(wc -l < "$deferred_hashes" | tr -d ' ')"
  aborted=1
  abort_reason="low_pool_space_preflight"
  exit_code=10
fi

idx=0
while IFS=$'\t' read -r hash plan_path; do
  if [[ "$aborted" -eq 1 ]]; then
    break
  fi
  [[ -z "$hash" ]] && continue
  idx=$((idx + 1))

  if [[ -z "$plan_path" || ! -f "$plan_path" ]]; then
    echo "apply idx=${idx}/${total} payload=${hash:0:16} status=missing_plan"
    echo "$hash" >> "$failed_hashes"
    failed=$((failed + 1))
    processed=$((processed + 1))
    continue
  fi

  echo "apply idx=${idx}/${total} payload=${hash:0:16} status=start plan=${plan_path}"
  if ! assert_pool_space "runtime"; then
    awk -F'\t' -v start="$idx" 'NR >= start && NF >= 1 {print $1}' "$queue_tsv" | sed '/^$/d' > "$deferred_hashes"
    deferred="$(wc -l < "$deferred_hashes" | tr -d ' ')"
    aborted=1
    abort_reason="low_pool_space_runtime"
    exit_code=10
    echo "apply idx=${idx}/${total} payload=${hash:0:16} status=blocked_low_space"
    break
  fi

  if PYTHONPATH=src python -u -m rehome.cli apply "$plan_path" --force --catalog "$DB_PATH" --spot-check "$SPOT_CHECK"; then
    echo "apply idx=${idx}/${total} payload=${hash:0:16} status=ok"
    echo "$hash" >> "$ok_hashes"
    ok=$((ok + 1))
  else
    echo "apply idx=${idx}/${total} payload=${hash:0:16} status=error"
    echo "$hash" >> "$failed_hashes"
    failed=$((failed + 1))
  fi
  processed=$((processed + 1))
done < "$queue_tsv"

echo "summary total=${total} processed=${processed} ok=${ok} failed=${failed} deferred=${deferred} aborted=${aborted} reason=${abort_reason}"
echo "ok_hashes=${ok_hashes}"
echo "failed_hashes=${failed_hashes}"
echo "deferred_hashes=${deferred_hashes}"
hr
if [[ "$aborted" -eq 1 ]]; then
  echo "Phase 60 halted: reason=${abort_reason} processed=${processed}/${total} deferred=${deferred}."
else
  echo "Phase 60 complete: applied ok=${ok}, failed=${failed}."
fi
hr

echo "run_log=${run_log}"
echo "ok_hashes=${ok_hashes}"
echo "failed_hashes=${failed_hashes}"
echo "deferred_hashes=${deferred_hashes}"
exit "$exit_code"
