"""
Save-path repair: move secondary hashes from _rehome-unique/<hash16>/ to canonical paths.

After hitchhiker split, secondary hashes live in _rehome-unique/<hash16>/ as temporary
locations. This module moves them to their canonical seeding paths based on category/tags
and stash-vs-pool placement decisions.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rt_cache import load_rt_cache_snapshot
from .save_path_inference import infer_canonical_save_path
from .rtorrent import rt_apply_directory_repoint, DEFAULT_RT_RPC_URL
from .utils import find_db_path

# Seeding root aliases: (fs_path_on_host, api_path_for_qb_and_rt)
_SEEDING_ROOT_ALIASES: list[tuple[str, str]] = [
    ("/stash/media/torrents/seeding", "/data/media/torrents/seeding"),
    ("/data/media/torrents/seeding", "/data/media/torrents/seeding"),
    ("/pool/media/torrents/seeding", "/pool/media/torrents/seeding"),
]


@dataclass
class RepairAction:
    """Planned/executed repair for one secondary hash."""
    hash_val: str
    current_source_path_fs: str  # current _rehome-unique location
    current_source_path_api: str  # qB/RT API path
    canonical_target_path_fs: str  # destination on filesystem
    canonical_target_path_api: str  # qB/RT API path for destination
    category: str
    is_drifted: bool
    files_moved: int = 0
    completed: bool = False
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class RepairResult:
    """Result of repairing one hash."""
    hash_val: str
    category: str
    actions: list[RepairAction] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _scan_rehome_unique_hashes(
    max_age_s: int = 300,
) -> dict[str, str]:
    """
    Scan _rehome-unique directories and return hash → source_path_fs mapping.
    Returns {hash_lower: fs_path_to_rehome_dir}.
    """
    rehome_hashes: dict[str, str] = {}

    # Scan both stash and pool
    for root_base in ["/stash/media/torrents/seeding", "/pool/media/torrents/seeding"]:
        rehome_dir = Path(root_base) / "_rehome-unique"
        if not rehome_dir.exists():
            continue

        for hash_dir in sorted(rehome_dir.iterdir()):
            if not hash_dir.is_dir():
                continue
            hash_val = hash_dir.name.lower()
            rehome_hashes[hash_val] = str(hash_dir)

    return rehome_hashes


def _api_path(path_on_fs: str, fs_root: str, api_root: str) -> str:
    """Convert a filesystem path to the corresponding qB/RT API path."""
    if fs_root == api_root:
        return path_on_fs
    rel = path_on_fs[len(fs_root):]
    return api_root + rel


def _move_tree(src: Path, dst_parent: Path, *, dry_run: bool) -> int:
    """
    Move src tree into dst_parent (rename operation, not copy+delete).
    Returns number of files moved (or counted in dry-run).
    """
    count = 0

    if src.is_file():
        dst = dst_parent / src.name
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        count = 1
    elif src.is_dir():
        for item in sorted(src.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(src.parent)  # keeps src.name in path
            dst_file = dst_parent / rel
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                if dst_file.exists():
                    raise FileExistsError(f"target already exists: {dst_file}")
                shutil.move(str(item), str(dst_file))
            count += 1

    return count


def audit_repair_candidates(
    max_age_s: int = 300,
) -> list[RepairAction]:
    """
    Scan _rehome-unique hashes and determine repair targets.
    Uses catalog save_path as the authoritative category/path hint.
    Returns list of planned repair actions.
    """
    import sqlite3

    rehome_hashes = _scan_rehome_unique_hashes(max_age_s=max_age_s)
    if not rehome_hashes:
        return []

    # Load qB state from cache
    qb_by_hash: dict = {}
    try:
        cached_raw = get_torrents_from_cache(max_age_s=max_age_s, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached_raw is not None:
            qb_client = QBittorrentClient()
            for r in cached_raw:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_by_hash[t.hash.lower()] = t
        else:
            qb_client = QBittorrentClient()
            all_hashes = list(rehome_hashes.keys())
            live = qb_client.get_torrents_by_hashes(all_hashes) or {}
            qb_by_hash = {h.lower(): v for h, v in live.items()}
    except Exception:
        pass

    # Load RT state from cache
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception:
        pass

    # Load catalog entries to get original save_path/category hints
    catalog_by_hash: dict = {}
    try:
        db = find_db_path()
        conn = sqlite3.connect(str(db), timeout=30.0)
        conn.row_factory = sqlite3.Row
        query = """
            SELECT ti.torrent_hash, ti.save_path, p.root_path
            FROM torrent_instances ti
            JOIN payloads p ON ti.payload_id = p.payload_id
        """
        for row in conn.execute(query).fetchall():
            hash_val = row["torrent_hash"].lower()
            catalog_by_hash[hash_val] = {
                "save_path": row["save_path"],
                "root_path": row["root_path"],
            }
        conn.close()
    except Exception:
        pass

    # Plan repairs
    actions = []
    for hash_val, source_fs_path in sorted(rehome_hashes.items()):
        qb_torrent = qb_by_hash.get(hash_val)
        rt_info = rt_by_hash.get(hash_val, {})
        catalog_info = catalog_by_hash.get(hash_val, {})

        # Get metadata for inference
        qb_category = qb_torrent.category if qb_torrent else ""
        # Note: qb_torrent.tags is already a comma-separated string, not a list
        qb_tags = qb_torrent.tags if qb_torrent and qb_torrent.tags else ""
        catalog_save_path = catalog_info.get("save_path", "")
        rt_directory = rt_info.get("directory", "")

        # Infer canonical path using catalog's original save_path as hint
        inferred = infer_canonical_save_path(
            category=qb_category,
            tags=qb_tags,
            current_save_path=catalog_save_path,  # Use catalog's original path
            current_rt_directory=rt_directory,
        )

        # Determine filesystem vs API paths based on device
        if inferred.device == "stash":
            target_fs = inferred.canonical_save_path.replace("/data/media", "/stash/media")
            fs_root, api_root = "/stash/media/torrents/seeding", "/data/media/torrents/seeding"
        else:
            target_fs = inferred.canonical_save_path.replace("/data/media", "/pool/media")
            fs_root, api_root = "/pool/media/torrents/seeding", "/pool/media/torrents/seeding"

        action = RepairAction(
            hash_val=hash_val,
            current_source_path_fs=source_fs_path,
            current_source_path_api=_api_path(source_fs_path, fs_root, api_root),
            canonical_target_path_fs=target_fs,
            canonical_target_path_api=inferred.canonical_save_path,
            category=qb_category or "uncategorized",
            is_drifted=False,
        )
        actions.append(action)

    return actions


def execute_repair(
    hash_val: str,
    *,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> RepairResult:
    """
    Repair one hash: move from _rehome-unique/<hash16>/ to canonical path.
    Uses pre-computed audit action if available (faster); otherwise computes on the fly.
    """
    import sqlite3

    result = RepairResult(
        hash_val=hash_val,
        category="unknown",
    )

    # Find the hash in rehome_unique
    rehome_hashes = _scan_rehome_unique_hashes()
    source_path_fs = rehome_hashes.get(hash_val.lower())
    if not source_path_fs:
        result.error = f"hash not found in _rehome-unique: {hash_val}"
        return result

    # Load qB and RT state
    qb_by_hash: dict = {}
    try:
        cached_raw = get_torrents_from_cache(max_age_s=300, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached_raw is not None:
            if qb_client is None:
                qb_client = QBittorrentClient()
            for r in cached_raw:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_by_hash[t.hash.lower()] = t
    except Exception:
        pass

    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception:
        pass

    # Load catalog entry for category hint
    catalog_info: dict = {}
    try:
        db = find_db_path()
        conn = sqlite3.connect(str(db), timeout=30.0)
        conn.row_factory = sqlite3.Row
        query = """
            SELECT ti.save_path FROM torrent_instances ti
            WHERE ti.torrent_hash = ? LIMIT 1
        """
        row = conn.execute(query, [hash_val]).fetchone()
        if row:
            catalog_info["save_path"] = row["save_path"]
        conn.close()
    except Exception:
        pass

    qb_torrent = qb_by_hash.get(hash_val.lower())
    rt_info = rt_by_hash.get(hash_val.lower(), {})

    qb_category = qb_torrent.category if qb_torrent else ""
    result.category = qb_category or "unknown"

    # Infer canonical path
    # Priority: use qB category/tags (current authority), fall back to catalog hints
    # Note: qb_torrent.tags is already a comma-separated string, not a list
    qb_tags = qb_torrent.tags if qb_torrent and qb_torrent.tags else ""
    catalog_save_path = catalog_info.get("save_path", "")

    inferred = infer_canonical_save_path(
        category=qb_category,
        tags=qb_tags,
        current_save_path=catalog_save_path,  # May contain _rehome-unique, but we use qB category instead
        current_rt_directory=rt_info.get("directory", ""),
    )

    # Skip if target path is malformed (e.g., ends with /)
    if not inferred.canonical_save_path or inferred.canonical_save_path.endswith("/-"):
        result.error = f"malformed canonical path: {inferred.canonical_save_path}"
        return result

    # Determine target paths
    target_fs_base = inferred.canonical_save_path.replace("/data/media", "/stash/media") if inferred.device == "stash" else inferred.canonical_save_path

    # Move files (dry-run or actual)
    try:
        src = Path(source_path_fs)
        dst_parent = Path(target_fs_base).parent
        files_moved = _move_tree(src, dst_parent, dry_run=dry_run)

        # Repoint qB only if it exists and is not in dry-run
        if not dry_run and qb_torrent:
            if qb_client is None:
                qb_client = QBittorrentClient()
            ok = qb_client.set_location(hash_val, inferred.canonical_save_path)
            if not ok:
                raise RuntimeError("qb set_location returned False")

        # Repoint RT only if it exists and is not in dry-run
        if not dry_run and rt_info:
            rt_apply_directory_repoint(
                hash_val,
                inferred.canonical_save_path,
                rpc_url=rpc_url,
                restart=True,
            )

        result.success = True
        result.notes.append(f"moved {files_moved} files to {target_fs_base}")

    except Exception as exc:
        result.error = str(exc)
        result.notes.append(f"FAILED: {exc}")

    if dry_run:
        result.notes.append("dry-run: no files moved, no qB/RT changes made")

    return result


def format_repair_report(
    results: list[RepairResult],
    *,
    dry_run: bool,
    json_output: bool = False,
) -> str:
    """Format repair results for output."""
    if json_output:
        import json
        return json.dumps(
            [
                {
                    "hash": r.hash_val[:16],
                    "category": r.category,
                    "success": r.success,
                    "error": r.error,
                    "dry_run": dry_run,
                    "notes": r.notes,
                }
                for r in results
            ],
            indent=2,
        )

    lines = []
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success and r.error)

    lines.append(f"Save-Path Repair [{mode}]: {len(results)} hashes processed")
    lines.append(f"  Succeeded: {succeeded}  Failed: {failed}")
    lines.append("")

    for r in results:
        status = "OK" if r.success else ("ERR" if r.error else "SKIP")
        lines.append(f"  [{status}] {r.hash_val[:16]}  category={r.category}")
        if r.error:
            lines.append(f"        error: {r.error}")
        for note in r.notes:
            lines.append(f"        {note}")

    return "\n".join(lines)
