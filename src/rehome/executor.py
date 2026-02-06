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
from hashall.payload import get_files_for_path
from rehome.view_builder import build_torrent_view


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

    def _get_torrent_save_path(self, conn: sqlite3.Connection, torrent_hash: str) -> Optional[Path]:
        """Get the save_path for a torrent from the catalog."""
        row = conn.execute("""
            SELECT save_path
            FROM torrent_instances
            WHERE torrent_hash = ?
        """, (torrent_hash,)).fetchone()
        if not row or not row[0]:
            return None
        return Path(row[0])

    def _build_views(self, payload_root: Path, view_targets: List[Dict], plan: Dict) -> None:
        """Build torrent views using hardlinks to the payload root."""
        if not view_targets:
            return

        for target in view_targets:
            torrent_hash = target["torrent_hash"]
            target_save_path = Path(target["target_save_path"])
            root_name = target.get("root_name")

            files = self.qbit_client.get_torrent_files(torrent_hash)
            if not files:
                raise RuntimeError(f"Failed to fetch files for torrent {torrent_hash[:16]}")

            result = build_torrent_view(
                payload_root=payload_root,
                target_save_path=target_save_path,
                files=files,
                root_name=root_name,
            )

            if result.file_count != plan["file_count"] or result.total_bytes != plan["total_bytes"]:
                raise RuntimeError(
                    f"View build mismatch for {torrent_hash[:16]}: "
                    f"files={result.file_count}/{plan['file_count']} "
                    f"bytes={result.total_bytes}/{plan['total_bytes']}"
                )

    def _build_relocations(self, conn: sqlite3.Connection, plan: Dict) -> List[Dict]:
        """Build relocation targets for all torrents in plan."""
        relocations = []
        view_targets = plan.get("view_targets") or []

        if view_targets:
            for target in view_targets:
                if not target.get("source_save_path"):
                    raise RuntimeError(f"Missing source_save_path for torrent {target['torrent_hash']}")
                relocations.append({
                    "torrent_hash": target["torrent_hash"],
                    "source_save_path": target.get("source_save_path"),
                    "target_save_path": target["target_save_path"],
                })
            return relocations

        # Fallback: move all torrents to the payload's parent directory
        fallback_target = str(Path(plan["target_path"]).parent)
        for torrent_hash in plan["affected_torrents"]:
            source_save = self._get_torrent_save_path(conn, torrent_hash)
            if not source_save:
                raise RuntimeError(f"Missing save_path for torrent {torrent_hash}")
            relocations.append({
                "torrent_hash": torrent_hash,
                "source_save_path": str(source_save) if source_save else None,
                "target_save_path": fallback_target,
            })
        return relocations

    def _relocate_torrents_atomic(self, relocations: List[Dict]) -> None:
        """
        Atomically relocate multiple torrents.

        Steps:
        1. Pause all
        2. Set locations for all
        3. Resume all
        4. Verify all
        Rollback location changes if any step fails.
        """
        paused = []
        moved = []

        for r in relocations:
            torrent_hash = r["torrent_hash"]
            if not self.qbit_client.pause_torrent(torrent_hash):
                for h in paused:
                    self.qbit_client.resume_torrent(h)
                raise RuntimeError(f"Failed to pause torrent {torrent_hash[:16]}")
            paused.append(torrent_hash)

        for r in relocations:
            torrent_hash = r["torrent_hash"]
            target_save_path = r["target_save_path"]
            if not self.qbit_client.set_location(torrent_hash, target_save_path):
                # Rollback any moved torrents
                for m in moved:
                    src = m.get("source_save_path")
                    if src:
                        self.qbit_client.set_location(m["torrent_hash"], src)
                for h in paused:
                    self.qbit_client.resume_torrent(h)
                raise RuntimeError(f"Failed to set location for torrent {torrent_hash[:16]}")
            moved.append(r)

        try:
            for h in paused:
                if not self.qbit_client.resume_torrent(h):
                    raise RuntimeError(f"Failed to resume torrent {h[:16]}")

            # Verify locations
            import time
            time.sleep(1)
            for r in relocations:
                torrent_hash = r["torrent_hash"]
                expected_path = Path(r["target_save_path"]).resolve()
                torrent_info = self.qbit_client.get_torrent_info(torrent_hash)
                if not torrent_info:
                    raise RuntimeError(f"Failed to verify torrent {torrent_hash[:16]} after relocation")
                actual_path = Path(torrent_info.save_path).resolve()
                if actual_path != expected_path:
                    raise RuntimeError(
                        f"Torrent {torrent_hash[:16]} location verification failed: "
                        f"expected={expected_path}, actual={actual_path}"
                    )
        except Exception as e:
            # Rollback to original locations if possible
            for m in moved:
                src = m.get("source_save_path")
                if src:
                    self.qbit_client.set_location(m["torrent_hash"], src)
            raise

    def _spot_check_payload(self, payload_root: Path, device_id: int, sample: int) -> None:
        """Spot-check a payload by verifying SHA256 on a sample of files."""
        if sample <= 0:
            return

        conn = self._get_db_connection()
        try:
            files = get_files_for_path(conn, device_id, str(payload_root))
        finally:
            conn.close()

        candidates = [f for f in files if f.sha256]
        if not candidates:
            raise RuntimeError("No SHA256 available for spot-check; run sha256-backfill")

        sample_files = candidates[:sample]
        for f in sample_files:
            if payload_root.is_file():
                abs_path = payload_root
            else:
                abs_path = payload_root / f.relative_path
            actual = compute_sha256(abs_path)
            if actual != f.sha256:
                raise RuntimeError(f"Spot-check hash mismatch for {abs_path}")

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
                cleanup_empty_dirs: bool = False, cleanup_duplicate_payload: bool = False,
                spot_check: int = 0) -> None:
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

        if spot_check:
            self._log(f"spot_check_files={spot_check}")

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

        if cleanup_source_views or cleanup_empty_dirs or cleanup_duplicate_payload:
            self._log("CLEANUP (dry-run):")
            if cleanup_source_views:
                self._log("  cleanup_source_views=true")
                self._preview_cleanup_source_views(plan)
            if cleanup_empty_dirs:
                self._log("  cleanup_empty_dirs=true")
                self._preview_cleanup_empty_dirs(plan)
            if cleanup_duplicate_payload:
                self._log("  cleanup_duplicate_payload=true")
                self._preview_cleanup_duplicate_payload(plan)

        self._log("✅ Dry-run complete (no changes made)", "success")

    def execute(self, plan: Dict, cleanup_source_views: bool = False,
                cleanup_empty_dirs: bool = False, cleanup_duplicate_payload: bool = False,
                rescan: bool = False, spot_check: int = 0) -> None:
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

        run_id = None
        run_conn = self._get_db_connection()
        try:
            run_id = self._record_rehome_run_start(run_conn, plan)
        finally:
            run_conn.close()

        try:
            if direction == 'promote':
                if decision != 'REUSE':
                    raise RuntimeError(f"Unknown promotion decision: {decision}")
                self._execute_promote_reuse(plan, spot_check=spot_check)
            elif decision == 'REUSE':
                self._execute_reuse(plan, spot_check=spot_check)
            elif decision == 'MOVE':
                self._execute_move(plan, spot_check=spot_check)
            else:
                raise RuntimeError(f"Unknown decision: {decision}")

            self._apply_cleanup(plan, cleanup_source_views, cleanup_empty_dirs, cleanup_duplicate_payload)
            self._sync_catalog_after_rehome(plan)
            if rescan:
                self._rescan_after_rehome(plan)

            if run_id is not None:
                run_conn = self._get_db_connection()
                try:
                    self._record_rehome_run_finish(run_conn, run_id, status="success", message="")
                finally:
                    run_conn.close()

            self._log("Plan execution completed successfully", "success")
            self._log(
                f"summary direction={direction} decision={decision} "
                f"torrents={len(plan['affected_torrents'])} "
                f"cleanup_source_views={str(cleanup_source_views).lower()} "
                f"cleanup_empty_dirs={str(cleanup_empty_dirs).lower()}",
                "success"
            )

        except Exception as e:
            if run_id is not None:
                run_conn = self._get_db_connection()
                try:
                    self._record_rehome_run_finish(run_conn, run_id, status="failed", message=str(e))
                finally:
                    run_conn.close()
            self._log(f"Execution failed: {e}", "error")
            raise

    def _sync_catalog_after_rehome(self, plan: Dict) -> None:
        """Update catalog records after successful relocation."""
        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)

            if plan.get("decision") == "REUSE":
                # Reassign torrents to payload on target device
                target_payload_row = conn.execute(
                    """
                    SELECT payload_id
                    FROM payloads
                    WHERE payload_hash = ? AND device_id = ? AND status = 'complete'
                    LIMIT 1
                    """,
                    (plan.get("payload_hash"), plan.get("target_device_id")),
                ).fetchone()

                if not target_payload_row:
                    raise RuntimeError("Target payload not found for catalog sync")

                target_payload_id = target_payload_row[0]

                for r in relocations:
                    conn.execute(
                        """
                        UPDATE torrent_instances
                        SET payload_id = ?, device_id = ?, save_path = ?
                        WHERE torrent_hash = ?
                        """,
                        (target_payload_id, plan.get("target_device_id"),
                         r.get("target_save_path"), r.get("torrent_hash"))
                    )

            elif plan.get("decision") == "MOVE":
                # Update payload location
                conn.execute(
                    """
                    UPDATE payloads
                    SET device_id = ?, root_path = ?, updated_at = julianday('now')
                    WHERE payload_id = ?
                    """,
                    (plan.get("target_device_id"), plan.get("target_path"), plan.get("payload_id"))
                )

                for r in relocations:
                    conn.execute(
                        """
                        UPDATE torrent_instances
                        SET device_id = ?, save_path = ?
                        WHERE torrent_hash = ?
                        """,
                        (plan.get("target_device_id"), r.get("target_save_path"), r.get("torrent_hash"))
                    )

            conn.commit()
        finally:
            conn.close()

    def _rescan_after_rehome(self, plan: Dict) -> None:
        """Rescan relevant roots to refresh file tables after execution."""
        from hashall.scan import scan_path

        paths = [plan.get("source_path"), plan.get("target_path")]
        for p in paths:
            if not p:
                continue
            root = Path(p)
            scan_root = root if root.is_dir() else root.parent
            if not scan_root.exists():
                continue
            scan_path(db_path=self.catalog_path, root_path=scan_root, quiet=True)

    def _record_rehome_run_start(self, conn: sqlite3.Connection, plan: Dict) -> int:
        """Insert a rehome run record and return its ID."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rehome_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                direction TEXT,
                decision TEXT,
                payload_hash TEXT,
                payload_id INTEGER,
                torrent_count INTEGER,
                status TEXT,
                message TEXT
            )
            """
        )
        cursor = conn.execute(
            """
            INSERT INTO rehome_runs (
                direction, decision, payload_hash, payload_id, torrent_count, status, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.get("direction"),
                plan.get("decision"),
                plan.get("payload_hash"),
                plan.get("payload_id"),
                len(plan.get("affected_torrents", [])),
                "running",
                "",
            )
        )
        conn.commit()
        return cursor.lastrowid

    def _record_rehome_run_finish(self, conn: sqlite3.Connection, run_id: int,
                                  status: str, message: str) -> None:
        """Update rehome run record on completion."""
        conn.execute(
            """
            UPDATE rehome_runs
            SET finished_at = CURRENT_TIMESTAMP,
                status = ?,
                message = ?
            WHERE id = ?
            """,
            (status, message, run_id)
        )
        conn.commit()

    def _execute_promote_reuse(self, plan: Dict, spot_check: int = 0) -> None:
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

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)

        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)
        finally:
            conn.close()

        # Build views (if mapping provided)
        self._log("step=build_views")
        self._build_views(target_path, plan.get("view_targets") or [], plan)

        # Relocate all torrents atomically
        self._log("step=relocate_siblings")
        self._relocate_torrents_atomic(relocations)

        self._log("PROMOTE_REUSE execution complete", "success")

    def _execute_reuse(self, plan: Dict, spot_check: int = 0) -> None:
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

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)

        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)
        finally:
            conn.close()

        # Build views (if mapping provided)
        self._log("step=build_views")
        self._build_views(target_path, plan.get("view_targets") or [], plan)

        # Relocate all torrents atomically
        self._log("step=relocate_siblings")
        self._relocate_torrents_atomic(relocations)

        # 3. Cleanup stash-side views
        self._log(f"step=cleanup_stash path={source_path} relocated={len(relocations)}")
        self._log(f"  MANUAL_ACTION_REQUIRED: Verify torrents work, then delete {source_path}", "warning")

        self._log("REUSE execution complete", "success")

    def _execute_move(self, plan: Dict, spot_check: int = 0) -> None:
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

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)

        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)
        finally:
            conn.close()

        # 4. Build views and relocate atomically
        try:
            self._log("step=build_views")
            self._build_views(target_path, plan.get("view_targets") or [], plan)

            self._log("step=relocate_siblings")
            self._relocate_torrents_atomic(relocations)
        except Exception as e:
            # Rollback: move payload back to stash if ANY torrent fails
            self._log("relocation_failed rolling_back_payload", "error")
            try:
                shutil.move(str(target_path), str(source_path))
                self._log(f"  Rolled back payload to {source_path}", "warning")
            except Exception as rollback_error:
                self._log(f"  ROLLBACK FAILED: {rollback_error}", "error")
            raise

        # 5. Verify source is removed
        self._log(f"step=verify_source_removed path={source_path}")
        if source_path.exists():
            raise RuntimeError(f"Source still exists after move: {source_path}")

        self._log("MOVE execution complete", "success")

    def _apply_cleanup(self, plan: Dict, cleanup_source_views: bool,
                       cleanup_empty_dirs: bool, cleanup_duplicate_payload: bool) -> None:
        """Apply optional cleanup actions after successful relocation."""
        if not cleanup_source_views and not cleanup_empty_dirs and not cleanup_duplicate_payload:
            return

        seeding_roots = [Path(r) for r in plan.get('seeding_roots', [])]
        if not seeding_roots:
            self._log("cleanup_skipped reason=no_seeding_roots", "warning")
            return

        if cleanup_source_views:
            self._cleanup_source_views(plan, seeding_roots, dry_run=False)
        if cleanup_empty_dirs:
            self._cleanup_empty_dirs(plan, seeding_roots, dry_run=False)
        if cleanup_duplicate_payload:
            self._cleanup_duplicate_payload(plan, dry_run=False)

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

    def _preview_cleanup_duplicate_payload(self, plan: Dict) -> None:
        """Preview duplicate payload cleanup actions without executing."""
        self._cleanup_duplicate_payload(plan, dry_run=True)

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

    def _cleanup_duplicate_payload(self, plan: Dict, dry_run: bool) -> None:
        """Remove duplicate payload roots after a REUSE plan when explicitly enabled."""
        if plan.get("decision") != "REUSE":
            self._log("  cleanup_duplicate skip reason=not_reuse", "warning")
            return

        target_path = Path(plan['target_path']).resolve() if plan.get('target_path') else None
        if target_path is None:
            self._log("  cleanup_duplicate skip reason=missing_target", "warning")
            return
        if not target_path.exists():
            self._log("  cleanup_duplicate skip reason=missing_target_path", "warning")
            return

        seeding_roots = [Path(r).resolve() for r in plan.get('seeding_roots', [])]
        if not seeding_roots:
            self._log("  cleanup_duplicate skip reason=no_seeding_roots", "warning")
            return

        group = plan.get("payload_group") or []
        if not group:
            source_path = Path(plan['source_path']).resolve()
            if source_path == target_path:
                self._log("  cleanup_duplicate skip reason=same_path", "warning")
                return
            if not source_path.exists():
                self._log("  cleanup_duplicate skip reason=missing_source", "warning")
                return
            if dry_run:
                self._log(f"  remove_duplicate_payload dry_run=true path={source_path}")
                return
            if source_path.is_dir():
                shutil.rmtree(source_path)
            else:
                source_path.unlink()
            self._log(f"  remove_duplicate_payload path={source_path}", "success")
            return

        for entry in group:
            root = Path(entry.get("root_path") or "").resolve()
            if not root:
                continue
            if root == target_path:
                continue
            if not root.exists():
                self._log(f"  cleanup_duplicate skip reason=missing_source path={root}", "warning")
                continue
            if not self._is_under_roots(root, seeding_roots):
                self._log(f"  cleanup_duplicate skip reason=outside_roots path={root}", "warning")
                continue
            file_count = entry.get("file_count", plan.get("file_count"))
            total_bytes = entry.get("total_bytes", plan.get("total_bytes"))
            if not self._verify_file_count(root, file_count):
                self._log(f"  cleanup_duplicate skip reason=file_count_mismatch path={root}", "warning")
                continue
            if not self._verify_total_bytes(root, total_bytes):
                self._log(f"  cleanup_duplicate skip reason=total_bytes_mismatch path={root}", "warning")
                continue

            if dry_run:
                self._log(f"  remove_duplicate_payload dry_run=true path={root}")
                continue

            if root.is_dir():
                shutil.rmtree(root)
            else:
                root.unlink()
            self._log(f"  remove_duplicate_payload path={root}", "success")
