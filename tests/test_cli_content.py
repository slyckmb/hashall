import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner
from hashall.bencode import bencode_dump
from hashall.rtorrent import (
    RTTorrentMeta,
    derive_rt_target_directory,
    normalize_rt_target_directory,
)

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
        CREATE TABLE files_pool_media (
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
    conn.execute(
        """
        INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, files_table)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("fs-pool-media", 53, "pool-media", "/pool", "/pool/media", "files_pool_media"),
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
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, fs_uuid, root_path, file_count, total_bytes, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            2,
            "duplicate-release-one",
            53,
            "fs-pool-media",
            "/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One",
            2,
            9,
            "complete",
        ),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, fs_uuid, save_path, root_name, category, tags, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        ("media111", 2, 53, "fs-pool-media", "/pool/media/torrents/seeding/cross-seed-link/FileList.io", "Release.One", "", "",),
    )
    conn.executemany(
        "INSERT INTO files_pool_media (path, size, quick_hash, sha256, status) VALUES (?, ?, ?, ?, 'active')",
        [
            ("torrents/seeding/cross-seed-link/FileList.io/Release.One/file1.mkv", 8, "qcs1m", "scs1"),
            ("torrents/seeding/cross-seed-link/FileList.io/Release.One/file2.srt", 1, "qcs2m", "scs2"),
        ],
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


def test_content_inventory_supports_filters_and_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "content",
            "inventory",
            "--db",
            str(db_path),
            "--root",
            "/pool/data/orphaned_data",
            "--kind",
            "orphan",
            "--path-contains",
            "movies",
            "--sort",
            "path",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "/pool/data/orphaned_data/movies/Movie.One.2024.mkv" in result.output
    assert "/pool/data/orphaned_data/movies/Movie.Two.2024.mkv" not in result.output
    assert "/pool/data/orphaned_data/A" not in result.output


def test_content_duplicates_supports_filters_and_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "content",
            "duplicates",
            "--db",
            str(db_path),
            "--root",
            "/pool/data/orphaned_data",
            "--path-contains",
            "orphaned_data",
            "--limit",
            "1",
        ],
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


def test_content_donors_json_includes_ranked_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["content", "donors", "--db", str(db_path), "--torrent", "abcd1234", "--root", "/pool/data/orphaned_data", "--json-output"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["ranked_candidates"]) >= 2
    assert payload["ranked_candidates"][0]["confidence"] == "strong"


def test_content_reclaim_report_ranks_keep_and_purge(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "content",
            "reclaim-report",
            "--db",
            str(db_path),
            "--root",
            "/pool/data/seeds",
            "--root",
            "/pool/media/torrents/seeding",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload) == 1
    group = payload[0]
    assert group["keep"]["root_path"] == "/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One"
    assert group["keep"]["reason"] == "live_qb_payload_root"
    assert group["purge"][0]["root_path"] == "/pool/data/seeds/cross-seed/tracker-one/Release.One"
    assert group["reclaimable_bytes"] == 9


def test_content_reclaim_report_protects_live_rt_session_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_db(db_path)
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    bencode_dump(
        session_dir / "deadbeef.torrent.rtorrent",
        {b"directory": b"/pool/data/seeds/cross-seed/tracker-one/Release.One"},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "content",
            "reclaim-report",
            "--db",
            str(db_path),
            "--root",
            "/pool/data/seeds",
            "--root",
            "/pool/media/torrents/seeding",
            "--rt-session-dir",
            str(session_dir),
            "--include-fully-protected",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("["):])
    assert len(payload) == 1
    group = payload[0]
    assert group["keep"]["root_path"] == "/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One"
    assert group["keep"]["reason"] == "live_qb_payload_root"
    assert group["purge"] == []


def test_rt_session_audit_reports_missing_and_existing(tmp_path: Path) -> None:
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    bencode_dump(
        session_dir / "AAA111.torrent.rtorrent",
        {b"directory": str(existing).encode("utf-8")},
    )
    bencode_dump(
        session_dir / "BBB222.torrent.rtorrent",
        {b"directory": b"/missing/path"},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["rt", "session-audit", "--session-dir", str(session_dir), "--json-output"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["total_rows"] == 2
    assert payload["summary"]["missing_rows"] == 1
    assert payload["summary"]["existing_rows"] == 1
    rows = {row["torrent_hash"]: row for row in payload["rows"]}
    assert rows["aaa111"]["path_exists"] is True
    assert rows["bbb222"]["path_exists"] is False


def test_rt_repair_report_classifies_ready_and_aligned_rows(tmp_path: Path) -> None:
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    target_dir = tmp_path / "pool" / "media" / "release-one"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "movie.mkv"
    target_file.write_text("x", encoding="utf-8")
    aligned_dir = tmp_path / "pool" / "media" / "release-two"
    aligned_dir.mkdir(parents=True)
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "hash": "aaa111",
                        "name": "Release One",
                        "action_bucket": "fix_now_repoint_rt_to_pool_media",
                        "qb_save_path": str(target_dir),
                        "qb_content_path": str(target_file),
                        "rt_directory": "/old/path/release-one",
                    },
                    {
                        "hash": "bbb222",
                        "name": "Release Two",
                        "action_bucket": "fix_now_repoint_rt_to_pool_media",
                        "qb_save_path": str(aligned_dir),
                        "qb_content_path": str(aligned_dir / "folder"),
                        "rt_directory": str(aligned_dir),
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bencode_dump(
        session_dir / "AAA111.torrent.rtorrent",
        {b"directory": b"/old/path/release-one"},
    )
    bencode_dump(
        session_dir / "BBB222.torrent.rtorrent",
        {b"directory": str(aligned_dir).encode("utf-8")},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "repair-report",
            "--report",
            str(report_path),
            "--session-dir",
            str(session_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["repair_status_counts"]["ready_repoint_missing_rt_root"] == 1
    assert payload["summary"]["repair_status_counts"]["aligned_now"] == 1
    rows = {row["hash"]: row for row in payload["rows"]}
    assert rows["aaa111"]["preferred_target"] == str(target_file)
    assert rows["aaa111"]["preferred_target_exists"] is True
    assert rows["aaa111"]["repair_status"] == "ready_repoint_missing_rt_root"
    assert rows["bbb222"]["repair_status"] == "aligned_now"


def test_rt_repair_report_unresolved_only_filters_aligned_rows(tmp_path: Path) -> None:
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    target_dir = tmp_path / "pool" / "media" / "release-one"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "movie.mkv"
    target_file.write_text("x", encoding="utf-8")
    aligned_dir = tmp_path / "pool" / "media" / "release-two"
    aligned_dir.mkdir(parents=True)
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "hash": "aaa111",
                        "name": "Release One",
                        "action_bucket": "wave1",
                        "qb_save_path": str(target_dir),
                        "qb_content_path": str(target_file),
                        "rt_directory": "/old/path/release-one",
                    },
                    {
                        "hash": "bbb222",
                        "name": "Release Two",
                        "action_bucket": "wave1",
                        "qb_save_path": str(aligned_dir),
                        "qb_content_path": str(aligned_dir / "folder"),
                        "rt_directory": str(aligned_dir),
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bencode_dump(
        session_dir / "AAA111.torrent.rtorrent",
        {b"directory": b"/old/path/release-one"},
    )
    bencode_dump(
        session_dir / "BBB222.torrent.rtorrent",
        {b"directory": str(aligned_dir).encode("utf-8")},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "repair-report",
            "--report",
            str(report_path),
            "--session-dir",
            str(session_dir),
            "--unresolved-only",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["rows"] == 1
    assert payload["summary"]["repair_status_counts"] == {"ready_repoint_missing_rt_root": 1}
    assert payload["rows"][0]["hash"] == "aaa111"


def test_rt_repair_report_markdown_output(tmp_path: Path) -> None:
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    target_dir = tmp_path / "pool" / "media" / "release-one"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "movie.mkv"
    target_file.write_text("x", encoding="utf-8")
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "hash": "aaa111",
                        "name": "Release One",
                        "action_bucket": "wave1",
                        "qb_save_path": str(target_dir),
                        "qb_content_path": str(target_file),
                        "rt_directory": "/old/path/release-one",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bencode_dump(
        session_dir / "AAA111.torrent.rtorrent",
        {b"directory": b"/old/path/release-one"},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "repair-report",
            "--report",
            str(report_path),
            "--session-dir",
            str(session_dir),
            "--markdown-output",
        ],
    )

    assert result.exit_code == 0
    assert "# RT Repair Report" in result.output
    assert "## wave1" in result.output
    assert "### 1. Release One" in result.output
    assert "- repair_status: `ready_repoint_missing_rt_root`" in result.output


def test_derive_rt_target_directory_for_single_file_wrapper() -> None:
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="movie.mkv", is_multi_file=False)
    target = derive_rt_target_directory(
        qb_save_path="/data/media/torrents/seeding/movies",
        qb_content_path="/data/media/torrents/seeding/movies/Movie.Release/movie.mkv",
        torrent_meta=meta,
    )
    assert target == "/data/media/torrents/seeding/movies/Movie.Release"


def test_derive_rt_target_directory_for_multi_file_existing_dir(tmp_path: Path) -> None:
    root_dir = tmp_path / "tv" / "Release.One"
    root_dir.mkdir(parents=True)
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Release.One", is_multi_file=True)
    target = derive_rt_target_directory(
        qb_save_path=str(tmp_path / "tv"),
        qb_content_path=str(root_dir),
        torrent_meta=meta,
    )
    assert target == str(root_dir)


def test_normalize_rt_target_directory_uses_parent_for_multi_file_content_root(tmp_path: Path) -> None:
    target_dir = tmp_path / "tv" / "Release.One"
    target_dir.mkdir(parents=True)
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Release.One", is_multi_file=True)
    normalized = normalize_rt_target_directory(str(target_dir), meta)
    assert normalized == str(target_dir.parent)


def test_rt_repair_apply_dry_run_uses_target_directory(tmp_path: Path) -> None:
    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    target_dir = tmp_path / "pool" / "media" / "Release.One"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "movie.mkv"
    target_file.write_text("x", encoding="utf-8")
    report_path = tmp_path / "repair-report.json"
    report_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "hash": "aaa111",
                        "name": "Release One",
                        "action_bucket": "wave1",
                        "qb_save_path": str(tmp_path / "pool" / "media"),
                        "qb_content_path": str(target_file),
                        "rt_directory": "/old/path/release-one",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    bencode_dump(
        session_dir / "AAA111.torrent.rtorrent",
        {b"directory": b"/old/path/release-one"},
    )
    bencode_dump(
        session_dir / "AAA111.torrent",
        {b"info": {b"name": b"movie.mkv", b"length": 1}},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "repair-apply",
            "--report",
            str(report_path),
            "--session-dir",
            str(session_dir),
        ],
    )

    assert result.exit_code == 0
    assert "candidates: 1" in result.output
    assert str(target_dir) in result.output
    assert "apply: False" in result.output


def test_rt_repoint_dry_run_shows_normalized_target_for_multi_file(tmp_path: Path, monkeypatch) -> None:
    from hashall import rtorrent as rtorrent_mod

    session_dir = tmp_path / "rt-session"
    session_dir.mkdir()
    content_root = tmp_path / "tv" / "Release.One"
    content_root.mkdir(parents=True)
    monkeypatch.setattr(rtorrent_mod, "DEFAULT_RT_SESSION_DIR", session_dir)
    bencode_dump(
        session_dir / "AAA111.torrent",
        {b"info": {b"name": b"Release.One", b"files": [{b"path": [b"episode1.mkv"], b"length": 1}]}},
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "repoint",
            "--hash",
            "aaa111",
            "--target-directory",
            str(content_root),
        ],
    )

    assert result.exit_code == 0
    assert f"normalized_target_directory: {content_root.parent}" in result.output


def test_rt_state_audit_bad_only(monkeypatch) -> None:
    from hashall import rtorrent as rtorrent_mod

    def fake_fetch(rpc_url: str):
        return [
            {"hash": "aaa111", "name": "Healthy", "directory": "/ok", "state": "stalledUP", "message": ""},
            {"hash": "bbb222", "name": "Broken", "directory": "/bad", "state": "stoppedDL", "message": ""},
        ]

    monkeypatch.setattr(rtorrent_mod, "fetch_rt_status_rows", fake_fetch)
    runner = CliRunner()
    result = runner.invoke(cli, ["rt", "state-audit", "--bad-only", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["rows"] == 1
    assert payload["summary"]["state_counts"] == {"stoppedDL": 1}
    assert payload["rows"][0]["hash"] == "bbb222"


def test_rt_recheck_dry_run_lists_hashes() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rt", "recheck", "--hash", "aaa111", "--hash", "bbb222"])

    assert result.exit_code == 0
    assert "hashes: 2" in result.output
    assert "hash: aaa111" in result.output
    assert "hash: bbb222" in result.output
    assert "apply: False" in result.output
