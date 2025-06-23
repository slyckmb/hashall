#!/usr/bin/env python3
"""
filehash_tool.py – CLI interface for hashall operations
"""

import argparse
import os
import sys
from pathlib import Path
import logging

from scan_session import scan_files
from json_export import export_json
from db_migration import backup_db, apply_migrations
import sqlite3

logger = logging.getLogger("hashall.cli")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def main():
    parser = argparse.ArgumentParser(description="Hashall: Scan and export file metadata with SHA1 hashes")
    subparsers = parser.add_subparsers(dest="command")

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a directory and store metadata")
    scan_parser.add_argument("root", help="Root directory to scan")
    scan_parser.add_argument("--db", help="Path to SQLite database")
    scan_parser.add_argument("--mode", choices=["partial", "full", "verify"], default="partial", help="Hashing mode")
    scan_parser.add_argument("--workers", type=int, default=4, help="Number of worker threads")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export scan results to JSON")
    export_parser.add_argument("root", help="Root directory to export")
    export_parser.add_argument("--db", help="Path to SQLite database")

    args = parser.parse_args()

    # Resolve DB path
    default_dir = os.environ.get("HASHALL_DIR", os.path.join(os.environ.get("HOME", "~"), ".hashall"))
    db_path = args.db or os.path.join(default_dir, "hashall.sqlite3")

    # Ensure DB parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Run DB upgrade logic
    if Path(db_path).exists():
        backup_db(db_path)
    conn = sqlite3.connect(db_path)
    apply_migrations(conn)
    conn.close()

    # Execute command
    if args.command == "scan":
        scan_files(
            root_path=args.root,
            db_path=db_path,
            mode=args.mode,
            workers=args.workers
        )
    elif args.command == "export":
        export_json(
            root_path=args.root,
            db_path=db_path
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
