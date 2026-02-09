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
        source_p = Path(mount_source)
        # Only remap for actual bind mounts (source is a directory), not
        # block devices like /dev/nvme0n1p7 which are regular FS backing.
        if not source_p.is_dir():
            return resolved
        try:
            rel = resolved.relative_to(Path(mount_point))
        except ValueError:
            return resolved
        return (source_p / rel).resolve()

    return resolved


def canonicalize_path(path: Path) -> Path:
    """
    Canonicalize a path by resolving symlinks and bind mounts.

    This ensures that bind-mounted aliases resolve to their real source paths.
    """
    resolved = Path(path).resolve()
    return resolve_bind_source(resolved)


def remap_to_mount_alias(path: Path, preferred_mount: Path) -> Optional[Path]:
    """
    Remap PATH onto PREFERRED_MOUNT when both are mounts of the same SOURCE.

    This handles "alternate mount points" where the same filesystem is mounted
    at multiple targets (common with ZFS datasets). Example:

        /data/media/...  ->  /stash/media/...

    when both mount targets have the same `findmnt -no SOURCE` value.

    Returns:
        Remapped absolute path, or None if no remap was possible.
    """
    try:
        p = Path(path)
        pref = Path(preferred_mount)
        if not p.is_absolute() or not pref.is_absolute():
            return None

        from_mount = get_mount_point(str(p))
        if not from_mount:
            return None
        from_mount_p = Path(from_mount)
        if not p.is_relative_to(from_mount_p):
            return None

        p_source = get_mount_source(str(p))
        pref_source = get_mount_source(str(pref))
        if not p_source or not pref_source or p_source != pref_source:
            return None

        rel = p.relative_to(from_mount_p)
        return pref / rel
    except Exception:
        return None


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
