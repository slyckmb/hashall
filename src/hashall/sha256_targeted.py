"""Targeted, identity-verified SHA-256 lookup and backfill (issue #12).

Hashes only the files a caller names (e.g. archive-reconciliation candidates)
instead of requiring a global ``--hash-mode full`` refresh.

Evidence rules:
- A stored catalog SHA-256 is used only when the catalog row is active and the
  live file's size and mtime still match the row (the same trust model the
  incremental scanner uses). Otherwise the file is hashed now.
- A computed SHA-256 is written back only to an active, fresh row on the file's
  own filesystem table (resolved by live fs_uuid, never by transient device_id),
  and only if the file did not change while it was being hashed.
- Filename, size or quick-hash agreement is never reported as SHA-256 proof;
  every result carries an explicit ``status`` and ``proven`` flag.
"""

from __future__ import annotations

import json
import os
import stat as stat_mod
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from hashall.device import (
    FilesystemIdentityError,
    files_table_matches_fs,
    files_table_name_for_fs_uuid,
    resolve_current_device_row,
    verify_registered_identity,
)
from hashall.fs_utils import get_filesystem_uuid, get_mount_point
from hashall.model import connect_db
from hashall.scan import compute_full_hashes

# Result statuses. "sha256-*" statuses carry SHA-256 proof for the live file.
SHA256_CATALOGED = "sha256-cataloged"  # stored hash, row fresh (size+mtime unchanged)
SHA256_COMPUTED = "sha256-computed"  # hashed now from file content
SHA256_MISMATCH = "sha256-mismatch"  # --verify: content differs from stored hash
NOT_REGULAR = "not-regular"
MISSING = "missing"
CHANGED_DURING_HASH = "changed-during-hash"
SKIPPED_BUDGET = "skipped-budget"
NOT_HASHED = "not-hashed"  # --cached-only and no fresh stored hash
ERROR = "error"


@dataclass
class FileHashResult:
    path: str
    status: str
    sha256: Optional[str] = None
    size: Optional[int] = None
    catalog: str = "none"  # fresh | stale | deleted | absent | uncataloged | identity-mismatch
    fs_uuid: Optional[str] = None
    files_table: Optional[str] = None
    rel_path: Optional[str] = None
    written: int = 0  # catalog rows updated with this hash
    detail: str = ""

    @property
    def proven(self) -> bool:
        return self.sha256 is not None and self.status in {SHA256_CATALOGED, SHA256_COMPUTED}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["proven"] = self.proven
        return data


@dataclass
class TargetedSha256Summary:
    results: list[FileHashResult] = field(default_factory=list)
    bytes_hashed: int = 0

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for result in self.results:
            out[result.status] = out.get(result.status, 0) + 1
        return out

    def groups(self) -> dict[str, list[str]]:
        """Proven SHA-256 -> input paths, for comparing candidates."""
        out: dict[str, list[str]] = {}
        for result in self.results:
            if result.proven:
                out.setdefault(str(result.sha256), []).append(result.path)
        return out

    def summary_line(self) -> str:
        counts = self.counts()
        written = sum(r.written for r in self.results)
        proven = sum(1 for r in self.results if r.proven)
        groups = self.groups()
        parts = [
            f"total={len(self.results)}",
            f"proven={proven}",
            f"cataloged={counts.get(SHA256_CATALOGED, 0)}",
            f"computed={counts.get(SHA256_COMPUTED, 0)}",
            f"mismatch={counts.get(SHA256_MISMATCH, 0)}",
            f"unproven={len(self.results) - proven}",
            f"rows_written={written}",
            f"bytes_hashed={self.bytes_hashed}",
            f"distinct_sha256={len(groups)}",
        ]
        return "sha256_files " + " ".join(parts)


def _fresh(row_size, row_mtime, st: os.stat_result) -> bool:
    return row_size == st.st_size and abs(float(row_mtime or 0.0) - st.st_mtime) < 0.001


def _catalog_location(cursor: sqlite3.Cursor, real: Path, st: os.stat_result):
    """Resolve (fs_uuid, files_table, rel_path) for a live file, or a reason string."""
    fs_uuid = get_filesystem_uuid(str(real))
    row = resolve_current_device_row(cursor, fs_uuid=fs_uuid)
    if row is None:
        return fs_uuid, None, None, "uncataloged"
    mount_now = get_mount_point(str(real)) or str(row[3])
    try:
        verify_registered_identity(
            cursor, fs_uuid=fs_uuid, device_id=st.st_dev, current_mount=mount_now
        )
    except FilesystemIdentityError as exc:
        return fs_uuid, None, None, f"identity-mismatch: {exc}"
    table = str(row[5] or "").strip() or files_table_name_for_fs_uuid(fs_uuid)
    exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return fs_uuid, None, None, "uncataloged"
    # Relative path against a registered mount that is this live filesystem.
    for base in (row[4], row[3], mount_now):
        if not base:
            continue
        base_path = Path(str(base))
        try:
            rel = real.relative_to(base_path)
        except ValueError:
            continue
        try:
            if os.stat(base_path).st_dev != st.st_dev:
                continue
        except OSError:
            continue
        return fs_uuid, table, str(rel), ""
    return fs_uuid, table, None, "uncataloged"


def hash_selected_files(
    db_path: Path,
    paths: Iterable[str | Path],
    *,
    write: bool = True,
    verify: bool = False,
    cached_only: bool = False,
    max_bytes: Optional[int] = None,
) -> TargetedSha256Summary:
    """Return SHA-256 evidence for each selected path, backfilling the catalog.

    Args:
        db_path: catalog database
        paths: absolute or relative file paths to evaluate
        write: write computed hashes back to fresh active catalog rows
        verify: re-hash even when a fresh stored hash exists (report mismatches,
            never overwrite a differing stored hash)
        cached_only: never read file contents; report stored fresh hashes only
        max_bytes: stop hashing new content once this many bytes were read
    """
    conn = connect_db(Path(db_path), read_only=not write)
    cursor = conn.cursor()
    summary = TargetedSha256Summary()
    try:
        for raw in paths:
            summary.results.append(
                _hash_one(
                    conn, cursor, str(raw), summary,
                    write=write, verify=verify, cached_only=cached_only, max_bytes=max_bytes,
                )
            )
    finally:
        conn.close()
    return summary


def _hash_one(conn, cursor, raw: str, summary: TargetedSha256Summary, *, write, verify, cached_only, max_bytes):
    real = Path(os.path.realpath(raw))
    result = FileHashResult(path=str(real), status=ERROR)
    try:
        st = os.stat(real)
    except FileNotFoundError:
        result.status = MISSING
        return result
    except OSError as exc:
        result.detail = str(exc)
        return result
    if not stat_mod.S_ISREG(st.st_mode):
        result.status = NOT_REGULAR
        return result
    result.size = st.st_size

    fs_uuid, table, rel, reason = _catalog_location(cursor, real, st)
    result.fs_uuid, result.files_table, result.rel_path = fs_uuid, table, rel
    row = None
    if reason.startswith("identity-mismatch"):
        result.catalog = "identity-mismatch"
        result.detail = reason
        table = rel = None
    elif table and rel is not None:
        row = cursor.execute(
            f'SELECT size, mtime, sha256, status, inode FROM "{table}" WHERE path = ?', (rel,)
        ).fetchone()
        if row is None:
            result.catalog = "absent"
        elif row[3] != "active":
            result.catalog = "deleted"
        elif _fresh(row[0], row[1], st):
            result.catalog = "fresh"
        else:
            result.catalog = "stale"
    else:
        result.catalog = "uncataloged"

    stored = row[2] if (row is not None and result.catalog == "fresh") else None
    if stored and not verify:
        result.status, result.sha256 = SHA256_CATALOGED, stored
        return result
    if cached_only:
        result.status = NOT_HASHED
        result.detail = "no fresh stored SHA-256 (cached-only)"
        return result
    if max_bytes is not None and summary.bytes_hashed + st.st_size > max_bytes:
        result.status = SKIPPED_BUDGET
        return result

    try:
        sha1, sha256 = compute_full_hashes(real)
    except OSError as exc:
        result.detail = str(exc)
        return result
    summary.bytes_hashed += st.st_size
    try:
        after = os.stat(real)
    except OSError as exc:
        result.detail = str(exc)
        return result
    if (after.st_size, after.st_mtime_ns, after.st_ino) != (st.st_size, st.st_mtime_ns, st.st_ino):
        result.status = CHANGED_DURING_HASH
        return result

    if stored and stored != sha256:
        result.status, result.sha256 = SHA256_MISMATCH, sha256
        result.detail = f"stored={stored}"
        return result
    result.status, result.sha256 = SHA256_COMPUTED, sha256

    if write and not stored and result.catalog == "fresh" and table:
        result.written = _write_hash(conn, table, rel, st, sha1, sha256, catalog_inode=row[4])
    return result


def _write_hash(conn, table: str, rel: str, st: os.stat_result, sha1: str, sha256: str, *, catalog_inode) -> int:
    """Write sha256 to the row (and fresh hardlink siblings sharing its live inode)."""
    cur = conn.cursor()
    cur.execute(
        f'UPDATE "{table}" SET sha256 = ?, sha1 = COALESCE(sha1, ?), hash_source = ?, '
        "last_modified_at = datetime('now') "
        "WHERE path = ? AND status = 'active' AND sha256 IS NULL AND size = ? AND abs(mtime - ?) < 0.001",
        (sha256, sha1, "calculated", rel, st.st_size, st.st_mtime),
    )
    written = int(cur.rowcount or 0)
    if written and catalog_inode == st.st_ino:
        cur.execute(
            f'UPDATE "{table}" SET sha256 = ?, sha1 = COALESCE(sha1, ?), hash_source = ?, '
            "last_modified_at = datetime('now') "
            "WHERE inode = ? AND path != ? AND status = 'active' AND sha256 IS NULL "
            "AND size = ? AND abs(mtime - ?) < 0.001",
            (sha256, sha1, f"inode:{st.st_ino}", st.st_ino, rel, st.st_size, st.st_mtime),
        )
        written += int(cur.rowcount or 0)
    conn.commit()
    return written


def lookup_sha256(db_path: Path, hashes: Iterable[str], *, check_live: bool = True) -> list[dict]:
    """Find catalog rows carrying each SHA-256 across all registered files tables.

    Catalog rows are evidence of where content was when hashed; with
    ``check_live`` each hit is re-stat'ed and labelled live-unchanged /
    live-changed / absent so stale rows are never mistaken for proof.
    """
    wanted = [h.strip().lower() for h in hashes if h and h.strip()]
    conn = connect_db(Path(db_path), read_only=True)
    out: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT fs_uuid, mount_point, preferred_mount_point, files_table FROM devices "
            "WHERE files_table IS NOT NULL"
        ).fetchall()
        for fs_uuid, mount, preferred, table in rows:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists or not files_table_matches_fs(table, fs_uuid):
                continue  # skip missing or misbound tables
            base = Path(str(preferred or mount))
            for digest in wanted:
                for path, size, mtime, status in conn.execute(
                    f'SELECT path, size, mtime, status FROM "{table}" WHERE sha256 = ?', (digest,)
                ):
                    abs_path = base / path
                    live = "unchecked"
                    if check_live:
                        try:
                            st = os.stat(abs_path)
                            live = "live-unchanged" if _fresh(size, mtime, st) else "live-changed"
                        except OSError:
                            live = "absent"
                    out.append({
                        "sha256": digest, "path": str(abs_path), "size": size,
                        "catalog_status": status, "live": live, "fs_uuid": fs_uuid,
                    })
    finally:
        conn.close()
    return out


def results_to_json(summary: TargetedSha256Summary) -> str:
    return json.dumps(
        {"summary": summary.summary_line(), "results": [r.to_dict() for r in summary.results],
         "groups": summary.groups()},
        indent=2,
    )
