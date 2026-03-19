"""
Tests for rehome demotion functionality.

Covers:
- External consumer detection (BLOCK case)
- REUSE decision when payload exists on pool
- MOVE decision when payload doesn't exist on pool
- Dry-run produces no side effects
"""

import pytest
import sqlite3
import json
import tempfile
from pathlib import Path
from typing import List

# Import rehome modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.planner import DemotionPlanner, ExternalConsumer
from rehome.executor import DemotionExecutor


class TestDatabase:
    """Helper class to create test database with payload schema."""

    @staticmethod
    def create_test_db(tmp_path: Path) -> Path:
        """Create a test database with payload tables."""
        db_path = tmp_path / "test_catalog.db"
        conn = sqlite3.connect(db_path)

        # Create minimal schema for testing
        conn.executescript("""
            -- Per-device files tables (used by current hashall)
            -- We'll create files_49 (pool) and files_50 (stash) for testing
            CREATE TABLE files_49 (
                path TEXT PRIMARY KEY,
                inode INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha1 TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                discovered_under TEXT
            );

            CREATE TABLE files_50 (
                path TEXT PRIMARY KEY,
                inode INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha1 TEXT,
                first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                discovered_under TEXT
            );

            -- Payload tables (Stage 2)
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
        """)

        conn.commit()
        conn.close()
        return db_path


class TestExternalConsumerDetection:
    """Test external consumer detection logic."""

    def test_block_when_external_consumer_detected(self, tmp_path):
        """Test that plan is BLOCKED when external consumers exist."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test data:
        # - Payload on stash with 2 files
        # - One file has a hardlink outside seeding domain
        payload_root = "/stash/torrents/seeding/Movie.2024"

        # Insert files into per-device table (device 50 = stash)
        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
            VALUES (50, 'fs-test-50', '/stash', '/stash');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
            VALUES ('fs-test-50', '/stash/torrents/seeding', '2026-02-06', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('torrents/seeding/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123'),
                ('torrents/seeding/Movie.2024/subtitles.srt', 1002, 5000, 1234567890, 'def456');

            -- External hardlink for video.mkv (same inode, outside seeding domain)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('media/exports/Movie.2024.mkv', 1001, 1000000, 1234567890, 'abc123');

            -- Create payload
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 2, 1005000, 'complete');

            -- Create torrent instance
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_abc123', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_abc123")

        # Assert BLOCKED
        assert plan['decision'] == 'BLOCK'
        assert len(plan['reasons']) > 0
        assert 'external' in plan['reasons'][0].lower() or 'outside' in plan['reasons'][0].lower()
        assert plan['payload_hash'] == 'payload_hash_123'

    def test_block_when_payload_root_not_under_mount(self, tmp_path):
        """Test that plan is BLOCKED when payload root cannot be resolved under mount."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        payload_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, mount_point, preferred_mount_point)
            VALUES (50, '/different', '/different');

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('{payload_root}/video.mkv', 1001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_bad_root', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        plan = planner.plan_demotion("torrent_bad_root")

        assert plan['decision'] == 'BLOCK'
        assert "mount" in plan['reasons'][0].lower() or "rescan" in plan['reasons'][0].lower()

    def test_no_block_when_all_hardlinks_internal(self, tmp_path):
        """Test that plan is NOT blocked when all hardlinks are internal."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test data:
        # - Payload on stash with 2 files
        # - All hardlinks are within seeding domain
        payload_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{payload_root}/video.mkv', 1001, 1000000, 1234567890, 'abc123'),
                ('{payload_root}/subtitles.srt', 1002, 5000, 1234567890, 'def456');

            -- Internal hardlink (within seeding domain)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie.2024.Alt/video.mkv', 1001, 1000000, 1234567890, 'abc123');

            -- Create payload
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 2, 1005000, 'complete');

            -- Create torrent instance
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_abc123', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_abc123")

        # Assert NOT BLOCKED (should be MOVE since payload doesn't exist on pool)
        assert plan['decision'] != 'BLOCK'

    def test_external_consumer_bind_mount_alias(self, tmp_path, monkeypatch):
        """Bind-mount alias roots should resolve to canonical paths for external detection."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        payload_root = "/data/media/torrents/seeding/Movie.2024"
        canonical_root = "/stash/media/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
            VALUES (50, 'fs-test-50', '/stash', '/stash');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
            VALUES ('fs-test-50', '/stash/media/torrents/seeding', '2026-02-06', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('media/torrents/seeding/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123', 'active'),
                ('media/movies/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_bind_alias', 1, 50, '/data/media/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        def fake_canonicalize(path):
            p = Path(path)
            if str(p).startswith("/data/media"):
                return Path(str(p).replace("/data/media", "/stash/media", 1))
            return p

        monkeypatch.setattr("rehome.planner.canonicalize_path", fake_canonicalize)

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/data/media/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49
        )

        plan = planner.plan_demotion("torrent_bind_alias")
        assert plan["decision"] == "BLOCK"
        assert any("outside" in r.lower() or "external" in r.lower() for r in plan["reasons"])

    def test_external_consumer_no_false_positive_when_hardlink_under_bind_alias(
        self, tmp_path, monkeypatch
    ):
        """Seeding-domain hardlinks stored under a bind alias must not be classified external.

        The legacy `files` table stores absolute paths. When a scan ran via the
        /data/media bind alias, paths are stored as /data/media/torrents/seeding/...
        While seeding_roots are canonicalized to /stash/media/torrents/seeding/.

        Old code: _normalize_abs_path used path.resolve(), leaving the bind-alias
        path as /data/media/..., which fails relative_to against /stash/media/...
        → every seeding-domain hardlink classified as external → false-positive BLOCK.

        Fix: _normalize_abs_path now uses canonicalize_path so bind-alias paths
        are mapped to /stash/media/... before comparison.
        """
        db_path = tmp_path / "catalog.db"
        conn = sqlite3.connect(db_path)

        # Legacy-style schema: single `files` table with absolute paths.
        conn.executescript("""
            CREATE TABLE files (
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
                status TEXT NOT NULL DEFAULT 'incomplete'
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

            -- Scan root recorded under the canonical path.
            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots VALUES ('fs-50', '/stash/media/torrents/seeding', '2026-01-01', 1);
        """)

        # Both hardlinks are inside the seeding domain, but stored under the
        # bind-alias prefix /data/media (as if scanned via that mount path).
        conn.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
            ("/data/media/torrents/seeding/cross-seed/aither/Movie/video.mkv", 1001, 1000000, 0.0, "abc", "active"),
        )
        conn.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
            ("/data/media/torrents/seeding/myanonamouse/Movie/video.mkv", 1001, 1000000, 0.0, "abc", "active"),
        )
        payload_root = "/data/media/torrents/seeding/cross-seed/aither/Movie"
        conn.execute(
            "INSERT INTO payloads VALUES (1, 'phash-noext', 50, ?, 1, 1000000, 'complete')",
            (payload_root,),
        )
        conn.commit()
        conn.close()

        # canonicalize_path maps /data/media -> /stash/media.
        def fake_canonicalize(path):
            p = Path(path)
            s = str(p)
            if s.startswith("/data/media"):
                return Path(s.replace("/data/media", "/stash/media", 1))
            return p

        monkeypatch.setattr("rehome.planner.canonicalize_path", fake_canonicalize)

        # Seeding roots canonicalized to /stash/media. Hardlinks in the legacy
        # table are stored as /data/media/... — they must be canonicalized before
        # the relative_to check, otherwise every seeding-domain hardlink looks external.
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/media/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
        )

        consumers = planner._detect_external_consumers(
            sqlite3.connect(db_path),
            payload_root,
        )

        assert consumers == [], (
            "All hardlinks are inside the seeding domain; no external consumer "
            "should be detected. A non-empty result means _normalize_abs_path "
            "left the bind-alias /data/media/... path un-canonicalized, causing "
            "a false-positive BLOCK."
        )

    def test_external_consumer_detection_uses_fs_uuid_backed_files_relation(self, tmp_path):
        """Planner should resolve devices.files_table and not require a physical files_<device_id> table."""
        db_path = tmp_path / "catalog.db"
        conn = sqlite3.connect(db_path)

        payload_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            CREATE TABLE devices (
                fs_uuid TEXT PRIMARY KEY,
                device_id INTEGER UNIQUE,
                device_alias TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT,
                files_table TEXT
            );

            CREATE TABLE payloads (
                payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_hash TEXT,
                device_id INTEGER,
                fs_uuid TEXT,
                root_path TEXT NOT NULL,
                file_count INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'incomplete'
            );

            CREATE TABLE files_fs_test_50 (
                path TEXT PRIMARY KEY,
                inode INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha1 TEXT,
                status TEXT DEFAULT 'active'
            );

            INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, files_table)
            VALUES ('fs-test-50', 50, 'stash', '/stash', '/stash', 'files_fs_test_50');

            INSERT INTO files_fs_test_50 (path, inode, size, mtime, sha1, status) VALUES
                ('torrents/seeding/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123', 'active'),
                ('media/exports/Movie.2024.mkv', 1001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_hash, device_id, fs_uuid, root_path, file_count, total_bytes, status)
            VALUES ('payload_hash_123', 50, 'fs-test-50', '{payload_root}', 1, 1000000, 'complete');
        """)
        conn.commit()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        consumers = planner._detect_external_consumers(conn, payload_root)
        conn.close()

        assert len(consumers) == 1
        assert consumers[0].file_path.endswith("video.mkv")
        assert any("media/exports/Movie.2024.mkv" in ext for ext in consumers[0].external_link_paths)

    def test_block_when_library_roots_not_scanned(self, tmp_path):
        """Block demotion when library roots are missing from scan_roots."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        payload_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
            VALUES (50, 'fs-test-50', '/stash', '/stash');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
            VALUES ('fs-test-50', '/stash/torrents/seeding', '2026-02-06', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('{payload_root}/video.mkv', 7001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_library_guard', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=["/data/media/movies"],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        plan = planner.plan_demotion("torrent_library_guard")
        assert plan["decision"] == "BLOCK"
        assert any("scan_roots" in r or "library" in r for r in plan["reasons"])

    def test_library_roots_cover_across_devices(self, tmp_path):
        """Allow demotion when scan_roots cover roots on multiple devices."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        payload_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
            VALUES
                (50, 'fs-stash', '/stash', '/stash'),
                (49, 'fs-pool', '/pool', '/pool');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
            VALUES
                ('fs-stash', '/stash/torrents/seeding', '2026-02-06', 1),
                ('fs-pool', '/pool/data/seeds', '2026-02-06', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('torrents/seeding/Movie.2024/video.mkv', 7001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_123', 50, '{payload_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_library_multi', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding", "/pool/data/seeds"],
            library_roots=["/pool/data/seeds"],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        plan = planner.plan_demotion("torrent_library_multi")
        assert plan["decision"] != "BLOCK"


class TestReusePlan:
    """Test REUSE decision when payload exists on pool."""

    def test_reuse_when_payload_exists_on_pool(self, tmp_path):
        """Test that plan is REUSE when payload already exists on pool."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test data:
        # - Payload on stash
        # - Same payload_hash exists on pool
        stash_root = str((tmp_path / "stash" / "torrents" / "seeding" / "Movie.2024").resolve())
        pool_root = str((tmp_path / "pool" / "torrents" / "content" / "Movie.2024").resolve())
        stash_save = str((tmp_path / "stash" / "torrents" / "seeding").resolve())
        payload_hash = "shared_payload_hash_456"

        Path(stash_root).mkdir(parents=True, exist_ok=True)
        Path(pool_root).mkdir(parents=True, exist_ok=True)

        conn.executescript(f"""
            -- Files on stash (device 50)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{stash_root}/video.mkv', 2001, 1000000, 1234567890, 'abc123'),
                ('{stash_root}/subtitles.srt', 2002, 5000, 1234567890, 'def456');

            -- Files on pool (device 49, same content)
            INSERT INTO files_49 (path, inode, size, mtime, sha1) VALUES
                ('{pool_root}/video.mkv', 3001, 1000000, 1234567890, 'abc123'),
                ('{pool_root}/subtitles.srt', 3002, 5000, 1234567890, 'def456');

            -- Stash payload
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 50, '{stash_root}', 2, 1005000, 'complete');

            -- Pool payload (same hash)
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (2, '{payload_hash}', 49, '{pool_root}', 2, 1005000, 'complete');

            -- Torrent instance pointing to stash payload
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_reuse_123', 1, 50, '{stash_save}', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=[stash_save],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root=str((tmp_path / "pool" / "torrents" / "content").resolve())
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_reuse_123")

        # Assert REUSE
        assert plan['decision'] == 'REUSE'
        assert plan['payload_hash'] == payload_hash
        assert plan['target_path'] == pool_root
        assert plan['source_path'] == stash_root
        assert plan.get('payload_group')

    def test_reuse_with_save_path_alias_and_scan_root_alias(self, tmp_path):
        """Allow REUSE when save_path and scan_roots use alternate mount aliases."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        data_media_root = (tmp_path / "data" / "media").resolve()
        stash_media_root = (tmp_path / "stash" / "media").resolve()
        pool_data_root = (tmp_path / "pool" / "data").resolve()
        stash_root = str((stash_media_root / "torrents" / "seeding" / "Movie.2024").resolve())
        pool_root = str((pool_data_root / "seeds" / "Movie.2024").resolve())
        alias_save = str((data_media_root / "torrents" / "seeding").resolve())
        payload_hash = "shared_alias_payload_hash"

        Path(stash_root).mkdir(parents=True, exist_ok=True)
        Path(pool_root).mkdir(parents=True, exist_ok=True)

        conn.executescript(f"""
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
            VALUES
                (50, 'fs-stash', '{data_media_root}', '{stash_media_root}'),
                (49, 'fs-pool', '{pool_data_root}', '{pool_data_root}');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count)
            VALUES
                ('fs-stash', '{stash_media_root}', '2026-02-18', 1),
                ('fs-pool', '{pool_data_root}', '2026-02-18', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('torrents/seeding/Movie.2024/video.mkv', 8001, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES
                (1, '{payload_hash}', 50, '{stash_root}', 1, 1000000, 'complete'),
                (2, '{payload_hash}', 49, '{pool_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_alias_123', 1, 50, '{alias_save}', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=[str(data_media_root), str(stash_media_root), str(pool_data_root)],
            library_roots=[str(data_media_root), str(stash_media_root)],
            stash_device=50,
            pool_device=49,
            stash_seeding_root=str((stash_media_root / "torrents" / "seeding").resolve()),
            pool_seeding_root=str((pool_data_root / "seeds").resolve()),
            pool_payload_root=str((pool_data_root / "seeds").resolve()),
        )

        plan = planner.plan_demotion("torrent_alias_123")
        assert plan["decision"] == "REUSE"
        assert plan["target_path"] == pool_root


class TestMovePlan:
    """Test MOVE decision when payload doesn't exist on pool."""

    def test_scan_roots_coverage_cached_per_planner(self, tmp_path, monkeypatch):
        """Scan-roots coverage check should run once per planner instance."""
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        stash_root = "/stash/torrents/seeding/Movie.2024"
        payload_hash = "scan_cache_payload_hash"

        conn.executescript(f"""
            INSERT INTO files_50 (path, inode, size, mtime, sha1, status)
            VALUES ('{stash_root}/video.mkv', 7101, 1000000, 1234567890, 'abc123', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 50, '{stash_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_scan_cache', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=["/stash/torrents/seeding"],
            stash_device=50,
            pool_device=49,
            stash_seeding_root="/stash/torrents/seeding",
            pool_seeding_root="/pool/torrents/seeding",
            pool_payload_root="/pool/torrents/content",
        )

        calls = {"count": 0}
        original = planner._scan_roots_cover

        def tracked_scan(conn, roots):
            calls["count"] += 1
            _ = original(conn, roots)
            return True

        monkeypatch.setattr(planner, "_scan_roots_cover", tracked_scan)

        plan1 = planner.plan_demotion("torrent_scan_cache")
        plan2 = planner.plan_demotion("torrent_scan_cache")

        assert plan1["decision"] == "MOVE"
        assert plan2["decision"] == "MOVE"
        assert calls["count"] == 1

    def test_move_when_payload_not_on_pool(self, tmp_path):
        """Test that plan is MOVE when payload doesn't exist on pool."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test data:
        # - Payload on stash
        # - Payload does NOT exist on pool
        stash_root = "/stash/torrents/seeding/Movie.2024"
        payload_hash = "unique_payload_hash_789"

        conn.executescript(f"""
            -- Files on stash (device 50)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{stash_root}/video.mkv', 4001, 1000000, 1234567890, 'abc123'),
                ('{stash_root}/subtitles.srt', 4002, 5000, 1234567890, 'def456');

            -- Stash payload
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 50, '{stash_root}', 2, 1005000, 'complete');

            -- Torrent instance pointing to stash payload
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_move_456', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            pool_payload_root="/pool/torrents/content"
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_move_456")

        # Assert MOVE
        assert plan['decision'] == 'MOVE'
        assert plan['payload_hash'] == payload_hash
        assert plan['source_path'] == stash_root
        assert plan['target_path'] is not None
        assert '/pool/' in plan['target_path']


class TestSiblingTorrents:
    """Test that sibling torrents (same payload) are included in plan."""

    def test_siblings_included_in_plan(self, tmp_path):
        """Test that all sibling torrents are listed in the plan."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test data:
        # - One payload on stash
        # - Three torrents pointing to same payload
        stash_root = "/stash/torrents/seeding/Movie.2024"
        payload_hash = "shared_payload_siblings"

        conn.executescript(f"""
            -- Files on stash (device 50)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{stash_root}/video.mkv', 5001, 1000000, 1234567890, 'abc123'),
                ('{stash_root}/subtitles.srt', 5002, 5000, 1234567890, 'def456');

            -- Stash payload
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 50, '{stash_root}', 2, 1005000, 'complete');

            -- Three torrent instances pointing to same payload
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES
                ('torrent_sibling_1', 1, 50, '/stash/torrents/seeding', 'Movie.2024'),
                ('torrent_sibling_2', 1, 50, '/stash/torrents/seeding', 'Movie.2024'),
                ('torrent_sibling_3', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49
        )

        # Plan demotion for first torrent
        plan = planner.plan_demotion("torrent_sibling_1")

        # Assert all siblings are included
        assert len(plan['affected_torrents']) == 3
        assert 'torrent_sibling_1' in plan['affected_torrents']
        assert 'torrent_sibling_2' in plan['affected_torrents']
        assert 'torrent_sibling_3' in plan['affected_torrents']


class TestDryRun:
    """Test that dry-run produces no side effects."""

    def test_dryrun_no_side_effects(self, tmp_path, capsys):
        """Test that dry-run prints actions but makes no changes."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create simple test payload
        stash_root = "/stash/torrents/seeding/Movie.2024"

        conn.executescript(f"""
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{stash_root}/video.mkv', 6001, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'dryrun_hash', 50, '{stash_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_dryrun', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()

        # Get initial payload count
        initial_count = conn.execute("SELECT COUNT(*) FROM payloads").fetchone()[0]
        conn.close()

        # Create plan
        plan = {
            'version': '1.0',
            'decision': 'MOVE',
            'torrent_hash': 'torrent_dryrun',
            'payload_id': 1,
            'payload_hash': 'dryrun_hash',
            'reasons': ['Test dry run'],
            'affected_torrents': ['torrent_dryrun'],
            'source_path': stash_root,
            'target_path': '/pool/torrents/content/Movie.2024',
            'file_count': 1,
            'total_bytes': 1000000
        }

        # Execute dry-run
        executor = DemotionExecutor(catalog_path=db_path)
        executor.dry_run(plan)

        # Verify output was printed
        captured = capsys.readouterr()
        assert 'decision=MOVE' in captured.out
        assert 'ACTION: MOVE' in captured.out
        assert 'Dry-run complete' in captured.out

        # Verify no database changes
        conn = sqlite3.connect(db_path)
        final_count = conn.execute("SELECT COUNT(*) FROM payloads").fetchone()[0]
        conn.close()

        assert final_count == initial_count


class TestFsUuidIdentity:
    """Tests for fs_uuid-first identity fields in generated plans."""

    def test_demotion_move_plan_includes_fs_uuid_identity(self, tmp_path):
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE devices (
                device_id INTEGER PRIMARY KEY,
                fs_uuid TEXT,
                mount_point TEXT NOT NULL,
                preferred_mount_point TEXT
            );

            INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point) VALUES
                (49, 'fs-test-49', '/pool', '/pool'),
                (50, 'fs-test-50', '/stash', '/stash');

            CREATE TABLE scan_roots (
                fs_uuid TEXT,
                root_path TEXT,
                last_scanned_at TEXT,
                scan_count INTEGER,
                PRIMARY KEY (fs_uuid, root_path)
            );

            INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count) VALUES
                ('fs-test-50', '/stash/torrents/seeding', '2026-03-06', 1);

            INSERT INTO files_50 (path, inode, size, mtime, sha1, status) VALUES
                ('torrents/seeding/Show.S01/ep1.mkv', 101, 1000, 1.0, 'a', 'active');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_show_s01', 50, '/stash/torrents/seeding/Show.S01', 1, 1000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('showhash001', 1, 50, '/stash/torrents/seeding', 'Show.S01');
            """
        )
        conn.commit()
        conn.close()

        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            library_roots=[],
            stash_device=50,
            pool_device=49,
            stash_seeding_root="/stash/torrents/seeding",
            pool_seeding_root="/pool/torrents/seeding",
            pool_payload_root="/pool/torrents/content",
        )

        plan = planner.plan_demotion("showhash001")

        assert plan["decision"] == "MOVE"
        assert plan.get("source_fs_uuid") == "fs-test-50"
        assert plan.get("target_fs_uuid") == "fs-test-49"


def test_executor_resolves_fs_uuid_backed_files_relation(tmp_path):
    """Executor helper should resolve devices.files_table without a physical files_<device_id> table."""
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE devices (
            fs_uuid TEXT PRIMARY KEY,
            device_id INTEGER UNIQUE,
            device_alias TEXT,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT,
            files_table TEXT
        );

        CREATE TABLE files_fs_test_50 (
            path TEXT PRIMARY KEY,
            sha256 TEXT,
            status TEXT
        );

        INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, files_table)
        VALUES ('fs-test-50', 50, 'stash', '/stash', '/stash', 'files_fs_test_50');
        """
    )
    conn.commit()

    executor = DemotionExecutor.__new__(DemotionExecutor)
    assert executor._get_device_table_name(conn, 50) == "files_fs_test_50"

    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
