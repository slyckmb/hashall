#!/usr/bin/env python3
# analyze_hashes.py (hashall companion script) v0.2.13

import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from termcolor import colored

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

    # Calculate reclaimable and disk usage per dev/inode
    dev_inode_map = defaultdict(set)
    for f in files:
        dev_inode_map[f["dev"]].add(f["inode"])

    disk_usage = sum(file_size for inodes in dev_inode_map.values() for _ in inodes)
    reclaimable = sum(file_size * max(0, len(inodes) - 1) for inodes in dev_inode_map.values())

    print(colored(
        f"\n🔁 Group: {sha1[:16]} [file size: {human_size(file_size)}] "
        f"(files: {total_files}, disk: {human_size(disk_usage)}, reclaimable: {human_size(reclaimable)})",
        attrs=["bold"]
    ))

    # Device subgroups
    dev_groups = defaultdict(list)
    for f in files:
        dev_groups[f["dev"]].append(f)

    for dev, dev_files in dev_groups.items():
        dev_inodes = set(f["inode"] for f in dev_files)
        dev_disk = file_size * len(dev_inodes)
        dev_reclaim = file_size * max(0, len(dev_inodes) - 1)

        print(colored(
            f"\n  ┌─ 💽 dev {dev}: [file size: {human_size(file_size)}] "
            f"(files: {len(dev_files)}, disk: {human_size(dev_disk)}, reclaimable: {human_size(dev_reclaim)})",
            "cyan", attrs=["bold"]
        ))

        # Inode subgroups
        inode_groups = defaultdict(list)
        for f in dev_files:
            inode_groups[f["inode"]].append(f)

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
    args = parser.parse_args()

    db_path = args.db
    print(f"\n📂 Analyzing hashall DB: {db_path}")
    print("-" * 50)

    groups = get_grouped_files(db_path)
    print(f"\n🔁 Duplicate full-hash groups: {len(groups)}")

    for sha1, files in groups.items():
        if args.verbose:
            display_group(sha1, files, verbose=True)

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Exit quietly when output is piped to something like `less` and closed early
        import sys
        sys.exit(0)

