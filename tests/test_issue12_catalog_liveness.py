"""Regression tests for issue #12: filesystem identity, interrupted-scan
tombstones, incremental reuse, liveness repair and targeted SHA-256."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import hashall.scan as scan
from hashall.device import (
    FilesystemIdentityError,
    files_table_name_for_fs_uuid,
    get_files_table_name,
    register_or_update_device,
)
from hashall.fs_utils import get_filesystem_uuid, get_mount_point
from hashall.liveness_repair import run_liveness_repair
from hashall.model import connect_db
from hashall.scan import load_existing_files, scan_path
from hashall.sha256_targeted import (
    NOT_HASHED,
    SHA256_CATALOGED,
    SHA256_COMPUTED,
    hash_selected_files,
)


# ---------------------------------------------------------------- helpers

def _make_tree(root: Path, n: int = 12) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(n):
        sub = root / ("a_b" if i % 2 else "axb")
        sub.mkdir(exist_ok=True)
        path = sub / f"f{i:02d}.txt"
        path.write_text(f"content-{i}\n" * (i + 1))
        files.append(path)
    return files


def _table_and_mount(db: Path, root: Path) -> tuple[str, Path]:
    fs_uuid = get_filesystem_uuid(str(root))
    conn = sqlite3.connect(db)
    try:
        table, mount, preferred = conn.execute(
            "SELECT files_table, mount_point, preferred_mount_point FROM devices WHERE fs_uuid = ?",
            (fs_uuid,),
        ).fetchone()
    finally:
        conn.close()
    return table, Path(preferred or mount)


def _statuses(db: Path, root: Path) -> dict[str, str]:
    table, mount = _table_and_mount(db, root)
    rel_root = str(root.resolve().relative_to(mount))
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            f'SELECT path, status FROM "{table}" WHERE substr(path, 1, ?) = ?',
            (len(rel_root) + 1, rel_root + "/"),
        ).fetchall()
    finally:
        conn.close()
    return {str(mount / p): s for p, s in rows}


def _sessions(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT status, files_deleted FROM scan_sessions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _scan_root_count(db: Path, root: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT scan_count FROM scan_roots WHERE root_path = ?", (str(root.resolve()),)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def _interrupt_after(n: int):
    real = scan._hash_file_worker
    calls = {"n": 0}

    def worker(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > n:
            raise KeyboardInterrupt()
        return real(*args, **kwargs)

    return worker


# ------------------------------------------- interrupted-scan invariant

@pytest.mark.parametrize("parallel", [False, True])
def test_interrupt_after_discovery_tombstones_nothing(tmp_path, monkeypatch, parallel):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    assert set(_statuses(db, root).values()) == {"active"}
    assert _scan_root_count(db, root) == 1

    monkeypatch.setattr(scan, "_hash_file_worker", _interrupt_after(3))
    if parallel:
        result = scan_path(db_path=db, root_path=root, quiet=True, parallel=True, workers=1)
        assert result.final_status == "interrupted"
        assert result.files_deleted == 0
        assert result.deletion_skipped_reason == ""  # no unvisited active rows were even considered deletable
    else:
        with pytest.raises(KeyboardInterrupt):
            scan_path(db_path=db, root_path=root, quiet=True)

    statuses = _statuses(db, root)
    assert len(statuses) == len(files)
    assert set(statuses.values()) == {"active"}, "unvisited rows must not be tombstoned"
    status, deleted = _sessions(db)[-1]
    assert status == "interrupted"
    assert deleted == 0
    # An interrupted scan never advertises the root as refreshed.
    assert _scan_root_count(db, root) == 1


def test_interrupted_scan_with_real_absence_still_preserves_liveness(tmp_path, monkeypatch):
    """Even a genuinely removed file is not tombstoned by an incomplete scan."""
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    files[0].unlink()
    monkeypatch.setattr(scan, "_hash_file_worker", _interrupt_after(2))
    result = scan_path(db_path=db, root_path=root, quiet=True, parallel=True, workers=1)
    assert result.final_status == "interrupted"
    assert result.deletion_skipped_reason == "interrupted"
    assert set(_statuses(db, root).values()) == {"active"}


def test_interrupt_during_discovery_finalizes_session(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    real_walk = os.walk

    def walk(top, *args, **kwargs):
        for i, item in enumerate(real_walk(top, *args, **kwargs)):
            if i == 1:
                raise KeyboardInterrupt()
            yield item

    monkeypatch.setattr(scan.os, "walk", walk)
    with pytest.raises(KeyboardInterrupt):
        scan_path(db_path=db, root_path=root, quiet=True)
    assert _sessions(db)[-1] == ("interrupted", 0)
    assert set(_statuses(db, root).values()) == {"active"}


def test_worker_errors_do_not_tombstone_existing_files(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    real = scan._hash_file_worker

    def worker(work_item, *args, **kwargs):
        if work_item["representative_path"].endswith(("f01.txt", "f02.txt")):
            return None  # simulated hash/IO failure
        return real(work_item, *args, **kwargs)

    monkeypatch.setattr(scan, "_hash_file_worker", worker)
    result = scan_path(db_path=db, root_path=root, quiet=True)
    assert result.files_deleted == 0
    assert set(_statuses(db, root).values()) == {"active"}
    assert len(_statuses(db, root)) == len(files)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses permissions")
def test_unreadable_directory_blocks_delete_pass_and_marks_partial(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    locked = root / "a_b"
    files[0].unlink()  # a real deletion elsewhere must also wait for a complete traversal
    locked.chmod(0)
    try:
        result = scan_path(db_path=db, root_path=root, quiet=True)
    finally:
        locked.chmod(0o755)
    assert result.final_status == "partial"
    assert result.files_deleted == 0
    assert set(_statuses(db, root).values()) == {"active"}
    assert _sessions(db)[-1][0] == "partial"
    assert _scan_root_count(db, root) == 1


def test_complete_scan_detects_real_deletion(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    files[3].unlink()
    result = scan_path(db_path=db, root_path=root, quiet=True)
    assert result.final_status == "completed"
    assert result.files_deleted == 1
    statuses = _statuses(db, root)
    assert statuses[str(files[3])] == "deleted"
    assert sum(1 for s in statuses.values() if s == "active") == len(files) - 1
    assert _sessions(db)[-1] == ("completed", 1)
    assert _scan_root_count(db, root) == 2


def test_nonregular_files_are_skipped_without_worker_errors(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root, n=3)
    os.mkfifo(root / "pipe")
    result = scan_path(db_path=db, root_path=root, quiet=True, parallel=True, workers=2)
    assert result.final_status == "completed"
    assert len(_statuses(db, root)) == len(files)


# ------------------------------------------- incremental reuse / reactivation

def test_unchanged_incremental_rescan_hashes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    calls = {"n": 0}
    real = scan.compute_quick_hash

    def counting(path, *a, **kw):
        calls["n"] += 1
        return real(path, *a, **kw)

    monkeypatch.setattr(scan, "compute_quick_hash", counting)
    result = scan_path(db_path=db, root_path=root, quiet=True)
    assert calls["n"] == 0
    assert result.bytes_hashed == 0
    assert result.files_unchanged == len(files)


def test_previously_deleted_but_present_files_reactivate_without_rehash(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    table, mount = _table_and_mount(db, root)
    false_tombstones = [str(p.relative_to(mount)) for p in files[:5]]
    conn = sqlite3.connect(db)
    conn.executemany(f'UPDATE "{table}" SET status = \'deleted\' WHERE path = ?', [(p,) for p in false_tombstones])
    conn.execute(f'UPDATE "{table}" SET sha256 = ? WHERE path = ?', ("ab" * 32, false_tombstones[0]))
    conn.commit()
    conn.close()

    calls = {"n": 0}
    real = scan.compute_quick_hash
    monkeypatch.setattr(scan, "compute_quick_hash", lambda p, *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(p, *a, **k))[1])
    result = scan_path(db_path=db, root_path=root, quiet=True)
    assert calls["n"] == 0, "reactivation must reuse existing hashes"
    assert result.files_reactivated == 5
    assert result.bytes_hashed == 0
    assert set(_statuses(db, root).values()) == {"active"}
    conn = sqlite3.connect(db)
    assert conn.execute(f'SELECT sha256 FROM "{table}" WHERE path = ?', (false_tombstones[0],)).fetchone()[0] == "ab" * 32
    conn.close()


def test_load_existing_files_prefix_is_literal_not_like_pattern(tmp_path):
    db = tmp_path / "catalog.db"
    conn = connect_db(db)
    cur = conn.cursor()
    register_or_update_device(cur, "zfs-test", 90, "/vol")
    table = files_table_name_for_fs_uuid("zfs-test")
    for path in ("a_b/x", "axb/y", "a_b", "a%b/z"):
        cur.execute(f'INSERT INTO "{table}" (path, size, mtime, inode) VALUES (?, 1, 1.0, 1)', (path,))
    conn.commit()
    got = load_existing_files(cur, 90, Path("/vol/a_b"), fs_uuid="zfs-test")
    assert set(got) == {"a_b", "a_b/x"}
    assert set(load_existing_files(cur, 90, Path("/vol/a%b"), fs_uuid="zfs-test")) == {"a%b/z"}
    conn.close()


# ------------------------------------------- filesystem identity correctness

@patch("hashall.fs_utils.get_zfs_metadata", return_value={})
@patch("hashall.device._get_fs_type", return_value="zfs")
def test_reused_device_id_does_not_rebind_other_filesystem(_fs_type, _zfs, tmp_path):
    """Reproduces the 2026-04 mechanism: pool/backup/secrets got st_dev 54, which
    stash/home/michael's row held; the old code rewrote that row's fs_uuid in
    place, inheriting michael's files table, preferred mount and scan history."""
    conn = connect_db(tmp_path / "catalog.db")
    cur = conn.cursor()
    register_or_update_device(cur, "zfs-home", 54, "/stash/home/michael")
    home_table = files_table_name_for_fs_uuid("zfs-home")
    cur.execute(f'INSERT INTO "{home_table}" (path, size, mtime, inode) VALUES (?, 1, 1.0, 1)', ("doc.txt",))
    cur.execute(
        "INSERT INTO scan_roots (fs_uuid, root_path, last_scanned_at, scan_count) VALUES (?, ?, datetime('now'), 1)",
        ("zfs-home", "/stash/home/michael"),
    )
    conn.commit()

    info = register_or_update_device(cur, "zfs-secrets", 54, "/pool/backup/secrets")
    conn.commit()

    home = cur.execute(
        "SELECT device_id, files_table, preferred_mount_point FROM devices WHERE fs_uuid = 'zfs-home'"
    ).fetchone()
    assert home is not None and home[0] < 0  # parked, identity intact
    assert home[1] == home_table
    assert home[2] == "/stash/home/michael"
    assert info["fs_uuid"] == "zfs-secrets"
    assert info["files_table"] == files_table_name_for_fs_uuid("zfs-secrets")
    assert info["preferred_mount_point"] == "/pool/backup/secrets"
    assert [tuple(r) for r in cur.execute("SELECT fs_uuid FROM scan_roots").fetchall()] == [("zfs-home",)]
    # The secrets slot must not resolve to michael's catalog.
    assert get_files_table_name(cur, device_id=54) == files_table_name_for_fs_uuid("zfs-secrets")
    conn.close()


@patch("hashall.fs_utils.get_zfs_metadata", return_value={})
@patch("hashall.device._get_fs_type", return_value="zfs")
def test_placeholder_identity_still_upgrades_in_place(_fs_type, _zfs, tmp_path):
    conn = connect_db(tmp_path / "catalog.db")
    cur = conn.cursor()
    register_or_update_device(cur, "dev-54", 54, "/pool/data")
    register_or_update_device(cur, "zfs-data", 54, "/pool/data")
    rows = cur.execute("SELECT fs_uuid, device_id FROM devices").fetchall()
    assert [tuple(r) for r in rows] == [("zfs-data", 54)]
    conn.close()


@patch("hashall.fs_utils.get_zfs_metadata", return_value={})
@patch("hashall.device._get_fs_type", return_value="zfs")
def test_unstable_newcomer_cannot_displace_stable_identity(_fs_type, _zfs, tmp_path):
    conn = connect_db(tmp_path / "catalog.db")
    cur = conn.cursor()
    register_or_update_device(cur, "zfs-home", 54, "/stash/home/michael")
    with pytest.raises(FilesystemIdentityError):
        register_or_update_device(cur, "dev-54", 54, "/pool/backup/secrets")
    conn.close()


def test_stale_compat_view_does_not_resolve_to_other_filesystem(tmp_path):
    """files_54 -> michael's table while device 54 is secrets (live catalog state)."""
    conn = connect_db(tmp_path / "catalog.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, files_table) "
        "VALUES ('zfs-home', 69, '/stash/home/michael', '/stash/home/michael', ?)",
        (files_table_name_for_fs_uuid("zfs-home"),),
    )
    cur.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, files_table) "
        "VALUES ('zfs-secrets', 54, '/pool/backup/secrets', '/pool/backup/secrets', ?)",
        (files_table_name_for_fs_uuid("zfs-secrets"),),
    )
    get_files_table_name(cur, fs_uuid="zfs-home", create=True)
    home_table = files_table_name_for_fs_uuid("zfs-home")
    cur.execute(f'INSERT INTO "{home_table}" (path, size, mtime, inode) VALUES (?, 1, 1.0, 1)', ("doc.txt",))
    cur.execute(f'CREATE VIEW files_54 AS SELECT * FROM "{home_table}"')
    conn.commit()
    assert get_files_table_name(cur, device_id=54) is None
    assert load_existing_files(cur, 54, Path("/pool/backup/secrets")) == {}
    conn.close()


def test_scan_refuses_misbound_files_table(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    _make_tree(root, n=2)
    fs_uuid = get_filesystem_uuid(str(root))
    mount = get_mount_point(str(root))
    conn = connect_db(db)
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, files_table) "
        "VALUES (?, ?, ?, ?, 'files_fs_zfs_someone_else')",
        (fs_uuid, os.stat(root).st_dev, mount, mount),
    )
    conn.commit()
    conn.close()
    with pytest.raises(FilesystemIdentityError):
        scan_path(db_path=db, root_path=root, quiet=True)
    assert _sessions(db) == []


def test_scan_refuses_preferred_mount_on_other_live_filesystem(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    _make_tree(root, n=2)
    fs_uuid = get_filesystem_uuid(str(root))
    mount = get_mount_point(str(root))
    if os.stat("/proc").st_dev == os.stat(root).st_dev:
        pytest.skip("/proc unexpectedly on same device")
    conn = connect_db(db)
    conn.execute(
        "INSERT INTO devices (fs_uuid, device_id, mount_point, preferred_mount_point, files_table) "
        "VALUES (?, ?, ?, '/proc', ?)",
        (fs_uuid, os.stat(root).st_dev, mount, files_table_name_for_fs_uuid(fs_uuid)),
    )
    conn.commit()
    conn.close()
    with pytest.raises(FilesystemIdentityError):
        scan_path(db_path=db, root_path=root, quiet=True)
    assert _sessions(db) == []


# ------------------------------------------- liveness repair

def test_liveness_repair_dry_run_then_apply(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root)
    scan_path(db_path=db, root_path=root, quiet=True)
    table, mount = _table_and_mount(db, root)
    rel = {p: str(p.relative_to(mount)) for p in files}
    conn = sqlite3.connect(db)
    conn.executemany(f'UPDATE "{table}" SET status = \'deleted\' WHERE path = ?', [(rel[p],) for p in files[:6]])
    conn.execute(f'CREATE VIEW files_99999 AS SELECT * FROM "{table}"')
    conn.commit()
    conn.close()
    files[0].unlink()  # genuinely absent
    files[1].write_text("changed size and content\n" * 50)  # size changed
    os.utime(files[2], (1, 1))  # mtime changed

    dry = run_liveness_repair(db, root, manifest_path=tmp_path / "dry.tsv")
    assert dry.candidates == 6
    assert dry.buckets["verified_live"] == 3
    assert dry.buckets["absent"] == 1
    assert dry.buckets["size_changed"] == 1
    assert dry.buckets["mtime_changed"] == 1
    assert dry.reactivated == 0
    assert dry.misbound_views == ["files_99999"]
    assert _statuses(db, root)[str(files[3])] == "deleted"  # dry run wrote nothing

    with pytest.raises(Exception):
        run_liveness_repair(db, root, apply_mode=True)  # backup is mandatory

    applied = run_liveness_repair(
        db, root, apply_mode=True, backup_dir=tmp_path / "bk",
        manifest_path=tmp_path / "apply.tsv", drop_misbound_views=True,
    )
    assert applied.reactivated == 3
    assert applied.backup_check == "ok" and Path(applied.backup_path).exists()
    assert applied.quick_check == "ok"
    assert applied.dropped_views == ["files_99999"]
    statuses = _statuses(db, root)
    for p in files[3:6]:
        assert statuses[str(p)] == "active"
    for p in files[:3]:
        assert statuses[str(p)] == "deleted"
    assert applied.after.get("deleted") == 3
    manifest = (tmp_path / "apply.tsv").read_text().splitlines()
    assert sum(1 for line in manifest if line.startswith("reactivate\t")) == 3
    # Backup preserves the pre-repair state for exact rollback.
    bk = sqlite3.connect(applied.backup_path)
    assert bk.execute(f'SELECT status FROM "{table}" WHERE path = ?', (rel[files[3]],)).fetchone()[0] == "deleted"
    bk.close()


# ------------------------------------------- targeted SHA-256

def test_targeted_sha256_backfill_reuse_and_staleness(tmp_path):
    db = tmp_path / "catalog.db"
    root = tmp_path / "home"
    files = _make_tree(root, n=4)
    twin = root / "axb" / "twin.txt"
    twin.write_bytes(files[0].read_bytes())
    scan_path(db_path=db, root_path=root, quiet=True)  # fast mode: no sha256 stored
    expected = hashlib.sha256(files[0].read_bytes()).hexdigest()

    # Quick-hash-only rows are never reported as SHA-256 proof.
    cached = hash_selected_files(db, [files[0]], cached_only=True)
    assert cached.results[0].status == NOT_HASHED and not cached.results[0].proven

    first = hash_selected_files(db, [files[0], twin])
    assert [r.status for r in first.results] == [SHA256_COMPUTED, SHA256_COMPUTED]
    assert first.results[0].sha256 == expected and first.results[0].written >= 1
    assert first.groups() == {expected: [str(files[0]), str(twin)]}

    second = hash_selected_files(db, [files[0]])
    assert second.results[0].status == SHA256_CATALOGED
    assert second.bytes_hashed == 0

    files[0].write_text("new content\n")
    third = hash_selected_files(db, [files[0]])
    assert third.results[0].catalog == "stale"
    assert third.results[0].status == SHA256_COMPUTED and third.results[0].written == 0
    table, mount = _table_and_mount(db, root)
    conn = sqlite3.connect(db)
    stored = conn.execute(f'SELECT sha256 FROM "{table}" WHERE path = ?', (str(files[0].relative_to(mount)),)).fetchone()[0]
    conn.close()
    assert stored == expected  # stale row keeps its hash until a rescan updates metadata

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x" * 10)
    other = hash_selected_files(db, [outside], write=False)
    assert other.results[0].status == SHA256_COMPUTED
    assert other.results[0].catalog in {"absent", "uncataloged"} and other.results[0].written == 0
