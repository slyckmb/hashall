"""
Tests for rehome save_path mapping.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.planner import DemotionPlanner
from rehome.normalize import DEFAULT_UNIQUE_VIEW_SUBDIR


def test_plan_includes_view_targets(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)

    payload_root = "/stash/torrents/seeding/Movie.2024"

    conn.executescript(f"""
        CREATE TABLE files_50 (
            path TEXT PRIMARY KEY,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );

        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            fs_uuid TEXT,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT
        );

        CREATE TABLE scan_roots (
            fs_uuid TEXT,
            root_path TEXT,
            last_scanned_at TEXT,
            scan_count INTEGER,
            PRIMARY KEY (fs_uuid, root_path)
        );

        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-test-50', '/stash', '/stash');

        INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
        VALUES ('fs-test-50', '/stash/torrents/seeding', '2026-02-06', 1);

        INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
            ('torrents/seeding/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123', 'active');

        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'payload_hash_123', 50, '{payload_root}', 1, 1000000, 'complete');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('torrent_map', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
    """)
    conn.commit()
    conn.close()

    planner = DemotionPlanner(
        catalog_path=db_path,
        seeding_roots=["/stash/torrents/seeding"],
        library_roots=[],
        stash_device=50,
        pool_device=49,
        stash_seeding_root="/stash/torrents/seeding",
        pool_seeding_root="/pool/data"
    )

    plan = planner.plan_demotion("torrent_map")
    assert plan["decision"] != "BLOCK"
    assert plan.get("view_targets")
    # Single-torrent payloads now use the same unique-view scheme as multi-torrent
    # payloads to prevent target collisions and state mismatches if a cross-seed
    # is added after initial demotion.
    assert plan["view_targets"][0]["target_save_path"] == "/pool/data/_rehome-unique/torrent_map"


def test_move_target_preserves_seeding_relative_structure(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)

    payload_root = "/stash/media/torrents/seeding/cross-seed/FearNoPeer/Show.S01"

    conn.executescript(f"""
        CREATE TABLE files_49 (
            path TEXT PRIMARY KEY,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );

        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            fs_uuid TEXT,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT
        );

        CREATE TABLE scan_roots (
            fs_uuid TEXT,
            root_path TEXT,
            last_scanned_at TEXT,
            scan_count INTEGER,
            PRIMARY KEY (fs_uuid, root_path)
        );

        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (49, 'dev-49', '/stash/media', '/stash/media');

        INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
        VALUES ('dev-49', '/stash/media/torrents/seeding', '2026-02-19', 1);

        INSERT INTO files_49 (path, inode, size, mtime, sha1, status) VALUES
            ('torrents/seeding/cross-seed/FearNoPeer/Show.S01/ep01.mkv', 2001, 1000, 1234567890, 'sha1', 'active');

        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'payload_hash_abc', 49, '{payload_root}', 1, 1000, 'complete');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('torrent_struct', 1, 49, '/stash/media/torrents/seeding/cross-seed/FearNoPeer', 'Show.S01');
    """)
    conn.commit()
    conn.close()

    planner = DemotionPlanner(
        catalog_path=db_path,
        seeding_roots=["/stash/media/torrents/seeding"],
        library_roots=[],
        stash_device=49,
        pool_device=44,
        stash_seeding_root="/stash/media/torrents/seeding",
        pool_seeding_root="/pool/data/seeds",
    )

    plan = planner.plan_demotion("torrent_struct")
    assert plan["decision"] == "MOVE"
    assert plan["target_path"] == "/pool/data/seeds/cross-seed/FearNoPeer/Show.S01"


def test_plan_builds_unique_view_targets_for_multi_hash_payload_group(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)

    payload_root = "/stash/media/torrents/seeding/cross-seed/FearNoPeer/Show.S01"

    conn.executescript(f"""
        CREATE TABLE files_49 (
            path TEXT PRIMARY KEY,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );

        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            fs_uuid TEXT,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT
        );

        CREATE TABLE scan_roots (
            fs_uuid TEXT,
            root_path TEXT,
            last_scanned_at TEXT,
            scan_count INTEGER,
            PRIMARY KEY (fs_uuid, root_path)
        );

        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (49, 'dev-49', '/stash/media', '/stash/media');

        INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
        VALUES ('dev-49', '/stash/media/torrents/seeding', '2026-02-19', 1);

        INSERT INTO files_49 (path, inode, size, mtime, sha1, status) VALUES
            ('torrents/seeding/cross-seed/FearNoPeer/Show.S01/ep01.mkv', 2001, 1000, 1234567890, 'sha1', 'active');

        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'payload_hash_multi', 49, '{payload_root}', 1, 1000, 'complete');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('torrent_multi_a', 1, 49, '/stash/media/torrents/seeding/cross-seed/FearNoPeer', 'Show.S01');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('torrent_multi_b', 1, 49, '/stash/media/torrents/seeding/cross-seed/FearNoPeer', 'Show.S01');
    """)
    conn.commit()
    conn.close()

    planner = DemotionPlanner(
        catalog_path=db_path,
        seeding_roots=["/stash/media/torrents/seeding"],
        library_roots=[],
        stash_device=49,
        pool_device=44,
        stash_seeding_root="/stash/media/torrents/seeding",
        pool_seeding_root="/pool/media/torrents/seeding",
    )

    plan = planner.plan_demotion("torrent_multi_a")
    assert plan["decision"] == "MOVE"
    assert sorted(plan["affected_torrents"]) == ["torrent_multi_a", "torrent_multi_b"]
    by_hash = {target["torrent_hash"]: target for target in plan["view_targets"]}
    assert by_hash["torrent_multi_a"]["target_save_path"] == (
        f"/pool/media/torrents/seeding/{DEFAULT_UNIQUE_VIEW_SUBDIR}/torrent_multi_a"
    )
    assert by_hash["torrent_multi_b"]["target_save_path"] == (
        f"/pool/media/torrents/seeding/{DEFAULT_UNIQUE_VIEW_SUBDIR}/torrent_multi_b"
    )
