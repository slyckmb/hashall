#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7-patch3)

import argparse
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime

TOOL_VERSION = "v0.3.7-patch3"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")

def print_version_header():
    print(f"📦 filehash_tool.py (rev {TOOL_VERSION})\n")

def connect_db(db_path):
    if not os.path.isfile(db_path):
        print(f"⚠️  No database found at {db_path}")
        return None
    try:
        return sqlite3.connect(db_path)
    except Exception as e:
        print(f"❌ Error opening DB: {e}")
        return None

def run_scan(args):
    print_version_header()
    print(f"🔍 Scanning root: {args.root}")
    # Stubbed logic
    print("📌 [stub] Scan would update file_hashes with new/changed files.")

def run_verify(args):
    print_version_header()
    mode = "full" if args.full else "fast"
    print(f"🔁 Verifying hashes ({mode} mode)")
    print("📌 [stub] Verify would rehash files and compare against DB.")

def run_clean(args):
    print_version_header()
    print("🧹 Cleaning stale records...")
    # Stubbed logic
    print("📌 [stub] Clean would remove entries for missing files.")

def run_tree(args):
    print_version_header()
    print("🌲 Building folder signature hashes...")
    # Stubbed logic
    print("📌 [stub] Tree hash would populate folder_hashes table recursively.")

def run_status(args):
    print_version_header()
    db = connect_db(args.db)
    if not db:
        return
    try:
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM file_hashes")
        total_files = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM folder_hashes")
        total_folders = cur.fetchone()[0]

        print(f"📄 Tracked files:  {total_files}")
        print(f"📁 Hashed folders: {total_folders}")
    except Exception as e:
        print(f"❌ Status error: {e}")
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(
        description=f"filehash_tool.py (rev {TOOL_VERSION})",
        usage="filehash_tool.py {scan,verify,clean,tree,status} [options]"
    )
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to database")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")
    p_scan.set_defaults(func=run_scan)

    p_verify = subparsers.add_parser("verify", help="Verify file hashes")
    p_verify.add_argument("--full", action="store_true", help="Force full hash verify")
    p_verify.set_defaults(func=run_verify)

    p_clean = subparsers.add_parser("clean", help="Clean removed/missing entries")
    p_clean.set_defaults(func=run_clean)

    p_tree = subparsers.add_parser("tree", help="Build folder signature hashes")
    p_tree.set_defaults(func=run_tree)

    p_status = subparsers.add_parser("status", help="Show current database summary")
    p_status.set_defaults(func=run_status)

    if len(sys.argv) == 1:
        print_version_header()
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
