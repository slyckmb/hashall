#!/bin/bash
set -e

DB_PATH="${1:-$HOME/.hashall/hashall.sqlite3}"
DB_PATH="$(realpath "$DB_PATH")"

if [[ ! -f "$DB_PATH" ]]; then
  echo "❌ No database found at $DB_PATH"
  exit 1
fi

HAS_INODE=$(sqlite3 "$DB_PATH" "PRAGMA table_info(files);" | grep -c '|inode|')

TMP_SCRIPT="/tmp/hashdash-$$.sh"

cat > "$TMP_SCRIPT" <<EOF
#!/bin/bash
echo -e "\\n📊 Hash-Dash — Hashall DB Stats (Updated: \$(date +%H:%M:%S))"
echo "---------------------------------------------------------------"
EOF

if [[ "$HAS_INODE" -eq 0 ]]; then
cat >> "$TMP_SCRIPT" <<EOF
sqlite3 -cmd "PRAGMA busy_timeout=2000;" "$DB_PATH" "
SELECT 
  (SELECT COUNT(*) FROM files),
  (SELECT COUNT(*) FROM files WHERE sha1 IS NOT NULL)
;" | awk -F"|" '{
  total=\$1; full=\$2;
  pending = total - full;
  percent = (total > 0) ? (full / total) * 100 : 0;
  printf "Total files:        %d\\n", total;
  printf "Full hashes:        %d\\n", full;
  printf "Hardlinks:          N/A\\n";
  printf "Pending verify:     %d\\n", pending;
  printf "Verified %%:         %.2f%%\\n", percent;
}'
EOF
else
cat >> "$TMP_SCRIPT" <<EOF
sqlite3 -cmd "PRAGMA busy_timeout=2000;" "$DB_PATH" "
SELECT 
  (SELECT COUNT(*) FROM files),
  (SELECT COUNT(*) FROM files WHERE sha1 IS NOT NULL),
  (SELECT COUNT(*) FROM (
    SELECT inode FROM files GROUP BY inode HAVING COUNT(*) > 1
  ))
;" | awk -F"|" '{
  total=\$1; full=\$2; hl=\$3;
  pending = total - full;
  percent = (total > 0) ? (full / total) * 100 : 0;
  printf "Total files:        %d\\n", total;
  printf "Full hashes:        %d\\n", full;
  printf "Hardlinks:          %d\\n", hl;
  printf "Pending verify:     %d\\n", pending;
  printf "Verified %%:         %.2f%%\\n", percent;
}'
EOF
fi

chmod +x "$TMP_SCRIPT"
watch -n 5 "$TMP_SCRIPT"
