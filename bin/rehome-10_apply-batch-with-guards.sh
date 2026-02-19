#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-10_apply-batch-with-guards.sh [options]

Options:
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-name NAME          ZFS pool name to guard (default: pool)
  --min-free-pct N          Minimum required free percent on pool (default: 20)
  --pool-device ID          Pool device_id for DB checks (default: 44)
  --stash-device ID         Stash device_id for done-checks (default: 49)
  --spot-check N            Spot-check files during dryrun/apply (default: 0)
  --hash HASH               Add one payload hash (repeatable)
  --hashes-file PATH        File with payload hashes (one per line)
  -h, --help                Show help

Behavior:
  - Processes one payload hash at a time.
  - Before each hash: verifies pool free % >= --min-free-pct.
  - For each hash: plan+dryrun, then live apply.
  - After apply, runs 4 checks and stops on any failure:
      1) apply exit code == 0
      2) plan decision is MOVE|REUSE
      3) target exists and source state matches decision
         (MOVE=source removed, REUSE=source retained unless cleanup was requested)
      4) DB has complete payload on pool device for the payload_hash

Defaults hashes (if none provided):
  af43288cf64092870cbc8281ece7aff703299ca8547d336026ba7e1d8e35cbc9
  6e5a1307eedb1526418cb6a456950a37749a5a7b1b4e10f0365025967392a70a
  51bb3ce9037522d97affc84fedd65e7e0154ab3cd360f0bfe7121211451dc88f
  8277eae774b3591bafaf08d6917c797475f011d9fd4f450988264e308d9b35d8
  e8ab1ad3e87542dcd83e55dbb5ef8f45e5713e89a2cc0f91b8fc90b14ee460a0
  921dde75673bd27fbb5a044fe695119222cb06e52fd3d6c650d11189254aece2
USAGE
}

DB_PATH="/home/michael/.hashall/catalog.db"
POOL_NAME="pool"
MIN_FREE_PCT=20
POOL_DEVICE_ID=44
STASH_DEVICE_ID=49
SPOT_CHECK=0

HASHES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_PATH="${2:-}"; shift 2 ;;
    --pool-name)
      POOL_NAME="${2:-}"; shift 2 ;;
    --min-free-pct)
      MIN_FREE_PCT="${2:-}"; shift 2 ;;
    --pool-device)
      POOL_DEVICE_ID="${2:-}"; shift 2 ;;
    --stash-device)
      STASH_DEVICE_ID="${2:-}"; shift 2 ;;
    --spot-check)
      SPOT_CHECK="${2:-}"; shift 2 ;;
    --hash)
      HASHES+=("${2:-}"); shift 2 ;;
    --hashes-file)
      while IFS= read -r line; do
        line="${line%%#*}"
        line="${line//[$'\t\r\n ']/}"
        [[ -z "$line" ]] && continue
        HASHES+=("$line")
      done < "${2:-}"
      shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2 ;;
  esac
done

if [[ ${#HASHES[@]} -eq 0 ]]; then
  HASHES=(
    "af43288cf64092870cbc8281ece7aff703299ca8547d336026ba7e1d8e35cbc9"
    "6e5a1307eedb1526418cb6a456950a37749a5a7b1b4e10f0365025967392a70a"
    "51bb3ce9037522d97affc84fedd65e7e0154ab3cd360f0bfe7121211451dc88f"
    "8277eae774b3591bafaf08d6917c797475f011d9fd4f450988264e308d9b35d8"
    "e8ab1ad3e87542dcd83e55dbb5ef8f45e5713e89a2cc0f91b8fc90b14ee460a0"
    "921dde75673bd27fbb5a044fe695119222cb06e52fd3d6c650d11189254aece2"
  )
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mkdir -p out/reports/rehome-pilot

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
    exit 10
  fi
  echo "pool_free_pct=${free_pct} required_min=${MIN_FREE_PCT}"
}

run_post_checks() {
  local plan_path="$1"
  local hash="$2"

  PYTHONPATH=src python - "$plan_path" "$DB_PATH" "$POOL_DEVICE_ID" "$hash" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

plan_path, db_path, pool_device_id, expected_hash = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
plan = json.loads(Path(plan_path).read_text())

# check #2: decision
if plan.get("decision") not in {"MOVE", "REUSE"}:
    raise SystemExit(f"check_failed decision={plan.get('decision')}")

# check #3: target exists + source state matches decision
source_path = Path(plan["source_path"])
target_path = Path(plan["target_path"])
decision = plan.get("decision")
if not target_path.exists():
    raise SystemExit(f"check_failed target_missing={target_path}")
if decision == "MOVE":
    if source_path.exists():
        raise SystemExit(f"check_failed source_still_exists={source_path}")
elif decision == "REUSE":
    # REUSE keeps source unless explicit cleanup flags are enabled at apply time.
    if not source_path.exists():
        raise SystemExit(f"check_failed reuse_source_missing_unexpectedly={source_path}")

# check #4: DB payload on pool complete
conn = sqlite3.connect(db_path)
try:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM payloads
        WHERE payload_hash = ? AND device_id = ? AND status = 'complete'
        """,
        (expected_hash, pool_device_id),
    ).fetchone()
    if not row or row[0] < 1:
        raise SystemExit("check_failed db_pool_payload_missing")
finally:
    conn.close()

print("checks_ok=decision,target_source,db_pool_payload")
PY
}

payload_counts() {
  local hash="$1"
  sqlite3 -separator ' ' "$DB_PATH" "
    SELECT
      SUM(CASE WHEN device_id = ${STASH_DEVICE_ID} AND status = 'complete' THEN 1 ELSE 0 END) AS stash_complete,
      SUM(CASE WHEN device_id = ${POOL_DEVICE_ID} AND status = 'complete' THEN 1 ELSE 0 END) AS pool_complete
    FROM payloads
    WHERE payload_hash = '${hash}';
  " | awk '{print ($1==""?0:$1) " " ($2==""?0:$2)}'
}

echo "batch_total=${#HASHES[@]}"

idx=0
for hash in "${HASHES[@]}"; do
  idx=$((idx + 1))
  stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
  prefix="${hash:0:12}"
  batch_log="out/reports/rehome-pilot/rehome-batch-${idx}-${prefix}-${stamp}.log"

  {
    echo "==== batch=${idx}/${#HASHES[@]} hash=${hash} ===="
    assert_pool_space

    echo "step=plan"
    plan_path="out/reports/rehome-pilot/rehome-pilot-${prefix}-${stamp}.json"
    PYTHONPATH=src python -m rehome.cli plan \
      --demote \
      --payload-hash "$hash" \
      --catalog "$DB_PATH" \
      --seeding-root /stash/media \
      --seeding-root /data/media \
      --seeding-root /pool/data \
      --library-root /stash/media \
      --library-root /data/media \
      --stash-device "$STASH_DEVICE_ID" \
      --pool-device "$POOL_DEVICE_ID" \
      --stash-seeding-root /stash/media/torrents/seeding \
      --pool-seeding-root /pool/data/seeds \
      --pool-payload-root /pool/data/seeds \
      --output "$plan_path"

    if [[ ! -f "$plan_path" ]]; then
      echo "ERROR: plan_path_not_found" >&2
      exit 20
    fi

    decision="$(PYTHONPATH=src python - "$plan_path" <<'PY'
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
print(plan.get("decision",""))
PY
)"
    read -r stash_complete pool_complete <<<"$(payload_counts "$hash")"
    echo "payload_counts stash_complete=${stash_complete} pool_complete=${pool_complete} decision=${decision}"

    if [[ "$pool_complete" -ge 1 && "$stash_complete" -eq 0 ]]; then
      echo "skip_ok already_done hash=${hash} reason=pool_complete_and_no_stash_payload"
      continue
    fi

    if [[ "$decision" == "BLOCK" ]]; then
      echo "ERROR: blocked_and_not_already_done hash=${hash}" >&2
      exit 25
    fi

    echo "step=dryrun_apply plan=${plan_path}"
    PYTHONPATH=src python -u -m rehome.cli apply "$plan_path" --dryrun --catalog "$DB_PATH" --spot-check "$SPOT_CHECK"

    echo "step=live_apply plan=${plan_path}"
    set +e
    PYTHONPATH=src python -u -m rehome.cli apply "$plan_path" --force --catalog "$DB_PATH" --spot-check "$SPOT_CHECK"
    rc=$?
    set -e

    # check #1: apply exit status
    if [[ $rc -ne 0 ]]; then
      echo "ERROR: apply_failed rc=${rc}" >&2
      exit 30
    fi

    echo "step=post_checks"
    run_post_checks "$plan_path" "$hash"

    echo "batch_ok=${idx} hash=${hash}"
  } 2>&1 | tee "$batch_log"

done

echo "all_batches_ok=${#HASHES[@]}"
