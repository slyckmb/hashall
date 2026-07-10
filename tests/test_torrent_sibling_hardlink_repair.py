import hashlib
import importlib.util
import sys
from pathlib import Path

from hashall.bencode import bencode_encode
from hashall.torrent_verify import verify_torrent_pieces


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "torrent-sibling-hardlink-repair.py"


def load_module():
    spec = importlib.util.spec_from_file_location("torrent_sibling_hardlink_repair", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def pieces_for(data: bytes, piece_length: int) -> bytes:
    return b"".join(
        hashlib.sha1(data[i : i + piece_length]).digest()
        for i in range(0, len(data), piece_length)
    )


def write_single_torrent(path: Path, name: str, data: bytes, piece_length: int = 4) -> None:
    info = {
        b"name": name.encode("utf-8"),
        b"length": len(data),
        b"piece length": piece_length,
        b"pieces": pieces_for(data, piece_length),
    }
    path.write_bytes(bencode_encode({b"info": info}))


def write_multi_torrent(path: Path, name: str, files: list[tuple[str, bytes]], piece_length: int = 4) -> None:
    payload = b"".join(data for _, data in files)
    info = {
        b"name": name.encode("utf-8"),
        b"files": [
            {b"length": len(data), b"path": [rel.encode("utf-8")]}
            for rel, data in files
        ],
        b"piece length": piece_length,
        b"pieces": pieces_for(payload, piece_length),
    }
    path.write_bytes(bencode_encode({b"info": info}))


def test_single_source_file_name_may_differ_from_target_name(tmp_path: Path) -> None:
    mod = load_module()
    data = b"abcdefghij"
    torrent = tmp_path / "single.torrent"
    write_single_torrent(torrent, "target-name.mkv", data)
    source_file = tmp_path / "different-source-name.bin"
    source_file.write_bytes(data)
    target_base = tmp_path / "target"

    info = mod.load_torrent_info(torrent)
    name, is_multi, size, piece_length, pieces, entries = mod.torrent_expected_files(info)
    assert name == "target-name.mkv"
    assert not is_multi
    assert mod.verify_source_file(source_file, size, piece_length, pieces)["success"]

    result = mod.hardlink_expected_file(source_file, target_base / entries[0].rel_path, size, apply=True)

    assert result["ok"]
    assert (target_base / "target-name.mkv").stat().st_ino == source_file.stat().st_ino
    assert verify_torrent_pieces(torrent, target_base).success


def test_multi_source_dir_may_be_content_root(tmp_path: Path) -> None:
    mod = load_module()
    files = [("a.bin", b"abcd"), ("b.bin", b"efghi")]
    torrent = tmp_path / "multi.torrent"
    write_multi_torrent(torrent, "release", files)
    source_content = tmp_path / "source" / "release"
    for rel, data in files:
        path = source_content / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    target_base = tmp_path / "target"

    info = mod.load_torrent_info(torrent)
    name, is_multi, _size, _piece_length, _pieces, entries = mod.torrent_expected_files(info)
    assert name == "release"
    assert is_multi
    source_base = mod.source_base_for_dir(source_content, name, entries)

    result = mod.hardlink_expected_tree(source_base, target_base, entries, apply=True)

    assert result["ok"]
    assert verify_torrent_pieces(torrent, source_base).success
    assert verify_torrent_pieces(torrent, target_base).success
    for rel, _data in files:
        assert (target_base / "release" / rel).stat().st_ino == (source_content / rel).stat().st_ino
