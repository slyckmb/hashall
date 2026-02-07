#!/usr/bin/env python3
"""Report workflow status for a path (scan, link, payload, empty-link)."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from hashall.model import connect_db
from hashall.pathing import canonicalize_path, is_under
from hashall.fs_utils import get_filesystem_uuid, get_mount_point, get_mount_source
from hashall.scan import _canonicalize_root


def _resolve_device(conn: sqlite3.Connection, root: Path) -> tuple[int, str, Path, Path]:
    device_id = os.stat(root).st_dev
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
        current_mount = Path(get_mount_point(str(root)) or str(root))
        preferred_mount = current_mount
    return device_id, device_alias, current_mount, preferred_mount


def _rel_root(root: Path, current_mount: Path, preferred_mount: Path) -> tuple[Path, Path]:
    effective_mount = preferred_mount if is_under(root, preferred_mount) else current_mount
    try:
        rel_root = root.relative_to(effective_mount)
    except ValueError:
        rel_root = Path(".")
    return rel_root, effective_mount


def _find_recent_plan(
    conn: sqlite3.Connection,
    device_id: int,
    rel_root_str: str,
) -> tuple | None:
    if rel_root_str == ".":
        return conn.execute(
            """
            SELECT id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped
            FROM link_plans
            WHERE device_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()

    pattern = f"{rel_root_str}/%"
    return conn.execute(
        """
        SELECT lp.id, lp.name, lp.status, lp.created_at,
               lp.actions_total, lp.actions_executed, lp.actions_failed, lp.actions_skipped
        FROM link_plans lp
        WHERE lp.device_id = ?
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
        """,
        (device_id, rel_root_str, pattern, rel_root_str, pattern),
    ).fetchone()


def _find_recent_empty_plan(
    conn: sqlite3.Connection,
    device_id: int,
    rel_root_str: str,
) -> tuple | None:
    marker = "%payload_empty%"
    if rel_root_str == ".":
        return conn.execute(
            """
            SELECT lp.id, lp.name, lp.status, lp.created_at,
                   lp.actions_total, lp.actions_executed, lp.actions_failed, lp.actions_skipped
            FROM link_plans lp
            WHERE lp.device_id = ?
              AND (lp.notes LIKE ? OR lp.metadata LIKE ?)
            ORDER BY lp.created_at DESC
            LIMIT 1
            """,
            (device_id, marker, marker),
        ).fetchone()

    pattern = f"{rel_root_str}/%"
    return conn.execute(
        """
        SELECT lp.id, lp.name, lp.status, lp.created_at,
               lp.actions_total, lp.actions_executed, lp.actions_failed, lp.actions_skipped
        FROM link_plans lp
        WHERE lp.device_id = ?
          AND EXISTS (
                SELECT 1 FROM link_actions la
                WHERE la.plan_id = lp.id
                  AND (
                       la.canonical_path = ? OR la.canonical_path LIKE ?
                    OR la.duplicate_path = ? OR la.duplicate_path LIKE ?
                  )
          )
          AND (lp.notes LIKE ? OR lp.metadata LIKE ?)
        ORDER BY lp.created_at DESC
        LIMIT 1
        """,
        (device_id, rel_root_str, pattern, rel_root_str, pattern, marker, marker),
    ).fetchone()


def _payload_counts(conn: sqlite3.Connection, root: Path, device_id: int) -> tuple[int, int]:
    rows = conn.execute(
        "SELECT root_path, status FROM payloads WHERE device_id = ?",
        (device_id,),
    ).fetchall()
    total = 0
    complete = 0
    for root_path, status in rows:
        try:
            payload_root = Path(root_path)
        except Exception:
            continue
        if payload_root == root or is_under(payload_root, root):
            total += 1
            if status == "complete":
                complete += 1
    return total, complete


def _print_item(label: str, done: bool, detail: str, explain: str) -> None:
    status = "[x]" if done else "[ ]"
    print(f"{status} {label:<22} {detail:<52} {explain}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Workflow status for a path.")
    parser.add_argument("path", help="Root path to check")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    args = parser.parse_args()

    root_input = Path(args.path)
    root_resolved = root_input.resolve()
    root_canonical = canonicalize_path(root_resolved)

    conn = connect_db(Path(args.db))
    try:
        device_id, device_alias, current_mount, preferred_mount = _resolve_device(conn, root_canonical)
        mount_source = get_mount_source(str(root_canonical)) or ""
        canonical_root = _canonicalize_root(
            root_canonical, current_mount, preferred_mount, allow_remap=bool(mount_source)
        )
        rel_root, effective_mount = _rel_root(canonical_root, current_mount, preferred_mount)
        rel_root_str = str(rel_root)
        fs_uuid = get_filesystem_uuid(str(root_canonical))

        print(f"Workflow status for: {root_input}")
        print(f"  Resolved: {root_resolved}")
        print(f"  Canonical: {canonical_root}")
        print(f"  Device: {device_alias} ({device_id})")
        print(f"  Effective mount: {effective_mount}")
        print(f"  Relative root: {rel_root_str}")
        print("")

        scan_row = conn.execute(
            "SELECT last_scanned_at, scan_count FROM scan_roots WHERE fs_uuid = ? AND root_path = ?",
            (fs_uuid, str(canonical_root)),
        ).fetchone()
        if scan_row:
            _print_item("scan", True, f"last={scan_row[0]} scans={scan_row[1]}", "record all files under the root")
        else:
            _print_item("scan", False, f"make scan PATH={root_input}", "record all files under the root")

        plan_row = _find_recent_plan(conn, device_id, rel_root_str)
        if plan_row:
            plan_id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped = plan_row
            _print_item(
                "link plan",
                True,
                f"plan #{plan_id} ({status}) actions={actions_total} created={created_at}",
                "decide which duplicates should hardlink",
            )
            _print_item(
                "link execute",
                status == "completed",
                f"hashall link execute {plan_id}",
                "apply the plan (or dry-run first)",
            )
        else:
            _print_item(
                "link plan",
                False,
                f"hashall link plan \"dedupe {root_input}\" --device {device_alias}",
                "decide which duplicates should hardlink",
            )
            _print_item("link execute", False, "no plan", "apply the plan (or dry-run first)")

        total_payloads, complete_payloads = _payload_counts(conn, canonical_root, device_id)
        if complete_payloads > 0:
            _print_item(
                "payload sync",
                True,
                f"complete={complete_payloads} total={total_payloads}",
                "map torrents to payloads",
            )
        else:
            _print_item(
                "payload sync",
                False,
                "hashall payload sync ...",
                "map torrents to payloads",
            )

        empty_plan_row = _find_recent_empty_plan(conn, device_id, rel_root_str)
        if empty_plan_row:
            plan_id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped = empty_plan_row
            _print_item(
                "empty payload plan",
                True,
                f"plan #{plan_id} ({status}) actions={actions_total} created={created_at}",
                "plan empty-file hardlinks inside payloads",
            )
            _print_item(
                "empty payload execute",
                status == "completed",
                f"hashall link execute {plan_id}",
                "apply empty-file hardlinks",
            )
        else:
            _print_item(
                "empty payload plan",
                False,
                f"hashall link plan-payload-empty \"empty payload {root_input}\" --device {device_alias}",
                "plan empty-file hardlinks inside payloads",
            )
            _print_item("empty payload execute", False, "no plan", "apply empty-file hardlinks")

        _print_item("rehome", False, "hashall payload rehome ...", "move payloads to preferred root")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
