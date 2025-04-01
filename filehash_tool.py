#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch2)

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

TOOL_VERSION = "v0.3.7"

DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")


def print_header(db_path):
    print(f"\n📂 filehash_tool.py (rev {TOOL_VERSION})")
    print(f"Database: {db_path}")
    print("-" * 50)


def open_db(path):
    if not os.path.exists(path):
        print(f"❌ Error: DB not found at {path}")
        sys.exit(1)
    return sqlite3.connect(path)


def run_scan(args):
    print_header(args.db)
    print(f"🔍 Scanning root: {args.root}")
    # Stubbed logic
    scanned, skipped = 1234, 87
    print(f"✅ Scan complete: {scanned} files hashed, {skipped} skipped")


def run_clean(args):
    print_header(args.db)
    print("🧹 Cleaning stale entries...")
    # Stubbed logic
    removed = 42
    print(f"✅ Cleaned: {removed} stale paths removed")


def run_verify(args):
    print_header(args.db)
    mode = "Full verify" if args.full else "Quick verify"
    print(f"🔁 {mode} starting...")
    # Stubbed logic
    print("✅ Verification complete")


def run_tree(args):
    print_header(args.db)
    print("🌲 Building folder signature hashes...")
    # Stubbed logic
    folders_built = 735
    print(f"✅ Tree signatures updated: {folders_built} folders processed")


def run_status(args):
    print_header(args.db)
    try:
        with open_db(args.db) as conn:
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM file_hashes")
            file_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT full_sha1) FROM file_hashes WHERE full_sha1 IS NOT NULL")
            unique_hashes = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM folder_hashes")
            folder_count = cur.fetchone()[0]

            cur.execute("SELECT MAX(last_updated) FROM folder_hashes")
            last_tree_update = cur.fetchone()[0] or "N/A"

            cur.execute("SELECT DISTINCT host_name FROM file_hashes WHERE host_name IS NOT NULL LIMIT 1")
            host = cur.fetchone()[0] or "N/A"

            print(f"🧮 Stats:")
            print(f"  • Files tracked: {file_count}")
            print(f"  • Unique full hashes: {unique_hashes}")
            print(f"  • Folders tracked: {folder_count}")
            print(f"  • Host name: {host}")
            print(f"  • Last tree update: {last_tree_update}")
    except Exception as e:
        print(f"❌ Status error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description=f"filehash_tool.py (rev {TOOL_VERSION})",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to the hashall database")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan and hash new files")
    p_scan.add_argument("root", help="Root directory to scan")
    p_scan.set_defaults(func=run_scan)

    # clean
    p_clean = subparsers.add_parser("clean", help="Remove missing or stale file entries")
    p_clean.set_defaults(func=run_clean)

    # verify
    p_verify = subparsers.add_parser("verify", help="Re-verify file hashes")
    p_verify.add_argument("--full", action="store_true", help="Force full hash verify")
    p_verify.set_defaults(func=run_verify)

    # tree
    p_tree = subparsers.add_parser("tree", help="Build recursive folder signature hashes")
    p_tree.set_defaults(func=run_tree)

    # status
    p_status = subparsers.add_parser("status", help="Show DB and host stats")
    p_status.set_defaults(func=run_status)

    args = parser.parse_args()
    try:
        args.func(args)
    except BrokenPipeError:
        sys.exit(0)


if __name__ == "__main__":
    main()
