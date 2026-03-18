from pathlib import Path

import pytest

from hashall.bencode import bencode_encode
from hashall.fastresume import normalize_save_path, patch_fastresume_file, read_fastresume


def test_normalize_save_path_requires_absolute():
    with pytest.raises(ValueError):
        normalize_save_path("relative/path")


def test_patch_fastresume_file_normalizes_target_and_creates_backup(tmp_path):
    fastresume_path = tmp_path / "abc.fastresume"
    fastresume_path.write_bytes(
        bencode_encode(
            {
                b"save_path": b"/old/path",
                b"qBt-savePath": b"/old/path",
                b"qBt-downloadPath": b"/old/download",
            }
        )
    )

    result = patch_fastresume_file(fastresume_path, "/new/path/", ".bak")
    patched = read_fastresume(fastresume_path)

    assert result.changed is True
    assert result.backup_path.endswith(".bak")
    assert Path(result.backup_path).exists()
    assert result.old_save_path == "/old/path"
    assert result.new_save_path == "/new/path"
    assert patched[b"save_path"] == b"/new/path"
    assert patched[b"qBt-savePath"] == b"/new/path"
    assert patched[b"qBt-downloadPath"] == b""


def test_patch_fastresume_file_rejects_trailing_data(tmp_path):
    fastresume_path = tmp_path / "broken.fastresume"
    fastresume_path.write_bytes(
        bencode_encode({b"save_path": b"/old/path"}) + b"junk"
    )

    with pytest.raises(ValueError):
        patch_fastresume_file(fastresume_path, "/new/path", ".bak")
