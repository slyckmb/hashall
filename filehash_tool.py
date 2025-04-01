#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch5)

import os
import hashlib
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime

TOOL_VERSION = "v0.3.7-patch5"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")


def hash_file(path, mode="full"):
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


def scan_directory(root, db_path):
    print(f"🔍 Running scan on root: {root} [rev {TOOL_VERSION}]")
    files = []
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            try:
                path = os.path.join(dirpath, f)
                stat = os.stat(path)
                files.append((path, stat))
            except Exception:
                continue

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS file_hashes ("
                    "path TEXT PRIMARY KEY, size INTEGER, mtime REAL, inode INTEGER, dev INTEGER, "
                    "owner INTEGER, file_group INTEGER, partial_sha1 TEXT, full_sha1 TEXT, "
                    "is_hardlink INTEGER DEFAULT 0, host_name TEXT DEFAULT NULL)")
        added = 0
        for path, stat in files:
            cur.execute("INSERT OR IGNORE INTO file_hashes (path, size, mtime, inode, dev, owner) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (path, stat.st_size, stat.st_mtime,
                                                      stat.st_ino, stat.st_dev, stat.st_uid))
            added += cur.rowcount
        conn.commit()
    print(f"📂 Scan complete: {len(files)} files walked, {added} new added to DB")


def clean_stale_records(db_path):
    print(f"🧹 Cleaning stale records [rev {TOOL_VERSION}]")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT path FROM file_hashes")
        stale = []
        for (path,) in cur.fetchall():
            if not os.path.exists(path):
                stale.append(path)
        for p in stale:
            cur.execute("DELETE FROM file_hashes WHERE path = ?", (p,))
        conn.commit()
    print(f"🗑️ Removed {len(stale)} stale entries")


def verify_hashes(db_path, fill=False, all_files=False, path=None):
    print(f"🔁 Verifying hashes [rev {TOOL_VERSION}]")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        clause = "WHERE 1=1"
        if path:
            clause += f" AND path LIKE '{path.rstrip('/')}/%'"

        if all_files:
            cur.execute(f"SELECT path FROM file_hashes {clause}")
        elif fill:
            cur.execute(f"SELECT path FROM file_hashes {clause} AND full_sha1 IS NULL")
        else:
            # Baseline mode: infer hardlinks + fill full hash where needed
            cur.execute(f"SELECT dev, inode, GROUP_CONCAT(path) FROM file_hashes {clause} GROUP BY dev, inode HAVING COUNT(*) > 1")
            hl_groups = cur.fetchall()
            for dev, inode, paths in hl_groups:
                for p in paths.split(','):
                    cur.execute("UPDATE file_hashes SET is_hardlink = 1 WHERE path = ?", (p,))
            print(f"🔗 Inferred {len(hl_groups)} hardlink groups")

            cur.execute(f"SELECT partial_sha1, GROUP_CONCAT(path) FROM file_hashes {clause} WHERE partial_sha1 IS NOT NULL GROUP BY partial_sha1 HAVING COUNT(*) > 1")
            fill_targets = []
            for _, pathlist in cur.fetchall():
                fill_targets.extend(pathlist.split(','))
            print(f"💠 Resolving {len(fill_targets)} partial hash collisions")
            for p in fill_targets:
                full = hash_file(p, "full")
                if full:
                    cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, p))
            conn.commit()
            return

        rows = cur.fetchall()
        updated = 0
        for (p,) in rows:
            if not os.path.exists(p):
                continue
            full = hash_file(p, "full")
            if full:
                cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, p))
                updated += 1
        conn.commit()
        print(f"✅ Updated full hash for {updated} files")


def build_tree_hashes(db_path):
    print(f"🌲 Building folder signature hashes [rev {TOOL_VERSION}]")
    # Stub: coming in next patch
    print(f"🧪 Simulated: 0 folders hashed")


def show_status(db_path):
    print(f"📦 filehash_tool.py (rev {TOOL_VERSION}) DB: {db_path}")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM file_hashes")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM file_hashes WHERE full_sha1 IS NULL")
            missing = cur.fetchone()[0]
            print(f"📊 File records: {total:,}")
            print(f"📉 Missing full hashes: {missing:,}")
        except Exception as e:
            print(f"❌ Status error: {e}")


def main():
    parser = argparse.ArgumentParser(description=f"filehash_tool.py (rev {TOOL_VERSION})")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify and update file hashes")
    p_verify.add_argument("--fill", action="store_true", help="Fill in missing full hashes")
    p_verify.add_argument("--all", action="store_true", help="Recalculate all hashes")
    p_verify.add_argument("--path", type=str, help="Restrict to path")

    # clean
    subparsers.add_parser("clean", help="Remove stale DB entries")

    # tree
    subparsers.add_parser("tree", help="Build folder signature hashes")

    # status
    subparsers.add_parser("status", help="Show current database summary")

    args = parser.parse_args()
    db_path = args.db

    if args.command == "scan":
        scan_directory(args.root, db_path)
    elif args.command == "verify":
        verify_hashes(db_path, fill=args.fill, all_files=args.all, path=args.path)
    elif args.command == "clean":
        clean_stale_records(db_path)
    elif args.command == "tree":
        build_tree_hashes(db_path)
    elif args.command == "status":
        show_status(db_path)


if __name__ == "__main__":
    main()
