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


def _insert_payload(conn, root_path: str, *, device_id: int = 49, status: str = "incomplete", file_count: int = 0, total_bytes: int = 0):
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, device_id, root_path, file_count, total_bytes, status),
    )


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
    _insert_payload(conn, "/pool/data/not-seeding", file_count=0, total_bytes=0)
    _insert_payload(conn, "/stash/media/torrents/seeding/one", file_count=0, total_bytes=0)
    _insert_payload(conn, "/stash/media/other/two", file_count=0, total_bytes=0)
    conn.commit()

    state = workflow.collect_workflow_state(conn, ["/pool/data", "/stash/media"])
    conn.close()

    assert state["dirty_in_scope"] == 3
    assert state["scan_path"] == "/stash/media/torrents/seeding"


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
