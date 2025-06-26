# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
import json
from dataclasses import dataclass
from typing import List
from pathlib import Path

def connect_db(path: Path):
    from hashall.migrate import apply_migrations  # Lazy import
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    apply_migrations(path, Path(__file__).parent / "migrations")
    return conn

def init_db_schema(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        size INTEGER,
        mtime REAL,
        scan_session_id TEXT
    )
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
