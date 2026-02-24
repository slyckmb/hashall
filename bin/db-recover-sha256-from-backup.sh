#!/usr/bin/env bash
# Recover SHA256 values from pre-rotation backup into current DB.
# Matches on path + size + mtime — safe to run without re-reading any files.
# Run AFTER step 3 (dupes), BEFORE step 4 (payload sync).
set -euo pipefail

DB="$HOME/.hashall/catalog.db"
BAK="$HOME/.hashall/catalog.db.bak.20260223-132115"

if [[ ! -f "$BAK" ]]; then
  echo "ERROR: backup not found at $BAK"
  exit 1
fi

WT="/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028"
LOGDIR="$HOME/.logs/hashall/reports/db-refresh"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/sha256-recovery-$(date +%Y%m%d-%H%M%S).log"

echo "================================================================" | tee -a "$LOGFILE"
echo "SHA256 RECOVERY from backup — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "source: $BAK" | tee -a "$LOGFILE"
echo "target: $DB" | tee -a "$LOGFILE"
echo "log:    $LOGFILE" | tee -a "$LOGFILE"
echo "================================================================" | tee -a "$LOGFILE"

# --- backup current DB before making any changes ---
echo "" | tee -a "$LOGFILE"
echo "--- backing up current DB --- $(date '+%F %T')" | tee -a "$LOGFILE"
PREBAK="${DB}.bak.pre-sha256-recovery-$(date +%Y%m%d-%H%M%S)"
cp "$DB" "$PREBAK"
echo "backup: $PREBAK" | tee -a "$LOGFILE"

# --- dry-run: count recoverable rows ---
echo "" | tee -a "$LOGFILE"
echo "--- dry-run: counting recoverable SHA256 values ---" | tee -a "$LOGFILE"
sqlite3 "$DB" "
ATTACH '$BAK' AS bak;
SELECT COUNT(*) || ' sha256 values recoverable (path+size+mtime match)'
FROM files_44 cur
JOIN bak.files_49 old
  ON cur.path = old.path
 AND cur.size = old.size
 AND cur.mtime = old.mtime
WHERE cur.sha256 IS NULL
  AND old.sha256 IS NOT NULL;
" 2>&1 | tee -a "$LOGFILE"

# --- apply recovery ---
echo "" | tee -a "$LOGFILE"
echo "--- applying recovery --- $(date '+%F %T')" | tee -a "$LOGFILE"
sqlite3 "$DB" "
ATTACH '$BAK' AS bak;
UPDATE files_44
SET sha256 = (
  SELECT old.sha256
  FROM bak.files_49 old
  WHERE old.path  = files_44.path
    AND old.size  = files_44.size
    AND old.mtime = files_44.mtime
    AND old.sha256 IS NOT NULL
)
WHERE sha256 IS NULL
  AND EXISTS (
    SELECT 1 FROM bak.files_49 old
    WHERE old.path  = files_44.path
      AND old.size  = files_44.size
      AND old.mtime = files_44.mtime
      AND old.sha256 IS NOT NULL
  );
SELECT changes() || ' rows updated';
" 2>&1 | tee -a "$LOGFILE"

# --- verify ---
echo "" | tee -a "$LOGFILE"
echo "--- remaining NULL sha256 after recovery --- $(date '+%F %T')" | tee -a "$LOGFILE"
sqlite3 "$DB" "
SELECT 'files_44 (stash)' as tbl,
  COUNT(*) as total,
  SUM(CASE WHEN sha256 IS NOT NULL THEN 1 ELSE 0 END) as has_sha256,
  SUM(CASE WHEN sha256 IS NULL     THEN 1 ELSE 0 END) as still_missing
FROM files_44;
" 2>&1 | tee -a "$LOGFILE"

echo "" | tee -a "$LOGFILE"
echo "RECOVERY DONE — $(date '+%F %T')" | tee -a "$LOGFILE"
echo "log: $LOGFILE" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
echo ">>> Paste output to Claude, then run step 4 (payload sync). <<<"
