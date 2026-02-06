"""
Payload identity module for hashall.

A "payload" is the on-disk content tree a torrent points to:
- Single-file torrent → that file
- Multi-file torrent → directory tree under the torrent root

Payload identity is independent of torrent metadata (piece size, sources, v1/v2, etc).
Multiple different torrents can map to the same payload.
"""

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from hashall.pathing import canonicalize_path, to_relpath


@dataclass
class PayloadFile:
    """Represents a file within a payload."""
    relative_path: str
    size: int
    sha256: Optional[str]  # None if not yet scanned


@dataclass
class Payload:
    """Represents a unique content instance on disk."""
    payload_id: Optional[int]
    payload_hash: Optional[str]
    device_id: Optional[int]
    root_path: str
    file_count: int
    total_bytes: int
    status: str  # 'complete' | 'incomplete'
    last_built_at: Optional[float]


@dataclass
class TorrentInstance:
    """Represents a torrent instance mapping to a payload."""
    torrent_hash: str
    payload_id: int
    device_id: Optional[int]
    save_path: Optional[str]
    root_name: Optional[str]
    category: Optional[str]
    tags: Optional[str]
    last_seen_at: Optional[float]


def compute_payload_hash(files: List[PayloadFile]) -> Optional[str]:
    """
    Compute deterministic payload hash from file list.

    Args:
        files: List of PayloadFile objects

    Returns:
        SHA256 hex digest, or None if any file is missing SHA256

    Algorithm:
        1. Check all files have SHA256
        2. Sort by (relative_path, size, sha256)
        3. Hash the sorted tuple list
    """
    # Check completeness
    for f in files:
        if f.sha256 is None:
            return None  # Incomplete payload

    # Sort files for deterministic output
    sorted_files = sorted(
        files,
        key=lambda f: (f.relative_path, f.size, f.sha256)
    )

    # Compute hash of sorted file metadata
    hasher = hashlib.sha256()
    for f in sorted_files:
        # Encode as: path|size|sha256\n
        entry = f"{f.relative_path}|{f.size}|{f.sha256}\n"
        hasher.update(entry.encode('utf-8'))

    return hasher.hexdigest()


def get_files_for_path(conn: sqlite3.Connection, device_id: int, root_path: str) -> List[PayloadFile]:
    """
    Get all files under a given root path from the per-device table.

    Args:
        conn: Database connection
        device_id: Device ID for the filesystem
        root_path: Root directory path

    Returns:
        List of PayloadFile objects
    """
    # Normalize path
    root_path = root_path.rstrip('/')

    # Use device-specific table
    table_name = f"files_{device_id}"

    # Check if table exists
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name,))

    if not cursor.fetchone():
        # Table doesn't exist, no files to return
        return []

    def _table_exists(name: str) -> bool:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None

    # Determine mount points when available
    mount_point = None
    preferred_mount = None
    if _table_exists("devices"):
        dev_row = conn.execute(
            "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if dev_row:
            mount_point = Path(dev_row[0])
            preferred_mount = Path(dev_row[1] or dev_row[0])

    root = Path(root_path)
    if root.is_absolute():
        root = canonicalize_path(root)

    # Convert root to relative path when mount points are known
    if mount_point:
        if root.is_absolute():
            rel_root = to_relpath(root, preferred_mount) or to_relpath(root, mount_point)
            if rel_root is None:
                return []
        else:
            rel_root = root
    else:
        # Legacy/unknown mount: treat as absolute path in table
        rel_root = root

    rel_root_str = str(rel_root)

    # Query files from device-specific table
    # Only get active files (exclude deleted files)
    if rel_root_str == ".":
        rows = conn.execute(
            f"SELECT path, size, sha256 FROM {table_name} WHERE status = 'active' ORDER BY path"
        ).fetchall()
    else:
        query = f"""
            SELECT path, size, sha256
            FROM {table_name}
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
            ORDER BY path
        """
        pattern = f"{rel_root_str}/%"
        rows = conn.execute(query, (rel_root_str, pattern)).fetchall()

    # Convert to PayloadFile objects
    files = []
    for row in rows:
        path = row[0]
        # Make path relative to payload root
        if rel_root_str == ".":
            relative_path = path
        elif path.startswith(rel_root_str + '/'):
            relative_path = path[len(rel_root_str) + 1:]
        elif path == rel_root_str:
            relative_path = Path(path).name
        else:
            relative_path = path

        files.append(PayloadFile(
            relative_path=relative_path,
            size=row[1],
            sha256=row[2]
        ))

    return files


def build_payload(conn: sqlite3.Connection, root_path: str,
                 device_id: Optional[int] = None) -> Payload:
    """
    Build or update payload for a given root path.

    Args:
        conn: Database connection
        root_path: Root directory path
        device_id: Optional device ID (will be derived from root_path if not provided)

    Returns:
        Payload object (may be incomplete)
    """
    # Canonicalize root path for consistent device resolution
    root = Path(root_path)
    if root.is_absolute():
        root = canonicalize_path(root)

    # Derive device_id from root_path if not provided
    if device_id is None:
        try:
            device_id = os.stat(root).st_dev
        except (OSError, IOError):
            # Path doesn't exist or is inaccessible
            return Payload(
                payload_id=None,
                payload_hash=None,
                device_id=None,
                root_path=str(root),
                file_count=0,
                total_bytes=0,
                status='incomplete',
                last_built_at=None
            )

    # Get files from device-specific table
    files = get_files_for_path(conn, device_id, str(root))

    if not files:
        return Payload(
            payload_id=None,
            payload_hash=None,
            device_id=device_id,
            root_path=str(root),
            file_count=0,
            total_bytes=0,
            status='incomplete',
            last_built_at=None
        )

    # Compute statistics
    file_count = len(files)
    total_bytes = sum(f.size for f in files)

    # Compute payload hash
    payload_hash = compute_payload_hash(files)
    status = 'complete' if payload_hash else 'incomplete'

    return Payload(
        payload_id=None,  # Will be set on insert
        payload_hash=payload_hash,
        device_id=device_id,
        root_path=str(root),
        file_count=file_count,
        total_bytes=total_bytes,
        status=status,
        last_built_at=time.time() if payload_hash else None
    )


def upsert_payload(conn: sqlite3.Connection, payload: Payload) -> int:
    """
    Insert or update a payload in the database.

    Args:
        conn: Database connection
        payload: Payload object

    Returns:
        payload_id (int)
    """
    # Check if payload with this root_path already exists (scoped to device_id)
    if payload.device_id is None:
        existing = conn.execute(
            "SELECT payload_id FROM payloads WHERE root_path = ? AND device_id IS NULL",
            (payload.root_path,)
        ).fetchone()
    else:
        existing = conn.execute(
            "SELECT payload_id FROM payloads WHERE root_path = ? AND device_id = ?",
            (payload.root_path, payload.device_id)
        ).fetchone()

    if existing:
        # Update existing
        payload_id = existing[0]
        conn.execute("""
            UPDATE payloads
            SET payload_hash = ?, device_id = ?, file_count = ?,
                total_bytes = ?, status = ?, last_built_at = ?,
                updated_at = julianday('now')
            WHERE payload_id = ?
        """, (
            payload.payload_hash, payload.device_id, payload.file_count,
            payload.total_bytes, payload.status, payload.last_built_at,
            payload_id
        ))
    else:
        # Insert new
        cursor = conn.execute("""
            INSERT INTO payloads (
                payload_hash, device_id, root_path, file_count,
                total_bytes, status, last_built_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.payload_hash, payload.device_id, payload.root_path,
            payload.file_count, payload.total_bytes, payload.status,
            payload.last_built_at
        ))
        payload_id = cursor.lastrowid

    conn.commit()
    return payload_id


def upsert_torrent_instance(conn: sqlite3.Connection, torrent: TorrentInstance) -> None:
    """
    Insert or update a torrent instance in the database.

    Args:
        conn: Database connection
        torrent: TorrentInstance object
    """
    conn.execute("""
        INSERT OR REPLACE INTO torrent_instances (
            torrent_hash, payload_id, device_id, save_path, root_name,
            category, tags, last_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, julianday('now'))
    """, (
        torrent.torrent_hash, torrent.payload_id, torrent.device_id,
        torrent.save_path, torrent.root_name, torrent.category,
        torrent.tags, torrent.last_seen_at
    ))
    conn.commit()


def get_payload_by_id(conn: sqlite3.Connection, payload_id: int) -> Optional[Payload]:
    """Get payload by ID."""
    row = conn.execute(
        "SELECT * FROM payloads WHERE payload_id = ?",
        (payload_id,)
    ).fetchone()

    if not row:
        return None

    return Payload(
        payload_id=row[0],
        payload_hash=row[1],
        device_id=row[2],
        root_path=row[3],
        file_count=row[4],
        total_bytes=row[5],
        status=row[6],
        last_built_at=row[7]
    )


def get_payloads_by_hash(conn: sqlite3.Connection, payload_hash: str,
                         device_id: Optional[int] = None,
                         status: Optional[str] = "complete") -> List[Payload]:
    """Get payloads by payload_hash, optionally filtering by device and status."""
    if not payload_hash:
        return []

    query = "SELECT * FROM payloads WHERE payload_hash = ?"
    params: List[object] = [payload_hash]

    if device_id is not None:
        query += " AND device_id = ?"
        params.append(device_id)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY payload_id"
    rows = conn.execute(query, params).fetchall()
    return [
        Payload(
            payload_id=row[0],
            payload_hash=row[1],
            device_id=row[2],
            root_path=row[3],
            file_count=row[4],
            total_bytes=row[5],
            status=row[6],
            last_built_at=row[7],
        )
        for row in rows
    ]


def get_torrent_siblings(conn: sqlite3.Connection, torrent_hash: str) -> List[str]:
    """
    Get all torrent hashes that map to the same payload hash.

    Args:
        conn: Database connection
        torrent_hash: Torrent hash to find siblings for

    Returns:
        List of torrent hashes (including the input hash)
    """
    # Get payload_id and payload_hash for this torrent
    row = conn.execute(
        """
        SELECT ti.payload_id, p.payload_hash
        FROM torrent_instances ti
        LEFT JOIN payloads p ON ti.payload_id = p.payload_id
        WHERE ti.torrent_hash = ?
        """,
        (torrent_hash,)
    ).fetchone()

    if not row:
        return []

    payload_id, payload_hash = row

    if payload_hash:
        payload_rows = conn.execute(
            "SELECT payload_id FROM payloads WHERE payload_hash = ?",
            (payload_hash,)
        ).fetchall()
        payload_ids = [r[0] for r in payload_rows]
        if not payload_ids:
            return []
        placeholders = ",".join(["?"] * len(payload_ids))
        rows = conn.execute(
            f"SELECT torrent_hash FROM torrent_instances WHERE payload_id IN ({placeholders}) ORDER BY torrent_hash",
            payload_ids
        ).fetchall()
        return [r[0] for r in rows]

    # Get all torrents with this payload_id
    rows = conn.execute(
        "SELECT torrent_hash FROM torrent_instances WHERE payload_id = ? ORDER BY torrent_hash",
        (payload_id,)
    ).fetchall()

    return [r[0] for r in rows]


def get_torrent_instance(conn: sqlite3.Connection, torrent_hash: str) -> Optional[TorrentInstance]:
    """Get torrent instance by hash."""
    row = conn.execute(
        """SELECT torrent_hash, payload_id, device_id, save_path, root_name,
                  category, tags, last_seen_at
           FROM torrent_instances WHERE torrent_hash = ?""",
        (torrent_hash,)
    ).fetchone()

    if not row:
        return None

    return TorrentInstance(
        torrent_hash=row[0],
        payload_id=row[1],
        device_id=row[2],
        save_path=row[3],
        root_name=row[4],
        category=row[5],
        tags=row[6],
        last_seen_at=row[7]
    )
