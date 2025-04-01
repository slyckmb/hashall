#!/usr/bin/env python3
# filehash_tool.py v0.3.7 – Tree-level folder signature hashing

import argparse
import hashlib
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict

VERSION = "v0.3.7"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")

def compute_sha1_from_list(items):
    sha1 = hashlib.sha1()
    for item in sorted(items):
        sha1.update(item.encode("utf-8"))
    return sha1.hexdigest()

def build_folder_hashes(db_path):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        print(f"\n🌳 filehash_tool.py (rev {VERSION})")
        print(f"📂 Analyzing DB: {db_path}")
        print("-" * 50)

        # Clear old data
        cur.execute("DELETE FROM folder_hashes")

        # Load all hashed files
        cur.execute("""
            SELECT path, full_sha1, size FROM file_hashes
            WHERE full_sha1 IS NOT NULL
        """)
        file_rows = cur.fetchall()

        # Map files to folders
        folder_map = defaultdict(list)
        for path, sha1, size in file_rows:
            folder = str(Path(path).parent)
            folder_map[folder].append((sha1, size))

        print(f"📁 Found {len(folder_map)} folders to analyze")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        inserted = 0
        for folder_path, file_list in folder_map.items():
            file_hashes = [sha1 for sha1, _ in file_list]
            sizes = [s for _, s in file_list]

            folder_hash = compute_sha1_from_list(file_hashes)
            total_size = sum(sizes)
            total_files = len(file_hashes)
            hash_depth = 1  # placeholder for future recursion

            cur.execute("""
                INSERT OR REPLACE INTO folder_hashes
                (folder_path, folder_hash, total_size, total_files, hash_depth, last_updated, needs_rebuild)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (folder_path, folder_hash, total_size, total_files, hash_depth, now))
            inserted += 1

        conn.commit()
        print(f"✅ Folder hashes written: {inserted}")

def main():
    parser = argparse.ArgumentParser(description=f"filehash_tool.py (rev {VERSION})")
    subparsers = parser.add_subparsers(dest="command")

    # Tree subcommand
    tree_parser = subparsers.add_parser("tree", help="Build folder signature hashes")
    tree_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to hashall database")

    args = parser.parse_args()

    if args.command == "tree":
        build_folder_hashes(args.db)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
