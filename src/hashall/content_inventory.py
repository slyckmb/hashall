from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from hashall.pathing import canonicalize_path


@dataclass(frozen=True)
class ContentRootSummary:
    root_path: str
    root_kind: str
    fs_uuid: Optional[str]
    device_id: Optional[int]
    file_count: int
    total_bytes: int
    files_with_sha256: int
    files_with_quick: int
    tree_hash: Optional[str]
    status: str


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({_quote_ident(table_name)})").fetchall()
    except Exception:
        return False
    return any(str(row[1]) == str(column_name) for row in rows)


def _kind_for_base(base_root: Path) -> str:
    parts = base_root.parts
    if "orphaned_data" in parts:
        return "orphan"
    if "RecycleBin" in parts:
        return "recovery"
    if "seeds" in parts:
        return "archive"
    return "other"


def _device_row_for_path(conn: sqlite3.Connection, path: Path) -> sqlite3.Row | None:
    path = canonicalize_path(path)
    rows = conn.execute(
        """
        SELECT device_id, fs_uuid, mount_point, preferred_mount_point, files_table
        FROM devices
        """
    ).fetchall()
    best = None
    best_len = -1
    for row in rows:
        for raw_mount in (row["preferred_mount_point"], row["mount_point"]):
            mount = str(raw_mount or "").strip()
            if not mount:
                continue
            mount_path = Path(mount)
            try:
                path.relative_to(mount_path)
            except Exception:
                continue
            score = len(str(mount_path))
            if score > best_len:
                best = row
                best_len = score
    return best


def _relpath_for_device(path: Path, mount_point: str | None, preferred_mount: str | None) -> str | None:
    path = canonicalize_path(path)
    for raw_mount in (preferred_mount, mount_point):
        mount = str(raw_mount or "").strip()
        if not mount:
            continue
        try:
            rel = path.relative_to(Path(mount))
            return rel.as_posix() if str(rel) != "." else "."
        except Exception:
            continue
    return None


def _iter_candidate_roots(
    conn: sqlite3.Connection,
    *,
    base_root: Path,
) -> Iterable[tuple[sqlite3.Row, str, str]]:
    device_row = _device_row_for_path(conn, base_root)
    if device_row is None:
        return []
    table_name = str(device_row["files_table"] or "").strip()
    if not table_name:
        return []
    rel_root = _relpath_for_device(
        base_root,
        device_row["mount_point"],
        device_row["preferred_mount_point"] or device_row["mount_point"],
    )
    if rel_root is None:
        return []
    table_ident = _quote_ident(table_name)
    status_clause = "status='active' AND " if _table_has_column(conn, table_name, "status") else ""
    if rel_root == ".":
        like_pattern = "%"
    else:
        like_pattern = rel_root.rstrip("/") + "/%"
    rows = conn.execute(
        f"SELECT path FROM {table_ident} WHERE {status_clause} path LIKE ? ORDER BY path",
        (like_pattern,),
    ).fetchall()
    seen: set[str] = set()
    out: list[tuple[sqlite3.Row, str, str]] = []
    base_text = str(base_root)
    prefix = rel_root.rstrip("/") + "/" if rel_root != "." else ""
    for row in rows:
        rel_path = str(row["path"] or "")
        remainder = rel_path[len(prefix):] if prefix and rel_path.startswith(prefix) else rel_path
        if not remainder:
            continue
        head, _, _tail = remainder.partition("/")
        candidate_rel = f"{prefix}{head}" if prefix else head
        if candidate_rel in seen:
            continue
        seen.add(candidate_rel)
        out.append((device_row, candidate_rel, str((base_root / head).resolve() if base_root.exists() else Path(base_text) / head)))
    return out


def _build_summary_for_rel_root(
    conn: sqlite3.Connection,
    *,
    device_row: sqlite3.Row,
    candidate_rel_root: str,
    candidate_abs_root: str,
    root_kind: str,
) -> ContentRootSummary:
    table_name = str(device_row["files_table"] or "").strip()
    table_ident = _quote_ident(table_name)
    status_clause = "status='active' AND " if _table_has_column(conn, table_name, "status") else ""
    pattern = candidate_rel_root.rstrip("/") + "/%"
    rows = conn.execute(
        f"""
        SELECT path, size, sha256, quick_hash
        FROM {table_ident}
        WHERE {status_clause} (path = ? OR path LIKE ?)
        ORDER BY path
        """,
        (candidate_rel_root, pattern),
    ).fetchall()
    file_count = len(rows)
    total_bytes = sum(int(row["size"] or 0) for row in rows)
    files_with_sha256 = sum(1 for row in rows if str(row["sha256"] or "").strip())
    files_with_quick = sum(1 for row in rows if str(row["quick_hash"] or "").strip())
    tree_hash = None
    if file_count > 0 and files_with_sha256 == file_count:
        hasher = hashlib.sha256()
        prefix = candidate_rel_root.rstrip("/") + "/"
        for row in rows:
            rel = str(row["path"] or "")
            if rel == candidate_rel_root:
                rel_inside = Path(rel).name
            elif rel.startswith(prefix):
                rel_inside = rel[len(prefix):]
            else:
                rel_inside = rel
            entry = f"{rel_inside}|{int(row['size'] or 0)}|{str(row['sha256'] or '').strip()}\n"
            hasher.update(entry.encode("utf-8"))
        tree_hash = hasher.hexdigest()
    status = "complete" if file_count > 0 and files_with_sha256 == file_count else "incomplete"
    return ContentRootSummary(
        root_path=str(candidate_abs_root),
        root_kind=root_kind,
        fs_uuid=str(device_row["fs_uuid"] or "").strip() or None,
        device_id=int(device_row["device_id"]) if device_row["device_id"] is not None else None,
        file_count=file_count,
        total_bytes=total_bytes,
        files_with_sha256=files_with_sha256,
        files_with_quick=files_with_quick,
        tree_hash=tree_hash,
        status=status,
    )


def discover_content_roots(conn: sqlite3.Connection, base_roots: Iterable[str]) -> list[ContentRootSummary]:
    results: list[ContentRootSummary] = []
    for raw_root in base_roots:
        base_root = canonicalize_path(Path(raw_root))
        root_kind = _kind_for_base(base_root)
        for device_row, rel_root, abs_root in _iter_candidate_roots(conn, base_root=base_root):
            results.append(
                _build_summary_for_rel_root(
                    conn,
                    device_row=device_row,
                    candidate_rel_root=rel_root,
                    candidate_abs_root=abs_root,
                    root_kind=root_kind,
                )
            )
    results.sort(key=lambda item: (item.root_kind, item.root_path))
    return results


def duplicate_content_roots(items: Iterable[ContentRootSummary]) -> list[list[ContentRootSummary]]:
    by_hash: dict[str, list[ContentRootSummary]] = {}
    for item in items:
        if item.tree_hash:
            by_hash.setdefault(item.tree_hash, []).append(item)
    groups = [sorted(group, key=lambda item: item.root_path) for group in by_hash.values() if len(group) > 1]
    groups.sort(key=lambda group: (-group[0].total_bytes, group[0].root_path))
    return groups


def donors_for_torrent(conn: sqlite3.Connection, torrent_hash: str, items: Iterable[ContentRootSummary]) -> dict:
    row = conn.execute(
        """
        SELECT ti.torrent_hash, ti.save_path, ti.root_name, p.payload_hash, p.root_path, p.file_count, p.total_bytes
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE lower(ti.torrent_hash) = ?
        LIMIT 1
        """,
        (str(torrent_hash or "").strip().lower(),),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"torrent_not_found hash={torrent_hash}")
    payload_hash = str(row["payload_hash"] or "").strip() or None
    exact_non_qb = []
    partial_non_qb = []
    for item in items:
        if payload_hash and item.tree_hash == payload_hash:
            exact_non_qb.append(item)
        elif (
            item.file_count == int(row["file_count"] or 0)
            and item.total_bytes == int(row["total_bytes"] or 0)
        ):
            partial_non_qb.append(item)
    exact_non_qb.sort(key=lambda item: item.root_path)
    partial_non_qb.sort(key=lambda item: (item.status != "complete", item.root_path))
    return {
        "torrent_hash": str(row["torrent_hash"]),
        "save_path": str(row["save_path"] or ""),
        "root_name": str(row["root_name"] or ""),
        "payload_hash": payload_hash,
        "root_path": str(row["root_path"] or ""),
        "file_count": int(row["file_count"] or 0),
        "total_bytes": int(row["total_bytes"] or 0),
        "exact_non_qb_donors": exact_non_qb,
        "candidate_non_qb_donors": partial_non_qb,
    }
