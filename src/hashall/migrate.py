# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
from pathlib import Path
from datetime import datetime, UTC

def ensure_migration_table(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename TEXT PRIMARY KEY,
        applied_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()

def get_applied_migrations(conn):
    ensure_migration_table(conn)
    return {row["filename"] for row in conn.execute("SELECT filename FROM schema_migrations")}

def apply_migrations(db_path: Path, migrations_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_migration_table(conn)

    applied = get_applied_migrations(conn)

    for sql_file in sorted(migrations_path.glob("*.sql")):
        name = sql_file.name
        if name in applied:
            continue

        sql = sql_file.read_text()
        try:
            print(f"🔧 Applying migration: {name}")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
                (name, datetime.now(UTC).isoformat())
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column name" in msg or "already exists" in msg:
                print(f"⚠️  Skipping migration {name} (already applied based on error: {e})")
                conn.execute("INSERT OR IGNORE INTO schema_migrations (filename) VALUES (?)", (name,))
                conn.commit()
            else:
                print(f"❌ Migration failed: {name}\n{e}")
                raise
