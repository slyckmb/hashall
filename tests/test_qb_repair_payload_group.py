import json
import os
import sqlite3
from pathlib import Path

import pytest

from hashall.bencode import bencode_encode
from hashall.fastresume import read_fastresume
from hashall.qb_repair_payload_group import (
    CatalogLookup,
    build_repair_plan,
    can_reuse_good_save_path_directly,
    choose_repair_save_paths,
    ensure_same_payload_group,
    load_payload_pair,
    parse_args,
    patch_fastresume_with_journal,
    payload_identity_evidence_matches,
    qbtree_evidence_matches,
)


def _init_catalog(db_path: Path) -> None:
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
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT,
            file_count INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'complete'
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_ensure_same_payload_group_rejects_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_catalog(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path) VALUES (?, ?, ?, ?)",
        [
            (1, "payload-a", 1, "/pool/media/a"),
            (2, "payload-b", 1, "/pool/media/b"),
        ],
    )
    conn.executemany(
        "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, ?, ?, ?, ?)",
        [
            ("goodhash", 1, 1, "/pool/media/save-a", "A"),
            ("brokenhash", 2, 1, "/pool/media/save-b", "B"),
        ],
    )
    conn.commit()
    conn.close()

    catalog = CatalogLookup(db_path)
    try:
        with pytest.raises(RuntimeError, match="payload_group_mismatch"):
            ensure_same_payload_group(catalog, "goodhash", "brokenhash")
    finally:
        catalog.close()


def test_payload_identity_evidence_matches_allows_catalog_drift_when_shape_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_catalog(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "payload-a", 1, "/pool/media/a", 22, 71017483824),
            (2, "payload-b", 1, "/pool/media/b", 22, 71017483824),
        ],
    )
    conn.executemany(
        "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, ?, ?, ?, ?)",
        [
            ("goodhash", 1, 1, "/pool/media/save-a", "The.West.Wing.S02"),
            ("brokenhash", 2, 1, "/pool/media/save-b", "The.West.Wing.S02"),
        ],
    )
    conn.commit()
    conn.close()

    catalog = CatalogLookup(db_path)
    try:
        good, broken = load_payload_pair(catalog, "goodhash", "brokenhash")
        assert payload_identity_evidence_matches(good, broken) is True
    finally:
        catalog.close()


def test_qbtree_evidence_matches_when_root_names_differ() -> None:
    good_files = [
        {"name": "Show.Good/Disc1/track01.flac", "size": 10},
        {"name": "Show.Good/Disc2/track01.flac", "size": 11},
    ]
    broken_files = [
        {"name": "Show Bad/Disc1/track01.flac", "size": 10},
        {"name": "Show Bad/Disc2/track01.flac", "size": 11},
    ]

    assert qbtree_evidence_matches(good_files, broken_files) is True


def test_catalog_lookup_supports_pool_media(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    _init_catalog(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, files_table) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("fs-pool-media", 141, "pool-media", "/pool", "/pool/media", "files_pool_media"),
    )
    conn.execute(
        """
        CREATE TABLE files_pool_media (
            path TEXT PRIMARY KEY,
            quick_hash TEXT,
            status TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO files_pool_media (path, quick_hash, status) VALUES (?, ?, ?)",
        (
            "torrents/seeding/cross-seed/TorrentDay/Show/episode01.mkv",
            "qh-episode01",
            "active",
        ),
    )
    conn.commit()
    conn.close()

    catalog = CatalogLookup(db_path)
    try:
        value = catalog.quick_hash("/pool/media/torrents/seeding/cross-seed/TorrentDay/Show/episode01.mkv")
        assert value == "qh-episode01"
    finally:
        catalog.close()


def test_build_repair_plan_matches_multifile_paths_without_root_name(tmp_path: Path) -> None:
    good_save = tmp_path / "good"
    broken_save = tmp_path / "broken"
    paths = [
        (good_save / "Show.Good" / "Disc1" / "track01.flac", "good-disc1"),
        (good_save / "Show.Good" / "Disc2" / "track01.flac", "good-disc2"),
        (broken_save / "Show Bad" / "Disc1" / "track01.flac", "good-disc1"),
        (broken_save / "Show Bad" / "Disc2" / "track01.flac", "broken-disc2"),
    ]
    for path, _ in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    qhash_map = {
        str(good_save / "Show.Good" / "Disc1" / "track01.flac"): "good-disc1",
        str(good_save / "Show.Good" / "Disc2" / "track01.flac"): "good-disc2",
        str(broken_save / "Show Bad" / "Disc1" / "track01.flac"): "good-disc1",
        str(broken_save / "Show Bad" / "Disc2" / "track01.flac"): "broken-disc2",
    }

    plan = build_repair_plan(
        good_save=str(good_save),
        broken_save=str(broken_save),
        good_files=[
            {"name": "Show.Good/Disc1/track01.flac", "size": 10},
            {"name": "Show.Good/Disc2/track01.flac", "size": 11},
        ],
        broken_files=[
            {"name": "Show Bad/Disc1/track01.flac", "size": 10},
            {"name": "Show Bad/Disc2/track01.flac", "size": 11},
        ],
        quick_hash_lookup=qhash_map.get,
    )

    actions = {item.broken_rel: item.action for item in plan}
    assert actions["Show Bad/Disc1/track01.flac"] == "dup_copy"
    assert actions["Show Bad/Disc2/track01.flac"] == "garbage"


def test_build_repair_plan_matches_single_file_even_when_names_differ(tmp_path: Path) -> None:
    good_save = tmp_path / "good"
    broken_save = tmp_path / "broken"
    good_path = good_save / "Movie.2024.REMUX.mkv"
    broken_path = broken_save / "Movie 2024 REMUX.mkv"
    good_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    good_path.write_text("good", encoding="utf-8")
    broken_path.write_text("broken", encoding="utf-8")

    qhash_map = {
        str(good_path): "same-qh",
        str(broken_path): "same-qh",
    }

    plan = build_repair_plan(
        good_save=str(good_save),
        broken_save=str(broken_save),
        good_files=[{"name": "Movie.2024.REMUX.mkv", "size": 100}],
        broken_files=[{"name": "Movie 2024 REMUX.mkv", "size": 100}],
        quick_hash_lookup=qhash_map.get,
    )

    assert len(plan) == 1
    assert plan[0].action == "dup_copy"
    assert plan[0].good_rel == "Movie.2024.REMUX.mkv"


def test_patch_fastresume_with_journal_uses_shared_backup(tmp_path: Path) -> None:
    fastresume_path = tmp_path / "abc.fastresume"
    journal_path = tmp_path / "journal.jsonl"
    fastresume_path.write_bytes(
        bencode_encode(
            {
                b"save_path": b"/old/path",
                b"qBt-savePath": b"/old/path",
                b"qBt-downloadPath": b"/old/download",
            }
        )
    )

    entry = patch_fastresume_with_journal(
        fastresume_path=fastresume_path,
        target_save_path="/new/path/",
        backup_suffix=".bak",
        journal_path=journal_path,
    )

    assert entry["changed"] is True
    assert Path(entry["backup_path"]).exists()
    patched = read_fastresume(fastresume_path)
    assert patched[b"save_path"] == b"/new/path"
    assert patched[b"qBt-savePath"] == b"/new/path"
    assert patched[b"qBt-downloadPath"] == b""
    logged = json.loads(journal_path.read_text(encoding="utf-8").strip())
    assert logged["action"] == "fastresume_patch"
    assert logged["backup_path"] == entry["backup_path"]


def test_choose_repair_save_paths_rejects_broken_runtime_drift_to_tmp() -> None:
    result = choose_repair_save_paths(
        good_runtime_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
        broken_runtime_save_path="/tmp",
        good_catalog_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
        broken_catalog_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
    )

    assert result["good_effective_save_path"] == "/data/media/torrents/seeding/cross-seed/TorrentLeech"
    assert result["broken_effective_save_path"] == "/data/media/torrents/seeding/cross-seed/TorrentLeech"
    assert result["broken_reason"] == "catalog_broken_save_path_fallback"


def test_choose_repair_save_paths_prefers_catalog_when_good_runtime_drifts() -> None:
    result = choose_repair_save_paths(
        good_runtime_save_path="/pool/media/torrents/seeding/cross-seed/TorrentLeech",
        broken_runtime_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
        good_catalog_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
        broken_catalog_save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech",
    )

    assert result["good_effective_save_path"] == "/data/media/torrents/seeding/cross-seed/TorrentLeech"
    assert result["good_reason"] == "catalog_good_save_path_fallback"


def test_parse_args_defaults_log_path_to_empty_string() -> None:
    args = parse_args(["--good", "goodhash", "--broken", "brokenhash"])
    assert args.log_path == ""
    assert args.force_identical is False


def test_parse_args_accepts_force_identical() -> None:
    args = parse_args(["--good", "goodhash", "--broken", "brokenhash", "--force-identical"])
    assert args.force_identical is True


def test_build_repair_plan_does_not_stat_live_files(monkeypatch, tmp_path: Path) -> None:
    good_save = tmp_path / "good"
    broken_save = tmp_path / "broken"
    good_path = good_save / "movie.mkv"
    broken_path = broken_save / "movie.mkv"
    good_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    good_path.write_text("good", encoding="utf-8")
    broken_path.write_text("broken", encoding="utf-8")

    monkeypatch.setattr(os, "stat", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("os.stat should not be called")))

    plan = build_repair_plan(
        good_save=str(good_save),
        broken_save=str(broken_save),
        good_files=[{"name": "movie.mkv", "size": 100}],
        broken_files=[{"name": "movie.mkv", "size": 100}],
        quick_hash_lookup=lambda _path: "same-qh",
    )

    assert len(plan) == 1
    assert plan[0].action == "dup_copy"


def test_can_reuse_good_save_path_directly_for_single_file_missing_attach() -> None:
    plan = [
        build_repair_plan(
            good_save="/good",
            broken_save="/broken",
            good_files=[{"name": "movie.mkv", "size": 100}],
            broken_files=[{"name": "movie.mkv", "size": 100}],
            quick_hash_lookup=lambda _path: None,
        )[0]
    ]

    assert plan[0].action == "missing"
    assert can_reuse_good_save_path_directly(plan) is True
