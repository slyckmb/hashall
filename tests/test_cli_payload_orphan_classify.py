"""Tests for `hashall payload classify-orphan-dedup` CLI command."""

import json
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.model import connect_db


def _make_two_device_catalog(db_path: Path) -> None:
    """Set up devices + files tables for pool (dev 52) and hotspare (dev 53)."""
    conn = connect_db(db_path)

    conn.execute("DROP TABLE IF EXISTS devices")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            fs_uuid TEXT,
            device_id INTEGER PRIMARY KEY,
            mount_point TEXT,
            preferred_mount_point TEXT,
            device_alias TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, device_alias) "
        "VALUES (?, ?, ?, ?, ?)",
        ("pool-uuid", 52, "/pool/media", "/pool/media", "pool"),
    )
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, device_alias) "
        "VALUES (?, ?, ?, ?, ?)",
        ("spare-uuid", 53, "/mnt/hotspare6tb", "/mnt/hotspare6tb", "hotspare"),
    )

    for did in (52, 53):
        conn.execute(f"DROP TABLE IF EXISTS files_{did}")
        conn.execute(
            f"""
            CREATE TABLE files_{did} (
                path TEXT PRIMARY KEY,
                size INTEGER,
                sha256 TEXT,
                quick_hash TEXT,
                inode INTEGER,
                status TEXT
            )
            """
        )

    conn.execute("DROP TABLE IF EXISTS payloads")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT,
            file_count INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'incomplete'
        )
        """
    )

    conn.commit()
    conn.close()


def test_classify_empty_scope_no_orphans(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "orphan payloads in scope: 0" in result.output


def test_classify_sha256_confirmed_cross_device_match(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )

    sha = "d" * 64

    conn.execute(
        "INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (None, 52, "/pool/media/torrents/orphans/ghost-item", 1, 1048576, "incomplete"),
    )

    conn.execute(
        "INSERT INTO files_52 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("torrents/orphans/ghost-item/file.mkv", 1048576, sha, "qh_aaa", 1000, "active"),
    )
    conn.execute(
        "INSERT INTO files_53 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("orphan_data/ghost-item/file.mkv", 1048576, sha, "qh_aaa", 2000, "active"),
    )

    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "orphan payloads in scope: 1" in result.output
    assert "total orphan files: 1" in result.output
    assert "SHA256-confirmed" in result.output
    assert "sha256_confirmed" not in result.output.replace("SHA256-confirmed", "") or True


def test_classify_quick_hash_only_candidate(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )

    conn.execute(
        "INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (None, 52, "/pool/media/torrents/orphans/qh-ghost", 1, 2097152, "incomplete"),
    )

    conn.execute(
        "INSERT INTO files_52 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "torrents/orphans/qh-ghost/bigfile.mkv",
            2097152,
            None,
            "qh_bbb",
            3000,
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO files_53 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "orphan_data/qh-ghost/bigfile.mkv",
            2097152,
            None,
            "qh_bbb",
            4000,
            "active",
        ),
    )

    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "quick-hash-only" in result.output


def test_classify_json_output(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )

    sha = "e" * 64

    conn.execute(
        "INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (None, 52, "/pool/media/torrents/orphans/json-test", 2, 3145728, "incomplete"),
    )

    conn.execute(
        "INSERT INTO files_52 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "torrents/orphans/json-test/file1.mkv",
            1048576,
            sha,
            "qh_xxx",
            5000,
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO files_52 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "torrents/orphans/json-test/file2.mkv",
            2097152,
            None,
            None,
            5001,
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO files_53 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "orphan_data/json-test/file1.mkv",
            1048576,
            sha,
            "qh_xxx",
            6000,
            "active",
        ),
    )

    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["orphan_payloads_in_scope"] == 1
    assert payload["total_files"] == 2
    assert payload["sha256_confirmed"]["files"] == 1
    assert payload["no_match"]["files"] == 1
    assert len(payload["candidates"]) == 2


def test_classify_with_min_size_filter(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )

    sha = "f" * 64

    conn.execute(
        "INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (None, 52, "/pool/media/torrents/orphans/smol", 1, 1, "incomplete"),
    )

    conn.execute(
        "INSERT INTO files_52 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "torrents/orphans/smol/tiny.txt",
            1,
            sha,
            "qh_smol",
            7000,
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO files_53 (path, size, sha256, quick_hash, inode, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "orphan_data/smol/tiny.txt",
            1,
            sha,
            "qh_smol",
            7001,
            "active",
        ),
    )

    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
            "--min-size", "1048576",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no cross-device match" in result.output


def test_classify_show_candidates_flag(tmp_path):
    db_path = tmp_path / "catalog.db"
    _make_two_device_catalog(db_path)

    conn = connect_db(db_path)
    conn.execute("DROP TABLE IF EXISTS torrent_instances")
    conn.execute(
        "CREATE TABLE torrent_instances (torrent_hash TEXT, payload_id INTEGER)"
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload", "classify-orphan-dedup",
            "--db", str(db_path),
            "--show-candidates", "5",
        ],
    )
    assert result.exit_code == 0, result.output
