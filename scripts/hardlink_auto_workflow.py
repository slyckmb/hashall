#!/usr/bin/env python3
"""Automated hardlink workflow orchestration across one or more roots."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if REPO_SRC.exists():
    sys.path.insert(0, str(REPO_SRC))

from hashall.fs_utils import get_filesystem_uuid, get_mount_source
from hashall.model import connect_db
from hashall.pathing import canonicalize_path, is_under
from hashall.scan import _canonicalize_root

STALL_THRESHOLD = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-run hardlink workflow to convergence")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--roots", help="Comma-separated roots (auto-discover if omitted)")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Execute generated plans")
    parser.add_argument("--scan-each-iteration", action="store_true")
    parser.add_argument("--auto-verify-scope", action="store_true", default=True)
    parser.add_argument("--no-auto-verify-scope", action="store_false", dest="auto_verify_scope")
    parser.add_argument("--hash-mode", default="fast")
    parser.add_argument("--min-size", type=int, default=0)
    parser.add_argument("--link-limit", type=int, default=0)
    parser.add_argument("--low-priority", action="store_true", default=True)
    parser.add_argument("--normal-priority", action="store_false", dest="low_priority")
    parser.add_argument("--fix-perms", action="store_true", default=True)
    parser.add_argument("--no-fix-perms", action="store_false", dest="fix_perms")
    parser.add_argument("--fix-acl", action="store_true", default=False)
    args = parser.parse_args()

    conn = connect_db(Path(args.db), read_only=args.dry_run, apply_migrations=not args.dry_run)
    roots = _resolve_roots(conn, args.roots)
    if not roots:
        print("❌ No roots available. Pass --roots or run scans first.")
        conn.close()
        return 1

    contexts = []
    for root in roots:
        try:
            contexts.append(_resolve_root_context(conn, root))
        except Exception as exc:
            print(f"❌ Failed to resolve root {root}: {exc}")
            conn.close()
            return 1

    run_id = uuid.uuid4().hex[:10]
    log_path = _workflow_log_path(run_id)
    _log_event(
        log_path,
        "run_start",
        run_id=run_id,
        db=args.db,
        roots=roots,
        dry_run=args.dry_run,
        execute=args.execute,
        max_iterations=args.max_iterations,
        hash_mode=args.hash_mode,
    )

    print("Automated hardlink workflow")
    print(f"  Roots: {', '.join(roots)}")
    print(f"  DB: {args.db}")
    print(f"  Run ID: {run_id}")
    print(f"  Log: {log_path}")
    print(f"  Max iterations: {args.max_iterations}")
    print(f"  Execute plans: {'yes' if args.execute else 'no'}")
    if args.dry_run:
        print("  Dry-run: yes (commands skipped)")
    print()

    previous_signature = None
    stagnation_streak = 0

    max_iterations = 1 if (args.dry_run or not args.execute) else args.max_iterations

    try:
        for iteration in range(1, max_iterations + 1):
            print(f"--- Iteration {iteration} ---")
            iteration_state = {
                "roots": [],
                "scan_failures": 0,
                "scope_failures": 0,
                "execute_failures": 0,
                "main_actions": 0,
                "empty_actions": 0,
            }

            for ctx in contexts:
                root_result = _run_root_iteration(conn, ctx, args, iteration, log_path, run_id)
                iteration_state["roots"].append(root_result)
                iteration_state["scan_failures"] += root_result["scan_failures"]
                iteration_state["scope_failures"] += root_result["scope_failures"]
                iteration_state["execute_failures"] += root_result["execute_failures"]
                iteration_state["main_actions"] += root_result["main_actions"]
                iteration_state["empty_actions"] += root_result["empty_actions"]

            signature = state_signature(iteration_state)
            stagnation_streak = next_stagnation_streak(previous_signature, signature, stagnation_streak)
            previous_signature = signature

            _log_event(
                log_path,
                "iteration_state",
                run_id=run_id,
                iteration=iteration,
                signature=list(signature),
                stagnation_streak=stagnation_streak,
                state=iteration_state,
            )

            if iteration_state["scan_failures"] > 0 or iteration_state["execute_failures"] > 0:
                print("❌ Workflow failed due to command errors")
                _log_event(
                    log_path,
                    "run_failed",
                    run_id=run_id,
                    iteration=iteration,
                    reason="command_failure",
                    state=iteration_state,
                )
                return 1

            if iteration_state["scope_failures"] > 0:
                print("❌ Workflow stopped: scope verification failed")
                _log_event(
                    log_path,
                    "run_failed",
                    run_id=run_id,
                    iteration=iteration,
                    reason="scope_verification_failed",
                    state=iteration_state,
                )
                return 1

            if args.dry_run:
                print("✅ Hardlink workflow dry-run complete")
                _log_event(
                    log_path,
                    "run_complete",
                    run_id=run_id,
                    iteration=iteration,
                    mode="dry_run",
                    state=iteration_state,
                )
                return 0

            if not args.execute:
                print("✅ Hardlink workflow planning complete (execution disabled)")
                _log_event(
                    log_path,
                    "run_complete_with_warnings",
                    run_id=run_id,
                    iteration=iteration,
                    warning="execution_disabled",
                    state=iteration_state,
                )
                return 0

            if iteration_state["main_actions"] == 0 and iteration_state["empty_actions"] == 0:
                print("✅ Hardlink workflow complete - no additional actions found")
                _log_event(
                    log_path,
                    "run_complete",
                    run_id=run_id,
                    iteration=iteration,
                    state=iteration_state,
                )
                return 0

            if stagnation_streak >= STALL_THRESHOLD:
                print(f"⚠️  Stopping early: stalled_no_progress after {stagnation_streak} unchanged iterations")
                _log_event(
                    log_path,
                    "run_stalled",
                    run_id=run_id,
                    iteration=iteration,
                    reason="stalled_no_progress",
                    signature=list(signature),
                    stagnation_streak=stagnation_streak,
                    state=iteration_state,
                )
                return 1

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


def _run_root_iteration(conn, ctx: dict, args, iteration: int, log_path: Path, run_id: str) -> dict:
    current_ctx = _resolve_root_context(conn, ctx["root_input"])
    root = current_ctx["root_input"]
    canonical_root = current_ctx["canonical_root"]
    device_label = current_ctx["device_alias"]

    print(f"  Root: {root} [{device_label}]")

    result = {
        "root": root,
        "canonical_root": canonical_root,
        "device_alias": device_label,
        "scan_failures": 0,
        "scope_failures": 0,
        "execute_failures": 0,
        "main_actions": 0,
        "empty_actions": 0,
        "main_plan_id": None,
        "empty_plan_id": None,
    }

    if iteration == 1 or args.scan_each_iteration:
        scan_result = run_scan(canonical_root, args.db, args.hash_mode, args.dry_run)
        _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="scan", command=scan_result["cmd"], result=scan_result)
        if not scan_result["ok"]:
            result["scan_failures"] += 1
            return result

        sync_result = run_payload_sync(root, args.db, args.dry_run)
        _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="payload_sync", command=sync_result["cmd"], result=sync_result)
        if not sync_result["ok"]:
            result["scan_failures"] += 1
            return result

        upgrade_result = run_payload_upgrade_collisions(root, args.db, args.dry_run)
        _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="payload_upgrade_collisions", command=upgrade_result["cmd"], result=upgrade_result)
        if not upgrade_result["ok"]:
            result["scan_failures"] += 1
            return result

    plan_name = f"hardlink auto {root} iter{iteration}"
    plan_result = run_link_plan(plan_name, current_ctx["device_key"], args.db, args.min_size, args.dry_run)
    _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="link_plan", command=plan_result["cmd"], result=plan_result)
    if not plan_result["ok"]:
        result["scan_failures"] += 1
        return result

    if args.dry_run:
        empty_name = f"empty payload {root} iter{iteration}"
        empty_plan_result = run_link_plan_payload_empty(
            empty_name,
            current_ctx["device_key"],
            args.db,
            args.dry_run,
        )
        _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="link_plan_payload_empty", command=empty_plan_result["cmd"], result=empty_plan_result)
        if not empty_plan_result["ok"]:
            result["scan_failures"] += 1
            return result
        print("    plans: dry-run (not created)")
        _log_event(log_path, "root_summary", run_id=run_id, iteration=iteration, root=root, summary=result)
        return result

    main_plan = _find_recent_plan(conn, current_ctx["device_id"], current_ctx["rel_root"], include_payload_empty=False)
    if main_plan:
        result["main_plan_id"] = main_plan["id"]
        result["main_actions"] = main_plan["actions_pending"]

        if args.auto_verify_scope:
            verify_result = run_verify_scope(root, main_plan["id"], args.db, args.dry_run)
            _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="verify_scope_main", command=verify_result["cmd"], result=verify_result)
            if not verify_result["ok"] or verify_result["rc"] == 2:
                result["scope_failures"] += 1

        if args.execute and main_plan["actions_pending"] > 0:
            exec_result = run_link_execute(
                main_plan["id"],
                args.db,
                args.link_limit,
                args.low_priority,
                args.fix_perms,
                args.fix_acl,
                args.dry_run,
            )
            _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="link_execute_main", command=exec_result["cmd"], result=exec_result)
            if not exec_result["ok"]:
                result["execute_failures"] += 1

    empty_name = f"empty payload {root} iter{iteration}"
    empty_plan_result = run_link_plan_payload_empty(
        empty_name,
        current_ctx["device_key"],
        args.db,
        args.dry_run,
    )
    _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="link_plan_payload_empty", command=empty_plan_result["cmd"], result=empty_plan_result)
    if not empty_plan_result["ok"]:
        result["scan_failures"] += 1
        return result

    empty_plan = _find_recent_plan(conn, current_ctx["device_id"], current_ctx["rel_root"], include_payload_empty=True)
    if empty_plan:
        result["empty_plan_id"] = empty_plan["id"]
        result["empty_actions"] = empty_plan["actions_pending"]

        if args.auto_verify_scope:
            verify_result = run_verify_scope(root, empty_plan["id"], args.db, args.dry_run)
            _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="verify_scope_empty", command=verify_result["cmd"], result=verify_result)
            if not verify_result["ok"] or verify_result["rc"] == 2:
                result["scope_failures"] += 1

        if args.execute and empty_plan["actions_pending"] > 0:
            exec_result = run_link_execute(
                empty_plan["id"],
                args.db,
                args.link_limit,
                args.low_priority,
                args.fix_perms,
                args.fix_acl,
                args.dry_run,
            )
            _log_event(log_path, "command", run_id=run_id, iteration=iteration, root=root, step="link_execute_empty", command=exec_result["cmd"], result=exec_result)
            if not exec_result["ok"]:
                result["execute_failures"] += 1

    print(
        f"    plans: main={result['main_plan_id']} actions={result['main_actions']} | "
        f"empty={result['empty_plan_id']} actions={result['empty_actions']}"
    )
    _log_event(log_path, "root_summary", run_id=run_id, iteration=iteration, root=root, summary=result)
    return result


def _resolve_roots(conn: sqlite3.Connection, roots_arg: Optional[str]) -> list[str]:
    if roots_arg:
        return [r.strip() for r in roots_arg.split(",") if r.strip()]
    return _discover_roots(conn)


def _discover_roots(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT root_path
        FROM scan_roots
        WHERE root_path IS NOT NULL AND root_path != ''
        ORDER BY COALESCE(last_scanned_at, '') DESC, root_path ASC
        """
    ).fetchall()
    seen = set()
    roots = []
    for row in rows:
        root = str(row[0])
        if root not in seen:
            roots.append(root)
            seen.add(root)
    return roots


def _resolve_root_context(conn: sqlite3.Connection, root: str) -> dict:
    root_input = str(Path(root))
    root_resolved = Path(root).resolve()
    root_canonical = canonicalize_path(root_resolved)
    device_id = os.stat(root_canonical).st_dev

    row = conn.execute(
        "SELECT device_alias, mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()

    if row:
        device_alias = row[0] or str(device_id)
        current_mount = Path(row[1])
        preferred_mount = Path(row[2] or row[1])
    else:
        device_alias = str(device_id)
        current_mount = Path(root_canonical.anchor if root_canonical.anchor else "/")
        preferred_mount = current_mount

    mount_source = get_mount_source(str(root_canonical)) or ""
    canonical_root = _canonicalize_root(
        root_canonical,
        current_mount,
        preferred_mount,
        allow_remap=bool(mount_source),
    )
    effective_mount = preferred_mount if is_under(canonical_root, preferred_mount) else current_mount
    try:
        rel_root = canonical_root.relative_to(effective_mount)
    except ValueError:
        rel_root = Path(".")

    return {
        "root_input": root_input,
        "root_canonical": str(root_canonical),
        "canonical_root": str(canonical_root),
        "device_id": device_id,
        "device_alias": device_alias,
        "device_key": device_alias if row and row[0] else str(device_id),
        "rel_root": str(rel_root),
        "fs_uuid": get_filesystem_uuid(str(root_canonical)),
    }


def _find_recent_plan(conn: sqlite3.Connection, device_id: int, rel_root: str, include_payload_empty: bool) -> Optional[dict]:
    params: list[object]
    if rel_root == ".":
        if include_payload_empty:
            query = """
                SELECT id, status, actions_total, actions_executed, actions_failed, actions_skipped
                FROM link_plans
                WHERE device_id = ?
                  AND (notes LIKE ? OR metadata LIKE ?)
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [device_id, "%payload_empty%", "%payload_empty%"]
        else:
            query = """
                SELECT id, status, actions_total, actions_executed, actions_failed, actions_skipped
                FROM link_plans
                WHERE device_id = ?
                  AND (notes NOT LIKE ? OR notes IS NULL)
                  AND (metadata NOT LIKE ? OR metadata IS NULL)
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [device_id, "%payload_empty%", "%payload_empty%"]
    else:
        pattern = f"{rel_root.rstrip('/')}/%"
        marker_clause = "AND (lp.notes LIKE ? OR lp.metadata LIKE ?)" if include_payload_empty else "AND ((lp.notes NOT LIKE ? OR lp.notes IS NULL) AND (lp.metadata NOT LIKE ? OR lp.metadata IS NULL))"
        query = f"""
            SELECT lp.id, lp.status, lp.actions_total, lp.actions_executed, lp.actions_failed, lp.actions_skipped
            FROM link_plans lp
            WHERE lp.device_id = ?
              {marker_clause}
              AND EXISTS (
                    SELECT 1 FROM link_actions la
                    WHERE la.plan_id = lp.id
                      AND (
                           la.canonical_path = ? OR la.canonical_path LIKE ?
                        OR la.duplicate_path = ? OR la.duplicate_path LIKE ?
                      )
              )
            ORDER BY lp.created_at DESC
            LIMIT 1
        """
        params = [
            device_id,
            "%payload_empty%",
            "%payload_empty%",
            rel_root,
            pattern,
            rel_root,
            pattern,
        ]

    row = conn.execute(query, params).fetchone()
    if not row:
        return None

    actions_total = int(row[2] or 0)
    actions_executed = int(row[3] or 0)
    actions_failed = int(row[4] or 0)
    actions_skipped = int(row[5] or 0)
    pending = max(0, actions_total - actions_executed - actions_failed - actions_skipped)

    return {
        "id": int(row[0]),
        "status": str(row[1]),
        "actions_total": actions_total,
        "actions_pending": pending,
    }


def state_signature(state: dict) -> tuple[int, int, int]:
    return (
        int(state["main_actions"]),
        int(state["empty_actions"]),
        int(state["scope_failures"]),
    )


def next_stagnation_streak(previous_signature: Optional[tuple], current_signature: tuple, streak: int) -> int:
    if previous_signature is None:
        return 0
    if previous_signature == current_signature:
        return streak + 1
    return 0


def run_scan(root: str, db_path: str, hash_mode: str, dry_run: bool) -> dict:
    cmd = [sys.executable, "-m", "hashall.cli", "scan", root, "--db", db_path, "--hash-mode", hash_mode, "--parallel"]
    return _run_cmd(cmd, dry_run=dry_run)


def run_payload_sync(root: str, db_path: str, dry_run: bool) -> dict:
    cmd = [sys.executable, "-m", "hashall.cli", "payload", "sync", "--db", db_path, "--path-prefix", root]
    return _run_cmd(cmd, dry_run=dry_run)


def run_payload_upgrade_collisions(root: str, db_path: str, dry_run: bool) -> dict:
    cmd = [sys.executable, "-m", "hashall.cli", "payload", "upgrade-collisions", "--db", db_path, "--path-prefix", root]
    return _run_cmd(cmd, dry_run=dry_run)


def run_link_plan(name: str, device: str, db_path: str, min_size: int, dry_run: bool) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "link",
        "plan",
        name,
        "--device",
        device,
        "--db",
        db_path,
    ]
    if min_size > 0:
        cmd.extend(["--min-size", str(min_size)])
    return _run_cmd(cmd, dry_run=dry_run)


def run_link_plan_payload_empty(name: str, device: str, db_path: str, dry_run: bool) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "link",
        "plan-payload-empty",
        name,
        "--device",
        device,
        "--db",
        db_path,
    ]
    return _run_cmd(cmd, dry_run=dry_run)


def run_verify_scope(root: str, plan_id: int, db_path: str, dry_run: bool) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "link",
        "verify-scope",
        root,
        "--plan-id",
        str(plan_id),
        "--db",
        db_path,
        "--max-examples",
        "0",
    ]
    return _run_cmd(cmd, dry_run=dry_run)


def run_link_execute(
    plan_id: int,
    db_path: str,
    link_limit: int,
    low_priority: bool,
    fix_perms: bool,
    fix_acl: bool,
    dry_run: bool,
) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "link",
        "execute",
        str(plan_id),
        "--db",
        db_path,
        "--yes",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if link_limit > 0:
        cmd.extend(["--limit", str(link_limit)])
    if low_priority:
        cmd.append("--low-priority")
    if fix_perms:
        cmd.append("--fix-perms")
    else:
        cmd.append("--no-fix-perms")
    if fix_acl:
        cmd.append("--fix-acl")
    return _run_cmd(cmd, dry_run=dry_run)


def _run_cmd(cmd: list[str], dry_run: bool) -> dict:
    print(f"    → Running: {' '.join(cmd)}")
    if dry_run:
        print("      (dry-run, skipped)")
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


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    repo_src = str(REPO_SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_src if not existing else f"{repo_src}:{existing}"
    return env


def _workflow_log_path(run_id: str) -> Path:
    preferred = Path(os.environ.get("HASHALL_HARDLINK_AUTO_LOG_DIR", str(Path.home() / ".logs" / "hashall" / "hardlink-auto")))
    fallbacks = [
        preferred,
        Path("/tmp/hashall/hardlink-auto"),
        Path.cwd() / ".agent" / "logs" / "hardlink-auto",
    ]
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{run_id}.jsonl"
    for base in fallbacks:
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base / filename
        except OSError:
            continue
    return Path("/tmp") / filename


def _log_event(path: Path, event: str, **fields) -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
    row.update(fields)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
