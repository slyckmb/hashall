# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
import json
from dataclasses import dataclass
from typing import List
from pathlib import Path
from urllib.parse import quote

def connect_db(path: Path, read_only: bool = False, apply_migrations: bool = True):
    """
    Connect to the catalog DB.

    By default this opens the DB read-write, enables WAL, and applies migrations.
    For analysis-only / dry-run workflows, use read_only=True to avoid *any* DB writes.
    """
    from hashall.migrate import apply_migrations as _apply_migrations  # Lazy import

    if read_only:
        # Use SQLite URI mode=ro so SQLite doesn't attempt to create/modify files.
        # Note: for paths with spaces/special chars we percent-encode.
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)

    # Enable WAL mode for better concurrency
    # - Allows multiple readers + one writer simultaneously
    # - Readers don't block writers (and vice versa)
    # - Better performance for concurrent scans
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout

    conn.row_factory = sqlite3.Row
    if apply_migrations:
        _apply_migrations(path, Path(__file__).parent / "migrations")
    return conn

def init_db_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS scan_sessions (
        id INTEGER PRIMARY KEY,
        scan_id TEXT UNIQUE NOT NULL,
        root_path TEXT NOT NULL,
        started_at TEXT DEFAULT CURRENT_TIMESTAMP,
        treehash TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        path TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        sha1 TEXT,
        sha256 TEXT,
        scan_session_id INTEGER,
        PRIMARY KEY (path, scan_session_id),
        FOREIGN KEY (scan_session_id) REFERENCES scan_sessions(id)
    )
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_files_scan_session ON files(scan_session_id)
    """)
    conn.commit()

def fetch_scan_results(db_path):
    conn = connect_db(db_path)
    rows = conn.execute("SELECT * FROM files").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def load_json_scan_into_db(conn, json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        raise ValueError("Expected JSON object, got list.")
    scan_id = data.get("scan_id", "json_import")
    for item in data.get("files", []):
        p = item.get("path") or item.get("file") or item.get("relpath")
        size = item.get("size") or item.get("bytes") or item.get("length", 0)
        mtime = item.get("mtime") or item.get("timestamp", 0)
        if p is None:
            print(f"⚠️ Skipping item with no path: {item}")
            continue
        conn.execute(
            "INSERT OR IGNORE INTO files (path, size, mtime, scan_session_id) VALUES (?, ?, ?, ?)",
            (p, size, mtime, scan_id)
        )
    conn.commit()
    return scan_id

@dataclass
class DiffReportEntry:
    path: str
    status: str

@dataclass
class DiffReport:
    entries: List[DiffReportEntry]
