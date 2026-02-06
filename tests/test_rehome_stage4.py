"""
Tests for rehome Stage 4 features (qBittorrent integration + batch demotion).

Covers:
- qBittorrent relocation (pause/set_location/resume)
- Batch demotion by payload hash
- Batch demotion by tag
- Relocation failure handling and rollback
"""

import pytest
import sqlite3
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import List

# Import rehome modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.planner import DemotionPlanner
from rehome.executor import DemotionExecutor
from hashall.qbittorrent import QBittorrentClient, QBitTorrent


class TestDatabase:
    """Helper class to create test database with payload schema."""

    @staticmethod
    def create_test_db(tmp_path: Path) -> Path:
        """Create a test database with payload tables."""
        db_path = tmp_path / "test_catalog.db"
        conn = sqlite3.connect(db_path)

        # Create minimal schema for testing
        conn.executescript("""
            -- Session-based files table (used by current hashall)
            CREATE TABLE files (
                path TEXT PRIMARY KEY,
                inode INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha1 TEXT,
                scan_session_id INTEGER
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


class TestQBittorrentRelocation:
    """Test real qBittorrent relocation logic."""

    def test_pause_resume_relocate_flow(self):
        """Test that qBittorrent client properly pauses, relocates, and resumes."""
        # Create mock session
        mock_session = Mock()

        # Mock successful responses
        mock_pause_response = Mock()
        mock_pause_response.text = "Ok."
        mock_pause_response.raise_for_status = Mock()

        mock_set_location_response = Mock()
        mock_set_location_response.text = "Ok."
        mock_set_location_response.raise_for_status = Mock()

        mock_resume_response = Mock()
        mock_resume_response.text = "Ok."
        mock_resume_response.raise_for_status = Mock()

        mock_session.post.side_effect = [
            Mock(text="Ok."),  # login
            mock_pause_response,
            mock_set_location_response,
            mock_resume_response
        ]

        # Create client
        client = QBittorrentClient()
        client.session = mock_session
        client._authenticated = True

        # Test pause
        mock_session.post.reset_mock()
        mock_session.post.return_value = mock_pause_response
        assert client.pause_torrent("abc123") is True
        assert mock_session.post.call_count == 1  # pause only (already authenticated)

        # Test set_location
        mock_session.post.reset_mock()
        mock_session.post.return_value = mock_set_location_response
        assert client.set_location("abc123", "/new/path") is True
        assert mock_session.post.call_count == 1

        # Test resume
        mock_session.post.reset_mock()
        mock_session.post.return_value = mock_resume_response
        assert client.resume_torrent("abc123") is True
        assert mock_session.post.call_count == 1

    def test_relocation_failure_handling(self, tmp_path):
        """Test that executor handles relocation failures gracefully."""
        # Create test database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create test payload
        conn.executescript(f"""
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie.2024/video.mkv', 1001, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_fail', 50, '/stash/torrents/seeding/Movie.2024', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_fail_test', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        # Create executor with mocked qBit client
        executor = DemotionExecutor(catalog_path=db_path)

        # Mock qBit client to fail on set_location
        mock_client = Mock()
        mock_client.pause_torrent.return_value = True
        mock_client.set_location.return_value = False  # Fail here
        mock_client.resume_torrent.return_value = True

        executor.qbit_client = mock_client

        # Create plan
        plan = {
            'version': '1.0',
            'decision': 'MOVE',
            'torrent_hash': 'torrent_fail_test',
            'payload_id': 1,
            'payload_hash': 'payload_hash_fail',
            'reasons': ['Test failure'],
            'affected_torrents': ['torrent_fail_test'],
            'source_path': '/stash/torrents/seeding/Movie.2024',
            'target_path': '/pool/torrents/content/Movie.2024',
            'file_count': 1,
            'total_bytes': 1000000
        }

        # Execution should raise error
        with pytest.raises(RuntimeError, match="Failed to set location"):
            executor._relocate_torrent('torrent_fail_test', '/pool/torrents/content')


class TestBatchDemotionByPayloadHash:
    """Test batch demotion by payload hash."""

    def test_batch_by_payload_hash(self, tmp_path):
        """Test planning batch demotion for all torrents with same payload hash."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create payload with multiple torrents (siblings)
        payload_hash = "shared_payload_batch_test"
        conn.executescript(f"""
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie.2024/video.mkv', 2001, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 50, '/stash/torrents/seeding/Movie.2024', 1, 1000000, 'complete');

            -- Three torrents pointing to same payload
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES
                ('torrent_batch_1', 1, 50, '/stash/torrents/seeding', 'Movie.2024'),
                ('torrent_batch_2', 1, 50, '/stash/torrents/seeding', 'Movie.2024'),
                ('torrent_batch_3', 1, 50, '/stash/torrents/seeding', 'Movie.2024');
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

        # Plan batch demotion by payload hash
        plan = planner.plan_batch_demotion_by_payload_hash(payload_hash)

        # Verify plan
        assert plan['batch_mode'] == 'payload_hash'
        assert plan['batch_filter'] == payload_hash
        assert plan['payload_hash'] == payload_hash
        assert len(plan['affected_torrents']) == 3
        assert 'torrent_batch_1' in plan['affected_torrents']
        assert 'torrent_batch_2' in plan['affected_torrents']
        assert 'torrent_batch_3' in plan['affected_torrents']


class TestBatchDemotionByTag:
    """Test batch demotion by qBittorrent tag."""

    def test_batch_by_tag_multiple_payloads(self, tmp_path):
        """Test planning batch demotion for all torrents with a specific tag."""
        # Setup database
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        # Create multiple payloads with tagged torrents
        conn.executescript(f"""
            -- Payload 1
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie1/video.mkv', 3001, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, 'payload_hash_1', 50, '/stash/torrents/seeding/Movie1', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, tags)
            VALUES ('torrent_tag_1', 1, 50, '/stash/torrents/seeding', 'Movie1', '~noHL,seed');

            -- Payload 2
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie2/video.mkv', 3002, 2000000, 1234567890, 'def456');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (2, 'payload_hash_2', 50, '/stash/torrents/seeding/Movie2', 1, 2000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, tags)
            VALUES ('torrent_tag_2', 2, 50, '/stash/torrents/seeding', 'Movie2', '~noHL');

            -- Payload 3 (no tag)
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('/stash/torrents/seeding/Movie3/video.mkv', 3003, 3000000, 1234567890, 'ghi789');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (3, 'payload_hash_3', 50, '/stash/torrents/seeding/Movie3', 1, 3000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, tags)
            VALUES ('torrent_no_tag', 3, 50, '/stash/torrents/seeding', 'Movie3', 'other');
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

        # Plan batch demotion by tag
        plans = planner.plan_batch_demotion_by_tag('~noHL')

        # Verify plans
        assert len(plans) == 2  # Two payloads have ~noHL tag

        # Check that each plan is for a different payload
        payload_hashes = [p['payload_hash'] for p in plans]
        assert 'payload_hash_1' in payload_hashes
        assert 'payload_hash_2' in payload_hashes
        assert 'payload_hash_3' not in payload_hashes

        # Check batch metadata
        for plan in plans:
            assert plan['batch_mode'] == 'tag'
            assert plan['batch_filter'] == '~noHL'


class TestRelocationVerification:
    """Test that relocation is verified after execution."""

    def test_verification_catches_failed_relocation(self, tmp_path):
        """Test that executor verifies torrent location after relocation."""
        db_path = TestDatabase.create_test_db(tmp_path)

        # Create executor with mocked qBit client
        executor = DemotionExecutor(catalog_path=db_path)

        # Mock qBit client
        mock_client = Mock()
        mock_client.pause_torrent.return_value = True
        mock_client.set_location.return_value = True
        mock_client.resume_torrent.return_value = True

        # Mock get_torrent_info to return WRONG location
        wrong_location_torrent = QBitTorrent(
            hash="verify_test",
            name="Test",
            save_path="/wrong/path",  # Wrong location!
            content_path="/wrong/path/Test",
            category="",
            tags="",
            state="uploading",
            size=1000000,
            progress=1.0
        )
        mock_client.get_torrent_info.return_value = wrong_location_torrent

        executor.qbit_client = mock_client

        # Try to relocate - should fail verification
        with pytest.raises(RuntimeError, match="location verification failed"):
            executor._relocate_torrent('verify_test', '/pool/torrents/content')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
