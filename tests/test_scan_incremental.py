"""
Tests for incremental scanning functionality.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from hashall.scan import load_existing_files, _canonicalize_root
from hashall.device import ensure_files_table
from hashall.model import connect_db


@pytest.fixture
def test_db():
    """Create a temporary test database with devices table."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    conn = connect_db(db_path)
    cursor = conn.cursor()

    # Create devices table (minimal schema needed for tests)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            fs_uuid TEXT PRIMARY KEY,
            device_id INTEGER NOT NULL UNIQUE,
            device_alias TEXT UNIQUE,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT,
            fs_type TEXT,
            first_scanned_at TEXT,
            last_scanned_at TEXT,
            scan_count INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            device_id_history TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    yield cursor

    conn.close()
    db_path.unlink()


def test_load_existing_files_returns_files_under_root(test_db):
    """Test that load_existing_files returns only files under the specified root."""
    cursor = test_db
    device_id = 49
    mount_point = "/pool"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, fs_type)
        VALUES (?, ?, ?, ?, ?)
    """, ("zfs-test-1", device_id, mount_point, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert test files
    test_files = [
        ("torrents/movie1.mkv", 1000000, 1234567890.0, "abc123", 'active'),
        ("torrents/tv/show1.mkv", 2000000, 1234567891.0, "def456", 'active'),
        ("torrents/tv/show2.mkv", 3000000, 1234567892.0, "ghi789", 'active'),
        ("backups/backup.tar.gz", 4000000, 1234567893.0, "jkl012", 'active'),
        ("other/file.txt", 5000, 1234567894.0, "mno345", 'active'),
    ]

    for path, size, mtime, sha1, status in test_files:
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, size, mtime, sha1, 1000, status))

    cursor.connection.commit()

    # Load files under /pool/torrents
    root_path = Path("/pool/torrents")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return only files under torrents/
    assert len(result) == 3
    assert "torrents/movie1.mkv" in result
    assert "torrents/tv/show1.mkv" in result
    assert "torrents/tv/show2.mkv" in result
    assert "backups/backup.tar.gz" not in result
    assert "other/file.txt" not in result

    # Verify structure of returned data
    assert result["torrents/movie1.mkv"]["size"] == 1000000
    assert result["torrents/movie1.mkv"]["mtime"] == 1234567890.0
    assert result["torrents/movie1.mkv"]["sha1"] == "abc123"


def test_load_existing_files_excludes_deleted_files(test_db):
    """Test that deleted files are not returned."""
    cursor = test_db
    device_id = 50
    mount_point = "/stash"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, fs_type)
        VALUES (?, ?, ?, ?, ?)
    """, ("zfs-test-2", device_id, mount_point, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert test files with different statuses
    test_files = [
        ("data/active1.txt", 1000, 1234567890.0, "aaa111", 'active'),
        ("data/active2.txt", 2000, 1234567891.0, "bbb222", 'active'),
        ("data/deleted.txt", 3000, 1234567892.0, "ccc333", 'deleted'),
        ("data/moved.txt", 4000, 1234567893.0, "ddd444", 'moved'),
    ]

    for path, size, mtime, sha1, status in test_files:
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, size, mtime, sha1, 2000, status))

    cursor.connection.commit()

    # Load files under /stash/data
    root_path = Path("/stash/data")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return only active files
    assert len(result) == 2
    assert "data/active1.txt" in result
    assert "data/active2.txt" in result
    assert "data/deleted.txt" not in result
    assert "data/moved.txt" not in result


def test_load_existing_files_mount_point_not_found(test_db):
    """Test that empty dict is returned when mount point is not found."""
    cursor = test_db
    device_id = 99

    # Don't insert device record - device doesn't exist

    # Try to load files
    root_path = Path("/nonexistent/path")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return empty dict
    assert result == {}


def test_load_existing_files_no_files_found(test_db):
    """Test that empty dict is returned when no files match."""
    cursor = test_db
    device_id = 51
    mount_point = "/backup"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, fs_type)
        VALUES (?, ?, ?, ?, ?)
    """, ("zfs-test-3", device_id, mount_point, mount_point, "zfs"))

    # Create files table but don't insert any files
    ensure_files_table(cursor, device_id)
    cursor.connection.commit()

    # Try to load files
    root_path = Path("/backup/empty")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return empty dict
    assert result == {}


def test_load_existing_files_path_not_under_mount(test_db):
    """Test that empty dict is returned when root_path is not under mount point."""
    cursor = test_db
    device_id = 52
    mount_point = "/pool"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, fs_type)
        VALUES (?, ?, ?, ?, ?)
    """, ("zfs-test-4", device_id, mount_point, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert test file
    cursor.execute(f"""
        INSERT INTO {table_name}
        (path, size, mtime, sha1, inode, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("data/file.txt", 1000, 1234567890.0, "eee555", 3000, 'active'))

    cursor.connection.commit()

    # Try to load files from a path not under mount point
    root_path = Path("/stash/data")  # mount_point is /pool, so this won't work
    result = load_existing_files(cursor, device_id, root_path)

    # Should return empty dict
    assert result == {}


def test_load_existing_files_uses_preferred_mount_point(test_db):
    """Test that preferred_mount_point is used for root scoping."""
    cursor = test_db
    device_id = 60
    mount_point = "/pool"
    preferred_mount = "/mnt/pool"

    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, fs_type)
        VALUES (?, ?, ?, ?, ?)
    """, ("zfs-test-5", device_id, mount_point, preferred_mount, "zfs"))

    table_name = ensure_files_table(cursor, device_id)

    cursor.execute(f"""
        INSERT INTO {table_name}
        (path, size, mtime, sha1, inode, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("torrents/movie1.mkv", 1000, 1234.0, "abc123", 3000, "active"))

    cursor.connection.commit()

    root_path = Path("/mnt/pool/torrents")
    result = load_existing_files(cursor, device_id, root_path)

    assert "torrents/movie1.mkv" in result


def test_canonicalize_root_remaps_to_preferred_mount():
    """Preferred mount point should be used to remap drifted roots when allowed."""
    root_path = Path("/mnt/pool/media")
    current_mount = Path("/mnt/pool")
    preferred_mount = Path("/pool")

    canonical = _canonicalize_root(
        root_path,
        current_mount,
        preferred_mount,
        allow_remap=True
    )

    assert canonical == Path("/pool/media")


def test_canonicalize_root_skips_remap_for_bind_mounts():
    """Do not remap when bind mounts are detected (allow_remap=False)."""
    root_path = Path("/mnt/pool/media")
    current_mount = Path("/mnt/pool")
    preferred_mount = Path("/pool")

    canonical = _canonicalize_root(
        root_path,
        current_mount,
        preferred_mount,
        allow_remap=False
    )

    assert canonical == root_path


def test_load_existing_files_root_is_mount_point(test_db):
    """Test loading files when root_path equals mount_point."""
    cursor = test_db
    device_id = 53
    mount_point = "/archive"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, fs_type)
        VALUES (?, ?, ?, ?)
    """, ("zfs-test-5", device_id, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert test files at root level (relative to mount point)
    test_files = [
        ("file1.txt", 1000, 1234567890.0, "fff666", 'active'),
        ("dir/file2.txt", 2000, 1234567891.0, "ggg777", 'active'),
    ]

    for path, size, mtime, sha1, status in test_files:
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, size, mtime, sha1, 4000, status))

    cursor.connection.commit()

    # Load files from mount point itself
    root_path = Path("/archive")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return all active files
    assert len(result) == 2
    assert "file1.txt" in result
    assert "dir/file2.txt" in result


def test_load_existing_files_handles_dot_relative_path(test_db):
    """Test that relative path of '.' (mount point == root) is handled correctly."""
    cursor = test_db
    device_id = 54
    mount_point = "/data"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, fs_type)
        VALUES (?, ?, ?, ?)
    """, ("zfs-test-6", device_id, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert test files stored with '.' as root
    test_files = [
        (".", 4096, 1234567890.0, "hhh888", 'active'),  # Directory itself
        ("file.txt", 1000, 1234567891.0, "iii999", 'active'),
    ]

    for path, size, mtime, sha1, status in test_files:
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, size, mtime, sha1, 5000, status))

    cursor.connection.commit()

    # Load files from mount point
    root_path = Path("/data")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return both entries (if '.' was stored)
    assert "." in result or "file.txt" in result
    # At minimum, we should get the file
    assert "file.txt" in result


def test_load_existing_files_nested_paths(test_db):
    """Test loading files with deeply nested paths."""
    cursor = test_db
    device_id = 55
    mount_point = "/media"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, fs_type)
        VALUES (?, ?, ?, ?)
    """, ("zfs-test-7", device_id, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert deeply nested files
    test_files = [
        ("movies/action/2024/movie1.mkv", 1000000, 1234567890.0, "jjj111", 'active'),
        ("movies/action/2024/movie2.mkv", 2000000, 1234567891.0, "kkk222", 'active'),
        ("movies/comedy/2023/movie3.mkv", 3000000, 1234567892.0, "lll333", 'active'),
        ("tv/drama/season1/episode1.mkv", 4000000, 1234567893.0, "mmm444", 'active'),
    ]

    for path, size, mtime, sha1, status in test_files:
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (path, size, mtime, sha1, 6000, status))

    cursor.connection.commit()

    # Load files under /media/movies/action
    root_path = Path("/media/movies/action")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return only action movies
    assert len(result) == 2
    assert "movies/action/2024/movie1.mkv" in result
    assert "movies/action/2024/movie2.mkv" in result
    assert "movies/comedy/2023/movie3.mkv" not in result
    assert "tv/drama/season1/episode1.mkv" not in result


def test_load_existing_files_sql_injection_safe(test_db):
    """Test that function is safe from SQL injection via path components."""
    cursor = test_db
    device_id = 56
    mount_point = "/test"

    # Insert device record
    cursor.execute("""
        INSERT INTO devices (fs_uuid, device_id, mount_point, fs_type)
        VALUES (?, ?, ?, ?)
    """, ("zfs-test-8", device_id, mount_point, "zfs"))

    # Create files table
    table_name = ensure_files_table(cursor, device_id)

    # Insert normal file
    cursor.execute(f"""
        INSERT INTO {table_name}
        (path, size, mtime, sha1, inode, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("data/normal.txt", 1000, 1234567890.0, "nnn555", 7000, 'active'))

    cursor.connection.commit()

    # Try with path containing SQL-like characters
    # This should safely fail to match, not cause SQL errors
    root_path = Path("/test/data' OR '1'='1")
    result = load_existing_files(cursor, device_id, root_path)

    # Should return empty (path doesn't exist) without SQL errors
    assert result == {}
