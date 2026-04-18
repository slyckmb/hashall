"""
Orphan sweep: find and relocate/delete content in seeding trees that is not
backed by an active RT or qBittorrent torrent.

Seeding roots scanned:
  /pool/data/media/torrents/seeding  → cross-dataset rsync --move to /pool/media/torrents/orphaned_data
  /pool/media/torrents/seeding       → same-dataset os.rename to /pool/media/torrents/orphaned_data
  /stash/media/torrents/seeding      → cross-dataset rsync --move to /pool/media/torrents/orphaned_data

RT and qB both report paths under /data/media/... which maps to /stash/media/... on host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

from hashall.rt_cache import DEFAULT_RT_SHARED_CACHE_FILE, DEFAULT_RT_SHARED_CACHE_META_FILE, load_rt_cache_snapshot
from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE


# /data/media in RT/qB container = /stash/media on host
_RT_QBT_DATA_MEDIA = "/data/media"
_HOST_STASH_MEDIA = "/stash/media"

# Where orphaned content lands
ORPHANED_DATA_DEST = Path("/pool/media/torrents/orphaned_data")

# rsync-move script path
RSYNC_MV_SCRIPT = Path.home() / "bin" / "rsync-copy-with-progress.sh"

# Unconditional delete patterns (by filename suffix/prefix)
_BAD_SUFFIXES = (".bad", ".bad.torrent")
_BAD_PREFIXES = ("__hl_tmp__",)

# Depth-1 dirs in seeding root that are NOT content categories; skip them
_SKIP_DEPTH1_NAMES: frozenset[str] = frozenset({
    "orphaned_data",   # legacy destination dir, not a content category
})


@dataclass
class DatasetConfig:
    name: str
    seeding_roots: list[Path]
    dest: Path
    cross_dataset: bool  # True → rsync --move; False → os.rename


DATASETS: list[DatasetConfig] = [
    DatasetConfig(
        name="pool-data",
        seeding_roots=[Path("/pool/data/media/torrents/seeding")],
        dest=ORPHANED_DATA_DEST,
        cross_dataset=True,
    ),
    DatasetConfig(
        name="pool-media",
        seeding_roots=[Path("/pool/media/torrents/seeding")],
        dest=ORPHANED_DATA_DEST,
        cross_dataset=False,
    ),
    DatasetConfig(
        name="stash",
        seeding_roots=[Path("/stash/media/torrents/seeding")],
        dest=ORPHANED_DATA_DEST,
        cross_dataset=True,
    ),
]


@dataclass
class SweepItem:
    path: Path
    tracker_label: str
    dataset_name: str
    cross_dataset: bool
    is_orphan: bool = False
    skip_reason: str = ""          # non-empty → skip (not moved/deleted)
    warn_nlinks: bool = False      # True → nlinks > 1, warn only
    catalog_refs: int = 0          # payload refs in DB
    bad_files_deleted: list[Path] = field(default_factory=list)
    action: str = ""               # "moved", "deleted", "skipped", "dryrun_move", "dryrun_delete"
    dest_path: Path | None = None
    size_bytes: int = 0


def _normalize_container_path(path_str: str) -> str:
    """Map /data/media/... → /stash/media/... for RT/qB reported paths."""
    prefix = _RT_QBT_DATA_MEDIA.rstrip("/") + "/"
    if path_str.startswith(prefix):
        return _HOST_STASH_MEDIA.rstrip("/") + "/" + path_str[len(prefix):]
    if path_str == _RT_QBT_DATA_MEDIA:
        return _HOST_STASH_MEDIA
    return path_str


def build_live_content_paths(
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_max_age_s: float = 3600.0,
) -> tuple[set[str], dict]:
    """
    Load RT and qB caches; return (live_paths_set, diagnostics_dict).

    live_paths_set: set of normalized host-side absolute paths that are
    actively seeded (either the content_path for single-file torrents, or
    the directory/content_path for multi-file).
    """
    diagnostics: dict = {"rt_rows": 0, "qb_rows": 0, "warnings": []}
    live: set[str] = set()

    # --- RT cache ---
    snap = load_rt_cache_snapshot(
        cache_file=rt_cache_file,
        meta_file=DEFAULT_RT_SHARED_CACHE_META_FILE,
        max_age_s=rt_max_age_s,
    )
    rt_rows = snap.get("rows") or []
    diagnostics["rt_rows"] = len(rt_rows)
    diagnostics["rt_freshness"] = snap.get("freshness", "unknown")
    age = snap.get("cache_age_s") or 0
    diagnostics["rt_age_s"] = age

    if snap.get("freshness") in ("missing", "error"):
        diagnostics["warnings"].append(f"RT cache unavailable: {snap.get('last_error') or snap.get('freshness')}")

    for row in rt_rows:
        directory = _normalize_container_path(str(row.get("directory") or "").strip())
        name = str(row.get("name") or "").strip()
        if directory and name:
            content = (directory.rstrip("/") + "/" + name)
            live.add(content)
        if directory:
            live.add(directory.rstrip("/"))

    # --- qB cache ---
    try:
        import json
        qb_path = Path(qb_cache_file).expanduser()
        if qb_path.exists():
            qb_age = time.time() - qb_path.stat().st_mtime
            diagnostics["qb_age_s"] = qb_age
            if qb_age > 3600:
                diagnostics["warnings"].append(f"qB cache is {qb_age/60:.0f}m old")
            qb_data = json.loads(qb_path.read_text(encoding="utf-8"))
            if isinstance(qb_data, list):
                diagnostics["qb_rows"] = len(qb_data)
                for row in qb_data:
                    cp = _normalize_container_path(str(row.get("content_path") or "").strip())
                    sp = _normalize_container_path(str(row.get("save_path") or "").strip())
                    name = str(row.get("name") or "").strip()
                    if cp:
                        live.add(cp.rstrip("/"))
                    if sp and name:
                        live.add((sp.rstrip("/") + "/" + name).rstrip("/"))
                    if sp:
                        live.add(sp.rstrip("/"))
        else:
            diagnostics["warnings"].append(f"qB cache not found: {qb_path}")
    except Exception as exc:
        diagnostics["warnings"].append(f"qB cache error: {exc}")

    return live, diagnostics


def _is_bad_file(name: str) -> bool:
    n = name.lower()
    for suf in _BAD_SUFFIXES:
        if n.endswith(suf):
            return True
    for pre in _BAD_PREFIXES:
        if n.startswith(pre):
            return True
    return False


def _delete_bad_files(root: Path, dry_run: bool) -> list[Path]:
    """Recursively delete .bad.* and __hl_tmp__* files under root. Returns deleted paths."""
    deleted: list[Path] = []
    if root.is_file():
        if _is_bad_file(root.name):
            if not dry_run:
                root.unlink(missing_ok=True)
            deleted.append(root)
        return deleted
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            if _is_bad_file(fname):
                fp = Path(dirpath) / fname
                if not dry_run:
                    fp.unlink(missing_ok=True)
                deleted.append(fp)
    return deleted


def _get_max_nlinks(path: Path) -> int:
    """Return max nlink count across files under path (1 for files, max for dirs)."""
    if path.is_file():
        try:
            return os.stat(path).st_nlink
        except OSError:
            return 1
    max_nl = 1
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                nl = os.stat(os.path.join(dirpath, fname)).st_nlink
                if nl > max_nl:
                    max_nl = nl
            except OSError:
                pass
    return max_nl


def _get_payload_refs(root_path: Path, conn) -> int:
    """Return torrent_instance ref count for any payload rooted at root_path."""
    if conn is None:
        return 0
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(ref_ct), 0)
            FROM (
                SELECT COUNT(*) AS ref_ct
                FROM torrent_instances ti
                JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE p.root_path = ?
            )
            """,
            (str(root_path),),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _get_item_size_bytes(path: Path) -> int:
    """Return total bytes for a file or directory tree."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            file_path = Path(dirpath) / fname
            try:
                total += int(file_path.stat().st_size)
            except OSError:
                continue
    return total


def _free_bytes(path: Path) -> int:
    """Return available bytes on the destination filesystem."""
    try:
        target = path if path.exists() else path.parent
        return int(shutil.disk_usage(target).free)
    except OSError:
        return 0


def _sort_orphan_candidates(
    items: list[SweepItem],
    order: Literal["small-first", "large-first", "input"],
) -> list[SweepItem]:
    if order == "input":
        return list(items)
    reverse = order == "large-first"
    return sorted(items, key=lambda item: (item.size_bytes, str(item.path)), reverse=reverse)


def iter_seeding_items(
    seeding_root: Path,
    live_paths: set[str],
    dataset_name: str,
    cross_dataset: bool,
) -> Iterator[SweepItem]:
    """
    Yield one SweepItem per torrent content item under seeding_root.

    Directory structure handled:
      <root>/cross-seed/<prowlarr-tracker>/<item>          depth-3
      <root>/cross-seed-link/<prowlarr-tracker>/<item>     depth-3 (legacy, treat same)
      <root>/<tracker-or-category>/<item>                  depth-2
      <root>/<loose-item>                                  depth-1 (seeded directly here)
    """
    if not seeding_root.is_dir():
        return

    for entry in sorted(seeding_root.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.name in _SKIP_DEPTH1_NAMES:
            continue

        # cross-seed and cross-seed-link: container of tracker subdirs
        if entry.is_dir() and entry.name in ("cross-seed", "cross-seed-link"):
            for tracker_dir in sorted(entry.iterdir()):
                if not tracker_dir.is_dir() or tracker_dir.name.startswith("."):
                    continue
                try:
                    tracker_children = sorted(tracker_dir.iterdir())
                except PermissionError:
                    continue
                if not tracker_children:
                    yield SweepItem(
                        path=tracker_dir,
                        tracker_label=tracker_dir.name,
                        dataset_name=dataset_name,
                        cross_dataset=cross_dataset,
                        is_orphan=True,
                        skip_reason="empty_dir",
                    )
                    continue
                for item in tracker_children:
                    if item.name.startswith("."):
                        continue
                    is_live = str(item).rstrip("/") in live_paths
                    yield SweepItem(
                        path=item,
                        tracker_label=tracker_dir.name,
                        dataset_name=dataset_name,
                        cross_dataset=cross_dataset,
                        is_orphan=not is_live,
                    )
            continue

        # For other depth-1 entries: is it a direct seeded item or a category container?
        is_direct_item = (
            entry.is_file()
            or str(entry).rstrip("/") in live_paths
        )

        if is_direct_item:
            is_live = str(entry).rstrip("/") in live_paths
            yield SweepItem(
                path=entry,
                tracker_label="uncategorized",
                dataset_name=dataset_name,
                cross_dataset=cross_dataset,
                is_orphan=not is_live,
            )
        elif entry.is_dir():
            # Treat as category/tracker container; iterate children
            try:
                children = sorted(entry.iterdir())
            except PermissionError:
                continue
            if not children:
                # Empty category dir — mark for deletion, not relocation
                yield SweepItem(
                    path=entry,
                    tracker_label=entry.name,
                    dataset_name=dataset_name,
                    cross_dataset=cross_dataset,
                    is_orphan=True,
                    skip_reason="empty_dir",
                )
                continue
            for item in children:
                if item.name.startswith("."):
                    continue
                is_live = str(item).rstrip("/") in live_paths
                yield SweepItem(
                    path=item,
                    tracker_label=entry.name,
                    dataset_name=dataset_name,
                    cross_dataset=cross_dataset,
                    is_orphan=not is_live,
                )


def _move_cross_dataset(src: Path, dest_dir: Path, dry_run: bool, rsync_script: Path) -> None:
    """Use rsync --move to transfer src to dest_dir/."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(rsync_script), "--move"]
    if dry_run:
        cmd.append("--dryrun")
    cmd += [str(src), str(dest_dir) + "/"]
    subprocess.run(cmd, check=True)


def _move_same_dataset(src: Path, dest_dir: Path, dry_run: bool) -> Path:
    """Atomic rename within same ZFS dataset."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if not dry_run:
        # Handle name collision
        if dest.exists():
            stem = src.stem if src.is_file() else src.name
            suffix = src.suffix if src.is_file() else ""
            ts = int(time.time())
            dest = dest_dir / f"{stem}_{ts}{suffix}"
        src.rename(dest)
    return dest


def run_orphan_sweep(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    db_path: Path | None = None,
    rsync_script: Path = RSYNC_MV_SCRIPT,
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    datasets: list[DatasetConfig] | None = None,
    skip_live_warn: bool = False,
    verbose: bool = False,
    order: Literal["small-first", "large-first", "input"] = "input",
    reserve_gib: int = 0,
    dataset_names: set[str] | None = None,
) -> dict:
    """
    Main entry point for orphan sweep.

    Returns summary dict with counts and per-item results.
    """
    if datasets is None:
        datasets = DATASETS

    live_paths, cache_diag = build_live_content_paths(
        rt_cache_file=rt_cache_file,
        qb_cache_file=qb_cache_file,
    )

    conn = None
    if db_path:
        try:
            from hashall.model import connect_db
            conn = connect_db(Path(db_path), read_only=True, apply_migrations=False)
        except Exception:
            pass

    results: list[SweepItem] = []
    orphan_candidates: list[SweepItem] = []
    moved = 0
    skipped = 0
    skipped_space = 0
    warned = 0
    bad_deleted = 0
    bytes_planned = 0
    bytes_moved = 0

    reserve_bytes = max(0, int(reserve_gib)) * 1024 * 1024 * 1024

    for ds in datasets:
        if dataset_names and ds.name not in dataset_names:
            continue
        for seeding_root in ds.seeding_roots:
            if not seeding_root.is_dir():
                if verbose:
                    print(f"  skip missing root: {seeding_root}")
                continue

            for item in iter_seeding_items(seeding_root, live_paths, ds.name, ds.cross_dataset):
                # Always clean bad files regardless of live status
                bad = _delete_bad_files(item.path, dry_run=dry_run)
                item.bad_files_deleted = bad
                bad_deleted += len(bad)

                if not item.is_orphan:
                    if verbose and not skip_live_warn:
                        print(f"  live: {item.path}")
                    results.append(item)
                    continue

                # Check catalog refs (hitchhiker guard)
                if item.skip_reason != "empty_dir":
                    refs = _get_payload_refs(item.path, conn)
                    item.catalog_refs = refs
                    if refs > 0:
                        item.skip_reason = f"catalog refs={refs} (hitchhiker group, Docker's lane)"
                        item.action = "skipped"
                        skipped += 1
                        results.append(item)
                        continue

                # Check nlinks
                if item.skip_reason != "empty_dir":
                    max_nl = _get_max_nlinks(item.path)
                    if max_nl > 1:
                        item.warn_nlinks = True
                        warned += 1

                    item.size_bytes = _get_item_size_bytes(item.path)
                orphan_candidates.append(item)

    selected_candidates = _sort_orphan_candidates(orphan_candidates, order=order)
    if limit is not None:
        selected_candidates = selected_candidates[: max(0, int(limit))]

    for item in selected_candidates:
        ds = next(ds for ds in datasets if ds.name == item.dataset_name)
        dest_tracker_dir = ds.dest / item.tracker_label
        item.dest_path = dest_tracker_dir / item.path.name

        if item.skip_reason == "empty_dir":
            if dry_run:
                item.action = "dryrun_delete"
            else:
                try:
                    item.path.rmdir()
                    item.action = "deleted"
                except OSError as exc:
                    item.action = "skipped"
                    item.skip_reason = f"rmdir failed: {exc}"
            skipped += 1
            results.append(item)
            continue

        available = _free_bytes(dest_tracker_dir)
        budget = max(0, available - reserve_bytes)
        if item.cross_dataset and item.size_bytes > budget:
            item.skip_reason = (
                f"insufficient destination space: need {item.size_bytes} bytes, budget {budget} bytes"
            )
            item.action = "skipped"
            skipped += 1
            skipped_space += 1
            results.append(item)
            continue

        bytes_planned += item.size_bytes

        if dry_run:
            item.action = "dryrun_move"
            moved += 1
            bytes_moved += item.size_bytes
            results.append(item)
            continue

        try:
            if item.cross_dataset:
                _move_cross_dataset(item.path, dest_tracker_dir, dry_run=False, rsync_script=rsync_script)
            else:
                item.dest_path = _move_same_dataset(item.path, dest_tracker_dir, dry_run=False)
            item.action = "moved"
            moved += 1
            bytes_moved += item.size_bytes
        except Exception as exc:
            item.skip_reason = f"move failed: {exc}"
            item.action = "skipped"
            skipped += 1

        results.append(item)

    if conn:
        conn.close()

    return {
        "dry_run": dry_run,
        "cache_diag": cache_diag,
        "items": results,
        "moved": moved,
        "skipped": skipped,
        "skipped_space": skipped_space,
        "warned_nlinks": warned,
        "bad_deleted": bad_deleted,
        "bytes_planned": bytes_planned,
        "bytes_moved": bytes_moved,
    }
