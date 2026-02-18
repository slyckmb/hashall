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


def test_execute_move_cross_filesystem_uses_rsync_and_removes_source(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    rsync_calls = {}

    def fake_run(cmd, check):
        rsync_calls["cmd"] = cmd
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("rehome.executor.subprocess.run", fake_run)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])
    monkeypatch.setattr(executor, "_build_views", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_relocate_torrents_atomic", lambda *args, **kwargs: None)

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)

    assert "rsync" in rsync_calls["cmd"]
    assert target_path.exists()
    assert not source_path.exists()


def test_execute_move_cross_filesystem_relocation_failure_keeps_source(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_fail"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_fail"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    def fake_run(cmd, check):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("rehome.executor.subprocess.run", fake_run)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])
    monkeypatch.setattr(executor, "_build_views", lambda *args, **kwargs: None)

    def fail_relocation(*_args, **_kwargs):
        raise RuntimeError("relocation failed")

    monkeypatch.setattr(executor, "_relocate_torrents_atomic", fail_relocation)

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    with pytest.raises(RuntimeError, match="relocation failed"):
        executor._execute_move(plan, spot_check=0)

    assert source_path.exists()
    assert not target_path.exists()
