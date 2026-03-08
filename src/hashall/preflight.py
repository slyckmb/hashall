"""Catalog integrity preflight checks used by migration/repair workflows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List

from hashall.device import get_files_table_name
from hashall.fs_utils import filesystem_uuid_is_stable


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    severity: str
    message: str
    details: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": bool(self.ok),
            "severity": str(self.severity),
            "message": str(self.message),
            "details": dict(self.details or {}),
        }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (str(table_name),),
    ).fetchone()
    return row is not None


def _relation_exists(conn: sqlite3.Connection, relation_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?",
        (str(relation_name),),
    ).fetchone()
    return row is not None


def _device_files_relation_exists(conn: sqlite3.Connection, device_id: int) -> bool:
    relation_name = get_files_table_name(conn.cursor(), device_id=int(device_id))
    if not relation_name:
        return False
    return _relation_exists(conn, relation_name)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.Error:
        return set()


def _grouped_counts(rows: List[sqlite3.Row], key_name: str = "device_id") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                key_name: int(row[0]) if row[0] is not None else None,
                "count": int(row[1] or 0),
            }
        )
    return out


def run_catalog_preflight(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Run structural integrity checks that must pass before apply-style tooling."""
    checks: List[CheckResult] = []

    has_devices = _table_exists(conn, "devices")
    has_payloads = _table_exists(conn, "payloads")
    has_torrents = _table_exists(conn, "torrent_instances")

    checks.append(
        CheckResult(
            name="devices_table_exists",
            ok=has_devices,
            severity="error",
            message="devices table is present" if has_devices else "devices table missing",
            details={},
        )
    )
    checks.append(
        CheckResult(
            name="payloads_table_exists",
            ok=has_payloads,
            severity="error",
            message="payloads table is present" if has_payloads else "payloads table missing",
            details={},
        )
    )
    checks.append(
        CheckResult(
            name="torrent_instances_table_exists",
            ok=has_torrents,
            severity="error",
            message="torrent_instances table is present"
            if has_torrents
            else "torrent_instances table missing",
            details={},
        )
    )

    if has_devices:
        device_columns = _table_columns(conn, "devices")
        device_count = int(conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] or 0)
        checks.append(
            CheckResult(
                name="devices_nonempty",
                ok=device_count > 0,
                severity="warning",
                message=f"devices rows={device_count}",
                details={"rows": device_count},
            )
        )

        if "fs_uuid" in device_columns:
            volatile_fs_uuid_rows = conn.execute(
                """
                SELECT device_id, COUNT(*) AS rows
                FROM devices
                WHERE fs_uuid IS NOT NULL AND trim(fs_uuid) <> ''
                GROUP BY device_id
                ORDER BY device_id
                """
            ).fetchall()
            volatile_fs_uuid_rows = [
                row for row in volatile_fs_uuid_rows
                if not filesystem_uuid_is_stable(
                    conn.execute(
                        "SELECT fs_uuid FROM devices WHERE device_id = ?",
                        (int(row[0]),),
                    ).fetchone()[0]
                )
            ]
            volatile_fs_uuid_total = int(sum(int(r[1] or 0) for r in volatile_fs_uuid_rows))
            checks.append(
                CheckResult(
                    name="device_fs_uuid_stable",
                    ok=volatile_fs_uuid_total == 0,
                    severity="error",
                    message=(
                        "all devices have stable fs_uuid values"
                        if volatile_fs_uuid_total == 0
                        else f"devices contain volatile dev-* fs_uuid fallbacks ({volatile_fs_uuid_total} rows)"
                    ),
                    details={
                        "volatile_rows": volatile_fs_uuid_total,
                        "by_device_id": _grouped_counts(list(volatile_fs_uuid_rows)),
                    },
                )
            )

    if has_devices and has_payloads:
        payload_unknown_rows = conn.execute(
            """
            SELECT p.device_id, COUNT(*) AS rows
            FROM payloads p
            WHERE p.device_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM devices d WHERE d.device_id = p.device_id
              )
            GROUP BY p.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        payload_unknown_total = int(sum(int(r[1] or 0) for r in payload_unknown_rows))
        checks.append(
            CheckResult(
                name="payload_device_refs_known",
                ok=payload_unknown_total == 0,
                severity="error",
                message=(
                    "all payload device_id references resolve to devices"
                    if payload_unknown_total == 0
                    else f"payload rows reference unknown device_id values ({payload_unknown_total} rows)"
                ),
                details={
                    "unknown_rows": payload_unknown_total,
                    "by_device_id": _grouped_counts(list(payload_unknown_rows)),
                },
            )
        )

        payload_device_rows = conn.execute(
            """
            SELECT p.device_id, COUNT(*) AS rows
            FROM payloads p
            WHERE p.device_id IS NOT NULL
            GROUP BY p.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        payload_missing_files_rows = [
            row for row in payload_device_rows if not _device_files_relation_exists(conn, int(row[0]))
        ]
        payload_missing_files_total = int(sum(int(r[1] or 0) for r in payload_missing_files_rows))
        checks.append(
            CheckResult(
                name="payload_device_files_table_present",
                ok=payload_missing_files_total == 0,
                severity="error",
                message=(
                    "all payload device_id values resolve to a files relation"
                    if payload_missing_files_total == 0
                    else (
                        "payload rows reference device_id values with no resolved files "
                        f"relation ({payload_missing_files_total} rows)"
                    )
                ),
                details={
                    "rows_without_files_relation": payload_missing_files_total,
                    "by_device_id": _grouped_counts(list(payload_missing_files_rows)),
                },
            )
        )

    if has_devices and has_torrents:
        torrent_unknown_rows = conn.execute(
            """
            SELECT t.device_id, COUNT(*) AS rows
            FROM torrent_instances t
            WHERE t.device_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM devices d WHERE d.device_id = t.device_id
              )
            GROUP BY t.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        torrent_unknown_total = int(sum(int(r[1] or 0) for r in torrent_unknown_rows))
        checks.append(
            CheckResult(
                name="torrent_device_refs_known",
                ok=torrent_unknown_total == 0,
                severity="error",
                message=(
                    "all torrent_instances device_id references resolve to devices"
                    if torrent_unknown_total == 0
                    else (
                        "torrent_instances rows reference unknown device_id values "
                        f"({torrent_unknown_total} rows)"
                    )
                ),
                details={
                    "unknown_rows": torrent_unknown_total,
                    "by_device_id": _grouped_counts(list(torrent_unknown_rows)),
                },
            )
        )

        torrent_device_rows = conn.execute(
            """
            SELECT t.device_id, COUNT(*) AS rows
            FROM torrent_instances t
            WHERE t.device_id IS NOT NULL
            GROUP BY t.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        torrent_missing_files_rows = [
            row for row in torrent_device_rows if not _device_files_relation_exists(conn, int(row[0]))
        ]
        torrent_missing_files_total = int(sum(int(r[1] or 0) for r in torrent_missing_files_rows))
        checks.append(
            CheckResult(
                name="torrent_device_files_table_present",
                ok=torrent_missing_files_total == 0,
                severity="error",
                message=(
                    "all torrent_instances device_id values resolve to a files relation"
                    if torrent_missing_files_total == 0
                    else (
                        "torrent_instances rows reference device_id values with no "
                        f"resolved files relation ({torrent_missing_files_total} rows)"
                    )
                ),
                details={
                    "rows_without_files_relation": torrent_missing_files_total,
                    "by_device_id": _grouped_counts(list(torrent_missing_files_rows)),
                },
            )
        )

    rendered = [c.as_dict() for c in checks]
    error_failures = [c for c in rendered if (not c["ok"]) and c["severity"] == "error"]
    warning_failures = [c for c in rendered if (not c["ok"]) and c["severity"] == "warning"]
    ok = len(error_failures) == 0
    return {
        "ok": bool(ok),
        "checks": rendered,
        "summary": {
            "total_checks": len(rendered),
            "failed_error": len(error_failures),
            "failed_warning": len(warning_failures),
        },
    }
