#!/usr/bin/env python3
"""Automated payload workflow - runs scan/sync/upgrade loop until complete."""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
ORPHAN_GC_MIN_SEEN_RUNS = 2
ORPHAN_GC_MIN_AGE_SECONDS = 24 * 60 * 60
QBIT_COMPLETE_PROGRESS = 0.999999
QBIT_MANAGE_FRESHNESS_MAX_MINUTES = 120


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-run payload workflow to completion")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--roots", help="Comma-separated roots (auto-discover if omitted)")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max loop iterations")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without executing")
    parser.add_argument("--backup", action="store_true", help="Create a timestamped DB backup before running")
    parser.add_argument("--backup-dir", help="Optional directory for --backup output (default: DB parent)")
    args = parser.parse_args()

    db_path = Path(args.db)
    backup_path = None
    if args.backup:
        try:
            backup_dir = Path(args.backup_dir) if args.backup_dir else None
            backup_path = _backup_db(db_path, backup_dir=backup_dir)
        except OSError as e:
            print(f"❌ Failed to create DB backup: {e}")
            return 1

    conn = connect_db(db_path)

    # Discover or parse roots
    if args.roots:
        roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    else:
        roots = _discover_roots(conn)

    if not roots:
        print("No roots found. Run 'make payload-sync' first.")
        return 1

    completed_hashes, completion_filter_active, completion_filter_error = _load_completed_torrent_hashes()
    qbm_freshness = _qbit_manage_freshness()

    run_id = uuid.uuid4().hex[:10]
    log_path = _workflow_log_path(run_id)
    _log_event(
        log_path,
        "run_start",
        run_id=run_id,
        db=args.db,
        db_backup=str(backup_path) if backup_path else None,
        roots=roots,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
        completion_filter_active=completion_filter_active,
        completion_filter_error=completion_filter_error,
        qbm_freshness=qbm_freshness,
    )

    print(f"Automated payload workflow")
    print(f"  Roots: {', '.join(roots)}")
    print(f"  DB: {args.db}")
    if backup_path:
        print(f"  DB backup: {backup_path}")
    print(f"  Run ID: {run_id}")
    print(f"  Log: {log_path}")
    print(f"  Max iterations: {args.max_iterations}")
    if completion_filter_active:
        print(f"  qB completion filter: active (ignoring refs below 100% progress)")
    elif completion_filter_error:
        print(f"  qB completion filter: disabled ({completion_filter_error})")

    qbm_age = qbm_freshness.get("age_seconds")
    if qbm_freshness["status"] == "fresh":
        print(
            "  qbit_manage freshness: fresh "
            f"(age={int(qbm_age)}s <= {int(qbm_freshness['max_age_seconds'])}s)"
        )
    elif qbm_freshness["status"] == "stale":
        print(
            "  ⚠ qbit_manage freshness: stale "
            f"(age={int(qbm_age)}s > {int(qbm_freshness['max_age_seconds'])}s)"
        )
    else:
        print(f"  qbit_manage freshness: unknown ({qbm_freshness.get('reason')})")

    fail_closed = os.environ.get("HASHALL_QBM_FRESH_FAIL_CLOSED") == "1"
    if fail_closed:
        print("  qbit_manage freshness policy: fail-closed")

    if fail_closed and qbm_freshness["status"] != "fresh":
        reason = "qbit_manage_freshness_not_fresh"
        print(f"❌ Stopping: {reason}")
        _log_event(
            log_path,
            "run_failed",
            run_id=run_id,
            iteration=0,
            reason=reason,
            qbm_freshness=qbm_freshness,
        )
        conn.close()
        return 1

    print()

    previous_signature = None
    stagnation_streak = 0
    iteration = 0

    try:
        # Main loop
        for iteration in range(1, args.max_iterations + 1):
            print(f"--- Iteration {iteration} ---")
            state = collect_workflow_state(
                conn,
                roots,
                completed_hashes=completed_hashes,
                completion_filter_active=completion_filter_active,
            )
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
            dirty_orphan_alias_in_scope = state["dirty_orphan_alias_in_scope"]
            dirty_pending_in_scope = state["dirty_noncomplete_in_scope"]
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
                print(
                    "  ⚠ Orphan GC staging: "
                    f"tracked={state['orphan_gc_tracked_in_scope']}, "
                    f"aged={state['orphan_gc_aged_in_scope']}"
                )

            if dirty_orphan_alias_in_scope > 0:
                print(
                    f"  ℹ In-scope orphan alias rows with active files: {dirty_orphan_alias_in_scope} "
                    f"(samples: {', '.join(state['dirty_orphan_alias_samples_in_scope'])})"
                )

            if dirty_pending_in_scope > 0:
                print(
                    f"  ⚠ In-scope dirty refs below 100% progress: {dirty_pending_in_scope} "
                    f"(samples: {', '.join(state['dirty_noncomplete_samples_in_scope'])})"
                )

            if stagnation_streak >= STALL_THRESHOLD:
                reason = "stalled_no_progress"
                print(f"⚠️  Stopping early: {reason} after {stagnation_streak} unchanged iterations")
                print(
                    f"   state: actionable_dirty={dirty_count}, "
                    f"pending_noncomplete={dirty_pending_in_scope}, "
                    f"orphan_dirty={dirty_orphan_in_scope}, "
                    f"orphan_alias={dirty_orphan_alias_in_scope}, "
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
                if args.dry_run:
                    print("✅ Workflow dry-run preview complete")
                    _log_event(
                        log_path,
                        "run_complete_dry_run",
                        run_id=run_id,
                        iteration=iteration,
                        reason="scan_and_resync_previewed",
                        state=state,
                    )
                    break
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
                if args.dry_run:
                    print("✅ Workflow dry-run preview complete")
                    _log_event(
                        log_path,
                        "run_complete_dry_run",
                        run_id=run_id,
                        iteration=iteration,
                        reason="payload_upgrade_previewed",
                        state=state,
                    )
                    break
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
                if args.dry_run:
                    print("✅ Workflow dry-run preview complete")
                    _log_event(
                        log_path,
                        "run_complete_dry_run",
                        run_id=run_id,
                        iteration=iteration,
                        reason="collision_upgrade_previewed",
                        state=state,
                    )
                    break
                continue  # Re-check from top

            if not action_taken:
                warnings: list[str] = []
                if dirty_orphan_in_scope > 0:
                    warnings.append("orphan payload rows remain")
                if dirty_pending_in_scope > 0:
                    warnings.append("non-100% torrent refs were ignored")

                if warnings:
                    print(f"✅ Workflow complete with warnings - {'; '.join(warnings)}")
                    _log_event(
                        log_path,
                        "run_complete_with_warnings",
                        run_id=run_id,
                        iteration=iteration,
                        warning="; ".join(warnings),
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
    except KeyboardInterrupt:
        print("⚠️ Interrupted by user")
        _log_event(
            log_path,
            "run_interrupted",
            run_id=run_id,
            iteration=iteration,
            reason="keyboard_interrupt",
        )
        return 130
    finally:
        conn.close()

    return 0


def collect_workflow_state(
    conn,
    roots: list[str],
    *,
    completed_hashes: set[str] | None = None,
    completion_filter_active: bool = False,
) -> dict:
    """Collect scoped/global state used for workflow decisions and diagnostics."""
    payload_rows = conn.execute(
        "SELECT payload_id, device_id, root_path, status, file_count, total_bytes FROM payloads"
    ).fetchall()
    if not payload_rows:
        return {
            "dirty_in_scope": 0,
            "dirty_noncomplete_in_scope": 0,
            "dirty_orphan_in_scope": 0,
            "dirty_orphan_alias_in_scope": 0,
            "dirty_total_in_scope": 0,
            "dirty_out_of_scope": 0,
            "incomplete_in_scope": 0,
            "collision_groups_in_scope": 0,
            "collision_groups_global": 0,
            "scan_path": None,
            "dirty_samples_out_of_scope": [],
            "dirty_noncomplete_samples_in_scope": [],
            "dirty_orphan_samples_in_scope": [],
            "dirty_orphan_alias_samples_in_scope": [],
            "mount_alias_hint": None,
            "orphan_gc_tracked_in_scope": 0,
            "orphan_gc_aged_in_scope": 0,
            "completion_filter_active": completion_filter_active,
        }

    completed_hashes = {h.lower() for h in (completed_hashes or set())}
    ref_rows = conn.execute("SELECT payload_id, torrent_hash FROM torrent_instances").fetchall()
    ref_count_by_payload: dict[int, int] = {}
    complete_ref_by_payload: dict[int, bool] = {}
    for payload_id, torrent_hash in ref_rows:
        pid = int(payload_id)
        ref_count_by_payload[pid] = ref_count_by_payload.get(pid, 0) + 1
        if completion_filter_active and torrent_hash and str(torrent_hash).lower() in completed_hashes:
            complete_ref_by_payload[pid] = True

    def _in_scope(root_path: str) -> bool:
        return any(root_path == root or root_path.startswith(root.rstrip("/") + "/") for root in roots)

    zero_count_in_scope = [
        (int(device_id), root_path)
        for _, device_id, root_path, _, file_count, _ in payload_rows
        if device_id is not None and int(file_count) == 0 and _in_scope(root_path)
    ]
    live_counts = _batch_live_active_file_counts(conn, zero_count_in_scope)

    dirty_actionable_in_scope_paths: list[str] = []
    dirty_noncomplete_in_scope_paths: list[str] = []
    dirty_orphan_in_scope_paths: list[str] = []
    dirty_orphan_alias_in_scope_paths: list[str] = []
    dirty_out_scope_paths: list[str] = []
    incomplete_in_scope = 0
    scoped_rows: list[dict[str, object]] = []

    for payload_id, device_id, root_path, status, file_count, total_bytes in payload_rows:
        payload_id = int(payload_id)
        file_count = int(file_count)
        ref_count = int(ref_count_by_payload.get(payload_id, 0))
        has_complete_ref = bool(complete_ref_by_payload.get(payload_id, False))
        in_scope = _in_scope(root_path)
        live_file_count = file_count

        if in_scope and file_count == 0 and device_id is not None:
            live_file_count = live_counts.get((int(device_id), root_path), 0)

        scoped_rows.append(
            {
                "payload_id": payload_id,
                "root_path": root_path,
                "status": status,
                "file_count": live_file_count,
                "total_bytes": int(total_bytes),
                "ref_count": ref_count,
                "has_complete_ref": has_complete_ref,
                "in_scope": in_scope,
            }
        )

        if status == "incomplete" and live_file_count > 0 and in_scope:
            incomplete_in_scope += 1

        if file_count != 0:
            continue

        if not in_scope:
            dirty_out_scope_paths.append(root_path)
            continue

        if live_file_count > 0:
            if ref_count == 0:
                dirty_orphan_alias_in_scope_paths.append(root_path)
            continue

        if ref_count == 0:
            dirty_orphan_in_scope_paths.append(root_path)
            continue

        if completion_filter_active and not has_complete_ref:
            dirty_noncomplete_in_scope_paths.append(root_path)
        else:
            dirty_actionable_in_scope_paths.append(root_path)

    collision_groups_in_scope = _count_collision_groups_from_rows(
        scoped_rows,
        in_scope_only=True,
        require_refs=True,
        completion_filter_active=completion_filter_active,
    )
    collision_groups_global = _count_collision_groups_from_rows(
        scoped_rows,
        in_scope_only=False,
        require_refs=False,
        completion_filter_active=False,
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
        scan_path = _remap_scan_path_to_preferred_mount(conn, scan_path)
    orphan_gc_tracked_in_scope, orphan_gc_aged_in_scope = _orphan_gc_metrics(conn, roots)

    return {
        "dirty_in_scope": len(dirty_actionable_in_scope_paths),
        "dirty_noncomplete_in_scope": len(dirty_noncomplete_in_scope_paths),
        "dirty_orphan_in_scope": len(dirty_orphan_in_scope_paths),
        "dirty_orphan_alias_in_scope": len(dirty_orphan_alias_in_scope_paths),
        "dirty_total_in_scope": (
            len(dirty_actionable_in_scope_paths)
            + len(dirty_noncomplete_in_scope_paths)
            + len(dirty_orphan_in_scope_paths)
        ),
        "dirty_out_of_scope": len(dirty_out_scope_paths),
        "incomplete_in_scope": incomplete_in_scope,
        "collision_groups_in_scope": collision_groups_in_scope,
        "collision_groups_global": collision_groups_global,
        "scan_path": scan_path,
        "dirty_samples_out_of_scope": dirty_out_scope_paths[:5],
        "dirty_noncomplete_samples_in_scope": dirty_noncomplete_in_scope_paths[:5],
        "dirty_orphan_samples_in_scope": dirty_orphan_in_scope_paths[:5],
        "dirty_orphan_alias_samples_in_scope": dirty_orphan_alias_in_scope_paths[:5],
        "mount_alias_hint": _mount_alias_hint(conn, roots, dirty_out_scope_paths),
        "orphan_gc_tracked_in_scope": orphan_gc_tracked_in_scope,
        "orphan_gc_aged_in_scope": orphan_gc_aged_in_scope,
        "completion_filter_active": completion_filter_active,
    }


def _batch_live_active_file_counts(
    conn,
    keys: list[tuple[int, str]],
) -> dict[tuple[int, str], int]:
    """Batch active-file counts for (device_id, root_path) pairs."""
    if not keys:
        return {}

    device_mounts: dict[int, tuple[str | None, str | None]] = {}
    has_devices = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
    ).fetchone()
    if has_devices:
        for row in conn.execute(
            "SELECT device_id, mount_point, preferred_mount_point FROM devices"
        ).fetchall():
            did = int(row[0])
            mount_point = row[1]
            preferred_mount = row[2] or row[1]
            device_mounts[did] = (mount_point, preferred_mount)

    out: dict[tuple[int, str], int] = {(device_id, root_path): 0 for device_id, root_path in keys}

    by_device: dict[int, list[str]] = {}
    for device_id, root_path in keys:
        by_device.setdefault(device_id, []).append(root_path)

    for device_id, root_paths in by_device.items():
        table_name = f"files_{int(device_id)}"
        if not conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone():
            continue

        status_clause = "status='active' AND " if _table_has_column(conn, table_name, "status") else ""

        rel_to_roots: dict[str, list[str]] = {}
        root_all: list[str] = []
        mount_point, preferred_mount = device_mounts.get(device_id, (None, None))
        for root_path in root_paths:
            rel_root = _to_rel_root_for_device(root_path, mount_point, preferred_mount)
            if rel_root is None:
                continue
            if rel_root == ".":
                root_all.append(root_path)
                continue
            rel_to_roots.setdefault(rel_root, []).append(root_path)

        if root_all:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE {status_clause}1=1"
            ).fetchone()
            count_all = int(row[0] or 0)
            for root_path in root_all:
                out[(device_id, root_path)] = count_all

        if not rel_to_roots:
            continue

        rel_root_counts: dict[str, int] = {rel_root: 0 for rel_root in rel_to_roots.keys()}
        rel_root_lookup = set(rel_root_counts.keys())
        path_rows = conn.execute(
            f"SELECT path FROM {table_name} WHERE {status_clause}1=1"
        ).fetchall()

        for row in path_rows:
            file_path = row[0]
            if not file_path:
                continue

            if file_path in rel_root_lookup:
                rel_root_counts[file_path] += 1

            idx = 0
            while True:
                idx = file_path.find("/", idx)
                if idx <= 0:
                    break
                prefix = file_path[:idx]
                if prefix in rel_root_lookup:
                    rel_root_counts[prefix] += 1
                idx += 1

        for rel_root, count in rel_root_counts.items():
            for root_path in rel_to_roots.get(rel_root, []):
                out[(device_id, root_path)] = int(count or 0)

    return out


def _to_rel_root_for_device(
    root_path: str,
    mount_point: str | None,
    preferred_mount: str | None,
) -> str | None:
    """Map absolute root path to per-device relative table path."""
    if not Path(root_path).is_absolute():
        return root_path

    for base in (preferred_mount, mount_point):
        if not base:
            continue
        if root_path == base:
            return "."
        prefix = base.rstrip("/") + "/"
        if root_path.startswith(prefix):
            return root_path[len(prefix):]

    return None


def _table_has_column(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _remap_scan_path_to_preferred_mount(conn, scan_path: str | None) -> str | None:
    """Use preferred mount aliases for scan path when device rows provide one."""
    if not scan_path:
        return scan_path
    p = Path(scan_path)
    rows = conn.execute(
        """
        SELECT mount_point, preferred_mount_point
        FROM devices
        WHERE preferred_mount_point IS NOT NULL AND preferred_mount_point != mount_point
        """
    ).fetchall()
    for mount_point, preferred_mount in rows:
        if not mount_point or not preferred_mount:
            continue
        mount_p = Path(mount_point)
        pref_p = Path(preferred_mount)
        if p == mount_p or str(p).startswith(str(mount_p).rstrip("/") + "/"):
            try:
                rel = p.relative_to(mount_p)
            except ValueError:
                continue
            return str(pref_p / rel)
    return scan_path


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


def _count_collision_groups_from_rows(
    rows: list[dict[str, object]],
    *,
    in_scope_only: bool,
    require_refs: bool,
    completion_filter_active: bool,
) -> int:
    groups: dict[tuple[int, int], dict[str, int]] = {}
    for row in rows:
        if in_scope_only and not bool(row["in_scope"]):
            continue
        if require_refs:
            if int(row["ref_count"]) <= 0:
                continue
            if completion_filter_active and not bool(row["has_complete_ref"]):
                continue

        key = (int(row["file_count"]), int(row["total_bytes"]))
        g = groups.setdefault(key, {"count": 0, "incomplete_count": 0})
        g["count"] += 1
        if row["status"] == "incomplete":
            g["incomplete_count"] += 1

    return sum(1 for g in groups.values() if g["count"] > 1 and g["incomplete_count"] > 0)


def _load_completed_torrent_hashes() -> tuple[set[str], bool, str | None]:
    """Return completed torrent hashes from qB; disable filtering if unavailable."""
    try:
        from hashall.qbittorrent import get_qbittorrent_client
    except Exception as exc:
        return set(), False, f"qB client import failed: {exc}"

    qbit = get_qbittorrent_client()
    if not qbit.test_connection():
        return set(), False, f"qB unreachable: {qbit.last_error or 'connection failed'}"
    if not qbit.login():
        return set(), False, f"qB login failed: {qbit.last_error or 'authentication failed'}"

    torrents = qbit.get_torrents()
    completed = {
        str(t.hash).lower()
        for t in torrents
        if t.hash and float(t.progress or 0.0) >= QBIT_COMPLETE_PROGRESS
    }
    return completed, True, None


def _qbit_manage_freshness() -> dict[str, object]:
    """Return qbit_manage activity freshness from local logs."""
    max_age_minutes_raw = os.environ.get(
        "HASHALL_QBM_FRESH_MAX_MINUTES",
        str(QBIT_MANAGE_FRESHNESS_MAX_MINUTES),
    )
    try:
        max_age_minutes = max(1, int(max_age_minutes_raw))
    except ValueError:
        max_age_minutes = QBIT_MANAGE_FRESHNESS_MAX_MINUTES
    max_age_seconds = max_age_minutes * 60

    configured_log = os.environ.get("HASHALL_QBM_ACTIVITY_LOG")
    candidates: list[Path] = []
    if configured_log:
        candidates.append(Path(configured_log))

    log_only = os.environ.get("HASHALL_QBM_ACTIVITY_LOG_ONLY") == "1"
    if not log_only:
        candidates.extend(
            [
                Path("/dump/docker/qbit_manage/logs/activity.log"),
                Path("/data/docker/qbit_manage/logs/activity.log"),
            ]
        )

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            age_seconds = max(0.0, time.time() - candidate.stat().st_mtime)
            status = "fresh" if age_seconds <= max_age_seconds else "stale"
            return {
                "status": status,
                "path": str(candidate),
                "age_seconds": round(age_seconds, 3),
                "max_age_seconds": max_age_seconds,
                "reason": None,
            }
        except OSError:
            continue

    return {
        "status": "unknown",
        "path": str(candidates[0]) if candidates else None,
        "age_seconds": None,
        "max_age_seconds": max_age_seconds,
        "reason": "activity_log_not_found",
    }


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


def _orphan_gc_metrics(conn, roots: list[str]) -> tuple[int, int]:
    """Return (tracked, aged) orphan-GC candidate counts scoped to roots."""
    has_gc_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='payload_orphan_gc'"
    ).fetchone()
    if not has_gc_table:
        return 0, 0

    predicates: list[str] = []
    params: list[object] = [ORPHAN_GC_MIN_SEEN_RUNS, time.time(), ORPHAN_GC_MIN_AGE_SECONDS]
    for root in roots:
        root_s = str(root)
        predicates.append("(p.root_path = ? OR p.root_path LIKE ?)")
        params.extend([root_s, f"{root_s.rstrip('/')}/%"])

    if not predicates:
        return 0, 0

    scope_sql = " OR ".join(predicates)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS tracked,
            SUM(
                CASE
                    WHEN og.seen_count >= ?
                     AND (? - og.first_seen_at) >= ?
                    THEN 1 ELSE 0
                END
            ) AS aged
        FROM payload_orphan_gc og
        JOIN payloads p ON p.payload_id = og.payload_id
        LEFT JOIN (
            SELECT payload_id, COUNT(*) AS ref_count
            FROM torrent_instances
            GROUP BY payload_id
        ) ti ON ti.payload_id = p.payload_id
        WHERE COALESCE(ti.ref_count, 0) = 0
          AND p.file_count = 0
          AND ({scope_sql})
        """,
        params,
    ).fetchone()
    tracked = int(row[0] or 0)
    aged = int(row[1] or 0)
    return tracked, aged


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


def _backup_db(db_path: Path, backup_dir: Path | None = None) -> Path:
    """Create a timestamped copy of the SQLite catalog for quick rollback testing."""
    db_path = Path(db_path)
    out_dir = backup_dir or db_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = out_dir / f"{db_path.name}.backup-{stamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


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
