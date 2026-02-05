"""
Unit tests for link_analysis module.
"""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from hashall.link_analysis import (
    DuplicateGroup,
    AnalysisResult,
    analyze_device,
    format_analysis_text,
    format_analysis_json
)


@pytest.fixture
def test_db():
    """Create a test database with sample data."""
    # Create in-memory database
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Create devices table
    cursor.execute("""
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            device_alias TEXT,
            mount_point TEXT,
            fs_uuid TEXT,
            fs_type TEXT,
            total_files INTEGER,
            total_bytes INTEGER
        )
    """)

    # Create a test device
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (99, 'test_device', '/tmp/test', 'test-uuid-99')
    """)

    # Create files table for device 99
    cursor.execute("""
        CREATE TABLE files_99 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            quick_hash TEXT,
            sha1 TEXT,
            sha256 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
            discovered_under TEXT
        )
    """)

    # Insert test data: 3 files with same hash but different inodes (duplicates)
    test_data = [
        ('/test/file1.txt', 1000, 'hash1', 101),
        ('/test/file2.txt', 1000, 'hash1', 102),  # Duplicate of file1
        ('/test/file3.txt', 1000, 'hash1', 103),  # Duplicate of file1
        ('/test/unique1.txt', 2000, 'hash2', 201),  # Unique
        ('/test/dup1.txt', 500, 'hash3', 301),
        ('/test/dup2.txt', 500, 'hash3', 302),  # Duplicate of dup1
    ]

    for path, size, sha256, inode in test_data:
        cursor.execute("""
            INSERT INTO files_99 (path, size, sha256, inode, mtime, status)
            VALUES (?, ?, ?, ?, 1234567890.0, 'active')
        """, (path, size, sha256, inode))

    conn.commit()
    yield conn
    conn.close()


def test_duplicate_group_creation():
    """Test DuplicateGroup dataclass creation."""
    group = DuplicateGroup(
        hash='testhash',
        file_size=1000,
        file_count=3,
        unique_inodes=3,
        files=['/a', '/b', '/c'],
        inodes=[1, 2, 3],
        potential_savings=2000
    )

    assert group.hash == 'testhash'
    assert group.file_size == 1000
    assert group.file_count == 3
    assert group.potential_savings == 2000


def test_analysis_result_properties():
    """Test AnalysisResult computed properties."""
    groups = [
        DuplicateGroup('hash1', 1000, 3, 3, [], [], 2000),
        DuplicateGroup('hash2', 500, 2, 2, [], [], 500),
    ]

    result = AnalysisResult(
        device_id=99,
        device_alias='test',
        mount_point='/test',
        total_files=10,
        duplicate_groups=groups
    )

    assert result.total_duplicates == 5  # 3 + 2
    assert result.potential_bytes_saveable == 2500  # 2000 + 500


def test_analyze_device(test_db):
    """Test analyze_device function."""
    result = analyze_device(test_db, device_id=99, min_size=0)

    assert result.device_id == 99
    assert result.device_alias == 'test_device'
    assert result.mount_point == '/tmp/test'
    assert result.total_files == 6

    # Should find 2 duplicate groups (hash1 with 3 files, hash3 with 2 files)
    assert len(result.duplicate_groups) == 2

    # Check first group (hash1, 3 files, 1000 bytes each)
    group1 = result.duplicate_groups[0]
    assert group1.file_count == 3
    assert group1.unique_inodes == 3
    assert group1.file_size == 1000
    assert group1.potential_savings == 2000  # (3-1) * 1000

    # Check second group (hash3, 2 files, 500 bytes each)
    group2 = result.duplicate_groups[1]
    assert group2.file_count == 2
    assert group2.unique_inodes == 2
    assert group2.file_size == 500
    assert group2.potential_savings == 500  # (2-1) * 500


def test_analyze_device_min_size(test_db):
    """Test analyze_device with min_size filter."""
    # Only files >= 1000 bytes should be analyzed
    result = analyze_device(test_db, device_id=99, min_size=1000)

    # Should only find hash1 group (3 files, 1000 bytes each)
    # hash3 group should be filtered out (500 bytes < 1000)
    assert len(result.duplicate_groups) == 1
    assert result.duplicate_groups[0].file_size == 1000


def test_analyze_device_invalid_device(test_db):
    """Test analyze_device with invalid device_id."""
    with pytest.raises(ValueError, match="Device 999 not found"):
        analyze_device(test_db, device_id=999)


def test_format_analysis_text(test_db):
    """Test text formatting."""
    result = analyze_device(test_db, device_id=99)
    text = format_analysis_text(result)

    assert "🔍 Analyzing device: test_device" in text
    assert "Mount point: /tmp/test" in text
    assert "Total files: 6" in text
    assert "Duplicate groups found: 2" in text
    assert "Total duplicates: 5 files" in text
    assert "Potential space savings:" in text


def test_format_analysis_json(test_db):
    """Test JSON formatting."""
    import json

    result = analyze_device(test_db, device_id=99)
    json_str = format_analysis_json(result)

    # Parse JSON to verify it's valid
    data = json.loads(json_str)

    assert data['device_id'] == 99
    assert data['device_alias'] == 'test_device'
    assert data['total_files'] == 6
    assert data['analysis']['duplicate_groups'] == 2
    assert data['analysis']['total_duplicates'] == 5
    assert data['analysis']['potential_bytes_saveable'] == 2500

    # Check top groups
    assert len(data['analysis']['top_groups']) == 2
    assert data['analysis']['top_groups'][0]['file_count'] == 3
    assert data['analysis']['top_groups'][0]['potential_savings'] == 2000


def test_no_duplicates(test_db):
    """Test analysis when no duplicates exist."""
    cursor = test_db.cursor()

    # Create new device with no duplicates
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (100, 'unique_device', '/tmp/unique', 'test-uuid-100')
    """)

    cursor.execute("""
        CREATE TABLE files_100 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            sha256 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    # Insert files with unique hashes
    cursor.execute("""
        INSERT INTO files_100 (path, size, sha256, sha1, inode, mtime)
        VALUES
            ('/unique1.txt', 1000, 'unique_hash_1', 'legacy_hash_1', 1, 1234567890.0),
            ('/unique2.txt', 2000, 'unique_hash_2', 'legacy_hash_2', 2, 1234567890.0)
    """)

    test_db.commit()

    result = analyze_device(test_db, device_id=100)

    assert result.total_files == 2
    assert len(result.duplicate_groups) == 0
    assert result.total_duplicates == 0
    assert result.potential_bytes_saveable == 0

    # Check text output
    text = format_analysis_text(result)
    assert "No deduplication opportunities found" in text
