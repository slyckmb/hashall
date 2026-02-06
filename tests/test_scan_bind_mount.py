"""
Tests that scan uses canonicalized bind-mount sources.
"""

import os
import sqlite3
from pathlib import Path

import hashall.scan as scan


def test_scan_uses_canonical_bind_source(tmp_path, monkeypatch):
    db_path = tmp_path / "catalog.db"

    real_root = tmp_path / "stash" / "media"
    alias_root = tmp_path / "data" / "media"
    real_root.mkdir(parents=True)
    alias_root.mkdir(parents=True)

    (real_root / "file.txt").write_text("data")

    def fake_canonicalize_path(path: Path) -> Path:
        if path == alias_root:
            return real_root
        return path

    monkeypatch.setattr(scan, "canonicalize_path", fake_canonicalize_path)

    scan.scan_path(db_path=db_path, root_path=alias_root)

    conn = sqlite3.connect(db_path)
    try:
        root_rows = conn.execute("SELECT root_path FROM scan_roots").fetchall()
        assert str(real_root) in {row[0] for row in root_rows}

        device_id = os.stat(real_root).st_dev
        count = conn.execute(
            f"SELECT COUNT(*) FROM files_{device_id} WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 1
