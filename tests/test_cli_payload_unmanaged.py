"""Tests for `hashall payload unmanaged` CLI command."""

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.model import connect_db


def test_payload_unmanaged_splits_true_orphans_and_alias_artifacts(tmp_path):
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

    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/data/media/torrents/seeding/cross-seed/alias-item", 0, 0, "incomplete"),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/stash/media/torrents/seeding/ghost-item", 0, 0, "incomplete"),
    )

    cur = conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/stash/media/torrents/seeding/has-ref", 0, 0, "incomplete"),
    )
    ref_payload_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("has-ref-hash", ref_payload_id, 49, "/stash/media/torrents/seeding", "has-ref", "", "", 1.0),
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "unmanaged",
            "--db",
            str(db_path),
            "--path-prefix",
            "/data/media",
            "--path-prefix",
            "/stash/media",
            "--samples",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "unmanaged payloads: 2" in result.output
    assert "true orphans (no refs + no active files): 1" in result.output
    assert "alias artifacts (no refs + active files): 1" in result.output
    assert "/stash/media/torrents/seeding/ghost-item" in result.output
    assert "/data/media/torrents/seeding/cross-seed/alias-item" in result.output


def test_payload_unmanaged_respects_path_prefix_filter(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, None, "/stash/media/torrents/seeding/ghost-item", 0, 0, "incomplete"),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, None, "/pool/data/torrents/seeding/other-item", 0, 0, "incomplete"),
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "unmanaged",
            "--db",
            str(db_path),
            "--path-prefix",
            "/stash/media",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "unmanaged payloads: 1" in result.output
    assert "skipped (path-prefix): 1" in result.output
    assert "true orphans (no refs + no active files): 1" in result.output


def test_payload_unmanaged_counts_mount_root_payload_as_alias_artifact(tmp_path):
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
        ("torrents/seeding/root-file.mkv", 123, "abc", "active"),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/data/media", 0, 0, "incomplete"),
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "unmanaged",
            "--db",
            str(db_path),
            "--path-prefix",
            "/data/media",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "unmanaged payloads: 1" in result.output
    assert "true orphans (no refs + no active files): 0" in result.output
    assert "alias artifacts (no refs + active files): 1" in result.output
