"""
Device management for per-device file tables.

This module provides functionality for creating and managing per-device file tables
in the hashall catalog database. Each device (filesystem) gets its own table to track
files, enabling efficient incremental scanning and device-specific operations.
"""

import sqlite3
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional


def _quote_ident(name: str) -> str:
    """Return a safely quoted SQLite identifier."""
    return '"' + str(name).replace('"', '""') + '"'


def _files_index_specs(table_name: str) -> dict[str, str]:
    """Return expected index_name -> column mapping for a files_* table."""
    return {
        f"idx_{table_name}_quick_hash": "quick_hash",
        f"idx_{table_name}_sha1": "sha1",
        f"idx_{table_name}_sha256": "sha256",
        f"idx_{table_name}_inode": "inode",
        f"idx_{table_name}_status": "status",
    }


def ensure_files_indexes(cursor: sqlite3.Cursor, table_name: str, verbose: bool = False) -> dict:
    """
    Ensure a files_* table has the expected index set and ownership.

    Repairs two failure modes:
    - index-name conflicts where idx_files_<id>_* points at another files table
    - stale renamed indexes left behind on this table (idx_files_<oldid>_*)
    """
    expected = _files_index_specs(table_name)
    dropped_stale = 0
    dropped_conflicts = 0
    recreated = 0

    # Remove stale hashall index names attached to this table but not expected.
    stale_rows = cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='index'
          AND tbl_name=?
          AND name LIKE 'idx_files_%'
          AND sql IS NOT NULL
        """,
        (table_name,),
    ).fetchall()
    for row in stale_rows:
        idx_name = row[0]
        if idx_name in expected:
            continue
        cursor.execute(f"DROP INDEX IF EXISTS {_quote_ident(idx_name)}")
        dropped_stale += 1
        if verbose:
            print(f"⚠️  Dropped stale index {idx_name} on {table_name}")

    # Ensure each expected index name belongs to this table and uses the right column.
    for idx_name, col_name in expected.items():
        row = cursor.execute(
            """
            SELECT tbl_name
            FROM sqlite_master
            WHERE type='index' AND name=?
            """,
            (idx_name,),
        ).fetchone()

        if row and row[0] != table_name:
            cursor.execute(f"DROP INDEX IF EXISTS {_quote_ident(idx_name)}")
            dropped_conflicts += 1
            if verbose:
                print(f"⚠️  Dropped conflicting index {idx_name} from table {row[0]}")
            row = None

        if row and row[0] == table_name:
            # Validate index column definition; rebuild if drifted.
            cols = [r[2] for r in cursor.execute(f"PRAGMA index_info({_quote_ident(idx_name)})").fetchall()]
            if cols != [col_name]:
                cursor.execute(f"DROP INDEX IF EXISTS {_quote_ident(idx_name)}")
                if verbose:
                    print(f"⚠️  Rebuilding malformed index {idx_name} (cols={cols})")
                row = None

        if row is None:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {_quote_ident(idx_name)} "
                f"ON {_quote_ident(table_name)}({_quote_ident(col_name)})"
            )
            recreated += 1

    return {
        "table": table_name,
        "expected": len(expected),
        "dropped_stale": dropped_stale,
        "dropped_conflicts": dropped_conflicts,
        "recreated": recreated,
    }


def ensure_files_table(cursor: sqlite3.Cursor, device_id: int) -> str:
    """
    Create files_{device_id} table if not exists. Returns table name.

    Creates a per-device file table with the schema specified in priority-0-revised.
    The table tracks files on a specific device (filesystem) identified by its device_id.

    Args:
        cursor: Database cursor for executing SQL commands
        device_id: Numeric device ID (st_dev from os.stat)

    Returns:
        str: The created table name (e.g., "files_49")

    Schema:
        - path: Relative path from mount point (PRIMARY KEY)
        - size: File size in bytes
        - mtime: Modification time (Unix timestamp)
        - quick_hash: SHA-1 of first 1MB (fast scan, always computed)
        - sha1: Legacy SHA-1 hash (optional)
        - sha256: Full SHA-256 hash (NULL until backfilled)
        - inode: Inode number
        - first_seen_at: Timestamp when file was first discovered
        - last_seen_at: Timestamp when file was last seen in a scan
        - last_modified_at: Timestamp when file metadata was last modified
        - status: File status ('active', 'deleted', 'moved')
        - discovered_under: Root path where file was first discovered

    Note:
        This function is idempotent - it's safe to call multiple times.
        The table and indexes will only be created if they don't already exist.
    """
    table_name = f"files_{device_id}"
    table_ident = _quote_ident(table_name)

    # Create the table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_ident} (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            quick_hash TEXT,
            sha1 TEXT,
            sha256 TEXT,
            hash_source TEXT,
            inode INTEGER NOT NULL,
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            discovered_under TEXT
        )
    """)

    # Migrate existing tables: add quick_hash column if missing
    try:
        cursor.execute(f"ALTER TABLE {table_ident} ADD COLUMN quick_hash TEXT")
    except Exception:
        # Column already exists, ignore
        pass

    # Migrate existing tables: add sha256 column if missing
    try:
        cursor.execute(f"ALTER TABLE {table_ident} ADD COLUMN sha256 TEXT")
    except Exception:
        # Column already exists, ignore
        pass

    # Migrate existing tables: add hash_source column if missing
    try:
        cursor.execute(f"ALTER TABLE {table_ident} ADD COLUMN hash_source TEXT")
    except Exception:
        # Column already exists, ignore
        pass

    # Ensure expected index set is present and attached to the right table.
    ensure_files_indexes(cursor, table_name, verbose=False)

    return table_name


def rename_files_table(cursor: sqlite3.Cursor, old_device_id: int, new_device_id: int):
    """
    Rename files table when device_id changes.

    This function renames a per-device files table from files_{old_device_id} to
    files_{new_device_id}. It handles cases where the old table doesn't exist
    (no-op) and gracefully handles scenarios where the new table already exists.

    Args:
        cursor: Database cursor for executing SQL commands
        old_device_id: Previous device ID
        new_device_id: New device ID

    Note:
        This function is designed to be safe:
        - No-op if old table doesn't exist
        - Gracefully handles if new table already exists (rare but possible)
    """
    old_table_name = f"files_{old_device_id}"
    new_table_name = f"files_{new_device_id}"

    # Check if old table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (old_table_name,))

    result = cursor.fetchone()

    if result is None:
        # Old table doesn't exist, nothing to do
        return

    # Check if new table already exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (new_table_name,))

    new_exists = cursor.fetchone()

    if new_exists:
        # New table already exists, don't attempt rename
        # This is rare but possible in edge cases
        return

    # Rename the table (quoted to handle negative or unusual device_ids)
    cursor.execute(f'ALTER TABLE "{old_table_name}" RENAME TO "{new_table_name}"')
    # Rebuild indexes so names/ownership match the new table id.
    ensure_files_indexes(cursor, new_table_name, verbose=False)

    print(f"✅ Renamed table: files_{old_device_id} → files_{new_device_id}")


def repair_all_files_table_indexes(cursor: sqlite3.Cursor, verbose: bool = True) -> dict:
    """
    One-shot repair for files_* table indexes in an existing DB.

    Returns summary counters and per-table details.
    """
    rows = cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name LIKE 'files_%'
        ORDER BY name
        """
    ).fetchall()

    repaired = []
    totals = {
        "tables": 0,
        "dropped_stale": 0,
        "dropped_conflicts": 0,
        "recreated": 0,
    }

    for row in rows:
        table_name = str(row[0] or "").strip()
        if not table_name:
            continue
        stats = ensure_files_indexes(cursor, table_name, verbose=verbose)
        repaired.append(stats)
        totals["tables"] += 1
        totals["dropped_stale"] += int(stats["dropped_stale"])
        totals["dropped_conflicts"] += int(stats["dropped_conflicts"])
        totals["recreated"] += int(stats["recreated"])

    totals["details"] = repaired
    return totals


def suggest_device_alias(path: Path, cursor: sqlite3.Cursor) -> str:
    """
    Suggest a device alias based on path. Ensures uniqueness.

    This function analyzes the provided path and suggests a user-friendly alias
    for a device. It searches path components in reverse order for common names
    (pool, stash, backup, archive, data) and ensures the suggested alias is unique
    by checking the devices table. If a conflict exists, numeric suffixes are added.

    Args:
        path: The path to analyze (typically a mount point or root path)
        cursor: Database cursor for checking existing aliases

    Returns:
        str: A unique device alias suggestion

    Examples:
        /mnt/pool/torrents → "pool"
        /stash/media → "stash"
        /some/random/path → "path"
        If "pool" exists → "pool2"
        If "pool2" exists → "pool3"

    Note:
        The function prefers common storage names but falls back to the
        last directory component if none are found.
    """
    # Common storage-related directory names to look for
    common_names = {"pool", "stash", "backup", "archive", "data"}

    # Extract path components and search in reverse order
    parts = path.parts
    base_alias = None

    # Search from the end of the path backwards
    for part in reversed(parts):
        part_lower = part.lower()
        if part_lower in common_names:
            base_alias = part_lower
            break

    # Fallback to last directory name if no common names found
    if base_alias is None:
        # Use the last component, but handle edge cases
        if len(parts) > 0:
            base_alias = parts[-1].lower()
        else:
            base_alias = "device"

    # Check if this alias is already taken
    cursor.execute(
        "SELECT device_alias FROM devices WHERE device_alias = ?",
        (base_alias,)
    )
    result = cursor.fetchone()

    # If not taken, return as-is
    if result is None:
        return base_alias

    # If taken, add numeric suffix
    suffix = 2
    while True:
        candidate = f"{base_alias}{suffix}"
        cursor.execute(
            "SELECT device_alias FROM devices WHERE device_alias = ?",
            (candidate,)
        )
        result = cursor.fetchone()

        if result is None:
            return candidate

        suffix += 1


def register_or_update_device(cursor: sqlite3.Cursor, fs_uuid: str, device_id: int,
                              mount_point: str, **kwargs) -> dict:
    """
    Register a new device or update existing device metadata.

    This function handles device registration in the catalog database. It checks if a device
    with the given filesystem UUID already exists, and either updates it or creates a new entry.

    Key behaviors:
    1. If device exists and device_id changed:
       - Prints warning about the change
       - Updates device_id_history JSON array with old device_id and timestamp
       - Calls rename_files_table() to rename the files table
       - Updates the device record with new device_id

    2. If device exists and device_id is the same:
       - Updates last_scanned_at to current timestamp
       - Increments scan_count

    3. If device is new:
       - Suggests a device alias based on mount_point
       - Retrieves ZFS metadata if available
       - Gets filesystem type using stat command
       - Inserts new device record with all metadata
       - Prints confirmation message

    Args:
        cursor: Database cursor for executing SQL commands
        fs_uuid: Persistent filesystem UUID (e.g., "zfs-12345" or "a1b2c3d4-...")
        device_id: Current device ID from os.stat().st_dev
        mount_point: Current mount point path (e.g., "/pool", "/stash")
        **kwargs: Optional additional fields to set (fs_type, zfs_pool_name, etc.)

    Returns:
        dict: Device information containing:
            - device_id: Current device ID
            - fs_uuid: Filesystem UUID
            - device_alias: User-friendly alias (or None)
            - mount_point: Current mount point
            - fs_type: Filesystem type
            - scan_count: Number of scans performed
            - Plus any ZFS metadata if applicable

    Examples:
        >>> # First scan of a ZFS pool
        >>> device = register_or_update_device(
        ...     cursor, "zfs-12345", 49, "/pool"
        ... )
        >>> print(device['device_alias'])
        'pool'

        >>> # Rescan after reboot (device_id changed)
        >>> device = register_or_update_device(
        ...     cursor, "zfs-12345", 50, "/pool"
        ... )
        # Prints warning about device_id change
        # Renames files_49 to files_50
    """
    from hashall.fs_utils import get_zfs_metadata

    # Check if device exists by fs_uuid
    existing = cursor.execute("""
        SELECT device_id, device_alias, device_id_history, scan_count, preferred_mount_point
        FROM devices WHERE fs_uuid = ?
    """, (fs_uuid,)).fetchone()

    if existing:
        old_device_id, alias, history_json, scan_count, preferred_mount_point = existing

        # Check if device_id changed
        if old_device_id != device_id:
            print(f"⚠️  Device ID changed for filesystem {fs_uuid}:")
            print(f"   Old device_id: {old_device_id} → New device_id: {device_id}")
            print(f"   This can happen after remounts or reboots.")

            # Update device_id_history
            history = json.loads(history_json or '[]')
            history.append({
                'device_id': old_device_id,
                'changed_at': datetime.now().isoformat()
            })

            # If another device currently holds new device_id, park it at a temp
            # negative id BEFORE renaming our files table, so the target slot is
            # clear. That device will be corrected to its real new id when scanned.
            colliding = cursor.execute(
                "SELECT fs_uuid FROM devices WHERE device_id = ? AND fs_uuid != ?",
                (device_id, fs_uuid)
            ).fetchone()
            if colliding:
                colliding_uuid = colliding[0]
                temp_id = -(abs(hash(colliding_uuid)) % (2 ** 30))
                while cursor.execute(
                    "SELECT 1 FROM devices WHERE device_id = ?", (temp_id,)
                ).fetchone():
                    temp_id -= 1
                colliding_table = f"files_{device_id}"
                temp_table = f"files_{temp_id}"
                if cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (colliding_table,)
                ).fetchone():
                    cursor.execute(f'ALTER TABLE "{colliding_table}" RENAME TO "{temp_table}"')
                cursor.execute(
                    "UPDATE devices SET device_id = ? WHERE fs_uuid = ?",
                    (temp_id, colliding_uuid)
                )
                print(f"⚠️  Parked conflicting device {colliding_uuid[:8]} at temp id {temp_id}"
                      f" (will update on next scan of that device)")

            # Rename our files table now that the target slot is guaranteed clear
            rename_files_table(cursor, old_device_id, device_id)

            # Migrate payloads to new device_id so catalog stays consistent
            cursor.execute(
                "UPDATE payloads SET device_id = ? WHERE device_id = ?",
                (device_id, old_device_id),
            )
            migrated = cursor.rowcount
            if migrated > 0:
                print(f"   Migrated {migrated} payload row(s) from device_id {old_device_id} → {device_id}")

            # Update device record with new device_id
            cursor.execute("""
                UPDATE devices SET
                    device_id = ?,
                    device_id_history = ?,
                    mount_point = ?,
                    preferred_mount_point = COALESCE(preferred_mount_point, ?),
                    updated_at = datetime('now')
                WHERE fs_uuid = ?
            """, (device_id, json.dumps(history), mount_point, mount_point, fs_uuid))

        else:
            # Device ID unchanged - just update scan timestamp
            cursor.execute("""
                UPDATE devices SET
                    last_scanned_at = datetime('now'),
                    scan_count = scan_count + 1,
                    mount_point = ?,
                    preferred_mount_point = COALESCE(preferred_mount_point, ?),
                    updated_at = datetime('now')
                WHERE fs_uuid = ?
            """, (mount_point, mount_point, fs_uuid))

    else:
        # Handle legacy/placeholder fs_uuid rows that already own this device_id.
        # This avoids UNIQUE(device_id) failures when fs_uuid identity is corrected.
        existing_device = cursor.execute("""
            SELECT fs_uuid FROM devices WHERE device_id = ?
        """, (device_id,)).fetchone()

        if existing_device:
            old_fs_uuid = existing_device[0]
            if old_fs_uuid != fs_uuid:
                print(f"⚠️  Filesystem UUID updated for device_id {device_id}:")
                print(f"   Old fs_uuid: {old_fs_uuid} → New fs_uuid: {fs_uuid}")

                cursor.execute("""
                    UPDATE devices SET
                        fs_uuid = ?,
                        mount_point = ?,
                        preferred_mount_point = COALESCE(preferred_mount_point, ?),
                        last_scanned_at = datetime('now'),
                        scan_count = scan_count + 1,
                        updated_at = datetime('now')
                    WHERE device_id = ?
                """, (fs_uuid, mount_point, mount_point, device_id))

                for table_name in ("scan_roots", "scan_sessions"):
                    table_exists = cursor.execute("""
                        SELECT 1 FROM sqlite_master WHERE type='table' AND name=?
                    """, (table_name,)).fetchone()
                    if table_exists:
                        cursor.execute(
                            f"UPDATE {table_name} SET fs_uuid = ? WHERE fs_uuid = ?",
                            (fs_uuid, old_fs_uuid)
                        )
        else:
            # New device - register it
            alias = suggest_device_alias(Path(mount_point), cursor)

            # Try to get ZFS metadata
            zfs_meta = get_zfs_metadata(mount_point)

            # Get filesystem type
            fs_type = kwargs.get('fs_type')
            if not fs_type:
                fs_type = _get_fs_type(mount_point)

            # Insert new device record
            cursor.execute("""
                INSERT INTO devices
                (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, fs_type,
                 zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
                 first_scanned_at, last_scanned_at, scan_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 1)
            """, (
                fs_uuid,
                device_id,
                alias,
                mount_point,
                mount_point,
                fs_type,
                zfs_meta.get('pool_name'),
                zfs_meta.get('dataset_name'),
                zfs_meta.get('pool_guid')
            ))

            print(f"✅ Registered new device: {alias} (fs_uuid={fs_uuid}, device_id={device_id})")

    # Fetch and return complete device info
    device_info = cursor.execute("""
        SELECT device_id, fs_uuid, device_alias, mount_point, preferred_mount_point, fs_type,
               zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
               scan_count, total_files, total_bytes
        FROM devices WHERE fs_uuid = ?
    """, (fs_uuid,)).fetchone()

    if device_info:
        return {
            'device_id': device_info[0],
            'fs_uuid': device_info[1],
            'device_alias': device_info[2],
            'mount_point': device_info[3],
            'preferred_mount_point': device_info[4],
            'fs_type': device_info[5],
            'zfs_pool_name': device_info[6],
            'zfs_dataset_name': device_info[7],
            'zfs_pool_guid': device_info[8],
            'scan_count': device_info[9],
            'total_files': device_info[10],
            'total_bytes': device_info[11]
        }
    else:
        # Should not happen, but return minimal info
        return {
            'device_id': device_id,
            'fs_uuid': fs_uuid,
            'device_alias': None,
            'mount_point': mount_point,
            'preferred_mount_point': mount_point
        }


def resolve_device_id(conn: sqlite3.Connection, value: str) -> int:
    """Resolve a device alias or integer string to the current device_id.

    Accepts either a decimal integer string (e.g. "44") or a device alias
    (e.g. "stash", "pool") and returns the current integer device_id from the
    devices table.  Raises ValueError if the alias is not found.

    This insulates callers from volatile os.stat() device numbers — pass an
    alias and the correct device_id is always returned regardless of reboots.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    row = conn.execute(
        "SELECT device_id FROM devices WHERE device_alias = ?",
        (str(value),),
    ).fetchone()
    if row:
        return int(row[0])
    raise ValueError(
        f"No device found with alias {value!r}. "
        "Run 'make devices' to list registered devices and their aliases."
    )


def _get_fs_type(mount_point: str) -> str:
    """
    Get filesystem type for a mount point.

    Uses the `stat -f -c %T` command to determine the filesystem type.

    Args:
        mount_point: Path to check

    Returns:
        Filesystem type string (e.g., "zfs", "ext4", "btrfs") or "unknown" on error

    Examples:
        >>> _get_fs_type("/pool")
        'zfs'
        >>> _get_fs_type("/")
        'ext4'
    """
    try:
        result = subprocess.run(
            ['stat', '-f', '-c', '%T', mount_point],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return 'unknown'
    except Exception:
        return 'unknown'
