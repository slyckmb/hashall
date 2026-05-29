"""
Hitchhiker audit: detect N→1 payload groups (multiple hashes sharing one on-disk tree).

A "hitchhiker" group is a payload row in the catalog with 2+ torrent_instances rows.
Each hash needs its own unique content tree for correct verification and cleanup.
"""

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rt_cache import load_rt_cache_snapshot
from .rtorrent import DEFAULT_RT_SESSION_DIR, load_rt_session_directories, rt_path_aligned
from .utils import find_db_path


class HitchhikerStatus(str, Enum):
    """Classification of N→1 payload groups."""
    BLOCKED = "blocked"           # stale catalog/client drift/unsafe to split
    UNSPLIT = "unsplit"           # all N hashes point to same root, none in _rehome-unique
    PARTIALLY_SPLIT = "partially_split"  # some hashes already in _rehome-unique
    BUSY = "busy"                 # one or more hashes in checking/active state
    SAFE_TO_SPLIT = "safe_to_split"  # all hashes stopped, no busy, not partially split
    TYPE_A = "type_a"             # multiple distinct payloads sharing same root_path (catalog collision)


HEALTHY_QB_SPLIT_STATES = {"stoppedDL", "stoppedUP", "pausedDL", "pausedUP"}
HEALTHY_RT_SPLIT_STATES = {"uploading", "stalledUP", "stoppedUP", "pausedUP", "stopped", "paused"}


@dataclass
class HitchhikerGroup:
    """A group of hashes sharing one payload."""
    payload_id: int
    root_path: str
    file_count: int
    total_bytes: int
    hashes: list[str]  # list of torrent hashes
    status: HitchhikerStatus
    notes: list[str]
    hash_meta: dict = None  # type: ignore[assignment]
    # keyed by hash: {category, tags, save_path, content_path, rt_directory}


def query_hitchhiker_groups(db_path: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """
    Query catalog for N→1 payload groups.
    Returns list of (payload_id, hash, save_path, source) rows, grouped by payload_id.
    """
    db = find_db_path(db_path)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        limit_clause = f" LIMIT {limit}" if limit else ""
        query = f"""
            SELECT ti.payload_id, ti.torrent_hash, ti.save_path,
                   p.root_path, p.file_count, p.total_bytes
            FROM torrent_instances ti
            JOIN payloads p ON ti.payload_id = p.payload_id
            WHERE ti.payload_id IN (
                SELECT payload_id FROM torrent_instances
                GROUP BY payload_id HAVING COUNT(*) > 1
                ORDER BY payload_id{limit_clause}
            )
            ORDER BY ti.payload_id, ti.torrent_hash
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def query_type_a_groups(db_path: Optional[str] = None) -> list[HitchhikerGroup]:
    """
    Query catalog for Type A hitchhikers: distinct payload rows sharing the same root_path.

    Type A = different items with different file sets cataloged under the same on-disk tree
    root (catalog collision). Each shared root_path becomes one HitchhikerGroup with
    status=TYPE_A; hashes are all torrent_instances across all colliding payloads.
    """
    db = find_db_path(db_path)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT p.payload_id, p.root_path, p.file_count, p.total_bytes, ti.torrent_hash
            FROM payloads p
            LEFT JOIN torrent_instances ti ON ti.payload_id = p.payload_id
            WHERE p.root_path IN (
                SELECT root_path FROM payloads
                GROUP BY root_path HAVING COUNT(DISTINCT payload_id) > 1
            )
            ORDER BY p.root_path, p.payload_id, ti.torrent_hash
        """).fetchall()
    finally:
        conn.close()

    # Group by root_path
    by_root: dict = {}
    for row in rows:
        key = row["root_path"]
        if key not in by_root:
            by_root[key] = {
                "payload_ids": [],
                "hashes": [],
                "file_count": row["file_count"],
                "total_bytes": row["total_bytes"],
                "first_payload_id": row["payload_id"],
            }
        if row["payload_id"] not in by_root[key]["payload_ids"]:
            by_root[key]["payload_ids"].append(row["payload_id"])
        if row["torrent_hash"] is not None:
            by_root[key]["hashes"].append(row["torrent_hash"])

    groups: list[HitchhikerGroup] = []
    for root_path, data in by_root.items():
        notes = [f"  payload_ids sharing this root: {data['payload_ids']}"]
        groups.append(HitchhikerGroup(
            payload_id=data["first_payload_id"],
            root_path=root_path,
            file_count=data["file_count"],
            total_bytes=data["total_bytes"],
            hashes=data["hashes"],
            status=HitchhikerStatus.TYPE_A,
            notes=notes,
        ))
    return groups


def audit_hitchhiker_groups(
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
    session_dir: Path = DEFAULT_RT_SESSION_DIR,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_cache_file: Path | None = None,
) -> list[HitchhikerGroup]:
    """
    Audit all N→1 payload groups: classify by safety to split.
    Returns list of HitchhikerGroup with status and notes.
    """
    # Query catalog
    catalog_rows = query_hitchhiker_groups(db_path=db_path, limit=limit)
    if not catalog_rows:
        return []

    # Group by payload_id
    groups_by_payload = {}
    for row in catalog_rows:
        payload_id = row["payload_id"]
        if payload_id not in groups_by_payload:
            groups_by_payload[payload_id] = {
                "root_path": row["root_path"],
                "file_count": row["file_count"],
                "total_bytes": row["total_bytes"],
                "hashes": [],
                "save_paths": set(),
            }
        groups_by_payload[payload_id]["hashes"].append(row["torrent_hash"])
        groups_by_payload[payload_id]["save_paths"].add(row["save_path"])

    # Load qB state from file cache (avoids live API hit)
    qb_by_hash: dict = {}
    try:
        cached_raw = get_torrents_from_cache(max_age_s=300, cache_path=qb_cache_file)
        if cached_raw is not None:
            qb_client = QBittorrentClient()
            for r in cached_raw:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_by_hash[t.hash.lower()] = t
        else:
            # Fallback to live if cache absent/stale
            qb_client = QBittorrentClient()
            all_hashes = [row["torrent_hash"] for row in catalog_rows]
            live = qb_client.get_torrents_by_hashes(all_hashes) or {}
            qb_by_hash = {h.lower(): v for h, v in live.items()}
    except Exception:
        pass  # qB not accessible; continue with what we have

    # Load RT state from cache snapshot and session files and index by hash.
    # The shared RT cache can lag or omit directory values; session files are
    # the safer source for split/path-alignment checks.
    rt_by_hash: dict = {}
    try:
        kwargs = {"cache_file": rt_cache_file} if rt_cache_file is not None else {}
        snapshot = load_rt_cache_snapshot(**kwargs) or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception:
        pass
    try:
        rt_session_dirs = load_rt_session_directories(session_dir)
    except Exception:
        rt_session_dirs = {}

    # Classify each group
    groups = []
    for payload_id, group_data in groups_by_payload.items():
        hashes = group_data["hashes"]
        notes = []
        status = HitchhikerStatus.UNSPLIT
        busy_hashes = []
        partial_hashes = []
        blocked_hashes = []
        all_stopped = True

        for hash_val in hashes:
            # Check qB state
            hash_key = hash_val.lower()
            qb_torrent = qb_by_hash.get(hash_key)
            qb_state = qb_torrent.state if qb_torrent else "unknown"
            qb_save = qb_torrent.save_path if qb_torrent else ""
            qb_content = getattr(qb_torrent, "content_path", "") if qb_torrent else ""

            # Check RT state
            rt_info = rt_by_hash.get(hash_key, {})
            rt_session_entry = rt_session_dirs.get(hash_key)
            rt_state = str(rt_info.get("state") or "").strip()
            rt_dir = str(
                rt_info.get("directory")
                or rt_info.get("save_path")
                or (rt_session_entry.directory if rt_session_entry else "")
                or ""
            ).strip()
            in_qb = qb_torrent is not None
            in_rt = bool(rt_info) or rt_session_entry is not None

            # Check if already split (under _rehome-unique)
            if "_rehome-unique" in qb_save or "_rehome-unique" in rt_dir:
                partial_hashes.append(hash_val)
                notes.append(f"  {hash_val[:12]}: already in _rehome-unique")

            if not in_qb and not in_rt:
                blocked_hashes.append(hash_val)
                all_stopped = False
                notes.append(f"  {hash_val[:12]}: missing from both qB and RT (stale catalog row)")
                continue

            if in_qb and in_rt and not rt_path_aligned(
                rt_dir,
                qb_save_path=qb_save,
                qb_content_path=qb_content,
            ):
                blocked_hashes.append(hash_val)
                all_stopped = False
                notes.append(
                    f"  {hash_val[:12]}: qB/RT path drift blocks blind split "
                    f"(qb={qb_save or qb_content!r} rt={rt_dir!r})"
                )
                continue

            # Check if busy
            if qb_state in ("checkingDL", "checkingUP", "forcedDL", "forcedUP"):
                busy_hashes.append(hash_val)
                notes.append(f"  {hash_val[:12]}: qb state={qb_state} (busy)")
                all_stopped = False
            elif qb_state == "unknown":
                # Hash not in qB. Check if still active in RT.
                # If not in qB but RT still owns it, this broad split path is unsafe.
                if rt_state and rt_state not in ("stopped", "paused"):
                    all_stopped = False
                    notes.append(f"  {hash_val[:12]}: missing from qB but active in RT")
            elif qb_state not in HEALTHY_QB_SPLIT_STATES:
                # Not in a stopped/paused state
                all_stopped = False
            if rt_state and rt_state not in HEALTHY_RT_SPLIT_STATES:
                busy_hashes.append(hash_val)
                notes.append(f"  {hash_val[:12]}: rt state={rt_state} (busy)")
                all_stopped = False

        # Classify status
        if blocked_hashes:
            status = HitchhikerStatus.BLOCKED
        elif busy_hashes:
            status = HitchhikerStatus.BUSY
        elif partial_hashes:
            status = HitchhikerStatus.PARTIALLY_SPLIT
        elif all_stopped and not busy_hashes:
            status = HitchhikerStatus.SAFE_TO_SPLIT
        else:
            status = HitchhikerStatus.UNSPLIT

        # Check all hashes share same save_path (path-hitchhiker, not inode-hitchhiker)
        if len(group_data["save_paths"]) > 1:
            notes.append(f"  Multiple save_paths: {group_data['save_paths']}")

        # Build per-hash metadata for canonical path inference
        hash_meta: dict[str, dict] = {}
        for hash_val in hashes:
            hk = hash_val.lower()
            qb_t = qb_by_hash.get(hk)
            rt_i = rt_by_hash.get(hk, {})
            hash_meta[hash_val] = {
                "category": getattr(qb_t, "category", "") if qb_t else "",
                "tags": getattr(qb_t, "tags", "") if qb_t else "",
                "save_path": getattr(qb_t, "save_path", "") if qb_t else "",
                "content_path": getattr(qb_t, "content_path", "") if qb_t else "",
                "rt_directory": str(rt_i.get("directory", "") or ""),
            }

        groups.append(
            HitchhikerGroup(
                payload_id=payload_id,
                root_path=group_data["root_path"],
                file_count=group_data["file_count"],
                total_bytes=group_data["total_bytes"],
                hashes=hashes,
                status=status,
                notes=notes,
                hash_meta=hash_meta,
            )
        )

    # Append Type A (catalog collision) groups — separate query, no client-state needed.
    groups.extend(query_type_a_groups(db_path=db_path))

    return groups


def format_hitchhiker_report(groups: list[HitchhikerGroup], json_output: bool = False) -> str:
    """Format hitchhiker audit results for output."""
    if json_output:
        import json
        return json.dumps(
            [
                {
                    "payload_id": g.payload_id,
                    "root_path": g.root_path,
                    "hashes": g.hashes,
                    "status": g.status.value,
                    "file_count": g.file_count,
                    "total_bytes": g.total_bytes,
                    "notes": g.notes,
                }
                for g in groups
            ],
            indent=2,
        )

    # Text output
    lines = []
    lines.append(f"Hitchhiker Audit: {len(groups)} groups found\n")

    # Summary by status
    by_status = {}
    for g in groups:
        by_status.setdefault(g.status, []).append(g)

    for status in [
        HitchhikerStatus.TYPE_A,
        HitchhikerStatus.BLOCKED,
        HitchhikerStatus.SAFE_TO_SPLIT,
        HitchhikerStatus.UNSPLIT,
        HitchhikerStatus.PARTIALLY_SPLIT,
        HitchhikerStatus.BUSY,
    ]:
        if status in by_status:
            lines.append(f"{status.value.upper()}: {len(by_status[status])} groups")

    lines.append("")

    # Detail per group
    for status in [
        HitchhikerStatus.TYPE_A,
        HitchhikerStatus.BLOCKED,
        HitchhikerStatus.SAFE_TO_SPLIT,
        HitchhikerStatus.UNSPLIT,
        HitchhikerStatus.PARTIALLY_SPLIT,
        HitchhikerStatus.BUSY,
    ]:
        if status not in by_status:
            continue

        lines.append(f"\n{status.value.upper()}:")
        for g in by_status[status]:
            lines.append(
                f"  payload_id={g.payload_id}  hashes={len(g.hashes)}  "
                f"root={g.root_path}  bytes={g.total_bytes / (1024**3):.1f}GB"
            )
            for hash_val in g.hashes:
                lines.append(f"    {hash_val[:16]}")
            for note in g.notes:
                lines.append(note)

    return "\n".join(lines)
