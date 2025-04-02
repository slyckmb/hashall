#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch11)

import argparse
import os
import sys
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import signal
import threading

TOOL_VERSION = "v0.3.7-patch11"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")
stop_event = threading.Event()

def hash_file(path, mode="partial"):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            if mode == "partial":
                h.update(f.read(4096))
            else:
                while chunk := f.read(8192):
                    h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def debug_log(msg):
    if os.environ.get("HASHALL_DEBUG"):
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[DEBUG {now}] {msg}")

def graceful_exit():
    print("❌ Aborted by user")
    stop_event.set()

def scan_directory(root, db_path, workers):
    debug_log(f"Scanning path: {root}")
    all_files = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.isfile(full):
                all_files.append(full)

    if not all_files:
        print("⚠️ No files found.")
        return

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    bar = tqdm(total=len(all_files), desc="Scanning", unit="file")

    def task(path):
        if stop_event.is_set():
            return None
        try:
            stat = os.stat(path)
            partial = hash_file(path, "partial")
            return (
                path, stat.st_size, stat.st_mtime, stat.st_ino,
                stat.st_dev, stat.st_uid, stat.st_gid, partial
            )
        except Exception:
            return None

    updates = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(task, f): f for f in all_files}
        for future in as_completed(futures):
            if stop_event.is_set():
                break
            result = future.result()
            if result:
                updates.append(result)
            bar.update(1)

    bar.close()

    if updates:
        cur.executemany("""
            INSERT OR REPLACE INTO file_hashes
            (path, size, mtime, inode, dev, owner, file_group, partial_sha1)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, updates)
        con.commit()
        print(f"✅ Scanned {len(updates)} files")
    con.close()

def main():
    signal.signal(signal.SIGINT, lambda s, f: graceful_exit())

    parser = argparse.ArgumentParser(
        description=f"filehash_tool.py (rev {TOOL_VERSION})"
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to database")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--workers", type=int, default=None, help="Number of threads")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Root directory to scan")

    args = parser.parse_args()

    if args.debug:
        os.environ["HASHALL_DEBUG"] = "1"
        print(f"\n[DEBUG] {Path(sys.argv[0]).name} {sys.argv[1:]} [rev {TOOL_VERSION}]")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        db_backup = f"{args.db}.v{TOOL_VERSION}.{timestamp}.bak"
        if os.path.exists(args.db):
            from shutil import copy2
            copy2(args.db, db_backup)
            print(f"[DEBUG] Database backed up to {db_backup}")

    if args.command == "scan":
        workers = args.workers or os.cpu_count() or 4
        print(f"\n🔍 Scanning {args.root} [rev {TOOL_VERSION}]")
        scan_directory(args.root, args.db, workers)
    else:
        print("⚠️ Only 'scan' implemented in patch11")

if __name__ == "__main__":
    try:
        main()
    except sqlite3.OperationalError as e:
        print(f"❌ DB error: {e}")
        sys.exit(1)
    except Exception as e:
        if stop_event.is_set():
            sys.exit(1)
        raise
