"""Filesystem utilities for persistent device identification."""

import os
import subprocess
from typing import Optional


def get_filesystem_uuid(path: str) -> str:
    """
    Get persistent filesystem UUID for a path.

    This function attempts multiple strategies to obtain a stable identifier
    for the filesystem containing the given path. The identifier remains
    consistent across reboots, unlike device_id (st_dev) which can change.

    Strategy (in order of preference):
    1. findmnt -no UUID {path} - Most reliable, works for ext4, btrfs, xfs, etc.
    2. zfs get guid {path} - For ZFS filesystems (returns "zfs-{guid}")
    3. os.stat().st_dev - Fallback (returns "dev-{device_id}")

    Works for ZFS, ext4, btrfs, xfs, and other common filesystems.

    Args:
        path: Path to any file or directory on the filesystem

    Returns:
        - Filesystem UUID if available (e.g., "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        - "zfs-{guid}" for ZFS filesystems (e.g., "zfs-12345678901234567890")
        - "dev-{device_id}" as fallback (e.g., "dev-49")

    Examples:
        >>> get_filesystem_uuid("/pool/torrents")
        'zfs-12345678901234567890'

        >>> get_filesystem_uuid("/mnt/data")
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

        >>> get_filesystem_uuid("/tmp")  # tmpfs without UUID
        'dev-17'

    Note:
        This function is designed to never raise exceptions. In all error
        cases, it falls back to device_id-based identifier.
    """
    # Method 1: Use findmnt (most reliable for standard filesystems)
    uuid = _try_findmnt(path)
    if uuid:
        return uuid

    # Method 2: For ZFS, use dataset GUID
    zfs_guid = _try_zfs_guid(path)
    if zfs_guid:
        return f"zfs-{zfs_guid}"

    # Method 3: Fallback to device_id as string (last resort)
    try:
        device_id = os.stat(path).st_dev
        return f"dev-{device_id}"
    except (OSError, IOError):
        # If even stat() fails, return a sentinel value
        # This should be extremely rare (path doesn't exist, permissions, etc.)
        return "dev-unknown"


def _try_findmnt(path: str) -> Optional[str]:
    """
    Try to get filesystem UUID using findmnt.

    This is the most reliable method for standard Linux filesystems
    (ext4, btrfs, xfs, etc.)

    Args:
        path: Path to query

    Returns:
        UUID string if successful, None otherwise
    """
    try:
        result = subprocess.run(
            ['findmnt', '-no', 'UUID', path],
            capture_output=True,
            text=True,
            check=True,
            timeout=5  # Prevent hanging
        )
        uuid = result.stdout.strip()
        # Some filesystems (tmpfs, etc.) don't have UUIDs
        if uuid and uuid != '-':
            return uuid
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # findmnt not available, path not found, or command failed
        pass
    except Exception:
        # Catch any other unexpected errors
        pass

    return None


def _try_zfs_guid(path: str) -> Optional[str]:
    """
    Try to get ZFS filesystem GUID.

    ZFS datasets have a unique GUID that persists across renames,
    exports/imports, and system changes.

    Args:
        path: Path to query

    Returns:
        ZFS GUID string if successful, None otherwise
    """
    try:
        result = subprocess.run(
            ['zfs', 'get', '-H', '-o', 'value', 'guid', path],
            capture_output=True,
            text=True,
            check=True,
            timeout=5  # Prevent hanging
        )
        guid = result.stdout.strip()
        # Valid GUIDs are numeric strings, not '-' (property not available)
        if guid and guid != '-' and guid.isdigit():
            return guid
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # zfs command not available, path not a ZFS dataset, or command failed
        pass
    except Exception:
        # Catch any other unexpected errors
        pass

    return None


def get_zfs_metadata(path: str) -> dict:
    """
    Get ZFS-specific metadata for a path.

    This function extracts ZFS metadata including the pool name, dataset name,
    and pool GUID for a given path. It returns an empty dict if the path is not
    on a ZFS filesystem or if any ZFS commands fail.

    Args:
        path: Path to any file or directory on a ZFS filesystem

    Returns:
        Dictionary with keys:
        - pool_name: Name of the ZFS pool (e.g., "tank")
        - dataset_name: Full dataset name (e.g., "tank/data/torrents")
        - pool_guid: Pool GUID as a string (e.g., "12345678901234567890")

        Returns empty dict {} if:
        - Path is not on a ZFS filesystem
        - ZFS commands are not available
        - Any command fails or returns invalid data

    Examples:
        >>> get_zfs_metadata("/tank/data/torrents")
        {
            'pool_name': 'tank',
            'dataset_name': 'tank/data/torrents',
            'pool_guid': '12345678901234567890'
        }

        >>> get_zfs_metadata("/mnt/ext4")  # Non-ZFS filesystem
        {}
    """
    try:
        # Get dataset name using zfs list
        result = subprocess.run(
            ['zfs', 'list', '-H', '-o', 'name', path],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        dataset_name = result.stdout.strip()

        # Validate dataset name is not empty
        if not dataset_name:
            return {}

        # Extract pool name (first component before /)
        pool_name = dataset_name.split('/')[0]

        # Get pool GUID using zpool get
        result = subprocess.run(
            ['zpool', 'get', '-H', '-o', 'value', 'guid', pool_name],
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        pool_guid = result.stdout.strip()

        # Validate pool GUID
        if not pool_guid or pool_guid == '-':
            return {}

        return {
            'pool_name': pool_name,
            'dataset_name': dataset_name,
            'pool_guid': pool_guid
        }

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # ZFS commands not available, path not on ZFS, or command failed
        return {}
    except Exception:
        # Catch any other unexpected errors
        return {}
