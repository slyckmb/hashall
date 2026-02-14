import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hashall.device import ensure_files_table
from scripts.recovery_nonseeding_workflow import (
    _derive_canonical_base,
    _unit_key_from_suffix,
    apply_exact_prune,
    build_report,
)


def _setup_db(db_path: Path, stash_mount: Path, pool_mount: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE devices (
            fs_uuid TEXT PRIMARY KEY,
            device_id INTEGER UNIQUE,
            mount_point TEXT,
            preferred_mount_point TEXT
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
            save_path TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point) VALUES (?, ?, ?, ?)",
        ("dev-49", 49, str(stash_mount), str(stash_mount)),
    )
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point) VALUES (?, ?, ?, ?)",
        ("dev-44", 44, str(pool_mount), str(pool_mount)),
    )
    cur = conn.cursor()
    ensure_files_table(cur, 49)
    ensure_files_table(cur, 44)
    return conn


def test_recovery_helpers():
    base = _derive_canonical_base("torrents/seeding/recovery_20260211/recycle_snapshot_20260207")
    assert base == "torrents/seeding"

    assert _unit_key_from_suffix("cross-seed/FileList.io/Example.Release/movie.mkv") == "cross-seed/FileList.io/Example.Release"
    assert _unit_key_from_suffix("movies/Loose.Movie.avi") == "movies/Loose.Movie.avi"


def test_recovery_workflow_build_and_apply_exact_prune(tmp_path: Path):
    stash_mount = tmp_path / "stash" / "media"
    pool_mount = tmp_path / "pool" / "data"
    stash_mount.mkdir(parents=True, exist_ok=True)
    pool_mount.mkdir(parents=True, exist_ok=True)

    recovery_abs = (
        stash_mount
        / "torrents"
        / "seeding"
        / "recovery_20260211"
        / "recycle_snapshot_20260207"
    )
    dup_file = recovery_abs / "cross-seed" / "TrackerA" / "Torrent.One" / "movie.mkv"
    unique_file = recovery_abs / "movies" / "Unique.Movie.2020.mkv"
    dup_file.parent.mkdir(parents=True, exist_ok=True)
    unique_file.parent.mkdir(parents=True, exist_ok=True)
    dup_file.write_bytes(b"dup-bytes")
    unique_file.write_bytes(b"unique-bytes")

    canonical_pool_file = (
        pool_mount
        / "torrents"
        / "seeding"
        / "cross-seed"
        / "TrackerA"
        / "Torrent.One"
        / "movie.mkv"
    )
    canonical_pool_file.parent.mkdir(parents=True, exist_ok=True)
    canonical_pool_file.write_bytes(b"dup-bytes")

    db_path = tmp_path / "catalog.db"
    conn = _setup_db(db_path, stash_mount=stash_mount, pool_mount=pool_mount)
    try:
        dup_rel = str(dup_file.relative_to(stash_mount))
        unique_rel = str(unique_file.relative_to(stash_mount))
        pool_dup_rel = str(canonical_pool_file.relative_to(pool_mount))

        conn.execute(
            """
            INSERT INTO files_49 (path, size, mtime, sha256, inode, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (dup_rel, dup_file.stat().st_size, 100.0, "sha-dup", 1001),
        )
        conn.execute(
            """
            INSERT INTO files_49 (path, size, mtime, sha256, inode, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (unique_rel, unique_file.stat().st_size, 100.0, "sha-unique", 1002),
        )
        conn.execute(
            """
            INSERT INTO files_44 (path, size, mtime, sha256, inode, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (pool_dup_rel, canonical_pool_file.stat().st_size, 200.0, "sha-dup", 2001),
        )
        conn.commit()

        report = build_report(
            conn,
            stash_device=49,
            pool_device=44,
            recovery_prefix=str(recovery_abs),
        )
        actions = {u["unit_key"]: u["action"] for u in report["units"]}
        assert actions["cross-seed/TrackerA/Torrent.One"] == "DELETE_EXACT_DUPLICATE"
        assert actions["movies/Unique.Movie.2020.mkv"] == "REVIEW_PARTIAL"

        apply = apply_exact_prune(conn, report=report, stash_device=49, limit=10)
        assert apply["deleted_units"] == 1
        assert dup_file.exists() is False
        assert unique_file.exists() is True

        dup_status = conn.execute(
            "SELECT status FROM files_49 WHERE path = ?",
            (dup_rel,),
        ).fetchone()
        unique_status = conn.execute(
            "SELECT status FROM files_49 WHERE path = ?",
            (unique_rel,),
        ).fetchone()
        assert dup_status == ("deleted",)
        assert unique_status == ("active",)
    finally:
        conn.close()
