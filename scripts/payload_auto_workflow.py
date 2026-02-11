#!/usr/bin/env python3
"""Automated payload workflow - runs scan/sync/upgrade loop until complete."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Ensure this script and its subprocesses resolve hashall from this repo checkout.
REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if REPO_SRC.exists():
    sys.path.insert(0, str(REPO_SRC))

from hashall.model import connect_db

STALL_THRESHOLD = 2


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
        roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    else:
        roots = _discover_roots(conn)

    if not roots:
        print("No roots found. Run 'make payload-sync' first.")
        return 1

    run_id = uuid.uuid4().hex[:10]
    log_path = _workflow_log_path(run_id)
    _log_event(
        log_path,
        "run_start",
        run_id=run_id,
        db=args.db,
        roots=roots,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
    )

    print(f"Automated payload workflow")
    print(f"  Roots: {', '.join(roots)}")
    print(f"  DB: {args.db}")
    print(f"  Run ID: {run_id}")
    print(f"  Log: {log_path}")
    print(f"  Max iterations: {args.max_iterations}")
    print()

    previous_signature = None
    stagnation_streak = 0

    try:
        # Main loop
        for iteration in range(1, args.max_iterations + 1):
            print(f"--- Iteration {iteration} ---")
            state = collect_workflow_state(conn, roots)
            signature = state_signature(state)
            stagnation_streak = next_stagnation_streak(previous_signature, signature, stagnation_streak)
            previous_signature = signature

            _log_event(
                log_path,
                "iteration_state",
                run_id=run_id,
                iteration=iteration,
                signature=list(signature),
                stagnation_streak=stagnation_streak,
                state=state,
            )

            dirty_count = state["dirty_in_scope"]
            dirty_orphan_in_scope = state["dirty_orphan_in_scope"]
            incomplete_count = state["incomplete_in_scope"]
            collision_count = state["collision_groups_in_scope"]
            if state["dirty_out_of_scope"] > 0:
                print(
                    f"  ⚠ Out-of-scope dirty payloads: {state['dirty_out_of_scope']} "
                    f"(samples: {', '.join(state['dirty_samples_out_of_scope'])})"
                )
                if state["mount_alias_hint"]:
                    print(f"  ⚠ Hint: {state['mount_alias_hint']}")

            if dirty_orphan_in_scope > 0:
                print(
                    f"  ⚠ In-scope orphan dirty payloads: {dirty_orphan_in_scope} "
                    f"(samples: {', '.join(state['dirty_orphan_samples_in_scope'])})"
                )

            if stagnation_streak >= STALL_THRESHOLD:
                reason = "stalled_no_progress"
                print(f"⚠️  Stopping early: {reason} after {stagnation_streak} unchanged iterations")
                print(
                    f"   state: actionable_dirty={dirty_count}, "
                    f"orphan_dirty={dirty_orphan_in_scope}, "
                    f"incomplete={incomplete_count}, collisions={collision_count}"
                )
                _log_event(
                    log_path,
                    "run_stalled",
                    run_id=run_id,
                    iteration=iteration,
                    reason=reason,
                    signature=list(signature),
                    stagnation_streak=stagnation_streak,
                    state=state,
                )
                return 0 if args.dry_run else 1

            action_taken = False

            # Step 1: Check for dirty payloads (need scan)
            if dirty_count > 0:
                scan_path = state["scan_path"]
                print(f"  Found {dirty_count} dirty payloads (need scan)")
                scan_result = run_scan(scan_path, args.db, args.dry_run)
                _log_event(
                    log_path,
                    "command",
                    run_id=run_id,
                    iteration=iteration,
                    command=scan_result["cmd"],
                    action="scan",
                    result=scan_result,
                )
                if not scan_result["ok"]:
                    print("  ❌ Scan failed")
                    _log_event(
                        log_path,
                        "run_failed",
                        run_id=run_id,
                        iteration=iteration,
                        reason="scan_failed",
                        result=scan_result,
                    )
                    return 1
                action_taken = True
                # Re-run payload-sync after scan to update file_count
                print("  Re-syncing payloads after scan...")
                sync_result = run_payload_sync(roots, args.db, upgrade=False, dry_run=args.dry_run)
                _log_event(
                    log_path,
                    "command",
                    run_id=run_id,
                    iteration=iteration,
                    command=sync_result["cmd"],
                    action="payload_sync",
                    result=sync_result,
                )
                if not sync_result["ok"]:
                    print("  ❌ Payload-sync failed")
                    _log_event(
                        log_path,
                        "run_failed",
                        run_id=run_id,
                        iteration=iteration,
                        reason="payload_sync_failed_after_scan",
                        result=sync_result,
                    )
                    return 1
                continue  # Re-check from top

            # Step 2: Check for incomplete payloads (need upgrade)
            if incomplete_count > 0:
                print(f"  Found {incomplete_count} incomplete payloads (need upgrade)")
                upgrade_result = run_payload_sync(roots, args.db, upgrade=True, dry_run=args.dry_run)
                _log_event(
                    log_path,
                    "command",
                    run_id=run_id,
                    iteration=iteration,
                    command=upgrade_result["cmd"],
                    action="payload_sync_upgrade",
                    result=upgrade_result,
                )
                if not upgrade_result["ok"]:
                    print("  ❌ Payload upgrade failed")
                    _log_event(
                        log_path,
                        "run_failed",
                        run_id=run_id,
                        iteration=iteration,
                        reason="payload_upgrade_failed",
                        result=upgrade_result,
                    )
                    return 1
                action_taken = True
                continue  # Re-check from top

            # Step 3: Check collision groups (scoped to roots)
            if collision_count > 0:
                print(f"  Found {collision_count} collision groups (need upgrade)")
                collision_runs = run_collision_upgrade(roots, args.db, args.dry_run)
                for run in collision_runs:
                    _log_event(
                        log_path,
                        "command",
                        run_id=run_id,
                        iteration=iteration,
                        command=run["cmd"],
                        action="payload_upgrade_collisions",
                        result=run,
                    )
                if any(not run["ok"] for run in collision_runs):
                    print("  ❌ Collision upgrade failed")
                    _log_event(
                        log_path,
                        "run_failed",
                        run_id=run_id,
                        iteration=iteration,
                        reason="collision_upgrade_failed",
                    )
                    return 1
                action_taken = True
                continue  # Re-check from top

            if not action_taken:
                if dirty_orphan_in_scope > 0:
                    print("✅ Workflow complete with warnings - only orphan payload rows remain")
                    _log_event(
                        log_path,
                        "run_complete_with_warnings",
                        run_id=run_id,
                        iteration=iteration,
                        warning="orphan_payload_rows",
                        state=state,
                    )
                else:
                    print("✅ Workflow complete - no actions needed")
                    _log_event(
                        log_path,
                        "run_complete",
                        run_id=run_id,
                        iteration=iteration,
                        state=state,
                    )
                break
        else:
            print(f"⚠️  Max iterations ({args.max_iterations}) reached")
            _log_event(
                log_path,
                "run_max_iterations",
                run_id=run_id,
                max_iterations=args.max_iterations,
            )
            return 1
    finally:
        conn.close()

    return 0


def collect_workflow_state(conn, roots: list[str]) -> dict:
    """Collect scoped/global state used for workflow decisions and diagnostics."""
    all_rows = conn.execute(
        """
        SELECT
            p.payload_id,
            p.root_path,
            p.status,
            p.file_count,
            p.total_bytes,
            COALESCE(ti.ref_count, 0) AS ref_count
        FROM payloads p
        LEFT JOIN (
            SELECT payload_id, COUNT(*) AS ref_count
            FROM torrent_instances
            GROUP BY payload_id
        ) ti ON ti.payload_id = p.payload_id
        """
    ).fetchall()
    if not all_rows:
        return {
            "dirty_in_scope": 0,
            "dirty_orphan_in_scope": 0,
            "dirty_total_in_scope": 0,
            "dirty_out_of_scope": 0,
            "incomplete_in_scope": 0,
            "collision_groups_in_scope": 0,
            "collision_groups_global": 0,
            "scan_path": None,
            "dirty_samples_out_of_scope": [],
            "dirty_orphan_samples_in_scope": [],
            "mount_alias_hint": None,
        }

    def _in_scope(root_path: str) -> bool:
        return any(root_path == root or root_path.startswith(root.rstrip("/") + "/") for root in roots)

    dirty_actionable_in_scope_paths = [rp for _, rp, _, fc, _, ref_count in all_rows if fc == 0 and ref_count > 0 and _in_scope(rp)]
    dirty_orphan_in_scope_paths = [rp for _, rp, _, fc, _, ref_count in all_rows if fc == 0 and ref_count == 0 and _in_scope(rp)]
    dirty_out_scope_paths = [rp for _, rp, _, fc, _, _ in all_rows if fc == 0 and not _in_scope(rp)]
    incomplete_in_scope = sum(
        1 for _, rp, status, fc, _, _ in all_rows
        if status == "incomplete" and fc > 0 and _in_scope(rp)
    )

    per_root_dirty = {}
    for root in roots:
        per_root_dirty[root] = sum(
            1 for rp in dirty_actionable_in_scope_paths
            if rp == root or rp.startswith(root.rstrip("/") + "/")
        )

    scan_path = None
    if dirty_actionable_in_scope_paths:
        max_dirty = max(per_root_dirty.values())
        target_root = next(root for root, count in per_root_dirty.items() if count == max_dirty)
        target_dirty_paths = [
            rp for rp in dirty_actionable_in_scope_paths
            if rp == target_root or rp.startswith(target_root.rstrip("/") + "/")
        ]
        first_target_dirty = target_dirty_paths[0] if target_dirty_paths else ""
        if "/torrents/seeding/" in first_target_dirty:
            scan_path = target_root.rstrip("/") + "/torrents/seeding"
        else:
            scan_path = target_root

    return {
        "dirty_in_scope": len(dirty_actionable_in_scope_paths),
        "dirty_orphan_in_scope": len(dirty_orphan_in_scope_paths),
        "dirty_total_in_scope": len(dirty_actionable_in_scope_paths) + len(dirty_orphan_in_scope_paths),
        "dirty_out_of_scope": len(dirty_out_scope_paths),
        "incomplete_in_scope": incomplete_in_scope,
        "collision_groups_in_scope": _count_collision_groups(conn, roots=roots, require_refs=True),
        "collision_groups_global": _count_collision_groups(conn, roots=None),
        "scan_path": scan_path,
        "dirty_samples_out_of_scope": dirty_out_scope_paths[:5],
        "dirty_orphan_samples_in_scope": dirty_orphan_in_scope_paths[:5],
        "mount_alias_hint": _mount_alias_hint(conn, roots, dirty_out_scope_paths),
    }


def state_signature(state: dict) -> tuple:
    """Signature for stagnation detection."""
    return (
        state["dirty_in_scope"],
        state["incomplete_in_scope"],
        state["collision_groups_in_scope"],
    )


def next_stagnation_streak(previous_signature: tuple | None, current_signature: tuple, streak: int) -> int:
    """Increment streak when no progress, otherwise reset."""
    if previous_signature is None:
        return 0
    if previous_signature == current_signature:
        return streak + 1
    return 0


def _count_collision_groups(conn, roots: list[str] | None, require_refs: bool = False) -> int:
    ref_join = ""
    ref_where = ""
    if require_refs:
        ref_join = """
            LEFT JOIN (
                SELECT payload_id, COUNT(*) AS ref_count
                FROM torrent_instances
                GROUP BY payload_id
            ) ti ON ti.payload_id = p.payload_id
        """
        ref_where = " AND COALESCE(ti.ref_count, 0) > 0"

    if roots:
        where_clauses = []
        params: list[str] = []
        for root in roots:
            where_clauses.append("(p.root_path = ? OR p.root_path LIKE ?)")
            params.extend([root, f"{root.rstrip('/')}/%"])
        where_expr = " OR ".join(where_clauses)
        query = f"""
            SELECT COUNT(*) FROM (
                SELECT p.file_count, p.total_bytes
                FROM payloads p
                {ref_join}
                WHERE {where_expr}
                {ref_where}
                GROUP BY p.file_count, p.total_bytes
                HAVING COUNT(*) > 1
                   AND SUM(CASE WHEN p.status = 'incomplete' THEN 1 ELSE 0 END) > 0
            )
        """
        return conn.execute(query, params).fetchone()[0]

    query = """
        SELECT COUNT(*) FROM (
            SELECT p.file_count, p.total_bytes
            FROM payloads p
            GROUP BY p.file_count, p.total_bytes
            HAVING COUNT(*) > 1
               AND SUM(CASE WHEN p.status = 'incomplete' THEN 1 ELSE 0 END) > 0
        )
    """
    return conn.execute(query).fetchone()[0]


def _mount_alias_hint(conn, roots: list[str], dirty_out_scope_paths: list[str]) -> str | None:
    """Return mount alias guidance when out-of-scope dirty paths match non-preferred mount points."""
    if not dirty_out_scope_paths:
        return None
    rows = conn.execute(
        """
        SELECT mount_point, preferred_mount_point
        FROM devices
        WHERE preferred_mount_point IS NOT NULL AND preferred_mount_point != mount_point
        """
    ).fetchall()
    for mount_point, preferred_mount_point in rows:
        if not mount_point or not preferred_mount_point:
            continue
        has_out_scope = any(rp == mount_point or rp.startswith(mount_point.rstrip("/") + "/") for rp in dirty_out_scope_paths)
        root_uses_preferred = any(root == preferred_mount_point or root.startswith(preferred_mount_point.rstrip("/") + "/") for root in roots)
        if has_out_scope and root_uses_preferred:
            return f"dirty rows under {mount_point} but workflow roots use preferred mount {preferred_mount_point}"
    return None


def run_scan(scan_path: str, db_path: str, dry_run: bool) -> dict:
    """Execute scan command."""
    cmd = [sys.executable, "-m", "hashall.cli", "scan", scan_path, "--db", db_path, "--hash-mode", "full", "--parallel"]
    return _run_cmd(cmd, dry_run=dry_run)


def run_payload_sync(roots: list[str], db_path: str, upgrade: bool, dry_run: bool) -> dict:
    """Execute payload-sync."""
    cmd = [sys.executable, "-m", "hashall.cli", "payload", "sync", "--db", db_path]
    for root in roots:
        cmd.extend(["--path-prefix", root])
    if upgrade:
        cmd.extend(["--upgrade-missing", "--parallel"])
    return _run_cmd(cmd, dry_run=dry_run)


def run_collision_upgrade(roots: list[str], db_path: str, dry_run: bool) -> list[dict]:
    """Execute payload-upgrade-collisions for all roots."""
    runs: list[dict] = []
    for root in roots:
        cmd = [sys.executable, "-m", "hashall.cli", "payload", "upgrade-collisions", "--db",
               db_path, "--path-prefix", root]
        result = _run_cmd(cmd, dry_run=dry_run)
        runs.append(result)
        if not result["ok"]:
            break
    return runs


def _run_cmd(cmd: list[str], dry_run: bool) -> dict:
    """Run a command and return structured result."""
    print(f"  → Running: {' '.join(cmd)}")
    if dry_run:
        print("    (dry-run, skipped)")
        return {
            "cmd": cmd,
            "rc": 0,
            "ok": True,
            "duration_s": 0.0,
            "dry_run": True,
        }

    start = time.monotonic()
    result = subprocess.run(cmd, env=_subprocess_env())
    duration_s = round(time.monotonic() - start, 3)
    return {
        "cmd": cmd,
        "rc": result.returncode,
        "ok": result.returncode == 0,
        "duration_s": duration_s,
        "dry_run": False,
    }


def _workflow_log_path(run_id: str) -> Path:
    preferred = Path(os.environ.get("HASHALL_PAYLOAD_AUTO_LOG_DIR", str(Path.home() / ".logs" / "hashall" / "payload-auto")))
    fallbacks = [
        preferred,
        Path("/tmp/hashall/payload-auto"),
        Path.cwd() / ".agent" / "logs" / "payload-auto",
    ]
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{run_id}.jsonl"
    for base in fallbacks:
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base / filename
        except OSError:
            continue
    return Path("/tmp") / filename


def _log_event(log_path: Path, event: str, **fields) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        **fields,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    repo_src = str(REPO_SRC)
    env["PYTHONPATH"] = repo_src if not existing else f"{repo_src}:{existing}"
    return env


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
