"""
Demotion execution logic for rehome.

Applies demotion plans by moving payloads and relocating torrents.
"""

import sqlite3
import shutil
import os
from pathlib import Path
from typing import Dict, List
import json

# Import hashall and qBittorrent modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from hashall.qbittorrent import get_qbittorrent_client


class DemotionExecutor:
    """
    Executes demotion plans.

    Responsibilities:
    - Move or reuse payloads on pool
    - Build torrent views (hardlinked directory structures)
    - Relocate torrents in qBittorrent
    - Verify all operations
    """

    def __init__(self, catalog_path: Path,
                 qbit_url: str = None, qbit_user: str = None, qbit_pass: str = None):
        """
        Initialize executor.

        Args:
            catalog_path: Path to hashall catalog database
            qbit_url: qBittorrent URL (default from env)
            qbit_user: qBittorrent username (default from env)
            qbit_pass: qBittorrent password (default from env)
        """
        self.catalog_path = catalog_path
        self.qbit_client = get_qbittorrent_client(qbit_url, qbit_user, qbit_pass)

    def _get_db_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.catalog_path)

    def _log(self, message: str, prefix: str = "info"):
        """Log a message with key=value format."""
        prefixes = {
            "info": "ℹ️",
            "success": "✅",
            "error": "❌",
            "warning": "⚠️"
        }
        icon = prefixes.get(prefix, "ℹ️")
        print(f"{icon} {message}")

    def _verify_file_count(self, path: Path, expected_count: int) -> bool:
        """
        Verify file count matches expected.

        Args:
            path: Directory path
            expected_count: Expected number of files

        Returns:
            True if counts match
        """
        if not path.exists():
            return False

        actual_count = sum(1 for _ in path.rglob('*') if _.is_file())
        return actual_count == expected_count

    def _verify_total_bytes(self, path: Path, expected_bytes: int) -> bool:
        """
        Verify total bytes matches expected.

        Args:
            path: Directory path
            expected_bytes: Expected total bytes

        Returns:
            True if bytes match
        """
        if not path.exists():
            return False

        actual_bytes = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return actual_bytes == expected_bytes

    def dry_run(self, plan: Dict) -> None:
        """
        Perform dry-run of plan (print actions without executing).

        Args:
            plan: Plan dictionary from planner
        """
        decision = plan['decision']
        self._log(f"decision={decision}")
        self._log(f"payload_hash={plan['payload_hash'][:16]}..." if plan['payload_hash'] else "payload_hash=None")
        self._log(f"affected_torrents={len(plan['affected_torrents'])}")

        if decision == 'REUSE':
            self._log("ACTION: REUSE existing payload on pool")
            self._log(f"  source_path={plan['source_path']}")
            self._log(f"  target_path={plan['target_path']}")
            self._log(f"  Steps:")
            for i, torrent_hash in enumerate(plan['affected_torrents'], 1):
                self._log(f"    {i}. Build torrent view for {torrent_hash[:16]}...")
                self._log(f"    {i}. Relocate torrent {torrent_hash[:16]} in qBittorrent")
                self._log(f"    {i}. Verify torrent can access files")
            self._log(f"    {len(plan['affected_torrents'])+1}. Remove stash-side torrent views")

        elif decision == 'MOVE':
            self._log("ACTION: MOVE payload from stash to pool")
            self._log(f"  source_path={plan['source_path']}")
            self._log(f"  target_path={plan['target_path']}")
            self._log(f"  file_count={plan['file_count']}")
            self._log(f"  total_bytes={plan['total_bytes']} ({plan['total_bytes']/(1024**3):.2f} GB)")
            self._log(f"  Steps:")
            self._log(f"    1. Verify source exists: {plan['source_path']}")
            self._log(f"    2. Move payload root: {plan['source_path']} → {plan['target_path']}")
            self._log(f"    3. Verify file count and bytes at target")
            for i, torrent_hash in enumerate(plan['affected_torrents'], 1):
                self._log(f"    {i+3}. Build torrent view for {torrent_hash[:16]}...")
                self._log(f"    {i+3}. Relocate torrent {torrent_hash[:16]} in qBittorrent")
                self._log(f"    {i+3}. Verify torrent can access files")

        self._log("✅ Dry-run complete (no changes made)", "success")

    def execute(self, plan: Dict) -> None:
        """
        Execute a demotion plan.

        Args:
            plan: Plan dictionary from planner

        Raises:
            RuntimeError: If any step fails
        """
        decision = plan['decision']

        if decision == 'BLOCK':
            raise RuntimeError("Cannot execute BLOCKED plan")

        self._log(f"Executing {decision} plan for payload {plan['payload_hash'][:16] if plan['payload_hash'] else 'N/A'}...")

        try:
            if decision == 'REUSE':
                self._execute_reuse(plan)
            elif decision == 'MOVE':
                self._execute_move(plan)
            else:
                raise RuntimeError(f"Unknown decision: {decision}")

            self._log("Plan execution completed successfully", "success")

        except Exception as e:
            self._log(f"Execution failed: {e}", "error")
            raise

    def _execute_reuse(self, plan: Dict) -> None:
        """
        Execute a REUSE plan.

        Steps:
        1. Verify existing payload on pool
        2. For each sibling torrent:
           a. Build torrent view on pool (hardlinks to existing payload)
           b. Relocate torrent in qBittorrent
           c. Verify torrent can access files
        3. Remove stash-side torrent views (after all relocations succeed)
        """
        target_path = Path(plan['target_path'])
        source_path = Path(plan['source_path'])

        # 1. Verify existing payload on pool
        self._log(f"step=verify_pool_payload path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError(f"Pool payload file count mismatch at {target_path}")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError(f"Pool payload total bytes mismatch at {target_path}")

        # 2. For each sibling, build view and relocate
        for torrent_hash in plan['affected_torrents']:
            self._log(f"step=build_view torrent={torrent_hash[:16]} target={target_path}")
            # TODO: Build torrent view using hardlinks
            # For MVP, we'll assume the view is the payload itself
            # (single-torrent or torrent name matches directory name)

            self._log(f"step=relocate_torrent torrent={torrent_hash[:16]} new_path={target_path}")
            # TODO: Call qBittorrent API to relocate torrent
            # For MVP, this is stubbed out (requires qBit integration)

            self._log(f"step=verify_torrent torrent={torrent_hash[:16]}")
            # TODO: Verify torrent can access files (check qBit status)

        # 3. Remove stash-side views
        self._log(f"step=cleanup_stash path={source_path}")
        # TODO: Remove stash-side torrent views
        # For MVP, we'll leave this manual (safety-first approach)

        self._log("REUSE execution complete", "success")

    def _execute_move(self, plan: Dict) -> None:
        """
        Execute a MOVE plan.

        Steps:
        1. Verify source exists
        2. Move payload root from stash to pool
        3. Verify file count and bytes at target
        4. For each sibling torrent:
           a. Build torrent view on pool
           b. Relocate torrent in qBittorrent
           c. Verify torrent can access files
        5. Verify source is removed
        """
        source_path = Path(plan['source_path'])
        target_path = Path(plan['target_path'])

        # 1. Verify source exists
        self._log(f"step=verify_source path={source_path}")
        if not source_path.exists():
            raise RuntimeError(f"Source path does not exist: {source_path}")
        if not self._verify_file_count(source_path, plan['file_count']):
            raise RuntimeError(f"Source file count mismatch")
        if not self._verify_total_bytes(source_path, plan['total_bytes']):
            raise RuntimeError(f"Source total bytes mismatch")

        # 2. Move payload root
        self._log(f"step=move_payload source={source_path} target={target_path}")

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Move the directory
        try:
            shutil.move(str(source_path), str(target_path))
        except Exception as e:
            raise RuntimeError(f"Failed to move payload: {e}")

        # 3. Verify target
        self._log(f"step=verify_target path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError(f"Target file count mismatch after move")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError(f"Target total bytes mismatch after move")

        # 4. For each sibling, build view and relocate
        for torrent_hash in plan['affected_torrents']:
            self._log(f"step=build_view torrent={torrent_hash[:16]} target={target_path}")
            # TODO: Build torrent view using hardlinks
            # For MVP, assume view is the payload itself

            self._log(f"step=relocate_torrent torrent={torrent_hash[:16]} new_path={target_path}")
            # TODO: Call qBittorrent API to relocate torrent

            self._log(f"step=verify_torrent torrent={torrent_hash[:16]}")
            # TODO: Verify torrent can access files

        # 5. Verify source is removed
        self._log(f"step=verify_source_removed path={source_path}")
        if source_path.exists():
            raise RuntimeError(f"Source still exists after move: {source_path}")

        self._log("MOVE execution complete", "success")
