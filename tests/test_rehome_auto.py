import sqlite3
from contextlib import contextmanager
from pathlib import Path

import rehome.auto as auto_mod


class _FakeInfo:
    def __init__(self, state: str = "stoppedup", progress: float = 1.0):
        self.state = state
        self.progress = progress


class _FakeQBClient:
    def __init__(self, infos: dict[str, _FakeInfo]):
        self._infos = infos

    def get_torrent_info(self, torrent_hash: str):
        return self._infos.get(torrent_hash)


class _DummyConn:
    def close(self):
        return None


class _DummyLock:
    def close(self):
        return None


class _FakePlanner:
    def __init__(self, plan: dict):
        self._plan = plan

    def plan_batch_demotion_by_payload_hash(self, payload_hash: str):
        return dict(self._plan)

    def plan_batch_promotion_by_payload_hash(self, payload_hash: str):
        return dict(self._plan)


class _FakeExecutor:
    def __init__(self, *args, **kwargs):
        self.qbit_client = object()

    def dry_run(self, plan: dict):
        return None

    def execute(self, plan: dict):
        plan["cleanup_source_deferred"] = True
        plan["cleanup_source_deferred_path"] = plan.get("source_path")
        return None


class _FakeExecutorSourceGone(_FakeExecutor):
    def execute(self, plan: dict):
        plan["cleanup_source_deferred"] = False
        plan.pop("cleanup_source_deferred_path", None)


class _FakeRunLogger:
    dumped_extra = None

    def __init__(self, *args, **kwargs):
        self.verbose = bool(kwargs.get("verbose", False))
        self.debug = bool(kwargs.get("debug", False))

    @contextmanager
    def patch_stdout(self):
        yield

    def dump_json(self, path: Path, extra=None) -> None:
        _FakeRunLogger.dumped_extra = extra

    def close(self) -> None:
        return None

    def write_raw(self, text: str) -> None:
        return None

    def record_step(self, *args, **kwargs) -> None:
        return None


def _catalog_for_inline_verify(tmp_path: Path, *, device_id: int = 141) -> sqlite3.Connection:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            device_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, ?)", (device_id,))
    conn.execute(
        "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, 1)",
        ("abc123",),
    )
    conn.commit()
    return conn


def test_inline_verify_reuse_allows_retained_source(tmp_path: Path) -> None:
    conn = _catalog_for_inline_verify(tmp_path, device_id=141)
    source_path = tmp_path / "still-there"
    source_path.mkdir()
    try:
        ok, summary = auto_mod._inline_verify(
            _FakeQBClient({"abc123": _FakeInfo("stoppedup", 1.0)}),
            conn,
            {
                "decision": "REUSE",
                "affected_torrents": ["abc123"],
                "source_path": str(source_path),
            },
            141,
        )
    finally:
        conn.close()

    assert ok is True
    assert "catalog OK" in summary
    assert "cleanup pending" in summary
    assert "source STILL EXISTS" not in summary


def test_inline_verify_move_requires_source_removed(tmp_path: Path) -> None:
    conn = _catalog_for_inline_verify(tmp_path, device_id=141)
    source_path = tmp_path / "still-there"
    source_path.mkdir()
    try:
        ok, summary = auto_mod._inline_verify(
            _FakeQBClient({"abc123": _FakeInfo("stoppedup", 1.0)}),
            conn,
            {
                "decision": "MOVE",
                "affected_torrents": ["abc123"],
                "source_path": str(source_path),
            },
            141,
        )
    finally:
        conn.close()

    assert ok is False
    assert "source STILL EXISTS" in summary


def test_run_auto_reuse_apply_reports_cleanup_pending(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    plan = {
        "direction": "demote",
        "decision": "REUSE",
        "payload_hash": "payload_hash_123",
        "target_path": "/pool/media/torrents/seeding/cross-seed/Test/Item",
        "source_path": "/pool/data/media/torrents/seeding/cross-seed/Test/Item",
        "source_device_id": 231,
        "target_device_id": 141,
        "affected_torrents": ["abc123"],
        "view_targets": [
            {
                "torrent_hash": "abc123",
                "target_save_path": "/pool/media/torrents/seeding/cross-seed/Test",
            }
        ],
        "reasons": ["Payload already exists on pool-media"],
    }

    monkeypatch.setattr("rehome.runlog.RunLogger", _FakeRunLogger)
    monkeypatch.setattr("hashall.model.connect_db", lambda *args, **kwargs: _DummyConn())
    monkeypatch.setattr("rehome.executor.DemotionExecutor", _FakeExecutor)
    monkeypatch.setattr("rehome.cli._acquire_rehome_lock", lambda: _DummyLock())
    monkeypatch.setattr(
        auto_mod,
        "_device_info",
        lambda _conn, device_id: {
            44: {"alias": "stash", "mount": "/stash"},
            141: {"alias": "pool-media", "mount": "/pool/media"},
            231: {"alias": "pool-data", "mount": "/pool/data"},
        }[device_id],
    )
    monkeypatch.setattr(
        auto_mod,
        "_find_move_candidates",
        lambda *args, **kwargs: [
            {
                "payload_hash": "payload_hash_123",
                "source_bytes": 733 * 1024**3,
                "source_files": 18,
                "torrent_count": 1,
                "source_device_id": 231,
            }
        ],
    )
    monkeypatch.setattr(auto_mod, "_make_planner", lambda **kwargs: _FakePlanner(plan))
    monkeypatch.setattr(
        auto_mod,
        "_inline_verify",
        lambda *args, **kwargs: (True, "stoppedup×1 · 100% · catalog OK · cleanup pending"),
    )

    _FakeRunLogger.dumped_extra = None
    exit_code = auto_mod.run_auto(
        catalog_path=tmp_path / "catalog.db",
        active_device_id=44,
        dest_device_id=141,
        dest_root="/pool/media/torrents/seeding",
        active_root="/stash/media",
        content_root="/stash/media",
        limit=1,
        do_apply=True,
        plan_log_dir=tmp_path / "plans",
        source_device_id=231,
        extra_sources=[(231, "pool-data", "/pool/data")],
        verbose=False,
        debug=False,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "cleanup pending" in out
    assert "source deleted" not in out

    summary = _FakeRunLogger.dumped_extra["summary"]
    assert summary["freed_bytes"] == 0
    assert summary["cleanup_pending"] == 1

    apply_record = _FakeRunLogger.dumped_extra["candidates"][0]["apply"]
    assert apply_record["freed_bytes"] == 0
    assert apply_record["source_cleanup"] == "pending_manual_cleanup"


def test_run_auto_reuse_apply_reports_source_gone_when_not_deferred(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    plan = {
        "direction": "demote",
        "decision": "REUSE",
        "payload_hash": "payload_hash_123",
        "target_path": "/pool/media/torrents/seeding/cross-seed/Test/Item",
        "source_path": "/pool/data/media/torrents/seeding/cross-seed/Test/Item",
        "source_device_id": 231,
        "target_device_id": 141,
        "affected_torrents": ["abc123"],
        "view_targets": [
            {
                "torrent_hash": "abc123",
                "target_save_path": "/pool/media/torrents/seeding/cross-seed/Test",
            }
        ],
        "reasons": ["Payload already exists on pool-media"],
    }

    monkeypatch.setattr("rehome.runlog.RunLogger", _FakeRunLogger)
    monkeypatch.setattr("hashall.model.connect_db", lambda *args, **kwargs: _DummyConn())
    monkeypatch.setattr("rehome.executor.DemotionExecutor", _FakeExecutorSourceGone)
    monkeypatch.setattr("rehome.cli._acquire_rehome_lock", lambda: _DummyLock())
    monkeypatch.setattr(
        auto_mod,
        "_device_info",
        lambda _conn, device_id: {
            44: {"alias": "stash", "mount": "/stash"},
            141: {"alias": "pool-media", "mount": "/pool/media"},
            231: {"alias": "pool-data", "mount": "/pool/data"},
        }[device_id],
    )
    monkeypatch.setattr(
        auto_mod,
        "_find_move_candidates",
        lambda *args, **kwargs: [
            {
                "payload_hash": "payload_hash_123",
                "source_bytes": 50 * 1024**3,
                "source_files": 5,
                "torrent_count": 1,
                "source_device_id": 231,
            }
        ],
    )
    monkeypatch.setattr(auto_mod, "_make_planner", lambda **kwargs: _FakePlanner(plan))
    monkeypatch.setattr(
        auto_mod,
        "_inline_verify",
        lambda *args, **kwargs: (True, "stoppedup×1 · 100% · catalog OK · source gone"),
    )

    _FakeRunLogger.dumped_extra = None
    exit_code = auto_mod.run_auto(
        catalog_path=tmp_path / "catalog.db",
        active_device_id=44,
        dest_device_id=141,
        dest_root="/pool/media/torrents/seeding",
        active_root="/stash/media",
        content_root="/stash/media",
        limit=1,
        do_apply=True,
        plan_log_dir=tmp_path / "plans",
        source_device_id=231,
        extra_sources=[(231, "pool-data", "/pool/data")],
        verbose=False,
        debug=False,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "source gone" in out
    assert "cleanup pending" not in out

    apply_record = _FakeRunLogger.dumped_extra["candidates"][0]["apply"]
    assert apply_record["source_cleanup"] == "already_absent"
