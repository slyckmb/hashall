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
