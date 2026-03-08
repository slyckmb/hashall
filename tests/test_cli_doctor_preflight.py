import sqlite3
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli


def _init_schema(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE devices (device_id INTEGER PRIMARY KEY, device_alias TEXT)")
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.commit()
    conn.close()


def test_doctor_preflight_strict_fails_on_unknown_device_refs(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 999)")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "preflight", "--db", str(db_path)])
    assert result.exit_code != 0
    assert "catalog preflight failed" in result.output


def test_doctor_preflight_no_strict_reports_without_failing(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 999)")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli, ["doctor", "preflight", "--db", str(db_path), "--no-strict"]
    )
    assert result.exit_code == 0
    assert "failed_error=" in result.output


def test_doctor_preflight_passes_on_consistent_catalog(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE devices (device_id INTEGER PRIMARY KEY, device_alias TEXT)")
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE files_49 (path TEXT)")
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (49, 'pool')")
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 49)")
    conn.execute("INSERT INTO torrent_instances (torrent_hash, device_id) VALUES ('abc', 49)")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "preflight", "--db", str(db_path)])
    assert result.exit_code == 0
    assert "preflight ok=True" in result.output


def test_doctor_preflight_passes_on_stable_files_table_binding(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog-stable.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            device_alias TEXT,
            fs_uuid TEXT,
            files_table TEXT
        )
        """
    )
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE files_fs_pool_media (path TEXT)")
    conn.execute(
        "INSERT INTO devices (device_id, device_alias, fs_uuid, files_table) VALUES (49, 'pool', 'zfs-pool-media', 'files_fs_pool_media')"
    )
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 49)")
    conn.execute("INSERT INTO torrent_instances (torrent_hash, device_id) VALUES ('abc', 49)")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "preflight", "--db", str(db_path)])
    assert result.exit_code == 0
    assert "preflight ok=True" in result.output


def test_doctor_preflight_strict_fails_on_volatile_fs_uuid(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog-volatile.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE devices (device_id INTEGER PRIMARY KEY, device_alias TEXT, fs_uuid TEXT)"
    )
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.execute("INSERT INTO devices (device_id, device_alias, fs_uuid) VALUES (49, 'pool', 'dev-49')")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "preflight", "--db", str(db_path)])
    assert result.exit_code != 0
    assert "device_fs_uuid_stable" in result.output
