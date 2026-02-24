#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-92_nohl-basics-payload-sync.sh [options]

Options:
  --mode MODE              map-only | upgrade-targeted | upgrade-full (default: map-only)
  --manifest PATH          noHL plan manifest (used by upgrade-targeted; default: latest)
  --path-prefix PATH       Additional payload sync prefix (repeatable)
  --path-prefix-file PATH  Additional payload sync prefix file
  --upgrade-order MODE     input | small-first (default: small-first)
  --upgrade-root-limit N   Limit queued upgrade roots (default: 0 = all)
  --upgrade-parallel 0|1   Enable parallel hashing during upgrade (default: 0)
  --workers N              Worker threads for --upgrade-parallel
  --hash-progress MODE     auto | minimal | full (default: full)
  --min-upgrade-gib N      Require --yes-upgrade when estimated upgrade bytes >= N GiB (default: 200)
  --yes-upgrade            Confirm heavy upgrade mode after preflight
  --output-prefix NAME     Output prefix (default: nohl)
  --db PATH                Catalog DB path (default: ~/.hashall/catalog.db)
  --qbit-url URL           qB URL (default: env QBIT_URL or http://localhost:9003)
  --qbit-user USER         qB user (default: env QBIT_USER or admin)
  --qbit-pass PASS         qB pass (default: env QBIT_PASS or adminpass)
  --low-priority 0|1       Use low priority mode (default: 1)
  --debug                  Verbose script debug output
  -h, --help               Show this help
USAGE
}

latest_manifest() {
  ls -1t $HOME/.logs/hashall/reports/rehome-normalize/nohl-plan-manifest-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
WORKERS="${WORKERS:-}"
LOW_PRIORITY="${LOW_PRIORITY:-1}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
MODE="${MODE:-map-only}"
MANIFEST_PATH=""
PATH_PREFIX_FILE=""
UPGRADE_ORDER="${UPGRADE_ORDER:-small-first}"
UPGRADE_ROOT_LIMIT="${UPGRADE_ROOT_LIMIT:-0}"
UPGRADE_PARALLEL="${UPGRADE_PARALLEL:-0}"
HASH_PROGRESS="${HASH_PROGRESS:-full}"
MIN_UPGRADE_GIB="${MIN_UPGRADE_GIB:-200}"
YES_UPGRADE="${YES_UPGRADE:-0}"
DEBUG_MODE=0
declare -a PATH_PREFIXES=("/stash/media" "/data/media" "/pool/data")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_PATH="${2:-}"; shift 2 ;;
    --path-prefix) PATH_PREFIXES+=("${2:-}"); shift 2 ;;
    --path-prefix-file) PATH_PREFIX_FILE="${2:-}"; shift 2 ;;
    --upgrade-order) UPGRADE_ORDER="${2:-}"; shift 2 ;;
    --upgrade-root-limit) UPGRADE_ROOT_LIMIT="${2:-}"; shift 2 ;;
    --upgrade-parallel) UPGRADE_PARALLEL="${2:-}"; shift 2 ;;
    --workers) WORKERS="${2:-}"; shift 2 ;;
    --hash-progress) HASH_PROGRESS="${2:-}"; shift 2 ;;
    --min-upgrade-gib) MIN_UPGRADE_GIB="${2:-}"; shift 2 ;;
    --yes-upgrade) YES_UPGRADE=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --qbit-url) QBIT_URL="${2:-}"; shift 2 ;;
    --qbit-user) QBIT_USER="${2:-}"; shift 2 ;;
    --qbit-pass) QBIT_PASS="${2:-}"; shift 2 ;;
    --low-priority) LOW_PRIORITY="${2:-}"; shift 2 ;;
    --debug) DEBUG_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "map-only" && "$MODE" != "upgrade-targeted" && "$MODE" != "upgrade-full" ]]; then
  echo "Invalid --mode: $MODE" >&2
  exit 2
fi
if [[ "$UPGRADE_ORDER" != "input" && "$UPGRADE_ORDER" != "small-first" ]]; then
  echo "Invalid --upgrade-order: $UPGRADE_ORDER" >&2
  exit 2
fi
if ! [[ "$UPGRADE_ROOT_LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --upgrade-root-limit: $UPGRADE_ROOT_LIMIT" >&2
  exit 2
fi
if [[ "$UPGRADE_PARALLEL" != "0" && "$UPGRADE_PARALLEL" != "1" ]]; then
  echo "Invalid --upgrade-parallel: $UPGRADE_PARALLEL" >&2
  exit 2
fi
if [[ "$LOW_PRIORITY" != "0" && "$LOW_PRIORITY" != "1" ]]; then
  echo "Invalid --low-priority: $LOW_PRIORITY" >&2
  exit 2
fi
if [[ "$HASH_PROGRESS" != "auto" && "$HASH_PROGRESS" != "minimal" && "$HASH_PROGRESS" != "full" ]]; then
  echo "Invalid --hash-progress: $HASH_PROGRESS" >&2
  exit 2
fi
if ! [[ "$MIN_UPGRADE_GIB" =~ ^[0-9]+$ ]]; then
  echo "Invalid --min-upgrade-gib: $MIN_UPGRADE_GIB" >&2
  exit 2
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-payload-sync-${stamp}.log"
targeted_prefix_file="${log_dir}/${OUTPUT_PREFIX}-payload-sync-targeted-prefixes-${stamp}.txt"
preflight_json="${log_dir}/${OUTPUT_PREFIX}-payload-sync-preflight-${stamp}.json"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 92: Basics payload sync"
echo "What this does: refresh torrent->payload mappings; optional hash-upgrade runs in explicit modes."
hr
echo "run_id=${stamp} step=basics-payload-sync mode=${MODE} db=${DB_PATH} qbit_url=${QBIT_URL} qbit_user=${QBIT_USER} workers=${WORKERS:-auto} low_priority=${LOW_PRIORITY} debug=${DEBUG_MODE}"

if [[ "$MODE" == "upgrade-targeted" ]]; then
  if [[ -z "$MANIFEST_PATH" ]]; then
    MANIFEST_PATH="$(latest_manifest)"
  fi
  if [[ -z "$MANIFEST_PATH" || ! -f "$MANIFEST_PATH" ]]; then
    echo "Missing noHL manifest for --mode upgrade-targeted. Pass --manifest or generate Phase 40 first." >&2
    exit 3
  fi
  PYTHONPATH=src MANIFEST_PATH="$MANIFEST_PATH" TARGET_PREFIX_FILE="$targeted_prefix_file" python - <<'PY'
import json
import os
from pathlib import Path

manifest_path = Path(os.environ["MANIFEST_PATH"])
target_file = Path(os.environ["TARGET_PREFIX_FILE"])
obj = json.loads(manifest_path.read_text(encoding="utf-8"))

prefixes = set()
for entry in obj.get("entries", []):
    if str(entry.get("status", "")).lower() not in {"ok", "resume"}:
        continue
    for key in ("source_path", "target_path"):
        raw = str(entry.get(key) or "").strip()
        if raw.startswith("/"):
            prefixes.add(raw)

target_file.write_text(
    "\n".join(sorted(prefixes)) + ("\n" if prefixes else ""),
    encoding="utf-8",
)
print(f"targeted_prefixes={len(prefixes)}")
print(f"targeted_prefix_file={target_file}")
PY
  PATH_PREFIX_FILE="$targeted_prefix_file"
fi

prefixes_csv="$(IFS=,; echo "${PATH_PREFIXES[*]}")"
PYTHONPATH=src \
DB_PATH="$DB_PATH" \
MODE="$MODE" \
PREFIXES_CSV="$prefixes_csv" \
PREFIX_FILE="$PATH_PREFIX_FILE" \
MIN_UPGRADE_GIB="$MIN_UPGRADE_GIB" \
YES_UPGRADE="$YES_UPGRADE" \
PREFLIGHT_JSON="$preflight_json" \
python - <<'PY'
import json
import os
import sqlite3
import sys
from pathlib import Path

from hashall.payload import summarize_missing_sha256_for_path

db_path = Path(os.environ["DB_PATH"])
mode = os.environ["MODE"]
prefixes = [p for p in os.environ.get("PREFIXES_CSV", "").split(",") if p]
prefix_file = os.environ.get("PREFIX_FILE", "").strip()
min_upgrade_gib = int(os.environ.get("MIN_UPGRADE_GIB", "200") or 200)
yes_upgrade = str(os.environ.get("YES_UPGRADE", "0")).strip() in {"1", "true", "yes", "on"}
preflight_json = Path(os.environ["PREFLIGHT_JSON"])

if prefix_file:
  pf = Path(prefix_file)
  if pf.exists():
    for raw in pf.read_text(encoding="utf-8").splitlines():
      raw = raw.strip()
      if raw and not raw.startswith("#"):
        prefixes.append(raw)

prefixes = sorted({p for p in prefixes if p.startswith("/")})
conn = sqlite3.connect(str(db_path))
rows = []
total_files = 0
total_bytes = 0
for root in prefixes:
  summary = summarize_missing_sha256_for_path(conn, root)
  files = int(summary.get("files", 0))
  byte_count = int(summary.get("bytes", 0))
  if files <= 0:
    continue
  rows.append({"root": root, "missing_files": files, "missing_bytes": byte_count})
  total_files += files
  total_bytes += byte_count
conn.close()

rows.sort(key=lambda item: item["missing_bytes"], reverse=True)
payload = {
  "mode": mode,
  "prefixes_total": len(prefixes),
  "roots_with_missing": len(rows),
  "missing_files_total": total_files,
  "missing_bytes_total": total_bytes,
  "top_roots": rows[:20],
}
preflight_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

gib = total_bytes / (1024 ** 3)
print(
  f"preflight mode={mode} prefixes={len(prefixes)} roots_with_missing={len(rows)} "
  f"missing_files={total_files} missing_gib={gib:.1f}"
)
for item in rows[:10]:
  print(
    f"preflight_top root={item['root']} files={item['missing_files']} "
    f"gib={item['missing_bytes'] / (1024 ** 3):.1f}"
  )
print(f"preflight_json={preflight_json}")

if mode != "map-only" and gib >= float(min_upgrade_gib) and not yes_upgrade:
  print(
    f"gate=upgrade_preflight status=blocked missing_gib={gib:.1f} "
    f"threshold_gib={float(min_upgrade_gib):.1f}"
  )
  sys.exit(4)
PY

if [[ "$MODE" != "map-only" ]]; then
  echo "gate=upgrade_preflight status=allowed yes_upgrade=${YES_UPGRADE} threshold_gib=${MIN_UPGRADE_GIB}"
fi

cmd=(
  python -m hashall.cli payload sync
  --db "$DB_PATH"
  --qbit-url "$QBIT_URL"
  --qbit-user "$QBIT_USER"
  --qbit-pass "$QBIT_PASS"
  --path-prefix /stash/media
  --path-prefix /data/media
  --path-prefix /pool/data
  --hash-progress "$HASH_PROGRESS"
)
for ((i = 3; i < ${#PATH_PREFIXES[@]}; i++)); do
  cmd+=(--path-prefix "${PATH_PREFIXES[$i]}")
done
if [[ -n "$PATH_PREFIX_FILE" ]]; then
  cmd+=(--path-prefix-file "$PATH_PREFIX_FILE")
fi
if [[ "$MODE" != "map-only" ]]; then
  cmd+=(--upgrade-missing --upgrade-order "$UPGRADE_ORDER" --upgrade-root-limit "$UPGRADE_ROOT_LIMIT")
  if [[ "$UPGRADE_PARALLEL" == "1" ]]; then
    cmd+=(--parallel)
  fi
fi
if [[ -n "$WORKERS" ]]; then
  cmd+=(--workers "$WORKERS")
fi
if [[ "$LOW_PRIORITY" == "1" ]]; then
  cmd+=(--low-priority)
fi

echo "cmd=PYTHONPATH=src ${cmd[*]}"
PYTHONPATH=src "${cmd[@]}"

hr
echo "result=ok step=basics-payload-sync mode=${MODE} run_log=${run_log}"
hr
