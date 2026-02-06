"""Path canonicalization helpers for bind mounts and symlinks."""

from pathlib import Path
from typing import Optional

from hashall.fs_utils import get_mount_point, get_mount_source


def resolve_bind_source(path: Path) -> Path:
    """
    Resolve a path that is under a bind mount to its source path.

    If the mount source is an absolute path, we treat it as a bind mount and
    remap the path onto the source with the same relative suffix.
    """
    resolved = Path(path).resolve()
    mount_point = get_mount_point(str(resolved))
    mount_source = get_mount_source(str(resolved))

    if mount_point and mount_source and mount_source.startswith("/"):
        try:
            rel = resolved.relative_to(Path(mount_point))
        except ValueError:
            return resolved
        return (Path(mount_source) / rel).resolve()

    return resolved


def canonicalize_path(path: Path) -> Path:
    """
    Canonicalize a path by resolving symlinks and bind mounts.

    This ensures that bind-mounted aliases resolve to their real source paths.
    """
    resolved = Path(path).resolve()
    return resolve_bind_source(resolved)


def is_under(path: Path, root: Path) -> bool:
    """Return True if path is under root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def to_relpath(path: Path, root: Path) -> Optional[Path]:
    """Return relative path from root, or None if path is not under root."""
    try:
        return path.relative_to(root)
    except ValueError:
        return None
