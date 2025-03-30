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
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
from tqdm import tqdm
import signal
import psutil

DB_PATH = str(Path.home() / ".filehash.db")
LOGFILE = Path.home() / ".filehash.log"
PARTIAL_SIZE = 4096
INTERRUPTED = False

# Configure logger
logger = logging.getLogger("filehash_tool")
handler = logging.FileHandler(LOGFILE)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def recommended_workers():
    cpu_count = os.cpu_count()
    mem = psutil.virtual_memory()
    ram_gb = mem.total / (1024 ** 3)
    return max(2, min(cpu_count or 4, int(ram_gb // 2)))  # 1 worker per 2GB, max = cpu count

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


def handle_interrupt():
    global INTERRUPTED
    INTERRUPTED = True
    log("[INTERRUPTED] Caught Ctrl+C, cleaning up...")


def parse_args():
    parser = argparse.ArgumentParser(description="File Hashing Tool")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan directory for file hashes")
    scan_parser.add_argument("directory", type=str, help="Directory to scan")

    verify_parser = subparsers.add_parser("verify", help="Verify full hashes for duplicate partials")
    verify_parser.add_argument(
        "--workers",
        type=int,
        default=recommended_workers(),
        help=f"Number of worker processes (default: recommended based on system: {recommended_workers()})"
    )

    subparsers.add_parser("clean", help="Remove DB entries for missing files")
    subparsers.add_parser("detect-hardlinks", help="Mark entries with identical (dev, inode) as hardlinks")

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
            dev INTEGER,
            owner INTEGER,
            file_group INTEGER,
            partial_sha1 TEXT,
            full_sha1 TEXT,
            is_hardlink INTEGER DEFAULT 0
        )
    """)
    conn.commit()

    # Schema auto-upgrade check
    cur.execute("PRAGMA table_info(file_hashes)")
    existing = {row[1] for row in cur.fetchall()}
    expected = {
        "inode": "INTEGER",
        "dev": "INTEGER",
        "owner": "INTEGER",
        "file_group": "INTEGER",
        "is_hardlink": "INTEGER DEFAULT 0"
    }
    for col, col_type in expected.items():
        if col not in existing:
            log(f"[DB] Adding missing column: {col}")
            cur.execute(f"ALTER TABLE file_hashes ADD COLUMN {col} {col_type}")

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
            stat.st_dev,
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
                    path, size, mtime, inode, dev, owner, file_group, partial_sha1
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, res)
    conn.commit()
    conn.close()


def scan_directory(base_path, max_workers=8):
    start = time.perf_counter()
    base_path = Path(base_path)
    all_files = [p for p in base_path.rglob('*') if p.is_file()]
    log(f"[SCAN] {len(all_files)} files in {base_path}")

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(index_file, f): f for f in all_files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Indexing", smoothing=0.3):
            if INTERRUPTED:
                break
            res = future.result()
            if res:
                results.append(res)

    save_results(results)
    duration = time.perf_counter() - start
    log(f"[DONE] {len(results)} files indexed in {base_path} in {human_time(duration)}")


def verify_worker(row):
    file_id, path = row
    if not os.path.exists(path):
        return None
    full_sha = compute_full_sha1(path)
    return (full_sha, file_id, path) if full_sha else None


def verify_full_hashes(workers):
    start = time.perf_counter()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, path, dev, inode, partial_sha1 FROM file_hashes
        WHERE full_sha1 IS NULL
        AND partial_sha1 IN (
            SELECT partial_sha1 FROM file_hashes
            GROUP BY partial_sha1 HAVING COUNT(*) > 1
        )
    """)
    rows = cur.fetchall()

    cur.execute("SELECT dev, inode, full_sha1 FROM file_hashes WHERE full_sha1 IS NOT NULL")
    known_fulls = {(d, i): sha for d, i, sha in cur.fetchall()}
    conn.close()

    updated = []
    hardlinked = []
    todo = []

    for file_id, path, dev, inode, partial in rows:
        key = (dev, inode)
        if key in known_fulls:
            hardlinked.append((known_fulls[key], file_id))
            continue
        todo.append((file_id, path))

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(verify_worker, row): row for row in todo}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Verifying", unit="file", smoothing=0.3):
            if INTERRUPTED:
                executor.shutdown(wait=False, cancel_futures=True)
                break
            res = future.result()
            if res:
                updated.append(res)
                # if VERBOSE:
                #     log(f"[VERIFY] {res[2]} -> {res[0][:10]}...")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for full_sha, file_id, _ in updated:
        cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE id = ?", (full_sha, file_id))

    for full_sha, file_id in hardlinked:
        cur.execute("UPDATE file_hashes SET full_sha1 = ?, is_hardlink = 1 WHERE id = ?", (full_sha, file_id))

    conn.commit()
    conn.close()
    duration = time.perf_counter() - start
    log(f"✅ Verified full hashes for {len(updated)} files and inferred {len(hardlinked)} hardlinks in {human_time(duration)}.")
    if INTERRUPTED:
        log("[INTERRUPTED] verify aborted early due to Ctrl+C")


def clean_missing_paths():
    start = time.perf_counter()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM file_hashes")
    rows = cur.fetchall()

    deleted = 0
    for file_id, path in tqdm(rows, desc="Cleaning", unit="file", smoothing=0.3):
        if INTERRUPTED:
            break
        if not os.path.exists(path):
            cur.execute("DELETE FROM file_hashes WHERE id = ?", (file_id,))
            if VERBOSE:
                log(f"[CLEAN] Removed: {path}")
            deleted += 1

    conn.commit()
    conn.close()
    duration = time.perf_counter() - start
    log(f"🧹 Cleaned {deleted} entries from the DB in {human_time(duration)}.")
    if INTERRUPTED:
        log("[INTERRUPTED] clean aborted early due to Ctrl+C")


def detect_hardlinks():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT dev, inode, COUNT(*)
        FROM file_hashes
        GROUP BY dev, inode
        HAVING COUNT(*) > 1
    """)
    groups = cur.fetchall()
    count = 0
    for dev, inode, _ in groups:
        cur.execute("""
            UPDATE file_hashes SET is_hardlink = 1
            WHERE dev = ? AND inode = ?
        """, (dev, inode))
        count += cur.rowcount

    conn.commit()
    conn.close()
    log(f"🔗 Marked {count} entries as hardlinks.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda sig, frame: handle_interrupt())
    args = parse_args()
    VERBOSE = args.verbose

    init_db()

    try:
        if args.command == "scan":
            scan_directory(args.directory)
        elif args.command == "verify":
            verify_full_hashes(args.workers)
        elif args.command == "clean":
            clean_missing_paths()
        elif args.command == "detect-hardlinks":
            detect_hardlinks()
    except KeyboardInterrupt:
        log(f"[INTERRUPTED] {args.command} cancelled by user.")
        sys.exit(1)
