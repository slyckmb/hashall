from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "bin" / "qb-repair-fresh.py"
    spec = importlib.util.spec_from_file_location("qb_repair_fresh", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_hardlink_build_relinks_existing_identical_copy(tmp_path):
    mod = _load_module()
    source_save = tmp_path / "source"
    target_save = tmp_path / "target"
    source_save.mkdir()
    target_save.mkdir()

    src = source_save / "movie.mkv"
    dst = target_save / "movie.mkv"
    src.write_bytes(b"same-bytes")
    dst.write_bytes(b"same-bytes")

    manifest = [mod.ManifestEntry(rel_path="movie.mkv", size=src.stat().st_size)]

    ok, stats, _msg = mod.hardlink_build(str(source_save), str(target_save), manifest)

    assert ok is True
    assert stats["relinked"] == 1
    assert dst.exists()
    assert src.stat().st_ino == dst.stat().st_ino


def test_hardlink_build_counts_existing_hardlink_without_relink(tmp_path):
    mod = _load_module()
    source_save = tmp_path / "source"
    target_save = tmp_path / "target"
    source_save.mkdir()
    target_save.mkdir()

    src = source_save / "movie.mkv"
    dst = target_save / "movie.mkv"
    src.write_bytes(b"same-bytes")
    dst.hardlink_to(src)

    manifest = [mod.ManifestEntry(rel_path="movie.mkv", size=src.stat().st_size)]

    ok, stats, _msg = mod.hardlink_build(str(source_save), str(target_save), manifest)

    assert ok is True
    assert stats["existed"] == 1
    assert stats["relinked"] == 0
    assert src.stat().st_ino == dst.stat().st_ino
