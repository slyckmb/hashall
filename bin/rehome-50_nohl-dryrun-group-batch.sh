#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-50_nohl-dryrun-group-batch.sh [options]

Options:
  --hashes-file PATH        Plannable payload hash file (default: latest nohl-payload-hashes-plannable-*.txt)
  --manifest PATH           Plan manifest JSON (default: latest nohl-plan-manifest-*.json)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-name NAME          ZFS pool name to guard (default: pool)
  --min-free-pct N          Minimum required pool free % (default: 20)
  --spot-check N            Spot-check files in dryrun (default: 0)
  --limit N                 Limit hashes to process (default: 0 = all)
  --fast                    Fast mode (force spot-check 0)
  --debug                   Debug mode (enable qB debug env and verbose lines)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_plannable_hashes() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-payload-hashes-plannable-*.txt 2>/dev/null | head -n1
}

latest_manifest() {
  local prefix="$1"
  ls -1t "$HOME/.logs/hashall/reports/rehome-normalize/${prefix}-plan-manifest-"*.json 2>/dev/null | head -n1
}

HASHES_FILE=""
MANIFEST_JSON=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_NAME="pool"
MIN_FREE_PCT="20"
SPOT_CHECK="0"
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_JSON="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-name) POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct) MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --spot-check) SPOT_CHECK="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
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

if [[ -z "$HASHES_FILE" ]]; then
  HASHES_FILE="$(latest_plannable_hashes)"
fi
if [[ -z "$HASHES_FILE" || ! -f "$HASHES_FILE" ]]; then
  echo "Missing plannable hashes file; run rehome-40 first or pass --hashes-file" >&2
  exit 3
fi

if [[ -z "$MANIFEST_JSON" ]]; then
  MANIFEST_JSON="$(latest_manifest "$OUTPUT_PREFIX")"
fi
if [[ -z "$MANIFEST_JSON" || ! -f "$MANIFEST_JSON" ]]; then
  echo "Missing manifest file; run rehome-40 first or pass --manifest" >&2
  exit 3
fi

mapfile -t HASHES < <(sed -e 's/#.*$//' -e 's/[[:space:]]//g' "$HASHES_FILE" | awk 'NF > 0')
if [[ "$LIMIT" -gt 0 && "${#HASHES[@]}" -gt "$LIMIT" ]]; then
  HASHES=("${HASHES[@]:0:$LIMIT}")
fi
if [[ "${#HASHES[@]}" -eq 0 ]]; then
  echo "No hashes to dryrun" >&2
  exit 4
fi
if [[ "$FAST_MODE" -eq 1 ]]; then
  SPOT_CHECK="0"
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
  local free_pct
  free_pct="$(pool_free_pct)"
  if (( free_pct < MIN_FREE_PCT )); then
    echo "ERROR: pool $POOL_NAME free ${free_pct}% < required ${MIN_FREE_PCT}%" >&2
    return 1
  fi
  echo "pool_free_pct=${free_pct} required_min=${MIN_FREE_PCT}"
}

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-dryrun-group-batch-${stamp}.log"
ready_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-ready-${stamp}.txt"
ready_plans="${log_dir}/${OUTPUT_PREFIX}-payload-plans-dryrun-ready-${stamp}.tsv"
failed_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-failed-${stamp}.txt"
blocked_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-dryrun-blocked-${stamp}.txt"
queue_tsv="${log_dir}/${OUTPUT_PREFIX}-dryrun-queue-${stamp}.tsv"

> "$ready_hashes"
> "$ready_plans"
> "$failed_hashes"
> "$blocked_hashes"

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
    if not payload_hash:
        continue
    entries[payload_hash] = item

out = Path(os.environ["QUEUE_TSV"])
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as handle:
    handle.write("payload_hash\tdecision\tstatus\tplan_path\tsource_path\ttarget_path\n")
    for payload_hash in hashes:
        item = entries.get(payload_hash, {})
        handle.write(
            "\t".join(
                [
                    payload_hash,
                    str(item.get("decision") or ""),
                    str(item.get("status") or "missing"),
                    str(item.get("plan_path") or ""),
                    str(item.get("source_path") or ""),
                    str(item.get("target_path") or ""),
                ]
            )
            + "\n"
        )
print(f"queue_tsv={out}")
PY

ok=0
failed=0
blocked=0
missing=0

{
  hr
  echo "Phase 50: Dry-run candidate groups"
  echo "What this does: validate precomputed plans without moving data."
  hr
  echo "run_id=${stamp} step=nohl-dryrun-group-batch"
  echo "config hashes_file=${HASHES_FILE} manifest=${MANIFEST_JSON} db=${DB_PATH} pool_name=${POOL_NAME} min_free_pct=${MIN_FREE_PCT} spot_check=${SPOT_CHECK} fast=${FAST_MODE} debug=${DEBUG_MODE}"

  total="$(($(wc -l < "$queue_tsv") - 1))"
  idx=0
  while IFS=$'\t' read -r payload_hash decision status plan_path source_path target_path; do
    [[ "$payload_hash" == "payload_hash" ]] && continue
    idx=$((idx + 1))

    if [[ "$status" != "ok" || -z "$plan_path" || ! -f "$plan_path" ]]; then
      echo "dryrun idx=${idx}/${total} payload=${payload_hash:0:16} status=missing_plan manifest_status=${status}"
      echo "$payload_hash" >> "$failed_hashes"
      failed=$((failed + 1))
      missing=$((missing + 1))
      continue
    fi

    if [[ "$decision" == "BLOCK" ]]; then
      echo "dryrun idx=${idx}/${total} payload=${payload_hash:0:16} decision=BLOCK from=${source_path:--} to=${target_path:--} status=blocked"
      echo "$payload_hash" >> "$blocked_hashes"
      blocked=$((blocked + 1))
      continue
    fi

    echo "dryrun idx=${idx}/${total} payload=${payload_hash:0:16} decision=${decision} status=start"
    if ! assert_pool_space; then
      echo "$payload_hash" >> "$failed_hashes"
      failed=$((failed + 1))
      continue
    fi

    if PYTHONPATH=src python -u -m rehome.cli apply "$plan_path" --dryrun --catalog "$DB_PATH" --spot-check "$SPOT_CHECK"; then
      echo "dryrun idx=${idx}/${total} payload=${payload_hash:0:16} decision=${decision} from=${source_path:--} to=${target_path:--} status=ok"
      echo "$payload_hash" >> "$ready_hashes"
      printf '%s\t%s\n' "$payload_hash" "$plan_path" >> "$ready_plans"
      ok=$((ok + 1))
    else
      echo "dryrun idx=${idx}/${total} payload=${payload_hash:0:16} decision=${decision} from=${source_path:--} to=${target_path:--} status=error"
      echo "$payload_hash" >> "$failed_hashes"
      failed=$((failed + 1))
    fi
  done < "$queue_tsv"

  echo "summary total=${total} ok=${ok} failed=${failed} blocked=${blocked} missing_plan=${missing}"
  echo "ready_hashes=${ready_hashes}"
  echo "ready_plans=${ready_plans}"
  echo "failed_hashes=${failed_hashes}"
  echo "blocked_hashes=${blocked_hashes}"
  hr
  echo "Phase 50 complete: dryrun ok=${ok}, failed=${failed}, blocked=${blocked}, missing_plan=${missing}."
  hr
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "ready_hashes=${ready_hashes}"
echo "ready_plans=${ready_plans}"
echo "failed_hashes=${failed_hashes}"
echo "blocked_hashes=${blocked_hashes}"
