"""
Tests for torrent view builder.
"""

import os
from pathlib import Path

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
