#!/usr/bin/env python3
"""Automated payload workflow - runs scan/sync/upgrade loop until complete."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hashall.model import connect_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-run payload workflow to completion")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--roots", help="Comma-separated roots (auto-discover if omitted)")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max loop iterations")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without executing")
    args = parser.parse_args()

    conn = connect_db(Path(args.db))

    # Discover or parse roots
    if args.roots:
        roots = [r.strip() for r in args.roots.split(",")]
    else:
        roots = _discover_roots(conn)

    if not roots:
        print("No roots found. Run 'make payload-sync' first.")
        return 1

    print(f"Automated payload workflow")
    print(f"  Roots: {', '.join(roots)}")
    print(f"  DB: {args.db}")
    print(f"  Max iterations: {args.max_iterations}")
    print()

    # Main loop
    for iteration in range(1, args.max_iterations + 1):
        print(f"--- Iteration {iteration} ---")

        action_taken = False

        # Step 1: Check for dirty payloads (need scan)
        dirty_count, scan_path = check_dirty(conn, roots)
        if dirty_count > 0:
            print(f"  Found {dirty_count} dirty payloads (need scan)")
            if not run_scan(scan_path, args.dry_run):
                print("  ❌ Scan failed")
                return 1
            action_taken = True
            # Re-run payload-sync after scan to update file_count
            print(f"  Re-syncing payloads after scan...")
            if not run_payload_sync(roots, upgrade=False, dry_run=args.dry_run):
                print("  ❌ Payload-sync failed")
                return 1
            continue  # Re-check from top

        # Step 2: Check for incomplete payloads (need upgrade)
        incomplete_count = check_incomplete(conn, roots)
        if incomplete_count > 0:
            print(f"  Found {incomplete_count} incomplete payloads (need upgrade)")
            if not run_payload_sync(roots, upgrade=True, dry_run=args.dry_run):
                print("  ❌ Payload upgrade failed")
                return 1
            action_taken = True
            continue  # Re-check from top

        # Step 3: Check for collision groups
        collision_count = check_collisions(conn)
        if collision_count > 0:
            print(f"  Found {collision_count} collision groups (need upgrade)")
            if not run_collision_upgrade(roots, args.dry_run):
                print("  ❌ Collision upgrade failed")
                return 1
            action_taken = True
            continue  # Re-check from top

        if not action_taken:
            print("✅ Workflow complete - no actions needed")
            break
    else:
        print(f"⚠️  Max iterations ({args.max_iterations}) reached")
        return 1

    return 0


def check_dirty(conn, roots: list[str]) -> tuple[int, str | None]:
    """Check for dirty payloads (file_count=0). Returns (count, scan_path)."""
    rows = conn.execute(
        "SELECT root_path FROM payloads WHERE file_count = 0"
    ).fetchall()

    per_root = {}
    for root in roots:
        count = sum(1 for (rp,) in rows if rp == root or rp.startswith(root.rstrip("/") + "/"))
        per_root[root] = count

    total_dirty = sum(per_root.values())
    if total_dirty == 0:
        return 0, None

    # Find scan path - use root with most dirty + /torrents/seeding
    max_dirty = max(per_root.values())
    target_root = next(r for r, c in per_root.items() if c == max_dirty)

    first_dirty = rows[0][0] if rows else ""
    if "/torrents/seeding/" in first_dirty:
        scan_path = target_root + "/torrents/seeding"
    else:
        scan_path = target_root

    return total_dirty, scan_path


def check_incomplete(conn, roots: list[str]) -> int:
    """Check incomplete payloads needing upgrade (file_count>0, status=incomplete)."""
    rows = conn.execute(
        "SELECT root_path FROM payloads WHERE status = 'incomplete' AND file_count > 0"
    ).fetchall()

    count = 0
    for root in roots:
        for (rp,) in rows:
            if rp == root or rp.startswith(root.rstrip("/") + "/"):
                count += 1

    return count


def check_collisions(conn) -> int:
    """Check collision groups needing SHA256 upgrade."""
    count = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT file_count, total_bytes
            FROM payloads
            GROUP BY file_count, total_bytes
            HAVING COUNT(*) > 1
               AND SUM(CASE WHEN status = 'incomplete' THEN 1 ELSE 0 END) > 0
        )
        """
    ).fetchone()[0]
    return count


def run_scan(scan_path: str, dry_run: bool) -> bool:
    """Execute scan command. Returns True on success."""
    cmd = ["hashall", "scan", scan_path, "--hash-mode", "full", "--parallel"]
    print(f"  → Running: {' '.join(cmd)}")
    if dry_run:
        print("    (dry-run, skipped)")
        return True

    result = subprocess.run(cmd)
    return result.returncode == 0


def run_payload_sync(roots: list[str], upgrade: bool, dry_run: bool) -> bool:
    """Execute payload-sync. Returns True on success."""
    cmd = ["hashall", "payload", "sync", "--db", str(Path.home() / ".hashall" / "catalog.db")]
    for root in roots:
        cmd.extend(["--path-prefix", root])
    if upgrade:
        cmd.extend(["--upgrade-missing", "--parallel"])

    print(f"  → Running: {' '.join(cmd[:6])}... {'--upgrade-missing --parallel' if upgrade else ''}")
    if dry_run:
        print("    (dry-run, skipped)")
        return True

    result = subprocess.run(cmd)
    return result.returncode == 0


def run_collision_upgrade(roots: list[str], dry_run: bool) -> bool:
    """Execute payload-upgrade-collisions for all roots. Returns True on success."""
    for root in roots:
        cmd = ["hashall", "payload", "upgrade-collisions", "--db",
               str(Path.home() / ".hashall" / "catalog.db"), "--path-prefix", root]
        print(f"  → Running: {' '.join(cmd[:4])} ... --path-prefix {root}")
        if dry_run:
            print("    (dry-run, skipped)")
            continue

        result = subprocess.run(cmd)
        if result.returncode != 0:
            return False

    return True


def _discover_roots(conn) -> list[str]:
    """Auto-discover roots from payloads table."""
    rows = conn.execute(
        """
        SELECT DISTINCT p.root_path, d.preferred_mount_point, d.mount_point
        FROM payloads p
        LEFT JOIN devices d ON d.device_id = p.device_id
        """
    ).fetchall()
    mounts = set()
    for root_path, preferred, current in rows:
        mount = preferred or current or root_path
        mounts.add(mount)
    return sorted(mounts)


if __name__ == "__main__":
    sys.exit(main())
