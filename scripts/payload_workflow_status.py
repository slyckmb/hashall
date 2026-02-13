#!/usr/bin/env python3
"""Cross-device payload workflow status dashboard."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from hashall.model import connect_db
from hashall.payload_completion import load_completed_torrent_hashes

# ---------------------------------------------------------------------------
# Display helpers (shared style with workflow_status.py)
# ---------------------------------------------------------------------------


def _colorize(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _status_color(status: str, done: bool) -> str:
    lowered = status.lower()
    if "failed" in lowered or "error" in lowered or "missing" in lowered:
        return "31"
    return "32" if done else "33"


def _q(value: str) -> str:
    return f'"{value}"'


def _hashall_cli() -> str:
    return f"{sys.executable} -m hashall.cli"


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


# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------


def _discover_roots(conn: sqlite3.Connection) -> list[str]:
    """Auto-discover payload roots from the payloads table."""
    rows = conn.execute(
        """
        SELECT DISTINCT p.root_path, d.preferred_mount_point, d.mount_point
        FROM payloads p
        LEFT JOIN devices d ON d.device_id = p.device_id
        """
    ).fetchall()
    mounts: set[str] = set()
    for root_path, preferred, current in rows:
        mount = preferred or current or root_path
        mounts.add(mount)
    return sorted(mounts)


# ---------------------------------------------------------------------------
# CLI builders
# ---------------------------------------------------------------------------


def _payload_sync_cli(db: str) -> str:
    return " ".join([_hashall_cli(), "payload", "sync", "--db", _q(db)])


def _payload_sync_cli_for_root(db: str, root: str) -> str:
    parts = [_hashall_cli(), "payload", "sync", "--db", _q(db), "--path-prefix", _q(root)]
    return " ".join(parts)


def _payload_collisions_cli(root: str, db: str) -> str:
    parts = [_hashall_cli(), "payload", "collisions", "--db", _q(db), "--path-prefix", _q(root)]
    return " ".join(parts)


def _payload_upgrade_collisions_cli(root: str, db: str) -> str:
    parts = [_hashall_cli(), "payload", "upgrade-collisions", "--db", _q(db), "--path-prefix", _q(root)]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# State collection
# ---------------------------------------------------------------------------

def _in_scope(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _count_collision_groups(rows: list[dict[str, object]], *, in_scope_only: bool, require_refs: bool, completion_filter_active: bool) -> tuple[int, set[tuple[int, int]]]:
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

    keys = {k for k, g in groups.items() if g["count"] > 1 and g["incomplete_count"] > 0}
    return len(keys), keys


def _collect_status_context(
    conn: sqlite3.Connection,
    roots: list[str],
    *,
    completed_hashes: set[str] | None = None,
    completion_filter_active: bool | None = None,
    completion_filter_error: str | None = None,
) -> dict:
    if completion_filter_active is None:
        completed_hashes, completion_filter_active, completion_filter_error = load_completed_torrent_hashes()

    completed_hashes = {h.lower() for h in (completed_hashes or set())}

    payload_rows = conn.execute(
        "SELECT payload_id, root_path, status, file_count, total_bytes, payload_hash FROM payloads"
    ).fetchall()
    ref_rows = conn.execute("SELECT payload_id, torrent_hash FROM torrent_instances").fetchall()

    ref_count_by_payload: dict[int, int] = {}
    complete_ref_by_payload: dict[int, bool] = {}
    for payload_id, torrent_hash in ref_rows:
        pid = int(payload_id)
        ref_count_by_payload[pid] = ref_count_by_payload.get(pid, 0) + 1
        if completion_filter_active and torrent_hash and str(torrent_hash).lower() in completed_hashes:
            complete_ref_by_payload[pid] = True

    per_root: dict[str, dict[str, object]] = {
        root: {
            "total": 0,
            "complete": 0,
            "incomplete": 0,
            "needs_upgrade": 0,
            "dirty_actionable": 0,
            "dirty_noncomplete": 0,
            "dirty_orphan": 0,
            "first_actionable_path": None,
        }
        for root in roots
    }

    rows_for_collision: list[dict[str, object]] = []
    for payload_id, root_path, status, file_count, total_bytes, payload_hash in payload_rows:
        pid = int(payload_id)
        file_count = int(file_count)
        ref_count = int(ref_count_by_payload.get(pid, 0))
        has_complete_ref = bool(complete_ref_by_payload.get(pid, False))

        in_scope = False
        owner_root = None
        for root in roots:
            if _in_scope(root_path, root):
                in_scope = True
                owner_root = root
                break

        rows_for_collision.append(
            {
                "payload_id": pid,
                "root_path": root_path,
                "status": status,
                "file_count": file_count,
                "total_bytes": int(total_bytes),
                "payload_hash": payload_hash,
                "ref_count": ref_count,
                "has_complete_ref": has_complete_ref,
                "in_scope": in_scope,
            }
        )

        if not in_scope or owner_root is None:
            continue

        counts = per_root[owner_root]
        counts["total"] += 1
        if status == "complete":
            counts["complete"] += 1
        else:
            counts["incomplete"] += 1
            if file_count > 0:
                counts["needs_upgrade"] += 1

        if file_count == 0:
            if ref_count == 0:
                counts["dirty_orphan"] += 1
            elif completion_filter_active and not has_complete_ref:
                counts["dirty_noncomplete"] += 1
            else:
                counts["dirty_actionable"] += 1
                if counts["first_actionable_path"] is None:
                    counts["first_actionable_path"] = root_path

    collision_groups_in_scope, in_scope_collision_keys = _count_collision_groups(
        rows_for_collision,
        in_scope_only=True,
        require_refs=True,
        completion_filter_active=bool(completion_filter_active),
    )
    collision_groups_global, _ = _count_collision_groups(
        rows_for_collision,
        in_scope_only=False,
        require_refs=False,
        completion_filter_active=False,
    )

    missing_sha256_collision_in_scope = sum(
        1
        for row in rows_for_collision
        if bool(row["in_scope"])
        and row["payload_hash"] is None
        and (int(row["file_count"]), int(row["total_bytes"])) in in_scope_collision_keys
        and int(row["ref_count"]) > 0
        and (not completion_filter_active or bool(row["has_complete_ref"]))
    )

    hash_groups: dict[str, int] = {}
    for row in rows_for_collision:
        payload_hash = row["payload_hash"]
        if bool(row["in_scope"]) and payload_hash:
            key = str(payload_hash)
            hash_groups[key] = hash_groups.get(key, 0) + 1
    confirmed_groups_in_scope = sum(1 for c in hash_groups.values() if c > 1)

    totals = {
        "dirty_actionable": sum(int(v["dirty_actionable"]) for v in per_root.values()),
        "dirty_noncomplete": sum(int(v["dirty_noncomplete"]) for v in per_root.values()),
        "dirty_orphan": sum(int(v["dirty_orphan"]) for v in per_root.values()),
        "total_payloads": sum(int(v["total"]) for v in per_root.values()),
        "total_complete": sum(int(v["complete"]) for v in per_root.values()),
        "total_incomplete": sum(int(v["incomplete"]) for v in per_root.values()),
        "total_needs_upgrade": sum(int(v["needs_upgrade"]) for v in per_root.values()),
    }

    return {
        "per_root": per_root,
        "totals": totals,
        "completion_filter_active": bool(completion_filter_active),
        "completion_filter_error": completion_filter_error,
        "collision_groups_in_scope": collision_groups_in_scope,
        "collision_groups_global": collision_groups_global,
        "confirmed_groups_in_scope": confirmed_groups_in_scope,
        "missing_sha256_collision_in_scope": missing_sha256_collision_in_scope,
    }


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------


def _catalog_scan_status(conn: sqlite3.Connection, roots: list[str], ctx: dict) -> None:
    """Block 0: catalog scan — actionable payloads not yet in catalog."""
    per_root = {root: int(ctx["per_root"][root]["dirty_actionable"]) for root in roots}
    total_actionable = int(ctx["totals"]["dirty_actionable"])
    total_noncomplete = int(ctx["totals"]["dirty_noncomplete"])
    total_orphan = int(ctx["totals"]["dirty_orphan"])
    done = total_actionable == 0

    parts = [f"actionable_dirty={total_actionable}"]
    if total_noncomplete > 0:
        parts.append(f"ignored_noncomplete={total_noncomplete}")
    if total_orphan > 0:
        parts.append(f"orphan_dirty={total_orphan}")
    for root, count in per_root.items():
        if count > 0:
            parts.append(f"{root}: {count}")
    status_str = " | ".join(parts)

    target_root = max(roots, key=lambda r: per_root[r], default=roots[0])
    target_path = ctx["per_root"][target_root]["first_actionable_path"]
    if target_path and "/torrents/seeding/" in str(target_path):
        scan_path = target_root + "/torrents/seeding"
    else:
        scan_path = target_root

    make_cmd = f"make scan PATH={scan_path} HASH_MODE=full PARALLEL=1"
    cli_cmd = f"{_hashall_cli()} scan {_q(scan_path)} --hash-mode full --parallel"

    _print_block(
        "catalog scan",
        done,
        status_str,
        make_cmd,
        cli_cmd,
        "scan directories to add files to catalog (required before upgrade-missing)",
    )


def _payload_sync_status(conn: sqlite3.Connection, roots: list[str], ctx: dict) -> None:
    """Block 1: payload sync status per root."""
    torrent_count = conn.execute(
        "SELECT COUNT(DISTINCT torrent_hash) FROM torrent_instances"
    ).fetchone()[0]

    per_root = ctx["per_root"]
    total_payloads = int(ctx["totals"]["total_payloads"])
    total_complete = int(ctx["totals"]["total_complete"])
    total_needs_upgrade = int(ctx["totals"]["total_needs_upgrade"])
    actionable = int(ctx["totals"]["dirty_actionable"])
    ignored_noncomplete = int(ctx["totals"]["dirty_noncomplete"])
    orphan_dirty = int(ctx["totals"]["dirty_orphan"])
    synced = total_payloads > 0 and actionable == 0

    parts = [f"payloads={total_payloads}", f"complete={total_complete}", f"torrents={torrent_count}"]
    for root, counts in per_root.items():
        parts.append(f"{root}: {counts['complete']}/{counts['total']}")

    if actionable > 0:
        parts.append(f"⚠ {actionable} need scan first")
    if ignored_noncomplete > 0:
        parts.append(f"ignored_noncomplete={ignored_noncomplete}")
    if orphan_dirty > 0:
        parts.append(f"orphan_dirty={orphan_dirty}")

    status_str = " | ".join(parts)

    if total_payloads == 0:
        make_cmd = "make payload-sync"
        cli_cmd = _payload_sync_cli(args_db)
    else:
        prefixes = " ".join(roots)
        make_cmd = f"make payload-sync PAYLOAD_PATH_PREFIXES='{prefixes}'"
        cli_cmd = _payload_sync_cli_for_root(args_db, roots[0])

    _print_block(
        "payload sync",
        synced,
        status_str,
        make_cmd,
        cli_cmd,
        "sync torrents across all roots to payloads table",
    )

    if total_needs_upgrade > 0:
        upgrade_parts = [f"incomplete={total_needs_upgrade}"]
        for root, counts in per_root.items():
            if int(counts["needs_upgrade"]) > 0:
                upgrade_parts.append(f"{root}: {counts['needs_upgrade']}")
        inc_status = " | ".join(upgrade_parts)

        if total_payloads == 0:
            upgrade_make = "make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1"
            upgrade_cli = _payload_sync_cli(args_db) + " --upgrade-missing --parallel"
        else:
            prefixes = " ".join(roots)
            upgrade_make = (
                "make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1 "
                f"PAYLOAD_PATH_PREFIXES='{prefixes}'"
            )
            upgrade_cli = _payload_sync_cli_for_root(args_db, roots[0]) + " --upgrade-missing --parallel"

        _print_block(
            "payload complete",
            False,
            inc_status,
            upgrade_make,
            upgrade_cli,
            "hash only the files missing SHA256 in incomplete payloads (inode-aware, targeted)",
        )


def _payload_collision_status(conn: sqlite3.Connection, roots: list[str], ctx: dict) -> None:
    """Block 2: payload collisions — confirmed + candidate dupes."""
    confirmed = int(ctx["confirmed_groups_in_scope"])
    candidates = int(ctx["collision_groups_in_scope"])

    done = candidates == 0
    status_str = f"confirmed_groups={confirmed} candidate_groups={candidates}"

    root_cmds = [f"make payload-collisions PATH={r}" for r in roots]
    cli_cmds = [_payload_collisions_cli(r, args_db) for r in roots]

    _print_block(
        "payload collisions",
        done,
        status_str,
        root_cmds[0] if len(root_cmds) == 1 else " ; ".join(root_cmds),
        cli_cmds[0] if len(cli_cmds) == 1 else " ; ".join(cli_cmds),
        "find candidate duplicate payloads (fast signature, filtered for actionable refs)",
    )


def _payload_upgrade_status(conn: sqlite3.Connection, roots: list[str], ctx: dict) -> None:
    """Block 3: payload upgrade-collisions — SHA256 upgrade status."""
    fully_confirmed = int(ctx["confirmed_groups_in_scope"])
    pending = int(ctx["collision_groups_in_scope"])
    missing_sha256 = int(ctx["missing_sha256_collision_in_scope"])

    done = pending == 0 and missing_sha256 == 0
    status_str = f"fully_confirmed={fully_confirmed} pending={pending} missing_sha256={missing_sha256}"

    root_cmds = [f"make payload-upgrade-collisions PATH={r}" for r in roots]
    cli_cmds = [_payload_upgrade_collisions_cli(r, args_db) for r in roots]

    _print_block(
        "payload upgrade",
        done,
        status_str,
        root_cmds[0] if len(root_cmds) == 1 else " ; ".join(root_cmds),
        cli_cmds[0] if len(cli_cmds) == 1 else " ; ".join(cli_cmds),
        "hash missing SHA256 for actionable collision groups; compute confirmed payload_hash",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Module-level for access by status functions (set in main())
args_db: str = ""


def main() -> int:
    global args_db

    parser = argparse.ArgumentParser(
        description="Cross-device payload workflow status dashboard."
    )
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument(
        "paths", nargs="*",
        help="Payload roots to report on (auto-discovered from DB if omitted)",
    )
    args = parser.parse_args()
    args_db = args.db

    conn = connect_db(Path(args.db))
    try:
        if args.paths:
            roots = args.paths
        else:
            roots = _discover_roots(conn)

        if not roots:
            print("No payload roots found. Run 'make payload-sync' first.")
            return 0

        print("Payload workflow status")
        print(f"  Roots: {', '.join(roots)}")
        print(f"  DB: {args.db}")
        ctx = _collect_status_context(conn, roots)
        if ctx["completion_filter_active"]:
            print("  qB completion filter: active (ignoring refs below 100% progress)")
        elif ctx["completion_filter_error"]:
            print(f"  qB completion filter: disabled ({ctx['completion_filter_error']})")
        print()

        _catalog_scan_status(conn, roots, ctx)
        _payload_sync_status(conn, roots, ctx)
        _payload_collision_status(conn, roots, ctx)
        _payload_upgrade_status(conn, roots, ctx)

        print("-" * 70)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
