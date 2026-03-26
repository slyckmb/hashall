import sqlite3
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli


def _init_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE devices (
            fs_uuid TEXT PRIMARY KEY,
            device_id INTEGER NOT NULL,
            device_alias TEXT,
            mount_point TEXT NOT NULL,
            preferred_mount_point TEXT,
            files_table TEXT
        );
        CREATE TABLE files_pool_data (
            path TEXT PRIMARY KEY,
            size INTEGER,
            quick_hash TEXT,
            sha256 TEXT,
            status TEXT
        );
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            payload_hash TEXT,
            device_id INTEGER,
            fs_uuid TEXT,
            root_path TEXT,
            file_count INTEGER,
            total_bytes INTEGER,
            status TEXT
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER,
            device_id INTEGER,
            fs_uuid TEXT,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, files_table)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("fs-pool-data", 44, "pool-data", "/pool", "/pool/data", "files_pool_data"),
    )
    conn.executemany(
        "INSERT INTO files_pool_data (path, size, quick_hash, sha256, status) VALUES (?, ?, ?, ?, 'active')",
        [
            ("orphaned_data/A/file1.mkv", 10, "q1", "s1"),
            ("orphaned_data/A/file2.srt", 1, "q2", "s2"),
            ("orphaned_data/B/file1.mkv", 10, "q1b", "s1"),
            ("orphaned_data/B/file2.srt", 1, "q2b", "s2"),
            ("orphaned_data/movies/Movie.One.2024.mkv", 12, "qm1", "sm1"),
            ("orphaned_data/movies/Movie.Two.2024.mkv", 13, "qm2", "sm2"),
            ("orphaned_data/books/B/Book One.epub", 2, "qb1", "sb1"),
            ("orphaned_data/books/B/Book Two.epub", 3, "qb2", "sb2"),
            ("seeds/C/track1.flac", 5, "q3", "s3"),
            ("seeds/C/track2.flac", 6, "q4", None),
            ("seeds/cross-seed/tracker-one/Release.One/file1.mkv", 8, "qcs1", "scs1"),
            ("seeds/cross-seed/tracker-one/Release.One/file2.srt", 1, "qcs2", "scs2"),
            ("RecycleBin/D.bin", 7, "q5", "s5"),
        ],
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, "6d0f52e9dcf0a3f7c771c35b74cb5a0b9f2f4b5b1be6f5f5c2e0f7eb7c2f7608", 44, "fs-pool-data",
         "/pool/data/media/torrents/seeding/example", 2, 11, "complete"),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, fs_uuid, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        ("abcd1234", 1, 44, "fs-pool-data", "/pool/data/media/torrents/seeding", "example", "", "",),
    )
    conn.commit()
    conn.close()


def test_content_inventory_lists_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["content", "inventory", "--db", str(db_path), "--root", "/pool/data/orphaned_data", "--root", "/pool/data/seeds"],
    )

    assert result.exit_code == 0
    assert "Content inventory" in result.output
    assert "/pool/data/orphaned_data/A" in result.output
    assert "/pool/data/orphaned_data/B" in result.output
    assert "/pool/data/seeds/C" in result.output
    assert "/pool/data/orphaned_data/movies/Movie.One.2024.mkv" in result.output
    assert "/pool/data/orphaned_data/books/B/Book One.epub" in result.output
    assert "/pool/data/seeds/cross-seed/tracker-one/Release.One" in result.output
    assert "root=/pool/data/orphaned_data/movies\n" not in result.output


def test_content_duplicates_finds_exact_duplicate_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["content", "duplicates", "--db", str(db_path), "--root", "/pool/data/orphaned_data"],
    )

    assert result.exit_code == 0
    assert "groups: 1" in result.output
    assert "/pool/data/orphaned_data/A" in result.output
    assert "/pool/data/orphaned_data/B" in result.output


def test_content_donors_reports_exact_non_qb_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["content", "donors", "--db", str(db_path), "--torrent", "abcd1234", "--root", "/pool/data/orphaned_data"],
    )

    assert result.exit_code == 0
    assert "exact_non_qb_donors:" in result.output
    assert "/pool/data/orphaned_data/A" in result.output
    assert "/pool/data/orphaned_data/B" in result.output
