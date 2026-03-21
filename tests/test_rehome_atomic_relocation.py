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
        self.recheck_calls = []

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

    def recheck_torrent(self, torrent_hash: str) -> bool:
        self.recheck_calls.append(torrent_hash)
        return True

    def get_torrent_info(self, torrent_hash: str):
        return SimpleNamespace(
            save_path=self.save_paths.get(torrent_hash, self.default_path),
            auto_tmm=False,
            state="pausedUP",
            progress=1.0,
            amount_left=0,
            size=1024,
            completed=1024,
        )

    def get_torrent_files(self, torrent_hash: str):
        return []


class SequencedStateQbitClient(FakeQbitClient):
    def __init__(self, states):
        super().__init__()
        self._states = list(states)
        self._calls = 0

    def get_torrent_info(self, torrent_hash: str):
        idx = min(self._calls, len(self._states) - 1)
        state, progress = self._states[idx]
        self._calls += 1
        return SimpleNamespace(
            save_path=self.save_paths.get(torrent_hash, self.default_path),
            auto_tmm=False,
            state=state,
            progress=progress,
            amount_left=0,
            size=1024,
            completed=int(1024 * progress),
        )


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


def test_preflight_waits_for_transient_qbit_settle(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = SequencedStateQbitClient(
        [("checkingResumeData", 0.0), ("stalledUP", 1.0)]
    )
    executor.preflight_settle_attempts = 2
    executor.preflight_settle_seconds = 7.0

    plan = {"affected_torrents": ["abc123"]}

    executor._preflight_torrent_state_check_with_settle(plan)

    assert sleeps == [7.0]


def test_preflight_raises_after_transient_settle_window_exhausted(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = SequencedStateQbitClient(
        [("checkingResumeData", 0.0), ("checkingResumeData", 0.0), ("checkingResumeData", 0.0)]
    )
    executor.preflight_settle_attempts = 2
    executor.preflight_settle_seconds = 5.0

    plan = {"affected_torrents": ["abc123"]}

    with pytest.raises(RuntimeError, match="checkingresumedata"):
        executor._preflight_torrent_state_check_with_settle(plan)

    assert sleeps == [5.0, 5.0]


def test_preflight_blocks_qbit_sibling_gap_snapshot(tmp_path):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    plan = {
        "affected_torrents": ["abc123"],
        "_reality_snapshot_pre": {
            "group_state": "blocked_qbit_sibling_gap",
            "group_reason": "qB still has same-name sibling torrents outside this plan.",
            "group_warnings": [
                "qB still has 4 same-name out-of-plan torrent(s) that match this payload's size."
            ],
        },
    }

    with pytest.raises(RuntimeError, match="same-name out-of-plan sibling"):
        executor._preflight_torrent_state_check_with_settle(plan)


def test_copy_with_rsync_progress_applies_bwlimit_env(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")

    commands = []

    class FakeProc:
        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        commands.append(cmd)
        return FakeProc()

    monkeypatch.setenv("REHOME_RSYNC_BWLIMIT_KBPS", "51200")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr("rehome.executor.subprocess.Popen", fake_popen)

    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    target = tmp_path / "target.bin"

    executor._copy_with_rsync_progress(source, target)

    assert commands
    cmd = commands[0]
    assert "--bwlimit=51200" in cmd
    assert str(source) in cmd
    assert str(target) in cmd


def test_copy_with_rsync_progress_ignores_invalid_bwlimit_env(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")

    commands = []
    messages = []

    class FakeProc:
        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        commands.append(cmd)
        return FakeProc()

    monkeypatch.setenv("REHOME_RSYNC_BWLIMIT_KBPS", "abc")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr("rehome.executor.subprocess.Popen", fake_popen)
    monkeypatch.setattr(executor, "_log", lambda message, prefix="info": messages.append((prefix, message)))

    source = tmp_path / "source.bin"
    source.write_bytes(b"x")
    target = tmp_path / "target.bin"

    executor._copy_with_rsync_progress(source, target)

    assert commands
    cmd = commands[0]
    assert not any(part.startswith("--bwlimit=") for part in cmd)
    assert any(prefix == "warning" and "REHOME_RSYNC_BWLIMIT_KBPS" in msg for prefix, msg in messages)


def test_ensure_target_donor_rejects_dirty_preexisting_target(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    monkeypatch.setattr(executor, "_spot_check_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        executor,
        "_copy_with_rsync_progress",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy should not run")),
    )

    source = tmp_path / "source"
    source.mkdir()
    (source / "movie.mkv").write_bytes(b"payload")

    target = tmp_path / "target"
    target.mkdir()
    (target / "movie.mkv").write_bytes(b"payload")
    (target / "extra.nfo").write_bytes(b"extra")

    plan = {
        "decision": "MOVE",
        "source_path": str(source),
        "target_path": str(target),
        "file_count": 1,
        "total_bytes": len(b"payload"),
        "target_device_id": 44,
    }

    with pytest.raises(RuntimeError, match="Refusing MOVE into preexisting non-empty target") as excinfo:
        executor._ensure_target_donor(plan)

    message = str(excinfo.value)
    assert "expected_files=1" in message
    assert "actual_files=2" in message
    assert f"expected_bytes={len(b'payload')}" in message


def test_ensure_target_donor_reuses_exact_preexisting_target(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    monkeypatch.setattr(executor, "_spot_check_payload", lambda *args, **kwargs: None)
    copy_called = {"value": False}

    def fake_copy(*_args, **_kwargs):
        copy_called["value"] = True

    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)

    source = tmp_path / "source"
    source.mkdir()
    (source / "movie.mkv").write_bytes(b"payload")

    target = tmp_path / "target"
    target.mkdir()
    (target / "movie.mkv").write_bytes(b"payload")

    plan = {
        "decision": "MOVE",
        "source_path": str(source),
        "target_path": str(target),
        "file_count": 1,
        "total_bytes": len(b"payload"),
        "target_device_id": 44,
    }

    donor = executor._ensure_target_donor(plan)

    assert copy_called["value"] is False
    assert donor.acquisition_mode == "existing"
    assert donor.move_strategy == "idempotent_reconcile"
    assert donor.moved_payload is False
    assert donor.target_preexisting is True


def test_cleanup_unused_target_donor_removes_intermediate_root(tmp_path):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")

    donor_root = tmp_path / "pool-media" / "cross-seed" / "Donor"
    donor_root.mkdir(parents=True, exist_ok=True)
    (donor_root / "movie.mkv").write_bytes(b"movie")

    unique_root = tmp_path / "pool-media" / "_rehome-unique" / "hash-a" / "Movie"
    unique_root.mkdir(parents=True, exist_ok=True)
    (unique_root / "movie.mkv").write_bytes(b"movie")

    plan = {
        "_reality_snapshot_pre": {"summary": {"out_of_plan_siblings": 0}},
        "constructed_payload_roots": {"hash-a": str(unique_root)},
    }

    removed = executor._cleanup_unused_target_donor(
        plan,
        SimpleNamespace(target_path=donor_root),
    )

    assert removed is True
    assert not donor_root.exists()
    assert plan["cleanup_unused_target_donor"] == str(donor_root.resolve())


def test_cleanup_unused_target_donor_keeps_single_file_direct_target(tmp_path):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")

    donor_file = tmp_path / "pool-media" / "abtorrents" / "book.epub"
    donor_file.parent.mkdir(parents=True, exist_ok=True)
    donor_file.write_bytes(b"book")

    plan = {
        "_reality_snapshot_pre": {"summary": {"out_of_plan_siblings": 0}},
        # Single-file direct-target runs currently record the constructed root
        # as the parent directory, not the file path itself.
        "constructed_payload_roots": {"hash-a": str(donor_file.parent)},
        "payload_group": [
            {
                "hash": "hash-a",
                "dest_content_path": str(donor_file),
            }
        ],
    }

    removed = executor._cleanup_unused_target_donor(
        plan,
        SimpleNamespace(target_path=donor_file),
    )

    assert removed is False
    assert donor_file.exists()
    assert "cleanup_unused_target_donor" not in plan


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


def test_atomic_relocation_guard_blocks_resume_when_qb_reports_incomplete(tmp_path, monkeypatch):
    class IncompleteQbitClient(FakeQbitClient):
        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="pausedDL",
                progress=0.92,
                amount_left=12345,
                size=1024,
                completed=512,
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = IncompleteQbitClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    with pytest.raises(RuntimeError, match="seed-readiness guard failed"):
        executor._relocate_torrents_atomic(relocations)


def test_atomic_relocation_requests_recheck_before_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    executor._relocate_torrents_atomic(relocations)
    assert executor.qbit_client.recheck_calls == ["t1"]


def test_recheck_guard_waits_for_stable_ready_after_delayed_checking(tmp_path, monkeypatch):
    class DelayedCheckingClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self._seq = [
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="checkingUP", progress=0.25, amount_left=768, size=1024, completed=256),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
            ]
            self.info_calls = 0

        def get_torrent_info(self, torrent_hash: str):
            idx = min(self.info_calls, len(self._seq) - 1)
            self.info_calls += 1
            return self._seq[idx]

    fake_clock = {"t": 0.0}

    def _fake_monotonic():
        return fake_clock["t"]

    def _fake_sleep(seconds):
        fake_clock["t"] += seconds

    monkeypatch.setattr("time.monotonic", _fake_monotonic)
    monkeypatch.setattr("time.sleep", _fake_sleep)

    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = DelayedCheckingClient()
    executor.recheck_ready_stable_seconds = 4.0
    executor._get_torrent_info_with_retry = lambda *args, **kwargs: SimpleNamespace(
        size=1024, completed=1024, state="stoppedUP", progress=1.0, amount_left=0
    )

    executor._ensure_qb_seed_ready_after_relocate(
        "t1",
        min_timeout_seconds=10.0,
        interval_seconds=2.0,
    )

    assert executor.qbit_client.recheck_calls == ["t1"]
    assert executor.qbit_client.info_calls >= 6


def test_recheck_guard_tolerates_brief_stoppeddl_queue_before_checking(tmp_path, monkeypatch):
    class QueuedRecheckClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self._seq = [
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedDL", progress=0.0, amount_left=1024, size=1024, completed=0),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedDL", progress=0.0, amount_left=1024, size=1024, completed=0),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="checkingUP", progress=0.25, amount_left=768, size=1024, completed=256),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="checkingUP", progress=0.75, amount_left=256, size=1024, completed=768),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
                SimpleNamespace(save_path="/pool/seeding", auto_tmm=False, state="stoppedUP", progress=1.0, amount_left=0, size=1024, completed=1024),
            ]
            self.info_calls = 0

        def get_torrent_info(self, torrent_hash: str):
            idx = min(self.info_calls, len(self._seq) - 1)
            self.info_calls += 1
            return self._seq[idx]

    fake_clock = {"t": 0.0}

    def _fake_monotonic():
        return fake_clock["t"]

    def _fake_sleep(seconds):
        fake_clock["t"] += seconds

    monkeypatch.setattr("time.monotonic", _fake_monotonic)
    monkeypatch.setattr("time.sleep", _fake_sleep)

    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = QueuedRecheckClient()
    executor.recheck_ready_stable_seconds = 4.0
    executor.recheck_queue_grace_seconds = 10.0
    executor._get_torrent_info_with_retry = lambda *args, **kwargs: SimpleNamespace(
        size=1024, completed=1024, state="stoppedUP", progress=1.0, amount_left=0
    )

    executor._ensure_qb_seed_ready_after_relocate(
        "t1",
        min_timeout_seconds=10.0,
        interval_seconds=2.0,
    )

    assert executor.qbit_client.recheck_calls == ["t1"]
    assert executor.qbit_client.info_calls >= 7


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


def test_atomic_relocation_verifies_before_resume_when_resume_enabled(tmp_path, monkeypatch):
    class OrderedQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.resume_calls = 0

        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="uploading",
            )

        def resume_torrent(self, torrent_hash: str) -> bool:
            self.resume_calls += 1
            return True

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setenv("HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE", "1")
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


def test_atomic_relocation_keeps_torrents_paused_by_default(tmp_path, monkeypatch):
    class PausedByDefaultClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.resume_calls = 0

        def resume_torrent(self, torrent_hash: str) -> bool:
            self.resume_calls += 1
            return True

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.delenv("HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE", raising=False)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = PausedByDefaultClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]
    executor._relocate_torrents_atomic(relocations)
    assert executor.qbit_client.resume_calls == 0


def test_atomic_relocation_only_resumes_torrents_that_were_active_before_pause(tmp_path, monkeypatch):
    class MixedStateClient(FakeQbitClient):
        def __init__(self):
            super().__init__()
            self.resume_hashes = []
            self.states = {"t_paused": "pausedUP", "t_active": "uploading"}

        def resume_torrent(self, torrent_hash: str) -> bool:
            self.resume_hashes.append(torrent_hash)
            return True

        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state=self.states.get(torrent_hash, "pausedUP"),
                progress=1.0,
                amount_left=0,
                size=1024,
                completed=1024,
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setenv("HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE", "1")
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = MixedStateClient()

    relocations = [
        {"torrent_hash": "t_paused", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
        {"torrent_hash": "t_active", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]
    executor._relocate_torrents_atomic(relocations)

    assert executor.qbit_client.resume_hashes == ["t_active"]


def test_atomic_relocation_uses_size_aware_verify_timeout(tmp_path, monkeypatch):
    class LargeMoveQbitClient(FakeQbitClient):
        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                auto_tmm=False,
                state="pausedUP",
                size=25 * 1024**3,
                total_size=25 * 1024**3,
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = LargeMoveQbitClient()

    waits = []

    def fake_wait(_hash, expected, **kwargs):
        waits.append(kwargs.get("timeout_seconds"))
        return SimpleNamespace(save_path=str(expected), auto_tmm=False), expected

    monkeypatch.setattr(executor, "_wait_for_save_path", fake_wait)

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]
    executor._relocate_torrents_atomic(relocations)

    # Verify waits should include a materially larger timeout than the legacy fixed value.
    assert waits
    assert max(waits) >= 700.0


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


def test_execute_move_cross_filesystem_uses_rsync_and_defers_source_cleanup(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    popen_calls = []

    class FakeProc:
        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        if "rsync" in cmd:
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / "video.mkv").write_bytes(b"x")
        return FakeProc()

    monkeypatch.setattr("rehome.executor.subprocess.Popen", fake_popen)
    monkeypatch.setattr(executor, "_attach_torrents_to_donor", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        executor,
        "_relocate_torrents_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("MOVE must not call setLocation relocation")),
    )

    plan = {
        "decision": "MOVE",
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)

    assert any("rsync" in cmd for cmd in popen_calls)
    assert target_path.exists()
    assert source_path.exists()
    assert plan["cleanup_source_deferred"] is True
    assert plan["cleanup_source_deferred_path"] == str(source_path)


def test_execute_move_cross_filesystem_relocation_failure_keeps_source(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_fail"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_fail"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    def fake_copy(_source, _target):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")
    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)
    def fail_attach(*_args, **_kwargs):
        raise RuntimeError("relocation failed")

    monkeypatch.setattr(executor, "_attach_torrents_to_donor", fail_attach)

    plan = {
        "decision": "MOVE",
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

    def fail_attach(exec_plan, donor, **_kwargs):
        payload_root = donor.target_path
        for target in exec_plan.get("view_targets") or []:
            dst = Path(target["target_save_path"]) / target["root_name"]
            if dst == payload_root:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(payload_root, dst)
        raise RuntimeError("relocation failed")

    monkeypatch.setattr(executor, "_attach_torrents_to_donor", fail_attach)

    plan = {
        "decision": "MOVE",
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
        "_created_target_views": [str(side_view_path)],
    }

    with pytest.raises(RuntimeError, match="relocation failed"):
        executor._execute_move(plan, spot_check=0)

    assert source_path.exists()
    assert not target_path.exists()
    assert not side_view_path.exists()


def test_ensure_target_donor_promotes_move_to_reuse_when_existing_target_family_view_matches(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    monkeypatch.setattr(executor, "_spot_check_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        executor,
        "_copy_with_rsync_progress",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy should not run")),
    )

    source = tmp_path / "pool-data" / "cross-seed" / "Aither" / "Show.S01"
    source.mkdir(parents=True)
    (source / "episode.mkv").write_bytes(b"payload")

    existing_target = tmp_path / "pool-media" / "cross-seed" / "TorrentLeech" / "Show.S01"
    existing_target.mkdir(parents=True)
    (existing_target / "episode.mkv").write_bytes(b"payload")

    plan = {
        "decision": "MOVE",
        "source_path": str(source),
        "target_path": str(tmp_path / "pool-media" / "cross-seed" / "hawke-uno" / "Show.S01"),
        "file_count": 1,
        "total_bytes": len(b"payload"),
        "target_device_id": 44,
        "view_targets": [
            {
                "torrent_hash": "hash_a",
                "source_save_path": str(source.parent),
                "target_save_path": str(tmp_path / "pool-media" / "cross-seed" / "Aither"),
                "root_name": "Show.S01",
            },
            {
                "torrent_hash": "hash_b",
                "source_save_path": str(source.parent),
                "target_save_path": str(existing_target.parent),
                "root_name": "Show.S01",
            },
        ],
    }

    donor = executor._ensure_target_donor(plan)

    assert plan["decision"] == "REUSE"
    assert plan["target_path"] == str(existing_target)
    assert donor.acquisition_mode == "existing"
    assert donor.target_path == existing_target


def test_ensure_target_donor_blocks_before_copy_on_conflicting_existing_target_family_view(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    monkeypatch.setattr(executor, "_spot_check_payload", lambda *args, **kwargs: None)
    copy_called = {"value": False}

    def fake_copy(*_args, **_kwargs):
        copy_called["value"] = True

    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)

    source = tmp_path / "pool-data" / "cross-seed" / "Aither" / "Show.S01"
    source.mkdir(parents=True)
    (source / "episode.mkv").write_bytes(b"payload")

    conflicting_target = tmp_path / "pool-media" / "cross-seed" / "Aither" / "Show.S01"
    conflicting_target.mkdir(parents=True)
    (conflicting_target / "episode.mkv").write_bytes(b"payload")
    (conflicting_target / "extra.nfo").write_bytes(b"extra")

    plan = {
        "decision": "MOVE",
        "source_path": str(source),
        "target_path": str(tmp_path / "pool-media" / "cross-seed" / "hawke-uno" / "Show.S01"),
        "file_count": 1,
        "total_bytes": len(b"payload"),
        "target_device_id": 44,
        "view_targets": [
            {
                "torrent_hash": "hash_a",
                "source_save_path": str(source.parent),
                "target_save_path": str(conflicting_target.parent),
                "root_name": "Show.S01",
            },
        ],
    }

    with pytest.raises(RuntimeError, match="Target family conflict exists before apply"):
        executor._ensure_target_donor(plan)

    assert copy_called["value"] is False


def test_execute_reuse_blocks_same_size_different_content_target_family_before_apply(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    copy_called = {"value": False}

    def fake_copy(*_args, **_kwargs):
        copy_called["value"] = True

    monkeypatch.setattr(executor, "_copy_with_rsync_progress", fake_copy)

    source = tmp_path / "pool-data" / "cross-seed" / "TorrentDay" / "Show.S01"
    source.mkdir(parents=True)
    (source / "episode1.mkv").write_bytes(b"payload-a")
    (source / "episode2.mkv").write_bytes(b"payload-b")

    exact_target = tmp_path / "pool-media" / "cross-seed" / "TorrentDay" / "Show.S01"
    exact_target.mkdir(parents=True)
    (exact_target / "episode1.mkv").write_bytes(b"payload-a")
    (exact_target / "episode2.mkv").write_bytes(b"payload-b")

    conflicting_target = tmp_path / "pool-media" / "cross-seed" / "Aither" / "Show.S01"
    conflicting_target.mkdir(parents=True)
    (conflicting_target / "episode1.mkv").write_bytes(b"payload-x")
    (conflicting_target / "episode2.mkv").write_bytes(b"payload-y")

    plan = {
        "decision": "REUSE",
        "source_path": str(source),
        "target_path": str(exact_target),
        "payload_hash": "payload_hash_conflict",
        "file_count": 2,
        "total_bytes": len(b"payload-a") + len(b"payload-b"),
        "target_device_id": 44,
        "view_targets": [
            {
                "torrent_hash": "hash_td",
                "source_save_path": str(source.parent),
                "target_save_path": str(exact_target.parent),
                "root_name": "Show.S01",
            },
            {
                "torrent_hash": "hash_ai",
                "source_save_path": str(source.parent),
                "target_save_path": str(conflicting_target.parent),
                "root_name": "Show.S01",
            },
        ],
    }

    with pytest.raises(RuntimeError, match="Target family conflict exists before apply"):
        executor._ensure_target_donor(plan)

    assert copy_called["value"] is False


def test_rollback_partial_target_views_only_removes_paths_created_by_current_run(tmp_path):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")

    preexisting = tmp_path / "pool-media" / "cross-seed" / "Aither" / "Show.S01"
    preexisting.mkdir(parents=True)
    (preexisting / "episode.mkv").write_bytes(b"payload")

    created = tmp_path / "pool-media" / "cross-seed" / "TorrentLeech" / "Show.S01"
    created.mkdir(parents=True)
    (created / "episode.mkv").write_bytes(b"payload")

    plan = {
        "source_path": str(tmp_path / "pool-data" / "cross-seed" / "Aither" / "Show.S01"),
        "target_path": str(tmp_path / "pool-media" / "cross-seed" / "hawke-uno" / "Show.S01"),
        "seeding_roots": [str(tmp_path / "pool-media"), str(tmp_path / "pool-data")],
        "_created_target_views": [str(created)],
    }

    executor._rollback_partial_target_views(plan)

    assert preexisting.exists()
    assert created.exists() is False


def test_execute_move_spot_check_no_sha256_does_not_fail(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "src_payload_nosha"
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "video.mkv").write_bytes(b"x")
    target_path = tmp_path / "dst_payload_nosha"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: True)

    class FakeProc:
        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "video.mkv").write_bytes(b"x")
        return FakeProc()

    monkeypatch.setattr("rehome.executor.subprocess.Popen", fake_popen)
    monkeypatch.setattr(executor, "_attach_torrents_to_donor", lambda *args, **kwargs: {})
    monkeypatch.setattr("rehome.executor.get_payload_file_rows", lambda *_args, **_kwargs: [])

    plan = {
        "decision": "MOVE",
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=1)
    assert target_path.exists()
    assert source_path.exists()
    assert plan["cleanup_source_deferred"] is True


def test_execute_move_filters_view_target_that_recreates_source(tmp_path, monkeypatch):
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = FakeQbitClient()

    source_path = tmp_path / "pool" / "data" / "seeds" / "cross-seed" / "thegeeks" / "book.epub"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"x")
    target_path = tmp_path / "pool" / "data" / "seeds" / "thegeeks" / "book.epub"

    monkeypatch.setattr(executor, "_is_cross_filesystem", lambda *_: False)

    captured = {}

    def fake_attach(exec_plan, donor, **_kwargs):
        captured["view_targets"] = list(exec_plan.get("view_targets") or [])
        return {}

    monkeypatch.setattr(executor, "_attach_torrents_to_donor", fake_attach)

    plan = {
        "decision": "MOVE",
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
        "view_targets": [
            {
                "torrent_hash": "t1",
                "source_save_path": str(source_path.parent),
                "target_save_path": str(source_path.parent),
                "root_name": source_path.name,
            }
        ],
    }

    executor._execute_move(plan, spot_check=0)
    assert captured["view_targets"] == []
    assert target_path.exists()
    assert source_path.exists()
    assert plan["cleanup_source_deferred"] is True


def test_atomic_relocation_fails_when_qb_content_path_stays_missing(tmp_path, monkeypatch):
    class MissingContentQbitClient(FakeQbitClient):
        def __init__(self):
            super().__init__(default_path="/stash/seeding")
            self.missing_content = tmp_path / "does-not-exist" / "payload.mkv"

        def get_torrent_info(self, torrent_hash: str):
            return SimpleNamespace(
                save_path=self.save_paths.get(torrent_hash, self.default_path),
                content_path=str(self.missing_content),
                auto_tmm=False,
                state="pausedUP",
            )

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    executor = DemotionExecutor(catalog_path=tmp_path / "db.sqlite")
    executor.qbit_client = MissingContentQbitClient()

    relocations = [
        {"torrent_hash": "t1", "source_save_path": "/stash/seeding", "target_save_path": "/pool/seeding"},
    ]

    with pytest.raises(RuntimeError, match="qB content path missing after relocation"):
        executor._relocate_torrents_atomic(relocations)

    # Rollback should restore qB save_path authority after failed validation.
    assert executor.qbit_client.save_paths["t1"] == "/stash/seeding"


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


def test_execute_move_cross_filesystem_marks_cleanup_pending(tmp_path, monkeypatch):
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
    monkeypatch.setattr(executor, "_attach_torrents_to_donor", lambda *args, **kwargs: {})

    plan = {
        "decision": "MOVE",
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)
    assert target_path.exists()
    assert source_path.exists()
    assert plan["cleanup_source_deferred"] is True
    assert plan["cleanup_source_deferred_path"] == str(source_path)


def test_execute_move_cross_filesystem_cleanup_stays_deferred(tmp_path, monkeypatch):
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
    monkeypatch.setattr(executor, "_attach_torrents_to_donor", lambda *args, **kwargs: {})

    plan = {
        "decision": "MOVE",
        "source_path": str(source_path),
        "target_path": str(target_path),
        "file_count": 1,
        "total_bytes": 1,
        "target_device_id": 44,
    }

    executor._execute_move(plan, spot_check=0)
    assert target_path.exists()
    assert source_path.exists()
    assert plan["cleanup_source_deferred"] is True
