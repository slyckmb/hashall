#!/bin/bash

# Usage: ./hash_all.sh /path/to/scan
#        ./hash_all.sh --clean         # prune non-existent paths from DB

DB_PATH="$HOME/.filehashdb.sqlite"

if [ "$1" == "--clean" ]; then
  echo "🧹 Cleaning stale file entries from DB: $DB_PATH"
  sqlite3 "$DB_PATH" "DELETE FROM file_hashes WHERE NOT EXISTS (SELECT 1 FROM (SELECT path FROM file_hashes) WHERE path = file_hashes.path AND path IS NOT NULL AND path != '' AND NOT path GLOB '*[![:print:]]*');"
  echo "✅ Done."
  exit 0
fi

BASE_DIR="$1"
DATE="$(date +%F_%H-%M)"
TMP_CSV="/tmp/filehash_scan_$DATE.csv"

if [ -z "$BASE_DIR" ]; then
  echo "Usage: $0 /path/to/scan"
  exit 1
fi

echo "🔍 Scanning: $BASE_DIR"
echo "📦 Temp CSV: $TMP_CSV"
echo "💾 DB Path:  $DB_PATH"

find "$BASE_DIR" -type f -exec stat --format='%s,%Y,%i,%n' {} + \
  | while IFS=, read -r size mtime inode path; do
      sha1=$(sha1sum "$path" | awk '{print $1}')
      echo "$sha1,$size,$mtime,$inode,\"$path\",$(date +%s)"
    done > "$TMP_CSV"

sqlite3 "$DB_PATH" <<EOF
CREATE TABLE IF NOT EXISTS file_hashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha1 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    inode INTEGER,
    path TEXT NOT NULL UNIQUE,
    scanned_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sha1 ON file_hashes(sha1);
.mode csv
.separator ","
.import $TMP_CSV file_hashes
EOF

echo "✅ Scan complete. DB saved to: $DB_PATH"
