"""
Tests for cross-device duplicate analysis.
"""

import sqlite3
import tempfile
from pathlib import Path

from hashall.device import ensure_files_table
from hashall.link_analysis import analyze_cross_device


def test_analyze_cross_device_duplicates():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    ensure_files_table(cursor, 49)
    ensure_files_table(cursor, 50)

    cursor.execute(
        "INSERT INTO files_49 (path, size, mtime, sha256, inode, status) VALUES (?, ?, ?, ?, ?, 'active')",
        ("movies/a.mkv", 1000, 1234.0, "hash123", 1001),
    )
    cursor.execute(
        "INSERT INTO files_50 (path, size, mtime, sha256, inode, status) VALUES (?, ?, ?, ?, ?, 'active')",
        ("movies/a.mkv", 1000, 1234.0, "hash123", 2001),
    )
    conn.commit()

    result = analyze_cross_device(conn, min_size=0)
    assert len(result.duplicate_groups) == 1
    group = result.duplicate_groups[0]
    assert group.device_count == 2
    assert group.file_count == 2

    conn.close()
    db_path.unlink()


def test_analyze_cross_device_duplicates_with_stable_files_table_binding():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            device_alias TEXT,
            mount_point TEXT,
            preferred_mount_point TEXT,
            fs_uuid TEXT,
            files_table TEXT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO devices (device_id, device_alias, mount_point, preferred_mount_point, fs_uuid)
        VALUES (49, 'pool-a', '/pool/a', '/pool/a', 'zfs-pool-a')
        """
    )
    cursor.execute(
        """
        INSERT INTO devices (device_id, device_alias, mount_point, preferred_mount_point, fs_uuid)
        VALUES (50, 'pool-b', '/pool/b', '/pool/b', 'zfs-pool-b')
        """
    )

    table_49 = ensure_files_table(cursor, 49, fs_uuid="zfs-pool-a")
    table_50 = ensure_files_table(cursor, 50, fs_uuid="zfs-pool-b")
    assert table_49 != "files_49"
    assert table_50 != "files_50"

    cursor.execute(
        f"INSERT INTO {table_49} (path, size, mtime, sha256, inode, status) VALUES (?, ?, ?, ?, ?, 'active')",
        ("movies/a.mkv", 1000, 1234.0, "hash123", 1001),
    )
    cursor.execute(
        f"INSERT INTO {table_50} (path, size, mtime, sha256, inode, status) VALUES (?, ?, ?, ?, ?, 'active')",
        ("movies/a.mkv", 1000, 1234.0, "hash123", 2001),
    )
    conn.commit()

    result = analyze_cross_device(conn, min_size=0)
    assert len(result.duplicate_groups) == 1
    group = result.duplicate_groups[0]
    assert group.device_count == 2
    assert group.file_count == 2

    conn.close()
    db_path.unlink()
