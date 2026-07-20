import sqlite3
from pathlib import Path

import pytest

from hashall.client_drift import (
    ClientDriftPolicy,
    _AnchorScanResult,
    _Sha256ContentMatcher,
)


def _make_catalog(tmp_path: Path, tables: dict[str, list[dict]]) -> Path:
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(catalog))
    for table, rows in tables.items():
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table}" (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha256 TEXT,
                inode INTEGER NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        for row in rows:
            conn.execute(
                f'INSERT OR IGNORE INTO "{table}" (path, size, mtime, sha256, inode, status) VALUES (?,?,?,?,?,\'active\')',
                (row["path"], row["size"], row.get("mtime", 0.0), row.get("sha256"), row["inode"]),
            )
    conn.commit()
    conn.close()
    return catalog


def test_sha256_anchor_match_found_across_devices(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "torrents/seeding/site/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "torrents/seeding/site/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 2001},
            ],
            "files_fs_library": [
                {"path": "movies/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 3001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/library/movies", "/library/shows"))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["torrents/seeding/site/Release.One/file.bin"])

    assert result.has_arr_anchor is False
    assert result.source == "sha256_dupe"


def test_sha256_content_match_found(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "torrents/seeding/site/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "torrents/seeding/site/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 2001},
                {"path": "library/movies/Release.One/file.bin", "size": 1048576, "sha256": "abc123sha256def", "inode": 2002},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/stash/library",))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["torrents/seeding/site/Release.One/file.bin"])

    assert result.has_arr_anchor is False
    assert result.source == "sha256_dupe"


def test_sha256_anchor_match_with_library_root(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "/pool/media/torrents/seeding/site/Film/file.bin", "size": 2097152, "sha256": "hash_match_12345", "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "/stash/media/movies/Film/file.bin", "size": 2097152, "sha256": "hash_match_12345", "inode": 2001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/data/media", "/stash/media"))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["/pool/media/torrents/seeding/site/Film/file.bin"])

    assert result.has_arr_anchor is True
    assert result.source == "sha256_dupe"
    assert len(result.anchor_paths) >= 1
    assert any("/stash/media" in p for p in result.anchor_paths)


def test_sha256_no_match(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "torrents/seeding/site/NoMatch/file.bin", "size": 500, "sha256": "unique_hash_no_match", "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "media/movies/Other/file.bin", "size": 999, "sha256": "other_hash", "inode": 2001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/data/media", "/stash/media"))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["torrents/seeding/site/NoMatch/file.bin"])

    assert result.has_arr_anchor is False
    assert result.source == "sha256_dupe"
    assert result.payload_files_checked == 1


def test_sha256_null_for_payload(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "torrents/seeding/site/NoHash/file.bin", "size": 100, "sha256": None, "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "media/movies/NoHash/file.bin", "size": 100, "sha256": "some_hash", "inode": 2001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/stash/media",))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["torrents/seeding/site/NoHash/file.bin"])

    assert result.has_arr_anchor is False
    assert "sha256_matcher_no_sha256_for_payloads" in result.blockers


def test_sha256_no_catalog_configured() -> None:
    policy = ClientDriftPolicy(arr_library_roots=("/library",))
    matcher = _Sha256ContentMatcher(policy, catalog_path=None)
    result = matcher.find_sha256_anchors(["some/path"])

    assert result.has_arr_anchor is None
    assert "sha256_matcher_catalog_not_configured" in result.blockers


def test_sha256_catalog_not_found(tmp_path: Path) -> None:
    policy = ClientDriftPolicy(arr_library_roots=("/library",))
    catalog = tmp_path / "nonexistent.db"
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["some/path"])

    assert result.has_arr_anchor is None
    assert "sha256_matcher_catalog_not_found" in result.blockers


def test_sha256_no_library_roots(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_dev": [
                {"path": "file.bin", "size": 100, "sha256": "hash1", "inode": 1},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=())
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["file.bin"])

    assert result.has_arr_anchor is None
    assert "arr_library_roots_not_configured" in result.blockers


def test_sha256_match_different_size_not_matched(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "torrents/seeding/site/Film/file.bin", "size": 1000, "sha256": "shared_hash_val", "inode": 1001},
            ],
            "files_fs_stash": [
                {"path": "media/movies/Film/file.bin", "size": 2000, "sha256": "shared_hash_val", "inode": 2001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/stash/media",))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors(["torrents/seeding/site/Film/file.bin"])

    assert result.has_arr_anchor is False


def test_sha256_match_multiple_payloads_one_anchored(tmp_path: Path) -> None:
    catalog = _make_catalog(
        tmp_path,
        {
            "files_fs_pool": [
                {"path": "/pool/media/torrents/seeding/site/Film/file1.bin", "size": 5000, "sha256": "shared666", "inode": 1001},
                {"path": "/pool/media/torrents/seeding/site/Film/file2.bin", "size": 5000, "sha256": "shared666", "inode": 1002},
            ],
            "files_fs_stash": [
                {"path": "/stash/media/movies/Film/file1.bin", "size": 5000, "sha256": "shared666", "inode": 2001},
            ],
        },
    )

    policy = ClientDriftPolicy(arr_library_roots=("/stash/media", "/stash/library"))
    matcher = _Sha256ContentMatcher(policy, catalog_path=catalog)
    result = matcher.find_sha256_anchors([
        "/pool/media/torrents/seeding/site/Film/file1.bin",
        "/pool/media/torrents/seeding/site/Film/file2.bin",
    ])

    assert result.has_arr_anchor is True
    assert result.source == "sha256_dupe"
    assert result.payload_files_checked == 2
    assert any("/stash/media" in p for p in result.anchor_paths)
