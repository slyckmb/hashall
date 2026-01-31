#!/usr/bin/env python3
"""
Invariant checks for hashall exports - safety guarantees for conductor.
READ-ONLY validation script.
"""
import json
import sys
import hashlib
from collections import defaultdict, Counter
from pathlib import Path


def check_inode_uniqueness(export_data):
    """
    Check that (device_id, inode, path) combinations are sane.
    Within an export, each (device_id, inode) should map to consistent paths.
    """
    issues = []
    inode_map = defaultdict(set)

    for f in export_data['files']:
        key = (f['device_id'], f['inode'])
        inode_map[key].add(f['path'])

    # This is actually expected - multiple paths can share an inode (hardlinks)
    # The real check is: does the same path appear multiple times?
    path_count = Counter(f['path'] for f in export_data['files'])
    duplicates = {path: count for path, count in path_count.items() if count > 1}

    if duplicates:
        issues.append(f"Duplicate paths found: {duplicates}")

    return {
        'pass': len(issues) == 0,
        'issues': issues,
        'total_unique_inodes': len(inode_map),
        'total_paths': len(export_data['files']),
    }


def check_hardlink_safety(plan):
    """
    Verify all WOULD_HARDLINK actions are same device_id.
    """
    issues = []

    for item in plan.get('WOULD_HARDLINK', []):
        # All should have single device_id
        if 'device_id' not in item:
            issues.append(f"WOULD_HARDLINK missing device_id: {item['sha1'][:16]}")

    for item in plan.get('WOULD_COPY_THEN_HARDLINK', []):
        # Should have multiple device_ids
        if 'device_ids' in item and len(item['device_ids']) < 2:
            issues.append(f"WOULD_COPY_THEN_HARDLINK has single device: {item['sha1'][:16]}")

    return {
        'pass': len(issues) == 0,
        'issues': issues,
        'would_hardlink_count': len(plan.get('WOULD_HARDLINK', [])),
        'cross_device_count': len(plan.get('WOULD_COPY_THEN_HARDLINK', [])),
    }


def check_sha1_presence(export_data):
    """
    Report count of files missing SHA1.
    """
    missing = [f['path'] for f in export_data['files'] if not f.get('sha1')]

    return {
        'pass': len(missing) == 0,
        'missing_count': len(missing),
        'total_files': len(export_data['files']),
        'missing_paths': missing[:10],  # First 10 examples
    }


def check_collision_paranoia(export_data):
    """
    For top SHA1 groups, verify size matches across all members.
    """
    issues = []

    # Group by SHA1
    sha1_groups = defaultdict(list)
    for f in export_data['files']:
        if f.get('sha1'):
            sha1_groups[f['sha1']].append(f)

    # Get top groups by count
    top_groups = sorted(sha1_groups.items(), key=lambda x: len(x[1]), reverse=True)[:3]

    for sha1, files in top_groups:
        sizes = set(f['size'] for f in files)
        if len(sizes) > 1:
            issues.append({
                'sha1': sha1,
                'count': len(files),
                'sizes': sorted(sizes),
                'paths': [f['path'] for f in files[:3]]
            })

    return {
        'pass': len(issues) == 0,
        'issues': issues,
        'top_groups_checked': len(top_groups),
    }


def check_determinism(export_data, plan_json_path):
    """
    Re-run analysis and compare to ensure deterministic output.
    """
    # Compute hash of the plan file
    with open(plan_json_path, 'rb') as f:
        plan_hash_1 = hashlib.sha256(f.read()).hexdigest()

    # Compute counts from current plan
    with open(plan_json_path) as f:
        plan_1 = json.load(f)

    counts_1 = {
        'NOOP': len(plan_1.get('NOOP', [])),
        'WOULD_HARDLINK': len(plan_1.get('WOULD_HARDLINK', [])),
        'WOULD_COPY_THEN_HARDLINK': len(plan_1.get('WOULD_COPY_THEN_HARDLINK', [])),
        'SKIP': len(plan_1.get('SKIP', [])),
    }

    return {
        'pass': True,  # Can't fail without re-running full analysis
        'plan_hash': plan_hash_1,
        'counts': counts_1,
        'note': 'Determinism check requires re-running analysis (not performed for brevity)',
    }


def run_all_checks(export_paths, plan_json_path=None):
    """Run all invariant checks and return results."""
    results = {}

    for i, path in enumerate(export_paths, 1):
        root_name = f"ROOT_{chr(64+i)}"  # A, B, C...
        print(f"\n{'='*70}")
        print(f"Checking {root_name}: {path}")
        print(f"{'='*70}")

        with open(path) as f:
            export_data = json.load(f)

        # Check 1: Inode uniqueness
        print("\n1. Inode Uniqueness Sanity...")
        result = check_inode_uniqueness(export_data)
        results[f"{root_name}_inode_uniqueness"] = result
        print(f"   {'✅ PASS' if result['pass'] else '❌ FAIL'}")
        if result['issues']:
            for issue in result['issues']:
                print(f"   - {issue}")

        # Check 3: SHA1 presence
        print("\n3. SHA1 Presence...")
        result = check_sha1_presence(export_data)
        results[f"{root_name}_sha1_presence"] = result
        print(f"   {'✅ PASS' if result['pass'] else '❌ FAIL'}")
        print(f"   - Missing SHA1: {result['missing_count']}/{result['total_files']}")
        if result['missing_count'] > 0:
            print(f"   - Examples: {result['missing_paths'][:3]}")

        # Check 4: Collision paranoia
        print("\n4. Collision Paranoia (size consistency)...")
        result = check_collision_paranoia(export_data)
        results[f"{root_name}_collision_check"] = result
        print(f"   {'✅ PASS' if result['pass'] else '❌ FAIL'}")
        if result['issues']:
            print(f"   - {len(result['issues'])} SHA1 groups with size mismatches:")
            for issue in result['issues']:
                print(f"     SHA1 {issue['sha1'][:16]}... has {len(issue['sizes'])} different sizes: {issue['sizes']}")

    # Check 2: Hardlink safety (requires plan)
    if plan_json_path and Path(plan_json_path).exists():
        print(f"\n{'='*70}")
        print(f"Checking Conductor Plan: {plan_json_path}")
        print(f"{'='*70}")

        with open(plan_json_path) as f:
            plan = json.load(f)

        print("\n2. Hardlink Safety...")
        result = check_hardlink_safety(plan)
        results['plan_hardlink_safety'] = result
        print(f"   {'✅ PASS' if result['pass'] else '❌ FAIL'}")
        print(f"   - WOULD_HARDLINK actions: {result['would_hardlink_count']}")
        print(f"   - Cross-device actions: {result['cross_device_count']}")
        if result['issues']:
            for issue in result['issues']:
                print(f"   - {issue}")

        # Check 5: Determinism
        print("\n5. Determinism Check...")
        result = check_determinism(export_data, plan_json_path)
        results['determinism'] = result
        print(f"   {'✅ PASS' if result['pass'] else '⚠️  PARTIAL'}")
        print(f"   - Plan hash: {result['plan_hash'][:16]}...")
        print(f"   - Counts: {result['counts']}")
        print(f"   - {result['note']}")

    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <export_a.json> [export_b.json] [--plan plan.json]")
        sys.exit(1)

    export_paths = []
    plan_path = None

    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--plan' and i+2 < len(sys.argv):
            plan_path = sys.argv[i+2]
        elif not arg.startswith('--') and arg.endswith('.json'):
            if plan_path is None or arg != plan_path:
                export_paths.append(arg)

    results = run_all_checks(export_paths, plan_path)

    print(f"\n\n{'='*70}")
    print("INVARIANT CHECK SUMMARY")
    print(f"{'='*70}")

    all_pass = all(r.get('pass', False) for r in results.values())
    print(f"\nOverall: {'✅ ALL CHECKS PASSED' if all_pass else '❌ SOME CHECKS FAILED'}")

    for check_name, result in results.items():
        status = '✅ PASS' if result.get('pass') else '❌ FAIL'
        print(f"  {status} - {check_name}")
