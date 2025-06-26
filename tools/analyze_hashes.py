# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/usr/bin/env python3
# analyze_hashes.py (hashall companion script) v0.3.6

import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from termcolor import colored
import sys

VERSION = "v0.3.6"
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

def parse_human_size(s):
    s = s.strip().upper()
    try:
        if s.endswith("GB"):
            return float(s[:-2]) * 1024**3
        elif s.endswith("MB"):
            return float(s[:-2]) * 1024**2
        elif s.endswith("KB"):
            return float(s[:-2]) * 1024
        elif s.endswith("B"):
            return float(s[:-1])
        else:
            return float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid size format: '{s}'")

def get_grouped_files(db_path):
    if not os.path.exists(db_path):
        print(colored(f"\n❌ Database not found: {db_path}", "red", attrs=["bold"]))
        sys.exit(1)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT sha1, path, dev, inode, mtime, owner, file_group, is_hardlink, size
            FROM file_hashes
            WHERE sha1 IS NOT NULL
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

def display_group(sha1, files, args, summary):
    total_files = len(files)
    file_size = files[0]['size'] if files else 0

    # Reclaimable logic per device: one copy per inode survives
    dev_groups = defaultdict(list)
    for f in files:
        dev_groups[f["dev"]].append(f)

    device_reclaim = {}
    group_reclaim = 0
    for dev, dev_files in dev_groups.items():
        inode_count = len(set(f["inode"] for f in dev_files))
        dev_reclaim = file_size * max(0, inode_count - 1)
        device_reclaim[dev] = dev_reclaim
        group_reclaim += dev_reclaim

    # Filter: only show groups with reclaimable
    if args.only_hardlinkable and group_reclaim == 0:
        return

    if args.min_size and file_size < args.min_size:
        return
    if args.max_size and file_size > args.max_size:
        return

    summary["shown"] += 1
    summary["reclaimable"] += group_reclaim

    print(colored(f"\n🔁 Group: {sha1[:16]} [file size: {human_size(file_size)}] "
                  f"(files: {total_files}, reclaimable: {human_size(group_reclaim)})", attrs=["bold"]))

    for dev, dev_files in dev_groups.items():
        dev_inodes = defaultdict(list)
        for f in dev_files:
            dev_inodes[f["inode"]].append(f)

        dev_disk = file_size * len(dev_inodes)
        dev_reclaim = device_reclaim[dev]

        print(colored(f"\n  ┌─ 💽 dev {dev}: [file size: {human_size(file_size)}] "
                      f"(files: {len(dev_files)}, disk: {human_size(dev_disk)}, reclaimable: {human_size(dev_reclaim)})",
                      "cyan", attrs=["bold"]))

        for inode, inode_files in dev_inodes.items():
            print(colored(f"  │\n  ├─ inode {inode} ({len(inode_files)} files)", "yellow"))
            if args.verbose:
                for f in inode_files:
                    info = f"[{format_mtime(f['mtime'])},{f['uid']},{f['gid']}]"
                    icon = "🔗" if len(inode_files) >= 2 else "♻️"
                    print(f"  │ {colored(icon, 'green' if icon == '🔗' else 'magenta')} {info} {f['path']}")

        print("  └─────────────────────")

def main():
    parser = argparse.ArgumentParser(description="Analyze hashall database")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to hashall database")
    parser.add_argument("--verbose", action="store_true", help="Print file paths and details")
    parser.add_argument("--only-hardlinkable", action="store_true", help="Show only groups with reclaimable files")
    parser.add_argument("--min-size", type=parse_human_size, help="Minimum file size (e.g. 100MB, 1GB)")
    parser.add_argument("--max-size", type=parse_human_size, help="Maximum file size (e.g. 500MB)")
    args = parser.parse_args()

    print(f"\n📂 Analyzing hashall DB: {args.db} (rev {VERSION})")
    if args.min_size or args.max_size or args.only_hardlinkable:
        filters = []
        if args.min_size: filters.append(f"--min-size {human_size(args.min_size)}")
        if args.max_size: filters.append(f"--max-size {human_size(args.max_size)}")
        if args.only_hardlinkable: filters.append("--only-hardlinkable")
        print(colored(f"🔍 Filters active: {' '.join(filters)}", "cyan"))
    print("-" * 50)

    summary = {"shown": 0, "reclaimable": 0}
    try:
        groups = get_grouped_files(args.db)
        print(f"\n🔁 Duplicate full-hash groups: {len(groups)}")
        for sha1, files in groups.items():
            display_group(sha1, files, args, summary)
    except BrokenPipeError:
        sys.exit(0)

    print(colored("\n📊 Summary", attrs=["bold"]))
    print("──────────────")
    print(f"Groups shown: {summary['shown']}")
    print(f"Total reclaimable: {human_size(summary['reclaimable'])}")
    if args.min_size or args.max_size or args.only_hardlinkable:
        print(f"Filtered by: {' '.join(sys.argv[1:])}")

if __name__ == "__main__":
    main()
