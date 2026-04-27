import json
import sqlite3
import time
from pathlib import Path

import pytest
import requests
from click.testing import CliRunner
from hashall.bencode import bencode_dump
from hashall.rtorrent import (
    RTTorrentMeta,
    derive_rt_target_directory,
    map_rt_runtime_path,
    normalize_rt_target_directory,
    rt_build_load_cmd,
    rt_reset_torrent_session,
    rt_xmlrpc_call,
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


def test_normalize_rt_target_directory_keeps_multi_file_content_root(tmp_path: Path) -> None:
    target_dir = tmp_path / "tv" / "Release.One"
    target_dir.mkdir(parents=True)
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Release.One", is_multi_file=True)
    normalized = normalize_rt_target_directory(str(target_dir), meta)
    assert normalized == str(target_dir)


def test_normalize_rt_target_directory_uses_parent_for_multi_file_nested_file(tmp_path: Path) -> None:
    target_file = tmp_path / "movies" / "Release.One" / "movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("x", encoding="utf-8")
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Release.One", is_multi_file=True)
    normalized = normalize_rt_target_directory(str(target_file), meta)
    assert normalized == str(target_file.parent)


def test_normalize_rt_target_directory_uses_parent_for_single_file_path(tmp_path: Path) -> None:
    target_file = tmp_path / "movies" / "Movie.mkv"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("x", encoding="utf-8")
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Movie.mkv", is_multi_file=False)
    normalized = normalize_rt_target_directory(str(target_file), meta)
    assert normalized == str(target_file.parent)


def test_normalize_rt_target_directory_maps_stash_prefix_to_data(tmp_path: Path) -> None:
    stash_target = Path("/stash/media/torrents/seeding/books/Book.epub")
    data_target = Path("/data/media/torrents/seeding/books/Book.epub")
    data_target.parent.mkdir(parents=True, exist_ok=True)
    data_target.write_text("x", encoding="utf-8")
    meta = RTTorrentMeta(torrent_hash="aaa111", info_name="Book.epub", is_multi_file=False)
    normalized = normalize_rt_target_directory(str(stash_target), meta)
    assert normalized == str(data_target.parent)


def test_map_rt_runtime_path_translates_known_prefixes() -> None:
    assert map_rt_runtime_path("/stash/media/torrents/seeding/books/Book.epub") == "/data/media/torrents/seeding/books/Book.epub"
    assert map_rt_runtime_path("/dump/docker/gluetun_qbit/rtorrent_vpn/.session/ABC123.torrent") == "/config/.session/ABC123.torrent"


def test_rt_build_load_cmd_formats_assignment() -> None:
    assert rt_build_load_cmd("d.directory.set", "/data/media/torrents/seeding/books") == (
        'd.directory.set="/data/media/torrents/seeding/books"'
    )


def test_rt_build_load_cmd_quotes_spaces() -> None:
    assert rt_build_load_cmd("d.directory.set", "/data/media/torrents/seeding/OnlyEncodes (API)") == (
        'd.directory.set="/data/media/torrents/seeding/OnlyEncodes (API)"'
    )


def test_rt_xmlrpc_call_raises_on_fault(monkeypatch) -> None:
    class FakeResponse:
        text = (
            "<?xml version='1.0'?><methodResponse><fault><value><struct>"
            "<member><name>faultString</name><value><string>boom</string></value></member>"
            "</struct></value></fault></methodResponse>"
        )

        def raise_for_status(self) -> None:
            return None

    import hashall.rtorrent as rtorrent_mod

    monkeypatch.setattr(rtorrent_mod.requests, "post", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(RuntimeError, match="rt_xmlrpc_fault"):
        rt_xmlrpc_call("load.normal", "/config/.session/ABC123.torrent")


def test_rt_xmlrpc_call_base64_encodes_bytes(monkeypatch) -> None:
    class FakeResponse:
        text = "<?xml version='1.0'?><methodResponse><params><param><value><i8>0</i8></value></param></params></methodResponse>"

        def raise_for_status(self) -> None:
            return None

    captured = {}

    import hashall.rtorrent as rtorrent_mod

    def fake_post(url, data, headers, timeout):
        captured["data"] = data
        return FakeResponse()

    monkeypatch.setattr(rtorrent_mod.requests, "post", fake_post)
    rt_xmlrpc_call("load.raw_start", "", b"abc")
    assert "<base64>YWJj</base64>" in captured["data"]


def _write_rt_session_reset_fixture(session_dir: Path, torrent_hash: str = "AAA111") -> None:
    bencode_dump(
        session_dir / f"{torrent_hash}.torrent",
        {
            b"info": {
                b"name": b"Release.One",
                b"files": [{b"length": 1, b"path": [b"movie.mkv"]}],
            }
        },
    )
    bencode_dump(session_dir / f"{torrent_hash}.torrent.rtorrent", {b"directory": b"/old/root"})
    (session_dir / f"{torrent_hash}.torrent.libtorrent_resume").write_bytes(b"old-resume")


def test_rt_session_reset_verifies_after_load_timeout(tmp_path: Path, monkeypatch) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    backup_root = tmp_path / "backups"
    target = tmp_path / "media" / "Release.One"
    target.mkdir(parents=True)
    _write_rt_session_reset_fixture(session_dir)

    calls: list[str] = []
    loaded = {"ok": False}

    def fake_call(method, *args, **kwargs):
        calls.append(method)
        if method == "load.raw_start":
            loaded["ok"] = True
            raise requests.Timeout("read timeout")
        if method == "d.directory" and loaded["ok"]:
            return f"<methodResponse><params><param><value><string>{target}</string></value></param></params></methodResponse>"
        return "<methodResponse><params><param><value><i8>0</i8></value></param></params></methodResponse>"

    import hashall.rtorrent as rtorrent_mod

    monkeypatch.setattr(rtorrent_mod, "rt_xmlrpc_call", fake_call)
    result = rt_reset_torrent_session(
        "aaa111",
        target_directory=str(target),
        session_dir=session_dir,
        backup_root=backup_root,
        rpc_timeout=1,
        verify_timeout_s=0.1,
        poll_s=0.01,
    )

    assert result["status"] == "verified_after_timeout"
    assert "load.raw_start:verified_after_timeout" in result["completed"]
    assert result["recovery_completed"] == []
    assert calls.count("d.directory") >= 1


def test_rt_session_reset_restores_after_unverified_load_timeout(tmp_path: Path, monkeypatch) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    backup_root = tmp_path / "backups"
    target = tmp_path / "media" / "Release.One"
    target.mkdir(parents=True)
    _write_rt_session_reset_fixture(session_dir)
    rtorrent_file = session_dir / "AAA111.torrent.rtorrent"
    original_rtorrent = rtorrent_file.read_bytes()

    def fake_call(method, *args, **kwargs):
        if method == "load.raw_start":
            raise requests.Timeout("read timeout")
        if method == "d.directory":
            return "<methodResponse><params><param><value><string>/wrong/root</string></value></param></params></methodResponse>"
        return "<methodResponse><params><param><value><i8>0</i8></value></param></params></methodResponse>"

    import hashall.rtorrent as rtorrent_mod

    monkeypatch.setattr(rtorrent_mod, "rt_xmlrpc_call", fake_call)
    result = rt_reset_torrent_session(
        "aaa111",
        target_directory=str(target),
        session_dir=session_dir,
        backup_root=backup_root,
        rpc_timeout=1,
        verify_timeout_s=0.02,
        poll_s=0.01,
    )

    assert result["status"] == "blocked_restored"
    assert "load.raw_start:timeout" in result["completed"]
    assert "torrent_not_reloaded" in result["error"]
    assert rtorrent_file.read_bytes() == original_rtorrent


def test_rt_session_reset_restores_sidecars_when_load_fails(tmp_path: Path, monkeypatch) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    backup_root = tmp_path / "backups"
    target = tmp_path / "media" / "Release.One"
    target.mkdir(parents=True)
    _write_rt_session_reset_fixture(session_dir)
    rtorrent_file = session_dir / "AAA111.torrent.rtorrent"
    resume_file = session_dir / "AAA111.torrent.libtorrent_resume"
    original_rtorrent = rtorrent_file.read_bytes()
    original_resume = resume_file.read_bytes()

    def fake_call(method, *args, **kwargs):
        if method == "load.raw_start":
            raise RuntimeError("load failed")
        return "<methodResponse><params><param><value><i8>0</i8></value></param></params></methodResponse>"

    import hashall.rtorrent as rtorrent_mod

    monkeypatch.setattr(rtorrent_mod, "rt_xmlrpc_call", fake_call)
    result = rt_reset_torrent_session(
        "aaa111",
        target_directory=str(target),
        session_dir=session_dir,
        backup_root=backup_root,
        rpc_timeout=1,
        verify_timeout_s=0.1,
        poll_s=0.01,
    )

    assert result["status"] == "blocked_restored"
    assert result["error"] == "load failed"
    assert rtorrent_file.read_bytes() == original_rtorrent
    assert resume_file.read_bytes() == original_resume
    assert "session.rtorrent.restore" in result["recovery_completed"]
    assert "session.libtorrent_resume.restore" in result["recovery_completed"]


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
    assert str(target_dir.parent) in result.output
    assert "apply: False" in result.output


def test_rt_repoint_dry_run_keeps_multi_file_content_root(tmp_path: Path, monkeypatch) -> None:
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
    assert f"target_directory: {content_root}" in result.output
    assert "normalized_target_directory" not in result.output


def test_rt_state_audit_bad_only(monkeypatch) -> None:
    from hashall import rtorrent as rtorrent_mod

    def fake_fetch(rpc_url: str):
        return [
            {"hash": "aaa111", "name": "Healthy", "directory": "/ok", "state": "stalledUP", "message": ""},
            {"hash": "bbb222", "name": "Broken", "directory": "/bad", "state": "stoppedDL", "message": ""},
        ]

    monkeypatch.setattr(rtorrent_mod, "fetch_rt_status_rows", fake_fetch)
    runner = CliRunner()
    result = runner.invoke(cli, ["rt", "state-audit", "--live", "--bad-only", "--json-output"])

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["read_mode"] == "live"
    assert payload["summary"]["rows"] == 1
    assert payload["summary"]["state_counts"] == {"stoppedDL": 1}
    assert payload["rows"][0]["hash"] == "bbb222"


def test_rt_state_audit_uses_shared_cache_by_default(tmp_path: Path, monkeypatch) -> None:
    from hashall import rtorrent as rtorrent_mod

    cache_file = tmp_path / "torrents.json"
    meta_file = tmp_path / "torrents.meta.json"
    cache_file.write_text(
        json.dumps(
            [
                {"hash": "aaa111", "name": "Healthy", "save_path": "/ok", "state": "stalledUP", "dlspeed": "0", "upspeed": "0", "peers": 0},
                {"hash": "bbb222", "name": "Broken", "save_path": "/bad", "state": "stoppedDL", "dlspeed": "0", "upspeed": "0", "peers": 0},
            ]
        ),
        encoding="utf-8",
    )
    meta_file.write_text(
        json.dumps({"source": "daemon", "fetched_at": time.time(), "xmlrpc_url": "http://localhost:18000/RPC2"}),
        encoding="utf-8",
    )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("live RT fetch should not be used in cache mode")

    monkeypatch.setattr(rtorrent_mod, "fetch_rt_status_rows", fail_fetch)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "state-audit",
            "--cache-file",
            str(cache_file),
            "--meta-file",
            str(meta_file),
            "--bad-only",
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["read_mode"] == "shared_cache"
    assert payload["summary"]["freshness"] == "fresh"
    assert payload["summary"]["rows"] == 1
    assert payload["summary"]["state_counts"] == {"stoppedDL": 1}
    assert payload["rows"][0]["directory"] == "/bad"


def test_rt_state_audit_reports_stale_error_without_live_fallback(tmp_path: Path, monkeypatch) -> None:
    from hashall import rtorrent as rtorrent_mod

    cache_file = tmp_path / "torrents.json"
    meta_file = tmp_path / "torrents.meta.json"
    cache_file.write_text(
        json.dumps(
            [
                {"hash": "bbb222", "name": "Broken", "save_path": "/bad", "state": "stalledDL", "dlspeed": "0", "upspeed": "0", "peers": 0},
            ]
        ),
        encoding="utf-8",
    )
    meta_file.write_text(
        json.dumps(
            {
                "source": "daemon_error",
                "fetched_at": time.time() - 600,
                "xmlrpc_url": "http://localhost:18000/RPC2",
                "last_error": "rTorrent returned empty result",
                "consecutive_failures": 12,
            }
        ),
        encoding="utf-8",
    )

    def fail_fetch(*args, **kwargs):
        raise AssertionError("live RT fetch should not be used when cache is stale/degraded")

    monkeypatch.setattr(rtorrent_mod, "fetch_rt_status_rows", fail_fetch)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "state-audit",
            "--cache-file",
            str(cache_file),
            "--meta-file",
            str(meta_file),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["read_mode"] == "shared_cache"
    assert payload["summary"]["freshness"] == "stale_error"
    assert payload["summary"]["last_error"] == "rTorrent returned empty result"
    assert payload["summary"]["consecutive_failures"] == 12
    assert payload["summary"]["state_counts"] == {"stalledDL": 1}


def test_rt_recheck_dry_run_lists_hashes() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rt", "recheck", "--hash", "aaa111", "--hash", "bbb222"])

    assert result.exit_code == 0
    assert "hashes: 2" in result.output
    assert "hash: aaa111" in result.output
    assert "hash: bbb222" in result.output
    assert "apply: False" in result.output


def test_rt_session_reset_dry_run_lists_hashes() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "session-reset",
            "--hash",
            "aaa111",
            "--hash",
            "bbb222",
            "--target-directory",
            "/data/media/torrents/seeding/movies",
        ],
    )

    assert result.exit_code == 0
    assert "hashes: 2" in result.output
    assert "hash: aaa111" in result.output
    assert "hash: bbb222" in result.output
    assert "apply: False" in result.output


def test_rt_session_reset_batch_dry_run_reads_manifest(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    target = tmp_path / "media" / "Release.One"
    target.mkdir(parents=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"rows": [{"hash": "AAA111", "target_directory": str(target)}]}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "session-reset-batch",
            "--manifest",
            str(manifest),
            "--session-dir",
            str(session_dir),
        ],
    )

    assert result.exit_code == 0
    assert "manifest_rows: 1" in result.output
    assert "selected: 1" in result.output
    assert "hash: aaa111" in result.output
    assert "apply: False" in result.output


def test_rt_session_reset_batch_skips_journal_completed(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    target = tmp_path / "media" / "Release.One"
    target.mkdir(parents=True)
    manifest = tmp_path / "manifest.json"
    journal = tmp_path / "journal.jsonl"
    manifest.write_text(
        json.dumps({"rows": [{"hash": "aaa111", "target_directory": str(target)}]}),
        encoding="utf-8",
    )
    journal.write_text(json.dumps({"hash": "aaa111", "status": "verified"}) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "rt",
            "session-reset-batch",
            "--manifest",
            str(manifest),
            "--session-dir",
            str(session_dir),
            "--journal",
            str(journal),
        ],
    )

    assert result.exit_code == 0
    assert "journal_completed: 1" in result.output
    assert "skipped_completed: 1" in result.output
    assert "selected: 0" in result.output
