"""Regression tests for rehome catalog synchronization on MOVE."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hashall.device import ensure_files_table
from rehome.executor import DemotionExecutor


class FakeQbitClient:
    def __init__(self, default_path: str):
        self.default_path = default_path
        self.save_paths = {}

    def pause_torrent(self, torrent_hash: str) -> bool:
        self.save_paths.setdefault(torrent_hash, self.default_path)
        return True

    def set_location(self, torrent_hash: str, new_location: str) -> bool:
        self.save_paths[torrent_hash] = new_location
        return True

    def resume_torrent(self, torrent_hash: str) -> bool:
        return True

    def get_torrent_info(self, torrent_hash: str):
        return SimpleNamespace(save_path=self.save_paths.get(torrent_hash, self.default_path))

    def get_torrent_files(self, torrent_hash: str):
        return []


def test_move_idempotent_reconciles_files_tables_for_single_file(tmp_path):
    db_path = tmp_path / "catalog.db"
    stash_mount = tmp_path / "stash" / "media"
    pool_mount = tmp_path / "pool" / "data"
    source_file = stash_mount / "torrents" / "seeding" / "thegeeks" / "David Khune - Wakanda - Native American Magic.epub"
    target_file = pool_mount / "David Khune - Wakanda - Native American Magic.epub"

    target_file.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = b"epub-payload"
    target_file.write_bytes(payload_bytes)

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
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
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

    source_rel = str(source_file.relative_to(stash_mount))
    conn.execute(
        """
        INSERT INTO files_49
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            source_rel,
            len(payload_bytes),
            111.0,
            "qh",
            "sha1",
            "sha256-original",
            "calculated",
            9001,
            str(source_file.parent),
        ),
    )

    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (4413, 'payload_hash', 49, ?, 1, ?, 'complete')
        """,
        (str(source_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('0d7f158164e603de99bf78112724ae03f7204b92', 4413, 49, ?, ?)
        """,
        (str(source_file.parent), source_file.name),
    )
    conn.commit()
    conn.close()

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "MOVE",
        "torrent_hash": "0d7f158164e603de99bf78112724ae03f7204b92",
        "payload_id": 4413,
        "payload_hash": "payload_hash",
        "reasons": ["idempotent recovery test"],
        "affected_torrents": ["0d7f158164e603de99bf78112724ae03f7204b92"],
        "source_path": str(source_file),
        "target_path": str(target_file),
        "source_device_id": 49,
        "target_device_id": 44,
        "file_count": 1,
        "total_bytes": len(payload_bytes),
    }

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(source_file.parent))

    # Source file is already gone, target file already present.
    assert not source_file.exists()
    assert target_file.exists()

    executor.execute(plan)

    conn = sqlite3.connect(db_path)
    try:
        payload_row = conn.execute(
            "SELECT device_id, root_path FROM payloads WHERE payload_id = 4413"
        ).fetchone()
        torrent_row = conn.execute(
            "SELECT device_id, save_path FROM torrent_instances WHERE torrent_hash = ?",
            ("0d7f158164e603de99bf78112724ae03f7204b92",),
        ).fetchone()
        src_row = conn.execute(
            "SELECT status FROM files_49 WHERE path = ?",
            (source_rel,),
        ).fetchone()
        dst_row = conn.execute(
            "SELECT status, sha256 FROM files_44 WHERE path = ?",
            (target_file.name,),
        ).fetchone()
    finally:
        conn.close()

    assert payload_row == (44, str(target_file))
    assert torrent_row == (44, str(target_file.parent))
    assert src_row == ("deleted",)
    assert dst_row == ("active", "sha256-original")


def test_reuse_cleanup_reconciles_source_files_table_without_rescan(tmp_path):
    db_path = tmp_path / "catalog.db"
    stash_mount = tmp_path / "stash" / "media"
    pool_mount = tmp_path / "pool" / "data"
    source_file = stash_mount / "torrents" / "seeding" / "books" / "example.epub"
    target_file = pool_mount / "books" / "example.epub"

    source_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = b"same-epub"
    source_file.write_bytes(payload_bytes)
    target_file.write_bytes(payload_bytes)

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
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
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

    source_rel = str(source_file.relative_to(stash_mount))
    target_rel = str(target_file.relative_to(pool_mount))
    conn.execute(
        """
        INSERT INTO files_49
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            source_rel,
            len(payload_bytes),
            111.0,
            "qh-src",
            "sha1-src",
            "sha256-same",
            "calculated",
            1001,
            str(source_file.parent),
        ),
    )
    conn.execute(
        """
        INSERT INTO files_44
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            target_rel,
            len(payload_bytes),
            222.0,
            "qh-dst",
            "sha1-dst",
            "sha256-same",
            "calculated",
            2002,
            str(target_file.parent),
        ),
    )

    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'payload_hash_reuse', 49, ?, 1, ?, 'complete')
        """,
        (str(source_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (2, 'payload_hash_reuse', 44, ?, 1, ?, 'complete')
        """,
        (str(target_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('abc123', 1, 49, ?, ?)
        """,
        (str(source_file.parent), source_file.name),
    )
    conn.commit()
    conn.close()

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "REUSE",
        "torrent_hash": "abc123",
        "payload_id": 1,
        "payload_hash": "payload_hash_reuse",
        "affected_torrents": ["abc123"],
        "source_path": str(source_file),
        "target_path": str(target_file),
        "source_device_id": 49,
        "target_device_id": 44,
        "file_count": 1,
        "total_bytes": len(payload_bytes),
        "seeding_roots": [str(stash_mount)],
        "payload_group": [
            {"root_path": str(source_file), "file_count": 1, "total_bytes": len(payload_bytes)},
            {"root_path": str(target_file), "file_count": 1, "total_bytes": len(payload_bytes)},
        ],
    }

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(source_file.parent))

    executor.execute(plan, cleanup_duplicate_payload=True)

    conn = sqlite3.connect(db_path)
    try:
        torrent_row = conn.execute(
            "SELECT payload_id, device_id, save_path FROM torrent_instances WHERE torrent_hash = 'abc123'"
        ).fetchone()
        src_row = conn.execute(
            "SELECT status FROM files_49 WHERE path = ?",
            (source_rel,),
        ).fetchone()
        dst_row = conn.execute(
            "SELECT status FROM files_44 WHERE path = ?",
            (target_rel,),
        ).fetchone()
    finally:
        conn.close()

    assert not source_file.exists()
    assert target_file.exists()
    assert torrent_row == (2, 44, str(target_file.parent))
    assert src_row == ("deleted",)
    assert dst_row == ("active",)


def test_reuse_same_device_prefers_target_root_path_row(tmp_path):
    db_path = tmp_path / "catalog.db"
    pool_mount = tmp_path / "pool" / "data"
    source_file = pool_mount / "flat" / "Movie.2024.mkv"
    target_file = pool_mount / "cross-seed" / "FearNoPeer" / "Movie.2024.mkv"

    source_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = b"movie-bytes"
    source_file.write_bytes(payload_bytes)
    target_file.write_bytes(payload_bytes)

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
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
        """
    )

    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point) VALUES (?, ?, ?, ?)",
        ("dev-44", 44, str(pool_mount), str(pool_mount)),
    )

    cur = conn.cursor()
    ensure_files_table(cur, 44)

    source_rel = str(source_file.relative_to(pool_mount))
    target_rel = str(target_file.relative_to(pool_mount))
    conn.execute(
        """
        INSERT INTO files_44
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            source_rel,
            len(payload_bytes),
            111.0,
            "qh-flat",
            "sha1-flat",
            "sha256-same",
            "calculated",
            3001,
            str(source_file.parent),
        ),
    )
    conn.execute(
        """
        INSERT INTO files_44
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            target_rel,
            len(payload_bytes),
            222.0,
            "qh-target",
            "sha1-target",
            "sha256-same",
            "calculated",
            3002,
            str(target_file.parent),
        ),
    )

    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (10, 'payload_hash_norm', 44, ?, 1, ?, 'complete')
        """,
        (str(source_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (20, 'payload_hash_norm', 44, ?, 1, ?, 'complete')
        """,
        (str(target_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('normhash', 10, 44, ?, ?)
        """,
        (str(target_file.parent), target_file.name),
    )
    conn.commit()
    conn.close()

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "REUSE",
        "torrent_hash": "normhash",
        "payload_id": 10,
        "payload_hash": "payload_hash_norm",
        "affected_torrents": ["normhash"],
        "source_path": str(source_file),
        "target_path": str(target_file),
        "source_device_id": 44,
        "target_device_id": 44,
        "file_count": 1,
        "total_bytes": len(payload_bytes),
    }

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(target_file.parent))
    executor.execute(plan, cleanup_duplicate_payload=False)

    conn = sqlite3.connect(db_path)
    try:
        payload20 = conn.execute(
            "SELECT root_path FROM payloads WHERE payload_id = 20"
        ).fetchone()
        torrent_row = conn.execute(
            "SELECT payload_id, device_id, save_path FROM torrent_instances WHERE torrent_hash = 'normhash'"
        ).fetchone()
    finally:
        conn.close()

    assert payload20 == (str(target_file),)
    assert torrent_row == (20, 44, str(target_file.parent))


def test_dry_run_cleanup_source_views_works_with_readonly_catalog(tmp_path):
    db_path = tmp_path / "catalog.db"
    pool_mount = tmp_path / "pool" / "data"
    source_file = pool_mount / "cross-seed" / "FearNoPeer" / "Example.mkv"

    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"payload")

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
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
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (1, 'hash_ro', 44, ?, 1, ?, 'complete')
        """,
        (str(source_file), source_file.stat().st_size),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('tor_ro', 1, 44, ?, ?)
        """,
        (str(source_file.parent), source_file.name),
    )
    conn.commit()
    conn.close()

    # Simulate readonly catalog (for example restored snapshots/symlinked DBs).
    db_path.chmod(0o444)

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "REUSE",
        "torrent_hash": "tor_ro",
        "payload_id": 1,
        "payload_hash": "hash_ro",
        "affected_torrents": ["tor_ro"],
        "source_path": str(source_file),
        "target_path": str(source_file),
        "source_device_id": 44,
        "target_device_id": 44,
        "file_count": 1,
        "total_bytes": source_file.stat().st_size,
        "seeding_roots": [str(pool_mount)],
    }

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(source_file.parent))
    executor.dry_run(plan, cleanup_source_views=True)


def test_reuse_same_device_without_target_payload_row_repoints_source_payload(tmp_path):
    db_path = tmp_path / "catalog.db"
    pool_mount = tmp_path / "pool" / "data"
    source_file = pool_mount / "flat" / "Movie.2024.mkv"
    target_file = pool_mount / "cross-seed" / "FearNoPeer" / "Movie.2024.mkv"

    source_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = b"movie-bytes"
    source_file.write_bytes(payload_bytes)
    target_file.write_bytes(payload_bytes)

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
            status TEXT NOT NULL DEFAULT 'incomplete',
            last_built_at REAL,
            updated_at REAL
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL,
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
        """
    )

    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point) VALUES (?, ?, ?, ?)",
        ("dev-44", 44, str(pool_mount), str(pool_mount)),
    )

    cur = conn.cursor()
    ensure_files_table(cur, 44)

    source_rel = str(source_file.relative_to(pool_mount))
    target_rel = str(target_file.relative_to(pool_mount))
    conn.execute(
        """
        INSERT INTO files_44
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            source_rel,
            len(payload_bytes),
            111.0,
            "qh-flat",
            "sha1-flat",
            "sha256-same",
            "calculated",
            3001,
            str(source_file.parent),
        ),
    )
    conn.execute(
        """
        INSERT INTO files_44
            (path, size, mtime, quick_hash, sha1, sha256, hash_source, inode, status, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            target_rel,
            len(payload_bytes),
            222.0,
            "qh-target",
            "sha1-target",
            "sha256-same",
            "calculated",
            3002,
            str(target_file.parent),
        ),
    )

    conn.execute(
        """
        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES (10, 'payload_hash_norm_missing_target', 44, ?, 1, ?, 'complete')
        """,
        (str(source_file), len(payload_bytes)),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name)
        VALUES ('normhash_missing_target', 10, 44, ?, ?)
        """,
        (str(target_file.parent), target_file.name),
    )
    conn.commit()
    conn.close()

    plan = {
        "version": "1.0",
        "direction": "demote",
        "decision": "REUSE",
        "torrent_hash": "normhash_missing_target",
        "payload_id": 10,
        "payload_hash": "payload_hash_norm_missing_target",
        "affected_torrents": ["normhash_missing_target"],
        "source_path": str(source_file),
        "target_path": str(target_file),
        "source_device_id": 44,
        "target_device_id": 44,
        "file_count": 1,
        "total_bytes": len(payload_bytes),
    }

    executor = DemotionExecutor(catalog_path=db_path)
    executor.qbit_client = FakeQbitClient(default_path=str(target_file.parent))
    executor.execute(plan, cleanup_duplicate_payload=False)

    conn = sqlite3.connect(db_path)
    try:
        payload10 = conn.execute(
            "SELECT root_path FROM payloads WHERE payload_id = 10"
        ).fetchone()
        torrent_row = conn.execute(
            "SELECT payload_id, device_id, save_path FROM torrent_instances WHERE torrent_hash = 'normhash_missing_target'"
        ).fetchone()
    finally:
        conn.close()

    assert payload10 == (str(target_file),)
    assert torrent_row == (10, 44, str(target_file.parent))
