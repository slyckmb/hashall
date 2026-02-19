"""Tests for hardlink_auto_workflow helper logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from hashall.model import connect_db


def _load_workflow_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "hardlink_auto_workflow.py"
    spec = importlib.util.spec_from_file_location("hardlink_auto_workflow", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _insert_plan(conn, *, name: str, device_id: int, notes=None, metadata=None, actions_total: int = 0, actions_executed: int = 0):
    cur = conn.execute(
        """
        INSERT INTO link_plans (
            name, device_id, device_alias, mount_point,
            total_opportunities, total_bytes_saveable,
            actions_total, actions_executed, actions_failed, actions_skipped,
            notes, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            name,
            device_id,
            "stash",
            "/stash/media",
            0,
            0,
            actions_total,
            actions_executed,
            notes,
            metadata,
        ),
    )
    return int(cur.lastrowid)


def test_discover_roots_from_scan_roots(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        "INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count) VALUES (?, ?, ?, ?)",
        ("zfs-1", "/pool/data", "2026-02-11T10:00:00", 1),
    )
    conn.execute(
        "INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count) VALUES (?, ?, ?, ?)",
        ("zfs-2", "/stash/media", "2026-02-11T11:00:00", 1),
    )
    conn.commit()

    roots = workflow._discover_roots(conn)
    conn.close()

    assert roots == ["/stash/media", "/pool/data"]


def test_find_recent_plan_filters_payload_empty_marker(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    normal_plan_id = _insert_plan(conn, name="normal", device_id=49, actions_total=3, actions_executed=1)
    empty_plan_id = _insert_plan(
        conn,
        name="empty",
        device_id=49,
        notes="payload_empty",
        metadata='{"type":"payload_empty"}',
        actions_total=5,
        actions_executed=2,
    )

    conn.execute(
        """
        INSERT INTO link_actions (plan_id, action_type, status, canonical_path, duplicate_path, device_id, file_size, bytes_to_save)
        VALUES (?, 'HARDLINK', 'pending', ?, ?, ?, ?, ?)
        """,
        (normal_plan_id, "torrents/a.bin", "torrents/b.bin", 49, 10, 10),
    )
    conn.execute(
        """
        INSERT INTO link_actions (plan_id, action_type, status, canonical_path, duplicate_path, device_id, file_size, bytes_to_save)
        VALUES (?, 'HARDLINK', 'pending', ?, ?, ?, ?, ?)
        """,
        (empty_plan_id, "torrents/c.bin", "torrents/d.bin", 49, 10, 10),
    )
    conn.commit()

    normal = workflow._find_recent_plan(conn, 49, "torrents", include_payload_empty=False)
    empty = workflow._find_recent_plan(conn, 49, "torrents", include_payload_empty=True)
    conn.close()

    assert normal is not None
    assert normal["id"] == normal_plan_id
    assert normal["actions_pending"] == 2

    assert empty is not None
    assert empty["id"] == empty_plan_id
    assert empty["actions_pending"] == 3


def test_resolve_roots_prefers_explicit_arg(tmp_path):
    workflow = _load_workflow_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        "INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count) VALUES (?, ?, ?, ?)",
        ("zfs-1", "/pool/data", "2026-02-11T10:00:00", 1),
    )
    conn.commit()

    roots = workflow._resolve_roots(conn, "/stash/media,/data/media")
    conn.close()

    assert roots == ["/stash/media", "/data/media"]


def test_stagnation_streak_helper():
    workflow = _load_workflow_module()
    sig = (4, 1, 0)

    streak = workflow.next_stagnation_streak(None, sig, 0)
    assert streak == 0

    streak = workflow.next_stagnation_streak(sig, sig, streak)
    assert streak == 1

    streak = workflow.next_stagnation_streak(sig, (3, 1, 0), streak)
    assert streak == 0

