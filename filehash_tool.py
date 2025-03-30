#!/usr/bin/env python3
# filehash_tool.py

import os
import hashlib
import sqlite3
import logging
import time
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from tqdm import tqdm

DB_PATH = str(Path.home() / ".filehash.db")
LOGFILE = Path.home() / ".filehash.log"
PARTIAL_SIZE = 4096

# Configure logger
logger = logging.getLogger("filehash_tool")
handler = logging.FileHandler(LOGFILE)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def log(msg):
    logger.info(msg)
    if VERBOSE:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def human_size(bytes):
    for unit in ['B','KB','MB','GB','TB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"


def human_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    elif m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def parse_args():
    parser = argparse.ArgumentParser(description="File Hashing Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan directory for file hashes")
    scan_parser.add_argument("directory", type=str, help="Directory to scan")

    subparsers.add_parser("verify", help="Verify full hashes for duplicate partials")
    subparsers.add_parser("clean", help="Remove DB entries for missing files")

    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    return parser.parse_args()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_hashes (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            size INTEGER,
            mtime REAL,
            inode INTEGER,
            owner INTEGER,
            file_group INTEGER,
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
        resolved_path = str(Path(path).resolve())
        stat = os.stat(resolved_path)
        partial = compute_partial_sha1(resolved_path)
        if not partial:
            return None
        return (
            resolved_path,
            stat.st_size,
            stat.st_mtime,
            stat.st_ino,
            stat.st_uid,
            stat.st_gid,
            partial
        )
    except Exception as e:
        log(f"[ERROR] Failed indexing {path}: {e}")
        return None


def save_results(results):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for res in results:
        if res:
            cur.execute("""
                INSERT OR REPLACE INTO file_hashes (
                    path, size, mtime, inode, owner, file_group, partial_sha1
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, res)
    conn.commit()
    conn.close()


def scan_directory(base_path, max_workers=8):
    start = time.perf_counter()
    base_path = Path(base_path)
    all_files = [p for p in base_path.rglob('*') if p.is_file()]
    log(f"[SCAN] {len(all_files)} files in {base_path}")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(index_file, f): f for f in all_files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Indexing"):
            res = future.result()
            if res:
                results.append(res)

    save_results(results)
    duration = time.perf_counter() - start
    log(f"[DONE] {len(results)} files indexed in {base_path} in {human_time(duration)}")


def verify_full_hashes():
    start = time.perf_counter()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT partial_sha1 FROM file_hashes
        GROUP BY partial_sha1 HAVING COUNT(*) > 1
    """)
    partials = cur.fetchall()

    total_verified = 0
    for (partial,) in tqdm(partials, desc="Verifying", unit="group"):
        cur.execute("""
            SELECT id, path FROM file_hashes
            WHERE partial_sha1 = ? AND full_sha1 IS NULL
        """, (partial,))
        for file_id, path in cur.fetchall():
            if not os.path.exists(path):
                continue
            full_sha = compute_full_sha1(path)
            if full_sha:
                cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE id = ?", (full_sha, file_id))
                if VERBOSE:
                    log(f"[VERIFY] {path} -> {full_sha[:10]}...")
                total_verified += 1

    conn.commit()
    conn.close()
    duration = time.perf_counter() - start
    log(f"✅ Verified full hashes for {total_verified} files in {human_time(duration)}.")


def clean_missing_paths():
    start = time.perf_counter()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM file_hashes")
    rows = cur.fetchall()

    deleted = 0
    for file_id, path in tqdm(rows, desc="Cleaning", unit="file"):
        if not os.path.exists(path):
            cur.execute("DELETE FROM file_hashes WHERE id = ?", (file_id,))
            if VERBOSE:
                log(f"[CLEAN] Removed: {path}")
            deleted += 1

    conn.commit()
    conn.close()
    duration = time.perf_counter() - start
    log(f"🧹 Cleaned {deleted} entries from the DB in {human_time(duration)}.")


if __name__ == "__main__":
    args = parse_args()
    VERBOSE = args.verbose

    init_db()

    try:
        if args.command == "scan":
            scan_directory(args.directory)
        elif args.command == "verify":
            verify_full_hashes()
        elif args.command == "clean":
            clean_missing_paths()
    except KeyboardInterrupt:
        log(f"[INTERRUPTED] {args.command} cancelled by user.")
        sys.exit(1)
