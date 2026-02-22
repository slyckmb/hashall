"""Tests for rehome follow-up verification and cleanup."""

from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.followup import run_followup


class FakeQbitClient:
    def __init__(self):
        self.torrents_by_tag = {}
        self.all_torrents = []
        self.torrent_info = {}
        self.info_calls = 0
        self.add_calls = []
        self.remove_calls = []

    def test_connection(self):
        return True

    def login(self):
        return True

    def get_torrents(self, category=None, tag=None):
        if tag is None:
            if self.all_torrents:
                return list(self.all_torrents)
            if self.torrent_info:
                return list(self.torrent_info.values())
            seen = {}
            for values in self.torrents_by_tag.values():
                for item in values:
                    key = getattr(item, "hash", "")
                    if key and key not in seen:
                        seen[key] = item
            return list(seen.values())
        return list(self.torrents_by_tag.get(tag or "", []))

    def get_torrent_info(self, torrent_hash: str):
        self.info_calls += 1
        return self.torrent_info.get(torrent_hash)

    def add_tags(self, torrent_hash: str, tags):
        self.add_calls.append((torrent_hash, tuple(tags)))
        return True

    def remove_tags(self, torrent_hash: str, tags):
        self.remove_calls.append((torrent_hash, tuple(tags)))
        return True


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT,
            file_count INTEGER,
            total_bytes INTEGER,
            status TEXT
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
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_followup_marks_pending_group_verify_ok(monkeypatch, tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash-ok', 44, '/pool/data/seeds/Show', 1, 123, 'complete');
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
        VALUES ('torrent-ok', 1, 44, '/pool/data/seeds/cross-seed/FearNoPeer',
                'rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending');
        """
    )
    conn.commit()
    conn.close()

    fake = FakeQbitClient()
    fake.torrents_by_tag["rehome_verify_pending"] = [
        SimpleNamespace(
            hash="torrent-ok",
            tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending",
        )
    ]
    fake.torrents_by_tag["rehome_cleanup_source_required"] = []
    fake.torrent_info["torrent-ok"] = SimpleNamespace(
        hash="torrent-ok",
        tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending",
        progress=1.0,
        state="uploading",
        auto_tmm=False,
        save_path="/pool/data/seeds/cross-seed/FearNoPeer",
    )

    monkeypatch.setattr("rehome.followup.get_qbittorrent_client", lambda: fake)

    report = run_followup(catalog_path=db_path)

    assert report["summary"]["groups_ok"] == 1
    assert report["summary"]["groups_pending"] == 0
    assert report["summary"]["groups_failed"] == 0
    assert report["entries"][0]["outcome"] == "ok"
    assert ("torrent-ok", ("rehome_verify_ok",)) in fake.add_calls


def test_followup_cleanup_retries_and_clears_cleanup_required(monkeypatch, tmp_path: Path):
    db_path = _make_db(tmp_path)
    source_dir = tmp_path / "stash-source"
    source_dir.mkdir()
    (source_dir / "file.mkv").write_bytes(b"abc")

    conn = sqlite3.connect(db_path)
    conn.executescript(
        f"""
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES
          (1, 'hash-clean', 44, '/pool/data/seeds/Movie', 1, 3, 'complete'),
          (2, 'hash-clean', 49, '{source_dir}', 1, 3, 'complete');
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
        VALUES ('torrent-clean', 1, 44, '/pool/data/seeds/cross-seed/seedpool (API)',
                'rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending,rehome_cleanup_source_required');
        """
    )
    conn.commit()
    conn.close()

    fake = FakeQbitClient()
    fake.torrents_by_tag["rehome_verify_pending"] = [
        SimpleNamespace(
            hash="torrent-clean",
            tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending,rehome_cleanup_source_required",
        )
    ]
    fake.torrents_by_tag["rehome_cleanup_source_required"] = [
        SimpleNamespace(
            hash="torrent-clean",
            tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending,rehome_cleanup_source_required",
        )
    ]
    fake.torrent_info["torrent-clean"] = SimpleNamespace(
        hash="torrent-clean",
        tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending,rehome_cleanup_source_required",
        progress=1.0,
        state="uploading",
        auto_tmm=False,
        save_path="/pool/data/seeds/cross-seed/seedpool (API)",
    )

    monkeypatch.setattr("rehome.followup.get_qbittorrent_client", lambda: fake)

    report = run_followup(catalog_path=db_path, cleanup=True)

    assert report["summary"]["cleanup_attempted"] == 1
    assert report["summary"]["cleanup_done"] == 1
    assert source_dir.exists() is False
    removed_tags = [call for call in fake.remove_calls if call[0] == "torrent-clean"]
    assert removed_tags
    assert any("rehome_cleanup_source_required" in call[1] for call in removed_tags)


def test_followup_marks_hard_failures_verify_failed(monkeypatch, tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash-fail', 44, '/pool/data/seeds/Fail', 1, 100, 'complete');
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
        VALUES ('torrent-fail', 1, 44, '/pool/data/seeds/cross-seed/Aither (API)',
                'rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending');
        """
    )
    conn.commit()
    conn.close()

    fake = FakeQbitClient()
    fake.torrents_by_tag["rehome_verify_pending"] = [
        SimpleNamespace(
            hash="torrent-fail",
            tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending",
        )
    ]
    fake.torrents_by_tag["rehome_cleanup_source_required"] = []
    fake.torrent_info["torrent-fail"] = SimpleNamespace(
        hash="torrent-fail",
        tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending",
        progress=1.0,
        state="uploading",
        auto_tmm=False,
        save_path="/data/media/torrents/seeding/cross-seed/Aither (API)",
    )

    monkeypatch.setattr("rehome.followup.get_qbittorrent_client", lambda: fake)

    report = run_followup(catalog_path=db_path)

    assert report["summary"]["groups_failed"] == 1
    assert report["entries"][0]["outcome"] == "failed"
    assert ("torrent-fail", ("rehome_verify_failed",)) in fake.add_calls


def test_followup_uses_snapshot_before_per_hash_lookup(monkeypatch, tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash-snapshot', 44, '/pool/data/seeds/Snapshot', 1, 99, 'complete');
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
        VALUES ('torrent-snapshot', 1, 44, '/pool/data/seeds/cross-seed/FNP',
                'rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending');
        """
    )
    conn.commit()
    conn.close()

    snapshot_item = SimpleNamespace(
        hash="torrent-snapshot",
        tags="rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260219,rehome_verify_pending",
        progress=1.0,
        state="uploading",
        auto_tmm=False,
        save_path="/pool/data/seeds/cross-seed/FNP",
    )

    fake = FakeQbitClient()
    fake.torrents_by_tag["rehome_verify_pending"] = [snapshot_item]
    fake.torrents_by_tag["rehome_cleanup_source_required"] = []
    fake.all_torrents = [snapshot_item]
    fake.torrent_info["torrent-snapshot"] = snapshot_item

    monkeypatch.setattr("rehome.followup.get_qbittorrent_client", lambda: fake)

    report = run_followup(catalog_path=db_path)

    assert report["summary"]["groups_ok"] == 1
    assert fake.info_calls == 0
