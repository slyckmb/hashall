"""
Nested-folder repair: move doubly-nested torrent content to its canonical location.

Doubly-nested: QB content_path is a directory whose name matches the torrent name,
AND inside that directory another directory with the same name exists.

Single-file example:
  movies/TorrentName/TorrentName/file.mkv  → movies/file.mkv
  (QB save_path stays movies/, RT repointed to movies/)

Multi-file example:
  movies/TorrentName/TorrentName/file1 file2  → movies/TorrentName/file1 file2
  (QB save_path stays movies/, RT stays at movies/TorrentName/)
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rt_cache import load_rt_cache_snapshot
from .rtorrent import rt_apply_directory_repoint, DEFAULT_RT_RPC_URL
from .save_path_repair import _move_tree

# API→FS path aliases (QB and RT report /data/media, host FS uses /stash/media)
_API_TO_FS: list[tuple[str, str]] = [
    ("/data/media", "/stash/media"),
]
_FS_TO_API: list[tuple[str, str]] = [
    ("/stash/media", "/data/media"),
]


def _api_to_fs(path: str) -> str:
    for api_prefix, fs_prefix in _API_TO_FS:
        if path.startswith(api_prefix):
            return fs_prefix + path[len(api_prefix):]
    return path


def _fs_to_api(path: str) -> str:
    for fs_prefix, api_prefix in _FS_TO_API:
        if path.startswith(fs_prefix):
            return api_prefix + path[len(fs_prefix):]
    return path


def _count_files(directory: Path) -> int:
    return sum(1 for p in directory.rglob("*") if p.is_file())


@dataclass
class NestedFolderInfo:
    """Detected doubly-nested layout for one torrent."""
    hash_val: str
    torrent_name: str
    save_path_api: str      # QB save_path (API form)
    save_path_fs: str       # save_path on host FS
    content_path_api: str   # QB content_path (API form, is a dir)
    content_path_fs: str    # content_path on host FS
    nested_dir_fs: str      # doubly-nested dir: content_path_fs/torrent_name
    file_count: int         # files inside nested_dir
    is_single_file: bool    # True if file_count == 1


@dataclass
class NestedFolderRepairResult:
    """Result of nested-folder repair for one torrent."""
    hash_val: str
    torrent_name: str
    success: bool = False
    error: Optional[str] = None
    dry_run: bool = True
    files_moved: int = 0
    rt_repointed: bool = False
    notes: list[str] = field(default_factory=list)


def detect_nested_folder(
    hash_val: str,
    *,
    qb_client: Optional[QBittorrentClient] = None,
    qb_cache_max_age_s: int = 300,
) -> Optional[NestedFolderInfo]:
    """
    Check if a torrent's content is doubly-nested on the filesystem.

    Detection: save_path / torrent_name / torrent_name exists as a directory.
    QB reports content_path as the actual file/dir deep inside the nesting, so
    we use save_path + torrent_name to find the two-level nested structure.

    Returns NestedFolderInfo if doubly-nested, None otherwise.
    hash_val may be a prefix (16 chars) or full 40-char hash.
    """
    if qb_client is None:
        qb_client = QBittorrentClient()

    qb_torrent = None
    prefix = hash_val.lower()
    try:
        cached = get_torrents_from_cache(max_age_s=qb_cache_max_age_s, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached is not None:
            for r in cached:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash and t.hash.lower().startswith(prefix):
                    qb_torrent = t
                    break
        if qb_torrent is None:
            live = qb_client.get_torrents_by_hashes([hash_val]) or {}
            for h, t in live.items():
                if h.lower().startswith(prefix):
                    qb_torrent = t
                    break
    except Exception:
        pass

    if qb_torrent is None:
        return None

    torrent_name = qb_torrent.name or ""
    save_path_api = (qb_torrent.save_path or "").rstrip("/") + "/"
    content_path_api = qb_torrent.content_path or ""

    if not torrent_name or not save_path_api:
        return None

    save_path_fs = _api_to_fs(save_path_api.rstrip("/"))
    content_path_fs = _api_to_fs(content_path_api) if content_path_api else ""

    # Outer dir: save_path / torrent_name  (the first level of nesting)
    outer = Path(save_path_fs) / torrent_name
    if not outer.is_dir():
        return None

    # Inner dir: outer / torrent_name  (the doubly-nested dir containing actual files)
    inner = outer / torrent_name
    if not inner.is_dir():
        return None

    file_count = _count_files(inner)

    return NestedFolderInfo(
        hash_val=qb_torrent.hash.lower(),
        torrent_name=torrent_name,
        save_path_api=save_path_api,
        save_path_fs=save_path_fs,
        content_path_api=content_path_api,
        content_path_fs=content_path_fs,
        nested_dir_fs=str(inner),
        file_count=file_count,
        is_single_file=file_count == 1,
    )


def execute_nested_folder_repair(
    info: NestedFolderInfo,
    *,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> NestedFolderRepairResult:
    """
    Move doubly-nested content to its canonical location, then update both clients.

    Single-file: nested_dir/* → save_path_fs; remove nested_dir + content_path dir;
                 RT repointed to save_path_api (parent of file).
    Multi-file:  nested_dir/* → content_path_fs; remove nested_dir;
                 RT stays at content_path_api (already the torrent root).
    After: QB recheck triggered in both cases.
    """
    result = NestedFolderRepairResult(
        hash_val=info.hash_val,
        torrent_name=info.torrent_name,
        dry_run=dry_run,
    )

    if qb_client is None:
        qb_client = QBittorrentClient()

    nested = Path(info.nested_dir_fs)           # save_path / torrent_name / torrent_name
    outer = Path(info.save_path_fs) / info.torrent_name  # save_path / torrent_name
    save_path = Path(info.save_path_fs)
    outer_api = info.save_path_api.rstrip("/") + "/" + info.torrent_name

    try:
        if info.is_single_file:
            # Move file(s) from doubly-nested dir directly into save_path
            target = save_path
            rt_new_dir = info.save_path_api.rstrip("/")
            result.notes.append(f"single-file repair: {nested} → {target}")
        else:
            # Move files from inner dir up one level into the torrent root (outer)
            target = outer
            rt_new_dir = outer_api
            result.notes.append(f"multi-file repair: {nested}/* → {target}")

        result.files_moved = _move_tree(nested, target, dry_run=dry_run)

        if not dry_run:
            # Remove now-empty inner (nested) dir
            if nested.exists() and not list(nested.iterdir()):
                shutil.rmtree(str(nested))
                result.notes.append(f"removed: {nested}")

            # Single-file: also remove the outer dir (save_path/torrent_name) — now empty wrapper
            if info.is_single_file and outer.exists() and not list(outer.iterdir()):
                shutil.rmtree(str(outer))
                result.notes.append(f"removed: {outer}")

            # QB recheck — save_path is unchanged; recheck finds content at corrected location
            try:
                qb_client.recheck_torrent(info.hash_val)
                result.notes.append("QB recheck triggered")
            except Exception as e:
                result.notes.append(f"QB recheck failed: {e}")

            # RT repoint
            try:
                snapshot = load_rt_cache_snapshot() or {}
                rows = snapshot.get("rows") or []
                rt_hashes = {str(r.get("hash") or "").lower() for r in rows}
                if info.hash_val in rt_hashes:
                    rt_apply_directory_repoint(
                        info.hash_val,
                        rt_new_dir,
                        rpc_url=rpc_url,
                        restart=True,
                    )
                    result.rt_repointed = True
                    result.notes.append(f"RT repointed → {rt_new_dir}")
                else:
                    result.notes.append("RT: hash not in cache, skipping repoint")
            except Exception as e:
                result.notes.append(f"RT repoint failed: {e}")

        result.success = True
        result.notes.append(
            f"{'[dry-run] would move' if dry_run else 'moved'} {result.files_moved} files"
        )

    except Exception as e:
        result.error = str(e)
        result.notes.append(f"FAILED: {e}")

    if dry_run:
        result.notes.append("dry-run: no files moved, no client changes made")

    return result


def format_nested_folder_repair_report(
    info: Optional[NestedFolderInfo],
    result: Optional[NestedFolderRepairResult],
    *,
    dry_run: bool,
) -> str:
    lines: list[str] = []
    mode = "DRY-RUN" if dry_run else "EXECUTE"

    if info is None:
        lines.append(f"Nested-Folder Repair [{mode}]: no doubly-nested layout detected")
        return "\n".join(lines)

    lines.append(f"Nested-Folder Repair [{mode}]")
    lines.append(f"  hash:          {info.hash_val[:16]}")
    lines.append(f"  torrent_name:  {info.torrent_name}")
    lines.append(f"  type:          {'single-file' if info.is_single_file else 'multi-file'}")
    lines.append(f"  nested_dir:    {info.nested_dir_fs}")
    lines.append(f"  file_count:    {info.file_count}")
    outer = info.save_path_fs.rstrip("/") + "/" + info.torrent_name
    outer_api = info.save_path_api.rstrip("/") + "/" + info.torrent_name
    if info.is_single_file:
        lines.append(f"  target:        {info.save_path_fs} (RT → {info.save_path_api.rstrip('/')})")
    else:
        lines.append(f"  target:        {outer} (RT → {outer_api})")

    if result is not None:
        lines.append("")
        status = "OK" if result.success else "ERR"
        lines.append(f"  status:        {status}")
        if result.error:
            lines.append(f"  error:         {result.error}")
        for note in result.notes:
            lines.append(f"    {note}")

    return "\n".join(lines)
