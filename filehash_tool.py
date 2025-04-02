#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch12)

import argparse
import os
import sys
import sqlite3
import hashlib
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import signal

TOOL_VERSION = "v0.3.7-patch12"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")

# Shutdown flag
stop_requested = False
def signal_handler(sig, frame):
    global stop_requested
    stop_requested = True
    print("\n❌ Aborted by user")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --- Helpers ---

def debug_log(args, msg):
    if args.debug:
        print(f"[DEBUG] {msg}")

def hash_file(path, mode="partial"):
    try:
        with open(path, "rb") as f:
            if mode == "partial":
                chunk = f.read(65536)
                return hashlib.sha1(chunk).hexdigest()
            else:
                h = hashlib.sha1()
                while chunk := f.read(8192):
                    h.update(chunk)
                return h.hexdigest()
    except Exception:
        return None

def get_db_connection(db_path):
    try:
        return sqlite3.connect(db_path)
    except sqlite3.OperationalError as e:
        print(f"❌ Failed to open DB: {e}")
        sys.exit(1)

# --- Subcommands ---

def run_scan(args):
    print(f"🔍 Scanning {args.root} [rev {TOOL_VERSION}]")
    file_list = []
    for root, _, files in os.walk(args.root):
        for f in files:
            file_list.append(os.path.join(root, f))

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(hash_file, path, "partial"): path for path in file_list}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Scanning"):
            if stop_requested:
                break
            path = futures[future]
            partial = future.result()
            if partial:
                results.append((path, partial))

    print(f"✅ Scanned {len(results)} files")

def run_verify(args):
    print(f"🔁 Verifying hashes [rev {TOOL_VERSION}]")
    conn = get_db_connection(args.db)
    cur = conn.cursor()

    cur.execute("SELECT dev, inode, GROUP_CONCAT(path) FROM file_hashes GROUP BY dev, inode HAVING COUNT(*) > 1")
    hl_groups = cur.fetchall()
    print(f"🔗 Inferred {len(hl_groups)} hardlink groups")

    clause = f"WHERE path LIKE '{args.path}%'" if args.path else ""
    try:
        cur.execute(f"""
            SELECT path FROM file_hashes
            {clause}
            AND full_sha1 IS NULL
            AND partial_sha1 IS NOT NULL
        """)
    except sqlite3.OperationalError as e:
        print(f"❌ Query error: {e}")
        return

    rows = cur.fetchall()
    if not rows:
        print("✅ Nothing to verify")
        return

    files = [row[0] for row in rows]
    updated = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(hash_file, path, "full"): path for path in files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Verifying full hashes"):
            if stop_requested:
                break
            path = futures[future]
            full = future.result()
            if full:
                updated.append((full, path))

    for full, path in updated:
        cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, path))
    conn.commit()
    conn.close()
    print(f"✅ Updated full hash for {len(updated)} files")

def run_clean(args):
    print(f"🧹 Cleaning stale records [rev {TOOL_VERSION}]")
    conn = get_db_connection(args.db)
    cur = conn.cursor()
    cur.execute("SELECT path FROM file_hashes")
    rows = cur.fetchall()

    stale = []
    for row in tqdm(rows, desc="Checking files"):
        if not os.path.exists(row[0]):
            stale.append(row[0])

    for path in stale:
        cur.execute("DELETE FROM file_hashes WHERE path = ?", (path,))
    conn.commit()
    conn.close()
    print(f"✅ Removed {len(stale)} stale entries")

def run_tree(args):
    print(f"🌲 Building folder signature hashes [rev {TOOL_VERSION}]")
    # Placeholder until recursive hash engine is ready
    time.sleep(1)
    print("✅ Folder hash scan complete (sim)")

def run_status(args):
    print(f"📊 DB Status [rev {TOOL_VERSION}]")
    conn = get_db_connection(args.db)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM file_hashes")
        total = cur.fetchone()[0]
        print(f"🔹 Total entries: {total}")
    except Exception as e:
        print(f"❌ Status error: {e}")
    finally:
        conn.close()

# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description=f"filehash_tool.py (rev {TOOL_VERSION})",
        usage=f"filehash_tool.py {{scan,verify,clean,tree,status}} [options]"
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to database")
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="Number of parallel workers")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    subparsers = parser.add_subparsers(dest="command")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory to scan")
    p_scan.set_defaults(func=run_scan)

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify file hashes")
    p_verify.add_argument("--fill", action="store_true", help="Fill missing full hashes")
    p_verify.add_argument("--all", action="store_true", help="Re-hash all files")
    p_verify.add_argument("--path", help="Limit to path prefix")
    p_verify.set_defaults(func=run_verify)

    # clean
    p_clean = subparsers.add_parser("clean", help="Remove stale/missing entries")
    p_clean.set_defaults(func=run_clean)

    # tree
    p_tree = subparsers.add_parser("tree", help="Build folder signature hashes")
    p_tree.set_defaults(func=run_tree)

    # status
    p_status = subparsers.add_parser("status", help="Show current database summary")
    p_status.set_defaults(func=run_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print(f"\n📦 filehash_tool.py (rev {TOOL_VERSION})")
        return

    debug_log(args, f"Command: {args.command}, DB: {args.db}, Workers: {args.workers}")
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
