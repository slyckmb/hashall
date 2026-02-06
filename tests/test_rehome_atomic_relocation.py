"""
Tests for atomic relocation rollback behavior.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rehome.executor import DemotionExecutor


class FakeQbitClient:
    def __init__(self, fail_on=None, default_path="/stash/seeding"):
        self.fail_on = set(fail_on or [])
        self.save_paths = {}
        self.default_path = default_path

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

    def get_torrent_files(self, torrent_hash: str):
        return []


def test_atomic_relocation_rolls_back_on_failure(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient(fail_on={"t2"})

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
        {"torrent_hash": "t2", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    with pytest.raises(RuntimeError):
        executor._relocate_torrents_atomic(relocations)

    # t1 should be rolled back to source path
    assert executor.qbit_client.save_paths["t1"] == "/stash/seeding"
