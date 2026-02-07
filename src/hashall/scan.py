# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import hashlib
import sqlite3
import uuid
import time
import statistics
import shutil
import unicodedata
import sys
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from typing import Dict, Set, Tuple
from dataclasses import dataclass
from datetime import datetime
from tqdm import tqdm
from hashall.model import connect_db, init_db_schema
from hashall.device import register_or_update_device, ensure_files_table
from hashall.fs_utils import get_filesystem_uuid, get_mount_point, get_mount_source
from hashall.pathing import canonicalize_path, is_under

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
        dict: {path: {size, mtime, quick_hash, sha1, sha256}} for files under root_path

    Edge cases:
        - Mount point not found -> return empty dict
        - No files found -> return empty dict
        - Root path not under mount point -> return empty dict
    """
    # Get mount point for the device (prefer canonical mount when available)
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(devices)").fetchall()}
    if "preferred_mount_point" in columns:
        row = cursor.execute("""
            SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?
        """, (device_id,)).fetchone()
    else:
        row = cursor.execute("""
            SELECT mount_point, NULL FROM devices WHERE device_id = ?
        """, (device_id,)).fetchone()

    if not row:
        return {}

    mount_point = Path(row[0])
    preferred_mount_point = Path(row[1]) if row[1] else mount_point
    effective_mount_point = preferred_mount_point if root_path.is_relative_to(preferred_mount_point) else mount_point

    # Calculate relative root from mount point
    try:
        rel_root = root_path.relative_to(effective_mount_point)
    except ValueError:
        # root_path is not under mount_point
        return {}

    rel_root_str = str(rel_root)
    table_name = f"files_{device_id}"

    # Query files under root_path with status='active'
    # Special case: if rel_root is ".", get all files (root == mount point)
    if rel_root_str == ".":
        cursor.execute(f"""
            SELECT path, size, mtime, quick_hash, sha1, sha256
            FROM {table_name}
            WHERE status = 'active'
        """)
    else:
        # Use both exact match and prefix match to get all files under the path
        cursor.execute(f"""
            SELECT path, size, mtime, quick_hash, sha1, sha256
            FROM {table_name}
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
        """, (rel_root_str, f"{rel_root_str}/%"))

    # Build dict: {path: {size, mtime, quick_hash, sha1, sha256}}
    existing = {}
    for row in cursor.fetchall():
        existing[row[0]] = {
            'size': row[1],
            'mtime': row[2],
            'quick_hash': row[3],
            'sha1': row[4],
            'sha256': row[5]
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


def compute_sha256(file_path):
    """Compute full SHA256 hash of entire file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def compute_full_hashes(file_path):
    """Compute full SHA1 + SHA256 hashes in a single pass."""
    h1 = hashlib.sha1()
    h256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h1.update(chunk)
            h256.update(chunk)
    return h1.hexdigest(), h256.hexdigest()


def find_quick_hash_collisions(device_id: int, db_path: Path) -> Dict[str, list]:
    """
    Find collision groups where multiple files share the same quick_hash.

    Args:
        device_id: Device ID to query
        db_path: Path to catalog database

    Returns:
        Dict mapping quick_hash to list of file records with that hash.
        Each file record is a dict with keys: path, size, mtime, quick_hash, sha1, sha256

    Example:
        {
            'abc123...': [
                {'path': 'file1.dat', 'size': 1048576, 'quick_hash': 'abc123...', 'sha1': None, 'sha256': None},
                {'path': 'file2.dat', 'size': 1048576, 'quick_hash': 'abc123...', 'sha1': None, 'sha256': None}
            ]
        }
    """
    conn = connect_db(db_path)
    cursor = conn.cursor()
    ensure_files_table(cursor, device_id)
    table_name = f"files_{device_id}"

    # Find all quick_hash values with multiple files
    cursor.execute(f"""
        SELECT quick_hash, COUNT(*) as file_count
        FROM {table_name}
        WHERE status = 'active'
          AND quick_hash IS NOT NULL
        GROUP BY quick_hash
        HAVING COUNT(*) > 1
        ORDER BY file_count DESC
    """)

    collision_hashes = [row[0] for row in cursor.fetchall()]

    # For each collision hash, get all files
    collisions = {}
    for quick_hash in collision_hashes:
        cursor.execute(f"""
            SELECT path, size, mtime, quick_hash, sha1, sha256
            FROM {table_name}
            WHERE quick_hash = ? AND status = 'active'
            ORDER BY path
        """, (quick_hash,))

        files = []
        for row in cursor.fetchall():
            files.append({
                'path': row[0],
                'size': row[1],
                'mtime': row[2],
                'quick_hash': row[3],
                'sha1': row[4],
                'sha256': row[5]
            })
        collisions[quick_hash] = files

    conn.close()
    return collisions


def upgrade_collision_group(quick_hash: str, device_id: int, db_path: Path, mount_point: Path) -> list:
    """
    Upgrade all files in a collision group to full SHA256 hash.

    Args:
        quick_hash: The quick_hash value shared by the collision group
        device_id: Device ID
        db_path: Path to catalog database
        mount_point: Mount point for the filesystem (to resolve absolute paths)

    Returns:
        List of updated file records with full SHA256 computed

    Side effects:
        Updates database records with computed full SHA256 values
    """
    conn = connect_db(db_path)
    cursor = conn.cursor()
    ensure_files_table(cursor, device_id)
    table_name = f"files_{device_id}"

    # Get all files with this quick_hash
    cursor.execute(f"""
        SELECT path, size, mtime, quick_hash, sha1, sha256
        FROM {table_name}
        WHERE quick_hash = ? AND status = 'active'
    """, (quick_hash,))

    files = []
    for row in cursor.fetchall():
        file_record = {
            'path': row[0],
            'size': row[1],
            'mtime': row[2],
            'quick_hash': row[3],
            'sha1': row[4],
            'sha256': row[5]
        }
        files.append(file_record)

    # Compute full hash for any file missing it
    updated_files = []
    for file_record in files:
        if file_record['sha1'] is None or file_record['sha256'] is None:
            # Resolve absolute path
            abs_path = mount_point / file_record['path']
            try:
                full_sha1, full_sha256 = compute_full_hashes(abs_path)

                # Update database
                cursor.execute(f"""
                    UPDATE {table_name}
                    SET sha1 = ?, sha256 = ?, last_modified_at = datetime('now')
                    WHERE path = ?
                """, (full_sha1, full_sha256, file_record['path']))

                file_record['sha1'] = full_sha1
                file_record['sha256'] = full_sha256
                updated_files.append(file_record)
            except Exception as e:
                print(f"⚠️  Could not upgrade {abs_path}: {e}")

    conn.commit()
    conn.close()

    return files  # Return all files (updated and already had full hashes)


def find_duplicates(device_id: int, db_path: Path, auto_upgrade: bool = True) -> Dict[str, list]:
    """
    Find duplicate files, optionally auto-upgrading collision groups to full hash.

    Args:
        device_id: Device ID to query
        db_path: Path to catalog database
        auto_upgrade: If True, automatically compute full SHA256 for collision groups

    Returns:
        Dict mapping full SHA256 to list of duplicate files.
        Only includes groups with 2+ files sharing the same full SHA256.

    Example:
        {
            'def456...': [
                {'path': 'file1.dat', 'size': 10485760, 'sha256': 'def456...'},
                {'path': 'file2.dat', 'size': 10485760, 'sha256': 'def456...'}
            ]
        }

    Algorithm:
        1. Find collision groups (files with same quick_hash)
        2. If auto_upgrade: compute full SHA256 for each collision group
        3. Group files by full SHA256
        4. Return only groups with 2+ files (true duplicates)
    """
    from collections import defaultdict

    conn = connect_db(db_path)
    cursor = conn.cursor()

    # Get mount point for path resolution
    cursor.execute("""
        SELECT mount_point FROM devices WHERE device_id = ?
    """, (device_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {}

    mount_point = Path(row[0])
    conn.close()

    # Find collision groups
    collisions = find_quick_hash_collisions(device_id, db_path)

    if not collisions:
        return {}  # No collisions, no duplicates

    print(f"🔍 Found {len(collisions)} collision groups")

    # Auto-upgrade collision groups if requested
    if auto_upgrade:
        print("⚡ Upgrading collision groups to full SHA256...")
        for quick_hash in collisions.keys():
            upgrade_collision_group(quick_hash, device_id, db_path, mount_point)

        # Re-query collisions to get updated SHA256 values
        collisions = find_quick_hash_collisions(device_id, db_path)

    # Group by full SHA256
    by_sha256 = defaultdict(list)
    for quick_hash, files in collisions.items():
        for file_record in files:
            if file_record['sha256'] is not None:
                by_sha256[file_record['sha256']].append(file_record)

    # Only return groups with 2+ files (true duplicates)
    duplicates = {}
    true_dupe_count = 0
    false_collision_count = 0

    for sha256, files in by_sha256.items():
        if len(files) >= 2:
            duplicates[sha256] = files
            true_dupe_count += 1
        elif len(files) == 1:
            false_collision_count += 1

    if true_dupe_count > 0:
        print(f"✅ True duplicates: {true_dupe_count} groups")
    if false_collision_count > 0:
        print(f"⚠️  False collisions: {false_collision_count} groups (same quick_hash, different sha256)")

    return duplicates


def upgrade_quick_hash_collisions(device_id: int, db_path: Path, quiet: bool = False) -> int:
    """
    Upgrade SHA256 for quick-hash collision groups (inode-aware).

    Only hashes files in groups where quick_hash collides and distinct inodes exist.
    Returns number of inode groups upgraded.
    """
    conn = connect_db(db_path)
    cursor = conn.cursor()
    ensure_files_table(cursor, device_id)
    table_name = f"files_{device_id}"

    row = cursor.execute(
        "SELECT preferred_mount_point, mount_point FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if not row:
        conn.close()
        return 0

    preferred_mount = Path(row[0]) if row[0] else None
    mount_point = Path(row[1]) if row[1] else None
    base_mounts = [p for p in (preferred_mount, mount_point) if p is not None]

    cursor.execute(f"""
        SELECT quick_hash
        FROM {table_name}
        WHERE status = 'active'
          AND quick_hash IS NOT NULL
        GROUP BY quick_hash
        HAVING COUNT(DISTINCT COALESCE(inode, path)) > 1
    """)
    quick_hashes = [row[0] for row in cursor.fetchall()]

    if not quick_hashes:
        conn.close()
        return 0

    if not quiet:
        print(f"⚡ Upgrading {len(quick_hashes)} quick-hash collision groups...")

    upgraded_groups = 0
    for quick_hash in quick_hashes:
        cursor.execute(f"""
            SELECT path, inode, sha1, sha256
            FROM {table_name}
            WHERE quick_hash = ? AND status = 'active'
        """, (quick_hash,))
        rows = cursor.fetchall()

        pending = []
        seen = set()
        for row in rows:
            path, inode, sha1, sha256 = row[0], row[1], row[2], row[3]
            if sha1 is not None and sha256 is not None:
                continue
            key = (inode, ) if inode is not None else ("path", path)
            if key in seen:
                continue
            seen.add(key)
            pending.append((path, inode))

        if not pending:
            continue

        for path, inode in pending:
            abs_path = None
            if path.startswith("/"):
                abs_path = Path(path)
            else:
                for base in base_mounts:
                    candidate = base / path
                    if candidate.exists():
                        abs_path = candidate
                        break
                if abs_path is None and base_mounts:
                    abs_path = base_mounts[0] / path

            try:
                sha1, sha256 = compute_full_hashes(str(abs_path))
            except Exception as e:
                if not quiet:
                    print(f"⚠️  Could not upgrade {abs_path}: {e}")
                continue

            if inode is None:
                cursor.execute(f"""
                    UPDATE {table_name}
                    SET sha1 = ?, sha256 = ?, last_modified_at = datetime('now')
                    WHERE path = ? AND status = 'active'
                """, (sha1, sha256, path))
            else:
                cursor.execute(f"""
                    UPDATE {table_name}
                    SET sha1 = ?, sha256 = ?, last_modified_at = datetime('now')
                    WHERE inode = ? AND status = 'active'
                """, (sha1, sha256, inode))
            upgraded_groups += 1

    conn.commit()
    conn.close()
    return upgraded_groups


def _hash_file_worker(file_path: str, mount_point: Path, existing_files: Dict[str, dict], hash_mode: str = 'fast'):
    """
    Hash a file for incremental scanning.

    Args:
        file_path: Absolute path to the file
        mount_point: Mount point for the filesystem (to compute relative path)
        existing_files: Dict of {rel_path: {size, mtime, quick_hash, sha1, sha256}} from database
        hash_mode: 'fast' (quick_hash only), 'full' (both), or 'upgrade' (add full hashes to existing quick_hash)

    Returns:
        Tuple of (rel_path, size, mtime, quick_hash, sha1, sha256, inode, device_id, is_new, is_updated)
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
            sha256 = existing.get('sha256')

            # If upgrading and no full hash yet, compute it
            if hash_mode == 'upgrade' and (sha1 is None or sha256 is None):
                sha1, sha256 = compute_full_hashes(file_path)
                return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, sha256, stat.st_ino, stat.st_dev, False, True)

            return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, sha256, stat.st_ino, stat.st_dev, False, False)

        # File is new or modified - compute hashes based on mode
        quick_hash = compute_quick_hash(file_path)
        sha1 = None
        sha256 = None
        if hash_mode == 'full':
            sha1, sha256 = compute_full_hashes(file_path)

        is_new = existing is None
        is_updated = not is_new

        return (rel_path, stat.st_size, stat.st_mtime, quick_hash, sha1, sha256, stat.st_ino, stat.st_dev, is_new, is_updated)
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
        rel_path, size, mtime, quick_hash, sha1, sha256, inode, device_id, is_new, is_updated = row

        if is_new:
            # Insert new file or re-activate deleted file
            cursor.execute(f"""
                INSERT INTO {table_name}
                (path, size, mtime, quick_hash, sha1, sha256, inode, first_seen_at, last_seen_at, last_modified_at, status, discovered_under)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'), 'active', ?)
                ON CONFLICT(path) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    quick_hash = excluded.quick_hash,
                    sha1 = excluded.sha1,
                    sha256 = excluded.sha256,
                    inode = excluded.inode,
                    last_seen_at = datetime('now'),
                    last_modified_at = datetime('now'),
                    status = 'active',
                    discovered_under = excluded.discovered_under
            """, (rel_path, size, mtime, quick_hash, sha1, sha256, inode, root_str))
            stats.files_added += 1
            stats.bytes_hashed += size

        elif is_updated:
            # Update existing file (metadata or hash changed)
            cursor.execute(f"""
                UPDATE {table_name}
                SET size = ?, mtime = ?, quick_hash = ?, sha1 = ?, sha256 = ?, inode = ?,
                    last_seen_at = datetime('now'), last_modified_at = datetime('now'), status = 'active'
                WHERE path = ?
            """, (size, mtime, quick_hash, sha1, sha256, inode, rel_path))
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


def _emit(quiet: bool, message: str) -> None:
    if not quiet:
        print(message)


def _progress_kwargs(*, total: int | None, tqdm_position: int | None, quiet: bool, file=None) -> dict:
    kwargs = {
        "desc": "📦 Scanning",
        "leave": not quiet,
        "dynamic_ncols": True,
        "unit": " files",
        "total": total,
        "disable": quiet and tqdm_position is None,
    }
    if tqdm_position is not None:
        kwargs["position"] = tqdm_position
    if file is not None:
        kwargs["file"] = file
    return kwargs


class _TwoLineProgress:
    def __init__(self, total: int, enabled: bool):
        self.enabled = enabled and sys.stdout.isatty()
        self.file = sys.stdout if self.enabled else None
        self.total = total
        self.start = time.monotonic()
        self.n = 0
        self.path = ""
        if self.enabled:
            print("", file=self.file, flush=True)
            print("", file=self.file, flush=True)

    def _width(self) -> int:
        try:
            width = shutil.get_terminal_size((120, 20)).columns
        except Exception:
            width = 120
        return max(10, width - 1)

    def _progress_line(self, width: int) -> str:
        elapsed = max(time.monotonic() - self.start, 1e-9)
        line = tqdm.format_meter(
            self.n,
            self.total,
            elapsed,
            ncols=width,
            prefix="📦 Scanning",
            unit="files",
        )
        return _pad_to_width(_truncate_middle(line, width), width)

    def update(self, *, path: str | None = None, advance: int = 0) -> None:
        if not self.enabled:
            return
        if path is not None:
            self.path = path.replace("\n", " ")
        if advance:
            self.n += advance
        width = self._width()
        status_line = _pad_to_width(_truncate_middle(self.path, width), width)
        bar_line = self._progress_line(width)
        self.file.write("\x1b[2A\r\x1b[2K" + status_line)
        self.file.write("\x1b[1B\r\x1b[2K" + bar_line)
        self.file.write("\x1b[1B\r")
        self.file.flush()

    def close(self) -> None:
        if not self.enabled:
            return
        self.file.write("\x1b[2A\r\x1b[2K\x1b[1B\r")
        self.file.flush()


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def _display_width(text: str) -> int:
    return sum(_char_width(ch) for ch in text)


def _slice_by_width(text: str, max_width: int, *, from_end: bool = False) -> str:
    if max_width <= 0:
        return ""
    if not from_end:
        width = 0
        out = []
        for ch in text:
            ch_w = _char_width(ch)
            if width + ch_w > max_width:
                break
            out.append(ch)
            width += ch_w
        return "".join(out)
    width = 0
    out = []
    for ch in reversed(text):
        ch_w = _char_width(ch)
        if width + ch_w > max_width:
            break
        out.append(ch)
        width += ch_w
    return "".join(reversed(out))


def _truncate_middle(text: str, max_width: int) -> str:
    if max_width <= 0 or _display_width(text) <= max_width:
        return text
    if max_width <= 3:
        return _slice_by_width(text, max_width)
    head = max_width // 2 - 1
    tail = max_width - head - 3
    return f"{_slice_by_width(text, head)}...{_slice_by_width(text, tail, from_end=True)}"


def _pad_to_width(text: str, max_width: int) -> str:
    pad = max_width - _display_width(text)
    if pad > 0:
        return text + (" " * pad)
    return text


def _canonicalize_root(
    root_path: Path,
    current_mount: Path,
    preferred_mount: Path,
    *,
    allow_remap: bool
) -> Path:
    """Normalize root_path to a preferred mount point when possible."""
    if preferred_mount == current_mount:
        return root_path
    if not allow_remap:
        return root_path
    if root_path.is_relative_to(preferred_mount):
        return root_path
    try:
        rel_root = root_path.relative_to(current_mount)
    except ValueError:
        return root_path
    return preferred_mount / rel_root


def scan_path(db_path: Path, root_path: Path, parallel: bool = False,
              workers: int | None = None, batch_size: int | None = None,
              tqdm_position: int | None = None, quiet: bool = False,
              hash_mode: str = 'fast', show_current_path: bool = False):
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
        hash_mode: 'fast' (quick_hash only), 'full' (both hashes), 'upgrade' (add full hashes)
    """
    conn = connect_db(db_path)
    init_db_schema(conn)
    cursor = conn.cursor()

    # 1. Resolve canonical path (handle symlinks, bind mounts)
    root_resolved = Path(root_path).resolve()
    root_canonical = canonicalize_path(root_resolved)

    # 2. Get device_id (kernel-level identifier)
    device_id = os.stat(root_canonical).st_dev

    # 3. Get filesystem UUID (persistent identifier)
    fs_uuid = get_filesystem_uuid(str(root_canonical))

    _emit(quiet, f"📍 Scanning: {root_canonical}")
    if root_canonical != root_resolved:
        _emit(quiet, f"   Bind mount source: {root_canonical}")
    _emit(quiet, f"   Device ID: {device_id} | Filesystem UUID: {fs_uuid}")

    mount_point_str = get_mount_point(str(root_canonical)) or str(root_canonical)
    mount_source = get_mount_source(str(root_canonical)) or ""

    # 4. Register/update device in registry
    device_info = register_or_update_device(
        cursor, fs_uuid, device_id, mount_point_str
    )
    conn.commit()

    current_mount = Path(device_info["mount_point"])
    preferred_mount = Path(device_info.get("preferred_mount_point") or device_info["mount_point"])
    canonical_root = _canonicalize_root(
        root_canonical,
        current_mount,
        preferred_mount,
        allow_remap=bool(mount_source)
    )
    if canonical_root != root_canonical:
        _emit(quiet, f"   Canonical root: {canonical_root}")

    # Effective mount point for relative path storage
    effective_mount = preferred_mount if is_under(canonical_root, preferred_mount) else current_mount
    if effective_mount != current_mount:
        _emit(quiet, f"   Preferred mount: {effective_mount}")

    # 5. Ensure per-device files table exists
    table_name = ensure_files_table(cursor, device_id)

    # 6. Track scan root
    cursor.execute("""
        INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
        VALUES (?, ?, datetime('now'), 1)
        ON CONFLICT (fs_uuid, root_path) DO UPDATE SET
            last_scanned_at = datetime('now'),
            scan_count = scan_count + 1
    """, (fs_uuid, str(canonical_root)))
    conn.commit()

    # 7. Create scan session with new fields
    scan_id = str(uuid.uuid4())
    started_at = time.time()

    cursor.execute("""
        INSERT INTO scan_sessions
        (scan_id, fs_uuid, device_id, root_path, started_at, status, parallel, workers)
        VALUES (?, ?, ?, ?, datetime('now'), 'running', ?, ?)
    """, (scan_id, fs_uuid, device_id, str(canonical_root), parallel, workers))
    scan_session_id = cursor.lastrowid
    conn.commit()

    _emit(quiet, f"✅ Scan session: {scan_id}")

    # 8. Load existing files from DB (scoped to root_path)
    existing_files = load_existing_files(cursor, device_id, canonical_root)
    _emit(quiet, f"📊 Existing files in catalog: {len(existing_files)}")

    # 9. Walk filesystem and collect file paths
    file_paths = []
    dir_count = 0
    file_count = 0
    discovery = None
    if not quiet:
        discovery = tqdm(
            total=0,
            desc="📁 Discovering",
            unit=" dirs",
            dynamic_ncols=True,
            mininterval=0.5,
        )

    for dirpath, dirnames, filenames in os.walk(root_canonical):
        # Skip symlinked directories
        dirnames[:] = [
            d for d in dirnames
            if not (Path(dirpath) / d).is_symlink()
        ]
        dir_count += 1
        if discovery is not None:
            discovery.update(1)
            if dir_count % 50 == 0:
                discovery.set_postfix(files=file_count)
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.is_symlink():
                continue
            file_paths.append(str(file_path))
            file_count += 1

    if discovery is not None:
        discovery.set_postfix(files=file_count)
        discovery.close()

    _emit(quiet, f"📁 Files on filesystem: {file_count:,} in {dir_count:,} dirs")

    # 10. Incremental scan logic
    stats = ScanStats()
    seen_paths: Set[str] = set()
    interrupted = False  # Track if scan was interrupted

    # Get mount point for relative path calculation
    mount_point = effective_mount

    use_two_line = show_current_path and not quiet and tqdm_position is None
    progress = _TwoLineProgress(total=len(file_paths), enabled=use_two_line)
    progress_position = tqdm_position
    progress_file = None

    if not parallel:
        # Sequential scanning
        if progress.enabled:
            for file_path in file_paths:
                result = _hash_file_worker(file_path, mount_point, existing_files, hash_mode)
                if result is None:
                    progress.update(path=file_path, advance=1)
                    continue
                seen_paths.add(result[0])

                # Write immediately in sequential mode
                _write_batch(cursor, table_name, canonical_root, [result], stats)
                stats.files_scanned += 1
                progress.update(path=file_path, advance=1)

                # Commit periodically
                if stats.files_scanned % 500 == 0:
                    conn.commit()

            conn.commit()
        else:
            pbar_kwargs = _progress_kwargs(
                total=len(file_paths), tqdm_position=progress_position, quiet=quiet, file=progress_file
            )
            for file_path in tqdm(file_paths, **pbar_kwargs):
                result = _hash_file_worker(file_path, mount_point, existing_files, hash_mode)
                if result is None:
                    continue
                seen_paths.add(result[0])

                # Write immediately in sequential mode
                _write_batch(cursor, table_name, canonical_root, [result], stats)
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
        future_to_path = {}

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Prime the queue
                while len(pending) < max_inflight:
                    try:
                        file_path = next(file_iter)
                    except StopIteration:
                        break
                    future = executor.submit(_hash_file_worker, file_path, mount_point, existing_files, hash_mode)
                    pending.add(future)
                    future_to_path[future] = file_path

                if progress.enabled:
                    while pending:
                        try:
                            done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        except KeyboardInterrupt:
                            interrupted = True
                            print("⚠️ Scan interrupted. Canceling pending tasks...")
                            # Cancel all pending futures
                            for fut in pending:
                                fut.cancel()
                            # Collect any completed results quickly
                            done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                            pending = set()  # Clear pending set

                        for fut in done:
                            from concurrent.futures import CancelledError
                            try:
                                file_path = future_to_path.pop(fut, None)
                                result = fut.result()
                            except CancelledError:
                                progress.update(advance=1)
                                continue

                            if result is not None:
                                rel_path = result[0]
                                seen_paths.add(rel_path)
                                batch_rows.append(result)
                                stats.files_scanned += 1

                                if len(batch_rows) >= batch_size:
                                    _write_batch(cursor, table_name, canonical_root, batch_rows, stats)
                                    batch_rows.clear()
                                    conn.commit()
                            progress.update(path=file_path, advance=1)

                        # Exit immediately if interrupted
                        if interrupted:
                            break

                        while len(pending) < max_inflight:
                            try:
                                file_path = next(file_iter)
                            except StopIteration:
                                break
                            future = executor.submit(_hash_file_worker, file_path, mount_point, existing_files, hash_mode)
                            pending.add(future)
                            future_to_path[future] = file_path
                else:
                    pbar_kwargs = _progress_kwargs(
                        total=len(file_paths), tqdm_position=progress_position, quiet=quiet, file=progress_file
                    )
                    with tqdm(**pbar_kwargs) as pbar:
                        while pending:
                            try:
                                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                            except KeyboardInterrupt:
                                interrupted = True
                                pbar.write("⚠️ Scan interrupted. Canceling pending tasks...")
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
                                        _write_batch(cursor, table_name, canonical_root, batch_rows, stats)
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
                                future = executor.submit(_hash_file_worker, file_path, mount_point, existing_files, hash_mode)
                                pending.add(future)
                                future_to_path[future] = file_path

        except KeyboardInterrupt:
            interrupted = True
        finally:
            if interrupted and pending:
                for fut in list(pending):
                    fut.cancel()
            if batch_rows:
                _write_batch(cursor, table_name, canonical_root, batch_rows, stats)
                batch_rows.clear()
            conn.commit()

    if progress.enabled:
        progress.close()

    # 11. SCOPED deletion detection
    # Only mark files as deleted if:
    # - They're under root_canonical
    # - They weren't seen in this scan
    # - Status is currently 'active'

    # Calculate relative root prefix
    try:
        rel_root = canonical_root.relative_to(preferred_mount)
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
        _emit(quiet, f"🗑️  Marking {len(deleted_paths)} deleted files...")
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
        print(
            f"""
📦 Scan complete!
   Duration: {duration:.1f}s
   Scanned: {stats.files_scanned:,} files
   Added: {stats.files_added:,}
   Updated: {stats.files_updated:,}
   Unchanged: {stats.files_unchanged:,}
   Deleted: {stats.files_deleted:,}
   Hashed: {stats.bytes_hashed / 1024 / 1024:.1f} MB
    """
        )

    # Close connection to prevent resource leaks with hierarchical scanning
    conn.close()
