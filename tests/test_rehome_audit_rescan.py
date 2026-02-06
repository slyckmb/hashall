"""
Tests for rehome audit trail and rescan behavior.
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.executor import DemotionExecutor


class FakeQbitClient:
    def __init__(self, default_path: str):
        self.default_path = default_path
        self.save_paths = {}

    def pause_torrent(self, torrent_hash: str) -> bool:
        self.save_paths.setdefault(torrent_hash, self.default_path)
        return True

    def set_location(self, torrent_hash: str, new_location: str) -> bool:
        self.save_paths[torrent_hash] = new_location
        return True

    def resume_torrent(self, torrent_hash: str) -> bool:
        return True

    def get_torrent_info(self, torrent_hash: str):
        return SimpleNamespace(save_path=self.save_paths.get(torrent_hash, self.default_path))

    def get_torrent_files(self, torrent_hash: str):
        return []


def _setup_db_and_plan(tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)

    target_root = tmp_path / "pool" / "content" / "Movie.2024"
    source_root = tmp_path / "stash" / "content" / "Movie.2024"
    target_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    payload_file = target_root / "video.mkv"
    payload_file.write_bytes(b"data")

    conn.executescript(f"""
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
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)

    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'payload_hash', 50, ?, 1, ?, 'complete')
        """,
        (str(source_root), payload_file.stat().st_size),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (2, 'payload_hash', 49, ?, 1, ?, 'complete')
        """,
        (str(target_root), payload_file.stat().st_size),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('torrent_audit', 1, 50, ?, 'Movie.2024')
        """,
        (str(source_root.parent),),
    )
    conn.commit()
    conn.close()

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "REUSE",
        "torrent_hash": "torrent_audit",
        "payload_id": 1,
        "payload_hash": "payload_hash",
        "reasons": ["payload exists on pool"],
        "affected_torrents": ["torrent_audit"],
        "source_path": str(source_root),
        "target_path": str(target_root),
        "source_device_id": 50,
        "target_device_id": 49,
        "seeding_roots": [],
        "file_count": 1,
        "total_bytes": payload_file.stat().st_size
    }

    return db_path, plan, source_root, target_root


def test_rehome_audit_run_recorded(tmp_path, monkeypatch):
    db_path, plan, source_root, target_root = _setup_db_and_plan(tmp_path)

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(source_root.parent))

    executor.execute(plan)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status FROM rehome_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    assert row[0] == "success"


def test_rehome_rescan_invoked(tmp_path, monkeypatch):
    db_path, plan, source_root, target_root = _setup_db_and_plan(tmp_path)

    calls = []

    def fake_scan_path(*, db_path, root_path, quiet=False, **kwargs):
        calls.append(Path(root_path))

    monkeypatch.setattr("hashall.scan.scan_path", fake_scan_path)

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(source_root.parent))

    executor.execute(plan, rescan=True)

    assert source_root in calls
    assert target_root in calls
