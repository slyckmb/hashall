#!/usr/bin/env python3
# filehash_tool.py

import os
import sys
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = str(Path.home() / ".filehash.db")
LOGFILE = Path.home() / ".filehash.log"
PARTIAL_SIZE = 4096
VERBOSE = "--verbose" in sys.argv


def log(msg):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {msg}"
    with open(LOGFILE, "a") as f:
        f.write(full_msg + "\n")
    if VERBOSE:
        print(full_msg)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_hashes (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            size INTEGER,
            mtime REAL,
            partial_sha1 TEXT,
            full_sha1 TEXT
        )
    """)
    conn.commit()
    conn.close()


def compute_partial_sha1(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read(PARTIAL_SIZE)).hexdigest()
    except Exception as e:
        log(f"[ERROR] Failed partial hash on {path}: {e}")
        return None


def compute_full_sha1(path):
    h = hashlib.sha1()
    try:
        with open(path, 'rb') as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        log(f"[ERROR] Failed full hash on {path}: {e}")
        return None


def index_file(path):
    try:
        stat = os.stat(path)
        size = stat.st_size
        mtime = stat.st_mtime
        partial = compute_partial_sha1(path)
        if not partial:
            return None
        return (str(path), size, mtime, partial)
    except Exception as e:
        log(f"[ERROR] Failed stat on {path}: {e}")
        return None


def save_results(results):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for res in results:
        if res:
            cur.execute("""
                INSERT OR REPLACE INTO file_hashes (path, size, mtime, partial_sha1)
                VALUES (?, ?, ?, ?)
            """, res)
    conn.commit()
    conn.close()


def scan_directory(base_path, max_workers=8):
    base_path = Path(base_path)
    all_files = [p for p in base_path.rglob('*') if p.is_file()]
    log(f"[SCAN] {len(all_files)} files in {base_path}")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(index_file, f): f for f in all_files}
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)

    save_results(results)
    log(f"[DONE] {len(results)} files indexed in {base_path}")


def verify_full_hashes():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT partial_sha1 FROM file_hashes GROUP BY partial_sha1 HAVING COUNT(*) > 1")
    partials = cur.fetchall()

    total_verified = 0
    for (partial,) in partials:
        cur.execute("SELECT id, path FROM file_hashes WHERE partial_sha1 = ? AND full_sha1 IS NULL", (partial,))
        for file_id, path in cur.fetchall():
            if not os.path.exists(path):
                continue
            full_sha = compute_full_sha1(path)
            if full_sha:
                cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE id = ?", (full_sha, file_id))
                log(f"[VERIFY] {path} -> {full_sha[:10]}...")
                total_verified += 1

    conn.commit()
    conn.close()
    log(f"✅ Verified full hashes for {total_verified} files.")


def clean_missing_paths():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM file_hashes")
    rows = cur.fetchall()

    deleted = 0
    for file_id, path in rows:
        if not os.path.exists(path):
            cur.execute("DELETE FROM file_hashes WHERE id = ?", (file_id,))
            log(f"[CLEAN] Removed: {path}")
            deleted += 1

    conn.commit()
    conn.close()
    log(f"🧹 Cleaned {deleted} entries from the DB.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: filehash_tool.py [scan DIR | verify | clean] [--verbose]")
        sys.exit(1)

    init_db()

    mode = sys.argv[1]
    if mode == "scan" and len(sys.argv) >= 3:
        scan_directory(sys.argv[2])
    elif mode == "verify":
        verify_full_hashes()
    elif mode == "clean":
        clean_missing_paths()
    else:
        print("Invalid command or missing argument.")
        sys.exit(1)
