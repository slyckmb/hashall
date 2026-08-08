"""
Dry-run orphan dedupe classification for OP-61.

Separates SHA256-confirmed cross-device duplicates from quick-hash-only
candidates and unmatched orphans.  Produces a classification report only;
never modifies the database or filesystem.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from hashall.device import get_files_table_name
from hashall.link_analysis import analyze_cross_device, CrossDeviceDuplicateGroup
from hashall.model import connect_db

# Mirror payload constants so we don't re-import cli
_ORPHAN_GC_MIN_SEEN_RUNS = 2
_ORPHAN_GC_MIN_AGE_SECONDS = 86400


@dataclass
class OrphanFileEntry:
    payload_id: int
    root_path: str
    device_id: int
    file_path: str
    file_size: int
    sha256: Optional[str]
    quick_hash: Optional[str]
    inode: int
    link_count: int


@dataclass
class ClassifiedOrphan:
    payload_id: int
    root_path: str
    device_id: int
    file_path: str
    file_size: int
    hash_basis: str
    sha256: Optional[str]
    quick_hash: Optional[str]
    inode: int
    link_count: int
    classification: str  # sha256_confirmed | quick_hash_candidate | no_match
    match_device_ids: List[int] = field(default_factory=list)
    match_paths: List[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    candidates: List[ClassifiedOrphan] = field(default_factory=list)
    total_orphan_payloads: int = 0
    total_files: int = 0
    sha256_confirmed: int = 0
    sha256_confirmed_bytes: int = 0
    quick_hash_only: int = 0
    quick_hash_only_bytes: int = 0
    no_match: int = 0
    no_match_bytes: int = 0
    warnings: List[str] = field(default_factory=list)


def _find_orphan_payloads(
    conn: sqlite3.Connection,
    path_prefixes: Optional[List[str]] = None,
) -> List[Tuple[int, str, int]]:
    """Return (payload_id, root_path, device_id) for true orphan payloads."""
    rows = conn.execute(
        """
        SELECT p.payload_id, p.root_path, p.device_id
        FROM payloads p
        LEFT JOIN (
            SELECT payload_id, COUNT(*) AS ref_count
            FROM torrent_instances
            GROUP BY payload_id
        ) ti ON ti.payload_id = p.payload_id
        WHERE COALESCE(ti.ref_count, 0) = 0
        ORDER BY p.root_path
        """
    ).fetchall()

    if not path_prefixes:
        return [(int(r[0]), r[1], r[2]) for r in rows]

    def _under(path_str: str, prefix: str) -> bool:
        return path_str == prefix or path_str.startswith(prefix.rstrip("/") + "/")

    result: List[Tuple[int, str, int]] = []
    for row in rows:
        root_path = row[1]
        if any(_under(root_path, pfx) for pfx in path_prefixes):
            result.append((int(row[0]), root_path, row[2]))
    return result


def _resolve_device_path(
    conn: sqlite3.Connection,
    device_id: int,
    file_path: str,
) -> str:
    """Resolve a device-relative file path to an absolute path if possible."""
    row = conn.execute(
        "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if not row:
        return file_path
    mp, pmp = row
    resolved = pmp or mp
    if resolved:
        return str(Path(resolved) / file_path)
    return file_path


def _collect_orphan_files(
    conn: sqlite3.Connection,
    orphans: List[Tuple[int, str, int]],
) -> List[OrphanFileEntry]:
    """Collect active file metadata for each orphan payload."""
    entries: List[OrphanFileEntry] = []
    table_cache: Dict[int, str] = {}
    columns_cache: Dict[str, Set[str]] = {}
    mount_cache: Dict[int, Tuple[str, str]] = {}

    for payload_id, root_path, device_id in orphans:
        if device_id is None:
            continue
        did = int(device_id)
        if did not in table_cache:
            table_name = get_files_table_name(conn.cursor(), device_id=did)
            if not table_name:
                continue
            table_cache[did] = table_name
        table_name = table_cache[did]

        if did not in mount_cache:
            row = conn.execute(
                "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
                (did,),
            ).fetchone()
            if row:
                mount_cache[did] = (row[0] or "", row[1] or "")
            else:
                mount_cache[did] = ("", "")

        if table_name not in columns_cache:
            cols = {
                r[1]
                for r in conn.execute(f"PRAGMA table_info({table_name})")
            }
            columns_cache[table_name] = cols
        cols = columns_cache[table_name]

        has_sha = "sha256" in cols
        has_qh = "quick_hash" in cols
        has_inode = "inode" in cols

        sha_col = "sha256" if has_sha else "NULL"
        qh_col = "quick_hash" if has_qh else "NULL"
        ino_col = "inode" if has_inode else "NULL"

        mp, pmp = mount_cache[did]
        rel_root = root_path
        for mount in (mp, pmp):
            if not mount:
                continue
            mps = mount.rstrip("/") + "/"
            if root_path.startswith(mps):
                rel_root = root_path[len(mps):]
                break
            if root_path == mount.rstrip("/"):
                rel_root = ""
                break

        root_prefix = (rel_root.rstrip("/") + "/") if rel_root else ""
        like_pattern = root_prefix + "%"
        try:
            rows = conn.execute(
                f"""
                SELECT path, size, {sha_col}, {qh_col}, {ino_col}
                FROM {table_name}
                WHERE path LIKE ? AND status = 'active'
                """,
                (like_pattern,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue

        for row in rows:
            fp, size, sha, qh, inode = row
            entries.append(OrphanFileEntry(
                payload_id=payload_id,
                root_path=root_path,
                device_id=did,
                file_path=fp,
                file_size=size or 0,
                sha256=sha,
                quick_hash=qh,
                inode=inode or 0,
                link_count=0,
            ))

    return entries


def _build_cross_device_sha256_index(
    conn: sqlite3.Connection,
    min_size: int = 0,
) -> Dict[Tuple[int, str], CrossDeviceDuplicateGroup]:
    """Build index of (device_id, path) → SHA256-confirmed cross-device dupe group."""
    result = analyze_cross_device(conn, min_size=min_size, use_quick_hash=False)
    index: Dict[Tuple[int, str], CrossDeviceDuplicateGroup] = {}
    for group in result.duplicate_groups:
        for dev_id, path in group.entries:
            index[(dev_id, path)] = group
    return index


def _build_cross_device_quick_hash_index(
    conn: sqlite3.Connection,
    min_size: int = 0,
) -> Dict[Tuple[int, str], CrossDeviceDuplicateGroup]:
    """Build index of (device_id, path) → quick-hash cross-device dupe group."""
    result = analyze_cross_device(conn, min_size=min_size, use_quick_hash=True)
    index: Dict[Tuple[int, str], CrossDeviceDuplicateGroup] = {}
    for group in result.duplicate_groups:
        for dev_id, path in group.entries:
            index[(dev_id, path)] = group
    return index


def classify_orphan_dedup(
    db_path: Path,
    path_prefixes: Optional[List[str]] = None,
    min_size: int = 0,
) -> ClassificationResult:
    conn = connect_db(db_path, read_only=True, apply_migrations=False)
    try:
        orphans = _find_orphan_payloads(conn, path_prefixes)
        if not orphans:
            return ClassificationResult(
                total_orphan_payloads=0,
                warnings=["No orphan payloads found in scope."],
            )

        orphan_files = _collect_orphan_files(conn, orphans)

        sha256_index = _build_cross_device_sha256_index(conn, min_size=min_size)
        qh_index = _build_cross_device_quick_hash_index(conn, min_size=min_size)

        candidates: List[ClassifiedOrphan] = []
        for entry in orphan_files:
            key = (entry.device_id, entry.file_path)

            sha_group = sha256_index.get(key)
            qh_group = qh_index.get(key)

            match_devs: List[int] = []
            match_paths: List[str] = []

            if sha_group is not None:
                classification = "sha256_confirmed"
                hash_basis = "sha256"
                for did, path in sha_group.entries:
                    if did != entry.device_id or path != entry.file_path:
                        match_devs.append(did)
                        match_paths.append(_resolve_device_path(conn, did, path))
            elif qh_group is not None:
                classification = "quick_hash_candidate"
                hash_basis = "quick_hash"
                for did, path in qh_group.entries:
                    if did != entry.device_id or path != entry.file_path:
                        match_devs.append(did)
                        match_paths.append(_resolve_device_path(conn, did, path))
            else:
                classification = "no_match"
                hash_basis = "none"

            candidates.append(ClassifiedOrphan(
                payload_id=entry.payload_id,
                root_path=entry.root_path,
                device_id=entry.device_id,
                file_path=entry.file_path,
                file_size=entry.file_size,
                hash_basis=hash_basis,
                sha256=entry.sha256,
                quick_hash=entry.quick_hash,
                inode=entry.inode,
                link_count=entry.link_count,
                classification=classification,
                match_device_ids=match_devs,
                match_paths=match_paths,
            ))

        sha_files = [c for c in candidates if c.classification == "sha256_confirmed"]
        qh_files = [c for c in candidates if c.classification == "quick_hash_candidate"]
        nm_files = [c for c in candidates if c.classification == "no_match"]

        warnings: List[str] = []
        sha_no_match_device = [
            c for c in sha_files if not c.match_device_ids
        ]
        if sha_no_match_device:
            warnings.append(
                f"{len(sha_no_match_device)} sha256_confirmed files have no "
                "other-device entries in the SHA256 group (only self-reference)."
            )

        return ClassificationResult(
            candidates=candidates,
            total_orphan_payloads=len(orphans),
            total_files=len(candidates),
            sha256_confirmed=len(sha_files),
            sha256_confirmed_bytes=sum(c.file_size for c in sha_files),
            quick_hash_only=len(qh_files),
            quick_hash_only_bytes=sum(c.file_size for c in qh_files),
            no_match=len(nm_files),
            no_match_bytes=sum(c.file_size for c in nm_files),
            warnings=warnings,
        )
    finally:
        conn.close()


def format_classification_text(result: ClassificationResult) -> str:
    lines: List[str] = []
    lines.append("🔎 Orphan Dedupe Classification (DRY-RUN ONLY)")
    lines.append(f"   orphan payloads in scope: {result.total_orphan_payloads}")
    lines.append(f"   total orphan files: {result.total_files:,}")
    lines.append("")
    lines.append("📊 Classification Breakdown:")
    lines.append(
        f"   SHA256-confirmed (safe to delete after approval): "
        f"{result.sha256_confirmed:,} files "
        f"({result.sha256_confirmed_bytes / (1024**3):.1f} GB)"
    )
    lines.append(
        f"   quick-hash-only (needs SHA256 upgrade before deletion): "
        f"{result.quick_hash_only:,} files "
        f"({result.quick_hash_only_bytes / (1024**3):.1f} GB)"
    )
    lines.append(
        f"   no cross-device match (needs rsync before deletion):     "
        f"{result.no_match:,} files "
        f"({result.no_match_bytes / (1024**3):.1f} GB)"
    )
    lines.append("")

    if result.warnings:
        lines.append("⚠ Warnings:")
        for w in result.warnings:
            lines.append(f"   {w}")
        lines.append("")

    lines.append("📋 Evidence Checklist (before any live deletion):")
    lines.append("   ☐ path: absolute path confirmed on source and target devices")
    lines.append("   ☐ size: file size matches across devices")
    lines.append("   ☐ hash basis: SHA256 for confirmed; upgrade quick-hash-only first")
    lines.append("   ☐ link count (st_nlink): verify hardlink references before rm")
    lines.append("   ☐ device ID: confirm both source and target device aliases")
    lines.append("   ☐ active-client exclusion: no RT/qB torrent references orphan path")
    lines.append("   ☐ rollback posture: hotspare copy confirmed; restore path documented")
    lines.append("   ☐ backup posture: rsync --dry-run verification before deletion")
    lines.append("")
    lines.append("🚫 No filesystem or client state was modified.")
    return "\n".join(lines)


def format_classification_json(result: ClassificationResult) -> str:
    payload: dict = {
        "orphan_payloads_in_scope": result.total_orphan_payloads,
        "total_files": result.total_files,
        "sha256_confirmed": {
            "files": result.sha256_confirmed,
            "bytes": result.sha256_confirmed_bytes,
            "bytes_human": f"{result.sha256_confirmed_bytes / (1024**3):.1f} GB",
        },
        "quick_hash_only": {
            "files": result.quick_hash_only,
            "bytes": result.quick_hash_only_bytes,
            "bytes_human": f"{result.quick_hash_only_bytes / (1024**3):.1f} GB",
        },
        "no_match": {
            "files": result.no_match,
            "bytes": result.no_match_bytes,
            "bytes_human": f"{result.no_match_bytes / (1024**3):.1f} GB",
        },
        "warnings": result.warnings,
        "candidates": [
            {
                "payload_id": c.payload_id,
                "root_path": c.root_path,
                "device_id": c.device_id,
                "file_path": c.file_path,
                "file_size": c.file_size,
                "hash_basis": c.hash_basis,
                "sha256": c.sha256,
                "quick_hash": c.quick_hash,
                "inode": c.inode,
                "link_count": c.link_count,
                "classification": c.classification,
                "match_device_ids": c.match_device_ids,
                "match_paths": c.match_paths[:10],
            }
            for c in result.candidates[:500]
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)
