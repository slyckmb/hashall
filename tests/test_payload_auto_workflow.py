"""Tests for payload_auto_workflow state and logging behavior."""

from __future__ import annotations

import importlib.util
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
