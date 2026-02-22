"""
Demotion planning logic for rehome.

Determines whether a payload can be demoted from stash to pool,
and what actions are needed.
"""

import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass

# Import hashall modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from hashall.payload import (
    get_torrent_instance,
    get_payload_by_id,
    get_payloads_by_hash,
    get_torrent_siblings,
)
from hashall.pathing import canonicalize_path, to_relpath, is_under, remap_to_mount_alias


@dataclass
class ExternalConsumer:
    """Represents a file with external hardlink consumers."""
    file_path: str
    external_link_paths: List[str]


def _build_view_targets(
    conn: sqlite3.Connection,
    torrent_hashes: List[str],
    source_roots: List[Optional[Path]],
    target_root: Optional[Path],
) -> List[Dict]:
    """
    Build per-torrent view targets using a source→target root mapping.

    Returns empty list if source/target roots are not provided.
    """
    if not target_root:
        return []
    resolved_sources = [
        canonicalize_path(Path(r))
        for r in source_roots
        if r
    ]
    if not resolved_sources:
        return []
    resolved_sources = sorted(resolved_sources, key=lambda p: len(str(p)), reverse=True)

    placeholders = ",".join(["?"] * len(torrent_hashes))
    rows = conn.execute(
        f"""
        SELECT torrent_hash, save_path, root_name, device_id
        FROM torrent_instances
        WHERE torrent_hash IN ({placeholders})
        """,
        torrent_hashes,
    ).fetchall()

    device_mounts: Dict[int, List[Path]] = {}
    try:
        mount_rows = conn.execute(
            "SELECT device_id, mount_point, preferred_mount_point FROM devices"
        ).fetchall()
    except sqlite3.Error:
        mount_rows = []
    for device_id, mount_point, preferred_mount in mount_rows:
        if device_id is None:
            continue
        mounts: List[Path] = []
        for candidate in (preferred_mount, mount_point):
            if not candidate:
                continue
            canon = canonicalize_path(Path(candidate))
            if canon not in mounts:
                mounts.append(canon)
        if mounts:
            device_mounts[int(device_id)] = mounts
    mount_groups: List[List[Path]] = list(device_mounts.values())

    view_targets = []
    for torrent_hash, save_path, root_name, device_id in rows:
        if not save_path:
            raise ValueError(f"Missing save_path for torrent {torrent_hash}")

        save_path_path = Path(save_path)
        if save_path_path.is_absolute():
            save_path_path = canonicalize_path(save_path_path)

        source_root = next(
            (root for root in resolved_sources if is_under(save_path_path, root)),
            None,
        )

        if source_root is None:
            candidate_mount_groups: List[List[Path]] = []
            if device_id is not None:
                specific = device_mounts.get(int(device_id), [])
                if specific:
                    candidate_mount_groups.append(specific)
            candidate_mount_groups.extend(mount_groups)

            remapped: Optional[Path] = None
            for mounts in candidate_mount_groups:
                for mount in mounts:
                    rel = to_relpath(save_path_path, mount)
                    if rel is None:
                        continue
                    for alias_mount in mounts:
                        candidate = alias_mount / rel
                        source_root = next(
                            (root for root in resolved_sources if is_under(candidate, root)),
                            None,
                        )
                        if source_root is not None:
                            remapped = candidate
                            break
                    if source_root is not None:
                        break
                if source_root is not None:
                    break
            if remapped is not None:
                save_path_path = remapped

        if source_root is None:
            raise ValueError(
                f"Torrent save_path {save_path_path} is not under any source root"
            )

        rel = save_path_path.relative_to(source_root)
        target_save_path = (target_root / rel).resolve()

        view_targets.append({
            "torrent_hash": torrent_hash,
            "source_save_path": str(save_path_path),
            "target_save_path": str(target_save_path),
            "root_name": root_name,
        })

    return view_targets


class DemotionPlanner:
    """
    Plans demotion of payloads from stash to pool.

    Responsibilities:
    - Detect external consumers (hardlinks outside seeding domain)
    - Determine REUSE vs MOVE vs BLOCK decision
    - Generate actionable plan JSON
    """

    def __init__(self, catalog_path: Path, seeding_roots: List[str],
                 library_roots: Optional[List[str]],
                 stash_device: int, pool_device: int,
                 stash_seeding_root: Optional[str] = None,
                 pool_seeding_root: Optional[str] = None,
                 pool_payload_root: Optional[str] = None):
        """
        Initialize planner.

        Args:
            catalog_path: Path to hashall catalog database
            seeding_roots: List of seeding domain root paths
            library_roots: Optional list of library roots to verify scan coverage
            stash_device: Device ID for stash
            pool_device: Device ID for pool
        """
        self.catalog_path = catalog_path
        self.seeding_roots = [canonicalize_path(Path(r)) for r in seeding_roots]
        self.library_roots = [canonicalize_path(Path(r)) for r in (library_roots or [])]
        self.stash_device = stash_device
        self.pool_device = pool_device
        self.stash_seeding_root = canonicalize_path(Path(stash_seeding_root)) if stash_seeding_root else None
        self.pool_seeding_root = canonicalize_path(Path(pool_seeding_root)) if pool_seeding_root else None
        self.pool_payload_root = canonicalize_path(Path(pool_payload_root)) if pool_payload_root else None
        self._scan_roots_cover_cache: Dict[Tuple[str, ...], Optional[bool]] = {}

    def _compute_pool_move_target(self, source_root_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Compute MOVE target path on pool while preserving seeding-relative structure.

        Returns:
            (target_path, error_reason)
        """
        base_root = self.pool_payload_root or self.pool_seeding_root
        if base_root is None:
            return None, "No pool payload root configured for MOVE"

        source_path = canonicalize_path(Path(source_root_path))

        # Backward compatibility: if stash mapping root is unavailable, keep legacy behavior.
        if self.stash_seeding_root is None:
            return str((base_root / source_path.name).resolve()), None

        rel = to_relpath(source_path, self.stash_seeding_root)
        if rel is None:
            remapped = remap_to_mount_alias(source_path, self.stash_seeding_root)
            if remapped is not None:
                rel = to_relpath(remapped, self.stash_seeding_root)

        if rel is None:
            return (
                None,
                f"Source path {source_path} is not under stash seeding root {self.stash_seeding_root}",
            )

        return str((base_root / rel).resolve()), None

    def _get_db_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.catalog_path)

    def _is_external_path(self, file_path: str) -> bool:
        """
        Check if a path is outside the seeding domain.

        Args:
            file_path: Absolute file path

        Returns:
            True if path is outside all seeding roots
        """
        path = canonicalize_path(Path(file_path))

        for root in self.seeding_roots:
            try:
                path.relative_to(root)
                return False  # Inside seeding domain
            except ValueError:
                continue  # Not under this root

        return True  # Outside all seeding roots

    def _detect_external_consumers(self, conn: sqlite3.Connection,
                                   root_path: str) -> List[ExternalConsumer]:
        """
        Detect files in payload that have hardlinks outside seeding domain.

        Args:
            conn: Database connection
            root_path: Payload root path

        Returns:
            List of ExternalConsumer objects
        """
        # Normalize root path
        root_path = root_path.rstrip('/')
        if not root_path:
            raise ValueError("Payload root path is empty")
        root = Path(root_path)
        if root.is_absolute():
            root = canonicalize_path(root)

        # Get device_id from payload
        device_row = conn.execute("""
            SELECT device_id FROM payloads WHERE root_path = ?
        """, (root_path,)).fetchone()
        if not device_row or device_row[0] is None:
            raise ValueError("Payload device_id is missing; rescan catalog")
        device_id = device_row[0]

        def _table_exists(name: str) -> bool:
            return conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone() is not None

        def _table_has_column(table: str, column: str) -> bool:
            try:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            except sqlite3.Error:
                return False
            return any(row[1] == column for row in rows)

        # Prefer per-device table if present, otherwise fallback to legacy files table
        table_name = f"files_{device_id}"
        use_device_table = _table_exists(table_name)
        use_legacy_table = _table_exists("files")

        if not use_device_table and not use_legacy_table:
            return []

        def _normalize_abs_path(path: Path) -> str:
            # Local filesystem normalization is sufficient for seeding-domain checks.
            try:
                return str(path.resolve())
            except Exception:
                return str(path)

        def _prefix_bounds(prefix: str) -> tuple[str, str]:
            low = f"{prefix}/"
            high = f"{low}\U0010FFFF"
            return low, high

        if use_device_table:
            # Resolve root_path relative to preferred mount when available.
            mount_point = None
            preferred_mount = None
            if _table_exists("devices"):
                device_row = conn.execute(
                    "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
                    (device_id,),
                ).fetchone()
                if device_row:
                    mount_point = Path(device_row[0])
                    preferred_mount = Path(device_row[1] or device_row[0])

            if mount_point is not None:
                if root.is_absolute():
                    rel_root = to_relpath(root, preferred_mount) or to_relpath(root, mount_point)
                    if rel_root is None:
                        raise ValueError("Payload root is not under device mount point; rescan catalog")
                else:
                    rel_root = root
                rel_root_str = str(rel_root)

                base_mount = preferred_mount or mount_point
                def _to_abs(p: str) -> str:
                    path = Path(p)
                    if path.is_absolute():
                        return _normalize_abs_path(path)
                    return _normalize_abs_path(base_mount / path)
            else:
                # No device metadata; expect absolute paths in table
                if not root.is_absolute():
                    raise ValueError("Relative payload root without device mount metadata")
                rel_root_str = str(root)
                def _to_abs(p: str) -> str:
                    return _normalize_abs_path(Path(p))

            low, high = _prefix_bounds(rel_root_str)
            query = f"""
                SELECT path, inode
                FROM {table_name} INDEXED BY sqlite_autoindex_{table_name}_1
                WHERE status = 'active' AND path = ?
                UNION ALL
                SELECT path, inode
                FROM {table_name} INDEXED BY sqlite_autoindex_{table_name}_1
                WHERE status = 'active' AND path >= ? AND path < ?
                ORDER BY path
            """
            file_rows = conn.execute(query, (rel_root_str, low, high)).fetchall()

        else:
            # Legacy table stores absolute paths
            if not root.is_absolute():
                raise ValueError("Relative payload root with legacy files table")
            root_str = str(root)
            low, high = _prefix_bounds(root_str)
            legacy_has_status = _table_has_column("files", "status")
            if legacy_has_status:
                query = """
                    SELECT DISTINCT path, inode
                    FROM files
                    WHERE status = 'active' AND (
                        path = ? OR (path >= ? AND path < ?)
                    )
                    ORDER BY path
                """
                file_rows = conn.execute(query, (root_str, low, high)).fetchall()
            else:
                query = """
                    SELECT DISTINCT path, inode
                    FROM files
                    WHERE path = ? OR (path >= ? AND path < ?)
                    ORDER BY path
                """
                file_rows = conn.execute(query, (root_str, low, high)).fetchall()

            def _to_abs(p: str) -> str:
                return _normalize_abs_path(Path(p))

        if not file_rows:
            raise ValueError("No files found under payload root in catalog; rescan required")

        external_consumers = []
        external_cache: Dict[str, bool] = {}

        def _is_external_cached(path_text: str) -> bool:
            cached = external_cache.get(path_text)
            if cached is not None:
                return cached
            path_obj = Path(path_text)
            is_external = True
            for seed_root in self.seeding_roots:
                try:
                    path_obj.relative_to(seed_root)
                    is_external = False
                    break
                except ValueError:
                    continue
            external_cache[path_text] = is_external
            return is_external

        unique_inodes = sorted({int(inode) for _, inode in file_rows if inode is not None})
        inode_paths: Dict[int, List[str]] = {}
        inode_chunk_size = 500
        if unique_inodes:
            for offset in range(0, len(unique_inodes), inode_chunk_size):
                chunk = unique_inodes[offset: offset + inode_chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                if use_device_table:
                    rows = conn.execute(
                        f"""
                        SELECT inode, path
                        FROM {table_name}
                        WHERE status = 'active' AND inode IN ({placeholders})
                        ORDER BY inode, path
                        """,
                        chunk,
                    ).fetchall()
                else:
                    where_clause = "inode IN ({placeholders})".format(placeholders=placeholders)
                    if legacy_has_status:
                        where_clause = f"status = 'active' AND {where_clause}"
                    rows = conn.execute(
                        f"""
                        SELECT inode, path
                        FROM files
                        WHERE {where_clause}
                        ORDER BY inode, path
                        """,
                        chunk,
                    ).fetchall()

                for inode, hardlink_path in rows:
                    inode_int = int(inode)
                    inode_paths.setdefault(inode_int, []).append(_to_abs(str(hardlink_path)))

        # For each file, check if its inode has any paths outside seeding domain
        for file_path, inode in file_rows:
            inode_int = int(inode)
            hardlink_paths = inode_paths.get(inode_int, [])
            file_path_abs = _to_abs(str(file_path))

            # Filter for external paths
            external_paths = [p for p in hardlink_paths if _is_external_cached(p)]

            if external_paths:
                external_consumers.append(ExternalConsumer(
                    file_path=file_path_abs,
                    external_link_paths=external_paths
                ))

        return external_consumers

    def _scan_roots_cover(self, conn: sqlite3.Connection,
                          roots: List[Path]) -> Optional[bool]:
        """
        Check whether all provided roots are covered by scan_roots for the device.

        Returns:
            True if covered, False if not, None if cannot be determined.
        """
        def _table_exists(name: str) -> bool:
            return conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone() is not None

        if not _table_exists("devices") or not _table_exists("scan_roots"):
            return None

        # Ensure devices table has fs_uuid column
        device_cols = conn.execute("PRAGMA table_info(devices)").fetchall()
        col_names = {row[1] for row in device_cols}
        if "fs_uuid" not in col_names:
            return None

        scan_rows = conn.execute(
            "SELECT fs_uuid, root_path FROM scan_roots"
        ).fetchall()

        if not scan_rows:
            return False

        device_rows = conn.execute(
            "SELECT fs_uuid, mount_point, preferred_mount_point FROM devices"
        ).fetchall()
        if not device_rows:
            return None

        def _normalize(path_text: str) -> Path:
            # scan_roots/devices data are absolute catalog paths; lexical resolution
            # avoids repeated mount/source subprocess calls.
            try:
                return Path(path_text).resolve()
            except Exception:
                return Path(path_text)

        prefixes: List[tuple[str, Path]] = []
        aliases_by_uuid: Dict[str, List[Path]] = {}
        for fs_uuid, mount_point, preferred in device_rows:
            alias_paths: List[Path] = []
            for candidate in (preferred, mount_point):
                if not candidate:
                    continue
                canon = _normalize(str(candidate))
                prefixes.append((fs_uuid, canon))
                if canon not in alias_paths:
                    alias_paths.append(canon)
            if alias_paths:
                aliases_by_uuid[fs_uuid] = alias_paths
        prefixes = sorted(prefixes, key=lambda item: len(str(item[1])), reverse=True)

        scanned_by_uuid: Dict[str, List[Path]] = {}
        for fs_uuid, root_path in scan_rows:
            scanned_by_uuid.setdefault(fs_uuid, []).append(_normalize(str(root_path)))

        for root in roots:
            root_canon = _normalize(str(root))
            fs_uuid = None
            for candidate_uuid, candidate_root in prefixes:
                if is_under(root_canon, candidate_root):
                    fs_uuid = candidate_uuid
                    break
            if fs_uuid is None:
                return False

            scanned_roots = scanned_by_uuid.get(fs_uuid, [])
            if not scanned_roots:
                return False

            covered = any(is_under(root_canon, scanned) for scanned in scanned_roots)
            if not covered:
                alias_roots = aliases_by_uuid.get(fs_uuid, [])
                for alias_root in alias_roots:
                    rel = to_relpath(root_canon, alias_root)
                    if rel is None:
                        continue
                    for alias_target in alias_roots:
                        remapped = alias_target / rel
                        if any(is_under(remapped, scanned) for scanned in scanned_roots):
                            covered = True
                            break
                    if covered:
                        break
            if not covered:
                return False
        return True

    def _scan_roots_cover_cached(self, conn: sqlite3.Connection,
                                 roots: List[Path]) -> Optional[bool]:
        """Memoize scan_roots coverage checks per planner run."""
        key = tuple(str(root) for root in roots)
        if key not in self._scan_roots_cover_cache:
            self._scan_roots_cover_cache[key] = self._scan_roots_cover(conn, roots)
        return self._scan_roots_cover_cache[key]


    def _payload_exists_on_pool(self, conn: sqlite3.Connection,
                                payload_hash: str) -> Optional[str]:
        """
        Check if a payload with this hash exists on pool device.

        Args:
            conn: Database connection
            payload_hash: Payload hash to check

        Returns:
            Root path if found, None otherwise
        """
        if not payload_hash:
            return None

        row = conn.execute("""
            SELECT root_path
            FROM payloads
            WHERE payload_hash = ? AND device_id = ? AND status = 'complete'
            LIMIT 1
        """, (payload_hash, self.pool_device)).fetchone()

        return row[0] if row else None

    def plan_demotion(
        self,
        torrent_hash: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict:
        """
        Create a demotion plan for a torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            Plan dictionary with decision and actions
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            # 1. Resolve torrent → payload
            torrent_instance = get_torrent_instance(conn, torrent_hash)

            if not torrent_instance:
                raise ValueError(f"Torrent {torrent_hash} not found in catalog")

            payload = get_payload_by_id(conn, torrent_instance.payload_id)

            if not payload:
                raise ValueError(f"Payload {torrent_instance.payload_id} not found")

            # 2. Require payload hash for cross-device grouping
            if not payload.payload_hash:
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": ["Payload hash missing; rescan or run sha256-backfill"],
                    "affected_torrents": get_torrent_siblings(conn, torrent_hash),
                    "source_path": payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

            # 3. Resolve payload on stash (source of demotion)
            stash_payloads = get_payloads_by_hash(
                conn, payload.payload_hash, device_id=self.stash_device, status="complete"
            )
            if not stash_payloads:
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": [
                        f"Payload with hash {payload.payload_hash} not found on stash (device {self.stash_device})"
                    ],
                    "affected_torrents": get_torrent_siblings(conn, torrent_hash),
                    "source_path": payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

            source_payload = stash_payloads[0]

            # 4. Get all sibling torrents (same payload hash)
            sibling_hashes = get_torrent_siblings(conn, torrent_hash)

            # 4a. Ensure scan roots cover seeding + library domains (if available)
            required_roots = self.seeding_roots + self.library_roots
            coverage = self._scan_roots_cover_cached(conn, required_roots)
            if coverage is False:
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": ["Seeding/library roots are not covered by scan_roots; rescan required"],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            # 5. Check for external consumers (stash copy)
            try:
                external_consumers = self._detect_external_consumers(conn, source_payload.root_path)
            except ValueError as e:
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [str(e)],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            if external_consumers:
                # BLOCK: External consumers detected
                reasons = []
                for ec in external_consumers:
                    for ext_path in ec.external_link_paths:
                        reasons.append(
                            f"File {ec.file_path} has hardlink at {ext_path} "
                            f"(outside seeding domain)"
                        )

                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": reasons,
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            # 6. Check if payload exists on pool
            pool_root = self._payload_exists_on_pool(conn, source_payload.payload_hash)

            # 6a. Build view targets (if mapping provided)
            try:
                view_targets = _build_view_targets(
                    conn,
                    sibling_hashes,
                    [self.stash_seeding_root, self.pool_seeding_root],
                    self.pool_seeding_root,
                )
            except ValueError as e:
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [str(e)],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            # Build payload group metadata (all payloads with same hash)
            payload_group = [
                {
                    "payload_id": p.payload_id,
                    "device_id": p.device_id,
                    "root_path": p.root_path,
                    "file_count": p.file_count,
                    "total_bytes": p.total_bytes,
                    "status": p.status,
                }
                for p in get_payloads_by_hash(conn, source_payload.payload_hash, status=None)
            ]

            if pool_root:
                # REUSE: Payload already on pool
                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "REUSE",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [f"Payload already exists on pool at {pool_root}"],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": pool_root,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "view_targets": view_targets,
                    "payload_group": payload_group,
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }
            else:
                # MOVE: Need to move payload to pool
                # Construct target path preserving stash-seeding-relative structure.
                target_root, target_error = self._compute_pool_move_target(source_payload.root_path)
                if target_root is None:
                    return {
                        "version": "1.0",
                        "direction": "demote",
                        "decision": "BLOCK",
                        "torrent_hash": torrent_hash,
                        "payload_id": source_payload.payload_id,
                        "payload_hash": source_payload.payload_hash,
                        "reasons": [target_error or "No pool payload root configured for MOVE"],
                        "affected_torrents": sibling_hashes,
                        "source_path": source_payload.root_path,
                        "target_path": None,
                        "source_device_id": self.stash_device,
                        "target_device_id": self.pool_device,
                        "seeding_roots": [str(r) for r in self.seeding_roots],
                        "library_roots": [str(r) for r in self.library_roots],
                        "file_count": source_payload.file_count,
                        "total_bytes": source_payload.total_bytes
                    }

                return {
                    "version": "1.0",
                    "direction": "demote",
                    "decision": "MOVE",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [f"Payload does not exist on pool, will move from {source_payload.root_path}"],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": target_root,
                    "source_device_id": self.stash_device,
                    "target_device_id": self.pool_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "view_targets": view_targets,
                    "payload_group": payload_group,
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

        finally:
            if close_conn:
                conn.close()

    def plan_batch_demotion_by_payload_hash(
        self,
        payload_hash: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict:
        """
        Create a batch demotion plan for all torrents with a specific payload hash.

        Args:
            payload_hash: Payload hash to demote

        Returns:
            Batch plan dictionary with payload-level decision
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            row = conn.execute("""
                SELECT ti.torrent_hash
                FROM torrent_instances ti
                JOIN payloads p ON ti.payload_id = p.payload_id
                WHERE p.payload_hash = ? AND p.status = 'complete'
                ORDER BY ti.torrent_hash
                LIMIT 1
            """, (payload_hash,)).fetchone()

            if not row:
                raise ValueError(f"No torrents found for payload {payload_hash}")

            # Use first torrent to generate plan (all siblings share same decision)
            first_torrent = row[0]
            plan = self.plan_demotion(first_torrent, conn=conn)

            # Mark as batch plan
            plan['batch_mode'] = 'payload_hash'
            plan['batch_filter'] = payload_hash

            return plan

        finally:
            if close_conn:
                conn.close()

    def plan_batch_demotion_by_tag(
        self,
        tag: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[Dict]:
        """
        Create batch demotion plans for all torrents with a specific tag.

        Args:
            tag: qBittorrent tag to filter by

        Returns:
            List of plans (one per unique payload)
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            torrent_rows = conn.execute("""
                SELECT DISTINCT ti.torrent_hash, ti.payload_id, p.payload_hash, ti.tags
                FROM torrent_instances ti
                JOIN payloads p ON ti.payload_id = p.payload_id
                WHERE p.status = 'complete'
                ORDER BY p.payload_hash, ti.payload_id, ti.torrent_hash
            """).fetchall()

            if not torrent_rows:
                raise ValueError("No torrents found")

            # Filter by tag (tags are comma-separated in database)
            matching_torrents = []
            for torrent_hash, payload_id, payload_hash, tags in torrent_rows:
                tag_list = [t.strip() for t in (tags or '').split(',')]
                if tag in tag_list:
                    group_key = payload_hash or f"id:{payload_id}"
                    matching_torrents.append((torrent_hash, group_key))

            if not matching_torrents:
                raise ValueError(f"No torrents with tag '{tag}' found on stash")

            # Group by payload_id to avoid duplicate plans
            payloads_seen = set()
            plans = []

            for torrent_hash, group_key in matching_torrents:
                if group_key in payloads_seen:
                    continue  # Already planned this payload

                payloads_seen.add(group_key)

                # Generate plan for this payload
                plan = self.plan_demotion(torrent_hash, conn=conn)
                plan['batch_mode'] = 'tag'
                plan['batch_filter'] = tag

                plans.append(plan)

            return plans

        finally:
            if close_conn:
                conn.close()


class PromotionPlanner:
    """
    Plans promotion of payloads from pool to stash.

    Responsibilities:
    - Verify payload exists on stash (no blind copy)
    - Determine REUSE vs BLOCK decision
    - Generate actionable plan JSON
    """

    def __init__(self, catalog_path: Path, seeding_roots: List[str],
                 library_roots: Optional[List[str]],
                 stash_device: int, pool_device: int,
                 stash_seeding_root: Optional[str] = None,
                 pool_seeding_root: Optional[str] = None):
        """
        Initialize planner.

        Args:
            catalog_path: Path to hashall catalog database
            seeding_roots: List of seeding domain root paths
            library_roots: Optional list of library roots to include in plan metadata
            stash_device: Device ID for stash
            pool_device: Device ID for pool
        """
        self.catalog_path = catalog_path
        self.seeding_roots = [Path(r).resolve() for r in seeding_roots]
        self.library_roots = [canonicalize_path(Path(r)) for r in (library_roots or [])]
        self.stash_device = stash_device
        self.pool_device = pool_device
        self.stash_seeding_root = canonicalize_path(Path(stash_seeding_root)) if stash_seeding_root else None
        self.pool_seeding_root = canonicalize_path(Path(pool_seeding_root)) if pool_seeding_root else None

    def _get_db_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.catalog_path)

    def _payload_exists_on_stash(self, conn: sqlite3.Connection,
                                 payload_hash: str) -> Optional[str]:
        """
        Check if a payload with this hash exists on stash device.

        Args:
            conn: Database connection
            payload_hash: Payload hash to check

        Returns:
            Root path if found, None otherwise
        """
        if not payload_hash:
            return None

        row = conn.execute("""
            SELECT root_path
            FROM payloads
            WHERE payload_hash = ? AND device_id = ? AND status = 'complete'
            LIMIT 1
        """, (payload_hash, self.stash_device)).fetchone()

        return row[0] if row else None

    def plan_promotion(
        self,
        torrent_hash: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict:
        """
        Create a promotion plan for a torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            Plan dictionary with decision and actions
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            # 1. Resolve torrent → payload
            torrent_instance = get_torrent_instance(conn, torrent_hash)

            if not torrent_instance:
                raise ValueError(f"Torrent {torrent_hash} not found in catalog")

            payload = get_payload_by_id(conn, torrent_instance.payload_id)

            if not payload:
                raise ValueError(f"Payload {torrent_instance.payload_id} not found")

            # 2. Require payload hash for cross-device grouping
            if not payload.payload_hash:
                return {
                    "version": "1.0",
                    "direction": "promote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": ["Payload hash missing; rescan or run sha256-backfill"],
                    "affected_torrents": get_torrent_siblings(conn, torrent_hash),
                    "source_path": payload.root_path,
                    "target_path": None,
                    "source_device_id": self.pool_device,
                    "target_device_id": self.stash_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "no_blind_copy": True,
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

            # 3. Resolve payload on pool (source of promotion)
            pool_payloads = get_payloads_by_hash(
                conn, payload.payload_hash, device_id=self.pool_device, status="complete"
            )
            if not pool_payloads:
                return {
                    "version": "1.0",
                    "direction": "promote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": [
                        f"Payload with hash {payload.payload_hash} not found on pool (device {self.pool_device})"
                    ],
                    "affected_torrents": get_torrent_siblings(conn, torrent_hash),
                    "source_path": payload.root_path,
                    "target_path": None,
                    "source_device_id": self.pool_device,
                    "target_device_id": self.stash_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "no_blind_copy": True,
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

            source_payload = pool_payloads[0]

            # 4. Get all sibling torrents (same payload hash)
            sibling_hashes = get_torrent_siblings(conn, torrent_hash)

            # 5. Check if payload exists on stash (no blind copy)
            stash_root = self._payload_exists_on_stash(conn, source_payload.payload_hash)

            if not stash_root:
                return {
                    "version": "1.0",
                    "direction": "promote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [
                        "Payload does not exist on stash; promotion requires pre-existing stash payload"
                    ],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.pool_device,
                    "target_device_id": self.stash_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "no_blind_copy": True,
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            # Build view targets (if mapping provided)
            try:
                view_targets = _build_view_targets(
                    conn,
                    sibling_hashes,
                    [self.stash_seeding_root, self.pool_seeding_root],
                    self.stash_seeding_root,
                )
            except ValueError as e:
                return {
                    "version": "1.0",
                    "direction": "promote",
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": source_payload.payload_id,
                    "payload_hash": source_payload.payload_hash,
                    "reasons": [str(e)],
                    "affected_torrents": sibling_hashes,
                    "source_path": source_payload.root_path,
                    "target_path": None,
                    "source_device_id": self.pool_device,
                    "target_device_id": self.stash_device,
                    "seeding_roots": [str(r) for r in self.seeding_roots],
                    "library_roots": [str(r) for r in self.library_roots],
                    "no_blind_copy": True,
                    "file_count": source_payload.file_count,
                    "total_bytes": source_payload.total_bytes
                }

            payload_group = [
                {
                    "payload_id": p.payload_id,
                    "device_id": p.device_id,
                    "root_path": p.root_path,
                    "file_count": p.file_count,
                    "total_bytes": p.total_bytes,
                    "status": p.status,
                }
                for p in get_payloads_by_hash(conn, source_payload.payload_hash, status=None)
            ]

            return {
                "version": "1.0",
                "direction": "promote",
                "decision": "REUSE",
                "torrent_hash": torrent_hash,
                "payload_id": source_payload.payload_id,
                "payload_hash": source_payload.payload_hash,
                "reasons": [f"Payload already exists on stash at {stash_root}"],
                "affected_torrents": sibling_hashes,
                "source_path": source_payload.root_path,
                "target_path": stash_root,
                "source_device_id": self.pool_device,
                "target_device_id": self.stash_device,
                "seeding_roots": [str(r) for r in self.seeding_roots],
                "library_roots": [str(r) for r in self.library_roots],
                "no_blind_copy": True,
                "view_targets": view_targets,
                "payload_group": payload_group,
                "file_count": source_payload.file_count,
                "total_bytes": source_payload.total_bytes
            }

        finally:
            if close_conn:
                conn.close()

    def plan_batch_promotion_by_payload_hash(
        self,
        payload_hash: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict:
        """
        Create a batch promotion plan for all torrents with a specific payload hash.

        Args:
            payload_hash: Payload hash to promote

        Returns:
            Batch plan dictionary with payload-level decision
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            row = conn.execute("""
                SELECT ti.torrent_hash
                FROM torrent_instances ti
                JOIN payloads p ON ti.payload_id = p.payload_id
                WHERE p.payload_hash = ? AND p.status = 'complete'
                ORDER BY ti.torrent_hash
                LIMIT 1
            """, (payload_hash,)).fetchone()

            if not row:
                raise ValueError(f"No torrents found for payload {payload_hash}")

            # Use first torrent to generate plan (all siblings share same decision)
            first_torrent = row[0]
            plan = self.plan_promotion(first_torrent, conn=conn)

            # Mark as batch plan
            plan['batch_mode'] = 'payload_hash'
            plan['batch_filter'] = payload_hash

            return plan

        finally:
            if close_conn:
                conn.close()

    def plan_batch_promotion_by_tag(
        self,
        tag: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> List[Dict]:
        """
        Create batch promotion plans for all torrents with a specific tag.

        Args:
            tag: qBittorrent tag to filter by

        Returns:
            List of plans (one per unique payload)
        """
        close_conn = conn is None
        if conn is None:
            conn = self._get_db_connection()

        try:
            torrent_rows = conn.execute("""
                SELECT DISTINCT ti.torrent_hash, ti.payload_id, p.payload_hash, ti.tags
                FROM torrent_instances ti
                JOIN payloads p ON ti.payload_id = p.payload_id
                WHERE p.status = 'complete'
                ORDER BY p.payload_hash, ti.payload_id, ti.torrent_hash
            """).fetchall()

            if not torrent_rows:
                raise ValueError("No torrents found on pool")

            # Filter by tag (tags are comma-separated in database)
            matching_torrents = []
            for torrent_hash, payload_id, payload_hash, tags in torrent_rows:
                tag_list = [t.strip() for t in (tags or '').split(',')]
                if tag in tag_list:
                    group_key = payload_hash or f"id:{payload_id}"
                    matching_torrents.append((torrent_hash, group_key))

            if not matching_torrents:
                raise ValueError(f"No torrents with tag '{tag}' found on pool")

            # Group by payload hash (or payload_id fallback) to avoid duplicate plans
            payloads_seen = set()
            plans = []

            for torrent_hash, group_key in matching_torrents:
                if group_key in payloads_seen:
                    continue

                payloads_seen.add(group_key)
                plan = self.plan_promotion(torrent_hash, conn=conn)
                plan['batch_mode'] = 'tag'
                plan['batch_filter'] = tag
                plans.append(plan)

            return plans

        finally:
            if close_conn:
                conn.close()
