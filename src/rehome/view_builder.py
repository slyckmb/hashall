"""
Torrent view builder.

Builds a torrent-specific directory layout (view) that hardlinks to a
canonical payload root. This allows multiple torrents to share one payload
without duplicating data.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import os

from hashall.qbittorrent import QBitFile


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


def _ensure_hardlink(src: Path, dst: Path) -> None:
    if dst.exists():
        src_stat = os.stat(src)
        dst_stat = os.stat(dst)
        if src_stat.st_ino == dst_stat.st_ino and src_stat.st_dev == dst_stat.st_dev:
            return
        raise RuntimeError(f"Destination exists and differs: {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    src_stat = os.stat(src)
    dst_parent_stat = os.stat(dst.parent)
    if src_stat.st_dev != dst_parent_stat.st_dev:
        raise RuntimeError(f"Cannot hardlink across filesystems: {src} -> {dst}")

    os.link(src, dst)


def build_torrent_view(
    payload_root: Path,
    target_save_path: Path,
    files: List[QBitFile],
    root_name: Optional[str] = None
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

    if single_file:
        view_root = target_save_path
    else:
        view_root = target_save_path / (root_name or payload_root.name)

    common_prefix = _common_prefix(files)

    total_bytes = 0
    for f in files:
        rel = _normalize_rel_path(f.name, common_prefix, root_name, payload_root)
        if single_file:
            src = payload_root
            dst = view_root / rel
        else:
            src = payload_root / rel
            dst = view_root / rel

        if not src.exists():
            raise RuntimeError(f"Missing source file for view: {src}")

        if src == dst:
            # Already in canonical place
            total_bytes += f.size
            continue

        _ensure_hardlink(src, dst)
        total_bytes += f.size

    return ViewBuildResult(view_root=view_root, file_count=len(files), total_bytes=total_bytes)
