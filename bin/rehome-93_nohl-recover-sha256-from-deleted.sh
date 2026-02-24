#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-93_nohl-recover-sha256-from-deleted.sh [options]

Options:
  --db PATH             Catalog DB path (default: ~/.hashall/catalog.db)
  --root PATH           Root path used to infer device id (default: /pool/data)
  --device-id N         Override inferred device id
  --sample N            Number of candidate samples to print (default: 20)
  --log-dir PATH        Log directory (default: $HOME/.logs/hashall/reports/rehome-normalize)
  --output-prefix NAME  Log file prefix (default: nohl)
  --apply               Apply updates (default: dryrun)
  --debug               Print extra debug fields in sample output
  -h, --help            Show this help
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

DB_PATH="${DB_PATH:-$HOME/.hashall/catalog.db}"
ROOT_PATH="${ROOT_PATH:-/pool/data}"
DEVICE_ID="${DEVICE_ID:-}"
SAMPLE="${SAMPLE:-20}"
LOG_DIR="${LOG_DIR:-$HOME/.logs/hashall/reports/rehome-normalize}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
APPLY_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --root) ROOT_PATH="${2:-}"; shift 2 ;;
    --device-id) DEVICE_ID="${2:-}"; shift 2 ;;
    --sample) SAMPLE="${2:-}"; shift 2 ;;
    --log-dir) LOG_DIR="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --apply) APPLY_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required but not installed." >&2
  exit 2
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "DB not found: $DB_PATH" >&2
  exit 2
fi
if ! [[ "$SAMPLE" =~ ^[0-9]+$ ]]; then
  echo "Invalid --sample: $SAMPLE" >&2
  exit 2
fi

if [[ -z "$DEVICE_ID" ]]; then
  if [[ ! -d "$ROOT_PATH" ]]; then
    echo "Cannot infer device id; root path not found: $ROOT_PATH" >&2
    exit 2
  fi
  DEVICE_ID="$(stat -c %d "$ROOT_PATH")"
fi
if ! [[ "$DEVICE_ID" =~ ^[0-9]+$ ]]; then
  echo "Invalid device id: $DEVICE_ID" >&2
  exit 2
fi

TABLE_NAME="files_${DEVICE_ID}"

mkdir -p "$LOG_DIR"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${LOG_DIR}/${OUTPUT_PREFIX}-recover-sha256-${stamp}.log"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 93: Recover SHA256 from deleted rows"
echo "What this does: copy hashes into active rows for moved files on same inode."
hr
echo "run_id=${stamp} db=${DB_PATH} root=${ROOT_PATH} device_id=${DEVICE_ID} table=${TABLE_NAME} mode=$([[ $APPLY_MODE -eq 1 ]] && echo apply || echo dryrun)"
echo "run_log=${run_log}"

table_exists="$(
  sqlite3 "$DB_PATH" \
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='${TABLE_NAME}';"
)"
if [[ "${table_exists:-0}" != "1" ]]; then
  echo "Table not found: ${TABLE_NAME}" >&2
  exit 3
fi

count_sql="
WITH deleted_ranked AS (
  SELECT
    d.path,
    d.inode,
    d.size,
    d.mtime,
    d.quick_hash,
    d.sha1,
    d.sha256,
    ROW_NUMBER() OVER (
      PARTITION BY d.inode, d.size
      ORDER BY COALESCE(d.last_seen_at, '') DESC, d.rowid DESC
    ) AS rn
  FROM ${TABLE_NAME} d
  WHERE d.status='deleted'
    AND d.sha256 IS NOT NULL
    AND d.inode IS NOT NULL
    AND d.inode != 0
),
candidates AS (
  SELECT
    a.path AS active_path,
    d.path AS deleted_path,
    a.inode,
    a.size,
    a.quick_hash AS active_quick_hash,
    d.quick_hash AS deleted_quick_hash,
    a.mtime AS active_mtime,
    d.mtime AS deleted_mtime,
    d.sha1 AS deleted_sha1,
    d.sha256 AS deleted_sha256
  FROM ${TABLE_NAME} a
  JOIN deleted_ranked d
    ON d.rn = 1
   AND d.inode = a.inode
   AND d.size = a.size
  WHERE a.status='active'
    AND a.sha256 IS NULL
    AND a.inode IS NOT NULL
    AND a.inode != 0
    AND (
      (a.quick_hash IS NOT NULL AND d.quick_hash IS NOT NULL AND a.quick_hash = d.quick_hash)
      OR (a.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
      OR (d.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
    )
)
SELECT
  (SELECT COUNT(*) FROM ${TABLE_NAME} WHERE status='active' AND sha256 IS NULL) AS active_missing_sha,
  (SELECT COUNT(*) FROM ${TABLE_NAME} WHERE status='active' AND sha256 IS NOT NULL) AS active_with_sha,
  (SELECT COUNT(*) FROM ${TABLE_NAME} WHERE status='deleted' AND sha256 IS NOT NULL) AS deleted_with_sha,
  (SELECT COUNT(*) FROM candidates) AS recoverable_candidates;
"

read -r active_missing_before active_with_sha_before deleted_with_sha recoverable_candidates <<<"$(
  sqlite3 -separator ' ' "$DB_PATH" "$count_sql"
)"

echo "summary_before active_missing_sha=${active_missing_before} active_with_sha=${active_with_sha_before} deleted_with_sha=${deleted_with_sha} recoverable_candidates=${recoverable_candidates}"

if [[ "${recoverable_candidates:-0}" -eq 0 ]]; then
  hr
  echo "result=ok updated=0 reason=no_candidates run_log=${run_log}"
  hr
  exit 0
fi

sample_sql="
WITH deleted_ranked AS (
  SELECT
    d.path,
    d.inode,
    d.size,
    d.mtime,
    d.quick_hash,
    d.sha1,
    d.sha256,
    ROW_NUMBER() OVER (
      PARTITION BY d.inode, d.size
      ORDER BY COALESCE(d.last_seen_at, '') DESC, d.rowid DESC
    ) AS rn
  FROM ${TABLE_NAME} d
  WHERE d.status='deleted'
    AND d.sha256 IS NOT NULL
    AND d.inode IS NOT NULL
    AND d.inode != 0
),
candidates AS (
  SELECT
    a.path AS active_path,
    d.path AS deleted_path,
    a.inode,
    a.size,
    a.quick_hash AS active_quick_hash,
    d.quick_hash AS deleted_quick_hash,
    a.mtime AS active_mtime,
    d.mtime AS deleted_mtime,
    d.sha1 AS deleted_sha1,
    d.sha256 AS deleted_sha256
  FROM ${TABLE_NAME} a
  JOIN deleted_ranked d
    ON d.rn = 1
   AND d.inode = a.inode
   AND d.size = a.size
  WHERE a.status='active'
    AND a.sha256 IS NULL
    AND a.inode IS NOT NULL
    AND a.inode != 0
    AND (
      (a.quick_hash IS NOT NULL AND d.quick_hash IS NOT NULL AND a.quick_hash = d.quick_hash)
      OR (a.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
      OR (d.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
    )
)
SELECT active_path, deleted_path, inode, size, substr(deleted_sha256, 1, 16), active_quick_hash, deleted_quick_hash
FROM candidates
ORDER BY size DESC, active_path
LIMIT ${SAMPLE};
"

echo "sample_candidates_begin"
if [[ "$DEBUG_MODE" -eq 1 ]]; then
  sqlite3 -header -column "$DB_PATH" "$sample_sql"
else
  sqlite3 -separator '|' "$DB_PATH" "$sample_sql" | awk -F'|' '{
    printf "candidate inode=%s size=%s sha16=%s\n", $3, $4, $5;
    printf "  active=%s\n", $1;
    printf "  deleted=%s\n", $2;
  }'
fi
echo "sample_candidates_end"

if [[ "$APPLY_MODE" -ne 1 ]]; then
  hr
  echo "result=ok mode=dryrun recoverable_candidates=${recoverable_candidates} run_log=${run_log}"
  hr
  exit 0
fi

apply_sql="
BEGIN IMMEDIATE;
WITH deleted_ranked AS (
  SELECT
    d.path,
    d.inode,
    d.size,
    d.mtime,
    d.quick_hash,
    d.sha1,
    d.sha256,
    ROW_NUMBER() OVER (
      PARTITION BY d.inode, d.size
      ORDER BY COALESCE(d.last_seen_at, '') DESC, d.rowid DESC
    ) AS rn
  FROM ${TABLE_NAME} d
  WHERE d.status='deleted'
    AND d.sha256 IS NOT NULL
    AND d.inode IS NOT NULL
    AND d.inode != 0
),
candidates AS (
  SELECT
    a.path AS active_path,
    d.sha1 AS deleted_sha1,
    d.sha256 AS deleted_sha256
  FROM ${TABLE_NAME} a
  JOIN deleted_ranked d
    ON d.rn = 1
   AND d.inode = a.inode
   AND d.size = a.size
  WHERE a.status='active'
    AND a.sha256 IS NULL
    AND a.inode IS NOT NULL
    AND a.inode != 0
    AND (
      (a.quick_hash IS NOT NULL AND d.quick_hash IS NOT NULL AND a.quick_hash = d.quick_hash)
      OR (a.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
      OR (d.quick_hash IS NULL AND ABS(COALESCE(a.mtime, 0) - COALESCE(d.mtime, 0)) < 0.001)
    )
)
UPDATE ${TABLE_NAME} AS a
SET
  sha256 = (SELECT c.deleted_sha256 FROM candidates c WHERE c.active_path = a.path),
  sha1 = COALESCE(a.sha1, (SELECT c.deleted_sha1 FROM candidates c WHERE c.active_path = a.path)),
  hash_source = COALESCE(a.hash_source, 'inode-recovered'),
  last_modified_at = datetime('now')
WHERE a.status='active'
  AND a.sha256 IS NULL
  AND EXISTS (SELECT 1 FROM candidates c WHERE c.active_path = a.path);
SELECT changes();
COMMIT;
"

updated_rows="$(sqlite3 "$DB_PATH" "$apply_sql" | tail -n1 | tr -d '[:space:]')"
if [[ -z "$updated_rows" ]]; then
  updated_rows=0
fi

active_missing_after="$(
  sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM ${TABLE_NAME} WHERE status='active' AND sha256 IS NULL;"
)"
active_with_sha_after="$(
  sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM ${TABLE_NAME} WHERE status='active' AND sha256 IS NOT NULL;"
)"

echo "summary_after updated_rows=${updated_rows} active_missing_sha=${active_missing_after} active_with_sha=${active_with_sha_after}"
hr
echo "result=ok mode=apply updated_rows=${updated_rows} run_log=${run_log}"
hr
