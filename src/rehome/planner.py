"""
Demotion planning logic for rehome.

Determines whether a payload can be demoted from stash to pool,
and what actions are needed.
"""

import sqlite3
import os
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass

# Import hashall modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from hashall.payload import get_torrent_instance, get_payload_by_id, get_torrent_siblings


@dataclass
class ExternalConsumer:
    """Represents a file with external hardlink consumers."""
    file_path: str
    external_link_paths: List[str]


class DemotionPlanner:
    """
    Plans demotion of payloads from stash to pool.

    Responsibilities:
    - Detect external consumers (hardlinks outside seeding domain)
    - Determine REUSE vs MOVE vs BLOCK decision
    - Generate actionable plan JSON
    """

    def __init__(self, catalog_path: Path, seeding_roots: List[str],
                 stash_device: int, pool_device: int):
        """
        Initialize planner.

        Args:
            catalog_path: Path to hashall catalog database
            seeding_roots: List of seeding domain root paths
            stash_device: Device ID for stash
            pool_device: Device ID for pool
        """
        self.catalog_path = catalog_path
        self.seeding_roots = [Path(r).resolve() for r in seeding_roots]
        self.stash_device = stash_device
        self.pool_device = pool_device

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
        path = Path(file_path).resolve()

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

        # Get all files under root_path from the files table
        # Note: We're using the session-based schema (files table)
        query = """
            SELECT DISTINCT path, inode
            FROM files
            WHERE (path = ? OR path LIKE ?)
            ORDER BY path
        """
        pattern = f"{root_path}/%"
        file_rows = conn.execute(query, (root_path, pattern)).fetchall()

        external_consumers = []

        # For each file, check if its inode has any paths outside seeding domain
        for file_path, inode in file_rows:
            # Find all paths with same inode (hardlinks)
            hardlink_query = """
                SELECT DISTINCT path
                FROM files
                WHERE inode = ?
                ORDER BY path
            """
            hardlink_paths = [row[0] for row in conn.execute(hardlink_query, (inode,)).fetchall()]

            # Filter for external paths
            external_paths = [p for p in hardlink_paths if self._is_external_path(p)]

            if external_paths:
                external_consumers.append(ExternalConsumer(
                    file_path=file_path,
                    external_link_paths=external_paths
                ))

        return external_consumers

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

    def plan_demotion(self, torrent_hash: str) -> Dict:
        """
        Create a demotion plan for a torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            Plan dictionary with decision and actions
        """
        conn = self._get_db_connection()

        try:
            # 1. Resolve torrent → payload
            torrent_instance = get_torrent_instance(conn, torrent_hash)

            if not torrent_instance:
                raise ValueError(f"Torrent {torrent_hash} not found in catalog")

            payload = get_payload_by_id(conn, torrent_instance.payload_id)

            if not payload:
                raise ValueError(f"Payload {torrent_instance.payload_id} not found")

            # 2. Verify payload is on stash
            if payload.device_id != self.stash_device:
                raise ValueError(
                    f"Payload is on device {payload.device_id}, not stash ({self.stash_device})"
                )

            # 3. Get all sibling torrents (same payload)
            sibling_hashes = get_torrent_siblings(conn, torrent_hash)

            # 4. Check for external consumers
            external_consumers = self._detect_external_consumers(conn, payload.root_path)

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
                    "decision": "BLOCK",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": reasons,
                    "affected_torrents": sibling_hashes,
                    "source_path": payload.root_path,
                    "target_path": None,
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

            # 5. Check if payload exists on pool
            pool_root = self._payload_exists_on_pool(conn, payload.payload_hash)

            if pool_root:
                # REUSE: Payload already on pool
                return {
                    "version": "1.0",
                    "decision": "REUSE",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": [f"Payload already exists on pool at {pool_root}"],
                    "affected_torrents": sibling_hashes,
                    "source_path": payload.root_path,
                    "target_path": pool_root,
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }
            else:
                # MOVE: Need to move payload to pool
                # Construct target path (same relative structure on pool)
                # For MVP, we'll use a simple /pool/torrents/content/... structure
                # This should be configurable but we'll hardcode for MVP
                target_root = f"/pool/torrents/content/{Path(payload.root_path).name}"

                return {
                    "version": "1.0",
                    "decision": "MOVE",
                    "torrent_hash": torrent_hash,
                    "payload_id": payload.payload_id,
                    "payload_hash": payload.payload_hash,
                    "reasons": [f"Payload does not exist on pool, will move from {payload.root_path}"],
                    "affected_torrents": sibling_hashes,
                    "source_path": payload.root_path,
                    "target_path": target_root,
                    "file_count": payload.file_count,
                    "total_bytes": payload.total_bytes
                }

        finally:
            conn.close()
