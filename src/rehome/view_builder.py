"""
Torrent view builder.

Builds a torrent-specific directory layout (view) that hardlinks to a
canonical payload root. This allows multiple torrents to share one payload
without duplicating data.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
import errno
import os
import time

from hashall.qbittorrent import QBitFile

_CONTENT_EQ_CACHE: dict[tuple[int, int, int, int, int, int], bool] = {}


@dataclass
class ViewBuildResult:
    view_root: Path
    file_count: int
    total_bytes: int


def _common_prefix(files: List[QBitFile]) -> Optional[str]:
    if not files:
        return None
    first_parts = Path(files[0].name).parts
    if not first_parts:
        return None
    prefix = first_parts[0]
    for f in files[1:]:
        parts = Path(f.name).parts
        if not parts or parts[0] != prefix:
            return None
    return prefix


def _normalize_rel_path(
    rel_path: str,
    common_prefix: Optional[str],
    root_name: Optional[str],
    payload_root: Path
) -> Path:
    path = Path(rel_path)
    if common_prefix and path.parts and (
        common_prefix == (root_name or "") or common_prefix == payload_root.name
    ):
        return Path(*path.parts[1:]) if len(path.parts) > 1 else Path(path.name)
    return path


def _ensure_hardlink(
    src: Path,
    dst: Path,
    *,
    compare_hint: Optional[Callable[[Path, Path], Optional[bool]]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    def _same_content(a: Path, b: Path) -> bool:
        a_stat = os.stat(a)
        b_stat = os.stat(b)
        if a_stat.st_size != b_stat.st_size:
            return False
        cache_key = (
            a_stat.st_dev,
            a_stat.st_ino,
            b_stat.st_dev,
            b_stat.st_ino,
            a_stat.st_size,
            b_stat.st_size,
        )
        cached = _CONTENT_EQ_CACHE.get(cache_key)
        if cached is not None:
            return cached
        bytes_total = int(a_stat.st_size)
        bytes_done = 0
        start = time.monotonic()
        last_log = start

        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ba = fa.read(1024 * 1024)
                bb = fb.read(1024 * 1024)
                if ba != bb:
                    _CONTENT_EQ_CACHE[cache_key] = False
                    return False
                if not ba:
                    _CONTENT_EQ_CACHE[cache_key] = True
                    return True
                bytes_done += len(ba)
                now = time.monotonic()
                if progress_cb and (now - last_log) >= 5.0 and bytes_total > 0:
                    pct = (bytes_done / bytes_total) * 100.0
                    elapsed = max(now - start, 0.001)
                    rate_mib = (bytes_done / (1024 * 1024)) / elapsed
                    progress_cb(
                        "build_views_progress phase=compare "
                        f"bytes_done={bytes_done} bytes_total={bytes_total} "
                        f"pct={pct:.1f} rate_mib_s={rate_mib:.1f} src={a} dst={b}"
                    )
                    last_log = now

    def _accept_or_reject_existing(a: Path, b: Path) -> bool:
        try:
            a_stat = os.stat(a)
            b_stat = os.stat(b)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Destination exists but is not a resolvable file: {b}") from exc

        if a_stat.st_ino == b_stat.st_ino and a_stat.st_dev == b_stat.st_dev:
            return True
        if compare_hint is not None:
            hinted = compare_hint(a, b)
            if hinted is True:
                return True
            if hinted is False:
                raise RuntimeError(f"Destination exists and differs: {b}")
        if _same_content(a, b):
            # Accept an existing identical file (already materialized by previous runs/manual copy).
            return True
        raise RuntimeError(f"Destination exists and differs: {b}")

    if dst.exists() or dst.is_symlink():
        _accept_or_reject_existing(src, dst)
        return

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        if progress_cb:
            progress_cb(
                "build_views_error phase=mkdir_parent "
                f"src={src} dst={dst} parent={dst.parent} "
                f"parent_exists={dst.parent.exists()} parent_is_dir={dst.parent.is_dir()}"
            )
        raise RuntimeError(
            f"Cannot create parent directory for destination: {dst.parent}"
        ) from exc

    src_stat = os.stat(src)
    dst_parent_stat = os.stat(dst.parent)
    if src_stat.st_dev != dst_parent_stat.st_dev:
        raise RuntimeError(f"Cannot hardlink across filesystems: {src} -> {dst}")

    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
        # Another writer created the path between exists() and os.link(); treat this as
        # idempotent if destination now matches source.
        if progress_cb:
            progress_cb(f"build_views_progress phase=link_race dst={dst}")
        if dst.exists() or dst.is_symlink():
            _accept_or_reject_existing(src, dst)
            return
        raise


def build_torrent_view(
    payload_root: Path,
    target_save_path: Path,
    files: List[QBitFile],
    root_name: Optional[str] = None,
    compare_hint: Optional[Callable[[Path, Path], Optional[bool]]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> ViewBuildResult:
    """
    Build a hardlink view for a torrent at target_save_path.

    For multi-file torrents, view_root is target_save_path/root_name.
    For single-file torrents where payload_root is a file, view_root is target_save_path.
    """
    if not files:
        raise RuntimeError("Torrent file list is empty")

    payload_root = Path(payload_root)
    target_save_path = Path(target_save_path)

    single_file = payload_root.is_file()
    if single_file and len(files) != 1:
        raise RuntimeError("Single-file payload but torrent has multiple files")

    common_prefix = _common_prefix(files)
    single_file_direct_dst: Optional[Path] = None
    if single_file:
        # Normal qB save_path points to a directory; tolerate file-form save_path too.
        first_rel = _normalize_rel_path(files[0].name, common_prefix, root_name, payload_root)
        if len(first_rel.parts) == 1 and target_save_path.name == first_rel.name:
            single_file_direct_dst = target_save_path
            view_root = target_save_path.parent
            if progress_cb:
                progress_cb(
                    "build_views_progress phase=single_file_direct_target "
                    f"target={target_save_path} view_root={view_root}"
                )
        else:
            view_root = target_save_path
    else:
        view_root = target_save_path / (root_name or payload_root.name)

    total_bytes = 0
    for f in files:
        rel = _normalize_rel_path(f.name, common_prefix, root_name, payload_root)
        if single_file:
            src = payload_root
            dst = single_file_direct_dst if single_file_direct_dst is not None else (view_root / rel)
        else:
            src = payload_root / rel
            dst = view_root / rel
            if len(files) == 1 and len(rel.parts) == 1 and view_root.name == rel.name:
                # Some single-entry torrents report root_name as the file name.
                # In that case, place the file directly at target_save_path/root_name.
                dst = view_root
                if progress_cb:
                    progress_cb(
                        "build_views_progress phase=single_entry_root_is_file "
                        f"target={target_save_path} root_name={root_name}"
                    )

        if not src.exists():
            raise RuntimeError(f"Missing source file for view: {src}")

        if src == dst:
            # Already in canonical place
            total_bytes += f.size
            continue

        _ensure_hardlink(src, dst, compare_hint=compare_hint, progress_cb=progress_cb)
        total_bytes += f.size

    return ViewBuildResult(view_root=view_root, file_count=len(files), total_bytes=total_bytes)
