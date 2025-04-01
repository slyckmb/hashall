#!/usr/bin/env python3
# analyze_hashes.py (hashall companion script) v0.3.5

import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from termcolor import colored
import re
import sys
from signal import signal, SIGPIPE, SIG_DFL
signal(SIGPIPE, SIG_DFL)

VERSION = "v0.3.5"
DEFAULT_DB_PATH = str(Path.home() / ".filehash.db")

def format_mtime(mtime):
    try:
        dt = datetime.fromtimestamp(mtime)
        return dt.strftime("%-m/%-d/%y %H:%M")
    except Exception:
        return "?"

def human_size(bytes):
    for unit in ['B','KB','MB','GB','TB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"

def parse_size(size_str):
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    match = re.match(r'^(\d+(?:\.\d+)?)([KMGT]?B)?$', size_str.strip(), re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid size format: {size_str}")
    number, unit = match.groups()
    unit = unit.upper() if unit else "B"
    if unit not in units:
        raise argparse.ArgumentTypeError(f"Unsupported unit: {unit}")
    return int(float(number) * units[unit])

def get_grouped_files(db_path):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT full_sha1, path, dev, inode, mtime, owner, file_group, is_hardlink, size
            FROM file_hashes
            WHERE full_sha1 IS NOT NULL
        """)
        rows = cur.fetchall()

    hash_groups = defaultdict(list)
    for row in rows:
        sha1, path, dev, inode, mtime, uid, gid, is_hl, size = row
        hash_groups[sha1].append({
            "path": path,
            "dev": dev,
            "inode": inode,
            "mtime": mtime,
            "uid": uid,
            "gid": gid,
            "is_hardlink": is_hl,
            "size": size
        })
    return {k: v for k, v in hash_groups.items() if len(v) > 1}

def display_group(sha1, files, verbose=False):
    total_files = len(files)
    file_size = files[0]['size'] if files else 0
    dev_inode_set = set((f["dev"], f["inode"]) for f in files)
    disk_usage = file_size * len(dev_inode_set)
    reclaimable = file_size * max(0, len(dev_inode_set) - 1)

    print(colored(f"\n🔁 Group: {sha1[:16]} [file size: {human_size(file_size)}] "
                  f"(files: {total_files}, disk: {human_size(disk_usage)}, reclaimable: {human_size(reclaimable)})",
                  attrs=["bold"]))

    dev_groups = defaultdict(list)
    for f in files:
        dev_groups[f["dev"]].append(f)

    for dev, dev_files in dev_groups.items():
        inode_groups = defaultdict(list)
        for f in dev_files:
            inode_groups[f["inode"]].append(f)

        dev_disk = file_size * len(inode_groups)
        dev_reclaim = file_size * max(0, len(inode_groups) - 1)

        print(colored(f"\n  ┌─ 💽 dev {dev}: [file size: {human_size(file_size)}] "
                      f"(files: {len(dev_files)}, disk: {human_size(dev_disk)}, reclaimable: {human_size(dev_reclaim)})",
                      "cyan", attrs=["bold"]))

        for inode, inode_files in inode_groups.items():
            print(colored(f"  │\n  ├─ inode {inode} ({len(inode_files)} files)", "yellow"))
            for f in inode_files:
                info = f"[{format_mtime(f['mtime'])},{f['uid']},{f['gid']}]"
                icon = "🔗" if len(inode_files) >= 2 else "♻️"
                print(f"  │ {colored(icon, 'green' if icon == '🔗' else 'magenta')} {info} {f['path']}")

        print("  └─────────────────────")

def main():
    parser = argparse.ArgumentParser(description="Analyze hashall database")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to hashall database")
    parser.add_argument("--verbose", action="store_true", help="Print file paths and details")
    parser.add_argument("--min-size", type=parse_size, help="Only show groups where file size >= this (e.g., 1GB)")
    parser.add_argument("--max-size", type=parse_size, help="Only show groups where file size <= this")
    parser.add_argument("--only-hardlinkable", action="store_true", help="Only show groups with ♻️ reclaimable files")
    args = parser.parse_args()

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"\n❌ Error: DB not found at {db_path}")
        sys.exit(1)

    print(f"\n📂 Analyzing hashall DB: {db_path} (rev {VERSION})")
    print("-" * 50)

    filters = []
    if args.min_size:
        filters.append(f"min-size: {human_size(args.min_size)}")
    if args.max_size:
        filters.append(f"max-size: {human_size(args.max_size)}")
    if args.only_hardlinkable:
        filters.append("only-hardlinkable: true")
    if filters:
        print("📎 Filters: " + ", ".join(filters))

    groups = get_grouped_files(db_path)
    print(f"\n🔁 Duplicate full-hash groups: {len(groups)}")

    for sha1, files in groups.items():
        file_size = files[0]['size']
        if args.min_size and file_size < args.min_size:
            continue
        if args.max_size and file_size > args.max_size:
            continue

        dev_inode_set = set((f["dev"], f["inode"]) for f in files)
        reclaimable = file_size * max(0, len(dev_inode_set) - 1)

        if args.only_hardlinkable and reclaimable == 0:
            continue

        display_group(sha1, files, verbose=args.verbose)

if __name__ == "__main__":
    main()
