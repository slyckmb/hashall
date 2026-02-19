"""
Tests for torrent view builder.
"""

import os
import errno
from pathlib import Path

import pytest

from hashall.qbittorrent import QBitFile
from rehome.view_builder import build_torrent_view


def test_build_view_multifile_with_root_prefix(tmp_path):
    payload_root = tmp_path / "payload" / "Movie.2024"
    payload_root.mkdir(parents=True)

    video = payload_root / "video.mkv"
    subs = payload_root / "subs" / "movie.srt"
    subs.parent.mkdir(parents=True)
    video.write_text("video")
    subs.write_text("subs")

    files = [
        QBitFile(name="Movie.2024/video.mkv", size=video.stat().st_size),
        QBitFile(name="Movie.2024/subs/movie.srt", size=subs.stat().st_size),
    ]

    target_save = tmp_path / "views"
    result = build_torrent_view(payload_root, target_save, files, root_name="Movie.2024")

    view_root = target_save / "Movie.2024"
    assert result.view_root == view_root
    assert (view_root / "video.mkv").exists()
    assert (view_root / "subs" / "movie.srt").exists()

    assert os.stat(view_root / "video.mkv").st_ino == os.stat(video).st_ino
    assert os.stat(view_root / "subs" / "movie.srt").st_ino == os.stat(subs).st_ino


def test_build_view_single_file(tmp_path):
    payload_root = tmp_path / "payload" / "audio.flac"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_text("audio")

    files = [
        QBitFile(name="audio.flac", size=payload_root.stat().st_size),
    ]

    target_save = tmp_path / "views"
    target_save.mkdir()

    result = build_torrent_view(payload_root, target_save, files, root_name="Audio")

    view_file = target_save / "audio.flac"
    assert result.view_root == target_save
    assert view_file.exists()
    assert os.stat(view_file).st_ino == os.stat(payload_root).st_ino


def test_build_view_accepts_existing_identical_file(tmp_path):
    payload_root = tmp_path / "payload" / "Longlegs.2024.mkv"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_bytes(b"A" * 4096)

    files = [QBitFile(name="Longlegs.2024.mkv", size=payload_root.stat().st_size)]
    target_save = tmp_path / "views"
    target_save.mkdir()
    preexisting = target_save / "Longlegs.2024.mkv"
    preexisting.write_bytes(b"A" * 4096)  # same bytes, different inode

    result = build_torrent_view(payload_root, target_save, files, root_name=None)
    assert result.view_root == target_save
    assert preexisting.exists()
    assert preexisting.read_bytes() == payload_root.read_bytes()


def test_build_view_compare_hint_accepts_existing(tmp_path):
    payload_root = tmp_path / "payload" / "sample.mkv"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_bytes(b"ABCDEF")

    files = [QBitFile(name="sample.mkv", size=payload_root.stat().st_size)]
    target_save = tmp_path / "views"
    target_save.mkdir()
    preexisting = target_save / "sample.mkv"
    preexisting.write_bytes(b"XXXXXX")  # different content

    result = build_torrent_view(
        payload_root,
        target_save,
        files,
        root_name=None,
        compare_hint=lambda _src, _dst: True,
    )

    assert result.view_root == target_save
    assert preexisting.exists()


def test_build_view_compare_hint_rejects_existing(tmp_path):
    payload_root = tmp_path / "payload" / "sample.mkv"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_bytes(b"ABCDEF")

    files = [QBitFile(name="sample.mkv", size=payload_root.stat().st_size)]
    target_save = tmp_path / "views"
    target_save.mkdir()
    preexisting = target_save / "sample.mkv"
    preexisting.write_bytes(b"XXXXXX")

    with pytest.raises(RuntimeError, match="Destination exists and differs"):
        build_torrent_view(
            payload_root,
            target_save,
            files,
            root_name=None,
            compare_hint=lambda _src, _dst: False,
        )


def test_build_view_accepts_link_race_file_exists(tmp_path, monkeypatch):
    payload_root = tmp_path / "payload" / "race.mkv"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_bytes(b"RACE")

    files = [QBitFile(name="race.mkv", size=payload_root.stat().st_size)]
    target_save = tmp_path / "views"
    target_save.mkdir()
    dst = target_save / "race.mkv"

    real_link = os.link

    def link_with_race(src, target, *args, **kwargs):
        # Simulate another process creating the link between exists() and os.link().
        if not os.path.exists(target):
            real_link(src, target)
        raise FileExistsError(errno.EEXIST, "File exists", target)

    monkeypatch.setattr("rehome.view_builder.os.link", link_with_race)

    result = build_torrent_view(payload_root, target_save, files, root_name=None)
    assert result.view_root == target_save
    assert dst.exists()
    assert os.stat(dst).st_ino == os.stat(payload_root).st_ino


def test_build_view_accepts_link_race_eexist_oserror(tmp_path, monkeypatch):
    payload_root = tmp_path / "payload" / "race-oserror.mkv"
    payload_root.parent.mkdir(parents=True)
    payload_root.write_bytes(b"RACE2")

    files = [QBitFile(name="race-oserror.mkv", size=payload_root.stat().st_size)]
    target_save = tmp_path / "views"
    target_save.mkdir()
    dst = target_save / "race-oserror.mkv"

    real_link = os.link

    def link_with_race_oserror(src, target, *args, **kwargs):
        if not os.path.exists(target):
            real_link(src, target)
        raise OSError(errno.EEXIST, "File exists", target)

    monkeypatch.setattr("rehome.view_builder.os.link", link_with_race_oserror)

    result = build_torrent_view(payload_root, target_save, files, root_name=None)
    assert result.view_root == target_save
    assert dst.exists()
    assert os.stat(dst).st_ino == os.stat(payload_root).st_ino
