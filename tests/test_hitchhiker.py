"""Tests for hitchhiker module — N→1 payload group detection and SQL limit correctness."""

import sqlite3

import pytest

from hashall.hitchhiker import query_hitchhiker_groups


@pytest.fixture
def hitchhiker_db(tmp_path):
    """
    Minimal DB with 3 hitchhiker groups (payload_id 1, 2, 3), each with 2 hashes.
    Total rows: 6 torrent_instances.
    """
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 1000
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '/data/media/torrents/seeding/tv',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    for pid in range(1, 4):
        conn.execute(
            "INSERT INTO payloads VALUES (?, ?, 1, 1000)",
            (pid, f"/data/media/torrents/seeding/tv/root{pid}"),
        )
        for h_suffix in range(2):
            conn.execute(
                "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, ?)",
                (f"{'a' * 38}{pid}{h_suffix}", pid),
            )
    conn.commit()
    conn.close()
    return str(db)


def test_query_no_limit_returns_all_groups(hitchhiker_db):
    rows = query_hitchhiker_groups(db_path=hitchhiker_db)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 3, f"Expected 3 groups, got {payload_ids}"
    assert len(rows) == 6, f"Expected 6 rows (3 groups × 2 hashes), got {len(rows)}"


def test_query_limit_1_returns_one_complete_group(hitchhiker_db):
    """LIMIT 1 must return 1 complete group (2 rows), not 1 row from a group."""
    rows = query_hitchhiker_groups(db_path=hitchhiker_db, limit=1)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 1, f"Expected 1 group, got {payload_ids}"
    assert len(rows) == 2, (
        f"LIMIT=1 should return all rows for 1 group (2 rows), got {len(rows)} — "
        f"SQL limit may be applying to rows rather than groups"
    )


def test_query_limit_2_returns_two_complete_groups(hitchhiker_db):
    """LIMIT 2 must return 2 complete groups (4 rows)."""
    rows = query_hitchhiker_groups(db_path=hitchhiker_db, limit=2)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 2
    assert len(rows) == 4


def test_query_no_hitchhiker_groups(tmp_path):
    """DB with only singleton groups returns empty list."""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 0
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    conn.execute("INSERT INTO payloads VALUES (1, '/seeding/tv/root1', 1, 0)")
    conn.execute("INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES ('aaa', 1)")
    conn.commit()
    conn.close()

    rows = query_hitchhiker_groups(db_path=str(db))
    assert rows == []
