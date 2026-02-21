"""
Demotion execution logic for rehome.

Applies demotion plans by moving payloads and relocating torrents.
"""

import sqlite3
import shutil
import os
import errno
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
from datetime import datetime
from urllib.parse import quote

# Import hashall and qBittorrent modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from hashall.device import ensure_files_table
from hashall.pathing import canonicalize_path, remap_to_mount_alias, to_relpath
from hashall.qbittorrent import get_qbittorrent_client
from hashall.payload import get_payload_file_rows
from hashall.scan import compute_sha256
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
        self.tag_strict = os.getenv("HASHALL_REHOME_TAG_STRICT") == "1"
        self.disable_atm_on_rehome = os.getenv("HASHALL_REHOME_DISABLE_ATM", "1") != "0"
        self.debug_qb = os.getenv("HASHALL_REHOME_QB_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}

    def _get_db_connection(self, *, read_only: bool = False) -> sqlite3.Connection:
        """Get database connection."""
        if not read_only:
            return sqlite3.connect(self.catalog_path)

        catalog_uri = (
            f"file:{quote(str(Path(self.catalog_path).expanduser().resolve()))}"
            "?mode=ro&immutable=1"
        )
        return sqlite3.connect(catalog_uri, uri=True)

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

        if path.is_file():
            return expected_count == 1

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

        if path.is_file():
            return path.stat().st_size == expected_bytes

        actual_bytes = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return actual_bytes == expected_bytes

    def _is_cross_filesystem(self, source_path: Path, target_parent: Path) -> bool:
        """Return True when source and target parent are on different filesystems."""
        def _existing_probe(path: Path) -> Optional[Path]:
            probe = Path(path)
            if probe.exists():
                return probe
            for parent in probe.parents:
                if parent.exists():
                    return parent
            return None

        try:
            source_probe = _existing_probe(source_path)
            target_probe = _existing_probe(target_parent)
            if source_probe is None or target_probe is None:
                # Be conservative: force copy strategy when mount cannot be determined.
                return True
            return source_probe.stat().st_dev != target_probe.stat().st_dev
        except FileNotFoundError:
            # Be conservative if either side disappears mid-check.
            return True

    @staticmethod
    def _is_permission_error(exc: BaseException) -> bool:
        """Return True when an exception indicates permission denied."""
        if isinstance(exc, PermissionError):
            return True
        if isinstance(exc, OSError) and exc.errno in {errno.EACCES, errno.EPERM}:
            return True
        return False

    def _delete_path(self, path: Path) -> None:
        """Delete a file or directory path."""
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _repair_permissions_for_cleanup(self, path: Path) -> bool:
        """
        Repair ownership/mode drift on a specific path tree, then retry cleanup.

        Scope is intentionally narrow (the failing payload path only).
        """
        if not path.exists():
            return True

        cmd_specs = [
            ["sudo", "chown", "-R", "michael:michael", str(path)],
            ["sudo", "find", str(path), "-type", "d", "-exec", "chmod", "2775", "{}", "+"],
            ["sudo", "find", str(path), "-type", "f", "-exec", "chmod", "664", "{}", "+"],
        ]
        for cmd in cmd_specs:
            try:
                self._log(f"  cleanup_perm_repair cmd={' '.join(cmd)}")
                subprocess.run(cmd, check=True)
            except Exception as exc:
                self._log(
                    f"  cleanup_perm_repair failed cmd={' '.join(cmd)} error={exc}",
                    "warning",
                )
                return False
        return True

    def _copy_with_rsync_progress(self, source_path: Path, target_path: Path) -> None:
        """Copy payload with rsync progress output, preserving metadata and hardlinks."""
        rsync_cmd = [
            "rsync",
            "-aHAX",
            "--partial",
            "--human-readable",
            "--info=progress2",
        ]
        if source_path.is_dir():
            rsync_cmd.extend([f"{source_path}/", f"{target_path}/"])
        else:
            rsync_cmd.extend([str(source_path), str(target_path)])

        # Keep transfer low-priority to reduce interference with interactive use.
        cmd: List[str] = []
        if shutil.which("ionice"):
            cmd.extend(["ionice", "-c3"])
        if shutil.which("nice"):
            cmd.extend(["nice", "-n", "15"])
        cmd.extend(rsync_cmd)

        self._log(
            f"step=move_payload method=rsync low_priority=true source={source_path} target={target_path}"
        )
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to copy payload with rsync: {exc}") from exc

    def _is_under_roots(self, path: Path, roots: List[Path]) -> bool:
        """Check if a path is under any of the given roots."""
        for root in roots:
            try:
                path.resolve().relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    def _get_device_mount_info(
        self,
        conn: sqlite3.Connection,
        device_id: Optional[int],
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """Fetch mount_point and preferred_mount_point for a device."""
        if device_id is None:
            return None, None

        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='devices'"
        ).fetchone():
            return None, None

        try:
            row = conn.execute(
                "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT mount_point, mount_point FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()

        if not row or not row[0]:
            return None, None

        mount_point = Path(row[0])
        preferred_mount = Path(row[1] or row[0])
        return mount_point, preferred_mount

    def _to_device_relpath(
        self,
        abs_path: Path,
        mount_point: Optional[Path],
        preferred_mount: Optional[Path],
    ) -> Optional[str]:
        """Map an absolute path to a device-relative path, including mount aliases."""
        p = canonicalize_path(abs_path)
        for base in (preferred_mount, mount_point):
            if base is None:
                continue
            rel = to_relpath(p, base)
            if rel is not None:
                return str(rel)

        # Handle alternate mount aliases (for example /data/media vs /stash/media).
        for base in (preferred_mount, mount_point):
            if base is None:
                continue
            remapped = remap_to_mount_alias(p, base)
            if remapped is None:
                continue
            rel = to_relpath(remapped, base)
            if rel is not None:
                return str(rel)

        return None

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

    def _get_device_table_name(self, conn: sqlite3.Connection, device_id: Optional[int]) -> Optional[str]:
        """Return per-device file table name when it exists."""
        if device_id is None:
            return None
        table_name = f"files_{device_id}"
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        return table_name if exists else None

    def _get_known_sha256_for_abs_path(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        abs_path: Path,
        mount_point: Optional[Path],
        preferred_mount: Optional[Path],
        cache: Dict[str, Optional[str]],
    ) -> Optional[str]:
        """Resolve SHA256 for an absolute path from files_<device_id>, cached by path."""
        key = str(abs_path.resolve())
        if key in cache:
            return cache[key]

        rel_path = self._to_device_relpath(abs_path, mount_point, preferred_mount)
        if rel_path is None:
            cache[key] = None
            return None

        try:
            row = conn.execute(
                f"SELECT sha256 FROM {table_name} WHERE path = ? AND status = 'active' LIMIT 1",
                (rel_path,),
            ).fetchone()
        except sqlite3.OperationalError:
            # Older test schemas may not yet have sha256.
            cache[key] = None
            return None
        value = str(row[0]) if row and row[0] else None
        cache[key] = value
        return value

    def _build_views(
        self,
        payload_root: Path,
        view_targets: List[Dict],
        plan: Dict,
        *,
        preloaded_files: Optional[Dict[str, List]] = None,
    ) -> None:
        """Build torrent views using hardlinks to the payload root."""
        if not view_targets:
            return

        import time

        total = len(view_targets)
        progress_every = 5 if total <= 50 else 25
        files_cache: Dict[str, List] = dict(preloaded_files or {})
        seen_view_targets: set[tuple[str, str]] = set()
        skipped_hashes: set[str] = set()

        conn = self._get_db_connection()
        table_name = self._get_device_table_name(conn, plan.get("target_device_id"))
        mount_point, preferred_mount = self._get_device_mount_info(conn, plan.get("target_device_id"))
        path_sha_cache: Dict[str, Optional[str]] = {}

        def compare_hint(src: Path, dst: Path) -> Optional[bool]:
            if not table_name:
                return None
            src_sha = self._get_known_sha256_for_abs_path(
                conn, table_name, src, mount_point, preferred_mount, path_sha_cache
            )
            dst_sha = self._get_known_sha256_for_abs_path(
                conn, table_name, dst, mount_point, preferred_mount, path_sha_cache
            )
            if src_sha and dst_sha:
                return src_sha == dst_sha
            return None

        try:
            for idx, target in enumerate(view_targets, start=1):
                torrent_hash = target["torrent_hash"]
                target_save_path = Path(target["target_save_path"])
                root_name = target.get("root_name")
                view_key = (str(target_save_path), str(root_name or ""))
                if view_key in seen_view_targets:
                    self._log(
                        "  build_views_progress phase=skip_duplicate_view "
                        f"done={idx}/{total} hash={torrent_hash[:16]}"
                    )
                    continue
                seen_view_targets.add(view_key)

                if idx == 1 or idx == total or idx % progress_every == 0:
                    self._log(
                        f"  build_views_progress phase=fetch_files done={idx}/{total} hash={torrent_hash[:16]}"
                    )
                fetch_start = time.monotonic()
                if torrent_hash in files_cache:
                    files = files_cache[torrent_hash]
                else:
                    files = self.qbit_client.get_torrent_files(torrent_hash)
                    files_cache[torrent_hash] = files
                fetch_elapsed = time.monotonic() - fetch_start
                self._log(
                    f"  build_views_progress phase=fetch_files_done done={idx}/{total} "
                    f"hash={torrent_hash[:16]} files={len(files)} elapsed_s={fetch_elapsed:.1f}"
                )
                if not files:
                    skipped_hashes.add(torrent_hash.lower())
                    self._log(
                        "  build_views_skip phase=missing_files "
                        f"done={idx}/{total} hash={torrent_hash[:16]}",
                        "warning",
                    )
                    continue

                link_start = time.monotonic()
                try:
                    result = build_torrent_view(
                        payload_root=payload_root,
                        target_save_path=target_save_path,
                        files=files,
                        root_name=root_name,
                        compare_hint=compare_hint,
                        progress_cb=lambda msg: self._log(f"  {msg}"),
                    )
                except Exception as exc:
                    first_rel = files[0].name if files else ""
                    self._log(
                        "  build_views_error "
                        f"done={idx}/{total} hash={torrent_hash[:16]} "
                        f"payload_root={payload_root} target_save_path={target_save_path} "
                        f"root_name={root_name or ''} first_rel={first_rel} "
                        f"error_type={type(exc).__name__} error={exc}",
                        "error",
                    )
                    raise
                link_elapsed = time.monotonic() - link_start

                if result.file_count != plan["file_count"] or result.total_bytes != plan["total_bytes"]:
                    raise RuntimeError(
                        f"View build mismatch for {torrent_hash[:16]}: "
                        f"files={result.file_count}/{plan['file_count']} "
                        f"bytes={result.total_bytes}/{plan['total_bytes']}"
                    )
                self._log(
                    f"  build_views_progress phase=link done={idx}/{total} "
                    f"hash={torrent_hash[:16]} elapsed_s={link_elapsed:.1f}"
                )

            if skipped_hashes:
                before = len(plan.get("affected_torrents") or [])
                filtered_torrents = [
                    h for h in (plan.get("affected_torrents") or [])
                    if str(h).strip().lower() not in skipped_hashes
                ]
                plan["affected_torrents"] = filtered_torrents
                if plan.get("torrent_hash", "").strip().lower() in skipped_hashes and filtered_torrents:
                    plan["torrent_hash"] = filtered_torrents[0]

                if plan.get("view_targets"):
                    plan["view_targets"] = [
                        t for t in plan.get("view_targets", [])
                        if str(t.get("torrent_hash", "")).strip().lower() not in skipped_hashes
                    ]

                self._log(
                    "  build_views_filter "
                    f"removed={before - len(filtered_torrents)} "
                    f"remaining={len(filtered_torrents)}",
                    "warning",
                )
                if not filtered_torrents:
                    raise RuntimeError("No live torrents remain after build_views file checks")
        finally:
            conn.close()

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

    def _get_torrent_info_with_retry(
        self,
        torrent_hash: str,
        *,
        attempts: int = 3,
        delay_seconds: float = 1.0,
    ) -> Optional[object]:
        """Fetch torrent info with retries for transient qB timeouts."""
        import time

        for attempt in range(1, attempts + 1):
            info = self.qbit_client.get_torrent_info(torrent_hash)
            if info:
                return info
            if attempt < attempts:
                self._log(
                    f"  retry_get_torrent_info hash={torrent_hash[:16]} "
                    f"attempt={attempt + 1}/{attempts}",
                    "warning",
                )
                time.sleep(min(delay_seconds * attempt, 3.0))
        return None

    def _relocate_torrents_atomic(self, relocations: List[Dict]) -> None:
        """
        Atomically relocate multiple torrents.

        Steps:
        1. Pause all
        2. Set locations for all
        3. Verify all while paused
        4. Resume all
        Rollback location changes if any step fails.
        """
        paused = []
        moved = []
        original_qb_paths: Dict[str, str] = {}
        total = len(relocations)
        progress_every = 5 if total <= 50 else 25

        try:
            # Capture runtime qB save_path as rollback source-of-truth.
            for r in relocations:
                torrent_hash = r["torrent_hash"]
                info = self._get_torrent_info_with_retry(torrent_hash, attempts=3, delay_seconds=1.0)
                if not info:
                    last_error = str(getattr(self.qbit_client, "last_error", "") or "unknown")
                    raise RuntimeError(
                        f"qB info unavailable for torrent {torrent_hash[:16]} "
                        f"error={last_error}"
                    )
                if not getattr(info, "save_path", None):
                    raise RuntimeError(f"Missing qB save_path for torrent {torrent_hash[:16]}")
                original_qb_path = str(getattr(info, "save_path")).strip()
                original_qb_paths[torrent_hash] = original_qb_path
                r["original_save_path_qb"] = original_qb_path

                auto_enabled = bool(getattr(info, "auto_tmm", False)) if info else False
                if self.disable_atm_on_rehome:
                    self._log(
                        f"  auto_tmm_before hash={torrent_hash[:16]} enabled={str(auto_enabled).lower()}"
                    )
                    if auto_enabled:
                        if not hasattr(self.qbit_client, "set_auto_management"):
                            raise RuntimeError(
                                f"qB client missing set_auto_management for torrent {torrent_hash[:16]}"
                            )
                        self._log(f"  disable_auto_tmm hash={torrent_hash[:16]}")
                        if not self.qbit_client.set_auto_management(torrent_hash, False):
                            raise RuntimeError(f"Failed to disable ATM for torrent {torrent_hash[:16]}")

            for idx, r in enumerate(relocations, start=1):
                torrent_hash = r["torrent_hash"]
                if not self.qbit_client.pause_torrent(torrent_hash):
                    raise RuntimeError(f"Failed to pause torrent {torrent_hash[:16]}")
                if not self._wait_for_stable_qb_state(torrent_hash, timeout_seconds=20.0):
                    raise RuntimeError(f"Torrent {torrent_hash[:16]} did not reach stable paused state")
                paused.append(torrent_hash)
                if idx == 1 or idx == total or idx % progress_every == 0:
                    self._log(f"  relocate_progress phase=pause done={idx}/{total}")

            for idx, r in enumerate(relocations, start=1):
                torrent_hash = r["torrent_hash"]
                target_save_path = r["target_save_path"]
                if not self._set_location_with_retry(torrent_hash, target_save_path):
                    raise RuntimeError(f"Failed to set location for torrent {torrent_hash[:16]}")
                moved.append(r)
                if idx == 1 or idx == total or idx % progress_every == 0:
                    self._log(f"  relocate_progress phase=set_location done={idx}/{total}")

            # Verify locations while torrents are paused.
            for idx, r in enumerate(relocations, start=1):
                torrent_hash = r["torrent_hash"]
                expected_path = canonicalize_path(Path(r["target_save_path"]).resolve())
                torrent_info, actual_path = self._wait_for_save_path(
                    torrent_hash,
                    expected_path,
                    timeout_seconds=90.0,
                    interval_seconds=1.0,
                )
                if not torrent_info:
                    raise RuntimeError(f"Failed to verify torrent {torrent_hash[:16]} after relocation")
                if actual_path != expected_path:
                    self._debug_qb_snapshot(torrent_hash, "verify_mismatch")
                    self._log(
                        f"  retry_verify_relocate hash={torrent_hash[:16]}",
                        "warning",
                    )
                    self.qbit_client.pause_torrent(torrent_hash)
                    relocated = self._set_location_with_retry(
                        torrent_hash,
                        str(expected_path),
                        attempts=12,
                        delay_seconds=1.0,
                    )
                    torrent_info, actual_path = self._wait_for_save_path(
                        torrent_hash,
                        expected_path,
                        timeout_seconds=120.0,
                        interval_seconds=1.0,
                    )
                    if (not relocated) or (actual_path != expected_path):
                        raise RuntimeError(
                            f"Torrent {torrent_hash[:16]} location verification failed: "
                            f"expected={expected_path}, actual={actual_path}"
                        )
                if self.disable_atm_on_rehome:
                    if bool(getattr(torrent_info, "auto_tmm", False)):
                        self._log(
                            f"  auto_tmm_after hash={torrent_hash[:16]} enabled=true (re-disabling)",
                            "warning",
                        )
                        if not self.qbit_client.set_auto_management(torrent_hash, False):
                            raise RuntimeError(
                                f"Failed to keep ATM disabled for torrent {torrent_hash[:16]}"
                            )
                        torrent_info = self.qbit_client.get_torrent_info(torrent_hash)
                        if torrent_info and bool(getattr(torrent_info, "auto_tmm", False)):
                            raise RuntimeError(
                                f"ATM still enabled after relocation for torrent {torrent_hash[:16]}"
                            )
                    self._log(
                        f"  auto_tmm_after hash={torrent_hash[:16]} "
                        f"enabled={str(bool(getattr(torrent_info, 'auto_tmm', False))).lower()}"
                    )
                if idx == 1 or idx == total or idx % progress_every == 0:
                    self._log(f"  relocate_progress phase=verify done={idx}/{total}")

            for idx, h in enumerate(paused, start=1):
                if not self.qbit_client.resume_torrent(h):
                    raise RuntimeError(f"Failed to resume torrent {h[:16]}")
                if idx == 1 or idx == total or idx % progress_every == 0:
                    self._log(f"  relocate_progress phase=resume done={idx}/{total}")
        except Exception as e:
            # Rollback to original locations if possible
            for m in moved:
                src = m.get("original_save_path_qb") or original_qb_paths.get(m["torrent_hash"])
                if src:
                    self._set_location_with_retry(m["torrent_hash"], src, attempts=12, delay_seconds=1.0)
            for h in paused:
                self.qbit_client.resume_torrent(h)
            raise

    def _rollback_partial_target_views(self, plan: Dict) -> None:
        """
        Remove pool-side views created before relocation failure.

        This keeps rollback idempotent when payload move is restored but view links
        were already materialized for sibling save paths.
        """
        view_targets = plan.get("view_targets") or []
        if not view_targets:
            return

        source_path = Path(plan.get("source_path", "")).resolve() if plan.get("source_path") else None
        target_path = Path(plan.get("target_path", "")).resolve() if plan.get("target_path") else None
        seeding_roots = [Path(r).resolve() for r in plan.get("seeding_roots", [])]
        seen: set[str] = set()
        removed = 0
        skipped = 0

        for target in view_targets:
            target_save = str(target.get("target_save_path") or "").strip()
            root_name = str(target.get("root_name") or "").strip()
            if not target_save or not root_name:
                skipped += 1
                continue

            view_path = (Path(target_save) / root_name).resolve()
            key = str(view_path)
            if key in seen:
                continue
            seen.add(key)

            if source_path is not None and view_path == source_path:
                skipped += 1
                continue
            if target_path is not None and view_path == target_path:
                skipped += 1
                continue
            if seeding_roots and not self._is_under_roots(view_path, seeding_roots):
                skipped += 1
                continue
            if not view_path.exists():
                skipped += 1
                continue

            try:
                if view_path.is_dir():
                    shutil.rmtree(view_path)
                else:
                    view_path.unlink()
                removed += 1
                self._log(f"  rollback_cleanup_view path={view_path}", "warning")
            except Exception as exc:
                skipped += 1
                self._log(
                    f"  rollback_cleanup_view_failed path={view_path} error={exc}",
                    "warning",
                )

        self._log(f"  rollback_cleanup_summary removed={removed} skipped={skipped}")

    def _set_location_with_retry(
        self,
        torrent_hash: str,
        target_save_path: str,
        *,
        attempts: int = 10,
        delay_seconds: float = 1.0,
    ) -> bool:
        """Set torrent location with retries to tolerate transient qB conflicts."""
        import time

        expected = canonicalize_path(Path(target_save_path).resolve())
        current_info, current_path = self._wait_for_save_path(
            torrent_hash,
            expected,
            timeout_seconds=0.0,
            interval_seconds=0.0,
        )
        if current_info and current_path == expected:
            return True

        for attempt in range(1, attempts + 1):
            if self.qbit_client.set_location(torrent_hash, target_save_path):
                return True
            # qB can return 409 while already applying the path change.
            info, actual = self._wait_for_save_path(
                torrent_hash,
                expected,
                timeout_seconds=2.0,
                interval_seconds=0.5,
            )
            if info and actual == expected:
                return True
            if attempt < attempts:
                if attempt in {4, 8}:
                    self.qbit_client.pause_torrent(torrent_hash)
                self._log(
                    f"  retry_set_location hash={torrent_hash[:16]} "
                    f"attempt={attempt + 1}/{attempts}",
                    "warning",
                )
                backoff = min(delay_seconds * (2 ** (attempt - 1)), 8.0)
                time.sleep(backoff)
        # Final check in case qB committed late.
        info, actual = self._wait_for_save_path(
            torrent_hash,
            expected,
            timeout_seconds=5.0,
            interval_seconds=0.5,
        )
        if info and actual == expected:
            return True
        return False

    def _wait_for_stable_qb_state(
        self,
        torrent_hash: str,
        *,
        timeout_seconds: float = 20.0,
        interval_seconds: float = 0.5,
    ) -> bool:
        """Wait until torrent state is no longer in a transient move/check phase."""
        import time

        transient_markers = ("checking", "moving", "allocating", "queued")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() <= deadline:
            info = self.qbit_client.get_torrent_info(torrent_hash)
            if info:
                state = str(getattr(info, "state", "")).lower()
                if not any(marker in state for marker in transient_markers):
                    return True
                if self.debug_qb:
                    self._log(
                        f"  qb_wait_state hash={torrent_hash[:16]} state={state}",
                        "warning",
                    )
            time.sleep(interval_seconds)
        return False

    def _wait_for_save_path(
        self,
        torrent_hash: str,
        expected_path: Path,
        *,
        timeout_seconds: float = 45.0,
        interval_seconds: float = 1.0,
    ) -> tuple[Optional[object], Optional[Path]]:
        """Poll qB until save_path matches expected, or timeout."""
        import time

        deadline = time.monotonic() + timeout_seconds
        last_info = None
        last_actual: Optional[Path] = None
        last_debug_log = 0.0
        while time.monotonic() <= deadline:
            info = self.qbit_client.get_torrent_info(torrent_hash)
            if info:
                last_info = info
                try:
                    last_actual = canonicalize_path(Path(info.save_path).resolve())
                except Exception:
                    last_actual = Path(info.save_path).resolve()
                if last_actual == expected_path:
                    return info, last_actual
                if self.debug_qb:
                    now = time.monotonic()
                    if last_debug_log == 0.0 or (now - last_debug_log) >= 5.0:
                        self._log(
                            f"  qb_wait hash={torrent_hash[:16]} "
                            f"state={getattr(info, 'state', 'unknown')} "
                            f"progress={getattr(info, 'progress', 'unknown')} "
                            f"actual={last_actual} expected={expected_path}",
                            "warning",
                        )
                        last_debug_log = now
            time.sleep(interval_seconds)
        return last_info, last_actual

    def _debug_qb_snapshot(self, torrent_hash: str, label: str) -> None:
        if not self.debug_qb:
            return
        info = self.qbit_client.get_torrent_info(torrent_hash)
        if not info:
            self._log(f"  qb_debug {label} hash={torrent_hash[:16]} info=missing", "warning")
            return
        self._log(
            f"  qb_debug {label} hash={torrent_hash[:16]} "
            f"state={getattr(info, 'state', 'unknown')} "
            f"progress={getattr(info, 'progress', 'unknown')} "
            f"save_path={getattr(info, 'save_path', 'unknown')} "
            f"content_path={getattr(info, 'content_path', 'unknown')}",
            "warning",
        )

    def _spot_check_payload(self, payload_root: Path, device_id: int, sample: int) -> None:
        """Spot-check a payload by verifying SHA256 and persisting computed values."""
        if sample <= 0:
            return

        conn = self._get_db_connection()
        try:
            rows = get_payload_file_rows(conn, str(payload_root), device_id=device_id)
            if not rows:
                self._log(
                    f"spot_check skipped: no payload rows found root={payload_root}",
                    "warning",
                )
                return

            table_name = f"files_{device_id}"
            hash_source_supported = "hash_source" in {
                str(r[1]) for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }

            # De-duplicate by inode so we never hash the same content twice in one check.
            unique_by_inode = {}
            for row in rows:
                inode_key = row.inode if row.inode is not None else row.path
                unique_by_inode.setdefault(inode_key, row)

            # Prefer smaller files for faster checks while still validating real content.
            sample_files = sorted(unique_by_inode.values(), key=lambda f: f.size)[:sample]
            self._log(
                f"spot_check start sample={len(sample_files)} root={payload_root}"
            )

            persisted_rows = 0
            persisted_groups = 0
            for idx, f in enumerate(sample_files, start=1):
                if payload_root.is_file():
                    abs_path = payload_root
                else:
                    abs_path = payload_root / f.relative_path
                self._log(
                    f"  spot_check_progress done={idx}/{len(sample_files)} "
                    f"size_bytes={f.size} path={abs_path}"
                )
                actual = compute_sha256(abs_path)
                if f.sha256 and actual != f.sha256:
                    raise RuntimeError(f"Spot-check hash mismatch for {abs_path}")

                if f.inode is None:
                    if hash_source_supported:
                        cursor = conn.execute(
                            f"""
                            UPDATE {table_name}
                            SET sha256 = ?, hash_source = ?, last_modified_at = datetime('now')
                            WHERE path = ? AND status = 'active'
                            """,
                            (actual, "calculated", f.path),
                        )
                    else:
                        cursor = conn.execute(
                            f"""
                            UPDATE {table_name}
                            SET sha256 = ?, last_modified_at = datetime('now')
                            WHERE path = ? AND status = 'active'
                            """,
                            (actual, f.path),
                        )
                    persisted_rows += int(cursor.rowcount or 0)
                else:
                    if hash_source_supported:
                        cursor = conn.execute(
                            f"""
                            UPDATE {table_name}
                            SET sha256 = ?,
                                hash_source = CASE WHEN path = ? THEN 'calculated' ELSE ? END,
                                last_modified_at = datetime('now')
                            WHERE inode = ? AND size = ? AND status = 'active'
                            """,
                            (actual, f.path, f"inode:{f.inode}", f.inode, f.size),
                        )
                    else:
                        cursor = conn.execute(
                            f"""
                            UPDATE {table_name}
                            SET sha256 = ?, last_modified_at = datetime('now')
                            WHERE inode = ? AND size = ? AND status = 'active'
                            """,
                            (actual, f.inode, f.size),
                        )
                    persisted_rows += int(cursor.rowcount or 0)
                persisted_groups += 1

            conn.commit()
            self._log(
                f"spot_check persisted_rows={persisted_rows} persisted_inode_groups={persisted_groups}"
            )
            self._log(
                f"spot_check complete sample={len(sample_files)} root={payload_root}",
                "success",
            )
        finally:
            conn.close()

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

        if self.disable_atm_on_rehome:
            info_before = self.qbit_client.get_torrent_info(torrent_hash)
            auto_before = bool(getattr(info_before, "auto_tmm", False)) if info_before else False
            self._log(f"  auto_tmm_before hash={torrent_hash[:16]} enabled={str(auto_before).lower()}")
            if auto_before:
                if not hasattr(self.qbit_client, "set_auto_management"):
                    raise RuntimeError(
                        f"qB client missing set_auto_management for torrent {torrent_hash[:16]}"
                    )
                self._log(f"  disable_auto_tmm hash={torrent_hash[:16]}")
                if not self.qbit_client.set_auto_management(torrent_hash, False):
                    raise RuntimeError(f"Failed to disable ATM for torrent {torrent_hash[:16]}")

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

        if self.disable_atm_on_rehome:
            if bool(getattr(torrent_info, "auto_tmm", False)):
                self._log(
                    f"  auto_tmm_after hash={torrent_hash[:16]} enabled=true (re-disabling)",
                    "warning",
                )
                if not self.qbit_client.set_auto_management(torrent_hash, False):
                    raise RuntimeError(f"Failed to keep ATM disabled for torrent {torrent_hash[:16]}")
                torrent_info = self.qbit_client.get_torrent_info(torrent_hash)
                if torrent_info and bool(getattr(torrent_info, "auto_tmm", False)):
                    raise RuntimeError(f"ATM still enabled after relocation for torrent {torrent_hash[:16]}")
            self._log(
                f"  auto_tmm_after hash={torrent_hash[:16]} "
                f"enabled={str(bool(getattr(torrent_info, 'auto_tmm', False))).lower()}"
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




    @staticmethod
    def _split_tags(raw_tags: Optional[str]) -> List[str]:
        """Split qB tag CSV into normalized tag names."""
        if not raw_tags:
            return []
        return [tag.strip() for tag in str(raw_tags).split(',') if tag and tag.strip()]

    def _sanitize_plan_live_torrents(self, plan: Dict) -> Dict[str, List]:
        """
        Filter plan torrents to hashes that are currently live in qB and have file lists.

        Normalize plans are generated from catalog snapshots; qB can drift before apply.
        This preflight keeps execution idempotent by trimming stale sibling hashes.

        Returns:
            Mapping of torrent_hash -> preloaded file list for view building.
        """
        requested_raw = [str(h).strip() for h in (plan.get("affected_torrents") or []) if str(h).strip()]
        if not requested_raw:
            raise RuntimeError("Plan has no affected_torrents to execute")

        requested: List[str] = []
        seen_requested: set[str] = set()
        for torrent_hash in requested_raw:
            key = torrent_hash.lower()
            if key in seen_requested:
                continue
            seen_requested.add(key)
            requested.append(torrent_hash)

        info_kept: List[str] = []
        kept: List[str] = []
        kept_lookup: set[str] = set()
        dropped_missing_info: List[str] = []
        no_files: List[str] = []
        files_cache: Dict[str, List] = {}

        for torrent_hash in requested:
            info = self.qbit_client.get_torrent_info(torrent_hash)
            if not info:
                dropped_missing_info.append(torrent_hash)
                continue

            files = self.qbit_client.get_torrent_files(torrent_hash)
            if not files:
                no_files.append(torrent_hash)
            else:
                files_cache[torrent_hash] = files
            info_kept.append(torrent_hash)

        dropped_no_files = 0
        if files_cache:
            # Prefer hashes with confirmed file lists when at least one succeeds.
            kept = [h for h in info_kept if h in files_cache]
            dropped_no_files = len(no_files)
        else:
            # If qB files API is unavailable for all hashes, keep info-confirmed hashes.
            kept = list(info_kept)
            if no_files:
                self._log(
                    "preflight_files_api_unavailable "
                    f"keeping_info_confirmed={len(kept)}",
                    "warning",
                )

        kept_lookup = {h.lower() for h in kept}

        if dropped_missing_info or no_files:
            self._log(
                "preflight_torrent_filter "
                f"requested={len(requested)} kept={len(kept)} "
                f"dropped_missing_info={len(dropped_missing_info)} "
                f"dropped_no_files={dropped_no_files} "
                f"no_files={len(no_files)}",
                "warning",
            )
            if self.debug_qb:
                if dropped_missing_info:
                    self._log(
                        "preflight_missing_info_hashes="
                        + ",".join(h[:16] for h in dropped_missing_info),
                        "warning",
                    )
                if no_files:
                    self._log(
                        "preflight_no_files_hashes="
                        + ",".join(h[:16] for h in no_files),
                        "warning",
                    )

        if not kept:
            raise RuntimeError("No live torrents with file lists remain in plan after qB preflight")

        plan["affected_torrents"] = kept

        plan_torrent_hash = str(plan.get("torrent_hash") or "").strip()
        if not plan_torrent_hash or plan_torrent_hash.lower() not in kept_lookup:
            plan["torrent_hash"] = kept[0]

        view_targets = plan.get("view_targets") or []
        if view_targets:
            filtered_view_targets = []
            for target in view_targets:
                target_hash = str(target.get("torrent_hash") or "").strip()
                if target_hash.lower() in kept_lookup:
                    filtered_view_targets.append(target)
            plan["view_targets"] = filtered_view_targets
            if len(filtered_view_targets) != len(view_targets):
                self._log(
                    "preflight_view_target_filter "
                    f"before={len(view_targets)} after={len(filtered_view_targets)}",
                    "warning",
                )

        return files_cache

    def _build_rehome_provenance_tags(self, plan: Dict) -> List[str]:
        """Compute rehome provenance tags for a completed apply run."""
        direction = plan.get("direction", "demote")
        if direction == "promote":
            source_tag = "rehome_from_pool"
            target_tag = "rehome_to_stash"
        else:
            source_tag = "rehome_from_stash"
            target_tag = "rehome_to_pool"

        date_tag = f"rehome_at_{datetime.now().strftime('%Y%m%d')}"
        tags = ["rehome", source_tag, target_tag, date_tag, "rehome_verify_pending"]
        if bool(plan.get("cleanup_source_deferred")):
            tags.append("rehome_cleanup_source_required")
        return tags


    def _apply_rehome_provenance_tags(self, plan: Dict) -> None:
        """Apply idempotent provenance tags to all affected torrents."""
        torrent_hashes = plan.get("affected_torrents") or []
        if not torrent_hashes:
            return

        desired_tags = self._build_rehome_provenance_tags(plan)
        failures: List[str] = []

        for torrent_hash in torrent_hashes:
            try:
                torrent_info = self.qbit_client.get_torrent_info(torrent_hash)
                existing_tags = self._split_tags(getattr(torrent_info, "tags", "") if torrent_info else "")
                stale_tags = [
                    tag for tag in existing_tags
                    if tag.startswith("rehome_from_")
                    or tag.startswith("rehome_to_")
                    or tag.startswith("rehome_at_")
                    or tag == "rehome_cleanup_source_required"
                    or tag == "rehome_verify_pending"
                    or tag == "rehome_verify_ok"
                    or tag == "rehome_verify_failed"
                ]

                if stale_tags and hasattr(self.qbit_client, "remove_tags"):
                    if not self.qbit_client.remove_tags(torrent_hash, stale_tags):
                        msg = f"rehome_tag_remove_failed hash={torrent_hash[:16]} tags={','.join(stale_tags)}"
                        failures.append(msg)
                        self._log(msg, "warning")

                if hasattr(self.qbit_client, "add_tags"):
                    if not self.qbit_client.add_tags(torrent_hash, desired_tags):
                        msg = f"rehome_tag_add_failed hash={torrent_hash[:16]} tags={','.join(desired_tags)}"
                        failures.append(msg)
                        self._log(msg, "warning")
                    else:
                        self._log(
                            f"rehome_tag_update hash={torrent_hash[:16]} tags={','.join(desired_tags)}"
                        )
                else:
                    msg = f"rehome_tag_update_skipped hash={torrent_hash[:16]} reason=no_add_tags_api"
                    failures.append(msg)
                    self._log(msg, "warning")
            except Exception as e:
                msg = f"rehome_tag_update_failed hash={torrent_hash[:16]} error={e}"
                failures.append(msg)
                self._log(msg, "warning")

        if failures and self.tag_strict:
            raise RuntimeError(
                f"rehome tag update failed in strict mode ({len(failures)} issues): {failures[0]}"
            )


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

        preloaded_files = self._sanitize_plan_live_torrents(plan)

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
                self._execute_promote_reuse(
                    plan,
                    spot_check=spot_check,
                    preloaded_files=preloaded_files,
                )
            elif decision == 'REUSE':
                self._execute_reuse(
                    plan,
                    spot_check=spot_check,
                    preloaded_files=preloaded_files,
                )
            elif decision == 'MOVE':
                self._execute_move(
                    plan,
                    spot_check=spot_check,
                    preloaded_files=preloaded_files,
                )
            else:
                raise RuntimeError(f"Unknown decision: {decision}")

            self._apply_cleanup(plan, cleanup_source_views, cleanup_empty_dirs, cleanup_duplicate_payload)
            self._sync_catalog_after_rehome(plan)
            self._apply_rehome_provenance_tags(plan)
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
                target_path = plan.get("target_path")
                target_device_id = plan.get("target_device_id")
                source_device_id = plan.get("source_device_id")
                same_device_reuse = (
                    target_path
                    and target_device_id is not None
                    and source_device_id is not None
                    and int(target_device_id) == int(source_device_id)
                )
                target_payload_row = conn.execute(
                    """
                    SELECT payload_id
                    FROM payloads
                    WHERE payload_hash = ? AND device_id = ? AND status = 'complete'
                      AND (? IS NULL OR root_path = ?)
                    ORDER BY CASE WHEN root_path = ? THEN 0 ELSE 1 END, payload_id
                    LIMIT 1
                    """,
                    (
                        plan.get("payload_hash"),
                        plan.get("target_device_id"),
                        target_path,
                        target_path,
                        target_path,
                    ),
                ).fetchone()

                target_payload_id: Optional[int] = None
                if target_payload_row:
                    target_payload_id = int(target_payload_row[0])
                elif same_device_reuse and plan.get("payload_id") is not None:
                    # Normalization case: target path can already exist on disk while
                    # catalog still points to source payload row on the same device.
                    source_payload_row = conn.execute(
                        """
                        SELECT payload_id
                        FROM payloads
                        WHERE payload_id = ? AND payload_hash = ? AND device_id = ? AND status = 'complete'
                        LIMIT 1
                        """,
                        (
                            int(plan.get("payload_id")),
                            plan.get("payload_hash"),
                            int(target_device_id),
                        ),
                    ).fetchone()
                    if source_payload_row:
                        target_payload_id = int(source_payload_row[0])

                if target_payload_id is None:
                    raise RuntimeError("Target payload not found for catalog sync")

                # Same-device REUSE may intentionally "re-point" the canonical payload
                # root to an existing target view path (normalization flow).
                if same_device_reuse:
                    conn.execute(
                        """
                        UPDATE payloads
                        SET root_path = ?, updated_at = julianday('now')
                        WHERE payload_id = ?
                        """,
                        (target_path, target_payload_id),
                    )

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

                self._sync_files_catalog_for_reuse_cleanup(conn, plan)

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

                self._sync_files_catalog_for_move(conn, plan)

            conn.commit()
        finally:
            conn.close()

    def _sync_files_catalog_for_reuse_cleanup(self, conn: sqlite3.Connection, plan: Dict) -> None:
        """
        Mark cleaned source payload paths as deleted in files_<source_device>.

        REUSE plans can remove source payload roots during cleanup without a follow-up
        scan. This reconciles source file rows immediately when those roots are gone.
        """
        source_device_id = plan.get("source_device_id")
        target_path = Path(plan.get("target_path") or "").resolve() if plan.get("target_path") else None
        if source_device_id is None:
            return

        source_table = ensure_files_table(conn.cursor(), source_device_id)
        source_mount, source_preferred = self._get_device_mount_info(conn, source_device_id)

        roots_to_check: List[Path] = []
        group = plan.get("payload_group") or []
        for entry in group:
            root = Path(entry.get("root_path") or "").resolve()
            if not root:
                continue
            if target_path and root == target_path:
                continue
            roots_to_check.append(root)

        if not roots_to_check and plan.get("source_path"):
            roots_to_check.append(Path(plan["source_path"]).resolve())

        seen: set[str] = set()
        for root in roots_to_check:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            if root.exists():
                continue

            rel_root = self._to_device_relpath(root, source_mount, source_preferred)
            if rel_root is None:
                continue

            pattern = f"{rel_root}/%"
            conn.execute(
                f"""
                UPDATE {source_table}
                SET status = 'deleted',
                    last_seen_at = CURRENT_TIMESTAMP,
                    last_modified_at = CURRENT_TIMESTAMP
                WHERE status = 'active' AND (path = ? OR path LIKE ?)
                """,
                (rel_root, pattern),
            )

    def _sync_files_catalog_for_move(self, conn: sqlite3.Connection, plan: Dict) -> None:
        """
        Reconcile per-device file rows after MOVE without requiring a follow-up scan.

        This keeps catalog state aligned when a payload has already been moved on disk
        before a rehome apply run is executed (idempotent recovery path).
        """
        source_device_id = plan.get("source_device_id")
        target_device_id = plan.get("target_device_id")
        if source_device_id is None or target_device_id is None:
            return

        source_table = ensure_files_table(conn.cursor(), source_device_id)
        target_table = ensure_files_table(conn.cursor(), target_device_id)

        source_mount, source_preferred = self._get_device_mount_info(conn, source_device_id)
        target_mount, target_preferred = self._get_device_mount_info(conn, target_device_id)

        source_path = Path(plan["source_path"])
        target_path = Path(plan["target_path"])

        source_rel_root = self._to_device_relpath(source_path, source_mount, source_preferred)
        target_rel_root = self._to_device_relpath(target_path, target_mount, target_preferred)
        if source_rel_root is None or target_rel_root is None:
            self._log("catalog_sync move skipped reason=unmapped_paths", "warning")
            return

        pattern = f"{source_rel_root}/%"
        source_rows = conn.execute(
            f"""
            SELECT path, size, mtime, quick_hash, sha1, sha256, hash_source, inode,
                   first_seen_at, discovered_under
            FROM {source_table}
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
            ORDER BY path
            """,
            (source_rel_root, pattern),
        ).fetchall()

        conn.execute(
            f"""
            UPDATE {source_table}
            SET status = 'deleted',
                last_seen_at = CURRENT_TIMESTAMP,
                last_modified_at = CURRENT_TIMESTAMP
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
            """,
            (source_rel_root, pattern),
        )

        if not source_rows:
            self._log("catalog_sync move source_rows=0", "warning")
            return

        for row in source_rows:
            src_rel_path = row[0]
            if src_rel_path == source_rel_root:
                rel_suffix = ""
            elif src_rel_path.startswith(source_rel_root + "/"):
                rel_suffix = src_rel_path[len(source_rel_root) + 1:]
            else:
                continue

            if rel_suffix:
                target_rel_path = (
                    rel_suffix if target_rel_root == "." else f"{target_rel_root}/{rel_suffix}"
                )
                target_abs_path = target_path / rel_suffix
            else:
                target_rel_path = target_rel_root
                target_abs_path = target_path

            size, mtime, quick_hash, sha1, sha256, hash_source, inode, first_seen_at, _ = row[1:]
            if target_abs_path.exists() and target_abs_path.is_file():
                stat = target_abs_path.stat()
                size = stat.st_size
                mtime = stat.st_mtime
                inode = stat.st_ino

            conn.execute(
                f"""
                INSERT INTO {target_table}
                    (path, size, mtime, quick_hash, sha1, sha256, hash_source,
                     inode, first_seen_at, last_seen_at, last_modified_at,
                     status, discovered_under)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP),
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'active', ?)
                ON CONFLICT(path) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    quick_hash = COALESCE(excluded.quick_hash, {target_table}.quick_hash),
                    sha1 = COALESCE(excluded.sha1, {target_table}.sha1),
                    sha256 = COALESCE(excluded.sha256, {target_table}.sha256),
                    hash_source = COALESCE(excluded.hash_source, {target_table}.hash_source),
                    inode = excluded.inode,
                    status = 'active',
                    discovered_under = excluded.discovered_under,
                    last_seen_at = CURRENT_TIMESTAMP,
                    last_modified_at = CURRENT_TIMESTAMP
                """,
                (
                    target_rel_path,
                    size,
                    mtime,
                    quick_hash,
                    sha1,
                    sha256,
                    hash_source,
                    inode,
                    first_seen_at,
                    str(target_path),
                ),
            )

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

    def _execute_promote_reuse(
        self,
        plan: Dict,
        spot_check: int = 0,
        *,
        preloaded_files: Optional[Dict[str, List]] = None,
    ) -> None:
        """
        Execute a PROMOTE_REUSE plan (pool → stash).

        Steps:
        1. Verify existing payload on stash
        2. For each sibling torrent:
           a. Build stash-side view (logical)
           b. Relocate torrent in qBittorrent
           c. Verify torrent can access files
        """
        import time

        t_start = time.monotonic()
        phase_times: Dict[str, float] = {}
        target_path = Path(plan['target_path'])

        # 1. Verify existing payload on stash
        t0 = time.monotonic()
        self._log(f"step=verify_stash_payload path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError(f"Stash payload file count mismatch at {target_path}")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError(f"Stash payload total bytes mismatch at {target_path}")

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)
        phase_times["verify"] = time.monotonic() - t0

        # Build views (if mapping provided)
        t0 = time.monotonic()
        self._log("step=build_views")
        self._build_views(
            target_path,
            plan.get("view_targets") or [],
            plan,
            preloaded_files=preloaded_files,
        )
        phase_times["build_views"] = time.monotonic() - t0

        t0 = time.monotonic()
        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)
        finally:
            conn.close()
        phase_times["build_relocations"] = time.monotonic() - t0

        # Relocate all torrents atomically
        t0 = time.monotonic()
        self._log("step=relocate_siblings")
        self._relocate_torrents_atomic(relocations)
        phase_times["relocate"] = time.monotonic() - t0

        phase_times["total"] = time.monotonic() - t_start
        self._log(
            "phase_timing_s "
            + " ".join(f"{k}={v:.1f}" for k, v in phase_times.items())
        )
        self._log("PROMOTE_REUSE execution complete", "success")

    def _execute_reuse(
        self,
        plan: Dict,
        spot_check: int = 0,
        *,
        preloaded_files: Optional[Dict[str, List]] = None,
    ) -> None:
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
        import time

        t_start = time.monotonic()
        phase_times: Dict[str, float] = {}
        target_path = Path(plan['target_path'])
        source_path = Path(plan['source_path'])

        # 1. Verify existing payload on pool
        t0 = time.monotonic()
        self._log(f"step=verify_pool_payload path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError(f"Pool payload file count mismatch at {target_path}")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError(f"Pool payload total bytes mismatch at {target_path}")

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)
        phase_times["verify"] = time.monotonic() - t0

        # Build views (if mapping provided)
        t0 = time.monotonic()
        self._log("step=build_views")
        self._build_views(
            target_path,
            plan.get("view_targets") or [],
            plan,
            preloaded_files=preloaded_files,
        )
        phase_times["build_views"] = time.monotonic() - t0

        t0 = time.monotonic()
        conn = self._get_db_connection()
        try:
            relocations = self._build_relocations(conn, plan)
        finally:
            conn.close()
        phase_times["build_relocations"] = time.monotonic() - t0

        # Relocate all torrents atomically
        t0 = time.monotonic()
        self._log("step=relocate_siblings")
        self._relocate_torrents_atomic(relocations)
        phase_times["relocate"] = time.monotonic() - t0

        # 3. Cleanup stash-side views
        t0 = time.monotonic()
        self._log(f"step=cleanup_stash path={source_path} relocated={len(relocations)}")
        self._log(f"  MANUAL_ACTION_REQUIRED: Verify torrents work, then delete {source_path}", "warning")
        phase_times["cleanup_notice"] = time.monotonic() - t0

        phase_times["total"] = time.monotonic() - t_start
        self._log(
            "phase_timing_s "
            + " ".join(f"{k}={v:.1f}" for k, v in phase_times.items())
        )
        self._log("REUSE execution complete", "success")

    def _execute_move(
        self,
        plan: Dict,
        spot_check: int = 0,
        *,
        preloaded_files: Optional[Dict[str, List]] = None,
    ) -> None:
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
        import time

        t_start = time.monotonic()
        phase_times: Dict[str, float] = {}
        source_path = Path(plan['source_path'])
        target_path = Path(plan['target_path'])

        moved_payload = False
        move_strategy = "rename"

        # 1. Verify source / idempotent target
        t0 = time.monotonic()
        self._log(f"step=verify_source path={source_path}")
        if source_path.exists():
            if not self._verify_file_count(source_path, plan['file_count']):
                raise RuntimeError("Source file count mismatch")
            if not self._verify_total_bytes(source_path, plan['total_bytes']):
                raise RuntimeError("Source total bytes mismatch")

            is_cross_fs = self._is_cross_filesystem(source_path, target_path.parent)
            if target_path.exists() and not is_cross_fs:
                raise RuntimeError(f"Target path already exists before move: {target_path}")

            # 2. Move payload root
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if is_cross_fs:
                    move_strategy = "rsync_copy"
                    self._copy_with_rsync_progress(source_path, target_path)
                else:
                    self._log(f"step=move_payload method=rename source={source_path} target={target_path}")
                    shutil.move(str(source_path), str(target_path))
                moved_payload = True
            except Exception as e:
                raise RuntimeError(f"Failed to move payload: {e}")
        else:
            if not target_path.exists():
                raise RuntimeError(f"Source path does not exist: {source_path}")
            self._log("step=verify_source source_missing=true mode=idempotent_reconcile", "warning")
        phase_times["verify_and_move"] = time.monotonic() - t0

        # 3. Verify target
        t0 = time.monotonic()
        self._log(f"step=verify_target path={target_path}")
        if not self._verify_file_count(target_path, plan['file_count']):
            raise RuntimeError("Target file count mismatch after move")
        if not self._verify_total_bytes(target_path, plan['total_bytes']):
            raise RuntimeError("Target total bytes mismatch after move")

        # Spot-check (optional)
        self._spot_check_payload(target_path, plan["target_device_id"], spot_check)
        phase_times["verify_target_and_spotcheck"] = time.monotonic() - t0

        # 4. Build views and relocate atomically
        try:
            t0 = time.monotonic()
            self._log("step=build_views")
            self._build_views(
                target_path,
                plan.get("view_targets") or [],
                plan,
                preloaded_files=preloaded_files,
            )
            phase_times["build_views"] = time.monotonic() - t0

            t0 = time.monotonic()
            conn = self._get_db_connection()
            try:
                relocations = self._build_relocations(conn, plan)
            finally:
                conn.close()
            phase_times["build_relocations"] = time.monotonic() - t0

            t0 = time.monotonic()
            self._log("step=relocate_siblings")
            self._relocate_torrents_atomic(relocations)
            phase_times["relocate"] = time.monotonic() - t0
        except Exception as e:
            # Rollback: restore source state if sibling relocation fails
            self._log("relocation_failed rolling_back_payload", "error")
            if moved_payload:
                if move_strategy == "rename":
                    try:
                        shutil.move(str(target_path), str(source_path))
                        self._log(f"  Rolled back payload to {source_path}", "warning")
                    except Exception as rollback_error:
                        self._log(f"  ROLLBACK FAILED: {rollback_error}", "error")
                else:
                    # rsync strategy leaves source in place until relocation succeeds.
                    if target_path.exists():
                        try:
                            if target_path.is_dir():
                                shutil.rmtree(target_path)
                            else:
                                target_path.unlink()
                            self._log(f"  Removed copied target after failure: {target_path}", "warning")
                        except Exception as rollback_error:
                            self._log(f"  ROLLBACK FAILED: {rollback_error}", "error")
            else:
                self._log("  rollback skipped reason=idempotent_mode_no_move", "warning")
            self._rollback_partial_target_views(plan)
            raise

        # For rsync-based cross-filesystem moves, remove source only after relocation succeeded.
        cleanup_source_status = "deleted"
        plan["cleanup_source_deferred"] = False
        plan.pop("cleanup_source_deferred_path", None)
        t0 = time.monotonic()
        if move_strategy == "rsync_copy" and source_path.exists():
            self._log(f"step=cleanup_source_after_rsync path={source_path}")
            try:
                self._delete_path(source_path)
            except Exception as e:
                if self._is_permission_error(e):
                    self._log(
                        f"cleanup_source_permission_denied path={source_path} error={e}",
                        "warning",
                    )
                    repaired = self._repair_permissions_for_cleanup(source_path)
                    if repaired:
                        try:
                            self._delete_path(source_path)
                            self._log(
                                f"cleanup_source_after_rsync recovered=true path={source_path}",
                                "success",
                            )
                        except Exception as retry_exc:
                            cleanup_source_status = "deferred"
                            plan["cleanup_source_deferred"] = True
                            plan["cleanup_source_deferred_path"] = str(source_path)
                            self._log(
                                f"cleanup_source_deferred path={source_path} error={retry_exc}",
                                "warning",
                            )
                    else:
                        cleanup_source_status = "deferred"
                        plan["cleanup_source_deferred"] = True
                        plan["cleanup_source_deferred_path"] = str(source_path)
                        self._log(
                            f"cleanup_source_deferred path={source_path} "
                            "reason=permission_repair_failed",
                            "warning",
                        )
                else:
                    raise RuntimeError(f"Failed to remove source after rsync move: {e}") from e
        phase_times["cleanup"] = time.monotonic() - t0

        # 5. Verify source is removed
        t0 = time.monotonic()
        self._log(f"step=verify_source_removed path={source_path}")
        if source_path.exists():
            if cleanup_source_status == "deferred":
                self._log(
                    f"cleanup_required=true path={source_path}",
                    "warning",
                )
            else:
                raise RuntimeError(f"Source still exists after move: {source_path}")
        self._log(f"cleanup_source_status={cleanup_source_status}")
        phase_times["verify_source_removed"] = time.monotonic() - t0
        phase_times["total"] = time.monotonic() - t_start
        self._log(
            "phase_timing_s "
            + " ".join(f"{k}={v:.1f}" for k, v in phase_times.items())
        )

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

        conn = self._get_db_connection(read_only=dry_run)
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
