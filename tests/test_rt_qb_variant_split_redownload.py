import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

from hashall.bencode import bencode_encode


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "rt-qb-variant-split-redownload.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rt_qb_variant_split_redownload", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_single_torrent(path: Path, name: str, size: int) -> None:
    info = {
        b"name": name.encode("utf-8"),
        b"length": size,
        b"piece length": 4,
        b"pieces": b"\x00" * 20,
    }
    path.write_bytes(bencode_encode({b"info": info}))


def test_dry_run_reports_shared_inode_and_quarantine_path(tmp_path, monkeypatch):
    mod = load_module()
    h = "a" * 40
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    source = tmp_path / "source.mkv"
    source.write_bytes(b"data")
    payload = save / "movie.mkv"
    payload.hardlink_to(source)

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(save))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=True,
        apply=False,
        allow_start_download=False,
        operator_download_approval=False,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.build_report(args)

    assert report["shared_inode_detected"] is True
    assert report["payload_path"] == str(payload)
    assert report["quarantine_path"].endswith("movie.mkv.invalid-for-test")
    assert report["status"] == "planned"


def test_apply_renames_only_failed_path_and_starts_rt(tmp_path, monkeypatch):
    mod = load_module()
    h = "b" * 40
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    sibling = tmp_path / "sibling.mkv"
    sibling.write_bytes(b"data")
    payload = save / "movie.mkv"
    payload.hardlink_to(sibling)
    calls = []

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(save))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda *a, **k: "0")
    monkeypatch.setattr(mod, "rt_xmlrpc_call", lambda method, *a, **k: calls.append(method) or "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=False,
        apply=True,
        allow_start_download=True,
        operator_download_approval=True,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )
    report = mod.apply_report(args, mod.build_report(args))

    assert report["status"] == "applied"
    assert not payload.exists()
    assert sibling.exists()
    assert (save / "movie.mkv.invalid-for-test").exists()
    assert calls[:3] == ["d.stop", "d.check_hash", "d.start"]


def test_hash_prefix_resolves_against_session_torrent_files(tmp_path):
    mod = load_module()
    h = "c" * 40
    session = tmp_path / "session"
    session.mkdir()
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)

    assert mod.resolve_hash(session, "cccccccccccc") == h


def test_apply_blocks_nested_session_dir_under_payload(tmp_path, monkeypatch):
    mod = load_module()
    h = "d" * 40
    other = "e" * 40
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(session / f"{h.upper()}.torrent", "release", 4)
    sibling_payload = save / "release" / "nested"
    sibling_payload.mkdir(parents=True)
    source = tmp_path / "source.bin"
    source.write_bytes(b"data")
    (save / "release" / "file.bin").hardlink_to(source)

    class Entry:
        def __init__(self, directory):
            self.directory = directory

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(save))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {other: Entry(str(sibling_payload))})
    monkeypatch.setattr(mod, "rt_scalar", lambda *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=False,
        apply=True,
        allow_start_download=False,
        operator_download_approval=False,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.apply_report(args, mod.build_report(args))

    assert report["status"] == "blocked"
    assert report["blocked_reason"] == "nested_rt_session_dir_under_payload"


def test_validate_freeleech_proof_requires_positive_report(tmp_path):
    mod = load_module()
    proof = tmp_path / "proof.json"
    proof.write_text('{"freeleech_proven": true, "freeleech_hits": 1}', encoding="utf-8")

    assert mod.validate_freeleech_proof(str(proof)) == (True, "ok")

    bad = tmp_path / "bad.json"
    bad.write_text('{"freeleech_proven": false, "freeleech_hits": 0}', encoding="utf-8")
    assert mod.validate_freeleech_proof(str(bad))[0] is False


def test_start_existing_split_blocks_shared_inode(tmp_path, monkeypatch):
    mod = load_module()
    h = "f" * 40
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    source = tmp_path / "source.mkv"
    source.write_bytes(b"data")
    payload = save / "movie.mkv"
    payload.hardlink_to(source)

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(save))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda method, *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=False,
        apply=True,
        start_existing_split=True,
        allow_start_download=True,
        operator_download_approval=True,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.start_existing_split(args, mod.build_report(args))

    assert report["status"] == "blocked"
    assert report["blocked_reason"] == "payload_still_shared_inode"


def test_placement_audit_media_library_member_requires_stash(tmp_path, monkeypatch):
    mod = load_module()
    h = "1" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    library = tmp_path / "data" / "media" / "movies" / "Spider-Man"
    session.mkdir()
    seeding.mkdir(parents=True)
    library.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    payload = seeding / "movie.mkv"
    payload.write_bytes(b"data")
    (library / "movie.mkv").hardlink_to(payload)

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(seeding))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda method, *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=True,
        apply=False,
        allow_start_download=False,
        operator_download_approval=False,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.placement_audit(
        mod.build_report(args),
        scan_roots=[str(tmp_path / "data" / "media")],
        media_prefixes=[str(tmp_path / "data" / "media" / "movies")],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "stash_required"
    assert audit["reason"] == "media_library_member_present"
    assert str(library / "movie.mkv") in audit["media_library_member_paths"]


def test_placement_audit_seeding_only_group_is_pool_eligible(tmp_path, monkeypatch):
    mod = load_module()
    h = "2" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    sibling = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "tracker"
    session.mkdir()
    seeding.mkdir(parents=True)
    sibling.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    payload = seeding / "movie.mkv"
    payload.write_bytes(b"data")
    (sibling / "movie.mkv").hardlink_to(payload)

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(seeding))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda method, *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=True,
        apply=False,
        allow_start_download=False,
        operator_download_approval=False,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.placement_audit(
        mod.build_report(args),
        scan_roots=[str(tmp_path / "data" / "media")],
        media_prefixes=[str(tmp_path / "data" / "media" / "movies")],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "pool_eligible"
    assert audit["media_library_member_paths"] == []
    assert str(sibling / "movie.mkv") in audit["same_inode_member_paths"]


def test_placement_audit_file_limit_requires_manual_review(tmp_path, monkeypatch):
    mod = load_module()
    h = "3" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    session.mkdir()
    seeding.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    payload = seeding / "movie.mkv"
    payload.write_bytes(b"data")

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(seeding))
    monkeypatch.setattr(mod, "load_rt_torrent_meta", lambda *a, **k: None)
    monkeypatch.setattr(mod, "load_rt_session_directories", lambda *a, **k: {})
    monkeypatch.setattr(mod, "rt_scalar", lambda method, *a, **k: "0")

    args = Namespace(
        hash=h,
        target="",
        session_dir=str(session),
        rpc_url="http://rt/",
        timeout=1,
        poll_secs=0,
        dry_run=True,
        apply=False,
        allow_start_download=False,
        operator_download_approval=False,
        freeleech_proof="",
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.placement_audit(
        mod.build_report(args),
        scan_roots=[str(tmp_path / "data" / "media")],
        media_prefixes=[str(tmp_path / "data" / "media" / "movies")],
        max_files=0,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "unknown_requires_manual_review"
    assert audit["reason"] == "placement_scan_file_limit_reached"
    assert audit["scan_truncated"] is True
