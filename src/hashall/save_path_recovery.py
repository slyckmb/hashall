"""
Save-path recovery: repair hashes displaced by the broken save-path-repair run.

The original save-path-repair had two critical bugs:
  1. _move_tree used relative_to(src.parent) instead of relative_to(src),
     so files landed at dst_parent/<hash_dir>/content instead of dst_parent/content.
  2. dst_parent was set to canonical.parent instead of canonical,
     so files ended up at parent_of_canonical/<hash_dir>/content.

Combined effect by group:
  - Group A (40-char hash dirs, old splits): files at cross-seed/<hash40>/content
    qB save_path was updated to canonical (set_location succeeded)
  - Group B (16-char hash dirs, new splits): files at /stash/media/torrents/<hash16>/content
    qB save_path was NOT updated (still points to _rehome-unique/<hash16>)
    qB/RT were not repointed (lookup failed due to 16-char vs 40-char mismatch)

Recovery plan:
  1. Identify all missingFiles hashes from qB (live API for fresh state)
  2. For each: locate displaced files on filesystem
  3. Move files from displaced location to correct canonical location
  4. Stop qB once
  5. Patch all fastresumes in one batch
  6. Start qB
  7. Recheck all hashes
  8. Fix RT repoints (best-effort, may be stale)
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .qbittorrent import (
    QBittorrentClient,
    DEFAULT_QB_CACHE_FILE,
    get_torrents_from_cache,
)
from .rt_cache import load_rt_cache_snapshot
from .save_path_inference import infer_canonical_save_path
from .rtorrent import rt_apply_directory_repoint, DEFAULT_RT_RPC_URL
from .utils import find_db_path
from .save_path_repair import (
    DEFAULT_QB_CONTAINER,
    DEFAULT_QB_API_URL,
    _docker_stop_qb,
    _docker_start_qb,
)

# Filesystem roots where displaced files might live.
# Each root was dst_parent = parent_of_canonical for the corresponding category:
#   uncategorized → canonical=/stash/.../seeding  → dst_parent=/stash/.../torrents
#   movies/tv/etc → canonical=/stash/.../seeding/<cat> → dst_parent=/stash/.../seeding
#   cross-seed    → canonical=/stash/.../cross-seed/<prov> → dst_parent=/stash/.../cross-seed
_DISPLACED_SEARCH_ROOTS: list[str] = [
    "/stash/media/torrents",                     # uncategorized stash
    "/stash/media/torrents/seeding",             # movies/tv/other stash categories
    "/stash/media/torrents/seeding/cross-seed",  # cross-seed stash (parent of provider/)
    "/pool/media/torrents",                      # uncategorized pool
    "/pool/media/torrents/seeding",              # movies/tv/other pool categories
    "/pool/media/torrents/seeding/cross-seed",   # cross-seed pool
]


@dataclass
class RecoveryAction:
    """Planned recovery for one displaced hash."""
    hash_val: str                # full 40-char hash
    category: str
    torrent_name: str
    displaced_path_fs: str       # where files currently are
    canonical_path_fs: str       # where they should go (filesystem)
    canonical_path_api: str      # qB/RT API path
    rt_directory: str            # canonical_path_api (parent only; rTorrent appends info_name itself)
    fastresume_path: str         # path to .fastresume file
    file_count: int              # files to move
    notes: list[str] = field(default_factory=list)


@dataclass
class RecoveryResult:
    """Result of recovering one hash."""
    hash_val: str
    category: str
    torrent_name: str
    success: bool = False
    files_moved: int = 0
    fastresume_patched: bool = False
    rechecked: bool = False
    rt_repointed: bool = False
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _find_displaced_path(hash_val: str) -> Optional[str]:
    """
    Search for displaced files using hash prefix (16 or 40 chars) under known wrong locations.
    Returns the displaced directory Path if found, else None.
    """
    hash16 = hash_val[:16]
    hash40 = hash_val[:40]

    candidates: list[Path] = []
    for root in _DISPLACED_SEARCH_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        # Check both hash16 and hash40 subdirectories
        for suffix in (hash16, hash40):
            candidate = root_path / suffix
            if candidate.is_dir():
                candidates.append(candidate)

    for candidate in candidates:
        file_count = sum(1 for f in candidate.rglob("*") if f.is_file())
        if file_count > 0:
            return str(candidate)

    return None


def plan_recovery(
    *,
    qb_client: Optional[QBittorrentClient] = None,
    max_age_s: int = 60,  # use fresh qB state (live fetch preferred)
) -> list[RecoveryAction]:
    """
    Identify all missingFiles hashes and build a recovery plan.

    Fetches live qB state to get full hashes and current metadata.
    Falls back to cache if live fetch fails.
    """
    if qb_client is None:
        qb_client = QBittorrentClient()

    # Fetch fresh qB state (need full hash, current state, category, tags)
    qb_torrents = []
    try:
        all_live = qb_client.get_torrents() or []
        qb_torrents = [t for t in all_live if t.state == "missingFiles"]
    except Exception:
        # Fallback to cache
        try:
            cached_raw = get_torrents_from_cache(max_age_s=max_age_s, cache_path=DEFAULT_QB_CACHE_FILE)
            if cached_raw:
                for r in cached_raw:
                    t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                    if t and t.state == "missingFiles":
                        qb_torrents.append(t)
        except Exception:
            pass

    if not qb_torrents:
        return []

    # Load RT cache for RT info
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception:
        pass

    # Load catalog for save_path hints
    catalog_by_hash: dict = {}
    try:
        db = find_db_path()
        if db is not None:
            hashes = [t.hash for t in qb_torrents if t.hash]
            conn = sqlite3.connect(str(db), timeout=30.0)
            try:
                conn.row_factory = sqlite3.Row
                MAX_VARS = 900
                for i in range(0, len(hashes), MAX_VARS):
                    batch = hashes[i:i + MAX_VARS]
                    placeholders = ",".join("?" * len(batch))
                    rows = conn.execute(
                        f"SELECT torrent_hash, save_path FROM torrent_instances WHERE torrent_hash IN ({placeholders})",
                        batch,
                    ).fetchall()
                    for row in rows:
                        catalog_by_hash[row["torrent_hash"].lower()] = {"save_path": row["save_path"]}
            finally:
                conn.close()
    except Exception:
        pass

    actions: list[RecoveryAction] = []

    for t in qb_torrents:
        if not t.hash:
            continue
        hash_val = t.hash.lower()
        qb_category = t.category or ""
        qb_tags = t.tags or ""  # already a comma-separated string
        rt_info = rt_by_hash.get(hash_val, {})
        catalog_info = catalog_by_hash.get(hash_val, {})

        inferred = infer_canonical_save_path(
            category=qb_category,
            tags=qb_tags,
            current_save_path=catalog_info.get("save_path", ""),
            current_rt_directory=rt_info.get("directory", ""),
        )

        if not inferred.canonical_save_path or inferred.canonical_save_path.endswith("/-"):
            continue  # skip malformed

        # Filesystem path
        if inferred.device == "stash":
            canonical_fs = inferred.canonical_save_path.replace("/data/media", "/stash/media")
        else:
            canonical_fs = inferred.canonical_save_path

        torrent_name = t.name or ""
        # RT d.directory.set takes the parent; rTorrent appends info_name itself
        rt_directory = inferred.canonical_save_path

        # Find displaced files
        displaced = _find_displaced_path(hash_val)

        # FastResume path
        fastresume_path = str(qb_client._fastresume_path(hash_val))

        # Count files in displaced location
        file_count = 0
        if displaced:
            file_count = sum(1 for f in Path(displaced).rglob("*") if f.is_file())

        notes = []
        if not displaced:
            notes.append("WARNING: displaced files not found in known locations")
        if not Path(fastresume_path).exists():
            notes.append(f"WARNING: fastresume file not found: {fastresume_path}")

        actions.append(RecoveryAction(
            hash_val=hash_val,
            category=qb_category or "uncategorized",
            torrent_name=torrent_name,
            displaced_path_fs=displaced or "",
            canonical_path_fs=canonical_fs,
            canonical_path_api=inferred.canonical_save_path,
            rt_directory=rt_directory,
            fastresume_path=fastresume_path,
            file_count=file_count,
            notes=notes,
        ))

    return actions


def _move_displaced_to_canonical(
    src: Path,
    dst: Path,
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """
    Move contents of src (displaced hash dir) into dst (canonical save_path dir).
    Each top-level item in src moves into dst directly.

    If dst_file already exists (cross-seed duplicate from another hash):
      - Same size: skip the move (file is already there, just from another seeder).
      - Different size: skip with a note (name collision, needs manual review).
    In both skip cases the displaced source file is left in place.

    Returns (files_moved, files_skipped_already_exist).
    """
    moved = 0
    skipped = 0
    if not dry_run and src.exists():
        src_stat = src.stat()
        dst.mkdir(parents=True, exist_ok=True)
        dst_stat = dst.stat()
        if src_stat.st_dev != dst_stat.st_dev:
            raise RuntimeError(
                f"cross-filesystem move rejected: src={src} dev={src_stat.st_dev} "
                f"dst={dst} dev={dst_stat.st_dev}"
            )
    for item in sorted(src.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src)  # relative to displaced dir (NOT src.parent)
        dst_file = dst / rel
        if dst_file.exists():
            # Cross-seed duplicate: file already at canonical — skip move
            skipped += 1
            continue
        if not dry_run:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dst_file))
        moved += 1
    return moved, skipped


def execute_recovery(
    actions: list[RecoveryAction],
    *,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    qb_container: str = DEFAULT_QB_CONTAINER,
    qb_url: str = DEFAULT_QB_API_URL,
) -> list[RecoveryResult]:
    """
    Execute recovery for all planned actions.

    Live workflow:
      1. Move files for all hashes (filesystem only)
      2. Stop qB once
      3. Patch fastresumes for all hashes in one batch
      4. Start qB
      5. Recheck all hashes via live qB API
      6. Repoint RT for each hash (best-effort)
    """
    from .fastresume import patch_fastresume_file

    if qb_client is None:
        qb_client = QBittorrentClient()

    results: list[RecoveryResult] = []
    move_results: dict[str, tuple[int, Optional[str]]] = {}  # hash → (files_moved, error)

    # --- Phase 1: Move files ---
    for action in actions:
        r = RecoveryResult(
            hash_val=action.hash_val,
            category=action.category,
            torrent_name=action.torrent_name,
        )
        results.append(r)

        if not action.displaced_path_fs:
            r.error = "no displaced files found"
            r.notes.append("SKIP: files not located on filesystem")
            move_results[action.hash_val] = (0, r.error)
            continue

        src = Path(action.displaced_path_fs)
        dst = Path(action.canonical_path_fs)

        try:
            files_moved, files_skipped = _move_displaced_to_canonical(src, dst, dry_run=dry_run)
            r.files_moved = files_moved
            move_results[action.hash_val] = (files_moved, None)
            verb = "[dry-run] would move" if dry_run else "moved"
            r.notes.append(f"{verb} {files_moved} files → {action.canonical_path_fs}")
            if files_skipped:
                r.notes.append(
                    f"{files_skipped} files already at canonical (cross-seed dup), skipped"
                )
        except Exception as exc:
            r.error = str(exc)
            r.notes.append(f"move FAILED: {exc}")
            move_results[action.hash_val] = (0, str(exc))

    if dry_run:
        for r in results:
            r.notes.append("dry-run: no qB/fastresume/RT changes made")
        return results

    # --- Phase 2: Stop qB, patch fastresumes, start qB ---
    actions_to_patch = [
        a for a in actions
        if move_results.get(a.hash_val, (0, "skip"))[1] is None  # only moved successfully
        and Path(a.fastresume_path).exists()
    ]

    if actions_to_patch:
        try:
            _docker_stop_qb(qb_container)
        except Exception as exc:
            for r in results:
                r.notes.append(f"qB stop FAILED: {exc} — fastresume not patched")
            # Try to start qB back up even if stop had issues
            try:
                _docker_start_qb(qb_container, qb_url)
            except Exception:
                pass
            return results

        patch_errors: list[str] = []
        try:
            for action in actions_to_patch:
                result_for_hash = next((r for r in results if r.hash_val == action.hash_val), None)
                try:
                    patch_fastresume_file(
                        Path(action.fastresume_path),
                        action.canonical_path_api,
                        ".bak-recovery",
                    )
                    if result_for_hash:
                        result_for_hash.fastresume_patched = True
                        result_for_hash.notes.append(
                            f"fastresume patched → {action.canonical_path_api}"
                        )
                except Exception as exc:
                    patch_errors.append(f"{action.hash_val[:16]}: {exc}")
                    if result_for_hash:
                        result_for_hash.notes.append(f"fastresume patch FAILED: {exc}")
        finally:
            _docker_start_qb(qb_container, qb_url)

        if patch_errors:
            for r in results:
                r.notes.append(f"patch errors ({len(patch_errors)}): see per-hash notes")

    # --- Phase 3: Recheck all successfully moved hashes ---
    hashes_to_recheck = [
        a.hash_val for a in actions
        if move_results.get(a.hash_val, (0, "skip"))[1] is None
    ]
    if hashes_to_recheck:
        try:
            qb_client.recheck_torrents(hashes_to_recheck)
            for h in hashes_to_recheck:
                result_for_hash = next((r for r in results if r.hash_val == h), None)
                if result_for_hash:
                    result_for_hash.rechecked = True
                    result_for_hash.notes.append("recheck triggered")
        except Exception as exc:
            for r in results:
                if r.hash_val in hashes_to_recheck:
                    r.notes.append(f"recheck failed: {exc}")

    # --- Phase 4: Repoint RT (best-effort per hash) ---
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(row.get("hash") or "").lower(): row for row in rows}
    except Exception:
        pass

    for action in actions:
        result_for_hash = next((r for r in results if r.hash_val == action.hash_val), None)
        if move_results.get(action.hash_val, (0, "skip"))[1] is not None:
            continue  # skip failed moves
        if not rt_by_hash.get(action.hash_val):
            continue  # not in RT cache, skip

        try:
            rt_apply_directory_repoint(
                action.hash_val,
                action.rt_directory,
                rpc_url=rpc_url,
                restart=True,
            )
            if result_for_hash:
                result_for_hash.rt_repointed = True
                result_for_hash.notes.append(f"RT repointed → {action.rt_directory}")
        except Exception as exc:
            if result_for_hash:
                result_for_hash.notes.append(f"RT repoint failed: {exc}")

    # Mark overall success: success if no error (whether files moved or already at canonical)
    for r in results:
        if r.error is None:
            r.success = True

    return results


def format_recovery_report(
    actions: list[RecoveryAction],
    results: list[RecoveryResult],
    *,
    dry_run: bool,
    json_output: bool = False,
) -> str:
    """Format recovery plan and results for output."""
    if json_output:
        import json
        return json.dumps(
            {
                "dry_run": dry_run,
                "planned": [
                    {
                        "hash": a.hash_val[:16],
                        "category": a.category,
                        "torrent_name": a.torrent_name,
                        "displaced_from": a.displaced_path_fs,
                        "canonical_to": a.canonical_path_api,
                        "file_count": a.file_count,
                        "fastresume": a.fastresume_path,
                        "notes": a.notes,
                    }
                    for a in actions
                ],
                "results": [
                    {
                        "hash": r.hash_val[:16],
                        "success": r.success,
                        "files_moved": r.files_moved,
                        "fastresume_patched": r.fastresume_patched,
                        "rechecked": r.rechecked,
                        "rt_repointed": r.rt_repointed,
                        "error": r.error,
                        "notes": r.notes,
                    }
                    for r in results
                ],
            },
            indent=2,
        )

    lines = []
    mode = "DRY-RUN" if dry_run else "EXECUTE"

    if results:
        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if r.error)
        no_files = sum(1 for r in results if r.files_moved == 0 and not r.error)
        lines.append(f"Save-Path Recovery [{mode}]: {len(results)} hashes")
        lines.append(f"  Succeeded: {succeeded}  Failed: {failed}  No-files: {no_files}")
        lines.append("")
        for r in results:
            status = "OK" if r.success else ("ERR" if r.error else "SKIP")
            extra = ""
            if r.fastresume_patched:
                extra += " [fr]"
            if r.rechecked:
                extra += " [chk]"
            if r.rt_repointed:
                extra += " [rt]"
            lines.append(f"  [{status}] {r.hash_val[:16]}  cat={r.category}  files={r.files_moved}{extra}")
            if r.error:
                lines.append(f"        error: {r.error}")
            for note in r.notes:
                lines.append(f"        {note}")
    else:
        # Dry-run plan only
        no_files = sum(1 for a in actions if not a.displaced_path_fs)
        lines.append(f"Save-Path Recovery [PLAN]: {len(actions)} candidates")
        lines.append(f"  No displaced files found: {no_files}")
        lines.append("")
        for a in actions:
            found = "FOUND" if a.displaced_path_fs else "MISSING"
            lines.append(
                f"  [{found}] {a.hash_val[:16]}  cat={a.category}  files={a.file_count}"
            )
            lines.append(f"          from: {a.displaced_path_fs or '?'}")
            lines.append(f"          to:   {a.canonical_path_api}")
            for note in a.notes:
                lines.append(f"          {note}")

    return "\n".join(lines)
