# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
import tempfile
from pathlib import Path

import pytest

from hashall.diff import diff_scan_sessions


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


def _entries_by_status(report):
    buckets = {"added": set(), "removed": set(), "changed": set()}
    for entry in report.entries:
        buckets[entry.status].add(entry.path)
    return buckets


def test_diff_scan_sessions_legacy_files_table(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE files (
            path TEXT NOT NULL,
            sha1 TEXT,
            sha256 TEXT,
            inode INTEGER,
            device_id INTEGER,
            scan_session_id INTEGER
        )
        """
    )

    src_id = 1
    dst_id = 2

    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/same.txt", "s1", "h1", 10, 1, src_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/remove.txt", "s2", "h2", 20, 1, src_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/change.txt", "sold", "hold", 30, 1, src_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/hardlink1", "s3", "h3", 40, 1, src_id),
    )

    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/same.txt", "s1-diff", "h1", 11, 1, dst_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/change.txt", "snew", "hnew", 31, 1, dst_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/added.txt", "s4", "h4", 50, 1, dst_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/hardlink2", "s3", "h3", 40, 1, dst_id),
    )

    conn.commit()

    report = diff_scan_sessions(conn, src_id, dst_id)
    buckets = _entries_by_status(report)

    assert "/added.txt" in buckets["added"]
    assert "/remove.txt" in buckets["removed"]
    assert "/change.txt" in buckets["changed"]
    assert "/hardlink1" not in buckets["removed"]
    assert "/hardlink2" not in buckets["added"]
    assert "/same.txt" not in buckets["changed"]

    conn.close()


def test_diff_scan_sessions_per_device_root_filter_and_hardlinks(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            mount_point TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE scan_sessions (
            id INTEGER PRIMARY KEY,
            device_id INTEGER NOT NULL,
            root_path TEXT NOT NULL
        )
        """
    )

    device_id = 7
    cursor.execute(
        "INSERT INTO devices (device_id, mount_point) VALUES (?, ?)",
        (device_id, "/pool"),
    )

    cursor.execute(
        """
        CREATE TABLE files_7 (
            path TEXT PRIMARY KEY,
            sha256 TEXT,
            sha1 TEXT,
            inode INTEGER,
            status TEXT
        )
        """
    )

    cursor.execute(
        """
        INSERT INTO files_7 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("media/alpha.txt", "ha", "sa", 1),
    )
    cursor.execute(
        """
        INSERT INTO files_7 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("media/hardlink1", "hh", "sh", 10),
    )
    cursor.execute(
        """
        INSERT INTO files_7 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("other/hardlink2", "hh", "sh", 10),
    )
    cursor.execute(
        """
        INSERT INTO files_7 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("other/bravo.txt", "hb", "sb", 2),
    )

    src_id = 1
    dst_id = 2
    cursor.execute(
        "INSERT INTO scan_sessions (id, device_id, root_path) VALUES (?, ?, ?)",
        (src_id, device_id, "/pool/media"),
    )
    cursor.execute(
        "INSERT INTO scan_sessions (id, device_id, root_path) VALUES (?, ?, ?)",
        (dst_id, device_id, "/pool/other"),
    )

    conn.commit()

    report = diff_scan_sessions(conn, src_id, dst_id)
    buckets = _entries_by_status(report)

    assert "/alpha.txt" in buckets["removed"]
    assert "/bravo.txt" in buckets["added"]
    assert "/hardlink1" not in buckets["removed"]
    assert "/hardlink2" not in buckets["added"]

    conn.close()


def test_diff_scan_sessions_per_device_detects_changes(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            mount_point TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE scan_sessions (
            id INTEGER PRIMARY KEY,
            device_id INTEGER NOT NULL,
            root_path TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        "INSERT INTO devices (device_id, mount_point) VALUES (?, ?)",
        (1, "/pool"),
    )
    cursor.execute(
        "INSERT INTO devices (device_id, mount_point) VALUES (?, ?)",
        (2, "/stash"),
    )

    cursor.execute(
        """
        CREATE TABLE files_1 (
            path TEXT PRIMARY KEY,
            sha256 TEXT,
            sha1 TEXT,
            inode INTEGER,
            status TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE files_2 (
            path TEXT PRIMARY KEY,
            sha256 TEXT,
            sha1 TEXT,
            inode INTEGER,
            status TEXT
        )
        """
    )

    cursor.execute(
        """
        INSERT INTO files_1 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("media/alpha.txt", "ha", "sa", 1),
    )
    cursor.execute(
        """
        INSERT INTO files_2 (path, sha256, sha1, inode, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        ("media/alpha.txt", "hb", "sb", 2),
    )

    src_id = 1
    dst_id = 2
    cursor.execute(
        "INSERT INTO scan_sessions (id, device_id, root_path) VALUES (?, ?, ?)",
        (src_id, 1, "/pool/media"),
    )
    cursor.execute(
        "INSERT INTO scan_sessions (id, device_id, root_path) VALUES (?, ?, ?)",
        (dst_id, 2, "/stash/media"),
    )

    conn.commit()

    report = diff_scan_sessions(conn, src_id, dst_id)
    buckets = _entries_by_status(report)

    assert "/alpha.txt" in buckets["changed"]

    conn.close()


def test_diff_scan_sessions_legacy_device_id_change_marks_changed(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE files (
            path TEXT NOT NULL,
            sha1 TEXT,
            sha256 TEXT,
            inode INTEGER,
            device_id INTEGER,
            scan_session_id INTEGER
        )
        """
    )

    src_id = 1
    dst_id = 2

    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/same.txt", "s1", "h1", 10, 1, src_id),
    )
    cursor.execute(
        """
        INSERT INTO files (path, sha1, sha256, inode, device_id, scan_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("/same.txt", "s1", "h1", 10, 2, dst_id),
    )

    conn.commit()

    report = diff_scan_sessions(conn, src_id, dst_id)
    buckets = _entries_by_status(report)

    assert "/same.txt" in buckets["changed"]

    conn.close()
