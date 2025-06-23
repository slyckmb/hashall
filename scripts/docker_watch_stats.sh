# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406
#!/bin/bash
set -e

DB_FILE="${1:-/mnt/media/.filehash.db}"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: $0 [/path/to/filehash.db]"
  echo "Watch and report stats for a running hashall DB (inside or outside container)."
  exit 0
fi

if [ ! -f "$DB_FILE" ]; then
  echo "❌ Database file not found at $DB_FILE"
  exit 1
fi

watch -n 5 "
echo -e '\n📊 Hashall DB Stats (Updated: \$(date +%H:%M:%S))'
echo '--------------------------------------------------'
sqlite3 \"$DB_FILE\" \"
SELECT   (SELECT COUNT(*) FROM file_hashes),
  (SELECT COUNT(*) FROM file_hashes WHERE full_sha1 IS NOT NULL),
  (SELECT COUNT(*) FROM file_hashes WHERE is_hardlink = 1)
;\" | awk -F\"|\" '{
  total=\$1; full=\$2; hl=\$3;
  pending = total - full;
  percent = (total > 0) ? (full / total) * 100 : 0;
  printf \"Total files:        %d\\n\", total;
  printf \"Full hashes:        %d\\n\", full;
  printf \"Hardlinks:          %d\\n\", hl;
  printf \"Pending verify:     %d\\n\", pending;
  printf \"Verified %%:         %.2f%%\\n\", percent;
}'"
