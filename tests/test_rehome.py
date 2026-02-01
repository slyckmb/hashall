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
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('{payload_root}/video.mkv', 1001, 1000000, 1234567890, 'abc123'),
                ('{payload_root}/subtitles.srt', 1002, 5000, 1234567890, 'def456');

            -- External hardlink for video.mkv (same inode, outside seeding domain)
            INSERT INTO files_50 (path, inode, size, mtime, sha1) VALUES
                ('/media/exports/Movie.2024.mkv', 1001, 1000000, 1234567890, 'abc123');

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
            stash_device=50,
            pool_device=49
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_abc123")

        # Assert BLOCKED
        assert plan['decision'] == 'BLOCK'
        assert len(plan['reasons']) > 0
        assert 'external' in plan['reasons'][0].lower() or 'outside' in plan['reasons'][0].lower()
        assert plan['payload_hash'] == 'payload_hash_123'

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
            stash_device=50,
            pool_device=49
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_abc123")

        # Assert NOT BLOCKED (should be MOVE since payload doesn't exist on pool)
        assert plan['decision'] != 'BLOCK'


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
        stash_root = "/stash/torrents/seeding/Movie.2024"
        pool_root = "/pool/torrents/content/Movie.2024"
        payload_hash = "shared_payload_hash_456"

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
            VALUES ('torrent_reuse_123', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create planner
        planner = DemotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/stash/torrents/seeding"],
            stash_device=50,
            pool_device=49
        )

        # Plan demotion
        plan = planner.plan_demotion("torrent_reuse_123")

        # Assert REUSE
        assert plan['decision'] == 'REUSE'
        assert plan['payload_hash'] == payload_hash
        assert plan['target_path'] == pool_root
        assert plan['source_path'] == stash_root


class TestMovePlan:
    """Test MOVE decision when payload doesn't exist on pool."""

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
            stash_device=50,
            pool_device=49
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
