import sqlite3

from hashall.status_report import (
    RootContext,
    _collect_duplicate_pockets,
    _collect_payload_groups,
    _render_phone,
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
        "rehome": {
            "stash_to_pool_groups": 7,
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
    assert "summary:" in text
    assert "hot pockets:" in text
    assert "/stash/media/torrents" in text
    assert "next:" in text
    assert "make payload-auto" in text
