#!/usr/bin/env python3
"""
Analyze hashall export JSON for real-world link validation.
Read-only analysis script - no filesystem modifications.
"""
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path


def analyze_export(json_path):
    """Analyze a hashall export JSON file and compute statistics."""
    with open(json_path) as f:
        data = json.load(f)

    root_path = data.get('root_path')
    scan_id = data.get('scan_id')
    files = data.get('files', [])

    # Basic counts
    total_files = len(files)
    total_logical_bytes = sum(f['size'] for f in files)

    # Track unique physical files by (device_id, inode)
    physical_files = {}
    for f in files:
        key = (f['device_id'], f['inode'])
        if key not in physical_files:
            physical_files[key] = f['size']

    unique_physical_files = len(physical_files)
    unique_physical_bytes = sum(physical_files.values())

    # Hardlink detection
    inode_paths = defaultdict(list)
    for f in files:
        inode_paths[(f['device_id'], f['inode'])].append(f['path'])

    hardlinked_paths = [paths for paths in inode_paths.values() if len(paths) > 1]
    hardlinked_paths_count = sum(len(paths) for paths in hardlinked_paths)

    # SHA1 analysis
    sha1_groups = defaultdict(list)
    for f in files:
        if f.get('sha1'):
            sha1_groups[f['sha1']].append(f)

    # Duplicates by SHA1 (same hash, different inodes)
    dup_groups = []
    for sha1, file_list in sha1_groups.items():
        unique_inodes = set((f['device_id'], f['inode']) for f in file_list)
        if len(unique_inodes) > 1:
            dup_groups.append((sha1, file_list))

    dup_by_sha_count = len(dup_groups)

    # Top 10 SHA1 groups by total logical bytes
    sha1_totals = []
    for sha1, file_list in sha1_groups.items():
        total_size = sum(f['size'] for f in file_list)
        sha1_totals.append((sha1, len(file_list), total_size, file_list))

    sha1_totals.sort(key=lambda x: x[2], reverse=True)
    top_10_sha1 = sha1_totals[:10]

    # Cross-device SHA1 groups
    cross_device_groups = []
    for sha1, file_list in sha1_groups.items():
        devices = set(f['device_id'] for f in file_list)
        if len(devices) > 1:
            cross_device_groups.append((sha1, devices, file_list))

    # Missing SHA1 count
    missing_sha1 = sum(1 for f in files if not f.get('sha1'))

    return {
        'root_path': root_path,
        'scan_id': scan_id,
        'total_files': total_files,
        'total_logical_bytes': total_logical_bytes,
        'unique_physical_files': unique_physical_files,
        'unique_physical_bytes': unique_physical_bytes,
        'hardlinked_paths_count': hardlinked_paths_count,
        'hardlinked_groups': len(hardlinked_paths),
        'dup_by_sha_count': dup_by_sha_count,
        'top_10_sha1': top_10_sha1,
        'cross_device_groups': cross_device_groups,
        'missing_sha1': missing_sha1,
    }


def format_bytes(bytes_val):
    """Format bytes in human-readable form."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def print_analysis(stats):
    """Print analysis results in human-readable format."""
    print(f"\n{'='*70}")
    print(f"HASHALL EXPORT ANALYSIS")
    print(f"{'='*70}")
    print(f"Root Path: {stats['root_path']}")
    print(f"Scan ID: {stats['scan_id']}")
    print(f"\n{'─'*70}")
    print(f"BASIC STATISTICS")
    print(f"{'─'*70}")
    print(f"Total Files (logical): {stats['total_files']:,}")
    print(f"Total Logical Bytes: {format_bytes(stats['total_logical_bytes'])} ({stats['total_logical_bytes']:,} bytes)")
    print(f"Unique Physical Files: {stats['unique_physical_files']:,}")
    print(f"Unique Physical Bytes: {format_bytes(stats['unique_physical_bytes'])} ({stats['unique_physical_bytes']:,} bytes)")

    if stats['total_files'] != stats['unique_physical_files']:
        savings = stats['total_logical_bytes'] - stats['unique_physical_bytes']
        print(f"Space Saved by Hardlinks: {format_bytes(savings)} ({100*savings/stats['total_logical_bytes']:.2f}%)")

    print(f"\n{'─'*70}")
    print(f"HARDLINK ANALYSIS")
    print(f"{'─'*70}")
    print(f"Hardlinked Path Count: {stats['hardlinked_paths_count']:,}")
    print(f"Hardlink Groups: {stats['hardlinked_groups']:,}")

    print(f"\n{'─'*70}")
    print(f"DUPLICATE DETECTION")
    print(f"{'─'*70}")
    print(f"Duplicate SHA1 Groups (different inodes): {stats['dup_by_sha_count']:,}")
    print(f"Missing SHA1: {stats['missing_sha1']:,}")

    if stats['cross_device_groups']:
        print(f"\n{'─'*70}")
        print(f"CROSS-DEVICE SHA1 GROUPS (cannot hardlink across devices)")
        print(f"{'─'*70}")
        print(f"Count: {len(stats['cross_device_groups']):,}")
        for sha1, devices, files in stats['cross_device_groups'][:5]:
            print(f"  SHA1 {sha1[:12]}... appears on devices {sorted(devices)}: {len(files)} files")

    print(f"\n{'─'*70}")
    print(f"TOP 10 SHA1 GROUPS BY TOTAL LOGICAL BYTES")
    print(f"{'─'*70}")
    for i, (sha1, count, total_size, files) in enumerate(stats['top_10_sha1'], 1):
        print(f"{i:2}. {sha1[:12]}... × {count:4} copies = {format_bytes(total_size):>12} total")
        # Show first 3 paths as examples
        for f in files[:3]:
            print(f"     - {f['path']}")
        if len(files) > 3:
            print(f"     ... and {len(files)-3} more")

    print(f"\n{'='*70}\n")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <hashall_export.json>")
        sys.exit(1)

    json_path = sys.argv[1]
    if not Path(json_path).exists():
        print(f"Error: {json_path} not found")
        sys.exit(1)

    stats = analyze_export(json_path)
    print_analysis(stats)
