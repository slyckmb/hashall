import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from hashall.bencode import bencode_encode
from hashall.cli import cli
from hashall.torrent_verify import result_to_dict, verify_torrent_pieces


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


def test_failed_piece_maps_to_media_mismatch(tmp_path: Path) -> None:
    torrent = tmp_path / "movie.torrent"
    write_single_torrent(torrent, "movie.mkv", b"abcdefgh", piece_length=4)
    (tmp_path / "movie.mkv").write_bytes(b"abcdWXYZ")

    result = verify_torrent_pieces(torrent, tmp_path, collect_piece_details=True)

    assert not result.success
    assert result.pieces_fail == 1
    assert result.failed_pieces[0].piece_index == 1
    assert result.failed_pieces[0].classification == "media_piece_mismatch"
    assert result.failed_pieces[0].spans[0].rel_path == "movie.mkv"


def test_failed_piece_maps_to_sidecar_only_missing(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"abcd"), ("episode.mkv", b"efgh")],
        piece_length=4,
    )
    root = tmp_path / "release"
    root.mkdir()
    (root / "episode.mkv").write_bytes(b"efgh")

    result = verify_torrent_pieces(torrent, tmp_path, collect_piece_details=True)

    assert not result.success
    assert result.pieces_missing == 1
    assert result.failed_pieces[0].classification == "sidecar_only_missing"
    assert result.failed_pieces[0].spans[0].kind == "sidecar"


def test_failed_piece_maps_to_sidecar_media_boundary(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    root = tmp_path / "release"
    root.mkdir()
    (root / "release.nfo").write_bytes(b"ab")
    (root / "episode.mkv").write_bytes(b"XYef")

    result = verify_torrent_pieces(torrent, tmp_path, collect_piece_details=True)

    assert not result.success
    assert result.pieces_fail == 1
    assert result.failed_pieces[0].classification == "sidecar_media_boundary_piece"
    assert {span.kind for span in result.failed_pieces[0].spans} == {"sidecar", "media"}


def test_compare_root_classifies_sidecar_only_boundary_diff(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "release.nfo").write_bytes(b"XY")
    (bad / "episode.mkv").write_bytes(b"cdef")
    (good / "release.nfo").write_bytes(b"ab")
    (good / "episode.mkv").write_bytes(b"cdef")

    result = verify_torrent_pieces(
        torrent,
        bad.parent,
        content_root=bad,
        compare_root=good,
        collect_piece_details=True,
    )

    assert not result.success
    piece = result.failed_pieces[0]
    assert piece.comparison_classification == "sidecar_only_diff"
    verdicts = {c.kind: c.verdict for c in piece.span_comparisons}
    assert verdicts == {"sidecar": "different", "media": "same"}


def test_compare_root_classifies_media_only_boundary_diff(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "release.nfo").write_bytes(b"ab")
    (bad / "episode.mkv").write_bytes(b"XYef")
    (good / "release.nfo").write_bytes(b"ab")
    (good / "episode.mkv").write_bytes(b"cdef")

    result = verify_torrent_pieces(
        torrent,
        bad.parent,
        content_root=bad,
        compare_root=good,
        collect_piece_details=True,
    )

    assert not result.success
    piece = result.failed_pieces[0]
    assert piece.comparison_classification == "media_only_diff"
    verdicts = {c.kind: c.verdict for c in piece.span_comparisons}
    assert verdicts == {"sidecar": "same", "media": "different"}


def test_compare_root_classifies_sidecar_and_media_boundary_diff(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "release.nfo").write_bytes(b"XY")
    (bad / "episode.mkv").write_bytes(b"ZWef")
    (good / "release.nfo").write_bytes(b"ab")
    (good / "episode.mkv").write_bytes(b"cdef")

    result = verify_torrent_pieces(
        torrent,
        bad.parent,
        content_root=bad,
        compare_root=good,
        collect_piece_details=True,
    )

    assert not result.success
    assert result.failed_pieces[0].comparison_classification == "sidecar_and_media_diff"


def test_content_root_verifies_split_payload_with_nonmatching_root_name(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"abcd"), ("episode.mkv", b"efgh")],
        piece_length=4,
    )
    quarantine = tmp_path / "release.invalid-for-hash"
    quarantine.mkdir()
    (quarantine / "release.nfo").write_bytes(b"abcd")
    (quarantine / "episode.mkv").write_bytes(b"efgh")

    result = verify_torrent_pieces(
        torrent,
        quarantine.parent,
        content_root=quarantine,
        collect_piece_details=True,
    )

    assert result.success
    assert result_to_dict(result)["failed_pieces"] == []


def test_cli_verify_pieces_json_maps_payload_root_without_qb(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    payload = tmp_path / "release.invalid-for-hash"
    payload.mkdir()
    (payload / "release.nfo").write_bytes(b"ab")
    (payload / "episode.mkv").write_bytes(b"XYef")

    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "verify-pieces",
            "abc123",
            "--torrent-file",
            str(torrent),
            "--payload-root",
            str(payload),
            "--json-output",
        ],
    )

    assert result.exit_code == 1
    report = json.loads(result.output[result.output.find("{"):])
    assert report["pieces_fail"] == 1
    assert report["failed_pieces"][0]["classification"] == "sidecar_media_boundary_piece"


def test_cli_verify_pieces_compare_root_reports_span_verdicts(tmp_path: Path) -> None:
    torrent = tmp_path / "release.torrent"
    write_multi_torrent(
        torrent,
        "release",
        [("release.nfo", b"ab"), ("episode.mkv", b"cdef")],
        piece_length=4,
    )
    bad = tmp_path / "bad"
    good = tmp_path / "good"
    bad.mkdir()
    good.mkdir()
    (bad / "release.nfo").write_bytes(b"ab")
    (bad / "episode.mkv").write_bytes(b"XYef")
    (good / "release.nfo").write_bytes(b"ab")
    (good / "episode.mkv").write_bytes(b"cdef")

    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "verify-pieces",
            "abc123",
            "--torrent-file",
            str(torrent),
            "--payload-root",
            str(bad),
            "--compare-root",
            str(good),
            "--json-output",
        ],
    )

    assert result.exit_code == 1
    report = json.loads(result.output[result.output.find("{"):])
    piece = report["failed_pieces"][0]
    assert piece["comparison_classification"] == "media_only_diff"
    assert {c["kind"]: c["verdict"] for c in piece["span_comparisons"]} == {
        "sidecar": "same",
        "media": "different",
    }
