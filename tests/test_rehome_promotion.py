"""
Tests for rehome promotion functionality and guarded cleanup.
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.planner import PromotionPlanner
from rehome.executor import DemotionExecutor


class TestDatabase:
    """Helper class to create test database with payload schema."""

    @staticmethod
    def create_test_db(tmp_path: Path) -> Path:
        db_path = tmp_path / "test_catalog.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE files (
                path TEXT PRIMARY KEY,
                inode INTEGER NOT NULL,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha1 TEXT,
                scan_session_id INTEGER
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
        """)
        conn.commit()
        conn.close()
        return db_path


class FakeQbitClient:
    def __init__(self, default_path: str, fail_on=None):
        self.default_path = default_path
        self.fail_on = set(fail_on or [])
        self.save_paths = {}

    def pause_torrent(self, torrent_hash: str) -> bool:
        self.save_paths.setdefault(torrent_hash, self.default_path)
        return True

    def set_location(self, torrent_hash: str, new_location: str) -> bool:
        if torrent_hash in self.fail_on:
            return False
        self.save_paths[torrent_hash] = new_location
        return True

    def resume_torrent(self, torrent_hash: str) -> bool:
        return True

    def get_torrent_info(self, torrent_hash: str):
        return SimpleNamespace(save_path=self.save_paths.get(torrent_hash, self.default_path))


class TestPromotionPlanner:
    def test_promotion_block_when_stash_missing(self, tmp_path):
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        pool_root = "/pool/torrents/content/Movie.2024"
        payload_hash = "payload_hash_pool_only"

        conn.executescript(f"""
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('{pool_root}/video.mkv', 7001, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (1, '{payload_hash}', 49, '{pool_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_promote_block', 1, 49, '/pool/torrents/content', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = PromotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/pool/torrents"],
            library_roots=[],
            stash_device=50,
            pool_device=49
        )

        plan = planner.plan_promotion("torrent_promote_block")

        assert plan["direction"] == "promote"
        assert plan["decision"] == "BLOCK"
        assert plan["no_blind_copy"] is True
        assert plan["target_path"] is None
        assert "stash" in plan["reasons"][0].lower()

    def test_promotion_reuse_when_stash_exists(self, tmp_path):
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        pool_root = "/pool/torrents/content/Movie.2024"
        stash_root = "/stash/torrents/seeding/Movie.2024"
        payload_hash = "payload_hash_shared"

        conn.executescript(f"""
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('{pool_root}/video.mkv', 8001, 1000000, 1234567890, 'abc123'),
                ('{stash_root}/video.mkv', 8002, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES
                (1, '{payload_hash}', 49, '{pool_root}', 1, 1000000, 'complete'),
                (2, '{payload_hash}', 50, '{stash_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_promote_reuse', 1, 49, '/pool/torrents/content', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = PromotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/pool/torrents", "/stash/torrents"],
            library_roots=[],
            stash_device=50,
            pool_device=49
        )

        plan = planner.plan_promotion("torrent_promote_reuse")

        assert plan["direction"] == "promote"
        assert plan["decision"] == "REUSE"
        assert plan["target_path"] == stash_root
        assert plan["no_blind_copy"] is True
        assert plan.get("payload_group")

    def test_batch_promotion_includes_siblings(self, tmp_path):
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        pool_root = "/pool/torrents/content/Movie.2024"
        stash_root = "/stash/torrents/seeding/Movie.2024"
        payload_hash = "payload_hash_siblings"

        conn.executescript(f"""
            INSERT INTO files (path, inode, size, mtime, sha1) VALUES
                ('{pool_root}/video.mkv', 9001, 1000000, 1234567890, 'abc123'),
                ('{stash_root}/video.mkv', 9002, 1000000, 1234567890, 'abc123');

            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES
                (1, '{payload_hash}', 49, '{pool_root}', 1, 1000000, 'complete'),
                (2, '{payload_hash}', 50, '{stash_root}', 1, 1000000, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES
                ('torrent_promote_sib1', 1, 49, '/pool/torrents/content', 'Movie.2024'),
                ('torrent_promote_sib2', 1, 49, '/pool/torrents/content', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        planner = PromotionPlanner(
            catalog_path=db_path,
            seeding_roots=["/pool/torrents", "/stash/torrents"],
            library_roots=[],
            stash_device=50,
            pool_device=49
        )

        plan = planner.plan_batch_promotion_by_payload_hash(payload_hash)

        assert plan["decision"] == "REUSE"
        assert len(plan["affected_torrents"]) == 2
        assert "torrent_promote_sib1" in plan["affected_torrents"]
        assert "torrent_promote_sib2" in plan["affected_torrents"]


class TestCleanupFlags:
    def _setup_plan_and_db(self, tmp_path: Path):
        db_path = TestDatabase.create_test_db(tmp_path)
        conn = sqlite3.connect(db_path)

        pool_content = tmp_path / "pool" / "content" / "Movie.2024"
        pool_view_root = tmp_path / "pool" / "seeding"
        pool_view = pool_view_root / "Movie.2024"
        stash_content = tmp_path / "stash" / "content" / "Movie.2024"
        stash_view_root = tmp_path / "stash" / "seeding"

        pool_content.mkdir(parents=True, exist_ok=True)
        pool_view.mkdir(parents=True, exist_ok=True)
        stash_content.mkdir(parents=True, exist_ok=True)
        stash_view_root.mkdir(parents=True, exist_ok=True)

        payload_file = stash_content / "video.mkv"
        payload_file.write_bytes(b"data")

        # Empty directories for cleanup
        empty_pool = pool_view_root / "emptydir"
        empty_stash = stash_view_root / "emptydir"
        empty_pool.mkdir(parents=True, exist_ok=True)
        empty_stash.mkdir(parents=True, exist_ok=True)

        conn.executescript(f"""
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES
                (1, 'cleanup_hash', 49, '{pool_content}', 1, {payload_file.stat().st_size}, 'complete'),
                (2, 'cleanup_hash', 50, '{stash_content}', 1, {payload_file.stat().st_size}, 'complete');

            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
            VALUES ('torrent_cleanup', 1, 49, '{pool_view_root}', 'Movie.2024');
        """)
        conn.commit()
        conn.close()

        plan = {
            "version": "1.0",
            "direction": "promote",
            "decision": "REUSE",
            "torrent_hash": "torrent_cleanup",
            "payload_id": 1,
            "payload_hash": "cleanup_hash",
            "reasons": ["Payload already exists on stash"],
            "affected_torrents": ["torrent_cleanup"],
            "source_path": str(pool_content),
            "target_path": str(stash_content),
            "source_device_id": 49,
            "target_device_id": 50,
            "seeding_roots": [str(pool_view_root), str(stash_view_root)],
            "no_blind_copy": True,
            "file_count": 1,
            "total_bytes": payload_file.stat().st_size
        }

        return db_path, plan, pool_view, empty_pool, empty_stash

    def test_cleanup_not_run_by_default(self, tmp_path, monkeypatch):
        db_path, plan, pool_view, empty_pool, empty_stash = self._setup_plan_and_db(tmp_path)

        fake_client = FakeQbitClient(default_path=str(Path(plan["source_path"]).parent))
        monkeypatch.setattr("rehome.executor.get_qbittorrent_client", lambda *args, **kwargs: fake_client)

        executor = DemotionExecutor(catalog_path=db_path)
        executor.execute(plan)

        assert pool_view.exists()
        assert empty_pool.exists()
        assert empty_stash.exists()

    def test_cleanup_runs_after_success(self, tmp_path, monkeypatch):
        db_path, plan, pool_view, empty_pool, empty_stash = self._setup_plan_and_db(tmp_path)

        fake_client = FakeQbitClient(default_path=str(Path(plan["source_path"]).parent))
        monkeypatch.setattr("rehome.executor.get_qbittorrent_client", lambda *args, **kwargs: fake_client)

        executor = DemotionExecutor(catalog_path=db_path)
        executor.execute(plan, cleanup_source_views=True, cleanup_empty_dirs=True)

        assert not pool_view.exists()
        assert not empty_pool.exists()
        assert not empty_stash.exists()

    def test_cleanup_skipped_on_failure(self, tmp_path, monkeypatch):
        db_path, plan, pool_view, empty_pool, empty_stash = self._setup_plan_and_db(tmp_path)

        fake_client = FakeQbitClient(
            default_path=str(Path(plan["source_path"]).parent),
            fail_on={"torrent_cleanup"}
        )
        monkeypatch.setattr("rehome.executor.get_qbittorrent_client", lambda *args, **kwargs: fake_client)

        executor = DemotionExecutor(catalog_path=db_path)
        with pytest.raises(RuntimeError):
            executor.execute(plan, cleanup_source_views=True, cleanup_empty_dirs=True)

        assert pool_view.exists()
        assert empty_pool.exists()
        assert empty_stash.exists()
