"""Tests for payload_auto_workflow state and logging behavior."""

from __future__ import annotations

import importlib.util
import os
import json
from pathlib import Path

from hashall.model import connect_db


def _load_workflow_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "payload_auto_workflow.py"
    spec = importlib.util.spec_from_file_location("payload_auto_workflow", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _insert_payload(conn, root_path: str, *, device_id: int = 49, status: str = "incomplete", file_count: int = 0, total_bytes: int = 0) -> int:
    cur = conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, device_id, root_path, file_count, total_bytes, status),
    )
    return int(cur.lastrowid)


def test_collect_workflow_state_scopes_collisions(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    _insert_payload(conn, "/data/media/a", file_count=0, total_bytes=0, status="incomplete")
    _insert_payload(conn, "/data/media/b", file_count=0, total_bytes=0, status="incomplete")
    _insert_payload(conn, "/stash/media/ok1", file_count=1, total_bytes=100, status="complete")
    _insert_payload(conn, "/stash/media/ok2", file_count=1, total_bytes=200, status="complete")
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/stash/media"])
    conn.close()

    assert state["collision_groups_global"] == 1
    assert state["collision_groups_in_scope"] == 0
    assert state["dirty_in_scope"] == 0
    assert state["dirty_out_of_scope"] == 2


def test_collect_workflow_state_uses_target_root_dirty_path(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    _insert_payload(conn, "/data/media/out-of-scope", file_count=0, total_bytes=0)
    p1 = _insert_payload(conn, "/pool/data/not-seeding", file_count=0, total_bytes=0)
    p2 = _insert_payload(conn, "/stash/media/torrents/seeding/one", file_count=0, total_bytes=0)
    p3 = _insert_payload(conn, "/stash/media/other/two", file_count=0, total_bytes=0)
    conn.executemany(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("h1", p1, 49, "/pool/data", "not-seeding", "", "", 1.0),
            ("h2", p2, 49, "/stash/media", "one", "", "", 1.0),
            ("h3", p3, 49, "/stash/media", "two", "", "", 1.0),
        ],
    )
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/pool/data", "/stash/media"])
    conn.close()

    assert state["dirty_in_scope"] == 3
    assert state["scan_path"] == "/stash/media/torrents/seeding"


def test_collect_workflow_state_remaps_scan_path_to_preferred_mount(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point)
        VALUES (?, ?, ?, ?)
        """,
        ("zfs-49", 49, "/data/media", "/stash/media"),
    )
    payload_id = _insert_payload(conn, "/data/media/torrents/seeding/one", file_count=0, total_bytes=0)
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("h-data", payload_id, 49, "/data/media", "one", "", "", 1.0),
    )
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/pool/data", "/stash/media", "/data/media"])
    conn.close()

    assert state["dirty_in_scope"] == 1
    assert state["scan_path"] == "/stash/media/torrents/seeding"


def test_collect_workflow_state_marks_orphan_dirty_in_scope(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    _insert_payload(conn, "/stash/media/torrents/seeding/orphan", file_count=0, total_bytes=0)
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/stash/media"])
    conn.close()

    assert state["dirty_in_scope"] == 0
    assert state["dirty_orphan_in_scope"] == 1
    assert state["dirty_total_in_scope"] == 1
    assert state["orphan_gc_tracked_in_scope"] == 0
    assert state["orphan_gc_aged_in_scope"] == 0


def test_collect_workflow_state_splits_alias_orphan_rows_with_live_files(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point)
        VALUES (?, ?, ?, ?)
        """,
        ("zfs-49", 49, "/data/media", "/stash/media"),
    )
    conn.execute(
        """
        CREATE TABLE files_49 (
            path TEXT PRIMARY KEY,
            size INTEGER,
            sha256 TEXT,
            status TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO files_49 (path, size, sha256, status) VALUES (?, ?, ?, ?)",
        ("torrents/seeding/cross-seed/alias-item/file.mkv", 123, "abc", "active"),
    )

    _insert_payload(
        conn,
        "/data/media/torrents/seeding/cross-seed/alias-item",
        device_id=49,
        file_count=0,
        total_bytes=0,
        status="incomplete",
    )
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/data/media", "/stash/media"])
    conn.close()

    assert state["dirty_orphan_in_scope"] == 0
    assert state["dirty_orphan_alias_in_scope"] == 1
    assert state["dirty_orphan_alias_samples_in_scope"] == [
        "/data/media/torrents/seeding/cross-seed/alias-item"
    ]


def test_collect_workflow_state_ignores_noncomplete_refs_when_filter_active(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    actionable = _insert_payload(conn, "/stash/media/torrents/seeding/ready", file_count=0, total_bytes=0)
    pending = _insert_payload(conn, "/stash/media/torrents/seeding/pending", file_count=0, total_bytes=0)
    conn.executemany(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("complete-hash", actionable, 49, "/stash/media", "ready", "", "", 1.0),
            ("pending-hash", pending, 49, "/stash/media", "pending", "", "", 1.0),
        ],
    )
    conn.commit()

    state = workflow.collect_workflow_state(
        conn,
        ["/stash/media"],
        completed_hashes={"complete-hash"},
        completion_filter_active=True,
    )
    conn.close()

    assert state["dirty_in_scope"] == 1
    assert state["dirty_noncomplete_in_scope"] == 1
    assert state["dirty_total_in_scope"] == 2
    assert state["scan_path"] == "/stash/media/torrents/seeding"


def test_collect_workflow_state_collision_counts_ignore_noncomplete_refs(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    a = _insert_payload(conn, "/stash/media/a", file_count=0, total_bytes=0)
    b = _insert_payload(conn, "/stash/media/b", file_count=0, total_bytes=0)
    conn.executemany(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("noncomplete-a", a, 49, "/stash/media", "a", "", "", 1.0),
            ("noncomplete-b", b, 49, "/stash/media", "b", "", "", 1.0),
        ],
    )
    conn.commit()

    state_without_filter = workflow.collect_workflow_state(conn, ["/stash/media"])
    state_with_filter = workflow.collect_workflow_state(
        conn,
        ["/stash/media"],
        completed_hashes=set(),
        completion_filter_active=True,
    )
    conn.close()

    assert state_without_filter["collision_groups_in_scope"] == 1
    assert state_with_filter["collision_groups_in_scope"] == 0


def test_collect_workflow_state_reports_orphan_gc_metrics(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    payload_id = _insert_payload(conn, "/stash/media/torrents/seeding/orphan", file_count=0, total_bytes=0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payload_orphan_gc (
            payload_id INTEGER PRIMARY KEY,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1,
            last_root_path TEXT,
            last_device_id INTEGER
        )
        """
    )
    old_seen = 1_700_000_000.0
    conn.execute(
        """
        INSERT INTO payload_orphan_gc (payload_id, first_seen_at, last_seen_at, seen_count, last_root_path, last_device_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payload_id, old_seen, old_seen, 2, "/stash/media/torrents/seeding/orphan", 49),
    )
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/stash/media"])
    conn.close()

    assert state["orphan_gc_tracked_in_scope"] == 1
    assert state["orphan_gc_aged_in_scope"] == 1


def test_mount_alias_hint_for_out_of_scope_dirty_rows(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point)
        VALUES (?, ?, ?, ?)
        """,
        ("zfs-1", 49, "/data/media", "/stash/media"),
    )
    _insert_payload(conn, "/data/media/torrents/seeding/legacy", file_count=0, total_bytes=0)
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/stash/media"])
    conn.close()

    assert state["mount_alias_hint"] is not None
    assert "/data/media" in state["mount_alias_hint"]
    assert "/stash/media" in state["mount_alias_hint"]


def test_next_stagnation_streak_tracks_unchanged_state():
    workflow = _load_workflow_module()
    sig = (5, 0, 1)

    streak = workflow.next_stagnation_streak(None, sig, 0)
    assert streak == 0

    streak = workflow.next_stagnation_streak(sig, sig, streak)
    assert streak == 1

    streak = workflow.next_stagnation_streak(sig, sig, streak)
    assert streak == 2

    streak = workflow.next_stagnation_streak(sig, (4, 0, 1), streak)
    assert streak == 0


def test_log_event_writes_jsonl(tmp_path):
    workflow = _load_workflow_module()
    log_path = tmp_path / "payload-auto.jsonl"

    workflow._log_event(log_path, "iteration_state", iteration=1, state={"dirty_in_scope": 3})

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "iteration_state"
    assert row["iteration"] == 1
    assert row["state"]["dirty_in_scope"] == 3


def test_backup_db_creates_timestamped_copy(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    db_path.write_bytes(b"db-bytes")
    backup_dir = tmp_path / "backups"

    backup_path = workflow._backup_db(db_path, backup_dir=backup_dir)

    assert backup_path.exists()
    assert backup_path.parent == backup_dir
    assert backup_path.name.startswith("catalog.db.backup-")
    assert backup_path.read_bytes() == b"db-bytes"


def test_qbit_manage_freshness_fresh(tmp_path, monkeypatch):
    workflow = _load_workflow_module()
    log_path = tmp_path / "activity.log"
    log_path.write_text("ok\n", encoding="utf-8")
    now = 2_000_000_000
    os.utime(log_path, (now - 30, now - 30))
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG", str(log_path))
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG_ONLY", "1")
    monkeypatch.setenv("HASHALL_QBM_FRESH_MAX_MINUTES", "5")
    monkeypatch.setattr(workflow.time, "time", lambda: float(now))

    result = workflow._qbit_manage_freshness()

    assert result["status"] == "fresh"
    assert result["path"] == str(log_path)
    assert result["max_age_seconds"] == 300


def test_qbit_manage_freshness_stale(tmp_path, monkeypatch):
    workflow = _load_workflow_module()
    log_path = tmp_path / "activity.log"
    log_path.write_text("ok\n", encoding="utf-8")
    now = 2_000_000_000
    os.utime(log_path, (now - 601, now - 601))
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG", str(log_path))
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG_ONLY", "1")
    monkeypatch.setenv("HASHALL_QBM_FRESH_MAX_MINUTES", "10")
    monkeypatch.setattr(workflow.time, "time", lambda: float(now))

    result = workflow._qbit_manage_freshness()

    assert result["status"] == "stale"
    assert result["path"] == str(log_path)
    assert result["max_age_seconds"] == 600


def test_qbit_manage_freshness_unknown_when_log_missing(tmp_path, monkeypatch):
    workflow = _load_workflow_module()
    missing_log = tmp_path / "missing.log"
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG", str(missing_log))
    monkeypatch.setenv("HASHALL_QBM_ACTIVITY_LOG_ONLY", "1")

    result = workflow._qbit_manage_freshness()

    assert result["status"] == "unknown"
    assert result["reason"] == "activity_log_not_found"
    assert result["path"] == str(missing_log)



def test_batch_live_active_file_counts_counts_multiple_roots(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point)
        VALUES (?, ?, ?, ?)
        """,
        ("zfs-49", 49, "/data/media", "/stash/media"),
    )
    conn.execute(
        """
        CREATE TABLE files_49 (
            path TEXT PRIMARY KEY,
            size INTEGER,
            sha256 TEXT,
            status TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO files_49 (path, size, sha256, status) VALUES (?, ?, ?, ?)",
        [
            ("torrents/seeding/A/file1.mkv", 1, "a", "active"),
            ("torrents/seeding/A/file2.mkv", 1, "b", "active"),
            ("torrents/seeding/B/file1.mkv", 1, "c", "active"),
        ],
    )
    conn.commit()

    counts = workflow._batch_live_active_file_counts(
        conn,
        [
            (49, "/data/media/torrents/seeding/A"),
            (49, "/data/media/torrents/seeding/B"),
            (49, "/data/media/torrents/seeding/C"),
        ],
    )
    conn.close()

    assert counts[(49, "/data/media/torrents/seeding/A")] == 2
    assert counts[(49, "/data/media/torrents/seeding/B")] == 1
    assert counts[(49, "/data/media/torrents/seeding/C")] == 0


def test_main_fail_closed_stops_on_stale_qbit_manage(monkeypatch, tmp_path):
    workflow = _load_workflow_module()

    class DummyConn:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    conn = DummyConn()
    log_path = tmp_path / "payload-auto.jsonl"

    monkeypatch.setattr(workflow, "connect_db", lambda db_path: conn)
    monkeypatch.setattr(workflow, "_discover_roots", lambda _conn: ["/stash/media"])
    monkeypatch.setattr(workflow, "_load_completed_torrent_hashes", lambda: (set(), True, None))
    monkeypatch.setattr(
        workflow,
        "_qbit_manage_freshness",
        lambda: {
            "status": "stale",
            "path": "/tmp/activity.log",
            "age_seconds": 600,
            "max_age_seconds": 300,
            "reason": None,
        },
    )
    monkeypatch.setattr(workflow, "_workflow_log_path", lambda run_id: log_path)
    monkeypatch.setenv("HASHALL_QBM_FRESH_FAIL_CLOSED", "1")
    monkeypatch.setattr(workflow.sys, "argv", ["payload_auto_workflow.py", "--db", str(tmp_path / "catalog.db")])

    rc = workflow.main()

    assert rc == 1
    assert conn.closed is True
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert any('"event": "run_failed"' in line for line in lines)
    assert any('"reason": "qbit_manage_freshness_not_fresh"' in line for line in lines)
