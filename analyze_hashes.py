#!/usr/bin/env python3
# analyze_hashes.py (hashall companion script)

import os
import sqlite3
import argparse
from pathlib import Path

DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")

def get_duplicate_fullhash_groups(db_path):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT full_sha1, path
            FROM file_hashes
            WHERE full_sha1 IS NOT NULL
        """)
        groups = {}
        for sha1, path in cur.fetchall():
            groups.setdefault(sha1, []).append(path)

        # Filter: only keep groups with >1 file
        return {k: v for k, v in groups.items() if len(v) > 1}

def get_hardlink_candidates(db_path):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT full_sha1, COUNT(*)
            FROM file_hashes
            WHERE full_sha1 IS NOT NULL AND is_hardlink = 0
            GROUP BY full_sha1
            HAVING COUNT(*) > 1
        """)
        return cur.fetchall()

def get_duplicate_folder_structures(db_path):
    from collections import Counter
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT path FROM file_hashes WHERE full_sha1 IS NOT NULL")
        rows = cur.fetchall()

    # Extract directories using Python's Path
    dirs = [str(Path(path).parent) for (path,) in rows]
    counter = Counter(dirs)

    # Return folders with more than 10 hashed files
    return [(d, c) for d, c in counter.items() if c > 10]


def main():
    parser = argparse.ArgumentParser(description="Analyze file hashes for duplicates and hardlinks")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to the hashall database")
    parser.add_argument("--verbose", action="store_true", help="Print detailed results")
    args = parser.parse_args()

    db_path = args.db
    print(f"\n📂 Analyzing hashall DB: {db_path}")
    print("-" * 50)

    groups = get_duplicate_fullhash_groups(db_path)
    print(f"\n🔁 Duplicate file groups by full hash: {len(groups)} groups")
    if args.verbose:
        for sha1, files in groups.items():
            print(f"\n  {sha1[:10]}...: {len(files)} files")
            for path in files:
                print(f"    {path}")

    hardlinkable = get_hardlink_candidates(db_path)
    print(f"\n🔗 Hardlinkable file groups (same hash, not linked): {len(hardlinkable)} groups")
    if args.verbose:
        for sha1, count in hardlinkable:
            print(f"  {sha1[:10]}...: {count} files (not linked)")

    folder_dupes = get_duplicate_folder_structures(db_path)
    print(f"\n📁 Potential duplicate folder structures (10+ matching files): {len(folder_dupes)} folders")
    if args.verbose:
        for folder, count in sorted(folder_dupes, key=lambda x: -x[1])[:50]:
            print(f"  {folder}: {count} files")

if __name__ == "__main__":
    main()
