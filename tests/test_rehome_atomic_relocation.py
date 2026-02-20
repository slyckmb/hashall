"""
Tests for atomic relocation rollback behavior.
"""

from pathlib import Path
from types import SimpleNamespace
import shutil
import sqlite3
import os

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
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
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


def test_atomic_relocation_rollback_uses_qb_runtime_source_path(tmp_path, monkeypatch):
    class AliasQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__(default_path="/data/media/torrents/seeding")

        def set_location(self, torrent_hash: str, new_location: str) -> bool:
            if torrent_hash == "t2":
                return False
            self.save_paths[torrent_hash] = new_location
            return True

        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="pausedUP",
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = AliasQbitClient()

    relocations = [
        {
            "torrent_hash": "t1",
            "source_save_path": "/stash/media/torrents/seeding",
            "target_save_path": "/pool/data/seeds",
        },
        {
            "torrent_hash": "t2",
            "source_save_path": "/stash/media/torrents/seeding",
            "target_save_path": "/pool/data/seeds",
        },
    ]

    with pytest.raises(RuntimeError):
        executor._relocate_torrents_atomic(relocations)

    # Rollback should use qB's runtime path authority (/data/media...), not canonical stash alias.
    assert executor.qbit_client.save_paths["t1"] == "/data/media/torrents/seeding"


def test_atomic_relocation_retries_and_waits_for_qb_save_path(tmp_path, monkeypatch):
    class FlakyQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.set_calls = {}
            self.pending_paths = {}
            self.visible_after = {}

        def set_location(self, torrent_hash: str, new_location: str) -> bool:
            call_count = self.set_calls.get(torrent_hash, 0) + 1
            self.set_calls[torrent_hash] = call_count
            if call_count == 1:
                return False
            self.pending_paths[torrent_hash] = new_location
            self.visible_after[torrent_hash] = 2
            return True

        def get_torrent_info(self, torrent_hash: str):
            remaining = self.visible_after.get(torrent_hash, 0)
            if remaining > 0:
                self.visible_after[torrent_hash] = remaining - 1
            else:
                pending = self.pending_paths.get(torrent_hash)
                if pending:
                    self.save_paths[torrent_hash] = pending
            return SimpleNamespace(save_path=self.save_paths.get(torrent_hash, self.default_path), auto_tmm=False)

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FlakyQbitClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    executor._relocate_torrents_atomic(relocations)
    assert executor.qbit_client.set_calls["t1"] >= 2
    assert executor.qbit_client.save_paths["t1"] == "/pool/seeding"


def test_atomic_relocation_retries_torrent_info_before_failing(tmp_path, monkeypatch):
    class FlakyInfoQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.info_calls = 0
            self.last_error = None

        def get_torrent_info(self, torrent_hash: str):
            self.info_calls += 1
            if self.info_calls == 1:
                self.last_error = "Read timed out"
                return None
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="pausedUP",
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FlakyInfoQbitClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    executor._relocate_torrents_atomic(relocations)
    assert executor.qbit_client.info_calls >= 2


def test_atomic_relocation_verifies_before_resume(tmp_path, monkeypatch):
    class OrderedQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.resume_calls = 0

        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="pausedUP",
            )

        def resume_torrent(self, torrent_hash: str) -> bool:
            self.resume_calls += 1
            return True

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = OrderedQbitClient()

    def fake_wait(_hash, expected, **_kwargs):
        # Verify-time polling should happen before any resume call.
        assert executor.qbit_client.resume_calls == 0
        return SimpleNamespace(save_path=str(expected), auto_tmm=False), expected

    monkeypatch.setattr(executor, "_wait_for_save_path", fake_wait)

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]
    executor._relocate_torrents_atomic(relocations)
    assert executor.qbit_client.resume_calls == 1


def test_set_location_retry_succeeds_when_qb_reports_conflict_but_path_is_set(tmp_path, monkeypatch):
    class ConflictButMoved(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def set_location(self, torrent_hash: str, new_location: str) -> bool:
            self.calls += 1
            self.save_paths[torrent_hash] = new_location
            return False

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = ConflictButMoved()

    assert executor._set_location_with_retry("t1", "/pool/seeding", attempts=2, delay_seconds=0.01) is True
    assert executor.qbit_client.calls >= 1


def test_atomic_relocation_reverify_path_after_mismatch(tmp_path, monkeypatch):
    class NeedsReapply(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.set_calls = 0

        def set_location(self, torrent_hash: str, new_location: str) -> bool:
            self.set_calls += 1
            self.save_paths[torrent_hash] = new_location
            return True

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = NeedsReapply()

    expected = Path("/pool/seeding")
    old = Path("/stash/seeding")
    calls = {"count": 0}

    def fake_wait(_hash, _expected, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(save_path=str(old), auto_tmm=False), old
        return SimpleNamespace(save_path=str(expected), auto_tmm=False), expected

    monkeypatch.setattr(executor, "_wait_for_save_path", fake_wait)
    reapply = {"count": 0}

    def fake_retry(torrent_hash, target_save_path, **_kwargs):
        if Path(target_save_path) == expected:
            reapply["count"] += 1
        executor.qbit_client.save_paths[torrent_hash] = target_save_path
        return True

    monkeypatch.setattr(executor, "_set_location_with_retry", fake_retry)

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]
    executor._relocate_torrents_atomic(relocations)
    assert reapply["count"] >= 1


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


def test_execute_move_relocation_failure_cleans_partial_views(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "stash" / "payload.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"x")
    target_path = tmp_path / "pool" / "torrentleech" / "payload.mkv"
    side_view_parent = tmp_path / "pool" / "cross-seed" / "siteA"
    side_view_path = side_view_parent / "payload.mkv"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: False)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])

    def fake_build_views(payload_root, view_targets, plan, **_kwargs):
        for target in view_targets:
            dst = Path(target["target_save_path"]) / target["root_name"]
            if dst == payload_root:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(payload_root, dst)

    monkeypatch.setattr(executor, "_build_views", fake_build_views)
    monkeypatch.setattr(
        executor,
        "_relocate_torrents_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("relocation failed")),
    )

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
        "seeding_roots": [str(tmp_path / "pool"), str(tmp_path / "stash")],
        "view_targets": [
            {
                "torrent_hash": "t-main",
                "source_save_path": str(tmp_path / "stash" / "torrentleech"),
                "target_save_path": str(target_path.parent),
                "root_name": target_path.name,
            },
            {
                "torrent_hash": "t-side",
                "source_save_path": str(tmp_path / "stash" / "cross-seed" / "siteA"),
                "target_save_path": str(side_view_parent),
                "root_name": target_path.name,
            },
        ],
    }

    with pytest.raises(RuntimeError, match="relocation failed"):
        executor._execute_move(plan, spot_check=0)

    assert source_path.exists()
    assert not target_path.exists()
    assert not side_view_path.exists()


def test_execute_move_spot_check_no_sha256_does_not_fail(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_nosha"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_nosha"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    def fake_run(cmd, check):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("rehome.executor.subprocess.run", fake_run)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])
    monkeypatch.setattr(executor, "_build_views", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_relocate_torrents_atomic", lambda *args, **kwargs: None)
    monkeypatch.setattr("rehome.executor.get_payload_file_rows", lambda *_args, **_kwargs: [])

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=1)
    assert target_path.exists()
    assert not source_path.exists()


def test_is_cross_filesystem_checks_existing_ancestor_when_target_missing(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    source_path = tmp_path / "stash" / "payload.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"x")
    target_parent = tmp_path / "pool" / "missing" / "branch"

    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self == source_path:
            return SimpleNamespace(st_dev=49)
        if self == tmp_path:
            return SimpleNamespace(st_dev=44)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat, raising=False)
    assert executor._is_cross_filesystem(source_path, target_parent) is True


def test_spot_check_persists_sha256_and_inode_peers(tmp_path, monkeypatch):
    db_path = tmp_path / "spotcheck.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE files_44 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            sha256 TEXT,
            hash_source TEXT,
            inode INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            last_modified_at TEXT
        );
        """
    )
    payload_root = tmp_path / "payload_root"
    payload_root.mkdir(parents=True, exist_ok=True)
    payload_file = payload_root / "video.mkv"
    payload_file.write_bytes(b"demo-bytes")
    peer_path = tmp_path / "outside-peer.mkv"
    peer_path.write_bytes(b"demo-bytes")

    size = payload_file.stat().st_size
    conn.execute(
        "INSERT INTO files_44(path,size,sha256,hash_source,inode,status) VALUES (?,?,?,?,?,?)",
        (str(payload_file), size, None, None, 777, "active"),
    )
    conn.execute(
        "INSERT INTO files_44(path,size,sha256,hash_source,inode,status) VALUES (?,?,?,?,?,?)",
        (str(peer_path), size, None, None, 777, "active"),
    )
    conn.commit()
    conn.close()

    executor = DemotionExecutor(catalog_path=db_path)
    monkeypatch.setattr("rehome.executor.compute_sha256", lambda _p: "abc123hash")

    executor._spot_check_payload(payload_root, device_id=44, sample=1)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT path, sha256, hash_source FROM files_44 WHERE inode=777 ORDER BY path"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert all(r[1] == "abc123hash" for r in rows)
    as_map = {row[0]: row[2] for row in rows}
    assert as_map[str(payload_file)] == "calculated"
    assert as_map[str(peer_path)] == "inode:777"


def test_execute_move_cross_filesystem_cleanup_permission_repair_then_success(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_perm_fix"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_perm_fix"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    def fake_copy(_src, _dst):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")

    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])
    monkeypatch.setattr(executor, "_build_views", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_relocate_torrents_atomic", lambda *args, **kwargs: None)

    calls = {"delete": 0, "repair": 0}

    def fake_delete(path):
        calls["delete"] += 1
        if calls["delete"] == 1:
            raise PermissionError(13, "Permission denied", str(path))
        shutil.rmtree(path)

    def fake_repair(_path):
        calls["repair"] += 1
        return True

    monkeypatch.setattr(executor, "_delete_path", fake_delete)
    monkeypatch.setattr(executor, "_repair_permissions_for_cleanup", fake_repair)

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)
    assert calls["repair"] == 1
    assert target_path.exists()
    assert not source_path.exists()


def test_execute_move_cross_filesystem_cleanup_deferred_when_repair_fails(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_perm_deferred"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_perm_deferred"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    def fake_copy(_src, _dst):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")

    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)
    monkeypatch.setattr(executor, "_build_relocations", lambda conn, plan: [])
    monkeypatch.setattr(executor, "_build_views", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_relocate_torrents_atomic", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        executor,
        "_delete_path",
        lambda _path: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
    )
    monkeypatch.setattr(executor, "_repair_permissions_for_cleanup", lambda _path: False)

    plan = {
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)
    assert target_path.exists()
    assert source_path.exists()
