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


def test_remap_to_mount_alias_zfs_alternate_mount(monkeypatch, tmp_path):
    """
    When the same SOURCE is mounted at two different targets, remap to the
    preferred mount target.
    """
    data_root = tmp_path / "data" / "media"
    stash_root = tmp_path / "stash" / "media"
    (data_root / "payload").mkdir(parents=True)
    stash_root.mkdir(parents=True)

    target = data_root / "payload" / "file.txt"
    target.write_text("x")

    def fake_get_mount_point(p: str):
        p = str(Path(p))
        if p.startswith(str(data_root)):
            return str(data_root)
        if p.startswith(str(stash_root)):
            return str(stash_root)
        return None

    def fake_get_mount_source(p: str):
        p = str(Path(p))
        if p.startswith(str(data_root)) or p.startswith(str(stash_root)):
            return "stash/media"
        return None

    monkeypatch.setattr(pathing, "get_mount_point", fake_get_mount_point)
    monkeypatch.setattr(pathing, "get_mount_source", fake_get_mount_source)

    remapped = pathing.remap_to_mount_alias(target, stash_root)
    assert remapped == (stash_root / "payload" / "file.txt")


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
