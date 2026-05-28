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
from typing import Any, Optional

from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rt_cache import load_rt_cache_snapshot
from .rtorrent import rt_apply_directory_repoint, rt_xmlrpc_call, load_rt_torrent_meta, DEFAULT_RT_RPC_URL, DEFAULT_RT_SESSION_DIR
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
    save_path_api: str      # QB save_path (API form); synthesized for RT-only
    save_path_fs: str       # save_path on host FS
    content_path_api: str   # QB content_path (API form, is a dir)
    content_path_fs: str    # content_path on host FS
    nested_dir_fs: str      # doubly-nested dir: content_path_fs/torrent_name
    file_count: int         # files inside nested_dir
    is_single_file: bool    # True if file_count == 1
    qb_absent: bool = False  # True when torrent is RT-only; skip QB API steps in repair


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


@dataclass
class NestedFolderScanHit:
    """One doubly-nested detection hit from a cache-wide scan."""
    hash_val: str
    torrent_name: str
    qb_nested: bool                    # nesting detected from QB data
    rt_nested: bool                    # nesting detected from RT d.directory
    info: Optional[NestedFolderInfo]   # QB-derived repair info (if qb_nested)
    rt_directory_fs: Optional[str]     # RT d.directory on host FS
    rt_nested_dir_fs: Optional[str]    # RT-derived nested dir (dir to flatten)
    rt_save_path_fs: Optional[str]     # RT-derived canonical save_path
    file_count: int
    is_single_file: bool

    @property
    def source(self) -> str:
        if self.qb_nested and self.rt_nested:
            return "both"
        if self.qb_nested:
            return "qb_only"
        return "rt_only"


def _detect_qb_nesting_from_torrent(
    qb_torrent: Any,
    torrent_meta: Any,
) -> Optional[NestedFolderInfo]:
    """
    Core QB nesting detection from a resolved torrent object (no cache lookup).
    Factored out of detect_nested_folder() so the bulk scan can reuse it.
    """
    torrent_name = qb_torrent.name or ""
    save_path_api = (qb_torrent.save_path or "").rstrip("/") + "/"
    content_path_api = qb_torrent.content_path or ""

    if not torrent_name or not save_path_api.strip("/"):
        return None

    save_path_fs = _api_to_fs(save_path_api.rstrip("/"))
    content_path_fs = _api_to_fs(content_path_api) if content_path_api else ""

    outer = Path(save_path_fs) / torrent_name
    if not outer.is_dir():
        return None

    inner = outer / torrent_name
    if inner.is_dir():
        # Verify the canonical files are actually in the nested dir, not already at the
        # correct depth. In cross-seed environments, save_path/name/name/ may exist as
        # a different torrent's content_path — layout-pass means no repair needed.
        torrent_path = DEFAULT_RT_SESSION_DIR / f"{qb_torrent.hash.upper()}.torrent"
        if torrent_path.exists():
            from .torrent_verify import verify_layout
            layout = verify_layout(torrent_path, Path(save_path_fs))
            if layout.success:
                return None  # files already at correct depth; inner dir is another torrent
        file_count = _count_files(inner)
        is_single_file = torrent_meta is not None and not torrent_meta.is_multi_file
        return NestedFolderInfo(
            hash_val=qb_torrent.hash.lower(),
            torrent_name=torrent_name,
            save_path_api=save_path_api,
            save_path_fs=save_path_fs,
            content_path_api=content_path_api,
            content_path_fs=content_path_fs,
            nested_dir_fs=str(inner),
            file_count=file_count,
            is_single_file=is_single_file,
        )

    if Path(save_path_fs).name == torrent_name:
        corrected_save_path_fs = save_path_fs
        while Path(corrected_save_path_fs).name == torrent_name:
            corrected_save_path_fs = str(Path(corrected_save_path_fs).parent)
        corrected_save_path_api = _fs_to_api(corrected_save_path_fs).rstrip("/") + "/"
        nested_dir_for_case2 = Path(save_path_fs) / torrent_name
        if not nested_dir_for_case2.is_dir():
            return None
        # Same layout guard for Case 2: if corrected save_path yields a passing layout,
        # files are already correct and no repair is needed.
        torrent_path = DEFAULT_RT_SESSION_DIR / f"{qb_torrent.hash.upper()}.torrent"
        if torrent_path.exists():
            from .torrent_verify import verify_layout
            layout = verify_layout(torrent_path, Path(corrected_save_path_fs))
            if layout.success:
                return None
        file_count = _count_files(nested_dir_for_case2)
        is_single_file = torrent_meta is not None and not torrent_meta.is_multi_file
        return NestedFolderInfo(
            hash_val=qb_torrent.hash.lower(),
            torrent_name=torrent_name,
            save_path_api=corrected_save_path_api,
            save_path_fs=corrected_save_path_fs,
            content_path_api=content_path_api,
            content_path_fs=content_path_fs,
            nested_dir_fs=str(nested_dir_for_case2),
            file_count=file_count,
            is_single_file=is_single_file,
        )

    return None


def _detect_rt_nesting(
    rt_directory_fs: str,
    info_name: str,
    is_multi_file: bool,
    *,
    torrent_path: Optional[Path] = None,
) -> tuple[bool, Optional[str]]:
    """
    Check if RT's d.directory indicates doubly-nested content on disk.
    Returns (is_nested, nested_dir_fs).

    Multi-file: d.directory = save_path/info_name (torrent root as RT sees it).
      Case A: files are at d.directory/info_name/... (correct root, content too deep).
      Case B: d.directory itself = save_path/TN/TN (RT was set to the wrong level).

    Single-file: d.directory = save_path.
      Case A: save_path/info_name/info_name dir exists.
      Case B: save_path itself ends in /info_name (corrupted save_path).

    torrent_path: if provided, runs layout verify to filter cross-seed false positives.
    """
    directory = Path(rt_directory_fs)
    if is_multi_file:
        inner = directory / info_name
        if inner.is_dir():
            # Layout guard: if torrent file available, confirm files are NOT at correct depth
            if torrent_path and torrent_path.exists():
                from .torrent_verify import verify_layout
                # For RT multi-file: save_path = directory.parent; check layout from there
                save_path = directory.parent
                if verify_layout(torrent_path, save_path).success:
                    return False, None
            return True, str(inner)
        # Case B: RT points to the doubly-nested dir as "torrent root"
        if directory.name == info_name and directory.parent.name == info_name and directory.is_dir():
            if torrent_path and torrent_path.exists():
                from .torrent_verify import verify_layout
                # save_path is two levels up: directory = save_path/TN/TN
                if verify_layout(torrent_path, directory.parent.parent).success:
                    return False, None
            return True, str(directory)
    else:
        inner = directory / info_name / info_name
        if inner.is_dir():
            if torrent_path and torrent_path.exists():
                from .torrent_verify import verify_layout
                if verify_layout(torrent_path, directory).success:
                    return False, None
            return True, str(inner)
        # Case B: save_path itself is corrupted (ends in /info_name)
        if directory.name == info_name:
            inner2 = directory / info_name
            if inner2.is_dir():
                if torrent_path and torrent_path.exists():
                    from .torrent_verify import verify_layout
                    if verify_layout(torrent_path, directory.parent).success:
                        return False, None
                return True, str(inner2)
    return False, None


def _build_rt_only_nested_info(
    hash_val: str,
    rt_row: dict,
    torrent_meta: Any,
    rt_directory_fs: str,
    rt_nested_dir_fs: str,
    rt_save_path_fs: str,
) -> NestedFolderInfo:
    """
    Synthesize a NestedFolderInfo for a torrent that is in RT but not QB.
    Used so the standard repair path works for RT-only torrents.
    """
    info_name = torrent_meta.info_name if torrent_meta else str(rt_row.get("name") or "")
    is_single_file = torrent_meta is not None and not torrent_meta.is_multi_file
    file_count = torrent_meta.file_count if torrent_meta else _count_files(Path(rt_nested_dir_fs))
    save_path_api = _fs_to_api(rt_save_path_fs).rstrip("/") + "/"
    return NestedFolderInfo(
        hash_val=hash_val.lower(),
        torrent_name=info_name,
        save_path_api=save_path_api,
        save_path_fs=rt_save_path_fs,
        content_path_api="",
        content_path_fs="",
        nested_dir_fs=rt_nested_dir_fs,
        file_count=file_count,
        is_single_file=is_single_file,
        qb_absent=True,
    )


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

    torrent_meta = load_rt_torrent_meta(DEFAULT_RT_SESSION_DIR, qb_torrent.hash)
    return _detect_qb_nesting_from_torrent(qb_torrent, torrent_meta)


def scan_nested_folders(
    *,
    qb_cache_max_age_s: int = 300,
    limit: int = 0,
) -> tuple[list[NestedFolderScanHit], int]:
    """
    Scan QB and RT caches for doubly-nested torrent layouts.

    Iterates the union of QB + RT cached hashes. For each hash, runs
    independent QB-side and RT-side detection. Returns (hits, total_scanned)
    where hits are all hashes with double-nesting in either or both clients.
    """
    hits: list[NestedFolderScanHit] = []

    qb_client = QBittorrentClient()
    qb_map: dict[str, Any] = {}
    try:
        cached = get_torrents_from_cache(max_age_s=qb_cache_max_age_s, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached:
            for r in cached:
                t = qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                if t and t.hash:
                    qb_map[t.hash.lower()] = t
    except Exception:
        pass

    rt_snapshot = load_rt_cache_snapshot() or {}
    rt_rows: list[dict] = rt_snapshot.get("rows") or []
    rt_map: dict[str, dict] = {}
    for row in rt_rows:
        h = str(row.get("hash") or "").lower()
        if h:
            rt_map[h] = row

    all_hashes = sorted(set(qb_map) | set(rt_map))
    total_scanned = len(all_hashes)
    count = 0

    for hash_val in all_hashes:
        if limit and count >= limit:
            break

        qb_torrent = qb_map.get(hash_val)
        rt_row = rt_map.get(hash_val)

        torrent_meta = load_rt_torrent_meta(DEFAULT_RT_SESSION_DIR, hash_val)

        # ── QB-side detection
        info: Optional[NestedFolderInfo] = None
        qb_nested = False
        if qb_torrent:
            info = _detect_qb_nesting_from_torrent(qb_torrent, torrent_meta)
            if info:
                qb_nested = True

        # ── RT-side detection
        rt_nested = False
        rt_directory_fs: Optional[str] = None
        rt_nested_dir_fs: Optional[str] = None
        rt_save_path_fs: Optional[str] = None

        if rt_row and torrent_meta:
            rt_dir_raw = _api_to_fs(str(rt_row.get("directory") or "").strip())
            if rt_dir_raw:
                rt_directory_fs = rt_dir_raw
                info_name = torrent_meta.info_name or str(rt_row.get("name") or "")
                is_mf = torrent_meta.is_multi_file
                tp = DEFAULT_RT_SESSION_DIR / f"{hash_val.upper()}.torrent"
                is_rt_nested, nested_dir = _detect_rt_nesting(
                    rt_dir_raw, info_name, is_mf, torrent_path=tp if tp.exists() else None
                )
                if is_rt_nested:
                    rt_nested = True
                    rt_nested_dir_fs = nested_dir
                    directory = Path(rt_dir_raw)
                    if is_mf:
                        # Case B: d.directory = save_path/TN/TN → save_path = parent.parent
                        if directory.name == info_name and directory.parent.name == info_name:
                            rt_save_path_fs = str(directory.parent.parent)
                        else:
                            rt_save_path_fs = str(directory.parent)
                    else:
                        # d.directory = save_path; Case B: ends in /info_name
                        if directory.name == info_name:
                            rt_save_path_fs = str(directory.parent)
                        else:
                            rt_save_path_fs = rt_dir_raw

        if not qb_nested and not rt_nested:
            continue

        torrent_name = ""
        file_count = 0
        is_single_file = False
        if info:
            torrent_name = info.torrent_name
            file_count = info.file_count
            is_single_file = info.is_single_file
        elif torrent_meta:
            torrent_name = torrent_meta.info_name
            file_count = torrent_meta.file_count
            is_single_file = not torrent_meta.is_multi_file
        elif rt_row:
            torrent_name = str(rt_row.get("name") or "")

        # For RT-only hits, build a synthetic NestedFolderInfo so the repair path works
        if rt_nested and not qb_nested and rt_nested_dir_fs and rt_save_path_fs and rt_row and torrent_meta:
            info = _build_rt_only_nested_info(
                hash_val, rt_row, torrent_meta, rt_directory_fs or "", rt_nested_dir_fs, rt_save_path_fs
            )

        hits.append(NestedFolderScanHit(
            hash_val=hash_val,
            torrent_name=torrent_name,
            qb_nested=qb_nested,
            rt_nested=rt_nested,
            info=info,
            rt_directory_fs=rt_directory_fs,
            rt_nested_dir_fs=rt_nested_dir_fs,
            rt_save_path_fs=rt_save_path_fs,
            file_count=file_count,
            is_single_file=is_single_file,
        ))
        count += 1

    return hits, total_scanned


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
            # Single-file: move file(s) directly into save_path; RT gets save_path_api
            target = save_path
            rt_new_dir = info.save_path_api.rstrip("/")
            result.notes.append(f"single-file repair: {nested} → {target}")
        else:
            # Multi-file: move files one level up into the torrent root (outer dir);
            # RT gets save_path_api so it auto-appends info_name to find the torrent root
            target = outer
            rt_new_dir = info.save_path_api.rstrip("/")
            result.notes.append(f"multi-file repair: {nested}/* → {target}")

        result.files_moved = _move_tree(nested, target, dry_run=dry_run)

        if not dry_run:
            # Remove now-empty inner (nested) dir, then any empty intermediate dirs up to outer
            if nested.exists() and not list(nested.iterdir()):
                shutil.rmtree(str(nested))
                result.notes.append(f"removed: {nested}")
            ancestor = nested.parent
            while ancestor != outer and str(ancestor).startswith(str(outer)):
                if ancestor.exists() and not list(ancestor.iterdir()):
                    shutil.rmtree(str(ancestor))
                    result.notes.append(f"removed: {ancestor}")
                    ancestor = ancestor.parent
                else:
                    break

            # Single-file: also remove the outer dir (save_path/torrent_name) — now empty wrapper
            if info.is_single_file and outer.exists() and not list(outer.iterdir()):
                shutil.rmtree(str(outer))
                result.notes.append(f"removed: {outer}")

            # RT repoint — restart=True stops/sets/saves/opens/starts; then force hash check
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
                    try:
                        rt_xmlrpc_call("d.check_hash", info.hash_val, rpc_url=rpc_url)
                        result.notes.append("RT check_hash triggered")
                    except Exception as ce:
                        result.notes.append(f"RT check_hash failed: {ce}")
                else:
                    result.notes.append("RT: hash not in cache, skipping repoint")
            except Exception as e:
                result.notes.append(f"RT repoint failed: {e}")

            # QB: set_location + recheck (skip if torrent is RT-only)
            if info.qb_absent:
                result.notes.append("QB: skipped (RT-only torrent)")
            else:
                try:
                    qb_client.set_location(info.hash_val, info.save_path_api.rstrip("/"))
                    result.notes.append(f"QB set_location → {info.save_path_api.rstrip('/')}")
                    qb_client.recheck_torrent(info.hash_val)
                    result.notes.append("QB recheck triggered")
                except Exception as e:
                    result.notes.append(f"QB set_location/recheck failed: {e}")

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


def format_nested_folder_scan_report(
    hits: list[NestedFolderScanHit],
    *,
    scanned: int = 0,
    use_color: bool = True,
) -> str:
    """Rich-formatted scan report grouped by both/qb_only/rt_only."""
    import io
    from rich.console import Console
    from rich.text import Text
    from rich.rule import Rule

    buf = io.StringIO()
    console = Console(file=buf, highlight=False, markup=False, force_terminal=use_color, width=220)

    both = [h for h in hits if h.qb_nested and h.rt_nested]
    qb_only = [h for h in hits if h.qb_nested and not h.rt_nested]
    rt_only = [h for h in hits if h.rt_nested and not h.qb_nested]

    console.print(Rule("Nested-Folder Scan", style="bold"))
    console.print(Text.assemble(
        ("  scanned=", "dim"), (str(scanned), "white"),
        ("  hits=", "dim"), (str(len(hits)), "yellow bold" if hits else "white"),
        ("  both=", "dim"), (str(len(both)), "red bold" if both else "white"),
        ("  qb_only=", "dim"), (str(len(qb_only)), "yellow bold" if qb_only else "white"),
        ("  rt_only=", "dim"), (str(len(rt_only)), "yellow bold" if rt_only else "white"),
    ))
    console.print()

    def _print_group(label: str, group: list[NestedFolderScanHit], style: str) -> None:
        console.print(Text(f"{label}: {len(group)}", style=style))
        console.print()
        if not group:
            console.print(Text("  (none)", style="dim"))
            console.print()
            return
        for hit in group:
            console.print(Text.assemble(
                ("  ", ""), (hit.hash_val[:16], "bold white"),
                ("  ", ""), (hit.torrent_name, "white"),
            ))
            typ = "single-file" if hit.is_single_file else "multi-file"
            console.print(Text.assemble(
                ("    type=", "dim"), (typ, "cyan"),
                ("  files=", "dim"), (str(hit.file_count), "cyan"),
            ))
            if hit.info and not hit.info.qb_absent:
                console.print(Text.assemble(
                    ("    qb   ", "dim bold"),
                    ("save_path=", "dim"), (hit.info.save_path_fs, "cyan"),
                    ("  nested_dir=", "dim"), (hit.info.nested_dir_fs, "yellow"),
                ))
            if hit.rt_directory_fs:
                rt_nested_display = hit.rt_nested_dir_fs or "—"
                rt_color = "yellow" if hit.rt_nested else "dim"
                console.print(Text.assemble(
                    ("    rt   ", "dim bold"),
                    ("directory=", "dim"), (hit.rt_directory_fs, "cyan"),
                    ("  nested_dir=", "dim"), (rt_nested_display, rt_color),
                ))
            if hit.rt_save_path_fs:
                console.print(Text.assemble(
                    ("    rt   ", "dim bold"),
                    ("save_path=", "dim"), (hit.rt_save_path_fs, "dim cyan"),
                ))
            console.print(Text.assemble(
                ("    → repair:  ", "dim"),
                ("make client-drift-nested-repair-dry HASH=", "dim"),
                (hit.hash_val[:16], "green bold"),
            ))
            console.print()

    _print_group("BOTH CLIENTS NESTED", both, "bold red")
    _print_group("QB ONLY NESTED", qb_only, "bold yellow")
    _print_group("RT ONLY NESTED", rt_only, "bold blue")

    return buf.getvalue()
