#!/usr/bin/env python3
"""
Dry-run conductor plan generator for hashall exports.
Identifies deduplication and hardlink opportunities WITHOUT modifying filesystem.
READ-ONLY analysis only.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_export(json_path):
    """Load a hashall export JSON file."""
    with open(json_path) as f:
        return json.load(f)


def generate_plan(export_a, export_b=None):
    """
    Generate a dry-run conductor plan from one or two exports.

    Returns:
        dict with action plans categorized by type
    """
    plan = {
        'NOOP': [],
        'WOULD_HARDLINK': [],
        'WOULD_COPY_THEN_HARDLINK': [],
        'SKIP': [],
    }

    # Build file maps by SHA1
    files_by_sha1 = defaultdict(list)

    # Add files from export_a
    root_a = export_a['root_path']
    for f in export_a['files']:
        if f.get('sha1'):
            files_by_sha1[f['sha1']].append({
                **f,
                'root': root_a,
                'full_path': f"{root_a}/{f['path']}"
            })

    # Add files from export_b if provided
    if export_b:
        root_b = export_b['root_path']
        for f in export_b['files']:
            if f.get('sha1'):
                files_by_sha1[f['sha1']].append({
                    **f,
                    'root': root_b,
                    'full_path': f"{root_b}/{f['path']}"
                })

    # Process each SHA1 group
    for sha1, file_list in files_by_sha1.items():
        if len(file_list) < 2:
            continue  # No dedup opportunity, single file

        # Check if all files have consistent size
        sizes = set(f['size'] for f in file_list)
        if len(sizes) > 1:
            plan['SKIP'].append({
                'sha1': sha1,
                'reason': 'Size mismatch despite same SHA1',
                'candidate_paths': [f['full_path'] for f in file_list],
                'sizes': sorted(sizes),
            })
            continue

        # Get unique (device_id, inode) tuples
        unique_inodes = {}
        for f in file_list:
            key = (f['device_id'], f['inode'])
            if key not in unique_inodes:
                unique_inodes[key] = []
            unique_inodes[key].append(f)

        if len(unique_inodes) == 1:
            # All files already share the same inode = already hardlinked
            plan['NOOP'].append({
                'sha1': sha1,
                'reason': 'Already hardlinked',
                'canonical_path': file_list[0]['full_path'],
                'candidate_paths': [f['full_path'] for f in file_list],
                'inode': file_list[0]['inode'],
                'device_id': file_list[0]['device_id'],
            })
            continue

        # Multiple different inodes = dedup opportunity
        # Choose canonical copy (prefer root_a if provided)
        canonical = None
        if export_b:
            # Prefer root_a for canonical
            for f in file_list:
                if f['root'] == root_a:
                    canonical = f
                    break
        if not canonical:
            canonical = file_list[0]

        # Get unique device_ids
        devices = set(f['device_id'] for f in file_list)

        if len(devices) == 1:
            # Same device = can hardlink
            plan['WOULD_HARDLINK'].append({
                'sha1': sha1,
                'canonical_path': canonical['full_path'],
                'candidate_paths': [f['full_path'] for f in file_list if f['full_path'] != canonical['full_path']],
                'device_id': canonical['device_id'],
                'inode': canonical['inode'],
                'size': canonical['size'],
                'reason': 'Same device, can create hardlinks',
            })
        else:
            # Cross-device = cannot hardlink, would need copy+relink
            plan['WOULD_COPY_THEN_HARDLINK'].append({
                'sha1': sha1,
                'canonical_path': canonical['full_path'],
                'candidate_paths': [f['full_path'] for f in file_list if f['full_path'] != canonical['full_path']],
                'device_ids': sorted(devices),
                'inodes': [(f['device_id'], f['inode']) for f in file_list],
                'size': canonical['size'],
                'reason': 'Cross-device, would need copy then relink (not executed)',
            })

    return plan


def write_human_plan(plan, output_path):
    """Write human-readable plan to text file."""
    with open(output_path, 'w') as f:
        f.write("HASHALL CONDUCTOR DRY-RUN PLAN\n")
        f.write("=" * 70 + "\n\n")
        f.write("This is a DRY-RUN plan. NO filesystem modifications will be performed.\n\n")

        # Summary
        f.write(f"Summary:\n")
        f.write(f"  NOOP (already optimal):       {len(plan['NOOP']):5} items\n")
        f.write(f"  WOULD_HARDLINK (same device): {len(plan['WOULD_HARDLINK']):5} items\n")
        f.write(f"  WOULD_COPY_THEN_HARDLINK:     {len(plan['WOULD_COPY_THEN_HARDLINK']):5} items\n")
        f.write(f"  SKIP (issues/ambiguity):      {len(plan['SKIP']):5} items\n")
        f.write("\n" + "=" * 70 + "\n\n")

        # Details for each category
        for action_type in ['NOOP', 'WOULD_HARDLINK', 'WOULD_COPY_THEN_HARDLINK', 'SKIP']:
            items = plan[action_type]
            if not items:
                continue

            f.write(f"\n{action_type}\n")
            f.write("-" * 70 + "\n")

            for i, item in enumerate(items[:10], 1):  # Show first 10 of each type
                f.write(f"\n{i}. SHA1: {item['sha1'][:16]}...\n")
                f.write(f"   Reason: {item['reason']}\n")
                if 'canonical_path' in item:
                    f.write(f"   Canonical: {item['canonical_path']}\n")
                if 'candidate_paths' in item:
                    f.write(f"   Candidates ({len(item['candidate_paths'])}):\n")
                    for path in item['candidate_paths'][:5]:
                        f.write(f"     - {path}\n")
                    if len(item['candidate_paths']) > 5:
                        f.write(f"     ... and {len(item['candidate_paths'])-5} more\n")
                if 'size' in item:
                    f.write(f"   Size: {item['size']:,} bytes\n")

            if len(items) > 10:
                f.write(f"\n... and {len(items)-10} more {action_type} items\n")


def write_json_plan(plan, output_path):
    """Write machine-readable plan to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(plan, f, indent=2)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <export_a.json> [export_b.json]")
        sys.exit(1)

    export_a_path = sys.argv[1]
    export_b_path = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Loading ROOT_A: {export_a_path}")
    export_a = load_export(export_a_path)

    export_b = None
    if export_b_path:
        print(f"Loading ROOT_B: {export_b_path}")
        export_b = load_export(export_b_path)

    print("Generating conductor plan...")
    plan = generate_plan(export_a, export_b)

    txt_path = '/tmp/hashall_conductor_plan.txt'
    json_path = '/tmp/hashall_conductor_plan.json'

    write_human_plan(plan, txt_path)
    write_json_plan(plan, json_path)

    print(f"\nPlan written to:")
    print(f"  Human-readable: {txt_path}")
    print(f"  Machine-readable: {json_path}")

    print(f"\nSummary:")
    print(f"  NOOP (already optimal):       {len(plan['NOOP']):5} items")
    print(f"  WOULD_HARDLINK (same device): {len(plan['WOULD_HARDLINK']):5} items")
    print(f"  WOULD_COPY_THEN_HARDLINK:     {len(plan['WOULD_COPY_THEN_HARDLINK']):5} items")
    print(f"  SKIP (issues/ambiguity):      {len(plan['SKIP']):5} items")
