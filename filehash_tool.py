#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch8)

import argparse
import os
import sqlite3
import sys
import hashlib
import time
import shutil
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

TOOL_VERSION = "v0.3.7-patch8"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")
DEBUG_MODE = False

def debug(msg):
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}")

def backup_database(db_path):
    if os.path.exists(db_path):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{db_path}.{TOOL_VERSION}.{timestamp}.bak"
        shutil.copy2(db_path, backup_path)
        debug(f"Database backed up to {backup_path}")

def hash_file(path, mode="partial"):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            if mode == "partial":
                h.update(f.read(65536))
            else:
                while chunk := f.read(8192):
                    h.update(chunk)
    except Exception:
        return None
    return h.hexdigest()

def scan_files(db_path, root):
    start = time.time()
    debug(f"Scanning path: {root}")
    all_files = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            if os.path.isfile(full_path):
                all_files.append(full_path)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION")
        for path in tqdm(all_files, desc="Scanning"):
            try:
                stat = os.stat(path)
                partial = hash_file(path, mode="partial")
                cur.execute("""
                    INSERT OR REPLACE INTO file_hashes
                    (path, size, mtime, inode, dev, owner, partial_sha1)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    path,
                    stat.st_size,
                    stat.st_mtime,
                    stat.st_ino,
                    stat.st_dev,
                    stat.st_uid,
                    partial
                ))
            except Exception as e:
                debug(f"Skipping file {path}: {e}")
        conn.commit()

    print(f"✅ Scanned {len(all_files)} files")
    debug(f"Scan completed in {time.time() - start:.2f}s")

def clean_stale(db_path):
    start = time.time()
    debug("Cleaning stale records")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT path FROM file_hashes")
        paths = cur.fetchall()

        removed = 0
        cur.execute("BEGIN TRANSACTION")
        for (path,) in tqdm(paths, desc="Checking files"):
            if not os.path.exists(path):
                cur.execute("DELETE FROM file_hashes WHERE path = ?", (path,))
                removed += 1
        conn.commit()

    print(f"✅ Removed {removed} stale entries")
    debug(f"Clean completed in {time.time() - start:.2f}s")

def verify_hashes(db_path, fill=False, all_files=False, path=None):
    start = time.time()
    print(f"🔁 Verifying hashes [rev {TOOL_VERSION}]")

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        # Detect hardlinks
        cur.execute("SELECT dev, inode, GROUP_CONCAT(path) FROM file_hashes GROUP BY dev, inode HAVING COUNT(*) > 1")
        hardlink_groups = cur.fetchall()
        cur.execute("UPDATE file_hashes SET is_hardlink = 0")
        for dev, inode, _ in hardlink_groups:
            cur.execute("UPDATE file_hashes SET is_hardlink = 1 WHERE dev = ? AND inode = ?", (dev, inode))
        print(f"🔗 Inferred {len(hardlink_groups)} hardlink groups")

        clause = ""
        params = []

        if path:
            clause = "WHERE path LIKE ?"
            params = [f"{path}%"]

        if all_files:
            cur.execute(f"SELECT path FROM file_hashes {clause}", params)
            rows = cur.fetchall()
            updated = 0
            for (p,) in tqdm(rows, desc="Rehashing"):
                full = hash_file(p, "full")
                if full:
                    cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, p))
                    updated += 1
            conn.commit()
            print(f"✅ Updated full hash for {updated} files")
            debug(f"Full reverify completed in {time.time() - start:.2f}s")
            return

        if fill:
            cur.execute(f"SELECT path FROM file_hashes {clause} AND full_sha1 IS NULL" if clause else "SELECT path FROM file_hashes WHERE full_sha1 IS NULL")
            rows = cur.fetchall()
            updated = 0
            for (p,) in tqdm(rows, desc="Filling full hashes"):
                full = hash_file(p, "full")
                if full:
                    cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, p))
                    updated += 1
            conn.commit()
            print(f"✅ Updated full hash for {updated} files")
            debug(f"Fill completed in {time.time() - start:.2f}s")
            return

        # Default: resolve dupes
        cur.execute(f"""
            SELECT partial_sha1, GROUP_CONCAT(path)
            FROM file_hashes
            WHERE partial_sha1 IS NOT NULL
            GROUP BY partial_sha1
            HAVING COUNT(*) > 1
        """)
        groups = cur.fetchall()
        total = 0
        for partial, paths in tqdm(groups, desc="Verifying dupes"):
            path_list = paths.split(",")
            for p in path_list:
                full = hash_file(p, "full")
                if full:
                    cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, p))
                    total += 1
        conn.commit()
        print(f"✅ Updated full hash for {total} files")
        debug(f"Verify completed in {time.time() - start:.2f}s")

def tree_build(db_path):
    print(f"🌲 Building folder signature hashes [rev {TOOL_VERSION}]")
    print("⏳ Tree signature calculation is not yet implemented in this patch.")

def show_status(db_path):
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM file_hashes")
            files = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM file_hashes WHERE full_sha1 IS NOT NULL")
            full = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM file_hashes WHERE is_hardlink = 1")
            links = cur.fetchone()[0]
            print(f"📊 Status for {db_path}:")
            print(f"   Total files: {files:,}")
            print(f"   Full hashes: {full:,}")
            print(f"   Hardlinks:   {links:,}")
    except Exception as e:
        print(f"❌ Status error: {e}")

def main():
    global DEBUG_MODE

    parser = argparse.ArgumentParser(
        description=f"filehash_tool.py (rev {TOOL_VERSION})",
        epilog="Use --debug to show detailed logs and timings."
    )
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to database")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    subparsers = parser.add_subparsers(dest="command")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify file hashes")
    p_verify.add_argument("--fill", action="store_true", help="Fill in missing full hashes")
    p_verify.add_argument("--all", action="store_true", help="Force full hash on all files")
    p_verify.add_argument("--path", type=str, help="Restrict to files under path")

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean removed/missing entries")

    # tree
    p_tree = subparsers.add_parser("tree", help="Build folder signature hashes")

    # status
    p_status = subparsers.add_parser("status", help="Show current database summary")

    args = parser.parse_args()
    DEBUG_MODE = args.debug
    db_path = args.db

    if not os.path.exists(db_path):
        print(f"❌ Error: database not found at {db_path}")
        sys.exit(1)

    backup_database(db_path)

    if args.command == "scan":
        scan_files(db_path, args.root)
    elif args.command == "verify":
        verify_hashes(db_path, fill=args.fill, all_files=args.all, path=args.path)
    elif args.command == "clean":
        clean_stale(db_path)
    elif args.command == "tree":
        tree_build(db_path)
    elif args.command == "status":
        show_status(db_path)
    else:
        parser.print_help()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("❌ Aborted by user")
        sys.exit(1)
    except BrokenPipeError:
        sys.exit(0)