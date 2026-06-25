"""Tests for scripts/repair_cross_seed_nested_stubs.py."""

from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MOD = SourceFileLoader(
    "repair_cross_seed_nested_stubs",
    str(REPO_ROOT / "scripts" / "repair_cross_seed_nested_stubs.py"),
).load_module()


def test_dry_run_no_changes(tmp_path: Path) -> None:
    root_file = tmp_path / "zero_byte_file.mkv"
    root_file.write_bytes(b"")
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    nested_file = nested_dir / "zero_byte_file.mkv"
    nested_file.write_bytes(b"\xff" * 1024)

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)

    assert len(ops) == 1
    assert ops[0][0] == "hardlink_stub"
    assert ops[0][1] == str(root_file)
    assert ops[0][2] == str(nested_file)
    assert ops[0][3] == 1024
    assert root_file.stat().st_size == 0


def test_execute_hardlink_stub(tmp_path: Path) -> None:
    root_file = tmp_path / "stub.mkv"
    root_file.write_bytes(b"")
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    nested_file = nested_dir / "stub.mkv"
    content = b"\xAB" * 2048
    nested_file.write_bytes(content)

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)
    results = MOD.execute_ops(ops)

    assert any("DONE hardlink_stub" in r for r in results)
    assert root_file.stat().st_size == 2048
    assert root_file.stat().st_nlink == nested_file.stat().st_nlink
    assert os.stat(str(root_file)).st_ino == os.stat(str(nested_file)).st_ino


def test_execute_replace_downloaded(tmp_path: Path) -> None:
    root_file = tmp_path / "downloaded.mkv"
    root_file.write_bytes(b"\xCD" * 512)
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    nested_file = nested_dir / "downloaded.mkv"
    nested_file.write_bytes(b"\xCD" * 512)

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)
    results = MOD.execute_ops(ops)

    assert any("DONE replace_downloaded_with_hardlink" in r for r in results)
    assert root_file.stat().st_size == 512
    assert os.stat(str(root_file)).st_ino == os.stat(str(nested_file)).st_ino


def test_skip_no_nested_match(tmp_path: Path) -> None:
    root_file = tmp_path / "orphan_stub.mkv"
    root_file.write_bytes(b"")

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)

    assert len(ops) == 1
    assert ops[0][0] == "skip_no_nested_match"
    assert root_file.stat().st_size == 0


def test_skip_size_mismatch(tmp_path: Path) -> None:
    root_file = tmp_path / "mismatch.mkv"
    root_file.write_bytes(b"\xAB" * 100)
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    nested_file = nested_dir / "mismatch.mkv"
    nested_file.write_bytes(b"\xCD" * 200)

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)

    assert len(ops) == 1
    assert ops[0][0] == "skip_size_mismatch"


def test_skip_nested_also_zero(tmp_path: Path) -> None:
    root_file = tmp_path / "both_zero.mkv"
    root_file.write_bytes(b"")
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    nested_file = nested_dir / "both_zero.mkv"
    nested_file.write_bytes(b"")

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)

    assert len(ops) == 1
    assert ops[0][0] == "skip_nested_also_zero"


def test_build_ops_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "zero_stub.mkv").write_bytes(b"")
    (tmp_path / "good_file.mkv").write_bytes(b"\xAA" * 512)
    nested_dir = tmp_path / "ItemName"
    nested_dir.mkdir()
    (nested_dir / "zero_stub.mkv").write_bytes(b"\xBB" * 2048)
    (nested_dir / "good_file.mkv").write_bytes(b"\xAA" * 512)

    root_files, nested_files = MOD.scan_item(str(tmp_path))
    ops = MOD.build_ops(root_files, nested_files)

    op_types = [op[0] for op in ops]
    assert "hardlink_stub" in op_types
    assert "replace_downloaded_with_hardlink" in op_types
    assert len(ops) == 2


def test_host_path_no_mapping() -> None:
    assert MOD.host_path("/some/other/path") == "/some/other/path"


def test_host_path_with_mapping() -> None:
    assert MOD.host_path("/data/media/torrents/file.mkv") == "/stash/media/torrents/file.mkv"


def test_format_size() -> None:
    assert MOD.format_size(0) == "0.0 B"
    assert MOD.format_size(1023) == "1023.0 B"
    assert MOD.format_size(1024) == "1.0 KB"
    assert MOD.format_size(1048576) == "1.0 MB"
    assert MOD.format_size(1073741824) == "1.0 GB"


import os
