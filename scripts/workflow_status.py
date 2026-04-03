#!/usr/bin/env python3
"""Report workflow status for a path (scan, link, payload, empty-link)."""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
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
            SELECT id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped, metadata
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
               lp.actions_total, lp.actions_executed, lp.actions_failed, lp.actions_skipped,
               lp.metadata
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

def _payload_root_counts(conn: sqlite3.Connection, root: Path) -> tuple[int, int]:
    rows = conn.execute("SELECT root_path, status FROM payloads").fetchall()
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


def _colorize(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _status_color(status: str, done: bool) -> str:
    lowered = status.lower()
    if "failed" in lowered or "error" in lowered:
        return "31"
    if "no plan" in lowered or "missing" in lowered:
        return "31"
    return "32" if done else "33"


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _q(value: str) -> str:
    return f"\"{value}\""


def _hashall_cli() -> str:
    return f"{sys.executable} -m hashall.cli"


def _rehome_cli() -> str:
    return f"{sys.executable} -m rehome.cli"


def _scan_cli(root_input: Path, db: str) -> str:
    hash_mode = _env_value("HASH_MODE", "fast")
    parallel = _env_value("PARALLEL", "1")
    workers = os.getenv("WORKERS", "")
    show_path = _env_value("SHOW_PATH", "1")
    scan_nested = _env_value("SCAN_NESTED_DATASETS", "0")
    parts = [
        _hashall_cli(),
        "scan",
        _q(str(root_input)),
        "--db",
        _q(db),
        "--hash-mode",
        _q(hash_mode),
    ]
    if parallel == "1":
        parts.append("--parallel")
    if workers:
        parts.extend(["--workers", str(workers)])
    if show_path == "1":
        parts.append("--show-path")
    if scan_nested == "1":
        parts.append("--scan-nested-datasets")
    return " ".join(parts)


def _link_plan_cli(root_input: Path, device_alias: str, db: str) -> str:
    upgrade = _env_value("LINK_UPGRADE_COLLISIONS", "1")
    min_size = _env_value("LINK_MIN_SIZE", "0")
    dry_run = _env_value("LINK_DRY_RUN", "0")
    parts = [
        _hashall_cli(),
        "link",
        "plan",
        _q(f"dedupe {root_input}"),
        "--device",
        _q(device_alias),
        "--db",
        _q(db),
    ]
    if upgrade != "1":
        parts.append("--no-upgrade-collisions")
    if min_size not in ("", "0"):
        parts.extend(["--min-size", str(min_size)])
    if dry_run == "1":
        parts.append("--dry-run")
    return " ".join(parts)


def _link_verify_cli(root_input: Path, db: str, plan_id: int | None) -> str:
    parts = [
        _hashall_cli(),
        "link",
        "verify-scope",
        _q(str(root_input)),
    ]
    if plan_id is not None:
        parts.extend(["--plan-id", str(plan_id)])
    parts.extend(["--db", _q(db)])
    return " ".join(parts)


def _link_execute_cli(db: str, plan_id: int | None) -> str:
    if plan_id is None:
        return "no plan"
    dry_run = _env_value("LINK_DRY_RUN", "0")
    limit = _env_value("LINK_LIMIT", "0")
    low_priority = _env_value("LINK_LOW_PRIORITY", "1")
    fix_perms = _env_value("LINK_FIX_PERMS", "1")
    fix_acl = _env_value("LINK_FIX_ACL", "0")
    fix_log = os.getenv("LINK_FIX_PERMS_LOG", "")
    parts = [
        _hashall_cli(),
        "link",
        "execute",
        str(plan_id),
    ]
    if dry_run == "1":
        parts.append("--dry-run")
    if limit not in ("", "0"):
        parts.extend(["--limit", str(limit)])
    if low_priority == "1":
        parts.append("--low-priority")
    if fix_perms == "1":
        parts.append("--fix-perms")
    else:
        parts.append("--no-fix-perms")
    if fix_acl == "1":
        parts.append("--fix-acl")
    if fix_log:
        parts.extend(["--fix-perms-log", _q(fix_log)])
    parts.extend(["--db", _q(db)])
    return " ".join(parts)


def _payload_sync_cli(db: str) -> str:
    return " ".join([_hashall_cli(), "payload", "sync", "--db", _q(db)])

def _payload_sync_cli_for_root(db: str, root_input: Path) -> str:
    category = os.getenv("PAYLOAD_CATEGORY", "")
    tag = os.getenv("PAYLOAD_TAG", "")
    limit = os.getenv("PAYLOAD_LIMIT", "0")
    dry_run = os.getenv("PAYLOAD_DRY_RUN", "0")
    upgrade_missing = os.getenv("PAYLOAD_UPGRADE_MISSING", "0")
    parts = [
        _hashall_cli(),
        "payload",
        "sync",
        "--db",
        _q(db),
        "--path-prefix",
        _q(str(root_input)),
    ]
    if category:
        parts.extend(["--category", _q(category)])
    if tag:
        parts.extend(["--tag", _q(tag)])
    if limit not in ("", "0"):
        parts.extend(["--limit", str(limit)])
    if dry_run == "1":
        parts.append("--dry-run")
    if upgrade_missing == "1":
        parts.append("--upgrade-missing")
    return " ".join(parts)


def _payload_collisions_cli(root_input: Path, db: str) -> str:
    limit = os.getenv("PAYLOAD_LIMIT", "0")
    parts = [
        _hashall_cli(),
        "payload",
        "collisions",
        "--db",
        _q(db),
        "--path-prefix",
        _q(str(root_input)),
    ]
    if limit not in ("", "0"):
        parts.extend(["--limit", str(limit)])
    return " ".join(parts)


def _payload_upgrade_collisions_cli(root_input: Path, db: str) -> str:
    dry_run = os.getenv("PAYLOAD_DRY_RUN", "0")
    max_groups = os.getenv("PAYLOAD_MAX_GROUPS", "0")
    parts = [
        _hashall_cli(),
        "payload",
        "upgrade-collisions",
        "--db",
        _q(db),
        "--path-prefix",
        _q(str(root_input)),
    ]
    if max_groups not in ("", "0"):
        parts.extend(["--max-groups", str(max_groups)])
    if dry_run == "1":
        parts.append("--dry-run")
    return " ".join(parts)


def _payload_empty_cli(root_input: Path, device_alias: str, db: str) -> str:
    dry_run = _env_value("LINK_DRY_RUN", "0")
    require_hardlinks = _env_value("LINK_REQUIRE_EXISTING_HARDLINKS", "1")
    parts = [
        _hashall_cli(),
        "link",
        "plan-payload-empty",
        _q(f"empty payload {root_input}"),
        "--device",
        _q(device_alias),
        "--db",
        _q(db),
    ]
    if dry_run == "1":
        parts.append("--dry-run")
    if require_hardlinks != "1":
        parts.append("--no-require-existing-hardlinks")
    return " ".join(parts)

def _payload_sync_stats(conn: sqlite3.Connection, root: Path) -> tuple[int, int, int]:
    """
    Return (instances, unique_payloads, complete_payloads) under root.
    """
    rows = conn.execute(
        """
        SELECT p.root_path, p.status
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        """
    ).fetchall()
    instances = 0
    payloads = set()
    complete = set()
    for root_path, status in rows:
        try:
            payload_root = Path(root_path)
        except Exception:
            continue
        if payload_root == root or is_under(payload_root, root):
            instances += 1
            payloads.add(root_path)
            if status == "complete":
                complete.add(root_path)
    return instances, len(payloads), len(complete)


def _print_block(
    label: str,
    done: bool,
    status: str,
    make_cmd: str,
    cli_cmd: str,
    explain: str,
) -> None:
    color_enabled = sys.stdout.isatty() and not os.getenv("NO_COLOR")
    sep = "-" * 70
    checkbox = "[x]" if done else "[ ]"
    checkbox = _colorize(checkbox, "32" if done else "33", color_enabled)
    label_text = _colorize(label, "36", color_enabled)
    status_text = _colorize(status, _status_color(status, done), color_enabled)
    prefix = _colorize("make:", "2", color_enabled)
    cprefix = _colorize("cli:", "2", color_enabled)
    wprefix = _colorize("what:", "2", color_enabled)
    print(sep)
    print(f"{checkbox} | {label_text} | {status_text}")
    print(f"{prefix} {make_cmd}")
    print(f"{cprefix} {cli_cmd}")
    print(f"{wprefix} {explain}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Workflow status for a path.")
    parser.add_argument("path", help="Root path to check")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--auto-verify-scope", action="store_true", help="Run scope verification and update plan metadata")
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
            scan_status = f"last={scan_row[0]} scans={scan_row[1]}"
            scan_done = True
        else:
            scan_status = "missing"
            scan_done = False
        _print_block(
            "scan",
            scan_done,
            scan_status,
            f"make scan PATH={root_input}",
            _scan_cli(root_input, args.db),
            "record all files under the root",
        )

        plan_row = _find_recent_plan(conn, device_id, rel_root_str)
        if plan_row:
            plan_id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped, metadata = plan_row
            if args.auto_verify_scope:
                cmd = [
                    sys.executable,
                    "-m",
                    "hashall.cli",
                    "link",
                    "verify-scope",
                    str(root_input),
                    "--plan-id",
                    str(plan_id),
                    "--db",
                    args.db,
                    "--max-examples",
                    "0",
                ]
                subprocess.run(cmd, check=False)
                # Refresh metadata
                plan_row = _find_recent_plan(conn, device_id, rel_root_str)
                if plan_row:
                    plan_id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped, metadata = plan_row
            _print_block(
                "link plan",
                True,
                f"plan #{plan_id} ({status}) actions={actions_total} created={created_at}",
                f"make link-path PATH={root_input}",
                _link_plan_cli(root_input, device_alias, args.db),
                "decide which duplicates should hardlink",
            )
            scope_done = False
            if metadata:
                import json
                try:
                    meta = json.loads(metadata)
                    scope_done = (
                        meta.get("scope_status") == "ok"
                        and meta.get("scope_root") == str(canonical_root)
                    )
                except json.JSONDecodeError:
                    scope_done = False
            _print_block(
                "scope check",
                scope_done,
                f"plan #{plan_id} scope",
                f"make link-verify-scope PATH={root_input} PLAN_ID={plan_id}",
                _link_verify_cli(root_input, args.db, plan_id),
                "confirm plan paths are under root",
            )
            _print_block(
                "link exec",
                status == "completed",
                f"plan #{plan_id} ({status})",
                f"make link-execute PLAN_ID={plan_id}",
                _link_execute_cli(args.db, plan_id),
                "apply the plan (or dry-run first)",
            )
        else:
            _print_block(
                "link plan",
                False,
                "no plan",
                f"make link-path PATH={root_input}",
                _link_plan_cli(root_input, device_alias, args.db),
                "decide which duplicates should hardlink",
            )
            _print_block(
                "scope check",
                False,
                "no plan",
                f"make link-verify-scope PATH={root_input}",
                _link_verify_cli(root_input, args.db, None),
                "confirm plan paths are under root",
            )
            _print_block(
                "link exec",
                False,
                "no plan",
                "make link-execute PLAN_ID=<id>",
                _link_execute_cli(args.db, None),
                "apply the plan (or dry-run first)",
            )

        total_payloads, complete_payloads = _payload_root_counts(conn, canonical_root)
        instances, synced_payloads, synced_complete = _payload_sync_stats(conn, canonical_root)
        if instances > 0:
            payload_status = f"instances={instances} payloads={synced_payloads} complete={synced_complete}"
            payload_done = True
        else:
            payload_status = "not synced"
            payload_done = False
        _print_block(
            "payload sync",
            payload_done,
            payload_status,
            f"make payload-sync PAYLOAD_PATH_PREFIXES={root_input}",
            _payload_sync_cli_for_root(args.db, root_input),
            "sync torrents under this root to payloads",
        )

        _print_block(
            "payload coll",
            False,
            f"payloads={total_payloads} complete={complete_payloads}",
            f"make payload-collisions PATH={root_input}",
            _payload_collisions_cli(root_input, args.db),
            "find candidate duplicate payloads (fast signature)",
        )

        _print_block(
            "payload upg",
            False,
            "pending",
            f"make payload-upgrade-collisions PATH={root_input}",
            _payload_upgrade_collisions_cli(root_input, args.db),
            "hash missing SHA256 for colliding payloads; compute confirmed payload_hash",
        )

        empty_plan_row = _find_recent_empty_plan(conn, device_id, rel_root_str)
        if empty_plan_row:
            plan_id, name, status, created_at, actions_total, actions_executed, actions_failed, actions_skipped = empty_plan_row
            _print_block(
                "empty plan",
                True,
                f"plan #{plan_id} ({status}) actions={actions_total} created={created_at}",
                f"make link-payload-empty PATH={root_input}",
                _payload_empty_cli(root_input, device_alias, args.db),
                "plan empty-file hardlinks inside payloads",
            )
            _print_block(
                "empty exec",
                status == "completed",
                f"plan #{plan_id} ({status})",
                f"make link-execute PLAN_ID={plan_id}",
                _link_execute_cli(args.db, plan_id),
                "apply empty-file hardlinks",
            )
        else:
            _print_block(
                "empty plan",
                False,
                "no plan",
                f"make link-payload-empty PATH={root_input}",
                _payload_empty_cli(root_input, device_alias, args.db),
                "plan empty-file hardlinks inside payloads",
            )
            _print_block(
                "empty exec",
                False,
                "no plan",
                "make link-execute PLAN_ID=<id>",
                _link_execute_cli(args.db, None),
                "apply empty-file hardlinks",
            )

        _print_block(
            "rehome",
            False,
            "pending",
            "make rehome-plan ...",
            f"{_rehome_cli()} plan ...",
            "move payloads to preferred root",
        )

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
