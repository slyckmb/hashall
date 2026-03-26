from __future__ import annotations

import hashlib
import sqlite3
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
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


@dataclass(frozen=True)
class RankedDonorCandidate:
    donor_type: str
    confidence: str
    reason: str
    root_path: str
    root_kind: str
    file_count: int
    total_bytes: int
    status: str
    tree_hash: Optional[str]


@dataclass(frozen=True)
class ReclaimCandidate:
    root_path: str
    root_kind: str
    fs_uuid: Optional[str]
    device_id: Optional[int]
    total_bytes: int
    status: str
    recommendation: str
    reason: str


@dataclass(frozen=True)
class ReclaimGroup:
    tree_hash: str
    file_count: int
    total_bytes: int
    keep: ReclaimCandidate
    purge: tuple[ReclaimCandidate, ...]


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


def _prefer_file_roots(root_kind: str, rel_root: str) -> bool:
    parent = Path(rel_root).parent.name
    name = Path(rel_root).name
    if root_kind == "orphan":
        if name in {"books", "movies", "shows"}:
            return True
        if parent == "books" and len(name) == 1:
            return True
    if root_kind == "recovery" and name in {"public", "private", "bluraytracker", "abtorrents"}:
        return True
    return False


def _candidate_abs_path(base_root: Path, rel_root: str, candidate_rel: str) -> str:
    if rel_root == ".":
        relative = Path(candidate_rel)
    else:
        relative = Path(candidate_rel).relative_to(Path(rel_root))
    return str(base_root / relative)


def _iter_candidate_roots(
    conn: sqlite3.Connection,
    *,
    base_root: Path,
) -> Iterable[tuple[sqlite3.Row, str, str, list[sqlite3.Row]]]:
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
    detail_rows = conn.execute(
        f"""
        SELECT path, size, sha256, quick_hash
        FROM {table_ident}
        WHERE {status_clause} path LIKE ?
        ORDER BY path
        """,
        (like_pattern,),
    ).fetchall()
    out: list[tuple[sqlite3.Row, str, str, list[sqlite3.Row]]] = []
    base_text = str(base_root)
    all_paths = [str(row["path"] or "") for row in rows if str(row["path"] or "").strip()]
    if not all_paths:
        return []
    row_by_path = {str(row["path"] or ""): row for row in detail_rows}
    direct_files_by_dir: dict[str, set[str]] = defaultdict(set)
    child_dirs_by_dir: dict[str, set[str]] = defaultdict(set)
    rel_root_path = Path(rel_root) if rel_root != "." else None

    for rel_path in all_paths:
        rel_path_obj = Path(rel_path)
        try:
            rel_under_base = rel_path_obj.relative_to(rel_root_path) if rel_root_path else rel_path_obj
        except Exception:
            continue
        current_rel = rel_root
        parts = rel_under_base.parts
        for part in parts[:-1]:
            child_dirs_by_dir[current_rel].add(part)
            current_rel = f"{current_rel.rstrip('/')}/{part}" if current_rel != "." else part
        direct_files_by_dir[current_rel].add(rel_path)

    @lru_cache(maxsize=None)
    def _collect_subtree_paths(current_rel: str) -> tuple[str, ...]:
        direct_paths = tuple(sorted(direct_files_by_dir.get(current_rel, set())))
        out_paths = list(direct_paths)
        for child in sorted(child_dirs_by_dir.get(current_rel, set())):
            child_rel = f"{current_rel.rstrip('/')}/{child}" if current_rel != "." else child
            out_paths.extend(_collect_subtree_paths(child_rel))
        return tuple(out_paths)

    def add_candidate(candidate_rel: str) -> None:
        candidate_abs = _candidate_abs_path(Path(base_text), rel_root, candidate_rel)
        if candidate_rel in row_by_path:
            candidate_rows = [row_by_path[candidate_rel]]
        else:
            candidate_rows = [row_by_path[path] for path in _collect_subtree_paths(candidate_rel) if path in row_by_path]
        out.append((device_row, candidate_rel, candidate_abs, candidate_rows))

    def walk_dir(current_rel: str) -> None:
        direct_files = direct_files_by_dir.get(current_rel, set())
        child_dirs = child_dirs_by_dir.get(current_rel, set())
        if not direct_files and not child_dirs:
            return

        if direct_files and (child_dirs or _prefer_file_roots(_kind_for_base(base_root), current_rel)):
            for rel_file in sorted(direct_files):
                add_candidate(rel_file)
        elif direct_files:
            add_candidate(current_rel)
            return

        for child in sorted(child_dirs):
            child_rel = f"{current_rel.rstrip('/')}/{child}" if current_rel != "." else child
            walk_dir(child_rel)

    walk_dir(rel_root)
    return out


def _build_summary_for_rel_root(
    *,
    device_row: sqlite3.Row,
    candidate_rel_root: str,
    candidate_abs_root: str,
    root_kind: str,
    rows: list[sqlite3.Row],
) -> ContentRootSummary:
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
        for device_row, rel_root, abs_root, rows in _iter_candidate_roots(conn, base_root=base_root):
            results.append(
                _build_summary_for_rel_root(
                    device_row=device_row,
                    candidate_rel_root=rel_root,
                    candidate_abs_root=abs_root,
                    root_kind=root_kind,
                    rows=rows,
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


def filter_content_roots(
    items: Iterable[ContentRootSummary],
    *,
    root_kind: str | None = None,
    status: str | None = None,
    path_contains: str | None = None,
    min_bytes: int = 0,
) -> list[ContentRootSummary]:
    filtered = []
    needle = str(path_contains or "").strip().lower()
    for item in items:
        if root_kind and item.root_kind != root_kind:
            continue
        if status and item.status != status:
            continue
        if min_bytes and item.total_bytes < min_bytes:
            continue
        if needle and needle not in item.root_path.lower():
            continue
        filtered.append(item)
    return filtered


def sort_content_roots(items: Iterable[ContentRootSummary], *, sort_by: str = "bytes") -> list[ContentRootSummary]:
    if sort_by == "path":
        return sorted(items, key=lambda item: item.root_path)
    if sort_by == "files":
        return sorted(items, key=lambda item: (-item.file_count, -item.total_bytes, item.root_path))
    return sorted(items, key=lambda item: (-item.total_bytes, -item.file_count, item.root_path))


def filter_duplicate_groups(
    groups: Iterable[list[ContentRootSummary]],
    *,
    path_contains: str | None = None,
    min_bytes: int = 0,
) -> list[list[ContentRootSummary]]:
    needle = str(path_contains or "").strip().lower()
    filtered: list[list[ContentRootSummary]] = []
    for group in groups:
        if not group:
            continue
        if min_bytes and group[0].total_bytes < min_bytes:
            continue
        if needle and not any(needle in item.root_path.lower() for item in group):
            continue
        filtered.append(group)
    return filtered


def sort_duplicate_groups(groups: Iterable[list[ContentRootSummary]], *, sort_by: str = "bytes") -> list[list[ContentRootSummary]]:
    if sort_by == "count":
        return sorted(groups, key=lambda group: (-len(group), -group[0].total_bytes, group[0].root_path))
    if sort_by == "path":
        return sorted(groups, key=lambda group: group[0].root_path)
    return sorted(groups, key=lambda group: (-group[0].total_bytes, -len(group), group[0].root_path))


def _path_rank_for_reclaim(path: str) -> tuple[int, str]:
    normalized = str(path or "")
    lowered = normalized.lower()
    if normalized.startswith("/pool/media/"):
        return (0, lowered)
    if "/_rehome-unique/" in lowered:
        return (1, lowered)
    if normalized.startswith("/pool/data/cross-seed-link/"):
        return (2, lowered)
    if normalized.startswith("/pool/data/cross-seed/"):
        return (3, lowered)
    if normalized.startswith("/pool/data/seeds/"):
        return (4, lowered)
    if normalized.startswith("/pool/data/orphaned_data/"):
        return (5, lowered)
    if normalized.startswith("/pool/data/RecycleBin/"):
        return (6, lowered)
    if normalized.startswith("/pool/data/"):
        return (7, lowered)
    return (8, lowered)


def rank_reclaim_groups(groups: Iterable[list[ContentRootSummary]]) -> list[ReclaimGroup]:
    ranked_groups: list[ReclaimGroup] = []
    for group in groups:
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: _path_rank_for_reclaim(item.root_path))
        keep_item = ordered[0]
        purge_items = ordered[1:]
        keep = ReclaimCandidate(
            root_path=keep_item.root_path,
            root_kind=keep_item.root_kind,
            fs_uuid=keep_item.fs_uuid,
            device_id=keep_item.device_id,
            total_bytes=keep_item.total_bytes,
            status=keep_item.status,
            recommendation="keep",
            reason="preferred_path_rank",
        )
        purge = tuple(
            ReclaimCandidate(
                root_path=item.root_path,
                root_kind=item.root_kind,
                fs_uuid=item.fs_uuid,
                device_id=item.device_id,
                total_bytes=item.total_bytes,
                status=item.status,
                recommendation="purge_candidate",
                reason=f"duplicate_of:{keep_item.root_path}",
            )
            for item in purge_items
        )
        ranked_groups.append(
            ReclaimGroup(
                tree_hash=str(keep_item.tree_hash or ""),
                file_count=keep_item.file_count,
                total_bytes=keep_item.total_bytes,
                keep=keep,
                purge=purge,
            )
        )
    ranked_groups.sort(
        key=lambda group: (
            -sum(item.total_bytes for item in group.purge),
            -group.total_bytes,
            group.keep.root_path,
        )
    )
    return ranked_groups


def rank_donor_candidates_for_torrent(conn: sqlite3.Connection, torrent_hash: str, items: Iterable[ContentRootSummary]) -> dict:
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
    file_count = int(row["file_count"] or 0)
    total_bytes = int(row["total_bytes"] or 0)
    ranked: list[RankedDonorCandidate] = []

    for item in items:
        if payload_hash and item.tree_hash == payload_hash:
            ranked.append(
                RankedDonorCandidate(
                    donor_type="non_qb",
                    confidence="exact",
                    reason="tree_hash_match",
                    root_path=item.root_path,
                    root_kind=item.root_kind,
                    file_count=item.file_count,
                    total_bytes=item.total_bytes,
                    status=item.status,
                    tree_hash=item.tree_hash,
                )
            )
            continue
        if item.file_count == file_count and item.total_bytes == total_bytes:
            confidence = "strong" if item.status == "complete" else "candidate"
            reason = "file_count_total_bytes_match"
            ranked.append(
                RankedDonorCandidate(
                    donor_type="non_qb",
                    confidence=confidence,
                    reason=reason,
                    root_path=item.root_path,
                    root_kind=item.root_kind,
                    file_count=item.file_count,
                    total_bytes=item.total_bytes,
                    status=item.status,
                    tree_hash=item.tree_hash,
                )
            )

    confidence_rank = {"exact": 0, "strong": 1, "candidate": 2}
    ranked.sort(
        key=lambda item: (
            confidence_rank.get(item.confidence, 9),
            -item.total_bytes,
            item.root_path,
        )
    )
    return {
        "torrent_hash": str(row["torrent_hash"]),
        "save_path": str(row["save_path"] or ""),
        "root_name": str(row["root_name"] or ""),
        "payload_hash": payload_hash,
        "root_path": str(row["root_path"] or ""),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "ranked_candidates": ranked,
    }


def donors_for_torrent(conn: sqlite3.Connection, torrent_hash: str, items: Iterable[ContentRootSummary]) -> dict:
    ranked_report = rank_donor_candidates_for_torrent(conn, torrent_hash, items)
    exact_non_qb = []
    partial_non_qb = []
    for candidate in ranked_report["ranked_candidates"]:
        item = ContentRootSummary(
            root_path=candidate.root_path,
            root_kind=candidate.root_kind,
            fs_uuid=None,
            device_id=None,
            file_count=candidate.file_count,
            total_bytes=candidate.total_bytes,
            files_with_sha256=0,
            files_with_quick=0,
            tree_hash=candidate.tree_hash,
            status=candidate.status,
        )
        if candidate.confidence == "exact":
            exact_non_qb.append(item)
        else:
            partial_non_qb.append(item)
    return {
        "torrent_hash": ranked_report["torrent_hash"],
        "save_path": ranked_report["save_path"],
        "root_name": ranked_report["root_name"],
        "payload_hash": ranked_report["payload_hash"],
        "root_path": ranked_report["root_path"],
        "file_count": ranked_report["file_count"],
        "total_bytes": ranked_report["total_bytes"],
        "exact_non_qb_donors": exact_non_qb,
        "candidate_non_qb_donors": partial_non_qb,
        "ranked_candidates": ranked_report["ranked_candidates"],
    }
