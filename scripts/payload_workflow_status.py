#!/usr/bin/env python3
"""Cross-device payload workflow status dashboard."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from hashall.model import connect_db

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
    """Auto-discover payload roots from the payloads table.

    Groups root_path values by their device's preferred_mount_point (or
    mount_point) to return unique top-level roots.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT p.root_path, d.preferred_mount_point, d.mount_point
        FROM payloads p
        LEFT JOIN devices d ON d.device_id = p.device_id
        """
    ).fetchall()
    mounts: set[str] = set()
    for root_path, preferred, current in rows:
        # Use preferred mount if available, else current mount, else the
        # root_path itself as a fallback.
        mount = preferred or current or root_path
        mounts.add(mount)
    return sorted(mounts)


# ---------------------------------------------------------------------------
# CLI builders
# ---------------------------------------------------------------------------


def _payload_sync_cli(db: str) -> str:
    return " ".join([_hashall_cli(), "payload", "sync", "--db", _q(db)])


def _payload_sync_cli_for_root(db: str, root: str) -> str:
    parts = [_hashall_cli(), "payload", "sync", "--db", _q(db),
             "--path-prefix", _q(root)]
    return " ".join(parts)


def _payload_collisions_cli(root: str, db: str) -> str:
    parts = [_hashall_cli(), "payload", "collisions", "--db", _q(db),
             "--path-prefix", _q(root)]
    return " ".join(parts)


def _payload_upgrade_collisions_cli(root: str, db: str) -> str:
    parts = [_hashall_cli(), "payload", "upgrade-collisions", "--db", _q(db),
             "--path-prefix", _q(root)]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------


def _payload_sync_status(conn: sqlite3.Connection, roots: list[str]) -> None:
    """Block 1: payload sync status per root."""
    # Per-device breakdown
    rows = conn.execute(
        "SELECT device_id, status, COUNT(*) FROM payloads GROUP BY device_id, status"
    ).fetchall()

    torrent_count = conn.execute(
        "SELECT COUNT(DISTINCT torrent_hash) FROM torrent_instances"
    ).fetchone()[0]

    # Aggregate per root
    per_root: dict[str, dict[str, int]] = {}
    all_rows = conn.execute(
        "SELECT root_path, status FROM payloads"
    ).fetchall()

    for root in roots:
        counts: dict[str, int] = {"total": 0, "complete": 0, "incomplete": 0}
        for root_path, status in all_rows:
            if root_path == root or root_path.startswith(root.rstrip("/") + "/"):
                counts["total"] += 1
                if status == "complete":
                    counts["complete"] += 1
                else:
                    counts["incomplete"] += 1
        per_root[root] = counts

    total_payloads = sum(c["total"] for c in per_root.values())
    total_complete = sum(c["complete"] for c in per_root.values())
    total_incomplete = total_payloads - total_complete
    synced = total_payloads > 0

    parts = [f"payloads={total_payloads}", f"complete={total_complete}",
             f"torrents={torrent_count}"]
    for root, counts in per_root.items():
        parts.append(f"{root}: {counts['complete']}/{counts['total']}")

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

    # Block 1b: incomplete payload resolution guidance
    if total_incomplete > 0:
        incomplete_parts = [f"incomplete={total_incomplete}"]
        for root, counts in per_root.items():
            if counts["incomplete"] > 0:
                incomplete_parts.append(f"{root}: {counts['incomplete']}")
        inc_status = " | ".join(incomplete_parts)

        if total_payloads == 0:
            upgrade_make = "make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1"
            upgrade_cli = _payload_sync_cli(args_db) + " --upgrade-missing --parallel"
        else:
            prefixes = " ".join(roots)
            upgrade_make = f"make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1 PAYLOAD_PATH_PREFIXES='{prefixes}'"
            upgrade_cli = _payload_sync_cli_for_root(args_db, roots[0]) + " --upgrade-missing --parallel"

        _print_block(
            "payload complete",
            False,
            inc_status,
            upgrade_make,
            upgrade_cli,
            "hash only the files missing SHA256 in incomplete payloads (inode-aware, targeted)",
        )


def _payload_collision_status(conn: sqlite3.Connection, roots: list[str]) -> None:
    """Block 2: payload collisions — confirmed + candidate dupes."""
    # Confirmed: payloads with non-null payload_hash that share the same hash
    confirmed = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT payload_hash
            FROM payloads
            WHERE payload_hash IS NOT NULL
            GROUP BY payload_hash
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    # Candidates: incomplete payloads that share the same (file_count, total_bytes)
    # as a rough fast-signature proxy — groups where at least one is incomplete
    candidates = conn.execute(
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

    done = confirmed > 0 and candidates == 0
    status_str = f"confirmed_groups={confirmed} candidate_groups={candidates}"

    root_cmds = [f"make payload-collisions PATH={r}" for r in roots]
    cli_cmds = [_payload_collisions_cli(r, args_db) for r in roots]

    _print_block(
        "payload collisions",
        done,
        status_str,
        root_cmds[0] if len(root_cmds) == 1 else " ; ".join(root_cmds),
        cli_cmds[0] if len(cli_cmds) == 1 else " ; ".join(cli_cmds),
        "find candidate duplicate payloads (fast signature)",
    )


def _payload_upgrade_status(conn: sqlite3.Connection, roots: list[str]) -> None:
    """Block 3: payload upgrade-collisions — SHA256 upgrade status."""
    # Collision groups where all members are complete (fully confirmed)
    fully_confirmed = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT payload_hash
            FROM payloads
            WHERE payload_hash IS NOT NULL
            GROUP BY payload_hash
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    # Groups with at least one incomplete member (need SHA256 upgrade)
    pending = conn.execute(
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

    # Payloads missing SHA256 that are in collision groups
    missing_sha256 = conn.execute(
        """
        SELECT COUNT(*) FROM payloads
        WHERE payload_hash IS NULL
          AND (file_count, total_bytes) IN (
              SELECT file_count, total_bytes
              FROM payloads
              GROUP BY file_count, total_bytes
              HAVING COUNT(*) > 1
          )
        """
    ).fetchone()[0]

    done = pending == 0 and missing_sha256 == 0
    status_str = (f"fully_confirmed={fully_confirmed} pending={pending} "
                  f"missing_sha256={missing_sha256}")

    root_cmds = [f"make payload-upgrade-collisions PATH={r}" for r in roots]
    cli_cmds = [_payload_upgrade_collisions_cli(r, args_db) for r in roots]

    _print_block(
        "payload upgrade",
        done,
        status_str,
        root_cmds[0] if len(root_cmds) == 1 else " ; ".join(root_cmds),
        cli_cmds[0] if len(cli_cmds) == 1 else " ; ".join(cli_cmds),
        "hash missing SHA256 for colliding payloads; compute confirmed payload_hash",
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
        print()

        _payload_sync_status(conn, roots)
        _payload_collision_status(conn, roots)
        _payload_upgrade_status(conn, roots)

        print("-" * 70)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
