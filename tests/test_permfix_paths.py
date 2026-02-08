import os
import stat
import tempfile
from pathlib import Path

from hashall.permfix import resolve_plan_paths_for_permfix, fix_permissions
from hashall.link_executor import verify_parent_dir_writable


def test_resolve_plan_paths_for_permfix_resolves_relative_under_mount():
    mount = Path("/mnt/media")
    rows = [
        ("torrents/a.mkv", "torrents/b.mkv"),
    ]
    paths = resolve_plan_paths_for_permfix(rows, mount)

    assert mount / "torrents/a.mkv" in paths
    assert mount / "torrents/b.mkv" in paths
    assert mount / "torrents" in paths


def test_resolve_plan_paths_for_permfix_keeps_absolute_paths():
    mount = Path("/mnt/media")
    rows = [
        ("/abs/keep.mkv", "rel/dup.mkv"),
    ]
    paths = resolve_plan_paths_for_permfix(rows, mount)

    assert Path("/abs/keep.mkv") in paths
    assert mount / "rel/dup.mkv" in paths
    assert Path("/abs") in paths
    assert mount / "rel" in paths


def test_verify_parent_dir_writable():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        f = td_path / "file.bin"
        f.write_bytes(b"123")

        ok, err = verify_parent_dir_writable(f)
        assert ok is True
        assert err is None

        # Remove write bit on the directory and verify it fails.
        os.chmod(td_path, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        try:
            ok, err = verify_parent_dir_writable(f)
            assert ok is False
            assert "not writable" in (err or "").lower()
        finally:
            os.chmod(td_path, stat.S_IRWXU)


def test_fix_permissions_apply_false_does_not_modify():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "subdir"
        d.mkdir()
        os.chmod(d, 0o555)
        before = d.stat().st_mode & 0o7777
        try:
            summary, _ = fix_permissions(
                [d],
                target_gid=os.getgid(),
                target_uid=os.getuid(),
                apply=False,
                use_sudo=False,
            )
            after = d.stat().st_mode & 0o7777
            assert before == after
            assert summary.changed == 1
        finally:
            os.chmod(d, 0o755)
