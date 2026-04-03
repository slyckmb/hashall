import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            device_alias TEXT
        );

        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete'
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT
        );

        CREATE TABLE rehome_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            payload_hash TEXT,
            status TEXT,
            source_path TEXT,
            target_path TEXT
        );
        """
    )


def test_relocate_plan_accepts_device_aliases(tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    source_root = tmp_path / "pool" / "data" / "media" / "torrents" / "seeding"
    target_root = tmp_path / "pool" / "media" / "torrents" / "seeding"

    source_path = source_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    target_path = target_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"source-bytes")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (231, 'pool-data')")
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (141, 'pool-media')")
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash01', 231, ?, 1, ?, 'complete')
        """,
        (str(source_path), len(b"source-bytes")),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category)
        VALUES ('thash1', 1, 231, ?, ?, 'cross-seed')
        """,
        (str(source_root / "cross-seed" / "Aither (API)"), source_path.name),
    )
    conn.commit()
    conn.close()

    out_path = tmp_path / "relocate-plan.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "relocate-plan",
            "--catalog",
            str(db_path),
            "--source-device",
            "pool-data",
            "--source-root",
            str(source_root),
            "--target-device",
            "pool-media",
            "--target-root",
            str(target_root),
            "--all-mismatches",
            "--payload-hash", "hash01",
            "-o",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["candidates"] == 1
    assert data["plans"][0]["decision"] == "MOVE"
    assert data["plans"][0]["source_path"] == str(source_path)
    assert data["plans"][0]["target_path"] == str(target_path)


def test_relocate_plan_seeds_from_live_qbit_old_root(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    source_root = tmp_path / "pool" / "data" / "media" / "torrents" / "seeding"
    target_root = tmp_path / "pool" / "media" / "torrents" / "seeding"

    live_source_path = source_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    stale_source_path = source_root / "cross-seed" / "Aither (API)" / "Stale.2024.mkv"
    live_source_path.parent.mkdir(parents=True, exist_ok=True)
    live_source_path.write_bytes(b"source-bytes")
    stale_source_path.write_bytes(b"stale-bytes")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (231, 'pool-data')")
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (141, 'pool-media')")
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES
          (1, 'hash-live', 231, ?, 1, ?, 'complete'),
          (2, 'hash-stale', 231, ?, 1, ?, 'complete')
        """,
        (str(live_source_path), len(b"source-bytes"), str(stale_source_path), len(b"stale-bytes")),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category)
        VALUES
          ('livehash', 1, 231, ?, ?, 'cross-seed'),
          ('stalehash', 2, 231, ?, ?, 'cross-seed')
        """,
        (
            str(source_root / "cross-seed" / "Aither (API)"),
            live_source_path.name,
            str(source_root / "cross-seed" / "Aither (API)"),
            stale_source_path.name,
        ),
    )
    conn.commit()
    conn.close()

    class FakeQbit:
        def test_connection(self):
            return True

        def login(self):
            return True

        def get_torrents(self):
            return [
                SimpleNamespace(
                    hash="livehash",
                    save_path=str(source_root / "cross-seed" / "Aither (API)"),
                )
            ]

    monkeypatch.setattr("rehome.cli.get_qbittorrent_client", lambda: FakeQbit())

    out_path = tmp_path / "relocate-plan-live-qb.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "relocate-plan",
            "--catalog",
            str(db_path),
            "--source-device",
            "pool-data",
            "--source-root",
            str(source_root),
            "--target-device",
            "pool-media",
            "--target-root",
            str(target_root),
            "--all-mismatches",
            "-o",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["seed_scope"]["mode"] == "live_qb_root"
    assert data["seed_scope"]["qbit_hashes"] == 1
    assert data["seed_scope"]["mapped_payload_hashes"] == 1
    assert data["summary"]["candidates"] == 1
    assert data["plans"][0]["payload_hash"] == "hash-live"
    assert data["plans"][0]["affected_torrents"] == ["livehash"]


def test_relocate_plan_limits_affected_torrents_to_live_old_root_hashes(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    source_root = tmp_path / "pool" / "data" / "media" / "torrents" / "seeding"
    target_root = tmp_path / "pool" / "media" / "torrents" / "seeding"

    source_path = source_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    target_path = target_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"source-bytes")
    target_path.write_bytes(b"source-bytes")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (231, 'pool-data')")
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (141, 'pool-media')")
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES
          (1, 'hash-live', 231, ?, 1, ?, 'complete'),
          (2, 'hash-live', 141, ?, 1, ?, 'complete')
        """,
        (str(source_path), len(b"source-bytes"), str(target_path), len(b"source-bytes")),
    )
    conn.executemany(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category)
        VALUES (?, ?, ?, ?, ?, 'cross-seed')
        """,
        [
            ("livehash", 1, 231, str(source_root / "cross-seed" / "Aither (API)"), source_path.name),
            ("targethash", 2, 141, str(target_root / "cross-seed" / "Aither (API)"), target_path.name),
        ],
    )
    conn.commit()
    conn.close()

    class FakeQbit:
        def test_connection(self):
            return True

        def login(self):
            return True

        def get_torrents(self):
            return [
                SimpleNamespace(
                    hash="livehash",
                    save_path=str(source_root / "cross-seed" / "Aither (API)"),
                ),
                SimpleNamespace(
                    hash="targethash",
                    save_path=str(target_root / "cross-seed" / "Aither (API)"),
                ),
            ]

    monkeypatch.setattr("rehome.cli.get_qbittorrent_client", lambda: FakeQbit())

    out_path = tmp_path / "relocate-plan-live-qb-limited.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "relocate-plan",
            "--catalog",
            str(db_path),
            "--source-device",
            "pool-data",
            "--source-root",
            str(source_root),
            "--target-device",
            "pool-media",
            "--target-root",
            str(target_root),
            "--all-mismatches",
            "-o",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["candidates"] == 1
    assert data["plans"][0]["affected_torrents"] == ["livehash"]
    assert [row["torrent_hash"] for row in data["plans"][0]["view_targets"]] == ["livehash"]


def test_relocate_plan_defaults_to_nested_source_roots(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    source_root = tmp_path / "pool" / "data" / "media" / "torrents" / "seeding"
    target_root = tmp_path / "pool" / "media" / "torrents" / "seeding"

    source_path = source_root / "cross-seed" / "Aither (API)" / "Movie.2024.mkv"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"source-bytes")

    conn = sqlite3.connect(db_path)
    _init_schema(conn)
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (231, 'pool-data')")
    conn.execute("INSERT INTO devices (device_id, device_alias) VALUES (141, 'pool-media')")
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash-nested', 231, ?, 1, ?, 'complete')
        """,
        (str(source_path), len(b"source-bytes")),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category)
        VALUES ('livehash', 1, 231, ?, ?, 'cross-seed')
        """,
        (str(source_root / "cross-seed" / "Aither (API)"), source_path.name),
    )
    conn.commit()
    conn.close()

    class FakeQbit:
        def test_connection(self):
            return True

        def login(self):
            return True

        def get_torrents(self):
            return [
                SimpleNamespace(
                    hash="livehash",
                    save_path=str(source_root / "cross-seed" / "Aither (API)"),
                )
            ]

    monkeypatch.setattr("rehome.cli.get_qbittorrent_client", lambda: FakeQbit())

    out_path = tmp_path / "relocate-plan-defaults-nested.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "relocate-plan",
            "--catalog",
            str(db_path),
            "--source-device",
            "pool-data",
            "--source-root",
            str(source_root),
            "--target-device",
            "pool-media",
            "--target-root",
            str(target_root),
            "-o",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["summary"]["candidates"] == 1
    assert data["plans"][0]["payload_hash"] == "hash-nested"
    assert data["plans"][0]["source_path"] == str(source_path)
