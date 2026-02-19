"""Tests for pool path normalization planning."""

import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.normalize import build_pool_path_normalization_batch


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL
        );

        CREATE TABLE rehome_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            payload_hash TEXT,
            status TEXT,
            source_path TEXT,
            target_path TEXT
        );
        """
    )


def test_normalize_plan_prefers_rehome_run_relative_target(tmp_path):
    db_path = tmp_path / "catalog.db"
    pool_root = tmp_path / "pool" / "data" / "seeds"
    stash_root = tmp_path / "stash" / "media" / "torrents" / "seeding"
    source = pool_root / "Stranger.Things.S02.mkv"
    target = pool_root / "cross-seed" / "FearNoPeer" / "Stranger.Things.S02.mkv"
    stash_source = stash_root / "cross-seed" / "FearNoPeer" / "Stranger.Things.S02.mkv"

    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"abc")
    target.write_bytes(b"abc")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash01', 44, ?, 1, 3, 'complete')
        """,
        (str(source),),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('thash1', 1, 44, ?, ?)
        """,
        (str(target.parent), target.name),
    )
    conn.execute(
        """
        INSERT INTO rehome_runs (direction, payload_hash, status, source_path, target_path)
        VALUES ('demote', 'hash01', 'success', ?, ?)
        """,
        (str(stash_source), str(source)),
    )
    conn.commit()
    conn.close()

    report = build_pool_path_normalization_batch(
        catalog_path=db_path,
        pool_device=44,
        pool_seeding_root=str(pool_root),
        stash_seeding_root=str(stash_root),
        flat_only=True,
    )

    assert report["summary"]["candidates"] == 1
    assert report["summary"]["decision_reuse"] == 1
    plan = report["plans"][0]
    assert plan["source_path"] == str(source)
    assert plan["target_path"] == str(target)
    assert plan["decision"] == "REUSE"
    assert plan["affected_torrents"] == ["thash1"]


def test_normalize_plan_respects_flat_only_filter(tmp_path):
    db_path = tmp_path / "catalog.db"
    pool_root = tmp_path / "pool" / "data" / "seeds"
    stash_root = tmp_path / "stash" / "media" / "torrents" / "seeding"
    source = pool_root / "_flat" / "Movie.2024.mkv"
    target = pool_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    stash_source = stash_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"

    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"xyz")
    target.write_bytes(b"xyz")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (2, 'hash02', 44, ?, 1, 3, 'complete')
        """,
        (str(source),),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('thash2', 2, 44, ?, ?)
        """,
        (str(target.parent), target.name),
    )
    conn.execute(
        """
        INSERT INTO rehome_runs (direction, payload_hash, status, source_path, target_path)
        VALUES ('demote', 'hash02', 'success', ?, ?)
        """,
        (str(stash_source), str(source)),
    )
    conn.commit()
    conn.close()

    flat_report = build_pool_path_normalization_batch(
        catalog_path=db_path,
        pool_device=44,
        pool_seeding_root=str(pool_root),
        stash_seeding_root=str(stash_root),
        flat_only=True,
    )
    all_report = build_pool_path_normalization_batch(
        catalog_path=db_path,
        pool_device=44,
        pool_seeding_root=str(pool_root),
        stash_seeding_root=str(stash_root),
        flat_only=False,
    )

    assert flat_report["summary"]["candidates"] == 0
    assert all_report["summary"]["candidates"] == 1
