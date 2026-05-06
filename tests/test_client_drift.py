import json
import re
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from hashall.bencode import bencode_dump
from hashall.cli import cli
from hashall.cli import _read_client_drift_journal
from hashall.cli import _rt_qb_monitor_classify
from hashall.client_drift import (
    ClientDriftPolicy,
    build_client_drift_report,
    default_policy,
)


def _write_rt_session(session_dir: Path, torrent_hash: str, directory: Path, name: str = "Release.One") -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    bencode_dump(
        session_dir / f"{torrent_hash.upper()}.torrent",
        {
            b"info": {
                b"name": name.encode("utf-8"),
                b"files": [{b"length": 123, b"path": [b"file.bin"]}],
            }
        },
    )
    bencode_dump(
        session_dir / f"{torrent_hash.upper()}.torrent.rtorrent",
        {b"directory": str(directory).encode("utf-8")},
    )


def _assert_output_field(output: str, label: str, value: object) -> None:
    assert re.search(rf"{re.escape(label)}:\s+{re.escape(str(value))}\b", output)


class _FakeTorrentInfo:
    def __init__(self, state: str, progress: float, amount_left: int) -> None:
        self.state = state
        self.progress = progress
        self.amount_left = amount_left


def test_rt_qb_monitor_classifies_stopped_complete_success() -> None:
    status, detail = _rt_qb_monitor_classify(_FakeTorrentInfo("stoppedUP", 1.0, 0))

    assert status == "success"
    assert detail == "stoppedUP 100%"


def test_rt_qb_monitor_classifies_downloading_failure() -> None:
    status, detail = _rt_qb_monitor_classify(_FakeTorrentInfo("downloading", 0.5, 100))

    assert status == "failure"
    assert "transitioned_to_downloading" in detail


def test_rt_qb_monitor_keeps_checking_pending() -> None:
    status, detail = _rt_qb_monitor_classify(_FakeTorrentInfo("checkingDL", 0.5, 100))

    assert status == "pending"
    assert "checkingDL" in detail


def test_client_drift_conservative_does_not_auto_mirror_rt_only(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=default_policy("conservative"),
    )

    assert report["summary"]["rt_only"] == 1
    assert report["rows"][0]["action"] == "manual_review"
    assert "no_policy_says_rt_only_should_be_mirrored_or_removed" in report["rows"][0]["blockers"]


def test_client_drift_policy_mirrors_healthy_rt_only_under_mirror_root(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            mirror_roots=(str(tmp_path / "seeding"),),
            mode="rt-authoritative-mirror",
        ),
    )

    row = report["rows"][0]
    assert row["action"] == "mirror_rt_to_qb"
    assert row["confidence"] == "high"
    assert row["rt"]["target_qb_save_path"] == str(seed_root)


def test_client_drift_common_hash_aligned_paths_are_not_drift(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    (content_root / "file.bin").write_text("payload", encoding="utf-8")
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(seed_root),
                "content_path": str(content_root),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool"),),
            stash_roots=(str(tmp_path / "stash"),),
            arr_library_roots=(str(tmp_path / "library"),),
        ),
    )

    assert report["summary"]["path_drift"] == 0
    assert report["rows"] == []


def test_client_drift_path_drift_prefers_pool_without_arr_hardlink_anchor(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    qb_content.mkdir(parents=True)
    rt_content.mkdir(parents=True)
    library_root.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    (rt_content / "file.bin").write_text("payload", encoding="utf-8")
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=1000,
        ),
    )

    row = report["rows"][0]
    assert report["summary"]["path_drift"] == 1
    assert row["side"] == "path_drift"
    assert row["action"] == "repoint_rt_to_qb_path"
    assert row["placement"]["desired"] == "pool"
    assert row["placement"]["proposed_source_client"] == "qb"
    assert row["placement"]["proposed_rt_directory"] == str(qb_content)
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is False
    assert "no_arr_library_hardlink_anchor_found" in row["reasons"]


def test_client_drift_path_drift_prefers_stash_with_arr_hardlink_anchor(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    qb_content.mkdir(parents=True)
    rt_content.mkdir(parents=True)
    library_root.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    rt_file = rt_content / "file.bin"
    rt_file.write_text("payload", encoding="utf-8")
    (library_root / "Release.One.bin").hardlink_to(rt_file)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=1000,
        ),
    )

    row = report["rows"][0]
    assert report["summary"]["path_drift"] == 1
    assert row["action"] == "repoint_qb_to_rt_path"
    assert row["placement"]["desired"] == "stash"
    assert row["placement"]["proposed_source_client"] == "rt"
    assert row["placement"]["proposed_qb_save_path"] == str(stash_seed)
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is True
    assert row["placement"]["anchor_scan"]["anchor_paths"] == [str(library_root / "Release.One.bin")]
    assert "arr_library_hardlink_anchor_present" in row["reasons"]


def test_client_drift_hash_filter_limits_anchor_scan_to_selected_hash(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    library_root = tmp_path / "library" / "movies"
    library_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    selected_hash = "aaa111"
    other_hash = "bbb222"
    selected_qb = pool_seed / "Selected.Release"
    selected_rt = stash_seed / "Selected.Release"
    other_qb = pool_seed / "Other.Release"
    other_rt = stash_seed / "Other.Release"
    for path in (selected_qb, selected_rt, other_qb, other_rt):
        path.mkdir(parents=True)
        (path / "file.bin").write_text("payload", encoding="utf-8")
    _write_rt_session(session_dir, selected_hash, selected_rt, name="Selected.Release")
    _write_rt_session(session_dir, other_hash, other_rt, name="Other.Release")
    qb_cache.write_text(
        json.dumps([
            {
                "hash": selected_hash,
                "name": "Selected.Release",
                "save_path": str(pool_seed),
                "content_path": str(selected_qb),
                "state": "stoppedUP",
                "progress": 1,
            },
            {
                "hash": other_hash,
                "name": "Other.Release",
                "save_path": str(pool_seed),
                "content_path": str(other_qb),
                "state": "stoppedUP",
                "progress": 1,
            },
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": selected_hash,
                "name": "Selected.Release",
                "directory": str(selected_rt),
                "state": "stalledUP",
                "complete": 1,
            },
            {
                "hash": other_hash,
                "name": "Other.Release",
                "directory": str(other_rt),
                "state": "stalledUP",
                "complete": 1,
            },
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=1000,
        ),
        hash_filters=("aaa",),
    )

    assert report["summary"]["hash_filters"] == ["aaa"]
    assert report["summary"]["path_drift"] == 1
    assert [row["hash"] for row in report["rows"]] == [selected_hash]


def test_client_drift_uses_catalog_hardlink_anchor_evidence(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    for path in (qb_content, rt_content, library_root):
        path.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    (rt_content / "file.bin").write_text("payload", encoding="utf-8")
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
    conn.executescript("""
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            device_id INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            status TEXT DEFAULT 'active'
        );
    """)
    conn.execute(
        "INSERT INTO files (path, device_id, inode, size, mtime, status) VALUES (?, ?, ?, ?, ?, 'active')",
        (str(rt_content / "file.bin"), 4242, 1001, 7, 0.0),
    )
    conn.execute(
        "INSERT INTO files (path, device_id, inode, size, mtime, status) VALUES (?, ?, ?, ?, ?, 'active')",
        (str(library_root / "Release.One.bin"), 4242, 1001, 7, 0.0),
    )
    conn.commit()
    conn.close()
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=0,
        ),
        hash_filters=(torrent_hash,),
        catalog_path=catalog,
    )

    row = report["rows"][0]
    assert report["summary"]["catalog_path"] == str(catalog)
    assert row["action"] == "repoint_qb_to_rt_path"
    assert row["placement"]["anchor_scan"]["source"] == "catalog"
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is True
    assert row["placement"]["proposed_qb_save_path"] == str(stash_seed)


def test_client_drift_catalog_no_anchor_evidence_still_requires_filesystem_confirmation(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    for path in (qb_content, rt_content, library_root):
        path.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    (rt_content / "file.bin").write_text("payload", encoding="utf-8")
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
    conn.executescript("""
        CREATE TABLE files_fs_zfs_123 (
            path TEXT PRIMARY KEY,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            status TEXT DEFAULT 'active'
        );
    """)
    conn.execute(
        "INSERT INTO files_fs_zfs_123 (path, inode, size, mtime, status) VALUES (?, ?, ?, ?, 'active')",
        (str(qb_content / "file.bin"), 2001, 7, 0.0),
    )
    conn.execute(
        "INSERT INTO files_fs_zfs_123 (path, inode, size, mtime, status) VALUES (?, ?, ?, ?, 'active')",
        (str(rt_content / "file.bin"), 2002, 7, 0.0),
    )
    conn.commit()
    conn.close()
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=0,
        ),
        hash_filters=(torrent_hash,),
        catalog_path=catalog,
    )

    row = report["rows"][0]
    assert row["action"] == "manual_review"
    assert row["placement"]["anchor_scan"]["source"] == "catalog"
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is None
    assert "catalog_negative_anchor_requires_filesystem_confirmation" in row["blockers"]
    assert row["placement"]["proposed_rt_directory"] == ""


def test_client_drift_catalog_inode_match_requires_same_device_identity(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    for path in (qb_content, rt_content, library_root):
        path.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    (rt_content / "file.bin").write_text("payload", encoding="utf-8")
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
    conn.executescript("""
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            device_id INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            status TEXT DEFAULT 'active'
        );
    """)
    conn.execute(
        "INSERT INTO files (path, device_id, inode, size, mtime, status) VALUES (?, ?, ?, ?, ?, 'active')",
        (str(rt_content / "file.bin"), 1, 3001, 7, 0.0),
    )
    conn.execute(
        "INSERT INTO files (path, device_id, inode, size, mtime, status) VALUES (?, ?, ?, ?, ?, 'active')",
        (str(library_root / "same-inode-different-device.bin"), 2, 3001, 7, 0.0),
    )
    conn.commit()
    conn.close()
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=0,
        ),
        hash_filters=(torrent_hash,),
        catalog_path=catalog,
    )

    row = report["rows"][0]
    assert row["action"] == "manual_review"
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is None
    assert "catalog_negative_anchor_requires_filesystem_confirmation" in row["blockers"]
    assert row["placement"]["anchor_scan"]["anchor_paths"] == []


def test_client_drift_catalog_rows_without_device_identity_are_not_anchor_proof(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    library_root = tmp_path / "library" / "movies"
    for path in (qb_content, rt_content, library_root):
        path.mkdir(parents=True)
    (qb_content / "file.bin").write_text("payload", encoding="utf-8")
    (rt_content / "file.bin").write_text("payload", encoding="utf-8")
    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
    conn.executescript("""
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            status TEXT DEFAULT 'active'
        );
    """)
    conn.execute(
        "INSERT INTO files (path, inode, size, mtime, status) VALUES (?, ?, ?, ?, 'active')",
        (str(rt_content / "file.bin"), 4001, 7, 0.0),
    )
    conn.execute(
        "INSERT INTO files (path, inode, size, mtime, status) VALUES (?, ?, ?, ?, 'active')",
        (str(library_root / "same-inode-unknown-device.bin"), 4001, 7, 0.0),
    )
    conn.commit()
    conn.close()
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(library_root),),
            anchor_scan_max_files=0,
        ),
        hash_filters=(torrent_hash,),
        catalog_path=catalog,
    )

    row = report["rows"][0]
    assert row["action"] == "manual_review"
    assert row["placement"]["anchor_scan"]["has_arr_anchor"] is None
    assert "catalog_table_lacks_filesystem_identity:files" in row["blockers"]


def test_client_drift_nohl_tag_is_advisory_not_proof(tmp_path: Path) -> None:
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    qb_content = pool_seed / "Release.One"
    rt_content = stash_seed / "Release.One"
    for path in (qb_content, rt_content):
        path.mkdir(parents=True)
        (path / "file.bin").write_text("payload", encoding="utf-8")
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, rt_content)
    qb_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "save_path": str(pool_seed),
                "content_path": str(qb_content),
                "state": "stoppedUP",
                "progress": 1,
                "tags": "~noHL,tracker",
            }
        ]),
        encoding="utf-8",
    )
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(rt_content),
                "state": "stalledUP",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(
            pool_roots=(str(tmp_path / "pool" / "torrents" / "seeding"),),
            stash_roots=(str(tmp_path / "stash" / "torrents" / "seeding"),),
            arr_library_roots=(str(tmp_path / "library"),),
            anchor_scan_max_files=0,
        ),
    )

    row = report["rows"][0]
    assert row["action"] == "manual_review"
    assert row["placement"]["qb_has_nohl_tag"] is True
    assert "qb_nohl_tag_present_advisory" in row["reasons"]
    assert "hardlink_anchor_evidence_required_for_placement" in row["blockers"]
    assert row["placement"]["proposed_source_client"] == ""


def test_client_drift_remove_requires_explicit_policy(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "stale",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    report = build_client_drift_report(
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
        policy=ClientDriftPolicy(remove_from_rt_categories=("stale",)),
    )

    assert report["rows"][0]["action"] == "remove_from_rt"
    assert "explicit_remove_from_rt_policy" in report["rows"][0]["reasons"]


def test_client_drift_cli_audit_json_output(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "audit",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--json-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output[result.output.find("{"):])
    assert payload["summary"]["rt_only"] == 1
    assert payload["rows"][0]["action"] == "manual_review"


def test_client_drift_policy_template_is_conservative_by_default(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["hashall", "client-drift", "policy-template"])
    result = CliRunner().invoke(cli, ["client-drift", "policy-template"])

    assert result.exit_code == 0
    assert result.output.lstrip().startswith("{")
    payload = json.loads(result.output)
    assert payload["mode"] == "conservative"
    assert payload["mirror_roots"] == []
    assert payload["_example_mirror_roots"]


def test_client_drift_apply_dry_run_does_not_construct_qb_client(tmp_path: Path, monkeypatch) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )

    def fail_client():
        raise AssertionError("dry-run must not construct qB client")

    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", fail_client)
    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "apply",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--policy",
            str(policy),
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "selected: 1" in result.output


def test_client_drift_apply_rejects_remove_actions() -> None:
    result = CliRunner().invoke(
        cli,
        ["client-drift", "apply", "--action", "remove_from_rt"],
    )

    assert result.exit_code != 0
    assert "remove actions are audit-only" in result.output


def test_client_drift_journal_does_not_skip_failed_verify(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps({"hash": "aaa111", "status": "ok", "verify": {"ok": True}}),
                json.dumps({"hash": "bbb222", "status": "ok", "error": "verify_incomplete"}),
                json.dumps({"hash": "ccc333", "status": "ok", "verify": {"ok": False}}),
                json.dumps({"hash": "ddd444", "status": "already_present"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert _read_client_drift_journal(journal) == {"aaa111", "ddd444"}


def test_rt_qb_mirror_enqueue_respects_disable_env(tmp_path: Path, monkeypatch) -> None:
    queue_dir = tmp_path / "queue"
    monkeypatch.setenv("HASHALL_QB_MIRROR_ENABLED", "0")

    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "enqueue",
            "AAA111",
            "--queue-dir",
            str(queue_dir),
        ],
    )

    assert result.exit_code == 0
    assert "disabled" in result.output
    assert not queue_dir.exists()


def test_rt_qb_mirror_enqueue_writes_queue_file(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"

    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "enqueue",
            "AAA111",
            "--queue-dir",
            str(queue_dir),
            "--source",
            "test",
        ],
    )

    assert result.exit_code == 0
    queue_file = queue_dir / "aaa111.json"
    assert queue_file.exists()
    payload = json.loads(queue_file.read_text(encoding="utf-8"))
    assert payload["hash"] == "aaa111"
    assert payload["source"] == "test"


def test_rt_qb_mirror_sync_dry_run_selects_mirror_rows_without_qb(tmp_path: Path, monkeypatch) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )

    def fail_client():
        raise AssertionError("dry-run must not construct qB client")

    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", fail_client)
    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "sync",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--policy",
            str(policy),
            "--hash",
            torrent_hash[:6],
            "--journal",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code == 0
    _assert_output_field(result.output, "selected", 1)
    assert torrent_hash in result.output


def test_rt_qb_mirror_sync_apply_rechecks_by_default(tmp_path: Path, monkeypatch) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )

    class FakeQbit:
        last_error = None

        def __init__(self) -> None:
            self.rechecked: list[str] = []

        def get_torrent_info(self, torrent_hash: str):
            return None

        def add_torrent_file(self, *args, **kwargs) -> bool:
            return True

        def add_tags(self, torrent_hash: str, tags: list[str]) -> bool:
            return True

        def recheck_torrent(self, torrent_hash: str) -> bool:
            self.rechecked.append(torrent_hash)
            return True

    fake = FakeQbit()
    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", lambda: fake)
    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "sync",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--policy",
            str(policy),
            "--hash",
            torrent_hash,
            "--journal",
            str(tmp_path / "journal.jsonl"),
            "--apply",
            "--no-monitor",
        ],
    )

    assert result.exit_code == 0
    assert fake.rechecked == [torrent_hash]
    assert "recheck_started: True" in result.output


def test_rt_qb_mirror_process_queue_keeps_blocked_rows_queued(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    torrent_hash = "aaa111"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "downloading",
                "category": "tv",
                "complete": 0,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )
    queue_file = queue_dir / f"{torrent_hash}.json"
    queue_file.write_text(json.dumps({"hash": torrent_hash, "first_seen": 1}), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "process-queue",
            "--queue-dir",
            str(queue_dir),
            "--min-age",
            "0",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--policy",
            str(policy),
            "--journal",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code == 0
    _assert_output_field(result.output, "selected", 0)
    assert "queued_not_ready_for_mirror" in result.output
    assert queue_file.exists()


def test_rt_qb_mirror_process_queue_matches_hash_prefix_to_selected_row(tmp_path: Path) -> None:
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    torrent_hash = "aaa111bbb222"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )
    queue_file = queue_dir / "aaa111.json"
    queue_file.write_text(json.dumps({"hash": "aaa111", "first_seen": 1}), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror",
            "process-queue",
            "--queue-dir",
            str(queue_dir),
            "--min-age",
            "0",
            "--qb-cache-file",
            str(qb_cache),
            "--rt-cache-file",
            str(rt_cache),
            "--rt-session-dir",
            str(session_dir),
            "--policy",
            str(policy),
            "--journal",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code == 0
    _assert_output_field(result.output, "selected", 1)
    assert "dry-run would_remove_queue" in result.output
    assert "queued_not_ready_for_mirror" not in result.output
    assert queue_file.exists()
