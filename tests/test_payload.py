"""
Tests for payload identity functionality.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from hashall.payload import (
    PayloadFile, compute_payload_hash, build_payload,
    upsert_payload, get_torrent_siblings, Payload
)
from hashall.model import connect_db


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    # Connect and initialize
    conn = connect_db(db_path)

    # Create per-device files table
    device_id = 49
    cursor = conn.cursor()

    # Create files_49 table
    from hashall.device import ensure_files_table
    ensure_files_table(cursor, device_id)

    # Insert test files into device-specific table
    test_files = [
        ("/test/root/file1.txt", 100, "aaa111", 12345),
        ("/test/root/file2.txt", 200, "bbb222", 12346),
        ("/test/root/subdir/file3.txt", 300, "ccc333", 12347),
    ]

    for path, size, sha256, inode in test_files:
        cursor.execute(f"""
            INSERT INTO files_{device_id} (path, size, mtime, sha256, inode, status)
            VALUES (?, ?, 1234567890.0, ?, ?, 'active')
        """, (path, size, sha256, inode))

    conn.commit()

    yield conn

    conn.close()
    db_path.unlink()


def test_compute_payload_hash_deterministic():
    """Test that payload hash is deterministic."""
    files = [
        PayloadFile("b.txt", 200, "bbb222"),
        PayloadFile("a.txt", 100, "aaa111"),
        PayloadFile("c.txt", 300, "ccc333"),
    ]

    hash1 = compute_payload_hash(files)
    hash2 = compute_payload_hash(files)

    assert hash1 == hash2
    assert hash1 is not None
    assert len(hash1) == 64  # SHA256 hex digest


def test_compute_payload_hash_sorted():
    """Test that file order doesn't affect hash."""
    files1 = [
        PayloadFile("a.txt", 100, "aaa111"),
        PayloadFile("b.txt", 200, "bbb222"),
    ]

    files2 = [
        PayloadFile("b.txt", 200, "bbb222"),
        PayloadFile("a.txt", 100, "aaa111"),
    ]

    hash1 = compute_payload_hash(files1)
    hash2 = compute_payload_hash(files2)

    assert hash1 == hash2


def test_compute_payload_hash_incomplete():
    """Test that incomplete files (missing SHA256) return None."""
    files = [
        PayloadFile("a.txt", 100, "aaa111"),
        PayloadFile("b.txt", 200, None),  # Missing SHA256
    ]

    hash_result = compute_payload_hash(files)
    assert hash_result is None


def test_build_payload_complete(test_db):
    """Test building a complete payload."""
    # Test files exist in test_db
    payload = build_payload(test_db, "/test/root", device_id=49)

    assert payload.file_count == 3
    assert payload.total_bytes == 600  # 100 + 200 + 300
    assert payload.status == 'complete'
    assert payload.payload_hash is not None
    assert payload.last_built_at is not None


def test_build_payload_empty(test_db):
    """Test building payload for non-existent path."""
    payload = build_payload(test_db, "/nonexistent/path", device_id=49)

    assert payload.file_count == 0
    assert payload.total_bytes == 0
    assert payload.status == 'incomplete'
    assert payload.payload_hash is None


def test_upsert_payload(test_db):
    """Test inserting and updating payloads."""
    # Create payload
    payload = Payload(
        payload_id=None,
        payload_hash="abc123",
        device_id=49,
        root_path="/test/payload1",
        file_count=10,
        total_bytes=1000,
        status='complete',
        last_built_at=1234567890.0
    )

    # Insert
    payload_id = upsert_payload(test_db, payload)
    assert payload_id is not None
    assert payload_id > 0

    # Verify
    row = test_db.execute(
        "SELECT * FROM payloads WHERE payload_id = ?",
        (payload_id,)
    ).fetchone()
    assert row is not None
    assert row[1] == "abc123"  # payload_hash
    assert row[4] == 10  # file_count

    # Update
    payload.file_count = 15
    payload_id2 = upsert_payload(test_db, payload)
    assert payload_id2 == payload_id  # Same ID

    # Verify update
    row = test_db.execute(
        "SELECT file_count FROM payloads WHERE payload_id = ?",
        (payload_id,)
    ).fetchone()
    assert row[0] == 15


def test_torrent_siblings(test_db):
    """Test finding torrent siblings."""
    from hashall.payload import upsert_torrent_instance, TorrentInstance
    import time

    # Create a payload
    payload = Payload(
        payload_id=None,
        payload_hash="shared_hash",
        device_id=49,
        root_path="/test/shared",
        file_count=5,
        total_bytes=500,
        status='complete',
        last_built_at=time.time()
    )
    payload_id = upsert_payload(test_db, payload)

    # Create multiple torrents pointing to same payload
    torrents = [
        TorrentInstance(
            torrent_hash="hash1",
            payload_id=payload_id,
            device_id=49,
            save_path="/test",
            root_name="torrent1",
            category="test",
            tags="tag1",
            last_seen_at=time.time()
        ),
        TorrentInstance(
            torrent_hash="hash2",
            payload_id=payload_id,
            device_id=49,
            save_path="/test",
            root_name="torrent2",
            category="test",
            tags="tag2",
            last_seen_at=time.time()
        ),
        TorrentInstance(
            torrent_hash="hash3",
            payload_id=payload_id,
            device_id=49,
            save_path="/test",
            root_name="torrent3",
            category="other",
            tags="tag3",
            last_seen_at=time.time()
        ),
    ]

    for torrent in torrents:
        upsert_torrent_instance(test_db, torrent)

    # Test siblings
    siblings = get_torrent_siblings(test_db, "hash1")
    assert len(siblings) == 3
    assert "hash1" in siblings
    assert "hash2" in siblings
    assert "hash3" in siblings

    # Test from different torrent
    siblings2 = get_torrent_siblings(test_db, "hash2")
    assert siblings == siblings2


def test_different_payloads_different_hashes():
    """Test that different file sets produce different hashes."""
    files1 = [
        PayloadFile("a.txt", 100, "aaa111"),
        PayloadFile("b.txt", 200, "bbb222"),
    ]

    files2 = [
        PayloadFile("a.txt", 100, "aaa111"),
        PayloadFile("c.txt", 300, "ccc333"),  # Different file
    ]

    hash1 = compute_payload_hash(files1)
    hash2 = compute_payload_hash(files2)

    assert hash1 != hash2


def test_idempotent_sync(test_db):
    """Test that syncing same payload multiple times is idempotent."""
    from hashall.payload import upsert_torrent_instance, TorrentInstance
    import time

    # Create payload
    payload = build_payload(test_db, "/test/root", device_id=49)
    payload_id = upsert_payload(test_db, payload)

    # Sync torrent once
    torrent = TorrentInstance(
        torrent_hash="test_hash",
        payload_id=payload_id,
        device_id=49,
        save_path="/test",
        root_name="test_torrent",
        category="test",
        tags="tag1",
        last_seen_at=time.time()
    )
    upsert_torrent_instance(test_db, torrent)

    # Count rows
    count1 = test_db.execute(
        "SELECT COUNT(*) FROM torrent_instances"
    ).fetchone()[0]

    # Sync again (idempotent)
    torrent.tags = "tag1,tag2"  # Updated tags
    upsert_torrent_instance(test_db, torrent)

    # Count should be same
    count2 = test_db.execute(
        "SELECT COUNT(*) FROM torrent_instances"
    ).fetchone()[0]
    assert count1 == count2 == 1

    # Verify tags were updated
    row = test_db.execute(
        "SELECT tags FROM torrent_instances WHERE torrent_hash = ?",
        ("test_hash",)
    ).fetchone()
    assert row[0] == "tag1,tag2"
