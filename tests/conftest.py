"""
Shared pytest fixtures and skip guards.
"""

import subprocess

import pytest


def _tmp_is_on_separate_mount() -> bool:
    """Return True if /tmp lives on a different mount than /."""
    def _source(path: str) -> str:
        result = subprocess.run(
            ["findmnt", "-T", path, "-no", "SOURCE"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return _source("/tmp") != _source("/")


@pytest.fixture(scope="session")
def require_separate_tmp_mount():
    """Skip the test if /tmp shares the root partition.

    test_scan_integration.py creates temp dirs under /tmp, then calls
    scan_path() which uses ``findmnt -T`` to discover the device.  On hosts
    where /tmp is not a separate mount the device ID collides with real catalog
    data, causing table-name mismatches and assertion failures.
    """
    if not _tmp_is_on_separate_mount():
        pytest.skip(
            "test_scan_integration requires /tmp on a separate mount; "
            "on this host /tmp resolves to the root partition device. "
            "Run tests with TMPDIR pointing to a separately mounted path, "
            "or see docs/project/KNOWN-TEST-FAILURES.md for alternatives."
        )
