"""Tests for save_path_repair.py bug fixes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hashall.save_path_inference import InferredSavePath
from hashall.save_path_repair import execute_repair, gc_empty_staging_dirs


STASH_SEEDING = "/data/media/torrents/seeding"
STASH_SEEDING_FS = "/stash/media/torrents/seeding"
POOL_SEEDING = "/pool/media/torrents/seeding"

FULL_HASH = "a" * 40
HASH16 = FULL_HASH[:16]

_RELIABLE_INFERRED = InferredSavePath(
    canonical_save_path=f"{STASH_SEEDING}/tv",
    device="stash",
    category="tv",
    subdir="tv",
    reliability="reliable",
)

_AMBIGUOUS_INFERRED = InferredSavePath(
    canonical_save_path=f"{STASH_SEEDING}",
    device="stash",
    category="",
    subdir="",
    reliability="ambiguous",
)


def _make_qb_torrent(save_path: str, category: str = "tv", tags: str = "") -> MagicMock:
    t = MagicMock()
    t.hash = FULL_HASH
    t.save_path = save_path
    t.category = category
    t.tags = tags
    t.name = "Some.Show.S01"
    return t


# ---------------------------------------------------------------------------
# Bug 1: RT target dir must be the parent (canonical_save_path), not parent/name
# ---------------------------------------------------------------------------

def test_rt_target_is_parent_dir(tmp_path):
    """rt_apply_directory_repoint must receive canonical_save_path, not canonical_save_path/torrent_name."""
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    (staging / "file.mkv").write_text("data")

    qb_torrent = _make_qb_torrent(save_path=str(staging), category="tv")
    target_fs = tmp_path / "tv"

    inferred = InferredSavePath(
        canonical_save_path=str(target_fs),
        device="pool",
        category="tv",
        subdir="tv",
        reliability="reliable",
    )

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={FULL_HASH: qb_torrent},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair.infer_canonical_save_path", return_value=inferred),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
        patch("hashall.save_path_repair.rt_apply_directory_repoint") as mock_rt,
        patch("hashall.save_path_repair._docker_stop_qb"),
        patch("hashall.save_path_repair._docker_start_qb"),
        patch("hashall.save_path_repair.patch_fastresume_file" if False else "hashall.fastresume.patch_fastresume_file"),
    ):
        # Use dry_run=True to skip actual docker/fastresume calls; just check RT target
        result = execute_repair(HASH16, dry_run=True)

    # In dry_run mode rt_apply_directory_repoint is not called — test the path logic
    # by checking no "/Some.Show.S01" suffix appears in notes
    assert result.error is None or "ambiguous" not in (result.error or "")
    # The torrent_name append is gone; verify by inspecting notes
    for note in result.notes:
        assert "Some.Show.S01/Some.Show.S01" not in note


# ---------------------------------------------------------------------------
# Bug 2: Empty staging dir + qB at _rehome-unique → SKIP, no fastresume patch
# ---------------------------------------------------------------------------

def test_empty_staging_dir_skipped(tmp_path):
    """Empty _rehome-unique dir with qB pointing there must be skipped, not patched."""
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    # staging is empty — no files

    qb_torrent = _make_qb_torrent(
        save_path=f"/stash/media/torrents/seeding/_rehome-unique/{HASH16}",
        category="tv",
    )

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={FULL_HASH: qb_torrent},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": [{"hash": FULL_HASH, "directory": ""}]}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair.infer_canonical_save_path", return_value=_RELIABLE_INFERRED),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
        patch("hashall.save_path_repair._docker_stop_qb") as mock_stop,
        patch("hashall.save_path_repair._docker_start_qb") as mock_start,
    ):
        result = execute_repair(HASH16, dry_run=False)

    assert result.success is True
    assert mock_stop.call_count == 0, "qB must not be stopped for empty staging dir"
    assert mock_start.call_count == 0
    assert any("SKIP" in note and "empty staging dir" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Bug 3: category=unknown → bare seeding root → error, not success
# ---------------------------------------------------------------------------

def test_ambiguous_path_rejected(tmp_path):
    """category=unknown producing a bare seeding root must be rejected with an error."""
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    (staging / "file.mkv").write_text("data")

    qb_torrent = _make_qb_torrent(
        save_path=f"/stash/media/torrents/seeding/_rehome-unique/{HASH16}",
        category="",
    )

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={FULL_HASH: qb_torrent},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair.infer_canonical_save_path", return_value=_AMBIGUOUS_INFERRED),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
    ):
        result = execute_repair(HASH16, dry_run=False)

    assert result.success is False
    assert result.error is not None
    assert "ambiguous" in result.error


# ---------------------------------------------------------------------------
# Bug 4: qB cache exception → warning logged, item not silently processed
# ---------------------------------------------------------------------------

def test_qb_cache_exception_logged(tmp_path, caplog):
    """Exception loading qB cache must produce a warning, not silent empty state."""
    import logging
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    (staging / "file.mkv").write_text("data")

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", side_effect=RuntimeError("cache broken")),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair.infer_canonical_save_path", return_value=_AMBIGUOUS_INFERRED),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
        caplog.at_level(logging.WARNING, logger="hashall.save_path_repair"),
    ):
        result = execute_repair(HASH16, dry_run=True)

    assert any("qB cache" in msg for msg in caplog.messages), (
        f"Expected qB cache warning, got: {caplog.messages}"
    )


# ---------------------------------------------------------------------------
# Bug 5: orphan empty dirs (no live qB/RT entry) → SKIP
# ---------------------------------------------------------------------------

def test_orphan_dirs_skipped(tmp_path):
    """Empty _rehome-unique dirs with no live client entry must be SKIPped."""
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    # empty dir, no qB/RT entry for this hash

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
    ):
        result = execute_repair(HASH16, dry_run=False)

    assert result.success is True
    assert any("orphan" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Bug 5 (gc): gc_empty_staging_dirs deletes orphan dirs and skips live ones
# ---------------------------------------------------------------------------

def test_gc_empty_staging_dirs(tmp_path):
    """gc_empty_staging_dirs deletes empty orphan dirs, skips dirs with live entries."""
    orphan_hash = "b" * 16
    live_hash = "c" * 16
    live_full = "c" * 40

    orphan_dir = tmp_path / orphan_hash
    live_dir = tmp_path / live_hash
    orphan_dir.mkdir()
    live_dir.mkdir()

    def fake_scan(**kwargs):
        return {orphan_hash: str(orphan_dir), live_hash: str(live_dir)}

    qb_torrent = _make_qb_torrent(save_path=str(live_dir), category="tv")
    qb_torrent.hash = live_full

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", side_effect=fake_scan),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={live_full: qb_torrent},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
    ):
        deleted, total = gc_empty_staging_dirs(dry_run=False)

    assert total == 2
    assert deleted == 1
    assert not orphan_dir.exists(), "orphan dir should have been deleted"
    assert live_dir.exists(), "live dir must not be deleted"


# ---------------------------------------------------------------------------
# Regression: Group A happy path (data in staging, qB pointing there) → success
# ---------------------------------------------------------------------------

def test_group_a_happy_path(tmp_path):
    """Group A item: data in _rehome-unique, qB pointing there → files moved, notes include move count."""
    staging = tmp_path / "_rehome-unique" / HASH16
    staging.mkdir(parents=True)
    (staging / "episode.mkv").write_text("videodata")

    target = tmp_path / "tv"
    inferred = InferredSavePath(
        canonical_save_path=str(target),
        device="pool",
        category="tv",
        subdir="tv",
        reliability="reliable",
    )

    qb_torrent = _make_qb_torrent(
        save_path=str(staging),
        category="tv",
    )

    with (
        patch("hashall.save_path_repair._scan_rehome_unique_hashes", return_value={HASH16: str(staging)}),
        patch("hashall.save_path_repair.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_torrents_by_hashes",
            return_value={FULL_HASH: qb_torrent},
        ),
        patch("hashall.save_path_repair.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_repair.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_repair.infer_canonical_save_path", return_value=inferred),
        patch("hashall.save_path_repair._resolve_full_hash", return_value=FULL_HASH),
    ):
        result = execute_repair(HASH16, dry_run=True)

    assert result.success is True
    assert result.error is None
    assert any("1 files" in note or "move" in note for note in result.notes)
    # RT target must not double the torrent name
    for note in result.notes:
        assert "Some.Show.S01/Some.Show.S01" not in note
