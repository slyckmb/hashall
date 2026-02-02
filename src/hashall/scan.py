# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import hashlib
import sqlite3
import uuid
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, Set, Tuple
from dataclasses import dataclass
from datetime import datetime
from tqdm import tqdm
from hashall.model import connect_db, init_db_schema
from hashall.device import register_or_update_device, ensure_files_table
from hashall.fs_utils import get_filesystem_uuid

BATCH_SIZE = 500


@dataclass
class ScanStats:
    """Statistics for a scan session."""
    files_scanned: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    bytes_hashed: int = 0


def load_existing_files(cursor, device_id: int, root_path: Path) -> dict:
    """
    Load existing files from DB for incremental scan (scoped to root_path).

    Args:
        cursor: Database cursor for executing SQL commands
        device_id: Device ID to query
        root_path: Root path to scope the query to

    Returns:
        dict: {path: {size, mtime, quick_hash, sha1}} for files under root_path

    Edge cases:
        - Mount point not found -> return empty dict
        - No files found -> return empty dict
        - Root path not under mount point -> return empty dict
    """
    # Get mount point for the device
    row = cursor.execute("""
        SELECT mount_point FROM devices WHERE device_id = ?
    """, (device_id,)).fetchone()

    if not row:
        return {}

    mount_point = Path(row[0])

    # Calculate relative root from mount point
    try:
        rel_root = root_path.relative_to(mount_point)
    except ValueError:
        # root_path is not under mount_point
        return {}

    rel_root_str = str(rel_root)
    table_name = f"files_{device_id}"

    # Query files under root_path with status='active'
    # Special case: if rel_root is ".", get all files (root == mount point)
    if rel_root_str == ".":
        cursor.execute(f"""
            SELECT path, size, mtime, quick_hash, sha1
            FROM {table_name}
            WHERE status = 'active'
        """)
    else:
        # Use both exact match and prefix match to get all files under the path
        cursor.execute(f"""
            SELECT path, size, mtime, quick_hash, sha1
            FROM {table_name}
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
        """, (rel_root_str, f"{rel_root_str}/%"))

    # Build dict: {path: {size, mtime, quick_hash, sha1}}
    existing = {}
    for row in cursor.fetchall():
        existing[row[0]] = {
            'size': row[1],
            'mtime': row[2],
            'quick_hash': row[3],
            'sha1': row[4]
        }

    return existing


def compute_quick_hash(file_path, sample_size=1024*1024):
    """
    Compute SHA1 of first N bytes for fast scanning.

    Args:
        file_path: Path to file
        sample_size: Bytes to read (default 1MB)

    Returns:
        SHA1 hex digest of sample
    """
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        data = f.read(sample_size)
        h.update(data)
    return h.hexdigest()


def compute_sha1(file_path):
    """Compute full SHA1 hash of entire file."""
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def _hash_file_worker(file_path: str, mount_point: Path, existing_files: Dict[str, dict], hash_mode: str = 'fast'):
    """
    Hash a file for incremental scanning.

    Args:
        file_path: Absolute path to the file
        mount_point: Mount point for the filesystem (to compute relative path)
        existing_files: Dict of {rel_path: {size, mtime, quick_hash, sha1}} from database
        hash_mode: 'fast' (quick_hash only), 'full' (both), or 'upgrade' (add sha1 to existing quick_hash)

    Returns:
        Tuple of (rel_path, size, mtime, quick_hash, sha1, inode, device_id, is_new, is_updated)
        or None on error
    """
    try:
        stat = os.stat(file_path)
        rel_path = str(Path(file_path).relative_to(mount_point))

        # Check if file exists in catalog
        existing = existing_files.get(rel_path)

        # Determine if we need to hash
        if existing and existing['size'] == stat.st_size and abs(existing['mtime'] - stat.st_mtime) < 0.001:
            # File unchanged - reuse existing hashes
            quick_hash = existing.get('quick_hash')
            sha1 = existing.get('sha1')

            # If upgrading and no full hash yet, compute it
            if hash_mode == 'upgrade' and not sha1:
                sha1 = compute_sha1(file_path)
                return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, stat.st_ino, stat.st_dev, False, True)

            return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, stat.st_ino, stat.st_dev, False, False)

        # File is new or modified - compute hashes based on mode
        quick_hash = compute_quick_hash(file_path)
        sha1 = compute_sha1(file_path) if hash_mode == 'full' else None

        is_new = existing is None
        is_updated = not is_new

        return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, stat.st_ino, stat.st_dev, is_new, is_updated)
    except Exception as e:
        print(f"⚠️ Could not process: {file_path} ({e})")
        return None

def _write_batch(cursor, table_name: str, root_canonical: Path, rows: list[tuple], stats: ScanStats):
    """
    Write a batch of file records to the per-device table.

    Args:
        cursor: Database cursor
        table_name: Name of the per-device table (e.g., "files_49")
        root_canonical: Canonical root path for this scan
        rows: List of tuples from _hash_file_worker
        stats: ScanStats object to update
    """
    if not rows:
        return

    root_str = str(root_canonical)

    for row in rows:
        rel_path, size, mtime, quick_hash, sha1, inode, device_id, is_new, is_updated = row

        if is_new:
            # Insert new file or re-activate deleted file
            cursor.execute(f"""
                INSERT INTO {table_name}
                (path, size, mtime, quick_hash, sha1, inode, first_seen_at, last_seen_at, last_modified_at, status, discovered_under)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'), 'active', ?)
                ON CONFLICT(path) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    quick_hash = excluded.quick_hash,
                    sha1 = excluded.sha1,
                    inode = excluded.inode,
                    last_seen_at = datetime('now'),
                    last_modified_at = datetime('now'),
                    status = 'active',
                    discovered_under = excluded.discovered_under
            """, (rel_path, size, mtime, quick_hash, sha1, inode, root_str))
            stats.files_added += 1
            stats.bytes_hashed += size

        elif is_updated:
            # Update existing file (metadata or hash changed)
            cursor.execute(f"""
                UPDATE {table_name}
                SET size = ?, mtime = ?, quick_hash = ?, sha1 = ?, inode = ?,
                    last_seen_at = datetime('now'), last_modified_at = datetime('now'), status = 'active'
                WHERE path = ?
            """, (size, mtime, quick_hash, sha1, inode, rel_path))
            stats.files_updated += 1
            stats.bytes_hashed += size

        else:
            # Unchanged file - just update last_seen_at
            cursor.execute(f"""
                UPDATE {table_name}
                SET last_seen_at = datetime('now')
                WHERE path = ?
            """, (rel_path,))
            stats.files_unchanged += 1

def scan_path(db_path: Path, root_path: Path, parallel: bool = False,
              workers: int | None = None, batch_size: int | None = None,
              tqdm_position: int | None = None, quiet: bool = False,
              hash_mode: str = 'fast'):
    """
    Incrementally scan a directory with per-device table tracking.

    Args:
        db_path: Path to the catalog database
        root_path: Root directory to scan
        parallel: Whether to use parallel workers
        workers: Number of parallel workers (default: CPU count)
        batch_size: Number of files to batch before writing (default: 500)
        tqdm_position: Position for progress bar (for nested display)
        quiet: Suppress verbose output (for nested progress bars)
        hash_mode: 'fast' (quick_hash only), 'full' (both hashes), 'upgrade' (add sha1)
    """
    conn = connect_db(db_path)
    init_db_schema(conn)
    cursor = conn.cursor()

    # 1. Resolve canonical path (handle symlinks, bind mounts)
    root_canonical = Path(root_path).resolve()

    # 2. Get device_id (kernel-level identifier)
    device_id = os.stat(root_canonical).st_dev

    # 3. Get filesystem UUID (persistent identifier)
    fs_uuid = get_filesystem_uuid(str(root_canonical))

    if not quiet:
        print(f"📍 Scanning: {root_canonical}")
        print(f"   Device ID: {device_id}")
        print(f"   Filesystem UUID: {fs_uuid}")

    # 4. Register/update device in registry
    device_info = register_or_update_device(
        cursor, fs_uuid, device_id, str(root_canonical)
    )
    conn.commit()

    # 5. Ensure per-device files table exists
    table_name = ensure_files_table(cursor, device_id)

    # 6. Track scan root
    cursor.execute("""
        INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
        VALUES (?, ?, datetime('now'), 1)
        ON CONFLICT (fs_uuid, root_path) DO UPDATE SET
            last_scanned_at = datetime('now'),
            scan_count = scan_count + 1
    """, (fs_uuid, str(root_canonical)))
    conn.commit()

    # 7. Create scan session with new fields
    scan_id = str(uuid.uuid4())
    started_at = time.time()

    cursor.execute("""
        INSERT INTO scan_sessions
        (scan_id, fs_uuid, device_id, root_path, started_at, status, parallel, workers)
        VALUES (?, ?, ?, ?, datetime('now'), 'running', ?, ?)
    """, (scan_id, fs_uuid, device_id, str(root_canonical), parallel, workers))
    scan_session_id = cursor.lastrowid
    conn.commit()

    if not quiet:
        print(f"✅ Scan session: {scan_id}")

    # 8. Load existing files from DB (scoped to root_path)
    existing_files = load_existing_files(cursor, device_id, root_canonical)
    if not quiet:
        print(f"📊 Existing files in catalog: {len(existing_files)}")

    # 9. Walk filesystem and collect file paths
    file_paths = []
    for dirpath, _, filenames in os.walk(root_canonical):
        for filename in filenames:
            file_paths.append(os.path.join(dirpath, filename))

    if not quiet:
        print(f"📁 Files on filesystem: {len(file_paths)}")

    # 10. Incremental scan logic
    stats = ScanStats()
    seen_paths: Set[str] = set()
    interrupted = False  # Track if scan was interrupted

    # Get mount point for relative path calculation
    mount_point = Path(device_info['mount_point'])

    if not parallel:
        # Sequential scanning
        pbar_kwargs = {"desc": "📦 Scanning", "leave": True}
        if tqdm_position is not None:
            pbar_kwargs["position"] = tqdm_position
        for file_path in tqdm(file_paths, **pbar_kwargs):
            result = _hash_file_worker(file_path, mount_point, existing_files, hash_mode)
            if result is None:
                continue
            rel_path, size, mtime, quick_hash, sha1, inode, dev_id, is_new, is_updated = result
            seen_paths.add(rel_path)

            # Write immediately in sequential mode
            _write_batch(cursor, table_name, root_canonical, [result], stats)
            stats.files_scanned += 1

            # Commit periodically
            if stats.files_scanned % 500 == 0:
                conn.commit()

        conn.commit()

    else:
        # Parallel scanning
        workers = max(1, workers or (os.cpu_count() or 1))
        max_inflight = workers * 10
        batch_size = batch_size or BATCH_SIZE
        pending = set()
        batch_rows = []
        file_iter = iter(file_paths)

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Prime the queue
                while len(pending) < max_inflight:
                    try:
                        file_path = next(file_iter)
                    except StopIteration:
                        break
                    pending.add(executor.submit(_hash_file_worker, file_path, mount_point, existing_files, hash_mode))

                pbar_kwargs = {"total": len(file_paths), "desc": "📦 Scanning", "leave": True}
                if tqdm_position is not None:
                    pbar_kwargs["position"] = tqdm_position
                with tqdm(**pbar_kwargs) as pbar:
                    while pending:
                        try:
                            done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        except KeyboardInterrupt:
                            interrupted = True
                            print("\n⚠️ Scan interrupted. Canceling pending tasks...")
                            # Cancel all pending futures
                            for fut in pending:
                                fut.cancel()
                            # Collect any completed results quickly
                            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                            pending = set()  # Clear pending set

                        for fut in done:
                            from concurrent.futures import CancelledError
                            try:
                                result = fut.result()
                            except CancelledError:
                                # Ignore cancelled futures
                                pbar.update(1)
                                continue

                            if result is not None:
                                rel_path = result[0]
                                seen_paths.add(rel_path)
                                batch_rows.append(result)
                                stats.files_scanned += 1

                                if len(batch_rows) >= batch_size:
                                    _write_batch(cursor, table_name, root_canonical, batch_rows, stats)
                                    batch_rows.clear()
                                    conn.commit()
                            pbar.update(1)

                        # Exit immediately if interrupted
                        if interrupted:
                            break

                        while len(pending) < max_inflight:
                            try:
                                file_path = next(file_iter)
                            except StopIteration:
                                break
                            pending.add(executor.submit(_hash_file_worker, file_path, mount_point, existing_files, hash_mode))

        except KeyboardInterrupt:
            interrupted = True
        finally:
            if interrupted and pending:
                for fut in list(pending):
                    fut.cancel()
            if batch_rows:
                _write_batch(cursor, table_name, root_canonical, batch_rows, stats)
                batch_rows.clear()
            conn.commit()

    # 11. SCOPED deletion detection
    # Only mark files as deleted if:
    # - They're under root_canonical
    # - They weren't seen in this scan
    # - Status is currently 'active'

    # Calculate relative root prefix
    try:
        rel_root = root_canonical.relative_to(mount_point)
    except ValueError:
        rel_root = Path('.')

    rel_root_str = str(rel_root)

    # Find deleted paths (existed before but not seen now)
    deleted_paths = []
    for existing_path in existing_files.keys():
        if existing_path not in seen_paths:
            # File was in DB but not seen in this scan
            deleted_paths.append(existing_path)

    if deleted_paths:
        if not quiet:
            print(f"🗑️  Marking {len(deleted_paths)} deleted files...")
        for path in deleted_paths:
            cursor.execute(f"""
                UPDATE {table_name}
                SET status = 'deleted', last_seen_at = datetime('now')
                WHERE path = ? AND status = 'active'
            """, (path,))
        stats.files_deleted = len(deleted_paths)
        conn.commit()

    # 12. Update scan session stats
    duration = time.time() - started_at
    cursor.execute("""
        UPDATE scan_sessions SET
            completed_at = datetime('now'),
            duration_seconds = ?,
            status = ?,
            files_scanned = ?,
            files_added = ?,
            files_updated = ?,
            files_unchanged = ?,
            files_deleted = ?,
            bytes_hashed = ?
        WHERE id = ?
    """, (
        duration,
        'interrupted' if interrupted else 'completed',
        stats.files_scanned,
        stats.files_added,
        stats.files_updated,
        stats.files_unchanged,
        stats.files_deleted,
        stats.bytes_hashed,
        scan_session_id
    ))

    # 13. Update device metadata
    cursor.execute(f"""
        UPDATE devices SET
            total_files = (SELECT COUNT(*) FROM {table_name} WHERE status = 'active'),
            total_bytes = (SELECT COALESCE(SUM(size), 0) FROM {table_name} WHERE status = 'active'),
            updated_at = datetime('now')
        WHERE fs_uuid = ?
    """, (fs_uuid,))

    conn.commit()

    # Collect telemetry for continuous optimization
    try:
        from hashall.telemetry import TelemetryCollector, ScanPerformanceMetrics

        # Calculate file size metrics for scanned files
        file_sizes = []
        for file_path in file_paths[:min(100, len(file_paths))]:  # Sample up to 100 files
            try:
                file_sizes.append(os.path.getsize(file_path))
            except (OSError, PermissionError):
                continue

        if file_sizes and stats.files_scanned > 0:
            avg_size = statistics.mean(file_sizes)
            median_size = statistics.median(file_sizes)

            # Determine which preset was likely used based on config
            preset_used = None
            if parallel:
                if workers == 2:
                    if avg_size >= 50 * 1024 * 1024:
                        preset_used = "video"
                    elif avg_size >= 5 * 1024 * 1024:
                        preset_used = "audio"
                    else:
                        preset_used = "books"

            metrics = ScanPerformanceMetrics(
                parallel=parallel,
                workers=workers,
                batch_size=batch_size,
                file_count=stats.files_scanned,
                avg_file_size=avg_size,
                median_file_size=median_size,
                total_bytes=stats.bytes_hashed,
                duration_seconds=duration,
                files_per_second=stats.files_scanned / duration if duration > 0 else 0,
                bytes_per_second=stats.bytes_hashed / duration if duration > 0 else 0,
                device_id=device_id,
                scan_timestamp=datetime.now().isoformat(),
                preset_used=preset_used
            )

            collector = TelemetryCollector(db_path)
            collector.record_scan(metrics)
    except Exception as e:
        # Don't fail scan if telemetry fails
        pass

    if not quiet:
        print(f"""
📦 Scan complete!
   Duration: {duration:.1f}s
   Scanned: {stats.files_scanned:,} files
   Added: {stats.files_added:,}
   Updated: {stats.files_updated:,}
   Unchanged: {stats.files_unchanged:,}
   Deleted: {stats.files_deleted:,}
   Hashed: {stats.bytes_hashed / 1024 / 1024:.1f} MB
    """)

    # Close connection to prevent resource leaks with hierarchical scanning
    conn.close()
