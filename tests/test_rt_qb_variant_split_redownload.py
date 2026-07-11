import importlib.util
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

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


def write_single_torrent(path: Path, name: str, size: int, *, announce: str = "") -> None:
    info = {
        b"name": name.encode("utf-8"),
        b"length": size,
        b"piece length": 4,
        b"pieces": b"\x00" * 20,
    }
    payload = {b"info": info}
    if announce:
        payload[b"announce"] = announce.encode("utf-8")
        payload[b"announce-list"] = [[announce.encode("utf-8")]]
    path.write_bytes(bencode_encode(payload))


def write_freeleech_proof(path: Path, indexer: str = "TorrentLeech") -> None:
    path.write_text(
        """
{
  "freeleech_proven": true,
  "freeleech_hits": 1,
  "freeleech": [
    {
      "indexer": "%s",
      "freeleech": {"is_freeleech": true},
      "proof_match": {"is_match": true}
    }
  ]
}
""".strip()
        % indexer,
        encoding="utf-8",
    )


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


def test_start_existing_split_blocks_freeleech_proof_tracker_mismatch(tmp_path, monkeypatch):
    mod = load_module()
    h = "0" * 40
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(
        session / f"{h.upper()}.torrent",
        "movie.mkv",
        4,
        announce="http://speed.connecting.center/passkey/announce",
    )
    payload = save / "movie.mkv"
    payload.write_bytes(b"data")
    proof = tmp_path / "proof.json"
    write_freeleech_proof(proof, "TorrentLeech")

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
        dry_run=True,
        apply=False,
        start_existing_split=True,
        allow_start_download=True,
        operator_download_approval=False,
        freeleech_proof=str(proof),
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.start_existing_split(args, mod.build_report(args))

    assert report["status"] == "blocked"
    assert report["blocked_reason"] == "freeleech_proof_tracker_mismatch"
    assert report["freeleech_tracker_match"]["proof_indexers"] == ["TorrentLeech"]
    assert report["freeleech_tracker_match"]["tracker_hosts"] == ["speed.connecting.center"]


def test_start_existing_split_allows_matching_freeleech_tracker(tmp_path, monkeypatch):
    mod = load_module()
    h = "a0" * 20
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(
        session / f"{h.upper()}.torrent",
        "movie.mkv",
        4,
        announce="https://tracker.torrentleech.org/passkey/announce",
    )
    payload = save / "movie.mkv"
    payload.write_bytes(b"data")
    proof = tmp_path / "proof.json"
    write_freeleech_proof(proof, "TorrentLeech")

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
        dry_run=True,
        apply=False,
        start_existing_split=True,
        allow_start_download=True,
        operator_download_approval=False,
        freeleech_proof=str(proof),
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.start_existing_split(args, mod.build_report(args))

    assert report["status"] == "dry_run_ok"
    assert report["freeleech_tracker_match"]["matched_indexer"] == "TorrentLeech"


def test_start_existing_split_allows_digitalcore_api_indexer_alias(tmp_path, monkeypatch):
    mod = load_module()
    h = "b0" * 20
    session = tmp_path / "session"
    save = tmp_path / "save"
    session.mkdir()
    save.mkdir()
    write_single_torrent(
        session / f"{h.upper()}.torrent",
        "movie.mkv",
        4,
        announce="https://tracker.digitalcore.club/announce/passkey",
    )
    payload = save / "movie.mkv"
    payload.write_bytes(b"data")
    proof = tmp_path / "proof.json"
    write_freeleech_proof(proof, "DigitalCore (API)")

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
        dry_run=True,
        apply=False,
        start_existing_split=True,
        allow_start_download=True,
        operator_download_approval=False,
        freeleech_proof=str(proof),
        quarantine_suffix=".invalid-for-test",
        report_json="",
    )

    report = mod.start_existing_split(args, mod.build_report(args))

    assert report["status"] == "dry_run_ok"
    assert report["freeleech_tracker_match"]["matched_indexer"] == "DigitalCore (API)"


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
        member_paths=[],
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
        member_paths=[],
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
        member_paths=[],
        max_files=0,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "unknown_requires_manual_review"
    assert audit["reason"] == "placement_scan_file_limit_reached"
    assert audit["scan_truncated"] is True


def test_placement_audit_rejects_mutation_flags(monkeypatch, capsys):
    mod = load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rt-qb-variant-split-redownload.py",
            "--hash",
            "a" * 40,
            "--placement-audit",
            "--apply",
        ],
    )

    with patch.object(mod, "build_report") as build_report:
        assert mod.main() == 2

    build_report.assert_not_called()
    captured = capsys.readouterr()
    assert "--placement-audit is read-only" in captured.err


def test_placement_audit_missing_payload_is_manual_review(tmp_path, monkeypatch):
    mod = load_module()
    h = "4" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    session.mkdir()
    seeding.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "missing.mkv", 4)

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
        member_paths=[],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "unknown_requires_manual_review"
    assert audit["reason"] == "no_existing_payload_files_to_audit"


def test_placement_audit_scan_root_missing_payload_is_manual_review(tmp_path, monkeypatch):
    mod = load_module()
    h = "5" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    unrelated = tmp_path / "data" / "media" / "shows"
    session.mkdir()
    seeding.mkdir(parents=True)
    unrelated.mkdir(parents=True)
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
        scan_roots=[str(unrelated)],
        media_prefixes=[str(tmp_path / "data" / "media" / "movies")],
        member_paths=[],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "unknown_requires_manual_review"
    assert audit["reason"] == "payload_files_not_found_in_scan_roots"
    assert str(payload) in audit["missing_expected_payload_paths"]


def test_placement_audit_media_member_wins_over_file_limit(tmp_path, monkeypatch):
    mod = load_module()
    h = "6" * 40
    session = tmp_path / "session"
    seeding = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    library = tmp_path / "data" / "media" / "movies" / "Movie"
    session.mkdir()
    seeding.mkdir(parents=True)
    library.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    payload = seeding / "movie.mkv"
    payload.write_bytes(b"data")
    (library / "movie.mkv").hardlink_to(payload)
    (library / "zzz-extra.bin").write_bytes(b"x")

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
        scan_roots=[str(seeding), str(library)],
        media_prefixes=[str(tmp_path / "data" / "media" / "movies")],
        member_paths=[],
        max_files=2,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "stash_required"
    assert audit["reason"] == "media_library_member_present"
    assert audit["scan_truncated"] is True


def test_placement_audit_proposed_two_variants_with_one_media_anchor_requires_stash(tmp_path, monkeypatch):
    mod = load_module()
    h = "7" * 40
    session = tmp_path / "session"
    rep_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    candidate_a_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "aither"
    candidate_b_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "tl"
    library = tmp_path / "data" / "media" / "movies" / "Movie"
    session.mkdir()
    for path in (rep_root, candidate_a_root, candidate_b_root, library):
        path.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    representative = rep_root / "movie.mkv"
    representative.write_bytes(b"new-variant")
    candidate_a = candidate_a_root / "movie.mkv"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b = candidate_b_root / "movie.mkv"
    candidate_b.write_bytes(b"candidate-b")
    (library / "movie.mkv").hardlink_to(candidate_a)

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(rep_root))
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
        member_paths=[str(candidate_a), str(candidate_b)],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "stash_required"
    assert audit["reason"] == "media_library_member_present"
    assert str(library / "movie.mkv") in audit["media_library_member_paths"]
    assert str(candidate_a) in audit["same_inode_member_paths"]
    assert str(candidate_b) in audit["same_inode_member_paths"]
    assert str(representative) in audit["same_inode_member_paths"]


def test_placement_audit_proposed_two_variants_without_media_anchor_is_pool_eligible(tmp_path, monkeypatch):
    mod = load_module()
    h = "8" * 40
    session = tmp_path / "session"
    rep_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    candidate_a_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "aither"
    candidate_b_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "tl"
    session.mkdir()
    for path in (rep_root, candidate_a_root, candidate_b_root):
        path.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    representative = rep_root / "movie.mkv"
    representative.write_bytes(b"new-variant")
    candidate_a = candidate_a_root / "movie.mkv"
    candidate_a.write_bytes(b"candidate-a")
    candidate_b = candidate_b_root / "movie.mkv"
    candidate_b.write_bytes(b"candidate-b")

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(rep_root))
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
        member_paths=[str(candidate_a), str(candidate_b)],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "pool_eligible"
    assert audit["reason"] == "no_media_library_members_found"
    assert audit["media_library_member_paths"] == []


def test_placement_audit_missing_proposed_member_requires_manual_review(tmp_path, monkeypatch):
    mod = load_module()
    h = "9" * 40
    session = tmp_path / "session"
    rep_root = tmp_path / "data" / "media" / "torrents" / "seeding" / "movies"
    session.mkdir()
    rep_root.mkdir(parents=True)
    write_single_torrent(session / f"{h.upper()}.torrent", "movie.mkv", 4)
    representative = rep_root / "movie.mkv"
    representative.write_bytes(b"new-variant")
    missing_candidate = tmp_path / "data" / "media" / "torrents" / "seeding" / "cross-seed" / "missing" / "movie.mkv"

    monkeypatch.setattr(mod, "rt_get_torrent_directory", lambda *a, **k: str(rep_root))
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
        member_paths=[str(missing_candidate)],
        max_files=100,
    )

    audit = report["placement_audit"]
    assert audit["group_home"] == "unknown_requires_manual_review"
    assert audit["reason"] == "placement_member_path_missing"
    assert str(missing_candidate) in audit["missing_placement_member_paths"]
