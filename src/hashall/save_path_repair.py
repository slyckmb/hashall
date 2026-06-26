"""
Save-path repair: move hashes from staging dirs to canonical seeding paths.

Staging dirs handled:
  _rehome-unique/<hash16>/    — hitchhiker-split secondaries (stash + pool)
  _qb-finish/<hash40>/        — qB-finish legacy staging (stash only)
  _qb-unique-repair/<hash40>/ — qB-unique-repair legacy staging (stash only)

All hashes are moved to their canonical paths based on category/tags and
stash-vs-pool placement decisions.
"""

__version__ = "0.1.0"

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rt_cache import load_rt_cache_snapshot
from .save_path_inference import infer_canonical_save_path, _STAGING_DIRS
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


def _staging_has_real_content(path: Path) -> bool:
    """True if path contains any real files or symlinks (not just empty subdirectory structure)."""
    return any(p for p in path.rglob("*") if not p.is_dir())


def _is_in_staging_dir(path_str: str) -> bool:
    """True if path_str contains any staging directory component."""
    return any(f"/{d}/" in path_str or path_str.endswith(f"/{d}") for d in _STAGING_DIRS)


def _scan_staging_hashes(
    max_age_s: int = 300,
) -> dict[str, str]:
    """
    Scan all staging directories and return hash → source_path_fs mapping.

    Scanned dirs:
      _rehome-unique/    — stash + pool  (hash16 dir names)
      _qb-finish/        — stash only    (hash40 dir names)
      _qb-unique-repair/ — stash only    (hash40 dir names)

    Returns {hash_lower: fs_path_to_staging_hash_dir}.
    """
    staging_hashes: dict[str, str] = {}

    stash_root = "/stash/media/torrents/seeding"
    pool_root = "/pool/media/torrents/seeding"

    # _rehome-unique: stash + pool
    for root_base in [stash_root, pool_root]:
        d = Path(root_base) / "_rehome-unique"
        if not d.exists():
            continue
        for hash_dir in sorted(d.iterdir()):
            if hash_dir.is_dir():
                key = hash_dir.name.lower()
                if key in staging_hashes:
                    logger.error(
                        "save_path_repair: hash collision %r: stash/pool _rehome-unique dirs; "
                        "skipping both %s and %s — manual resolution required",
                        key, staging_hashes[key], str(hash_dir),
                    )
                    del staging_hashes[key]
                    continue
                staging_hashes[key] = str(hash_dir)

    # _qb-finish and _qb-unique-repair: stash only
    for staging_name in ("_qb-finish", "_qb-unique-repair"):
        d = Path(stash_root) / staging_name
        if not d.exists():
            continue
        for hash_dir in sorted(d.iterdir()):
            if hash_dir.is_dir():
                staging_hashes[hash_dir.name.lower()] = str(hash_dir)

    return staging_hashes


# Backward-compat alias used by legacy callers (gc, audit) — remove once all callers updated.
_scan_rehome_unique_hashes = _scan_staging_hashes


def _api_path(path_on_fs: str, fs_root: str, api_root: str) -> str:
    """Convert a filesystem path to the corresponding qB/RT API path."""
    if fs_root == api_root:
        return path_on_fs
    rel = path_on_fs[len(fs_root):]
    return api_root + rel


def _move_tree(src: Path, dst_parent: Path, *, dry_run: bool) -> int:
    """
    Move contents of src directory into dst_parent.
    For a directory src, each top-level item in src is moved into dst_parent.
    For a single file src, the file itself is moved into dst_parent.
    Returns number of files moved (or counted in dry-run).

    dst_parent should be the canonical save_path directory (not its parent).
    """
    if not dry_run and src.exists():
        src_stat = src.stat()
        dst_parent.mkdir(parents=True, exist_ok=True)
        dst_stat = dst_parent.stat()
        if src_stat.st_dev != dst_stat.st_dev:
            raise RuntimeError(
                f"cross-filesystem move rejected: src={src} dev={src_stat.st_dev} "
                f"dst_parent={dst_parent} dev={dst_stat.st_dev}"
            )

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
            rel = item.relative_to(src)  # relative to src (not src.parent) — excludes src dir name
            dst_file = dst_parent / rel
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                if dst_file.exists():
                    dst_st = dst_file.stat()
                    item_st = item.stat()
                    if dst_st.st_ino == item_st.st_ino and dst_st.st_dev == item_st.st_dev:
                        # Same inode (hardlink): file already at target, just remove source link
                        item.unlink()
                    else:
                        raise FileExistsError(f"target already exists: {dst_file}")
                else:
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

    rehome_hashes = _scan_staging_hashes(max_age_s=max_age_s)
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
    except Exception as exc:
        logger.warning("save_path_repair: failed to load qB cache: %s", exc)

    # Load RT state from cache
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception as exc:
        logger.warning("save_path_repair: failed to load RT cache: %s", exc)

    # Load catalog entries to get original save_path/category hints
    catalog_by_hash: dict = {}
    db = find_db_path()
    if db is not None:
        try:
            conn = sqlite3.connect(str(db), timeout=30.0)
            try:
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
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("save_path_repair: failed to load catalog: %s", exc)

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
            canon = inferred.canonical_save_path
            target_fs = "/stash/media" + canon[len("/data/media"):] if canon.startswith("/data/media") else canon
            fs_root, api_root = "/stash/media/torrents/seeding", "/data/media/torrents/seeding"
        else:
            canon = inferred.canonical_save_path
            target_fs = "/pool/media" + canon[len("/data/media"):] if canon.startswith("/data/media") else canon
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


DEFAULT_QB_CONTAINER = "qbittorrent_vpn"
DEFAULT_QB_API_URL = "http://localhost:9003"


def _resolve_full_hash(hash_val: str, qb_by_hash: dict, conn_db) -> str:
    """
    Resolve a possibly-truncated hash (hash16) to its full 40-char hash.
    Searches qB dict by prefix, then DB by LIKE prefix.
    Returns the input unchanged if already 40 chars.

    Bug B guard: if prefix matches more than one full hash, raise ValueError
    instead of silently using the first match. See BACKLOG.md Gap 6.

    Raises ValueError if 0 matches found in qB dict and catalog DB.
    """
    if len(hash_val) >= 40:
        return hash_val.lower()
    prefix = hash_val.lower()
    # Try qB dict by prefix match
    matches = sorted(full_h for full_h in qb_by_hash if full_h.startswith(prefix))
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous prefix {prefix}: matches {len(matches)} hashes "
            f"({', '.join(m[:16] for m in matches[:5])})"
        )
    if len(matches) == 1:
        return matches[0]
    # Try DB by LIKE
    if conn_db is not None:
        try:
            rows = conn_db.execute(
                "SELECT torrent_hash FROM torrent_instances WHERE torrent_hash LIKE ?",
                [prefix + "%"],
            ).fetchall()
            if len(rows) > 1:
                raise ValueError(
                    f"ambiguous prefix {prefix}: {len(rows)} matches in catalog DB"
                )
            if len(rows) == 1:
                return str(rows[0][0]).lower()
        except ValueError:
            raise
        except Exception:
            logger.warning(
                "save_path_repair: DB lookup failed for prefix %r", prefix, exc_info=True,
            )
    raise ValueError(
        f"No match for prefix {prefix!r} in qB or catalog — cannot resolve full hash"
    )


def _docker_stop_qb(container: str = DEFAULT_QB_CONTAINER) -> None:
    """Stop the qBittorrent Docker container."""
    import subprocess
    subprocess.run(["docker", "stop", container], check=True, capture_output=True, text=True, timeout=60)


def _docker_start_qb(
    container: str = DEFAULT_QB_CONTAINER,
    qb_url: str = DEFAULT_QB_API_URL,
    timeout_s: float = 90.0,
) -> None:
    """Start the qBittorrent Docker container and wait for API to become reachable."""
    import subprocess, time, requests as _requests
    subprocess.run(["docker", "start", container], check=True, capture_output=True, text=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = _requests.get(f"{qb_url}/api/v2/app/version", timeout=3)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"qB API not ready after {timeout_s}s at {qb_url}")


def execute_repair(
    hash_val: str,
    *,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    qb_container: str = DEFAULT_QB_CONTAINER,
    qb_url: str = DEFAULT_QB_API_URL,
) -> RepairResult:
    """
    Repair one hash: move from _rehome-unique/<hash_dir>/ to canonical path.

    Correct workflow (live mode):
      1. Move files from _rehome-unique/<hash_dir>/ to canonical_path_fs/
      2. Stop qB container
      3. Patch fastresume with canonical API path
      4. Start qB container
      5. Repoint RT to canonical content directory
      6. Recheck torrent in qB

    hash_val may be truncated (16 chars from dir name) or full (40 chars).
    Full hash is resolved via qB/DB prefix lookup.
    """
    import sqlite3

    result = RepairResult(
        hash_val=hash_val,
        category="unknown",
    )

    # Find the hash in any staging dir
    staging_hashes = _scan_staging_hashes()
    source_path_fs = staging_hashes.get(hash_val.lower())
    if not source_path_fs:
        result.error = f"hash not found in any staging dir: {hash_val}"
        return result

    # Load qB state from cache (avoids live API hit)
    if qb_client is None:
        qb_client = QBittorrentClient()
    qb_by_hash: dict = {}
    try:
        cached_raw = get_torrents_from_cache(max_age_s=300, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached_raw is not None:
            for r in cached_raw:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_by_hash[t.hash.lower()] = t
        else:
            # Cache miss: fetch live for just this hash (expensive but correct)
            live = qb_client.get_torrents_by_hashes([hash_val]) or {}
            qb_by_hash = {h.lower(): v for h, v in live.items()}
    except Exception as exc:
        logger.warning("save_path_repair: failed to load qB cache: %s", exc)

    # Load RT state from cache
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception as exc:
        logger.warning("save_path_repair: failed to load RT cache: %s", exc)

    # Open DB for catalog hints and hash resolution
    conn_db = None
    catalog_info: dict = {}
    try:
        db = find_db_path()
        conn_db = sqlite3.connect(str(db), timeout=30.0)
        conn_db.row_factory = sqlite3.Row
    except Exception:
        pass

    # Resolve hash_val to full 40-char hash (hash_val may be truncated 16-char dir name)
    try:
        effective_hash = _resolve_full_hash(hash_val.lower(), qb_by_hash, conn_db)
    except ValueError as e:
        result.error = str(e)
        return result

    # Load catalog entry for category hint
    try:
        if conn_db is not None:
            row = conn_db.execute(
                "SELECT ti.save_path FROM torrent_instances ti WHERE ti.torrent_hash = ? LIMIT 1",
                [effective_hash],
            ).fetchone()
            if row:
                catalog_info["save_path"] = row["save_path"]
    except Exception:
        pass
    finally:
        if conn_db is not None:
            try:
                conn_db.close()
            except Exception:
                pass

    qb_torrent = qb_by_hash.get(effective_hash)
    rt_info = rt_by_hash.get(effective_hash, {})

    # Guard: skip torrents that are still downloading — moving a partial file to the
    # canonical path is wrong; the data would be incomplete at the destination.
    if qb_torrent is not None:
        qb_progress = getattr(qb_torrent, "progress", None)
        qb_amount_left = getattr(qb_torrent, "amount_left", None)
        is_incomplete = (qb_progress is not None and qb_progress < 1.0) or (
            qb_amount_left is not None and qb_amount_left > 0
        )
        if is_incomplete:
            pct = f"{qb_progress * 100:.1f}%" if qb_progress is not None else "unknown%"
            result.notes.append(
                f"SKIP: torrent is still downloading ({pct} complete)"
                f" — repair only applies to completed/seeding torrents"
            )
            result.success = True
            return result

    # Bug 5 guard: orphan empty staging dirs → skip early, before inference.
    # Use save_path/directory filter (not bare prefix match): with 4800+ torrents,
    # ~80% of 16-char hash prefixes collide with unrelated hashes in qb_by_hash.
    src_early = Path(source_path_fs)
    if src_early.is_dir() and not _staging_has_real_content(src_early):
        qb_at_staging = qb_torrent is not None and _is_in_staging_dir(
            str(getattr(qb_torrent, "save_path", ""))
        )
        rt_at_staging = _is_in_staging_dir(str(rt_info.get("directory", "")))
        if not qb_at_staging and not rt_at_staging:
            result.notes.append(
                "SKIP: orphan empty staging dir — no live qB/RT entry, nothing to repair"
            )
            result.success = True
            return result

    qb_category = qb_torrent.category if qb_torrent else ""
    result.category = qb_category or "unknown"

    # qb_torrent.tags is a comma-separated string (not a list)
    qb_tags = qb_torrent.tags if qb_torrent and qb_torrent.tags else ""

    # Guard: ~issue tag → needs manual review before any automated repair
    tags_set = {t.strip() for t in qb_tags.split(",") if t.strip()}
    if "~issue" in tags_set:
        result.notes.append(
            "SKIP: torrent tagged ~issue — needs manual review before automated repair"
        )
        result.success = True
        return result
    catalog_save_path = catalog_info.get("save_path", "")

    inferred = infer_canonical_save_path(
        category=qb_category,
        tags=qb_tags,
        current_save_path=catalog_save_path,
        current_rt_directory=rt_info.get("directory", ""),
    )

    # Reject malformed canonical paths
    if not inferred.canonical_save_path or inferred.canonical_save_path.endswith("/-"):
        result.error = f"malformed canonical path: {inferred.canonical_save_path}"
        return result

    # Reject ambiguous inference that resolves to a bare seeding root (no subdir)
    _SEEDING_ROOTS = {
        "/data/media/torrents/seeding",
        "/stash/media/torrents/seeding",
        "/pool/media/torrents/seeding",
    }
    if (
        inferred.reliability == "ambiguous"
        and inferred.canonical_save_path.rstrip("/") in _SEEDING_ROOTS
    ):
        result.error = f"ambiguous canonical path (bare seeding root): {inferred.canonical_save_path}"
        return result

    # Filesystem path: stash uses /stash/media/, pool uses /pool/media/ (same as API)
    if inferred.device == "stash":
        canon = inferred.canonical_save_path
        target_fs = "/stash/media" + canon[len("/data/media"):] if canon.startswith("/data/media") else canon
    else:
        target_fs = inferred.canonical_save_path  # pool: API path == FS path

    # RT d.directory.set takes the parent dir; rTorrent appends info_name itself
    rt_target_dir = inferred.canonical_save_path

    try:
        src = Path(source_path_fs)
        dst = Path(target_fs)  # canonical save_path dir (not its parent)

        staging_is_empty = src.is_dir() and not _staging_has_real_content(src)

        # Bug 2 guard: skip fastresume patch when staging dir was empty and qB still
        # points to a staging dir — data already moved elsewhere, destination unknown.
        # Must check BEFORE _move_tree to avoid cross-filesystem rejection on empty dirs.
        qb_at_rehome = qb_torrent and _is_in_staging_dir(str(qb_torrent.save_path))
        if staging_is_empty and qb_at_rehome:
            result.notes.append(
                "SKIP: empty staging dir, qB still at _rehome-unique"
                " — data already moved; needs manual investigation before fastresume patch"
            )
            result.success = True
            return result

        files_moved = _move_tree(src, dst, dry_run=dry_run)

        should_apply = files_moved > 0 or qb_at_rehome

        if not dry_run:
            if not should_apply:
                result.notes.append(
                    f"SKIP: 0 files moved, qB save_path not in _rehome-unique"
                    f" — fastresume/RT not modified"
                )
            else:
                # Stop qB, patch fastresume, start qB
                fastresume_path = qb_client._fastresume_path(effective_hash)
                if fastresume_path.exists():
                    _docker_stop_qb(qb_container)
                    try:
                        from .fastresume import patch_fastresume_file
                        patch_fastresume_file(
                            fastresume_path,
                            inferred.canonical_save_path,
                            ".bak-repair",
                        )
                    finally:
                        _docker_start_qb(qb_container, qb_url)
                    result.notes.append(f"patched fastresume → {inferred.canonical_save_path}")
                else:
                    result.notes.append(f"fastresume not found: {fastresume_path}")

                # Repoint RT (best-effort)
                if rt_info:
                    try:
                        rt_apply_directory_repoint(
                            effective_hash,
                            rt_target_dir,
                            rpc_url=rpc_url,
                            restart=True,
                            check_before_start=True,
                            validate_target_exists=True,
                        )
                        result.notes.append(f"RT repointed → {rt_target_dir}")
                    except Exception as rt_exc:
                        result.notes.append(f"RT repoint failed: {rt_exc}")

                # Recheck torrent to confirm content at new location
                try:
                    qb_client.recheck_torrent(effective_hash)
                    result.notes.append("recheck triggered")
                except Exception as rc_exc:
                    result.notes.append(f"recheck failed: {rc_exc}")

        result.success = True
        result.notes.append(
            f"{'[dry-run] would move' if dry_run else 'moved'} {files_moved} files"
            f" from {source_path_fs} → {target_fs}"
        )

    except Exception as exc:
        result.error = str(exc)
        result.notes.append(f"FAILED: {exc}")

    if dry_run:
        result.notes.append("dry-run: no files moved, no qB/fastresume/RT changes made")

    return result


def gc_empty_staging_dirs(*, dry_run: bool = True) -> tuple[int, int]:
    """
    Delete empty staging hash dirs (_rehome-unique/, _qb-finish/, _qb-unique-repair/)
    that have no live qB/RT entry pointing to them.

    Returns (deleted_count, total_found).
    """
    rehome_hashes = _scan_staging_hashes()

    qb_by_hash: dict = {}
    try:
        cached_raw = get_torrents_from_cache(max_age_s=300, cache_path=DEFAULT_QB_CACHE_FILE)
        qb_client = QBittorrentClient()
        if cached_raw is not None:
            for r in cached_raw:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_by_hash[t.hash.lower()] = t
        else:
            all_hashes = list(rehome_hashes.keys())
            live = qb_client.get_torrents_by_hashes(all_hashes) or {}
            qb_by_hash = {h.lower(): v for h, v in live.items()}
    except Exception as exc:
        logger.warning("gc_empty_staging_dirs: failed to load qB cache: %s", exc)

    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception as exc:
        logger.warning("gc_empty_staging_dirs: failed to load RT cache: %s", exc)

    deleted = 0
    for hash_val, source_fs_path in sorted(rehome_hashes.items()):
        src = Path(source_fs_path)
        if not src.is_dir() or _staging_has_real_content(src):
            continue  # has real content — skip
        # A torrent is "live here" only if its save_path/directory actually points into
        # this _rehome-unique dir — not just any torrent whose hash shares a 16-char prefix.
        # (With 4800+ torrents, ~80% of 16-char prefixes collide with unrelated hashes.)
        has_live_qb = any(
            full_h.startswith(hash_val) and _is_in_staging_dir(str(t.save_path))
            for full_h, t in qb_by_hash.items()
        )
        has_live_rt = any(
            full_h.startswith(hash_val) and _is_in_staging_dir(str(r.get("directory", "")))
            for full_h, r in rt_by_hash.items()
        )
        if has_live_qb or has_live_rt:
            continue  # live client still points here — skip
        if not dry_run:
            # Use rmtree for dirs with empty subdirectory structure, rmdir for truly empty
            if any(src.iterdir()):
                shutil.rmtree(src)
            else:
                src.rmdir()
        deleted += 1

    return deleted, len(rehome_hashes)


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
