import sqlite3

from hashall.status_report import (
    RootContext,
    _cache_key,
    _collect_duplicate_pockets,
    _collect_payload_groups,
    _load_cached_report,
    _render_phone,
    _resolve_phone_width,
    _truncate_line,
    _write_cached_report,
)


def test_collect_duplicate_pockets_ranks_saveable_bytes():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE files_1 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            sha256 TEXT,
            status TEXT DEFAULT 'active'
        )
        """
    )
    conn.executemany(
        "INSERT INTO files_1 (path, size, inode, sha256, status) VALUES (?, ?, ?, ?, 'active')",
        [
            ("show/a.mkv", 100, 1, "sha-a"),
            ("show/b.mkv", 100, 2, "sha-a"),
            ("movies/base.mkv", 50, 3, "sha-b"),
            ("movies/sub/dup.mkv", 50, 4, "sha-b"),
        ],
    )
    conn.commit()

    ctx = RootContext(
        root_input="/pool/data",
        canonical_root="/pool/data",
        device_id=1,
        device_alias="pool",
        rel_root=".",
        root_kind="pool",
        fs_uuid="dev-1",
        scan_last_scanned_at=None,
    )
    pockets = _collect_duplicate_pockets(conn, ctx, pocket_depth=2, top_n=5)
    conn.close()

    assert pockets[0]["pocket"] == "/pool/data/show"
    assert pockets[0]["bytes_saveable"] == 100
    assert pockets[0]["actions"] == 1
    assert pockets[1]["pocket"] == "/pool/data/movies/sub"
    assert pockets[1]["bytes_saveable"] == 50


def test_collect_payload_groups_emits_rehome_signals():
    contexts = [
        RootContext(
            root_input="/pool/data",
            canonical_root="/pool/data",
            device_id=1,
            device_alias="pool",
            rel_root=".",
            root_kind="pool",
            fs_uuid="dev-1",
            scan_last_scanned_at=None,
        ),
        RootContext(
            root_input="/stash/media",
            canonical_root="/stash/media",
            device_id=2,
            device_alias="stash",
            rel_root=".",
            root_kind="stash",
            fs_uuid="dev-2",
            scan_last_scanned_at=None,
        ),
        RootContext(
            root_input="/data/media",
            canonical_root="/data/media",
            device_id=3,
            device_alias="media",
            rel_root=".",
            root_kind="media",
            fs_uuid="dev-3",
            scan_last_scanned_at=None,
        ),
    ]

    payload_rows = [
        {
            "payload_id": 1,
            "payload_hash": "h-stash",
            "status": "complete",
            "file_count": 10,
            "total_bytes": 1000,
            "root_path": "/stash/media/torrents/a",
            "device_id": 2,
        },
        {
            "payload_id": 2,
            "payload_hash": "h-stash",
            "status": "complete",
            "file_count": 10,
            "total_bytes": 1000,
            "root_path": "/stash/media/torrents/b",
            "device_id": 2,
        },
        {
            "payload_id": 3,
            "payload_hash": "h-pool-media",
            "status": "complete",
            "file_count": 5,
            "total_bytes": 500,
            "root_path": "/pool/data/torrents/c",
            "device_id": 1,
        },
        {
            "payload_id": 4,
            "payload_hash": "h-pool-media",
            "status": "complete",
            "file_count": 5,
            "total_bytes": 500,
            "root_path": "/data/media/library/c",
            "device_id": 3,
        },
    ]

    groups = _collect_payload_groups(
        contexts,
        payload_rows,
        media_root="/data/media",
        top_n=10,
    )

    assert groups["confirmed_groups"] == 2
    assert groups["rehome_opportunities"]["stash_to_pool_groups"] == 1
    assert groups["rehome_opportunities"]["pool_to_stash_groups"] == 1


def test_render_phone_includes_summary_pockets_and_actions():
    report = {
        "totals": {
            "active_files": 100,
            "bytes_saveable": 2048,
            "duplicate_sha256_groups": 3,
            "payload_complete": 10,
            "payload_incomplete": 2,
            "dirty_actionable": 1,
            "dirty_orphan": 9,
            "link_actions_nonzero": 4,
            "link_actions_zero_bytes": 5,
            "link_actions_possible": 9,
        },
        "db_health": {
            "quick_check": "ok",
        },
        "rehome": {
            "stash_to_pool_groups": 7,
            "stash_to_pool_estimated_bytes": 8192,
            "pool_to_stash_groups": 0,
        },
        "duplicate_pockets": [
            {"actions": 3, "bytes_saveable": 1024, "pocket": "/stash/media/torrents"},
        ],
        "actions": [
            {"priority": "P0", "command": "make payload-auto ROOTS='/pool/data,/stash/media'"},
        ],
    }

    text = _render_phone(report, width=78, top=3)
    assert "snapshot:" in text
    assert "do_now:" in text
    assert "converge payload state" in text
    assert "reclaim duplicate file bytes now" in text
    assert "review rehome queue" in text
    assert "make payload-auto" in text


def test_render_phone_truncates_lines_to_width():
    report = {
        "totals": {
            "active_files": 100,
            "bytes_saveable": 2048,
            "duplicate_sha256_groups": 3,
            "payload_complete": 10,
            "payload_incomplete": 2,
            "dirty_actionable": 1,
            "dirty_orphan": 9,
            "link_actions_nonzero": 4,
            "link_actions_zero_bytes": 5,
            "link_actions_possible": 9,
        },
        "db_health": {
            "quick_check": "ok",
        },
        "rehome": {
            "stash_to_pool_groups": 7,
            "stash_to_pool_estimated_bytes": 8192,
            "pool_to_stash_groups": 0,
        },
        "duplicate_pockets": [],
        "actions": [],
    }

    text = _render_phone(report, width=40, top=3)
    assert "..." in text
    for line in text.splitlines():
        assert len(line) <= 40


def test_truncate_line_keeps_short_lines():
    assert _truncate_line("abc", 5) == "abc"
    assert _truncate_line("abcdef", 3) == "..."
    assert _truncate_line("abcdef", 5) == "ab..."


def test_cache_roundtrip(tmp_path):
    db_path = tmp_path / "catalog.db"
    db_path.write_text("db", encoding="utf-8")
    key = _cache_key(
        db_path=db_path,
        roots_arg="/pool/data,/stash/media",
        media_root="/data/media",
        pocket_depth=2,
        top_n=10,
    )
    cache_path = tmp_path / "cache.json"
    report = {"roots": [], "totals": {"active_files": 0}}
    _write_cached_report(cache_path=cache_path, cache_key=key, report=report)

    loaded = _load_cached_report(cache_path=cache_path, expected_key=key, ttl_seconds=60)
    assert loaded == report


def test_resolve_phone_width_uses_requested_value():
    assert _resolve_phone_width(77) == 77
