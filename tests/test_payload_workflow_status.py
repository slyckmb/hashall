"""Tests for payload_workflow_status alignment with payload-auto semantics."""

from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from hashall.model import connect_db


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "payload_workflow_status.py"
    spec = importlib.util.spec_from_file_location("payload_workflow_status", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _insert_payload(conn, root_path: str, *, status: str = "incomplete", file_count: int = 0, total_bytes: int = 0, payload_hash: str | None = None) -> int:
    cur = conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payload_hash, 49, root_path, file_count, total_bytes, status),
    )
    return int(cur.lastrowid)


def _insert_torrent_ref(conn, payload_id: int, torrent_hash: str) -> None:
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (torrent_hash, payload_id, 49, "/stash/media/torrents/seeding", f"root-{payload_id}", "", "", 1.0),
    )


def test_collect_status_context_splits_actionable_noncomplete_and_orphan(tmp_path):
    module = _load_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    actionable = _insert_payload(conn, "/stash/media/torrents/seeding/actionable", file_count=0)
    noncomplete = _insert_payload(conn, "/stash/media/torrents/seeding/noncomplete", file_count=0)
    _insert_payload(conn, "/stash/media/torrents/seeding/orphan", file_count=0)

    c1 = _insert_payload(conn, "/stash/media/torrents/seeding/collide-a", file_count=1, total_bytes=123)
    c2 = _insert_payload(conn, "/stash/media/torrents/seeding/collide-b", file_count=1, total_bytes=123)

    _insert_torrent_ref(conn, actionable, "complete-hash")
    _insert_torrent_ref(conn, noncomplete, "pending-hash")
    _insert_torrent_ref(conn, c1, "complete-hash-c1")
    _insert_torrent_ref(conn, c2, "complete-hash-c2")
    conn.commit()

    ctx = module._collect_status_context(
        conn,
        ["/stash/media"],
        completed_hashes={"complete-hash", "complete-hash-c1", "complete-hash-c2"},
        completion_filter_active=True,
    )
    conn.close()

    assert ctx["totals"]["dirty_actionable"] == 1
    assert ctx["totals"]["dirty_noncomplete"] == 1
    assert ctx["totals"]["dirty_orphan"] == 1
    assert ctx["totals"]["total_needs_upgrade"] == 2
    assert ctx["collision_groups_in_scope"] == 1
    assert ctx["missing_sha256_collision_in_scope"] == 2


def test_catalog_scan_block_marks_done_when_only_noncomplete_and_orphan_remain(tmp_path):
    module = _load_module()
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    noncomplete = _insert_payload(conn, "/stash/media/torrents/seeding/noncomplete", file_count=0)
    _insert_torrent_ref(conn, noncomplete, "pending-hash")
    _insert_payload(conn, "/stash/media/torrents/seeding/orphan", file_count=0)
    conn.commit()

    ctx = module._collect_status_context(
        conn,
        ["/stash/media"],
        completed_hashes=set(),
        completion_filter_active=True,
    )

    out = StringIO()
    with redirect_stdout(out):
        module._catalog_scan_status(conn, ["/stash/media"], ctx)
    conn.close()

    text = out.getvalue()
    assert "[x] | catalog scan | actionable_dirty=0" in text
    assert "ignored_noncomplete=1" in text
    assert "orphan_dirty=1" in text
