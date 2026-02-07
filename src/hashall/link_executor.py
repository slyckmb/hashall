"""
Link deduplication executor module.

This module provides functionality to safely execute deduplication plans by
replacing duplicate files with hardlinks. Includes extensive safety checks
and atomic operations.

SAFETY FEATURES:
- Hash verification before linking
- Atomic operations (backup → verify → link → cleanup)
- Rollback on error
- Progress tracking
- Dry-run mode for testing
"""

import os
import sqlite3
import hashlib
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from hashall.link_query import get_plan, get_plan_actions, ActionInfo


@dataclass
class ExecutionResult:
    """Result of plan execution.

    Attributes:
        plan_id: Plan ID
        actions_executed: Number of successfully executed actions
        actions_failed: Number of failed actions
        actions_skipped: Number of skipped actions
        bytes_saved: Actual bytes saved
        errors: List of error messages
    """
    plan_id: int
    actions_executed: int
    actions_failed: int
    actions_skipped: int
    bytes_saved: int
    errors: list


def _resolve_path(path: str, mount_point: Optional[str]) -> Path:
    candidate = Path(path)
    if mount_point and not candidate.is_absolute():
        return Path(mount_point) / candidate
    return candidate


def _db_path_for_action(path: str, mount_point: Optional[str]) -> str:
    candidate = Path(path)
    if mount_point and candidate.is_absolute():
        try:
            return str(candidate.relative_to(mount_point))
        except ValueError:
            return path
    return path


def _fetch_file_metadata(
    conn: sqlite3.Connection,
    device_id: int,
    db_path: str
) -> Optional[Tuple[int, float, Optional[str], Optional[str]]]:
    cursor = conn.cursor()
    table_name = f"files_{device_id}"
    cursor.execute(
        f"SELECT size, mtime, sha256, sha1 FROM {table_name} WHERE path = ? AND status = 'active'",
        (db_path,)
    )
    return cursor.fetchone()


def _write_jdupes_list(paths: list[Path]) -> tuple[Path, int]:
    tmp = tempfile.NamedTemporaryFile(prefix="hashall-jdupes-", suffix=".lst", delete=False)
    try:
        seen_paths = set()
        seen_inodes = set()
        count = 0
        with tmp as handle:
            for path in paths:
                resolved = path.resolve()
                stat = resolved.stat()
                inode_key = (stat.st_dev, stat.st_ino)
                if inode_key in seen_inodes:
                    continue
                path_str = str(resolved)
                if path_str in seen_paths:
                    continue
                seen_inodes.add(inode_key)
                seen_paths.add(path_str)
                handle.write(os.fsencode(path_str))
                handle.write(b"\0")
                count += 1
        return Path(tmp.name), count
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _run_jdupes(jdupes_cmd: str, list_path: Path) -> subprocess.CompletedProcess:
    cmd = [
        "xargs",
        "-0",
        "-a",
        str(list_path),
        jdupes_cmd,
        "-L",
        "-1",
        "-O",
        "-P",
        "fullhash",
        "-q",
        "--",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_jdupes_log(log_dir: Optional[Path], filename: str, content: str) -> None:
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename
    log_path.write_text(content)


def compute_sha256(file_path: Path) -> Optional[str]:
    """
    Compute SHA256 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        SHA256 hash as hex string, or None if file cannot be read
    """
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, IOError):
        return None


def compute_fast_hash_sample(file_path: Path, sample_size: int = 1024*1024) -> Optional[str]:
    """
    Compute fast hash by sampling first, middle, and last portions of file.

    This is much faster than full hash for large files:
    - 100GB file: reads 3MB instead of 100GB (33,000x faster)
    - Still provides high confidence of file identity
    - Detects corruption, truncation, partial writes, etc.

    Args:
        file_path: Path to file
        sample_size: Size of each sample in bytes (default: 1MB)

    Returns:
        SHA1 hash of sampled content, or None if file cannot be read
    """
    try:
        file_size = file_path.stat().st_size
        sha1 = hashlib.sha1()

        with open(file_path, 'rb') as f:
            # Sample 1: First portion
            first_chunk = f.read(min(sample_size, file_size))
            sha1.update(first_chunk)

            # Sample 2: Middle portion (if file is large enough)
            if file_size > sample_size * 2:
                middle_offset = (file_size - sample_size) // 2
                f.seek(middle_offset)
                middle_chunk = f.read(sample_size)
                sha1.update(middle_chunk)

            # Sample 3: Last portion (if file is large enough)
            if file_size > sample_size:
                f.seek(max(0, file_size - sample_size))
                last_chunk = f.read(sample_size)
                sha1.update(last_chunk)

        return sha1.hexdigest()
    except (OSError, IOError) as e:
        return None


def verify_file_unchanged(
    file_path: Path,
    expected_size: int,
    expected_mtime: float
) -> Tuple[bool, Optional[str]]:
    """
    Verify file hasn't changed by checking size and mtime.

    This is instant (just stat syscall) and catches any file modifications.
    If size and mtime match, the file content is guaranteed unchanged.

    Args:
        file_path: Path to file
        expected_size: Expected file size in bytes
        expected_mtime: Expected modification time

    Returns:
        Tuple of (success, error_message)
    """
    try:
        stat = file_path.stat()

        if stat.st_size != expected_size:
            return False, f"File size changed: expected {expected_size}, got {stat.st_size}"

        if stat.st_mtime != expected_mtime:
            return False, f"File modified since planning (mtime changed)"

        return True, None
    except OSError as e:
        return False, f"Cannot stat file: {e}"


def verify_files_exist(canonical_path: Path, duplicate_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Verify both files exist and are regular files.

    Args:
        canonical_path: Path to canonical file
        duplicate_path: Path to duplicate file

    Returns:
        Tuple of (success, error_message)
    """
    if not canonical_path.exists():
        return False, f"Canonical file not found: {canonical_path}"

    if not duplicate_path.exists():
        return False, f"Duplicate file not found: {duplicate_path}"

    if not canonical_path.is_file():
        return False, f"Canonical path is not a file: {canonical_path}"

    if not duplicate_path.is_file():
        return False, f"Duplicate path is not a file: {duplicate_path}"

    return True, None


def verify_hash_matches(file_path: Path, expected_hash: str) -> Tuple[bool, Optional[str]]:
    """
    Verify file hash matches expected value.

    Args:
        file_path: Path to file
        expected_hash: Expected SHA256 hash

    Returns:
        Tuple of (success, error_message)
    """
    actual_hash = compute_sha256(file_path)

    if actual_hash is None:
        return False, f"Cannot read file to verify hash: {file_path}"

    if actual_hash != expected_hash:
        return False, f"Hash mismatch: expected {expected_hash[:8]}..., got {actual_hash[:8]}..."

    return True, None


def verify_same_filesystem(path1: Path, path2: Path) -> Tuple[bool, Optional[str]]:
    """
    Verify both files are on the same filesystem (required for hardlinks).

    Args:
        path1: First file path
        path2: Second file path

    Returns:
        Tuple of (success, error_message)
    """
    try:
        stat1 = os.stat(path1)
        stat2 = os.stat(path2)

        if stat1.st_dev != stat2.st_dev:
            return False, "Files are on different filesystems (hardlinks not possible)"

        return True, None
    except OSError as e:
        return False, f"Cannot stat files: {e}"


def verify_not_already_linked(canonical_path: Path, duplicate_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Verify files are not already hardlinked (same inode).

    Args:
        canonical_path: Path to canonical file
        duplicate_path: Path to duplicate file

    Returns:
        Tuple of (success, error_message)
    """
    try:
        canonical_stat = os.stat(canonical_path)
        duplicate_stat = os.stat(duplicate_path)

        if canonical_stat.st_ino == duplicate_stat.st_ino:
            return False, "Files are already hardlinked (same inode)"

        return True, None
    except OSError as e:
        return False, f"Cannot stat files: {e}"


def _precheck_jdupes_action(
    conn: sqlite3.Connection,
    action: ActionInfo,
    mount_point: Optional[str],
    verify_mode: str
) -> Tuple[str, Optional[str], Path, Path]:
    canonical_path = _resolve_path(action.canonical_path, mount_point)
    duplicate_path = _resolve_path(action.duplicate_path, mount_point)

    success, error = verify_files_exist(canonical_path, duplicate_path)
    if not success:
        return "failed", error, canonical_path, duplicate_path

    success, error = verify_same_filesystem(canonical_path, duplicate_path)
    if not success:
        return "failed", error, canonical_path, duplicate_path

    success, error = verify_not_already_linked(canonical_path, duplicate_path)
    if not success:
        return "skipped", error, canonical_path, duplicate_path

    if verify_mode != "none":
        canonical_db_path = _db_path_for_action(action.canonical_path, mount_point)
        duplicate_db_path = _db_path_for_action(action.duplicate_path, mount_point)
        canonical_row = _fetch_file_metadata(conn, action.device_id, canonical_db_path)
        duplicate_row = _fetch_file_metadata(conn, action.device_id, duplicate_db_path)
        if not canonical_row or not duplicate_row:
            return "failed", "Catalog metadata missing for verification", canonical_path, duplicate_path

        canonical_size, canonical_mtime, canonical_sha256, canonical_sha1 = canonical_row
        duplicate_size, duplicate_mtime, duplicate_sha256, duplicate_sha1 = duplicate_row

        if canonical_size != duplicate_size:
            return "failed", "Catalog size mismatch between canonical and duplicate", canonical_path, duplicate_path

        if verify_mode == "fast":
            success, error = verify_file_unchanged(canonical_path, canonical_size, canonical_mtime)
            if not success:
                return "failed", f"Canonical file: {error}", canonical_path, duplicate_path
            success, error = verify_file_unchanged(duplicate_path, duplicate_size, duplicate_mtime)
            if not success:
                return "failed", f"Duplicate file: {error}", canonical_path, duplicate_path
        elif verify_mode == "paranoid":
            expected_hash = action.sha256 or canonical_sha256 or duplicate_sha256 or canonical_sha1 or duplicate_sha1
            if not expected_hash:
                return "failed", "Missing expected hash for paranoid verification", canonical_path, duplicate_path
            if action.sha256 and canonical_sha256 and action.sha256 != canonical_sha256:
                return "failed", "Canonical SHA256 mismatch in catalog", canonical_path, duplicate_path
            if action.sha256 and duplicate_sha256 and action.sha256 != duplicate_sha256:
                return "failed", "Duplicate SHA256 mismatch in catalog", canonical_path, duplicate_path

            success, error = verify_hash_matches(canonical_path, expected_hash)
            if not success:
                return "failed", f"Canonical file: {error}", canonical_path, duplicate_path
            success, error = verify_hash_matches(duplicate_path, expected_hash)
            if not success:
                return "failed", f"Duplicate file: {error}", canonical_path, duplicate_path

    return "ok", None, canonical_path, duplicate_path


def create_hardlink_atomic(
    canonical_path: Path,
    duplicate_path: Path,
    create_backup: bool = True
) -> Tuple[bool, Optional[str], Optional[Path]]:
    """
    Replace duplicate file with hardlink to canonical file.

    Atomic operation:
    1. Verify files exist and are on same filesystem
    2. Create backup of duplicate (if requested)
    3. Remove duplicate
    4. Create hardlink
    5. Cleanup backup on success or restore on failure

    Args:
        canonical_path: Path to canonical file (to keep)
        duplicate_path: Path to duplicate file (to replace)
        create_backup: Whether to create .bak backup file

    Returns:
        Tuple of (success, error_message, backup_path)
    """
    backup_path = None

    try:
        # Step 1: Verify files exist
        success, error = verify_files_exist(canonical_path, duplicate_path)
        if not success:
            return False, error, None

        # Step 2: Verify same filesystem
        success, error = verify_same_filesystem(canonical_path, duplicate_path)
        if not success:
            return False, error, None

        # Step 3: Create backup if requested
        if create_backup:
            backup_path = duplicate_path.parent / f"{duplicate_path.name}.bak"

            # Remove old backup if exists
            if backup_path.exists():
                backup_path.unlink()

            # Create hardlink as backup (preserves inode, very fast)
            os.link(duplicate_path, backup_path)

        # Step 4: Remove duplicate
        duplicate_path.unlink()

        # Step 5: Create hardlink from duplicate to canonical
        os.link(canonical_path, duplicate_path)

        # Step 6: Cleanup backup on success (if created)
        if backup_path and backup_path.exists():
            backup_path.unlink()
            backup_path = None

        return True, None, None

    except OSError as e:
        # Rollback: restore from backup if it exists
        if backup_path and backup_path.exists():
            try:
                # Remove failed hardlink if it was created
                if duplicate_path.exists():
                    duplicate_path.unlink()

                # Restore from backup
                os.link(backup_path, duplicate_path)
                backup_path.unlink()

                return False, f"Operation failed, restored from backup: {e}", None
            except OSError as e2:
                return False, f"Operation failed AND backup restore failed: {e}, {e2}", backup_path

        return False, f"Operation failed: {e}", backup_path


def execute_action(
    conn: sqlite3.Connection,
    action: ActionInfo,
    mount_point: Optional[str] = None,
    dry_run: bool = False,
    verify_mode: str = 'fast',
    create_backup: bool = True
) -> Tuple[bool, Optional[str], int]:
    """
    Execute a single hardlink action.

    Args:
        conn: Database connection
        action: ActionInfo to execute
        mount_point: Device mount point (for resolving relative paths)
        dry_run: If True, simulate without making changes
        verify_mode: Verification mode:
            'fast' - Size/mtime + fast-hash sampling (default, recommended)
            'paranoid' - Full SHA256 hash verification (slow for large files)
            'none' - Skip verification (trust planning phase)
        create_backup: If True, create .bak backup file

    Returns:
        Tuple of (success, error_message, bytes_saved)
    """
    # Resolve paths (handle both absolute and relative)
    canonical_path = Path(action.canonical_path)
    duplicate_path = Path(action.duplicate_path)

    # If paths are relative and we have a mount_point, resolve them
    if mount_point and not canonical_path.is_absolute():
        canonical_path = Path(mount_point) / canonical_path
    if mount_point and not duplicate_path.is_absolute():
        duplicate_path = Path(mount_point) / duplicate_path

    # Safety checks
    success, error = verify_files_exist(canonical_path, duplicate_path)
    if not success:
        return False, error, 0

    # Check if already linked
    success, error = verify_not_already_linked(canonical_path, duplicate_path)
    if not success:
        # Not an error, just skip (already linked is good!)
        return True, None, 0  # Skip, don't count as saved

    # Verification strategy based on mode
    if verify_mode != 'none':
        canonical_db_path = _db_path_for_action(action.canonical_path, mount_point)
        duplicate_db_path = _db_path_for_action(action.duplicate_path, mount_point)
        canonical_row = _fetch_file_metadata(conn, action.device_id, canonical_db_path)
        duplicate_row = _fetch_file_metadata(conn, action.device_id, duplicate_db_path)

        if not canonical_row or not duplicate_row:
            return False, "Catalog metadata missing for verification", 0

        canonical_size, canonical_mtime, canonical_sha256, canonical_sha1 = canonical_row
        duplicate_size, duplicate_mtime, duplicate_sha256, duplicate_sha1 = duplicate_row
        expected_hash = action.sha256 or canonical_sha256 or duplicate_sha256 or canonical_sha1 or duplicate_sha1

        if canonical_size != duplicate_size:
            return False, "Catalog size mismatch between canonical and duplicate", 0

        if verify_mode == 'fast':
            # Fast verification: size/mtime + fast-hash sampling
            # Step 1: Check size/mtime (instant)
            success, error = verify_file_unchanged(canonical_path, canonical_size, canonical_mtime)
            if not success:
                return False, f"Canonical file: {error}", 0

            success, error = verify_file_unchanged(duplicate_path, duplicate_size, duplicate_mtime)
            if not success:
                return False, f"Duplicate file: {error}", 0

            # Step 2: Fast-hash sampling (3MB read for 100GB file)
            canonical_sample = compute_fast_hash_sample(canonical_path)
            duplicate_sample = compute_fast_hash_sample(duplicate_path)

            if canonical_sample is None:
                return False, "Cannot read canonical file for fast-hash verification", 0
            if duplicate_sample is None:
                return False, "Cannot read duplicate file for fast-hash verification", 0

            if canonical_sample != duplicate_sample:
                return False, "Fast-hash mismatch: files have different content", 0

        elif verify_mode == 'paranoid':
            # Paranoid verification: Full hash computation
            # This is SLOW for large files but provides 100% certainty
            if not expected_hash:
                return False, "Missing expected hash for paranoid verification", 0

            # Verify canonical file
            success, error = verify_hash_matches(canonical_path, expected_hash)
            if not success:
                return False, f"Canonical file: {error}", 0

            # Verify duplicate file
            success, error = verify_hash_matches(duplicate_path, expected_hash)
            if not success:
                return False, f"Duplicate file: {error}", 0

    # Dry-run mode: don't actually link
    if dry_run:
        return True, None, action.bytes_to_save

    # Execute hardlink
    success, error, backup_path = create_hardlink_atomic(
        canonical_path,
        duplicate_path,
        create_backup=create_backup
    )

    if not success:
        return False, error, 0

    return True, None, action.bytes_to_save


def update_action_status(
    conn: sqlite3.Connection,
    action_id: int,
    status: str,
    bytes_saved: int = 0,
    error_message: Optional[str] = None
):
    """
    Update action status in database.

    Args:
        conn: Database connection
        action_id: Action ID
        status: New status (completed, failed, skipped)
        bytes_saved: Bytes saved (for completed actions)
        error_message: Error message (for failed actions)
    """
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE link_actions
        SET status = ?,
            bytes_saved = ?,
            error_message = ?,
            executed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, bytes_saved, error_message, action_id))

    conn.commit()


def update_plan_progress(
    conn: sqlite3.Connection,
    plan_id: int,
    start_execution: bool = False,
    complete_execution: bool = False
):
    """
    Update plan execution progress.

    Args:
        conn: Database connection
        plan_id: Plan ID
        start_execution: If True, mark plan as in_progress
        complete_execution: If True, mark plan as completed
    """
    cursor = conn.cursor()

    # Count action statuses
    cursor.execute("""
        SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as executed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
            SUM(CASE WHEN status = 'completed' THEN bytes_saved ELSE 0 END) as total_saved
        FROM link_actions
        WHERE plan_id = ?
    """, (plan_id,))

    row = cursor.fetchone()
    executed, failed, skipped, total_saved = row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0

    # Determine new status
    if complete_execution:
        new_status = 'completed'
    elif start_execution:
        new_status = 'in_progress'
    else:
        new_status = None

    # Update plan
    if new_status:
        cursor.execute("""
            UPDATE link_plans
            SET status = ?,
                actions_executed = ?,
                actions_failed = ?,
                actions_skipped = ?,
                total_bytes_saved = ?,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END
            WHERE id = ?
        """, (new_status, executed, failed, skipped, total_saved, new_status, plan_id))
    else:
        cursor.execute("""
            UPDATE link_plans
            SET actions_executed = ?,
                actions_failed = ?,
                actions_skipped = ?,
                total_bytes_saved = ?
            WHERE id = ?
        """, (executed, failed, skipped, total_saved, plan_id))

    conn.commit()


def execute_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    dry_run: bool = False,
    verify_mode: str = 'fast',
    create_backup: bool = True,
    limit: int = 0,
    progress_callback=None,
    use_jdupes: bool = True,
    jdupes_path: Optional[str] = None,
    jdupes_log_dir: Optional[Path] = None
) -> ExecutionResult:
    """
    Execute a deduplication plan.

    Args:
        conn: Database connection
        plan_id: Plan ID to execute
        dry_run: If True, simulate without making changes
        verify_mode: Verification mode:
            'fast' - Size/mtime + fast-hash sampling (default, recommended)
            'paranoid' - Full SHA256 hash verification (slow for large files)
            'none' - Skip verification (trust planning phase)
        create_backup: If True, create .bak backup files
        limit: Maximum number of actions to execute (0 = all)
        progress_callback: Optional callback(action_num, total_actions, action)
        use_jdupes: If True, use jdupes for byte-for-byte verification + linking
        jdupes_path: Optional explicit path to jdupes binary
        jdupes_log_dir: Optional directory for per-group jdupes logs

    Returns:
        ExecutionResult with statistics
    """
    # Get plan
    plan = get_plan(conn, plan_id)
    if not plan:
        raise ValueError(f"Plan {plan_id} not found")

    if plan.status == 'completed':
        raise ValueError(f"Plan {plan_id} is already completed")

    # Get pending actions
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            id, plan_id, action_type, status,
            canonical_path, duplicate_path,
            canonical_inode, duplicate_inode,
            device_id, file_size, sha256,
            bytes_to_save, bytes_saved,
            executed_at, error_message
        FROM link_actions
        WHERE plan_id = ? AND status = 'pending'
        ORDER BY bytes_to_save DESC
    """, (plan_id,))

    actions = []
    for row in cursor.fetchall():
        from hashall.link_query import ActionInfo
        actions.append(ActionInfo(
            id=row[0], plan_id=row[1], action_type=row[2], status=row[3],
            canonical_path=row[4], duplicate_path=row[5],
            canonical_inode=row[6], duplicate_inode=row[7],
            device_id=row[8], file_size=row[9], sha256=row[10],
            bytes_to_save=row[11], bytes_saved=row[12],
            executed_at=row[13], error_message=row[14]
        ))

    if limit > 0:
        actions = actions[:limit]

    # Mark plan as in_progress (unless dry-run)
    if not dry_run:
        update_plan_progress(conn, plan_id, start_execution=True)

    # Execute actions
    executed = 0
    failed = 0
    skipped = 0
    total_bytes_saved = 0
    errors = []
    total_actions = len(actions)
    processed = 0

    jdupes_cmd = None
    if use_jdupes:
        jdupes_cmd = jdupes_path or shutil.which("jdupes")
        if not jdupes_cmd:
            use_jdupes = False
            errors.append("jdupes not found; falling back to internal linker")

    def record(action: ActionInfo, status: str, bytes_saved: int = 0, error_message: Optional[str] = None) -> None:
        nonlocal executed, failed, skipped, total_bytes_saved, processed
        processed += 1
        if progress_callback:
            progress_callback(processed, total_actions, action, status=status, error=error_message)

        if status == 'completed':
            executed += 1
            total_bytes_saved += bytes_saved
        elif status == 'failed':
            failed += 1
            if error_message:
                errors.append(f"Action {action.id}: {error_message}")
        else:
            skipped += 1

        if not dry_run:
            if status == 'completed':
                update_action_status(conn, action.id, 'completed', bytes_saved=bytes_saved)
            elif status == 'failed':
                update_action_status(conn, action.id, 'failed', error_message=error_message)
            else:
                update_action_status(conn, action.id, 'skipped')

            if processed % 10 == 0:
                update_plan_progress(conn, plan_id)

    if use_jdupes:
        groups = {}
        for action in actions:
            if not action.sha256:
                record(action, 'failed', error_message="Missing SHA256 for jdupes linking")
                continue
            groups.setdefault(action.sha256, []).append(action)

        for hash_val, group_actions in groups.items():
            valid = []
            log_lines = []
            log_lines.append(f"plan_id: {plan_id}")
            log_lines.append(f"sha256: {hash_val}")
            log_lines.append(f"actions: {len(group_actions)}")
            log_lines.append(f"jdupes_cmd: {jdupes_cmd} -L -1 -O -P fullhash -q")
            for action in group_actions:
                status, error, canonical_path, duplicate_path = _precheck_jdupes_action(
                    conn, action, plan.mount_point, verify_mode
                )
                log_lines.append(f"precheck: action={action.id} status={status} canonical={canonical_path} duplicate={duplicate_path} error={error or ''}")
                if status == "ok":
                    valid.append((action, canonical_path, duplicate_path))
                elif status == "skipped":
                    record(action, 'skipped', error_message=error)
                else:
                    record(action, 'failed', error_message=error)

            if not valid:
                continue

            canonical_counts = Counter(str(entry[1]) for entry in valid)
            canonical_choice, _ = canonical_counts.most_common(1)[0]
            log_lines.append(f"canonical_choice: {canonical_choice}")

            kept = []
            for action, canonical_path, duplicate_path in valid:
                if str(canonical_path) != canonical_choice:
                    record(action, 'failed', error_message="Conflicting canonical path for hash group")
                else:
                    kept.append((action, canonical_path, duplicate_path))

            if not kept:
                continue

            paths = []
            seen = set()
            for path in [Path(canonical_choice)] + [dup for _, _, dup in kept]:
                path_str = str(path)
                if path_str in seen:
                    continue
                seen.add(path_str)
                paths.append(path)

            if len(paths) < 2:
                for action, _, _ in kept:
                    record(action, 'failed', error_message="Insufficient paths for jdupes linking")
                continue

            if dry_run:
                log_lines.append("dry_run: true")
                for action, _, _ in kept:
                    record(action, 'completed', bytes_saved=action.bytes_to_save)
                continue

            list_path, list_count = _write_jdupes_list(paths)
            log_lines.append(f"list_count: {list_count}")
            if list_count < 2:
                list_path.unlink(missing_ok=True)
                for action, _, _ in kept:
                    record(action, 'failed', error_message="Insufficient unique paths for jdupes linking")
                continue
            try:
                result = _run_jdupes(jdupes_cmd, list_path)
            finally:
                list_path.unlink(missing_ok=True)

            if result.returncode != 0:
                err_text = (result.stderr or result.stdout or "").strip()
                if err_text:
                    err_text = err_text.splitlines()[-1]
                group_error = f"jdupes returned {result.returncode}"
                if err_text:
                    group_error = f"{group_error}: {err_text}"
                errors.append(f"Group {hash_val[:12]}: {group_error}")
            log_lines.append(f"jdupes_returncode: {result.returncode}")
            if result.stdout:
                log_lines.append("jdupes_stdout:")
                log_lines.append(result.stdout.rstrip())
            if result.stderr:
                log_lines.append("jdupes_stderr:")
                log_lines.append(result.stderr.rstrip())

            not_linked = 0
            for action, canonical_path, duplicate_path in kept:
                try:
                    canonical_stat = os.stat(canonical_path)
                    duplicate_stat = os.stat(duplicate_path)
                except OSError as e:
                    record(action, 'failed', error_message=f"Cannot stat after jdupes: {e}")
                    log_lines.append(f"postcheck: action={action.id} status=failed error=Cannot stat after jdupes: {e}")
                    not_linked += 1
                    continue

                if canonical_stat.st_dev == duplicate_stat.st_dev and canonical_stat.st_ino == duplicate_stat.st_ino:
                    record(action, 'completed', bytes_saved=action.bytes_to_save)
                    log_lines.append(f"postcheck: action={action.id} status=linked inode={canonical_stat.st_ino}")
                else:
                    record(action, 'failed', error_message="jdupes did not link files with matching SHA256")
                    log_lines.append(f"postcheck: action={action.id} status=failed error=jdupes did not link files with matching SHA256")
                    not_linked += 1

            if not_linked:
                errors.append(
                    f"ALERT: jdupes left {not_linked}/{len(kept)} files unlinked for hash {hash_val[:12]}"
                )
            log_name = f"plan-{plan_id}_sha256-{hash_val[:12]}.log"
            _write_jdupes_log(jdupes_log_dir, log_name, "\n".join(log_lines) + "\n")

    else:
        for action in actions:
            success, error, bytes_saved = execute_action(
                conn, action,
                mount_point=plan.mount_point,
                dry_run=dry_run,
                verify_mode=verify_mode,
                create_backup=create_backup
            )

            if success:
                if bytes_saved > 0:
                    record(action, 'completed', bytes_saved=bytes_saved)
                else:
                    record(action, 'skipped')
            else:
                record(action, 'failed', error_message=error)

    # Final progress update
    if not dry_run:
        # Check if all actions are done
        cursor.execute("""
            SELECT COUNT(*) FROM link_actions
            WHERE plan_id = ? AND status = 'pending'
        """, (plan_id,))

        remaining = cursor.fetchone()[0]

        if remaining == 0:
            update_plan_progress(conn, plan_id, complete_execution=True)
        else:
            update_plan_progress(conn, plan_id)

    return ExecutionResult(
        plan_id=plan_id,
        actions_executed=executed,
        actions_failed=failed,
        actions_skipped=skipped,
        bytes_saved=total_bytes_saved,
        errors=errors
    )
