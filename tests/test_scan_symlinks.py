"""
Tests for scan symlink handling.
"""

import os
import sqlite3
from pathlib import Path

from hashall.scan import scan_path


def test_scan_skips_symlinked_files(tmp_path):
    db_path = tmp_path / "catalog.db"
    root = tmp_path / "root"
    root.mkdir()

    real_file = root / "file.txt"
    real_file.write_text("data")

    symlink = root / "file_link.txt"
    os.symlink(real_file, symlink)

    scan_path(db_path=db_path, root_path=root)

    device_id = os.stat(root).st_dev
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM files_{device_id} WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        conn.close()

    # Only the real file should be indexed
    assert count == 1
