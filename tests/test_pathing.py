"""
Tests for path canonicalization helpers.
"""

from pathlib import Path

import hashall.pathing as pathing


def test_canonicalize_path_bind_mount(monkeypatch, tmp_path):
    """
    Bind mount source should remap canonical path to the mount source.
    """
    data_root = tmp_path / "data" / "media"
    stash_root = tmp_path / "stash" / "media"
    data_root.mkdir(parents=True)
    stash_root.mkdir(parents=True)

    target = data_root / "file.txt"
    target.write_text("x")

    def fake_get_mount_point(_path: str):
        return str(data_root)

    def fake_get_mount_source(_path: str):
        return str(stash_root)

    monkeypatch.setattr(pathing, "get_mount_point", fake_get_mount_point)
    monkeypatch.setattr(pathing, "get_mount_source", fake_get_mount_source)

    canonical = pathing.canonicalize_path(target)
    assert canonical == (stash_root / "file.txt").resolve()


def test_to_relpath_and_is_under(tmp_path):
    root = tmp_path / "pool"
    root.mkdir()
    path = root / "torrents" / "file.mkv"
    path.parent.mkdir(parents=True)
    path.write_text("x")

    rel = pathing.to_relpath(path, root)
    assert rel == Path("torrents/file.mkv")
    assert pathing.is_under(path, root) is True
    assert pathing.to_relpath(tmp_path / "other", root) is None
