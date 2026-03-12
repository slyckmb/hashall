"""Audit helpers for qBittorrent missingFiles root-drift cases."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from hashall.bencode import as_text
from hashall.fastresume import normalize_save_path, read_fastresume
from hashall.qbittorrent import QBittorrentClient, QBitTorrent
from rehome.normalize import DEFAULT_UNIQUE_VIEW_SUBDIR


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1] or "")
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        if len(row) > 1
    }


def _canonical(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def ts_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def _safe_normalize_save_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return normalize_save_path(raw)
    except Exception:
        return raw


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


def _payload_context(
    conn: Optional[sqlite3.Connection],
    torrent_hash: str,
    *,
    source_root: str,
    qb_snapshot: Dict[str, QBitTorrent],
) -> Dict[str, Any]:
    if conn is None:
        return {"payload_hash": "", "sibling_targets": []}
    ti_columns = _table_columns(conn, "torrent_instances")
    save_path_expr = "ti.save_path" if "save_path" in ti_columns else "''"
    ti_device_expr = "ti.device_id" if "device_id" in ti_columns else "0"
    rows = conn.execute(
        f"""
        SELECT p.payload_hash,
               ti.torrent_hash,
               {save_path_expr} AS save_path,
               {ti_device_expr} AS ti_device_id,
               p.root_path,
               p.device_id AS payload_device_id,
               p.status
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE p.payload_hash = (
            SELECT p2.payload_hash
            FROM torrent_instances ti2
            JOIN payloads p2 ON p2.payload_id = ti2.payload_id
            WHERE lower(ti2.torrent_hash) = ?
            LIMIT 1
        )
        ORDER BY ti.torrent_hash
        """,
        (str(torrent_hash or "").strip().lower(),),
    ).fetchall()
    if not rows:
        return {"payload_hash": "", "sibling_targets": []}

    payload_hash = str(rows[0]["payload_hash"] or "")
    normalized_source = normalize_save_path(source_root)
    source_prefix = normalized_source + "/"
    sibling_targets: list[dict[str, Any]] = []
    for row in rows:
        row_hash = str(row["torrent_hash"] or "").strip().lower()
        if row_hash == str(torrent_hash or "").strip().lower():
            continue
        root_path = _safe_normalize_save_path(str(row["root_path"] or ""))
        save_path = _safe_normalize_save_path(str(row["save_path"] or ""))
        if root_path.startswith(source_prefix) or save_path.startswith(source_prefix):
            continue
        info = qb_snapshot.get(row_hash)
        if not save_path and info is not None:
            save_path = _safe_normalize_save_path(str(getattr(info, "save_path", "") or ""))
        progress = float(getattr(info, "progress", 0.0) or 0.0) if info is not None else 0.0
        state = str(getattr(info, "state", "") or "") if info is not None else ""
        healthy = progress >= 0.9999 and str(state).strip().lower() not in {"missingfiles", "stoppeddl", "error"}
        sibling_targets.append(
            {
                "torrent_hash": row_hash,
                "save_path": save_path,
                "root_path": str(row["root_path"] or ""),
                "ti_device_id": int(row["ti_device_id"] or 0),
                "payload_device_id": int(row["payload_device_id"] or 0),
                "status": str(row["status"] or ""),
                "qb_state": state,
                "qb_progress": progress,
                "healthy": healthy,
            }
        )
    return {"payload_hash": payload_hash, "sibling_targets": sibling_targets}


def _select_sibling_target(
    conn: sqlite3.Connection,
    *,
    payload_hash: str,
    target_root: str,
    sibling_targets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    normalized_target = normalize_save_path(target_root)
    candidates: List[Dict[str, Any]] = []
    for target in sibling_targets:
        if not bool(target.get("healthy")):
            continue
        root_path = _safe_normalize_save_path(str(target.get("root_path") or ""))
        if not root_path.startswith(normalized_target + "/"):
            continue
        row = conn.execute(
            """
            SELECT payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status
            FROM payloads
            WHERE payload_hash = ? AND root_path = ? AND status = 'complete'
            ORDER BY payload_id
            LIMIT 1
            """,
            (payload_hash, root_path),
        ).fetchone()
        if row is None:
            continue
        candidates.append(
            {
                "payload_id": int(row["payload_id"] or 0),
                "payload_hash": str(row["payload_hash"] or ""),
                "device_id": int(row["device_id"] or 0),
                "root_path": str(row["root_path"] or ""),
                "file_count": int(row["file_count"] or 0),
                "total_bytes": int(row["total_bytes"] or 0),
                "status": str(row["status"] or ""),
                "save_path": str(target.get("save_path") or ""),
                "torrent_hash": str(target.get("torrent_hash") or ""),
            }
        )
    if not candidates:
        return None

    def _sort_key(item: Dict[str, Any]) -> tuple[int, int, str]:
        root_path = str(item.get("root_path") or "")
        return (
            1 if "/_rehome-unique/" in root_path else 0,
            int(item.get("payload_id") or 0),
            root_path,
        )

    return sorted(candidates, key=_sort_key)[0]


def _fetch_stale_torrent_rows(
    conn: sqlite3.Connection,
    *,
    torrent_hashes: Iterable[str],
) -> List[sqlite3.Row]:
    wanted = [str(torrent_hash or "").strip().lower() for torrent_hash in torrent_hashes if str(torrent_hash or "").strip()]
    if not wanted:
        return []
    placeholders = ",".join(["?"] * len(wanted))
    return conn.execute(
        f"""
        SELECT ti.torrent_hash,
               ti.payload_id,
               ti.device_id AS ti_device_id,
               ti.save_path,
               ti.root_name,
               p.payload_hash,
               p.device_id AS payload_device_id,
               p.root_path,
               p.file_count,
               p.total_bytes,
               p.status
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE lower(ti.torrent_hash) IN ({placeholders})
        ORDER BY ti.torrent_hash
        """,
        tuple(wanted),
    ).fetchall()


def _build_missing_view_targets(
    *,
    stale_rows: List[sqlite3.Row],
    source_root: str,
    target_root: str,
    unique_view_subdir: str,
) -> tuple[List[str], List[Dict[str, str]], int, int]:
    normalized_source = normalize_save_path(source_root)
    normalized_target = normalize_save_path(target_root)
    seen_view_keys: set[tuple[str, str]] = set()
    affected_torrents: List[str] = []
    view_targets: List[Dict[str, str]] = []
    collisions = 0
    unique_views = 0

    for row in stale_rows:
        torrent_hash = str(row["torrent_hash"] or "").strip().lower()
        save_path = str(row["save_path"] or "").strip()
        root_name = str(row["root_name"] or "").strip()
        if not torrent_hash or not save_path:
            continue
        target_save_path = _map_root(save_path, normalized_source, normalized_target)
        if not target_save_path:
            continue
        affected_torrents.append(torrent_hash)
        if not root_name:
            continue
        view_key = (target_save_path, root_name)
        if view_key in seen_view_keys:
            collisions += 1
            target_save_path = str(
                _canonical(Path(normalized_target) / unique_view_subdir / torrent_hash)
            )
            unique_views += 1
            view_key = (target_save_path, root_name)
        seen_view_keys.add(view_key)
        view_targets.append(
            {
                "torrent_hash": torrent_hash,
                "source_save_path": save_path,
                "target_save_path": target_save_path,
                "root_name": root_name,
            }
        )

    return affected_torrents, view_targets, collisions, unique_views


def build_missing_sibling_reconnect_batch(
    *,
    qb_client: QBittorrentClient,
    source_root: str,
    target_root: str,
    fastresume_dir: Path,
    catalog_path: Path,
    torrent_hashes: Optional[Iterable[str]] = None,
    limit: int = 0,
    unique_view_subdir: str = DEFAULT_UNIQUE_VIEW_SUBDIR,
) -> Dict[str, Any]:
    audit = audit_missing_root_drift(
        qb_client=qb_client,
        source_root=source_root,
        target_root=target_root,
        fastresume_dir=fastresume_dir,
        catalog_path=catalog_path,
        state_filter=("missingFiles",),
    )
    requested = {
        str(torrent_hash or "").strip().lower()
        for torrent_hash in (torrent_hashes or [])
        if str(torrent_hash or "").strip()
    }
    reconnect_root_causes = {
        "root_drift_to_surviving_sibling_target",
        "root_drift_fastresume_stale",
    }
    rows = [
        row
        for row in (audit.get("rows") or [])
        if str(row.get("root_cause") or "") in reconnect_root_causes
        and bool(row.get("sibling_targets"))
        and (not requested or str(row.get("hash") or "").strip().lower() in requested)
    ]

    catalog_uri = f"file:{quote(str(Path(catalog_path).expanduser().resolve()), safe='/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(catalog_uri, uri=True)
    conn.row_factory = sqlite3.Row
    plans: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    try:
        rows_by_payload: dict[str, list[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            rows_by_payload[str(row.get("payload_hash") or "")].append(row)

        for payload_hash, payload_rows in rows_by_payload.items():
            if not payload_hash:
                continue
            donor = _select_sibling_target(
                conn,
                payload_hash=payload_hash,
                target_root=target_root,
                sibling_targets=[
                    sibling
                    for row in payload_rows
                    for sibling in (row.get("sibling_targets") or [])
                ],
            )
            if donor is None:
                skipped.append(
                    {
                        "payload_hash": payload_hash,
                        "reason": "no_surviving_target_payload",
                        "torrent_hashes": [str(row.get("hash") or "") for row in payload_rows],
                    }
                )
                continue

            stale_rows = _fetch_stale_torrent_rows(
                conn,
                torrent_hashes=[str(row.get("hash") or "") for row in payload_rows],
            )
            affected_torrents, view_targets, collisions, unique_views = _build_missing_view_targets(
                stale_rows=stale_rows,
                source_root=source_root,
                target_root=target_root,
                unique_view_subdir=unique_view_subdir,
            )
            if not affected_torrents or not view_targets:
                skipped.append(
                    {
                        "payload_hash": payload_hash,
                        "reason": "no_reconnect_view_targets",
                        "torrent_hashes": [str(row.get("hash") or "") for row in payload_rows],
                    }
                )
                continue

            source_rows = [
                {
                    "payload_id": int(row["payload_id"] or 0),
                    "device_id": int(row["payload_device_id"] or 0),
                    "root_path": str(row["root_path"] or ""),
                    "file_count": int(row["file_count"] or 0),
                    "total_bytes": int(row["total_bytes"] or 0),
                    "status": str(row["status"] or ""),
                }
                for row in stale_rows
            ]
            payload_group = sorted(
                source_rows
                + [
                    {
                        "payload_id": int(donor["payload_id"] or 0),
                        "device_id": int(donor["device_id"] or 0),
                        "root_path": str(donor["root_path"] or ""),
                        "file_count": int(donor["file_count"] or 0),
                        "total_bytes": int(donor["total_bytes"] or 0),
                        "status": str(donor["status"] or ""),
                    }
                ],
                key=lambda item: (int(item.get("device_id") or 0), int(item.get("payload_id") or 0)),
            )
            unique_payload_group: List[Dict[str, Any]] = []
            seen_payload_ids: set[int] = set()
            for item in payload_group:
                payload_id = int(item.get("payload_id") or 0)
                if payload_id in seen_payload_ids:
                    continue
                seen_payload_ids.add(payload_id)
                unique_payload_group.append(item)

            primary_source = min(source_rows, key=lambda item: int(item.get("payload_id") or 0))
            plans.append(
                {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "REUSE",
                    "torrent_hash": affected_torrents[0],
                    "payload_id": int(primary_source["payload_id"] or 0),
                    "payload_hash": payload_hash,
                    "reasons": [
                        "Reconnect stale missingFiles siblings to surviving target payload without copy"
                    ],
                    "affected_torrents": affected_torrents,
                    "source_path": str(primary_source["root_path"] or ""),
                    "target_path": str(donor["root_path"] or ""),
                    "source_device_id": int(primary_source["device_id"] or 0),
                    "target_device_id": int(donor["device_id"] or 0),
                    "seeding_roots": [
                        normalize_save_path(source_root),
                        normalize_save_path(target_root),
                    ],
                    "library_roots": [],
                    "view_targets": view_targets,
                    "payload_group": unique_payload_group,
                    "file_count": int(donor["file_count"] or 0),
                    "total_bytes": int(donor["total_bytes"] or 0),
                    "normalization": {
                        "mode": "qb_missing_sibling_reconnect",
                        "source_root": normalize_save_path(source_root),
                        "target_root": normalize_save_path(target_root),
                        "view_collisions": int(collisions),
                        "unique_view_targets": int(unique_views),
                        "unique_view_subdir": str(unique_view_subdir),
                        "donor_torrent_hash": str(donor["torrent_hash"] or ""),
                        "donor_root_path": str(donor["root_path"] or ""),
                        "audit_root_cause": "root_drift_to_surviving_sibling_target",
                        "missing_hashes": [str(row.get("hash") or "") for row in payload_rows],
                    },
                }
            )
            if limit > 0 and len(plans) >= limit:
                break
    finally:
        conn.close()

    return {
        "version": "1.0",
        "generated_at": ts_iso(),
        "mode": "qb_missing_sibling_reconnect",
        "source_root": normalize_save_path(source_root),
        "target_root": normalize_save_path(target_root),
        "summary": {
            "rows": len(rows),
            "plans": len(plans),
            "skipped": len(skipped),
            "decision_reuse": len(plans),
            "decision_move": 0,
            "view_collisions": sum(
                int((plan.get("normalization") or {}).get("view_collisions") or 0)
                for plan in plans
            ),
            "unique_view_targets": sum(
                int((plan.get("normalization") or {}).get("unique_view_targets") or 0)
                for plan in plans
            ),
        },
        "audit": {
            "rows": int((audit.get("summary") or {}).get("rows") or 0),
            "root_causes": dict(audit.get("root_causes") or {}),
        },
        "plans": plans,
        "skipped": skipped,
    }


def _classify_root_cause(
    torrent: QBitTorrent,
    *,
    source_root: str,
    mapped_content_path: str,
    qb_content_exists: bool,
    mapped_exists: bool,
    fastresume_fields: Dict[str, str],
    latest_run: Dict[str, Any],
    sibling_targets: List[Dict[str, Any]],
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
    healthy_sibling_target_exists = any(bool(row.get("healthy")) for row in sibling_targets)

    if (not qb_content_exists) and mapped_exists and save_looks_old and fr_looks_old and latest_reuse_success:
        return "root_drift_after_rehome_reuse"
    if (not qb_content_exists) and (not mapped_exists) and save_looks_old and fr_looks_old and healthy_sibling_target_exists:
        return "root_drift_to_surviving_sibling_target"
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
        all_rows = list(qb_client.get_torrents() or [])
        qb_snapshot = {
            str(getattr(row, "hash", "") or "").strip().lower(): row
            for row in all_rows
            if str(getattr(row, "hash", "") or "").strip()
        }
        rows = [
            row
            for row in all_rows
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
            payload_context = _payload_context(
                conn,
                torrent_hash,
                source_root=normalized_source,
                qb_snapshot=qb_snapshot,
            )
            cause = _classify_root_cause(
                torrent,
                source_root=normalized_source,
                mapped_content_path=mapped_content_path,
                qb_content_exists=qb_content_exists,
                mapped_exists=mapped_exists,
                fastresume_fields=fastresume_fields,
                latest_run=latest_run,
                sibling_targets=payload_context["sibling_targets"],
            )
            row = {
                "hash": torrent_hash,
                "payload_hash": str(payload_context["payload_hash"] or ""),
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
                "sibling_target_count": len(payload_context["sibling_targets"]),
                "sibling_targets": payload_context["sibling_targets"],
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
