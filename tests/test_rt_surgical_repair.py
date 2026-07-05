import importlib.util
from argparse import Namespace
from pathlib import Path

from hashall.bencode import bencode_encode


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "rt-surgical-repair.py"


def load_script():
    spec = importlib.util.spec_from_file_location("rt_surgical_repair", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_torrent(session_dir: Path, torrent_hash: str, info: dict):
    (session_dir / f"{torrent_hash.upper()}.torrent").write_bytes(
        bencode_encode({b"info": info})
    )


def test_verify_payload_blocks_missing_sidecar(tmp_path):
    mod = load_script()
    h = "a" * 40
    session = tmp_path / "session"
    target = tmp_path / "target"
    session.mkdir()
    target.mkdir()
    write_torrent(
        session,
        h,
        {
            b"name": b"Movie",
            b"files": [
                {b"path": [b"Movie.mkv"], b"length": 4},
                {b"path": [b"Movie.mkv.nfo"], b"length": 3},
            ],
        },
    )
    root = target / "Movie"
    root.mkdir()
    (root / "Movie.mkv").write_bytes(b"data")

    result = mod.verify_payload(session, h, str(target))

    assert result["verified"] is False
    assert result["missing_count"] == 1
    assert result["missing"][0]["relative_path"] == "Movie.mkv.nfo"


def test_verify_payload_multifile_accepts_payload_root_target(tmp_path):
    mod = load_script()
    h = "b" * 40
    session = tmp_path / "session"
    parent = tmp_path / "parent"
    session.mkdir()
    parent.mkdir()
    write_torrent(
        session,
        h,
        {
            b"name": b"Show.S01",
            b"files": [
                {b"path": [b"ep1.mkv"], b"length": 2},
                {b"path": [b"ep2.mkv"], b"length": 2},
            ],
        },
    )
    root = parent / "Show.S01"
    root.mkdir()
    (root / "ep1.mkv").write_bytes(b"aa")
    (root / "ep2.mkv").write_bytes(b"bb")

    result = mod.verify_payload(session, h, str(root))

    assert result["verified"] is True
    assert result["normalized_target"] == str(parent)
    assert result["content_root"] == str(root)


def test_verify_payload_single_file_uses_containing_directory(tmp_path):
    mod = load_script()
    h = "c" * 40
    session = tmp_path / "session"
    parent = tmp_path / "single"
    session.mkdir()
    parent.mkdir()
    write_torrent(session, h, {b"name": b"Movie.mkv", b"length": 5})
    movie = parent / "Movie.mkv"
    movie.write_bytes(b"12345")

    result = mod.verify_payload(session, h, str(movie))

    assert result["verified"] is True
    assert result["normalized_target"] == str(parent)
    assert result["content_root"] == str(parent)


def test_repair_one_dry_run_blocks_before_mutation(tmp_path, monkeypatch):
    mod = load_script()
    h = "d" * 40
    session = tmp_path / "session"
    target = tmp_path / "target"
    session.mkdir()
    target.mkdir()
    write_torrent(
        session,
        h,
        {
            b"name": b"Movie",
            b"files": [{b"path": [b"missing.nfo"], b"length": 3}],
        },
    )
    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: "/old")
    monkeypatch.setattr(mod, "rt_scalar", lambda *a, **k: "0")

    args = Namespace(
        session_dir=str(session),
        target=str(target),
        dry_run=True,
        apply=False,
        allow_start_if_complete=True,
        rpc_url="http://rt/",
        timeout=1,
    )

    result = mod.repair_one(args, h)

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "payload_verification_failed"
