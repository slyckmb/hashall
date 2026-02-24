#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-23_normalize-live-prefix-hash-sync-replan_with-logs.sh --plan PLAN.json [options]

What it does:
  1) Reads skipped source_path rows from a normalize plan.
  2) Resolves current live qB roots from torrent_instances (save_path + root_name).
  3) Hash-upgrades those exact roots via one payload sync call.
  4) Rebuilds normalize plan.

Options:
  --plan PATH               Input normalize plan JSON with skipped entries (required)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --pool-device ID          Pool device_id (default: 44)
  --pool-root PATH          Pool seeding root (default: /pool/data/seeds)
  --stash-root PATH         Stash seeding root hint (default: /stash/media/torrents/seeding)
  --limit N                 Normalize candidate limit (default: 0 = all)
  --all-mismatches          Include non-flat mismatches (default: flat-only on)
  --output PATH             New plan output JSON path (default: auto timestamped)
  --hash-progress MODE      Hash progress mode: auto|minimal|full (default: auto)
  -h, --help                Show help
USAGE
}

INPUT_PLAN=""
DB_PATH="/home/michael/.hashall/catalog.db"
POOL_DEVICE="44"
POOL_ROOT="/pool/data/seeds"
STASH_ROOT="/stash/media/torrents/seeding"
LIMIT="0"
FLAT_ONLY="1"
PLAN_OUTPUT=""
HASH_PROGRESS="auto"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) INPUT_PLAN="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE="${2:-}"; shift 2 ;;
    --pool-root) POOL_ROOT="${2:-}"; shift 2 ;;
    --stash-root) STASH_ROOT="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --all-mismatches) FLAT_ONLY="0"; shift ;;
    --output) PLAN_OUTPUT="${2:-}"; shift 2 ;;
    --hash-progress) HASH_PROGRESS="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$INPUT_PLAN" ]]; then
  echo "Missing required --plan" >&2
  usage
  exit 2
fi
if [[ ! -f "$INPUT_PLAN" ]]; then
  echo "Plan not found: $INPUT_PLAN" >&2
  exit 2
fi
if [[ "$HASH_PROGRESS" != "auto" && "$HASH_PROGRESS" != "minimal" && "$HASH_PROGRESS" != "full" ]]; then
  echo "Invalid --hash-progress: $HASH_PROGRESS (expected auto|minimal|full)" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

export PYTHONUNBUFFERED=1
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
run_log="${log_dir}/rehome-normalize-live-prefix-sync-run-${stamp}.log"
sync_log="${log_dir}/rehome-normalize-live-prefix-sync-hash-${stamp}.log"
plan_log="${log_dir}/rehome-normalize-live-prefix-sync-plan-${stamp}.log"
prefix_file="/tmp/rehome-live-prefixes-${stamp}.txt"

if [[ -z "$PLAN_OUTPUT" ]]; then
  PLAN_OUTPUT="${log_dir}/rehome-plan-normalize-live-prefix-sync-${stamp}.json"
fi

HASHALL_SEMVER="$(PYTHONPATH=src python - <<'PY'
from hashall import __version__
print(__version__)
PY
)"
REHOME_SEMVER="$(PYTHONPATH=src python - <<'PY'
from rehome import __version__
print(__version__)
PY
)"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo "tool_semver_hashall=${HASHALL_SEMVER} tool_semver_rehome=${REHOME_SEMVER} git_sha=${GIT_SHA}" | tee "$run_log"
echo "run_id=${stamp} step=live-prefix-hash-sync-replan input_plan=${INPUT_PLAN}" | tee -a "$run_log"

echo "step=derive_live_prefixes cmd=python3/sqlite3" | tee -a "$run_log"
PLAN_IN="$INPUT_PLAN" DB_PATH="$DB_PATH" PREFIX_FILE="$prefix_file" python3 - <<'PY' 2>&1 | tee -a "$run_log"
import json
import os
import sqlite3
from pathlib import Path

plan = Path(os.environ["PLAN_IN"])
db_path = os.environ["DB_PATH"]
prefix_file = Path(os.environ["PREFIX_FILE"])
doc = json.loads(plan.read_text(encoding="utf-8"))
skipped = doc.get("skipped", [])
root_names = sorted({Path(item.get("source_path", "")).name for item in skipped if item.get("source_path")})

conn = sqlite3.connect(db_path)
rows = []
for root_name in root_names:
    query = """
        SELECT DISTINCT save_path || '/' || root_name
        FROM torrent_instances
        WHERE root_name = ?
        ORDER BY 1
    """
    rows.extend(row[0] for row in conn.execute(query, (root_name,)).fetchall())
conn.close()

prefixes = sorted(set(x for x in rows if x))
prefix_file.write_text("".join(f"{p}\n" for p in prefixes), encoding="utf-8")
print(f"skipped_root_names={len(root_names)}")
print(f"live_prefixes={len(prefixes)}")
print(f"prefix_file={prefix_file}")
PY

prefix_count="$(wc -l < "$prefix_file" | tr -d ' ')"
echo "live_prefix_count=${prefix_count}" | tee -a "$run_log"
if [[ "$prefix_count" == "0" ]]; then
  echo "No live prefixes resolved from skipped root names" | tee -a "$run_log"
  exit 1
fi

echo "step=payload_sync cmd=python -m hashall.cli payload sync" | tee -a "$run_log"
{
  PYTHONPATH=src python -m hashall.cli payload sync \
    --db "$DB_PATH" \
    --path-prefix-file "$prefix_file" \
    --upgrade-missing \
    --parallel \
    --hash-progress "$HASH_PROGRESS" \
    --low-priority
} 2>&1 | tee "$sync_log" | tee -a "$run_log"

echo "step=replan cmd=make rehome-normalize-plan" | tee -a "$run_log"
{
  make rehome-normalize-plan \
    "REHOME_CATALOG=${DB_PATH}" \
    "REHOME_POOL_DEVICE=${POOL_DEVICE}" \
    "REHOME_NORMALIZE_POOL_ROOT=${POOL_ROOT}" \
    "REHOME_NORMALIZE_STASH_ROOT=${STASH_ROOT}" \
    "REHOME_NORMALIZE_LIMIT=${LIMIT}" \
    "REHOME_NORMALIZE_FLAT_ONLY=${FLAT_ONLY}" \
    "REHOME_NORMALIZE_PRINT_SKIPPED=1" \
    "REHOME_NORMALIZE_REFRESH=0" \
    "REHOME_NORMALIZE_OUTPUT=${PLAN_OUTPUT}"
} 2>&1 | tee "$plan_log" | tee -a "$run_log"

echo "plan_output=${PLAN_OUTPUT}" | tee -a "$run_log"
echo "prefix_file=${prefix_file}" | tee -a "$run_log"
echo "run_log=${run_log}" | tee -a "$run_log"
echo "sync_log=${sync_log}" | tee -a "$run_log"
echo "plan_log=${plan_log}" | tee -a "$run_log"
