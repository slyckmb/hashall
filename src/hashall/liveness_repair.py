"""Bounded, reversible repair of false 'deleted' liveness rows (issue #12).

Reactivates tombstoned catalog rows under ONE scan root only when the live file
proves the row is current:

- the root's live fs_uuid has a correctly bound devices row and files table
  (verify_registered_identity; misbound registrations are refused);
- the path exists, is a regular file, and lives on the root's filesystem
  (st_dev equals the root's st_dev; nested datasets/other devices excluded);
- size and mtime equal the row exactly (the incremental scanner's trust model),
  so the row's existing hashes remain valid and nothing is rehashed.

Rows that fail any predicate are left 'deleted' and reported by bucket.
Dry-run by default. Apply requires a verified sqlite backup first and writes a
TSV manifest of every evaluated row so the change can be reverted exactly.
"""

from __future__ import annotations

import json
import os
import stat as stat_mod
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hashall.device import (
    _drop_compat_view,
    _view_target,
    files_table_matches_fs,
    resolve_current_device_row,
    verify_registered_identity,
)
from hashall.fs_utils import get_filesystem_uuid, get_mount_point
from hashall.model import connect_db
from hashall.pathing import canonicalize_path

BUCKETS = (
    "verified_live",  # regular, same fs, size+mtime equal -> reactivate
    "absent",
    "non_regular",
    "other_device",
    "size_changed",
    "mtime_changed",
    "stat_error",
)


@dataclass
class LivenessRepairResult:
    generated_at: str
    db_path: str
    root: str
    fs_uuid: str
    device_id: int
    files_table: str
    rel_root: str
    apply_mode: bool
    candidates: int = 0
    buckets: dict = field(default_factory=lambda: {b: 0 for b in BUCKETS})
    inode_changed: int = 0  # subset of verified_live whose inode differs (restored copy)
    reactivated: int = 0
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    misbound_views: list = field(default_factory=list)
    dropped_views: list = field(default_factory=list)
    misattributed_scan_roots: list = field(default_factory=list)
    backup_path: Optional[str] = None
    backup_check: Optional[str] = None
    quick_check: Optional[str] = None
    manifest_path: Optional[str] = None
    samples: dict = field(default_factory=dict)

    def summary_line(self) -> str:
        parts = [
            f"root={self.root}",
            f"fs_uuid={self.fs_uuid}",
            f"table={self.files_table}",
            f"apply={str(self.apply_mode).lower()}",
            f"candidates={self.candidates}",
        ]
        parts += [f"{name}={self.buckets.get(name, 0)}" for name in BUCKETS]
        parts += [
            f"inode_changed={self.inode_changed}",
            f"reactivated={self.reactivated}",
            f"active_before={self.before.get('active', 0)}",
            f"deleted_before={self.before.get('deleted', 0)}",
            f"active_after={self.after.get('active', 0)}",
            f"deleted_after={self.after.get('deleted', 0)}",
            f"misbound_views={len(self.misbound_views)}",
            f"dropped_views={len(self.dropped_views)}",
            f"quick_check={self.quick_check or 'n/a'}",
        ]
        return "liveness_repair " + " ".join(parts)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


class LivenessRepairError(RuntimeError):
    pass


def _status_counts(conn: sqlite3.Connection, table: str, rel_root: str) -> dict:
    where, params = _scope_clause(rel_root)
    rows = conn.execute(
        f'SELECT status, COUNT(*) FROM "{table}" WHERE {where} GROUP BY status', params
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _scope_clause(rel_root: str) -> tuple[str, tuple]:
    if rel_root in ("", "."):
        return "1=1", ()
    prefix = f"{rel_root}/"
    return "(path = ? OR substr(path, 1, ?) = ?)", (rel_root, len(prefix), prefix)


def backup_database(db_path: Path, backup_dir: Path) -> tuple[Path, str]:
    """Consistent online copy via the sqlite backup API, then quick_check it."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"catalog-pre-liveness-repair-{stamp}.sqlite"
    src = sqlite3.connect(str(db_path), timeout=60)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check_conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        check = str(check_conn.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        check_conn.close()
    return target, check


def _misbound_views(conn: sqlite3.Connection, table: str, fs_uuid: str) -> list[str]:
    """files_<id> views targeting ``table`` whose device_id slot is not this filesystem."""
    out = []
    owners = {int(r[0]): str(r[1]) for r in conn.execute("SELECT device_id, fs_uuid FROM devices")}
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'files\\_%' ESCAPE '\\'"
    ).fetchall():
        suffix = name[len("files_"):]
        if not suffix.lstrip("-").isdigit():
            continue
        if _view_target(conn.cursor(), name) != table:
            continue
        if owners.get(int(suffix)) != fs_uuid:
            out.append(name)
    return out


def run_liveness_repair(
    db_path: Path,
    root: Path,
    *,
    apply_mode: bool = False,
    backup_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    drop_misbound_views: bool = False,
    sample_limit: int = 10,
) -> LivenessRepairResult:
    root_real = canonicalize_path(Path(os.path.realpath(root)))
    try:
        root_st = os.stat(root_real)
    except OSError as exc:
        raise LivenessRepairError(f"Cannot stat root {root_real}: {exc}") from exc
    fs_uuid = get_filesystem_uuid(str(root_real))
    mount_now = get_mount_point(str(root_real)) or str(root_real)

    # Dry-run opens read-only (no migrations, no writes of any kind).
    conn = connect_db(Path(db_path), read_only=not apply_mode)
    try:
        cursor = conn.cursor()
        row = resolve_current_device_row(cursor, fs_uuid=fs_uuid)
        if row is None:
            raise LivenessRepairError(f"No devices row for live fs_uuid {fs_uuid} ({root_real})")
        # Raises FilesystemIdentityError on a misbound registration.
        verify_registered_identity(cursor, fs_uuid=fs_uuid, device_id=root_st.st_dev, current_mount=mount_now)
        table = str(row[5] or "").strip()
        if not table or not files_table_matches_fs(table, fs_uuid):
            raise LivenessRepairError(f"files_table {table!r} is not bound to {fs_uuid}")
        if not cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            raise LivenessRepairError(f"files table {table} does not exist")

        base = None
        for candidate in (row[4], row[3], mount_now):
            if not candidate:
                continue
            try:
                root_real.relative_to(Path(str(candidate)))
            except ValueError:
                continue
            try:
                if os.stat(str(candidate)).st_dev == root_st.st_dev:
                    base = Path(str(candidate))
                    break
            except OSError:
                continue
        if base is None:
            raise LivenessRepairError(
                f"Root {root_real} is not under a registered mount of {fs_uuid} on this filesystem"
            )
        rel_root = str(root_real.relative_to(base))

        result = LivenessRepairResult(
            generated_at=datetime.now(timezone.utc).isoformat(),
            db_path=str(db_path),
            root=str(root_real),
            fs_uuid=fs_uuid,
            device_id=int(root_st.st_dev),
            files_table=table,
            rel_root=rel_root,
            apply_mode=apply_mode,
        )
        result.before = _status_counts(conn, table, rel_root)
        result.misbound_views = _misbound_views(conn, table, fs_uuid)
        result.misattributed_scan_roots = [
            {"fs_uuid": str(r[0]), "root_path": str(r[1])}
            for r in conn.execute(
                "SELECT fs_uuid, root_path FROM scan_roots WHERE root_path = ? AND fs_uuid != ?",
                (str(root_real), fs_uuid),
            )
        ]

        where, params = _scope_clause(rel_root)
        rows = conn.execute(
            f'SELECT path, size, mtime, inode FROM "{table}" WHERE status = ? AND {where} ORDER BY path',
            ("deleted", *params),
        ).fetchall()
        result.candidates = len(rows)

        verified: list[tuple] = []  # (path, size, mtime, old_inode, new_inode)
        manifest_rows: list[tuple] = []
        samples: dict[str, list[str]] = {}
        for path, size, mtime, inode in rows:
            abs_path = base / path
            new_inode = ""
            try:
                st = os.lstat(abs_path)
            except FileNotFoundError:
                bucket = "absent"
            except OSError:
                bucket = "stat_error"
            else:
                new_inode = st.st_ino
                if not stat_mod.S_ISREG(st.st_mode):
                    bucket = "non_regular"
                elif st.st_dev != root_st.st_dev:
                    bucket = "other_device"
                elif st.st_size != size:
                    bucket = "size_changed"
                elif abs(st.st_mtime - float(mtime or 0.0)) >= 0.001:
                    bucket = "mtime_changed"
                else:
                    bucket = "verified_live"
                    if inode != st.st_ino:
                        result.inode_changed += 1
                    verified.append((path, size, mtime, inode, st.st_ino))
            result.buckets[bucket] += 1
            bucket_samples = samples.setdefault(bucket, [])
            if len(bucket_samples) < sample_limit:
                bucket_samples.append(path)
            action = "reactivate" if bucket == "verified_live" else "keep-deleted"
            manifest_rows.append((action, bucket, path, size, mtime, inode, new_inode))
        result.samples = samples

        if manifest_path is not None:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8") as fh:
                fh.write(f"# liveness_repair table={table} fs_uuid={fs_uuid} root={root_real}\n")
                fh.write("# revert: UPDATE <table> SET status='deleted', inode=<old_inode> WHERE path=<path> for action=reactivate\n")
                fh.write("action\tbucket\tpath\tsize\tmtime\told_inode\tnew_inode\n")
                for rec in manifest_rows:
                    fh.write("\t".join(str(v) for v in rec) + "\n")
            result.manifest_path = str(manifest_path)

        if not apply_mode:
            result.after = dict(result.before)
            return result

        if backup_dir is None:
            raise LivenessRepairError("Refusing to apply without --backup-dir")
        backup_path, backup_check = backup_database(Path(db_path), Path(backup_dir))
        result.backup_path, result.backup_check = str(backup_path), backup_check
        if backup_check != "ok":
            raise LivenessRepairError(f"Backup quick_check failed: {backup_check}")

        cursor.execute("BEGIN IMMEDIATE")
        try:
            for path, size, mtime, _old_inode, new_inode in verified:
                cursor.execute(
                    f'UPDATE "{table}" SET status = \'active\', inode = ?, last_seen_at = datetime(\'now\') '
                    "WHERE path = ? AND status = 'deleted' AND size = ? AND mtime = ?",
                    (new_inode, path, size, mtime),
                )
                result.reactivated += int(cursor.rowcount or 0)
            if drop_misbound_views:
                for view in result.misbound_views:
                    _drop_compat_view(cursor, int(view[len("files_"):]))
                    result.dropped_views.append(view)
            cursor.execute(
                f"""
                UPDATE devices SET
                    total_files = (SELECT COUNT(*) FROM "{table}" WHERE status = 'active'),
                    total_bytes = (SELECT COALESCE(SUM(size), 0) FROM "{table}" WHERE status = 'active'),
                    updated_at = datetime('now')
                WHERE fs_uuid = ?
                """,
                (fs_uuid,),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        result.after = _status_counts(conn, table, rel_root)
        result.quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        return result
    finally:
        conn.close()
