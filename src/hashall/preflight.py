"""Catalog integrity preflight checks used by migration/repair workflows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List


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

        payload_missing_files_rows = conn.execute(
            """
            SELECT p.device_id, COUNT(*) AS rows
            FROM payloads p
            LEFT JOIN sqlite_master m
              ON m.type = 'table'
             AND m.name = ('files_' || p.device_id)
            WHERE p.device_id IS NOT NULL
              AND m.name IS NULL
            GROUP BY p.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        payload_missing_files_total = int(sum(int(r[1] or 0) for r in payload_missing_files_rows))
        checks.append(
            CheckResult(
                name="payload_device_files_table_present",
                ok=payload_missing_files_total == 0,
                severity="error",
                message=(
                    "all payload device_id values have files_<device_id> tables"
                    if payload_missing_files_total == 0
                    else (
                        "payload rows reference device_id values with no files_<device_id> "
                        f"table ({payload_missing_files_total} rows)"
                    )
                ),
                details={
                    "rows_without_files_table": payload_missing_files_total,
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

        torrent_missing_files_rows = conn.execute(
            """
            SELECT t.device_id, COUNT(*) AS rows
            FROM torrent_instances t
            LEFT JOIN sqlite_master m
              ON m.type = 'table'
             AND m.name = ('files_' || t.device_id)
            WHERE t.device_id IS NOT NULL
              AND m.name IS NULL
            GROUP BY t.device_id
            ORDER BY rows DESC
            """
        ).fetchall()
        torrent_missing_files_total = int(sum(int(r[1] or 0) for r in torrent_missing_files_rows))
        checks.append(
            CheckResult(
                name="torrent_device_files_table_present",
                ok=torrent_missing_files_total == 0,
                severity="error",
                message=(
                    "all torrent_instances device_id values have files_<device_id> tables"
                    if torrent_missing_files_total == 0
                    else (
                        "torrent_instances rows reference device_id values with no "
                        f"files_<device_id> table ({torrent_missing_files_total} rows)"
                    )
                ),
                details={
                    "rows_without_files_table": torrent_missing_files_total,
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
