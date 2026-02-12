"""Tests for `hashall payload orphan-audit` CLI command."""

import time
import json
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.model import connect_db


def test_payload_orphan_audit_reports_true_vs_alias_and_gc(tmp_path):
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

    cur = conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/stash/media/torrents/seeding/ghost-item", 0, 0, "incomplete"),
    )
    true_payload_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, 49, "/data/media/torrents/seeding/cross-seed/alias-item", 0, 0, "incomplete"),
    )

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
    old = time.time() - (26 * 60 * 60)
    conn.execute(
        """
        INSERT INTO payload_orphan_gc (
            payload_id, first_seen_at, last_seen_at, seen_count, last_root_path, last_device_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (true_payload_id, old, old, 2, "/stash/media/torrents/seeding/ghost-item", 49),
    )

    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "orphan-audit",
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
    assert "scoped unmanaged payloads: 2" in result.output
    assert "true orphans (eligible class): 1" in result.output
    assert "alias artifacts (not eligible): 1" in result.output
    assert "gc tracked true orphans: 1" in result.output
    assert "gc aged true orphans: 1" in result.output
    assert "/stash/media/torrents/seeding/ghost-item" in result.output
    assert "/data/media/torrents/seeding/cross-seed/alias-item" in result.output


def test_payload_orphan_audit_handles_missing_gc_table(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, None, "/stash/media/torrents/seeding/ghost-item", 0, 0, "incomplete"),
    )
    conn.execute("DROP TABLE IF EXISTS payload_orphan_gc")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "orphan-audit",
            "--db",
            str(db_path),
            "--path-prefix",
            "/stash/media",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "true orphans (eligible class): 1" in result.output
    assert "gc staging table: missing" in result.output



def test_payload_orphan_audit_json_output(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)
    conn.execute(
        """
        INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (None, None, "/stash/media/torrents/seeding/ghost-item", 0, 0, "incomplete"),
    )
    conn.execute("DROP TABLE IF EXISTS payload_orphan_gc")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "orphan-audit",
            "--db",
            str(db_path),
            "--path-prefix",
            "/stash/media",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["scoped_unmanaged_payloads"] == 1
    assert payload["true_orphans"] == 1
    assert payload["alias_artifacts"] == 0
    assert payload["gc_table_exists"] is False
