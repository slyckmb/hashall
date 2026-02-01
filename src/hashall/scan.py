# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import hashlib
import sqlite3
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, Set, Tuple
from dataclasses import dataclass
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
        dict: {path: {size, mtime, sha1}} for files under root_path

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
            SELECT path, size, mtime, sha1
            FROM {table_name}
            WHERE status = 'active'
        """)
    else:
        # Use both exact match and prefix match to get all files under the path
        cursor.execute(f"""
            SELECT path, size, mtime, sha1
            FROM {table_name}
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
        """, (rel_root_str, f"{rel_root_str}/%"))

    # Build dict: {path: {size, mtime, sha1}}
    existing = {}
    for row in cursor.fetchall():
        existing[row[0]] = {
            'size': row[1],
            'mtime': row[2],
            'sha1': row[3]
        }

    return existing


def compute_sha1(file_path):
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def _hash_file_worker(file_path: str, mount_point: Path, existing_files: Dict[str, dict]):
    """
    Hash a file for incremental scanning.

    Args:
        file_path: Absolute path to the file
        mount_point: Mount point for the filesystem (to compute relative path)
        existing_files: Dict of {rel_path: {size, mtime, sha1}} from database

    Returns:
        Tuple of (rel_path, size, mtime, sha1, inode, device_id, is_new, is_updated)
        or None on error
    """
    try:
        stat = os.stat(file_path)
        rel_path = str(Path(file_path).relative_to(mount_point))

        # Check if file exists in catalog
        existing = existing_files.get(rel_path)

        # Determine if we need to hash
        if existing and existing['size'] == stat.st_size and abs(existing['mtime'] - stat.st_mtime) < 0.001:
            # File unchanged - reuse existing hash
            return (rel_path, stat.st_size, stat.st_mtime, existing['sha1'], stat.st_ino, stat.st_dev, False, False)

        # File is new or modified - compute hash
        sha1 = compute_sha1(file_path)
        is_new = existing is None
        is_updated = not is_new

        return (rel_path, stat.st_size, stat.st_mtime, sha1, stat.st_ino, stat.st_dev, is_new, is_updated)
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
        rel_path, size, mtime, sha1, inode, device_id, is_new, is_updated = row

        if is_new:
            # Insert new file
            cursor.execute(f"""
                INSERT INTO {table_name}
                (path, size, mtime, sha1, inode, first_seen_at, last_seen_at, last_modified_at, status, discovered_under)
                VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'), 'active', ?)
            """, (rel_path, size, mtime, sha1, inode, root_str))
            stats.files_added += 1
            stats.bytes_hashed += size

        elif is_updated:
            # Update existing file (metadata changed)
            cursor.execute(f"""
                UPDATE {table_name}
                SET size = ?, mtime = ?, sha1 = ?, inode = ?,
                    last_seen_at = datetime('now'), last_modified_at = datetime('now'), status = 'active'
                WHERE path = ?
            """, (size, mtime, sha1, inode, rel_path))
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
              workers: int | None = None, batch_size: int | None = None):
    """
    Incrementally scan a directory with per-device table tracking.

    Args:
        db_path: Path to the catalog database
        root_path: Root directory to scan
        parallel: Whether to use parallel workers
        workers: Number of parallel workers (default: CPU count)
        batch_size: Number of files to batch before writing (default: 500)
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

    print(f"✅ Scan session: {scan_id}")

    # 8. Load existing files from DB (scoped to root_path)
    existing_files = load_existing_files(cursor, device_id, root_canonical)
    print(f"📊 Existing files in catalog: {len(existing_files)}")

    # 9. Walk filesystem and collect file paths
    file_paths = []
    for dirpath, _, filenames in os.walk(root_canonical):
        for filename in filenames:
            file_paths.append(os.path.join(dirpath, filename))

    print(f"📁 Files on filesystem: {len(file_paths)}")

    # 10. Incremental scan logic
    stats = ScanStats()
    seen_paths: Set[str] = set()
    interrupted = False  # Track if scan was interrupted

    # Get mount point for relative path calculation
    mount_point = Path(device_info['mount_point'])

    if not parallel:
        # Sequential scanning
        for file_path in tqdm(file_paths, desc="📦 Scanning"):
            result = _hash_file_worker(file_path, mount_point, existing_files)
            if result is None:
                continue
            rel_path, size, mtime, sha1, inode, dev_id, is_new, is_updated = result
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
        drain_deadline = None
        drain_iters = 0

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Prime the queue
                while len(pending) < max_inflight:
                    try:
                        file_path = next(file_iter)
                    except StopIteration:
                        break
                    pending.add(executor.submit(_hash_file_worker, file_path, mount_point, existing_files))

                with tqdm(total=len(file_paths), desc="📦 Scanning") as pbar:
                    while pending:
                        try:
                            done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        except KeyboardInterrupt:
                            interrupted = True
                            drain_deadline = time.monotonic() + 1.0
                            drain_iters = 10
                            print("⚠️ Scan interrupted. Draining completed results...")
                            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)

                        for fut in done:
                            result = fut.result()
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

                        # Refill
                        if interrupted:
                            if drain_deadline is None:
                                drain_deadline = time.monotonic() + 1.0
                                drain_iters = 10
                            drain_iters -= 1
                            if time.monotonic() >= drain_deadline or drain_iters <= 0:
                                break
                            continue

                        while len(pending) < max_inflight:
                            try:
                                file_path = next(file_iter)
                            except StopIteration:
                                break
                            pending.add(executor.submit(_hash_file_worker, file_path, mount_point, existing_files))

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
