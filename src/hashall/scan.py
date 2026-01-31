# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import hashlib
import sqlite3
import uuid
from pathlib import Path
from tqdm import tqdm
from hashall.model import connect_db, init_db_schema

def compute_sha1(file_path):
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def scan_path(db_path: Path, root_path: Path, parallel: bool = False):
    conn = connect_db(db_path)
    init_db_schema(conn)
    cursor = conn.cursor()
    scan_id = str(uuid.uuid4())
    root_str = str(root_path)

    cursor.execute(
        "INSERT INTO scan_sessions (scan_id, root_path) VALUES (?, ?)",
        (scan_id, root_str),
    )
    scan_session_id = cursor.lastrowid

    print(f"✅ Scan session started: {scan_id} — {root_path}")
    file_paths = [
        os.path.join(dirpath, filename)
        for dirpath, _, filenames in os.walk(root_path)
        for filename in filenames
    ]

    for file_path in tqdm(file_paths, desc="📦 Scanning"):
        try:
            stat = os.stat(file_path)
            rel_path = str(Path(file_path).relative_to(root_path))
            sha1 = compute_sha1(file_path)
            cursor.execute("""
                INSERT OR REPLACE INTO files (path, size, mtime, sha1, scan_session_id, inode, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rel_path, stat.st_size, stat.st_mtime, sha1, scan_session_id, stat.st_ino, stat.st_dev))
        except Exception as e:
            print(f"⚠️ Could not process: {file_path} ({e})")

    conn.commit()
    print("📦 Scan complete.")
