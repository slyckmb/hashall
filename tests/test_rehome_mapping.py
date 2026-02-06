"""
Tests for rehome save_path mapping.
"""

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.planner import DemotionPlanner


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
        stash_device=50,
        pool_device=49,
        stash_seeding_root="/stash/torrents/seeding",
        pool_seeding_root="/pool/data"
    )

    plan = planner.plan_demotion("torrent_map")
    assert plan["decision"] != "BLOCK"
    assert plan.get("view_targets")
    assert plan["view_targets"][0]["target_save_path"] == "/pool/data"
