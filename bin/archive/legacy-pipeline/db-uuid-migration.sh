#!/usr/bin/env bash
# Pre-rescan DB migration: fix stale dev-XX UUIDs → correct zfs-XXXX UUIDs
# MUST run before first rescan or files_63/files_64/files_60 will be orphaned.
APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

DB="$HOME/.hashall/catalog.db"

show_state() {
  sqlite3 "$DB" "SELECT device_alias, fs_uuid, device_id FROM devices ORDER BY device_alias;" | column -t -s '|'
}

echo "=== BEFORE ==="
show_state

SQL="UPDATE devices SET fs_uuid='zfs-8419032985536447641'  WHERE fs_uuid='dev-48';
UPDATE devices SET fs_uuid='zfs-4712618669768664543'  WHERE fs_uuid='dev-64';
UPDATE devices SET fs_uuid='zfs-5797458154432047011'  WHERE fs_uuid='dev-63';
UPDATE devices SET fs_uuid='zfs-10871975109605971833' WHERE fs_uuid='dev-46';
UPDATE devices SET fs_uuid='zfs-4264799641605205671'  WHERE fs_uuid='dev-60';
UPDATE devices SET fs_uuid='zfs-16709113306013097470' WHERE fs_uuid='dev-55';"

if $APPLY; then
  sqlite3 "$DB" "$SQL"
  echo "=== AFTER ==="
  show_state
  echo "Migration applied. Run db-refresh-step1 next."
else
  echo ""
  echo "DRY RUN — SQL that would be applied:"
  echo "$SQL"
  echo ""
  echo "Run with --apply to execute."
fi
