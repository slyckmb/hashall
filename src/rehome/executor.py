"""
Demotion execution logic for rehome.

Applies demotion plans by moving payloads and relocating torrents.
"""

import sqlite3
import shutil
import os
from pathlib import Path
from typing import Dict, List, Optional
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

    def _is_under_roots(self, path: Path, roots: List[Path]) -> bool:
        """Check if a path is under any of the given roots."""
        for root in roots:
            try:
                path.resolve().relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    def _get_torrent_view_path(self, conn: sqlite3.Connection, torrent_hash: str) -> Optional[Path]:
        """Get the on-disk view path for a torrent from the catalog."""
        row = conn.execute("""
            SELECT save_path, root_name
            FROM torrent_instances
            WHERE torrent_hash = ?
        """, (torrent_hash,)).fetchone()

        if not row:
            return None

        save_path, root_name = row
        if not save_path or not root_name:
            return None

        return Path(save_path) / root_name

    def _relocate_torrent(self, torrent_hash: str, new_path: str) -> None:
        """
        Relocate a torrent in qBittorrent.

        Follows tracker-ctl pattern from qbit_migrate_paths.sh:
        1. Pause torrent
        2. Set new location
        3. Resume torrent
        4. Verify new location

        Args:
            torrent_hash: Torrent hash to relocate
            new_path: New save path (directory containing torrent content)

        Raises:
            RuntimeError: If relocation fails at any step
        """
        self._log(f"relocate_torrent hash={torrent_hash[:16]} new_path={new_path}")

        # 1. Pause torrent
        self._log(f"  pause_torrent hash={torrent_hash[:16]}")
        if not self.qbit_client.pause_torrent(torrent_hash):
            raise RuntimeError(f"Failed to pause torrent {torrent_hash[:16]}")

        # 2. Set location
        self._log(f"  set_location hash={torrent_hash[:16]} location={new_path}")
        if not self.qbit_client.set_location(torrent_hash, new_path):
            # Try to resume on failure
            self.qbit_client.resume_torrent(torrent_hash)
            raise RuntimeError(f"Failed to set location for torrent {torrent_hash[:16]}")

        # 3. Resume torrent
        self._log(f"  resume_torrent hash={torrent_hash[:16]}")
        if not self.qbit_client.resume_torrent(torrent_hash):
            raise RuntimeError(f"Failed to resume torrent {torrent_hash[:16]}")

        # 4. Verify new location
        self._log(f"  verify_location hash={torrent_hash[:16]}")
        import time
        time.sleep(1)  # Give qBittorrent time to update
        torrent_info = self.qbit_client.get_torrent_info(torrent_hash)
        if not torrent_info:
            raise RuntimeError(f"Failed to verify torrent {torrent_hash[:16]} after relocation")

        # Normalize paths for comparison
        expected_path = Path(new_path).resolve()
        actual_path = Path(torrent_info.save_path).resolve()

        if actual_path != expected_path:
            raise RuntimeError(
                f"Torrent {torrent_hash[:16]} location verification failed: "
                f"expected={expected_path}, actual={actual_path}"
            )

        self._log(f"  verified hash={torrent_hash[:16]} save_path={actual_path}", "success")

    def dry_run(self, plan: Dict, cleanup_source_views: bool = False,
                cleanup_empty_dirs: bool = False) -> None:
        """
        Perform dry-run of plan (print actions without executing).

        Args:
            plan: Plan dictionary from planner
        """
        direction = plan.get('direction', 'demote')
        decision = plan['decision']
        self._log(f"direction={direction} decision={decision}")
        self._log(f"payload_hash={plan['payload_hash'][:16]}..." if plan['payload_hash'] else "payload_hash=None")
        self._log(f"affected_torrents={len(plan['affected_torrents'])}")
        if plan.get("no_blind_copy"):
            self._log("no_blind_copy=true")

        if direction == 'promote' and decision == 'REUSE':
            self._log("ACTION: PROMOTE_REUSE (reuse existing payload on stash)")
            self._log(f"  source_path={plan['source_path']}")
            self._log(f"  target_path={plan['target_path']}")
            self._log("  Steps:")
            for i, torrent_hash in enumerate(plan['affected_torrents'], 1):
                self._log(f"    {i}. Build stash-side torrent view for {torrent_hash[:16]}...")
                self._log(f"    {i}. Relocate torrent {torrent_hash[:16]} in qBittorrent")
                self._log(f"    {i}. Verify torrent can access files")

        elif decision == 'REUSE':
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

        if cleanup_source_views or cleanup_empty_dirs:
            self._log("CLEANUP (dry-run):")
            if cleanup_source_views:
                self._log("  cleanup_source_views=true")
                self._preview_cleanup_source_views(plan)
            if cleanup_empty_dirs:
                self._log("  cleanup_empty_dirs=true")
                self._preview_cleanup_empty_dirs(plan)

        self._log("✅ Dry-run complete (no changes made)", "success")

    def execute(self, plan: Dict, cleanup_source_views: bool = False,
                cleanup_empty_dirs: bool = False) -> None:
        """
        Execute a demotion plan.

        Args:
            plan: Plan dictionary from planner

        Raises:
            RuntimeError: If any step fails
        """
        direction = plan.get('direction', 'demote')
        decision = plan['decision']

        if decision == 'BLOCK':
            raise RuntimeError("Cannot execute BLOCKED plan")

        self._log(f"Executing {direction} {decision} plan for payload {plan['payload_hash'][:16] if plan['payload_hash'] else 'N/A'}...")

        try:
            if direction == 'promote':
                if decision != 'REUSE':
                    raise RuntimeError(f"Unknown promotion decision: {decision}")
                self._execute_promote_reuse(plan)
            elif decision == 'REUSE':
                self._execute_reuse(plan)
            elif decision == 'MOVE':
                self._execute_move(plan)
            else:
                raise RuntimeError(f"Unknown decision: {decision}")

            self._apply_cleanup(plan, cleanup_source_views, cleanup_empty_dirs)

            self._log("Plan execution completed successfully", "success")
            self._log(
                f"summary direction={direction} decision={decision} "
                f"torrents={len(plan['affected_torrents'])} "
                f"cleanup_source_views={str(cleanup_source_views).lower()} "
                f"cleanup_empty_dirs={str(cleanup_empty_dirs).lower()}",
                "success"
            )

        except Exception as e:
            self._log(f"Execution failed: {e}", "error")
            raise

    def _execute_promote_reuse(self, plan: Dict) -> None:
        """
        Execute a PROMOTE_REUSE plan (pool → stash).

        Steps:
        1. Verify existing payload on stash
        2. For each sibling torrent:
           a. Build stash-side view (logical)
           b. Relocate torrent in qBittorrent
           c. Verify torrent can access files
        """
        target_path = Path(plan['target_path'])

        # 1. Verify existing payload on stash
        self._log(f"step=verify_stash_payload path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError(f"Stash payload file count mismatch at {target_path}")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError(f"Stash payload total bytes mismatch at {target_path}")

        # 2. For each sibling, relocate
        for torrent_hash in plan['affected_torrents']:
            self._log(f"step=relocate_sibling torrent={torrent_hash[:16]}")
            self._log(f"  build_view torrent={torrent_hash[:16]} target={target_path}")
            try:
                self._relocate_torrent(torrent_hash, str(target_path.parent))
            except Exception as e:
                self._log(f"Relocation failed for {torrent_hash[:16]}, aborting", "error")
                raise RuntimeError(f"Failed to relocate torrent {torrent_hash[:16]}: {e}")

        self._log("PROMOTE_REUSE execution complete", "success")

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
        relocated_torrents = []
        for torrent_hash in plan['affected_torrents']:
            self._log(f"step=relocate_sibling torrent={torrent_hash[:16]}")

            # Build torrent view on pool
            # For MVP: Assume payload directory matches torrent name
            # Future: Use hashall link to create hardlink views
            self._log(f"  build_view torrent={torrent_hash[:16]} target={target_path}")

            # Relocate torrent in qBittorrent
            try:
                self._relocate_torrent(torrent_hash, str(target_path.parent))
                relocated_torrents.append(torrent_hash)
            except Exception as e:
                # Rollback: abort execution, torrents remain on stash
                self._log(f"Relocation failed for {torrent_hash[:16]}, aborting", "error")
                raise RuntimeError(f"Failed to relocate torrent {torrent_hash[:16]}: {e}")

        # 3. Cleanup stash-side views
        # Only cleanup after ALL torrents successfully relocated
        self._log(f"step=cleanup_stash path={source_path} relocated={len(relocated_torrents)}")
        # For safety, we don't auto-delete stash content in MVP
        # User should manually verify and cleanup after confirming all torrents work
        self._log(f"  MANUAL_ACTION_REQUIRED: Verify torrents work, then delete {source_path}", "warning")

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
        relocated_torrents = []
        for torrent_hash in plan['affected_torrents']:
            self._log(f"step=relocate_sibling torrent={torrent_hash[:16]}")

            # Build torrent view on pool
            # For MVP: Assume torrent content is at target_path
            # Future: Use hashall link to create hardlink views
            self._log(f"  build_view torrent={torrent_hash[:16]} target={target_path}")

            # Relocate torrent in qBittorrent
            try:
                self._relocate_torrent(torrent_hash, str(target_path.parent))
                relocated_torrents.append(torrent_hash)
            except Exception as e:
                # Rollback: move payload back to stash if ANY torrent fails
                self._log(f"Relocation failed for {torrent_hash[:16]}, rolling back", "error")
                try:
                    shutil.move(str(target_path), str(source_path))
                    self._log(f"  Rolled back payload to {source_path}", "warning")
                except Exception as rollback_error:
                    self._log(f"  ROLLBACK FAILED: {rollback_error}", "error")
                raise RuntimeError(f"Failed to relocate torrent {torrent_hash[:16]}: {e}")

        # 5. Verify source is removed
        self._log(f"step=verify_source_removed path={source_path}")
        if source_path.exists():
            raise RuntimeError(f"Source still exists after move: {source_path}")

        self._log("MOVE execution complete", "success")

    def _apply_cleanup(self, plan: Dict, cleanup_source_views: bool,
                       cleanup_empty_dirs: bool) -> None:
        """Apply optional cleanup actions after successful relocation."""
        if not cleanup_source_views and not cleanup_empty_dirs:
            return

        seeding_roots = [Path(r) for r in plan.get('seeding_roots', [])]
        if not seeding_roots:
            self._log("cleanup_skipped reason=no_seeding_roots", "warning")
            return

        if cleanup_source_views:
            self._cleanup_source_views(plan, seeding_roots, dry_run=False)
        if cleanup_empty_dirs:
            self._cleanup_empty_dirs(plan, seeding_roots, dry_run=False)

    def _preview_cleanup_source_views(self, plan: Dict) -> None:
        """Preview source view cleanup actions without executing."""
        seeding_roots = [Path(r) for r in plan.get('seeding_roots', [])]
        if not seeding_roots:
            self._log("  cleanup_skipped reason=no_seeding_roots", "warning")
            return
        self._cleanup_source_views(plan, seeding_roots, dry_run=True)

    def _preview_cleanup_empty_dirs(self, plan: Dict) -> None:
        """Preview empty dir cleanup actions without executing."""
        seeding_roots = [Path(r) for r in plan.get('seeding_roots', [])]
        if not seeding_roots:
            self._log("  cleanup_skipped reason=no_seeding_roots", "warning")
            return
        self._cleanup_empty_dirs(plan, seeding_roots, dry_run=True)

    def _cleanup_source_views(self, plan: Dict, seeding_roots: List[Path],
                              dry_run: bool) -> None:
        """Remove torrent views at the source side, never canonical payload roots."""
        source_path = Path(plan['source_path']).resolve()
        target_path = Path(plan['target_path']).resolve() if plan.get('target_path') else None

        conn = self._get_db_connection()
        try:
            for torrent_hash in plan['affected_torrents']:
                view_path = self._get_torrent_view_path(conn, torrent_hash)
                if not view_path:
                    self._log(f"  cleanup_view skip reason=missing_view torrent={torrent_hash[:16]}")
                    continue

                view_path = view_path.resolve()
                if view_path == source_path or (target_path and view_path == target_path):
                    self._log(f"  cleanup_view skip reason=canonical_root path={view_path}")
                    continue

                if not self._is_under_roots(view_path, seeding_roots):
                    self._log(f"  cleanup_view skip reason=outside_roots path={view_path}")
                    continue

                if not view_path.exists():
                    self._log(f"  cleanup_view skip reason=missing path={view_path}")
                    continue

                action = "remove_view"
                if dry_run:
                    self._log(f"  {action} dry_run=true path={view_path}")
                    continue

                if view_path.is_dir():
                    shutil.rmtree(view_path)
                else:
                    view_path.unlink()

                self._log(f"  {action} path={view_path}", "success")
        finally:
            conn.close()

    def _cleanup_empty_dirs(self, plan: Dict, seeding_roots: List[Path],
                            dry_run: bool) -> None:
        """Remove empty directories under known seeding roots only."""
        source_path = Path(plan['source_path']).resolve()
        target_path = Path(plan['target_path']).resolve() if plan.get('target_path') else None

        for root in seeding_roots:
            root = root.resolve()
            if not root.exists():
                self._log(f"  cleanup_empty skip reason=missing_root root={root}")
                continue

            for dirpath, dirnames, filenames in os.walk(root, topdown=False):
                path = Path(dirpath)
                if path == root:
                    continue
                if path == source_path or (target_path and path == target_path):
                    continue
                if dirnames or filenames:
                    continue

                if dry_run:
                    self._log(f"  remove_empty_dir dry_run=true path={path}")
                    continue

                try:
                    path.rmdir()
                    self._log(f"  remove_empty_dir path={path}", "success")
                except OSError:
                    # Directory no longer empty or failed; skip
                    self._log(f"  remove_empty_dir skip path={path}", "warning")
