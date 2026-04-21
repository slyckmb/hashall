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

from .qbittorrent import QBittorrentClient
from .rtorrent import load_rt_session_directories
from .rt_cache import load_rt_cache_snapshot
from .utils import find_db_path


class HitchhikerStatus(str, Enum):
    """Classification of N→1 payload groups."""
    UNSPLIT = "unsplit"           # all N hashes point to same root, none in _rehome-unique
    PARTIALLY_SPLIT = "partially_split"  # some hashes already in _rehome-unique
    BUSY = "busy"                 # one or more hashes in checking/active state
    SAFE_TO_SPLIT = "safe_to_split"  # all hashes stopped, no busy, not partially split


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


def query_hitchhiker_groups(db_path: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """
    Query catalog for N→1 payload groups.
    Returns list of (payload_id, hash, save_path, source) rows, grouped by payload_id.
    """
    db = find_db_path(db_path)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT ti.payload_id, ti.torrent_hash, ti.save_path,
                   p.root_path, p.file_count, p.total_bytes
            FROM torrent_instances ti
            JOIN payloads p ON ti.payload_id = p.payload_id
            WHERE ti.payload_id IN (
                SELECT payload_id FROM torrent_instances
                GROUP BY payload_id HAVING COUNT(*) > 1
            )
            ORDER BY ti.payload_id, ti.torrent_hash
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def audit_hitchhiker_groups(
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
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

    # Fetch live qB and RT state
    qb_client = QBittorrentClient()
    all_hashes = [row["torrent_hash"] for row in catalog_rows]
    qb_torrents = {}
    try:
        qb_torrents = qb_client.get_torrents_by_hashes(all_hashes) or {}
    except Exception:
        pass  # qB might not be accessible; continue with what we have

    rt_state = load_rt_cache_snapshot() or {}
    rt_dirs = load_rt_session_directories() or {}

    # Classify each group
    groups = []
    for payload_id, group_data in groups_by_payload.items():
        hashes = group_data["hashes"]
        notes = []
        status = HitchhikerStatus.UNSPLIT
        busy_hashes = []
        partial_hashes = []
        all_stopped = True

        for hash_val in hashes:
            # Check qB state
            qb_torrent = qb_torrents.get(hash_val.lower())
            qb_state = qb_torrent.state if qb_torrent else "unknown"
            qb_save = qb_torrent.save_path if qb_torrent else ""

            # Check RT state
            rt_info = rt_state.get(hash_val, {})
            rt_dir = rt_info.get("d.directory", "")

            # Check if already split (under _rehome-unique)
            if "_rehome-unique" in qb_save or "_rehome-unique" in rt_dir:
                partial_hashes.append(hash_val)
                notes.append(f"  {hash_val[:12]}: already in _rehome-unique")

            # Check if busy
            if qb_state in ("checkingDL", "checkingUP", "forcedDL", "forcedUP"):
                busy_hashes.append(hash_val)
                notes.append(f"  {hash_val[:12]}: qb state={qb_state} (busy)")
                all_stopped = False
            elif qb_state not in ("stoppedDL", "stoppedUP", "pausedDL", "pausedUP"):
                # Not in a stopped/paused state
                all_stopped = False

        # Classify status
        if busy_hashes:
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

        groups.append(
            HitchhikerGroup(
                payload_id=payload_id,
                root_path=group_data["root_path"],
                file_count=group_data["file_count"],
                total_bytes=group_data["total_bytes"],
                hashes=hashes,
                status=status,
                notes=notes,
            )
        )

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
