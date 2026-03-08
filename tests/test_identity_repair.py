"""Tests for fs_uuid identity repair logic."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hashall.identity_repair import run_identity_repair


def _create_identity_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "identity.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            fs_uuid TEXT,
            mount_point TEXT,
            preferred_mount_point TEXT
        );

        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            payload_hash TEXT,
            device_id INTEGER,
            fs_uuid TEXT,
            root_path TEXT,
            file_count INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'incomplete',
            updated_at TEXT
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER,
            device_id INTEGER,
            fs_uuid TEXT,
            save_path TEXT,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_repairs_payload_from_current_device_id(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (1, 'hash-a', 50, NULL, '/stash/media/torrents/seeding/A');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=False)

    assert result.actions_planned == 1
    assert result.reason_counts.get("payload_current_device_id") == 1
    action = result.actions[0]
    assert action.table == "payloads"
    assert action.key == "1"
    assert action.target_device_id == 50
    assert action.target_fs_uuid == "fs-stash"


def test_repairs_torrent_from_linked_payload_fs_uuid(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (10, 'hash-a', 50, 'fs-stash', '/stash/media/torrents/seeding/A');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, fs_uuid, save_path)
        VALUES ('abc123', 10, NULL, NULL, '/stash/media/torrents/seeding');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=False)

    assert result.actions_planned == 1
    assert result.reason_counts.get("torrent_linked_payload_fs_uuid") == 1
    action = result.actions[0]
    assert action.table == "torrent_instances"
    assert action.key == "abc123"
    assert action.target_device_id == 50
    assert action.target_fs_uuid == "fs-stash"


def test_bind_alias_inference_can_be_disabled(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (1, 'hash-a', NULL, NULL, '/data/media/torrents/seeding/A');
        """
    )
    conn.commit()
    conn.close()

    result_enabled = run_identity_repair(db_path, apply_mode=False, allow_bind_aliases=True)
    assert result_enabled.actions_planned == 1
    assert result_enabled.reason_counts.get("path_alias_data_to_stash") == 1

    result_disabled = run_identity_repair(db_path, apply_mode=False, allow_bind_aliases=False)
    assert result_disabled.actions_planned == 0
    assert result_disabled.unresolved_count == 1


def test_no_unsafe_pool_media_to_pool_data_alias(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (49, 'fs-pool-data', '/pool/data', '/pool/data');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (1, 'hash-a', NULL, NULL, '/pool/media/torrents/seeding/A');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=False, allow_bind_aliases=True)
    assert result.actions_planned == 0
    assert result.unresolved_count == 1


def test_apply_updates_payload_and_torrent_rows(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (1, 'hash-a', 50, NULL, '/stash/media/torrents/seeding/A');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, fs_uuid, save_path)
        VALUES ('abc123', 1, NULL, NULL, '/stash/media/torrents/seeding');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=True)
    assert result.actions_applied == 2

    conn = sqlite3.connect(db_path)
    payload_row = conn.execute(
        "SELECT device_id, fs_uuid FROM payloads WHERE payload_id = 1"
    ).fetchone()
    torrent_row = conn.execute(
        "SELECT device_id, fs_uuid FROM torrent_instances WHERE torrent_hash = 'abc123'"
    ).fetchone()
    conn.close()

    assert payload_row == (50, "fs-stash")
    assert torrent_row == (50, "fs-stash")


def test_torrent_uses_pending_payload_repair_in_same_run(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES (1, 'hash-a', NULL, NULL, '/stash/media/torrents/seeding/A');

        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, fs_uuid, save_path)
        VALUES ('abc123', 1, NULL, NULL, '/unknown/path');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=False)
    assert result.actions_planned == 2
    assert result.reason_counts.get("path_prefix") == 1
    assert result.reason_counts.get("torrent_linked_payload_pending_repair") == 1


def test_max_actions_limit_is_enforced(tmp_path):
    db_path = _create_identity_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO devices (device_id, fs_uuid, mount_point, preferred_mount_point)
        VALUES (50, 'fs-stash', '/stash/media', '/stash/media');

        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path)
        VALUES
          (1, 'hash-a', 50, NULL, '/stash/media/torrents/seeding/A'),
          (2, 'hash-b', 50, NULL, '/stash/media/torrents/seeding/B');
        """
    )
    conn.commit()
    conn.close()

    result = run_identity_repair(db_path, apply_mode=True, max_actions=1)
    assert result.actions_planned == 1
    assert result.actions_applied == 1

    conn = sqlite3.connect(db_path)
    fixed = conn.execute("SELECT COUNT(*) FROM payloads WHERE fs_uuid = 'fs-stash'").fetchone()[0]
    conn.close()
    assert fixed == 1
