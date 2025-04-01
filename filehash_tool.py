#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch7)

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

TOOL_VERSION = "v0.3.7-patch7"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")


def hash_file(path, mode="partial"):
    try:
        hasher = hashlib.sha1()
        with open(path, "rb") as f:
            if mode == "partial":
                hasher.update(f.read(65536))
            else:
                while chunk := f.read(8192):
                    hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def scan_directory(db_path, root):
    print(f"🔍 Scanning {root} [rev {TOOL_VERSION}]")
    file_list = []
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            if os.path.isfile(fpath):
                file_list.append(fpath)

    with sqlite3.connect(db_path) as conn, tqdm(total=len(file_list), desc="Scanning") as pbar:
        cur = conn.cursor()
        for f in file_list:
            try:
                st = os.stat(f)
                partial = hash_file(f, "partial")
                cur.execute("INSERT OR REPLACE INTO file_hashes (path, size, mtime, inode, dev, owner, partial_sha1) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (f, st.st_size, st.st_mtime, st.st_ino, st.st_dev, st.st_uid, partial))
            except Exception:
                pass
            pbar.update(1)
        conn.commit()
    print(f"✅ Scanned {len(file_list)} files")


def clean_stale_entries(db_path):
    print(f"🧹 Cleaning stale records [rev {TOOL_VERSION}]")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT path FROM file_hashes")
        all_files = cur.fetchall()

        stale = []
        for (path,) in tqdm(all_files, desc="Checking files"):
            if not os.path.exists(path):
                stale.append((path,))

        cur.executemany("DELETE FROM file_hashes WHERE path = ?", stale)
        conn.commit()
    print(f"✅ Removed {len(stale)} stale entries")


def verify_hashes(db_path, fill=False, all_files=False, path=None):
    print(f"🔁 Verifying hashes [rev {TOOL_VERSION}]")
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()

            if not fill and not all_files:
                # Step 1: Mark hardlinks
                cur.execute("SELECT dev, inode, GROUP_CONCAT(path) FROM file_hashes GROUP BY dev, inode HAVING COUNT(*) > 1")
                hl_groups = cur.fetchall()
                for dev, inode, _ in hl_groups:
                    cur.execute("UPDATE file_hashes SET is_hardlink = 1 WHERE dev = ? AND inode = ?", (dev, inode))

                print(f"🔗 Inferred {len(hl_groups)} hardlink groups")

                # Step 2: Add full hashes to files with same partial
                clause = "WHERE" if path is None else f"WHERE path LIKE '{path}%' AND"
                query = f"""
                    SELECT partial_sha1, GROUP_CONCAT(path) FROM file_hashes
                    {clause} partial_sha1 IS NOT NULL
                    GROUP BY partial_sha1 HAVING COUNT(*) > 1
                """
                cur.execute(query)
                dup_groups = cur.fetchall()

                updated = 0
                for _, paths_str in tqdm(dup_groups, desc="Verifying dupes"):
                    for f in paths_str.split(","):
                        full = hash_file(f, "full")
                        if full:
                            cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, f))
                            updated += 1
                conn.commit()
                print(f"✅ Updated full hash for {updated} files")

            elif fill:
                cur.execute("SELECT path FROM file_hashes WHERE full_sha1 IS NULL")
                files = [row[0] for row in cur.fetchall()]
                updated = 0
                for f in tqdm(files, desc="Filling full hashes"):
                    full = hash_file(f, "full")
                    if full:
                        cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, f))
                        updated += 1
                conn.commit()
                print(f"✅ Filled full hash for {updated} files")

            elif all_files:
                clause = "" if path is None else f"WHERE path LIKE '{path}%'"
                cur.execute(f"SELECT path FROM file_hashes {clause}")
                files = [row[0] for row in cur.fetchall()]
                updated = 0
                for f in tqdm(files, desc="Rehashing all"):
                    full = hash_file(f, "full")
                    if full:
                        cur.execute("UPDATE file_hashes SET full_sha1 = ? WHERE path = ?", (full, f))
                        updated += 1
                conn.commit()
                print(f"✅ Rehashed {updated} files")

    except KeyboardInterrupt:
        print("\n❌ Aborted by user")


def build_folder_signatures(db_path):
    print(f"🌲 Building folder signatures [rev {TOOL_VERSION}]")
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT dirname(path) FROM file_hashes")
            folders = [row[0] for row in cur.fetchall()]

            updated = 0
            for folder in tqdm(folders, desc="Hashing folders"):
                cur.execute("SELECT full_sha1 FROM file_hashes WHERE path LIKE ?", (f"{folder}/%",))
                hashes = sorted(row[0] for row in cur.fetchall() if row[0])
                if hashes:
                    sig = hashlib.sha1("".join(hashes).encode()).hexdigest()
                    cur.execute("""
                        INSERT OR REPLACE INTO folder_hashes
                        (folder_path, folder_hash, total_size, total_files, hash_depth, last_updated, needs_rebuild)
                        VALUES (?, ?, ?, ?, ?, ?, 0)
                    """, (folder, sig, 0, len(hashes), 1, datetime.now().isoformat()))
                    updated += 1
            conn.commit()
        print(f"✅ Updated {updated} folder signatures")
    except KeyboardInterrupt:
        print("\n❌ Aborted by user")


def show_status(db_path):
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM file_hashes")
            count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM file_hashes WHERE full_sha1 IS NULL")
            missing = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM folder_hashes")
            folders = cur.fetchone()[0]

        print(f"📊 DB status for {db_path} [rev {TOOL_VERSION}]")
        print(f"  📁 Files: {count}")
        print(f"  ❌ Missing full hashes: {missing}")
        print(f"  🌲 Folders: {folders}")
    except Exception as e:
        print(f"❌ Status error: {e}")


def main():
    parser = argparse.ArgumentParser(description=f"filehash_tool.py (rev {TOOL_VERSION})")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")
    p_scan.set_defaults(func=lambda args: scan_directory(args.db, args.root))

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify file hashes")
    p_verify.add_argument("--fill", action="store_true", help="Fill in missing full hashes")
    p_verify.add_argument("--all", action="store_true", help="Recalculate all full hashes")
    p_verify.add_argument("--path", help="Limit to subtree")
    p_verify.set_defaults(func=lambda args: verify_hashes(args.db, args.fill, args.all, args.path))

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean removed/missing entries")
    p_clean.set_defaults(func=lambda args: clean_stale_entries(args.db))

    # tree
    p_tree = subparsers.add_parser("tree", help="Build folder signature hashes")
    p_tree.set_defaults(func=lambda args: build_folder_signatures(args.db))

    # status
    p_status = subparsers.add_parser("status", help="Show current database summary")
    p_status.set_defaults(func=lambda args: show_status(args.db))

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n❌ Aborted by user")


if __name__ == "__main__":
    main()
