#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch10)

import argparse
import os
import sys
import hashlib
import sqlite3
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from signal import signal, SIGINT
from datetime import datetime
from tqdm import tqdm
import psutil

TOOL_VERSION = "v0.3.7-patch10"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")
BATCH_SIZE = 100

stop_requested = False

def signal_handler(sig, frame):
    global stop_requested
    stop_requested = True
    print("\n❌ Aborted by user (Ctrl+C)")

signal(SIGINT, signal_handler)

def hash_file(path, mode="full"):
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def get_default_workers():
    return min(32, max(2, psutil.cpu_count(logical=False) or 4))

def init_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS file_hashes (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            size INTEGER,
            mtime REAL,
            partial_sha1 TEXT,
            full_sha1 TEXT,
            is_hardlink INTEGER DEFAULT 0
        )""")

def scan_dir(root):
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            yield os.path.join(dirpath, f)

def scan(root, db_path, workers):
    init_db(db_path)
    all_files = list(scan_dir(root))
    results = []
    updated = 0
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(hash_file, f): f for f in all_files}
            for future in tqdm(as_completed(futures), total=len(all_files), desc="Scanning", unit="file"):
                if stop_requested:
                    break
                f = futures[future]
                sha = future.result()
                try:
                    stat = os.stat(f)
                    results.append((f, stat.st_size, stat.st_mtime, sha))
                except:
                    continue

                if len(results) >= BATCH_SIZE:
                    cur.executemany("INSERT OR REPLACE INTO file_hashes (path, size, mtime, partial_sha1) VALUES (?, ?, ?, ?)",
                                    results)
                    updated += len(results)
                    results.clear()
        if results:
            cur.executemany("INSERT OR REPLACE INTO file_hashes (path, size, mtime, partial_sha1) VALUES (?, ?, ?, ?)",
                            results)
            updated += len(results)
    print(f"✅ Scanned {updated} files")

def parse_args():
    parser = argparse.ArgumentParser(description=f"filehash_tool.py (rev {TOOL_VERSION})")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to database")
    parser.add_argument("--workers", type=int, default=get_default_workers(), help="Worker thread count")
    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")

    return parser.parse_args()

def main():
    args = parse_args()
    if not args.command:
        print(f"\n📦 filehash_tool.py (rev {TOOL_VERSION})\n")
        os.system(f"{sys.executable} {sys.argv[0]} -h")
        return

    if args.command == "scan":
        print(f"🔍 Scanning {args.root} [rev {TOOL_VERSION}]")
        scan(args.root, args.db, args.workers)

if __name__ == "__main__":
    main()