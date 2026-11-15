"""Regression tests: catalog table lookups must verify filesystem identity.

Kernel st_dev values are reused across ZFS datasets (issue #12). Every path
that reads a files table to act on files, or writes hashes/inodes back, must
resolve the table from the live filesystem (fs_uuid), not from a bare
device_id, and must fail closed when identity cannot be verified.

The fixture fakes filesystem identity per subtree so one temp filesystem can
model several datasets that share one kernel st_dev.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hashall.device import (
    FilesystemIdentityError,
    files_table_name_for_fs_uuid,
    get_files_table_name,
    resolve_verified_files_table,
)
from hashall.link_executor import execute_plan
from hashall.model import connect_db
from hashall.orphan_sweep import validate_orphan_hardlinks
from hashall.payload import build_payload, upgrade_payload_missing_sha256
from hashall.scan import upgrade_quick_hash_collisions
from hashall.sha256_migration import backfill_sha256, verify_sha256

FS_A = "zfs-111"  # registered, mounted at <tmp>/fs_a
FS_B = "zfs-222"  # live at <tmp>/fs_b and <tmp>/fs_a/nested, never registered
FS_STALE = "zfs-444"  # registered at <tmp>/fs_b, but fs_b is live FS_B
FS_MISBOUND = "zfs-555"  # registered, owns zfs-777's table (device 48 shape, #14)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    fs_a = tmp_path / "fs_a"
    fs_b = tmp_path / "fs_b"
    nested = fs_a / "nested"
    for p in (fs_a, fs_b, nested):
        p.mkdir(parents=True)

    def fake_fs_uuid(path: str) -> str:
        p = os.path.abspath(str(path))
        if p == str(nested) or p.startswith(str(nested) + os.sep):
            return FS_B
        if p == str(fs_a) or p.startswith(str(fs_a) + os.sep):
            return FS_A
        if p == str(fs_b) or p.startswith(str(fs_b) + os.sep):
            return FS_B
        return "zfs-999"

    monkeypatch.setattr("hashall.fs_utils.get_filesystem_uuid", fake_fs_uuid)

    live_dev = os.stat(tmp_path).st_dev
    db = tmp_path / "catalog.db"
    conn = connect_db(db)
    cur = conn.cursor()
    rows = [
        # FS_A holds the live st_dev, exactly like a reused kernel id.
        (FS_A, live_dev, fs_a),
        (FS_STALE, 60, fs_b),
        (FS_MISBOUND, 61, tmp_path / "fs_c"),
    ]
    for fs_uuid, dev, mount in rows:
        cur.execute(
            "INSERT INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point) "
            "VALUES (?, ?, ?, ?, ?)",
            (fs_uuid, dev, fs_uuid, str(mount), str(mount)),
        )
        if fs_uuid == FS_MISBOUND:
            # Device 48 shape (#14): the row owns the table of a filesystem
            # that has no devices row of its own.
            cur.execute(
                "UPDATE devices SET files_table = ? WHERE fs_uuid = ?",
                (files_table_name_for_fs_uuid("zfs-777"), fs_uuid),
            )
        get_files_table_name(cur, fs_uuid=fs_uuid, create=True)
    conn.commit()
    conn.close()
    return {
        "db": db,
        "fs_a": fs_a,
        "fs_b": fs_b,
        "nested": nested,
        "live_dev": live_dev,
        "table_a": files_table_name_for_fs_uuid(FS_A),
        "table_stale": files_table_name_for_fs_uuid(FS_STALE),
    }


def _insert_file(db: Path, table: str, rel: str, path: Path, *, sha256=None, quick_hash=None) -> None:
    st = path.stat()
    conn = connect_db(db)
    conn.execute(
        f'INSERT INTO "{table}" (path, size, mtime, inode, quick_hash, sha256, status) '
        "VALUES (?, ?, ?, ?, ?, ?, 'active')",
        (rel, st.st_size, st.st_mtime, st.st_ino, quick_hash, sha256),
    )
    conn.commit()
    conn.close()


def _sha256_values(db: Path, table: str) -> list:
    conn = connect_db(db)
    try:
        return [r[0] for r in conn.execute(f'SELECT sha256 FROM "{table}" ORDER BY path')]
    finally:
        conn.close()


# ------------------------------------------------------------- resolver

def test_resolver_accepts_verified_row(catalog):
    conn = connect_db(catalog["db"])
    verified = resolve_verified_files_table(conn.cursor(), device_id=catalog["live_dev"])
    assert verified.fs_uuid == FS_A
    assert verified.files_table == catalog["table_a"]
    assert verified.base == str(catalog["fs_a"])
    by_path = resolve_verified_files_table(conn.cursor(), live_path=str(catalog["fs_a"] / "x"))
    assert by_path.files_table == catalog["table_a"]
    conn.close()


@pytest.mark.parametrize(
    "kwargs_factory",
    [
        pytest.param(lambda c: {"device_id": 60}, id="registered-mount-is-other-live-fs"),
        pytest.param(lambda c: {"fs_uuid": FS_MISBOUND}, id="files-table-owned-by-other-fs"),
        pytest.param(lambda c: {"live_path": str(c["fs_b"])}, id="live-fs-unregistered"),
        pytest.param(lambda c: {"live_path": str(c["nested"])}, id="nested-dataset-same-st_dev"),
        pytest.param(
            lambda c: {"live_path": str(c["fs_a"]), "fs_uuid": FS_STALE}, id="live-path-not-that-fs"
        ),
        pytest.param(lambda c: {"device_id": 12345}, id="unknown-device-id"),
    ],
)
def test_resolver_fails_closed(catalog, kwargs_factory):
    conn = connect_db(catalog["db"])
    with pytest.raises(FilesystemIdentityError):
        resolve_verified_files_table(conn.cursor(), **kwargs_factory(catalog))
    conn.close()


# --------------------------------------------- sha256-backfill / verify

def test_sha256_backfill_skips_device_whose_mount_is_another_filesystem(catalog):
    good = catalog["fs_a"] / "good.bin"
    good.write_bytes(b"a" * 100)
    _insert_file(catalog["db"], catalog["table_a"], "good.bin", good)
    other = catalog["fs_b"] / "other.bin"
    other.write_bytes(b"b" * 100)
    _insert_file(catalog["db"], catalog["table_stale"], "other.bin", other)

    backfill_sha256(catalog["db"])

    assert all(_sha256_values(catalog["db"], catalog["table_a"]))
    assert _sha256_values(catalog["db"], catalog["table_stale"]) == [None]


def test_sha256_verify_does_not_create_or_adopt_tables(catalog, capsys):
    conn = connect_db(catalog["db"])
    before = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    conn.close()
    verify_sha256(catalog["db"])
    conn = connect_db(catalog["db"])
    after = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    conn.close()
    assert before == after
    out = capsys.readouterr().out
    assert "filesystem identity check failed" in out


# ------------------------------------------------- dupes collision upgrade

def test_collision_upgrade_refuses_stale_mount(catalog):
    for name in ("x.bin", "y.bin"):
        path = catalog["fs_b"] / name
        path.write_bytes(name.encode() * 10)
        _insert_file(catalog["db"], catalog["table_stale"], name, path, quick_hash="q1")

    assert upgrade_quick_hash_collisions(60, catalog["db"], quiet=True) == 0
    assert _sha256_values(catalog["db"], catalog["table_stale"]) == [None, None]


# ------------------------------------------------------------- payload

def test_payload_upgrade_resolves_from_live_path_not_device_id(catalog):
    payload = catalog["fs_a"] / "payload"
    payload.mkdir()
    f = payload / "a.bin"
    f.write_bytes(b"z" * 64)
    _insert_file(catalog["db"], catalog["table_a"], "payload/a.bin", f)

    conn = connect_db(catalog["db"])
    # device_id 60 is the stale row; the live path is FS_A.
    assert upgrade_payload_missing_sha256(conn, str(payload), device_id=60) == 1
    conn.close()
    assert all(_sha256_values(catalog["db"], catalog["table_a"]))


def test_payload_upgrade_refuses_unregistered_live_filesystem(catalog):
    payload = catalog["nested"] / "payload"
    payload.mkdir()
    f = payload / "a.bin"
    f.write_bytes(b"n" * 64)
    # Stale FS_A rows under the nested dataset's path (same kernel st_dev).
    _insert_file(catalog["db"], catalog["table_a"], "nested/payload/a.bin", f)

    conn = connect_db(catalog["db"])
    assert upgrade_payload_missing_sha256(conn, str(payload), device_id=catalog["live_dev"]) == 0
    conn.close()
    assert _sha256_values(catalog["db"], catalog["table_a"]) == [None]


def test_build_payload_does_not_read_other_dataset_by_st_dev(catalog):
    payload = catalog["nested"] / "payload"
    payload.mkdir()
    f = payload / "a.bin"
    f.write_bytes(b"n" * 64)
    _insert_file(catalog["db"], catalog["table_a"], "nested/payload/a.bin", f, sha256="ab" * 32)

    conn = connect_db(catalog["db"])
    # already_canonical: temp dirs are not real mountpoints (see below).
    result = build_payload(conn, str(payload), already_canonical=True)
    conn.close()
    assert result.status == "incomplete"
    assert result.payload_hash is None
    assert result.file_count == 0


def test_build_payload_maps_live_filesystem_to_registered_row(catalog):
    payload = catalog["fs_a"] / "payload"
    payload.mkdir()
    f = payload / "a.bin"
    f.write_bytes(b"k" * 64)
    _insert_file(catalog["db"], catalog["table_a"], "payload/a.bin", f, sha256="cd" * 32)

    conn = connect_db(catalog["db"])
    # Hand the live kernel slot to the stale row, as after a reboot: a st_dev
    # lookup now lands on FS_STALE's (empty) table.
    conn.execute("UPDATE devices SET device_id = 70 WHERE fs_uuid = ?", (FS_A,))
    conn.execute("UPDATE devices SET device_id = ? WHERE fs_uuid = ?", (catalog["live_dev"], FS_STALE))
    conn.commit()
    # already_canonical: temp dirs are not real mountpoints, so skip mount-alias
    # remapping, which is unrelated to identity resolution.
    result = build_payload(conn, str(payload), already_canonical=True)
    conn.close()
    assert result.status == "complete"
    assert result.device_id == 70
    assert result.fs_uuid == FS_A
    assert result.file_count == 1


# ----------------------------------------------------------- link execute

def _insert_plan(db: Path, *, device_id: int, mount: Path, canonical: Path, duplicate: Path) -> int:
    conn = connect_db(db)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO link_plans (name, status, device_id, mount_point, total_opportunities, "
        "total_bytes_saveable, actions_total) VALUES ('p', 'pending', ?, ?, 1, 10, 1)",
        (device_id, str(mount)),
    )
    plan_id = cur.lastrowid
    cur.execute(
        "INSERT INTO link_actions (plan_id, action_type, status, canonical_path, duplicate_path, "
        "canonical_inode, duplicate_inode, device_id, file_size, bytes_to_save) "
        "VALUES (?, 'HARDLINK', 'pending', ?, ?, ?, ?, ?, ?, ?)",
        (
            plan_id,
            canonical.name,
            duplicate.name,
            canonical.stat().st_ino,
            duplicate.stat().st_ino,
            device_id,
            canonical.stat().st_size,
            canonical.stat().st_size,
        ),
    )
    conn.commit()
    conn.close()
    return plan_id


@pytest.mark.parametrize("dry_run", [True, False])
def test_link_execute_refuses_unverified_catalog(catalog, dry_run):
    canonical = catalog["fs_b"] / "c.bin"
    duplicate = catalog["fs_b"] / "d.bin"
    canonical.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    # Stored device_id is FS_A's live slot; the plan's mount is FS_B.
    plan_id = _insert_plan(
        catalog["db"], device_id=catalog["live_dev"], mount=catalog["fs_b"],
        canonical=canonical, duplicate=duplicate,
    )
    conn = connect_db(catalog["db"])
    with pytest.raises(FilesystemIdentityError):
        execute_plan(conn, plan_id, dry_run=dry_run, verify_mode="fast", use_jdupes=False,
                     create_backup=False)
    conn.close()
    assert canonical.stat().st_ino != duplicate.stat().st_ino


def test_link_execute_verifies_against_live_filesystem_table(catalog):
    canonical = catalog["fs_a"] / "c.bin"
    duplicate = catalog["fs_a"] / "d.bin"
    canonical.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    for p in (canonical, duplicate):
        _insert_file(catalog["db"], catalog["table_a"], p.name, p)
    # Stored device_id is stale (60); resolution follows the live mount.
    plan_id = _insert_plan(
        catalog["db"], device_id=60, mount=catalog["fs_a"],
        canonical=canonical, duplicate=duplicate,
    )
    conn = connect_db(catalog["db"])
    result = execute_plan(conn, plan_id, dry_run=True, verify_mode="fast", use_jdupes=False,
                          create_backup=False)
    conn.close()
    assert result.actions_failed == 0, result.errors
    assert result.actions_executed == 1


# ---------------------------------------------------------- orphan validate

def test_orphan_validate_fails_closed_without_verified_catalog(catalog):
    orphan_dir = catalog["nested"] / "orphaned_data"
    orphan_dir.mkdir()
    orphan = orphan_dir / "o.bin"
    orphan.write_bytes(b"seeded")
    seeding = catalog["nested"] / "seeding.bin"
    os.link(orphan, seeding)

    conn = connect_db(catalog["db"])
    # FS_A owns the live st_dev, and its table has no row for this inode. The
    # old st_dev lookup read FS_A's table, found no external link and called
    # the seeded file safe to move.
    safe, skipped = validate_orphan_hardlinks(str(orphan_dir), conn)
    conn.close()
    assert safe == []
    assert [s["path"] for s in skipped] == [str(orphan)]



# ------------------------------------------- review follow-ups (PR #15 G1/G2)

def test_resolver_refuses_live_path_when_registered_mount_is_other_fs(catalog):
    conn = connect_db(catalog["db"])
    conn.execute(
        "UPDATE devices SET preferred_mount_point = ? WHERE fs_uuid = ?",
        (str(catalog["fs_b"]), FS_A),
    )
    with pytest.raises(FilesystemIdentityError):
        resolve_verified_files_table(conn.cursor(), live_path=str(catalog["fs_a"]))
    conn.close()


def test_payload_upgrade_never_hashes_under_a_foreign_preferred_mount(catalog):
    for fs, data in ((catalog["fs_a"], b"A" * 64), (catalog["fs_b"], b"B" * 64)):
        (fs / "payload").mkdir()
        (fs / "payload" / "a.bin").write_bytes(data)
    _insert_file(catalog["db"], catalog["table_a"], "payload/a.bin", catalog["fs_a"] / "payload" / "a.bin")
    conn = connect_db(catalog["db"])
    conn.execute(
        "UPDATE devices SET preferred_mount_point = ? WHERE fs_uuid = ?",
        (str(catalog["fs_b"]), FS_A),
    )
    conn.commit()
    assert upgrade_payload_missing_sha256(conn, str(catalog["fs_a"] / "payload")) == 0
    conn.close()
    assert _sha256_values(catalog["db"], catalog["table_a"]) == [None]


def test_build_payload_ignores_stored_device_id_of_other_filesystem(catalog):
    payload = catalog["fs_a"] / "payload"
    payload.mkdir()
    f = payload / "a.bin"
    f.write_bytes(b"k" * 64)
    _insert_file(catalog["db"], catalog["table_a"], "payload/a.bin", f, sha256="cd" * 32)
    conn = connect_db(catalog["db"])
    # payload upgrade-collisions passes stored payloads.device_id; 61 is the
    # misbound row. The live root is FS_A, so FS_A's row is used.
    result = build_payload(conn, str(payload), device_id=61, already_canonical=True)
    assert result.status == "complete"
    assert result.fs_uuid == FS_A
    assert result.device_id == catalog["live_dev"]
    # A nested dataset sharing the st_dev: an explicit st_dev is not trusted.
    nested = catalog["nested"] / "payload"
    nested.mkdir()
    (nested / "n.bin").write_bytes(b"n" * 8)
    _insert_file(catalog["db"], catalog["table_a"], "nested/payload/n.bin", nested / "n.bin", sha256="ef" * 32)
    result = build_payload(conn, str(nested), device_id=catalog["live_dev"], already_canonical=True)
    assert result.status == "incomplete"
    assert result.file_count == 0
    conn.close()


def test_build_payload_missing_root_verifies_passed_device_id(catalog):
    conn = connect_db(catalog["db"])
    missing = catalog["fs_b"] / "gone"
    result = build_payload(conn, str(missing), device_id=60, already_canonical=True)
    assert result.status == "incomplete"
    assert result.device_id is None
    conn.close()


def test_link_execute_refuses_recorded_but_missing_mount(catalog):
    canonical = catalog["fs_a"] / "c.bin"
    duplicate = catalog["fs_a"] / "d.bin"
    canonical.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    plan_id = _insert_plan(
        catalog["db"], device_id=catalog["live_dev"], mount=catalog["fs_a"] / "missing",
        canonical=canonical, duplicate=duplicate,
    )
    conn = connect_db(catalog["db"])
    with pytest.raises(FilesystemIdentityError):
        execute_plan(conn, plan_id, dry_run=True, verify_mode="fast", use_jdupes=False,
                     create_backup=False)
    conn.close()


def test_link_execute_cli_refuses_before_fix_perms(catalog, monkeypatch):
    from click.testing import CliRunner

    import hashall.cli as cli_mod

    canonical = catalog["fs_b"] / "c.bin"
    duplicate = catalog["fs_b"] / "d.bin"
    canonical.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    plan_id = _insert_plan(
        catalog["db"], device_id=catalog["live_dev"], mount=catalog["fs_b"],
        canonical=canonical, duplicate=duplicate,
    )
    calls = []
    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: calls.append(a))
    result = CliRunner().invoke(
        cli_mod.cli,
        ["link", "execute", str(plan_id), "--db", str(catalog["db"]), "--yes",
         "--no-jdupes", "--no-backup"],
    )
    assert result.exit_code == 1
    assert "Filesystem identity check failed" in result.output
    assert "Traceback" not in result.output
    # Read-only `zfs list` dataset discovery may run; nothing that mutates.
    mutating = [c for c in calls if any(t in str(c) for t in ("sudo", "chmod", "chown", "setfacl", "snapshot"))]
    assert mutating == []
