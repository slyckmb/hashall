"""Tests for hardlink-aware hashing optimization in scan.py."""

import os
import sqlite3
from pathlib import Path

import pytest

from hashall.scan import scan_path
from hashall.model import connect_db


def test_inode_grouping_with_hardlinks(tmp_path):
    """Test that hardlinked files are grouped by inode and share hash."""
    # Create original file
    original = tmp_path / "original.txt"
    original.write_text("This is test content for hardlink detection")

    # Create hardlinks
    link1 = tmp_path / "link1.txt"
    link2 = tmp_path / "link2.txt"
    os.link(original, link1)
    os.link(original, link2)

    # Scan directory with full hash mode
    # Put catalog DB outside scan directory to avoid scanning it
    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    stats = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    # Verify stats: 3 files scanned, 1 inode hashed, 2 hardlinks propagated
    assert stats.files_scanned == 3
    assert stats.inode_groups_hashed == 1
    assert stats.hardlinks_propagated == 2

    # Verify all 3 files have same SHA256
    conn = connect_db(db_path)
    cursor = conn.cursor()
    device_id = os.stat(tmp_path).st_dev
    table_name = f"files_{device_id}"

    rows = cursor.execute(f"""
        SELECT path, sha256, hash_source, inode
        FROM {table_name}
        WHERE status = 'active'
        ORDER BY path
    """).fetchall()

    assert len(rows) == 3

    # All have same SHA256
    sha256_values = [r[1] for r in rows]
    assert sha256_values[0] == sha256_values[1] == sha256_values[2]
    assert sha256_values[0] is not None

    # One is 'calculated', two are 'inode:N'
    sources = [r[2] for r in rows]
    inode = rows[0][3]

    assert sources.count('calculated') == 1
    assert sources.count(f'inode:{inode}') == 2

    conn.close()


def test_hardlink_hash_propagation_efficiency(tmp_path):
    """Test that hardlinks are only hashed once."""
    # Create 100 hardlinks to same 1MB file
    original = tmp_path / "original.bin"
    original.write_bytes(b"x" * (1024 * 1024))  # 1MB

    for i in range(99):
        link = tmp_path / f"link{i:03d}.bin"
        os.link(original, link)

    # Scan with full hash mode
    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    stats = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    # Verify: 100 files scanned, only 1 MB hashed
    assert stats.files_scanned == 100
    assert stats.bytes_hashed == 1024 * 1024  # Only 1 MB
    assert stats.inode_groups_hashed == 1
    assert stats.hardlinks_propagated == 99


def test_mixed_hardlinks_and_unique_files(tmp_path):
    """Test correct handling of mix of hardlinks and unique files."""
    # 3 hardlinks to file A
    fileA = tmp_path / "A.txt"
    fileA.write_text("Content A")
    os.link(fileA, tmp_path / "A_link1.txt")
    os.link(fileA, tmp_path / "A_link2.txt")

    # 2 hardlinks to file B
    fileB = tmp_path / "B.txt"
    fileB.write_text("Content B")
    os.link(fileB, tmp_path / "B_link1.txt")

    # 1 unique file C (no hardlinks)
    fileC = tmp_path / "C.txt"
    fileC.write_text("Content C")

    # Scan
    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    stats = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    # Verify stats
    assert stats.files_scanned == 6  # Total files
    assert stats.inode_groups_hashed == 3  # A, B, C (each hashed once)
    assert stats.hardlinks_propagated == 3  # 2 for A, 1 for B, 0 for C

    # Verify database
    conn = connect_db(db_path)
    cursor = conn.cursor()
    device_id = os.stat(tmp_path).st_dev
    table_name = f"files_{device_id}"

    # Group files by inode
    rows = cursor.execute(f"""
        SELECT inode, COUNT(*), GROUP_CONCAT(path ORDER BY path)
        FROM {table_name}
        WHERE status = 'active'
        GROUP BY inode
        ORDER BY COUNT(*) DESC
    """).fetchall()

    assert len(rows) == 3  # 3 unique inodes
    # First group: 3 files (A and its links)
    assert rows[0][1] == 3
    # Second group: 2 files (B and its link)
    assert rows[1][1] == 2
    # Third group: 1 file (C alone)
    assert rows[2][1] == 1

    conn.close()


def test_rescan_with_hardlinks(tmp_path):
    """Test that incremental scan handles hardlinks correctly."""
    # Initial scan: create 2 hardlinks
    original = tmp_path / "original.txt"
    original.write_text("Initial content")
    link1 = tmp_path / "link1.txt"
    os.link(original, link1)

    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    stats1 = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    assert stats1.files_scanned == 2
    assert stats1.inode_groups_hashed == 1
    assert stats1.hardlinks_propagated == 1

    # Get initial SHA256
    conn = connect_db(db_path)
    cursor = conn.cursor()
    device_id = os.stat(tmp_path).st_dev
    table_name = f"files_{device_id}"

    # Path is relative to tmp_path, so use basename
    initial_sha256_row = cursor.execute(f"""
        SELECT sha256 FROM {table_name} WHERE path LIKE '%original.txt%'
    """).fetchone()
    assert initial_sha256_row is not None
    initial_sha256 = initial_sha256_row[0]

    # Rescan without changes (should be unchanged)
    stats2 = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    assert stats2.files_scanned == 2
    assert stats2.files_unchanged == 2
    assert stats2.bytes_hashed == 0  # Nothing re-hashed

    # Add a third hardlink and rescan
    link2 = tmp_path / "link2.txt"
    os.link(original, link2)

    stats3 = scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    # Should detect new file but reuse hash from existing hardlinks
    assert stats3.files_scanned == 3
    assert stats3.files_added == 1  # link2 is new
    assert stats3.files_unchanged == 2  # original and link1 unchanged

    # Verify all 3 have same SHA256
    rows = cursor.execute(f"""
        SELECT sha256 FROM {table_name} WHERE status = 'active' ORDER BY path
    """).fetchall()

    assert len(rows) == 3
    assert all(r[0] == initial_sha256 for r in rows)

    conn.close()


def test_hash_source_tracking(tmp_path):
    """Test that hash_source column correctly tracks calculated vs copied."""
    # Create hardlinks
    original = tmp_path / "file1.txt"
    original.write_text("Test data")
    link = tmp_path / "file2.txt"
    os.link(original, link)

    # Create unique file
    unique = tmp_path / "file3.txt"
    unique.write_text("Different data")

    # Scan
    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    scan_path(db_path, tmp_path, hash_mode='full', quiet=True)

    # Check hash_source values
    conn = connect_db(db_path)
    cursor = conn.cursor()
    device_id = os.stat(tmp_path).st_dev
    table_name = f"files_{device_id}"

    rows = cursor.execute(f"""
        SELECT path, hash_source, inode
        FROM {table_name}
        WHERE status = 'active'
        ORDER BY path
    """).fetchall()

    assert len(rows) == 3

    # file1.txt and file2.txt share inode (use LIKE for path matching)
    file1_source = next(r[1] for r in rows if 'file1.txt' in r[0])
    file2_source = next(r[1] for r in rows if 'file2.txt' in r[0])
    file3_source = next(r[1] for r in rows if 'file3.txt' in r[0])

    # One of the hardlinks should be 'calculated', the other 'inode:N'
    inode = rows[0][2]
    assert {file1_source, file2_source} == {'calculated', f'inode:{inode}'}

    # Unique file should be 'calculated'
    assert file3_source == 'calculated'

    conn.close()


def test_parallel_scan_with_hardlinks(tmp_path):
    """Test that parallel scanning correctly handles hardlinks."""
    # Create many hardlinks to test parallel processing
    original = tmp_path / "base.bin"
    original.write_bytes(b"a" * 100000)  # 100KB

    for i in range(50):
        link = tmp_path / f"link{i:03d}.bin"
        os.link(original, link)

    # Scan with parallel mode
    db_path = tmp_path.parent / f"{tmp_path.name}_catalog.db"
    stats = scan_path(
        db_path,
        tmp_path,
        hash_mode='full',
        parallel=True,
        workers=4,
        quiet=True
    )

    # Verify efficiency
    assert stats.files_scanned == 51  # original + 50 links
    assert stats.inode_groups_hashed == 1  # Only hashed once
    assert stats.hardlinks_propagated == 50  # 50 copied
    assert stats.bytes_hashed == 100000  # Only 100KB hashed, not 5.1MB

    # Verify all have same hash
    conn = connect_db(db_path)
    cursor = conn.cursor()
    device_id = os.stat(tmp_path).st_dev
    table_name = f"files_{device_id}"

    sha256_values = cursor.execute(f"""
        SELECT DISTINCT sha256 FROM {table_name} WHERE status = 'active'
    """).fetchall()

    # Only one unique SHA256 value
    assert len(sha256_values) == 1
    assert sha256_values[0][0] is not None

    conn.close()
