"""Audit helpers for qBittorrent missingFiles root-drift cases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from hashall.bencode import as_text
from hashall.fastresume import normalize_save_path, read_fastresume
from hashall.qbittorrent import QBittorrentClient, QBitTorrent


def _map_root(path: str, source_root: str, target_root: str) -> str:
    normalized_path = normalize_save_path(path)
    normalized_source = normalize_save_path(source_root)
    normalized_target = normalize_save_path(target_root)
    if normalized_path == normalized_source:
        return normalized_target
    prefix = normalized_source + "/"
    if not normalized_path.startswith(prefix):
        return ""
    return normalized_target + normalized_path[len(normalized_source) :]


def _safe_exists(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:
        return False


def _read_fastresume_fields(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {
            "fastresume_exists": "false",
            "fastresume_save_path": "",
            "fastresume_qbt_save_path": "",
            "fastresume_qbt_download_path": "",
        }
    try:
        payload = read_fastresume(path)
        return {
            "fastresume_exists": "true",
            "fastresume_save_path": as_text(payload.get(b"save_path", b"")).strip(),
            "fastresume_qbt_save_path": as_text(payload.get(b"qBt-savePath", b"")).strip(),
            "fastresume_qbt_download_path": as_text(payload.get(b"qBt-downloadPath", b"")).strip(),
        }
    except Exception as exc:
        return {
            "fastresume_exists": "error",
            "fastresume_save_path": "",
            "fastresume_qbt_save_path": "",
            "fastresume_qbt_download_path": "",
            "fastresume_error": str(exc),
        }


def _latest_rehome_run(
    conn: Optional[sqlite3.Connection],
    torrent_hash: str,
) -> Dict[str, Any]:
    if conn is None:
        return {}
    row = conn.execute(
        """
        SELECT rr.id, rr.started_at, rr.finished_at, rr.direction, rr.decision, rr.status,
               rr.source_path, rr.target_path, rr.cleanup_source_required, rr.cleanup_source_path
        FROM rehome_runs rr
        WHERE rr.payload_hash = (
            SELECT p.payload_hash
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) = ?
            LIMIT 1
        )
        ORDER BY rr.id DESC
        LIMIT 1
        """,
        (str(torrent_hash or "").strip().lower(),),
    ).fetchone()
    if row is None:
        return {}
    keys = [
        "id",
        "started_at",
        "finished_at",
        "direction",
        "decision",
        "status",
        "source_path",
        "target_path",
        "cleanup_source_required",
        "cleanup_source_path",
    ]
    return {key: row[idx] for idx, key in enumerate(keys)}


def _classify_root_cause(
    torrent: QBitTorrent,
    *,
    source_root: str,
    mapped_content_path: str,
    qb_content_exists: bool,
    mapped_exists: bool,
    fastresume_fields: Dict[str, str],
    latest_run: Dict[str, Any],
) -> str:
    save_path = str(getattr(torrent, "save_path", "") or "").strip()
    fr_save = str(fastresume_fields.get("fastresume_save_path") or "").strip()
    fr_qsave = str(fastresume_fields.get("fastresume_qbt_save_path") or "").strip()
    old_root = normalize_save_path(source_root)
    old_root_prefix = old_root + "/"
    save_looks_old = save_path == old_root or save_path.startswith(old_root_prefix)
    fr_looks_old = (
        fr_save == old_root
        or fr_save.startswith(old_root_prefix)
        or fr_qsave == old_root
        or fr_qsave.startswith(old_root_prefix)
    )
    latest_reuse_success = (
        str(latest_run.get("decision") or "").upper() == "REUSE"
        and str(latest_run.get("status") or "").lower() == "success"
    )

    if (not qb_content_exists) and mapped_exists and save_looks_old and fr_looks_old and latest_reuse_success:
        return "root_drift_after_rehome_reuse"
    if (not qb_content_exists) and mapped_exists and save_looks_old and fr_looks_old:
        return "root_drift_fastresume_stale"
    if (not qb_content_exists) and mapped_exists:
        return "old_root_missing_mapped_target_exists"
    if qb_content_exists:
        return "qb_reports_missing_but_content_exists"
    if mapped_content_path:
        return "missing_payload_no_mapped_target"
    return "unclassified"


def audit_missing_root_drift(
    *,
    qb_client: QBittorrentClient,
    source_root: str,
    target_root: str,
    fastresume_dir: Path,
    catalog_path: Optional[Path] = None,
    state_filter: Iterable[str] = ("missingFiles",),
) -> Dict[str, Any]:
    conn: Optional[sqlite3.Connection] = None
    normalized_source = normalize_save_path(source_root)
    normalized_target = normalize_save_path(target_root)
    if catalog_path is not None and Path(catalog_path).exists():
        conn = sqlite3.connect(catalog_path)
        conn.row_factory = sqlite3.Row
    try:
        wanted = {str(state).strip().lower() for state in state_filter}
        rows = [
            row
            for row in (qb_client.get_torrents() or [])
            if str(getattr(row, "state", "") or "").strip().lower() in wanted
        ]
        report_rows: List[Dict[str, Any]] = []
        summary: Dict[str, int] = {
            "rows": 0,
            "qb_content_exists": 0,
            "mapped_target_exists": 0,
            "fastresume_old_save_path": 0,
            "fastresume_old_qbt_save_path": 0,
            "latest_rehome_reuse_success": 0,
        }
        cause_counts: Dict[str, int] = {}

        for torrent in rows:
            torrent_hash = str(getattr(torrent, "hash", "") or "").strip().lower()
            content_path = str(getattr(torrent, "content_path", "") or "").strip()
            mapped_content_path = (
                _map_root(content_path, normalized_source, normalized_target)
                if content_path
                else ""
            )
            qb_content_exists = _safe_exists(content_path)
            mapped_exists = _safe_exists(mapped_content_path)
            fastresume_fields = _read_fastresume_fields(fastresume_dir / f"{torrent_hash}.fastresume")
            latest_run = _latest_rehome_run(conn, torrent_hash)
            cause = _classify_root_cause(
                torrent,
                source_root=normalized_source,
                mapped_content_path=mapped_content_path,
                qb_content_exists=qb_content_exists,
                mapped_exists=mapped_exists,
                fastresume_fields=fastresume_fields,
                latest_run=latest_run,
            )
            row = {
                "hash": torrent_hash,
                "name": str(getattr(torrent, "name", "") or ""),
                "state": str(getattr(torrent, "state", "") or ""),
                "progress": float(getattr(torrent, "progress", 0.0) or 0.0),
                "save_path": str(getattr(torrent, "save_path", "") or ""),
                "content_path": content_path,
                "qb_content_exists": bool(qb_content_exists),
                "mapped_content_path": mapped_content_path,
                "mapped_target_exists": bool(mapped_exists),
                "root_cause": cause,
                "latest_rehome_run": latest_run,
            }
            row.update(fastresume_fields)
            report_rows.append(row)

            summary["rows"] += 1
            if qb_content_exists:
                summary["qb_content_exists"] += 1
            if mapped_exists:
                summary["mapped_target_exists"] += 1
            if str(fastresume_fields.get("fastresume_save_path") or "").startswith(normalized_source):
                summary["fastresume_old_save_path"] += 1
            if str(fastresume_fields.get("fastresume_qbt_save_path") or "").startswith(normalized_source):
                summary["fastresume_old_qbt_save_path"] += 1
            if (
                str(latest_run.get("decision") or "").upper() == "REUSE"
                and str(latest_run.get("status") or "").lower() == "success"
            ):
                summary["latest_rehome_reuse_success"] += 1
            cause_counts[cause] = cause_counts.get(cause, 0) + 1

        return {
            "source_root": normalized_source,
            "target_root": normalized_target,
            "summary": summary,
            "root_causes": cause_counts,
            "rows": report_rows,
        }
    finally:
        if conn is not None:
            conn.close()
