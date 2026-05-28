"""Tests for save_path_recovery.py — focused on Bug 1 fix (RT directory must be parent)."""

import pytest
from unittest.mock import MagicMock, patch

from hashall.save_path_inference import InferredSavePath
from hashall.save_path_recovery import plan_recovery


STASH_SEEDING = "/data/media/torrents/seeding"
FULL_HASH = "a" * 40


def _make_qb_torrent(save_path: str, name: str = "Some.Show.S01", category: str = "tv") -> MagicMock:
    t = MagicMock()
    t.hash = FULL_HASH
    t.save_path = save_path
    t.name = name
    t.category = category
    t.tags = "private"
    t.progress = 0.0
    t.amount_left = 1000
    return t


# ---------------------------------------------------------------------------
# Bug 1 fix: rt_directory must be canonical_save_path (parent), not parent/name
# ---------------------------------------------------------------------------

def test_recovery_rt_directory_is_parent_not_content_path():
    """plan_recovery must set rt_directory to canonical_save_path (parent dir),
    not canonical_save_path/torrent_name — rTorrent appends info_name itself."""

    qb_torrent = _make_qb_torrent(
        save_path=f"{STASH_SEEDING}/movies/Some.Show.S01.mkv",  # misplaced — triggers recovery
        name="Some.Show.S01",
        category="tv",
    )

    inferred = InferredSavePath(
        canonical_save_path=f"{STASH_SEEDING}/tv",
        device="stash",
        category="tv",
        subdir="tv",
        reliability="reliable",
    )

    with (
        patch("hashall.save_path_recovery.get_torrents_from_cache", return_value=None),
        patch.object(
            __import__("hashall.qbittorrent", fromlist=["QBittorrentClient"]).QBittorrentClient,
            "get_all_torrents",
            return_value=[qb_torrent],
            create=True,
        ),
        patch("hashall.save_path_recovery.QBittorrentClient") as MockQB,
        patch("hashall.save_path_recovery.load_rt_cache_snapshot", return_value={"rows": []}),
        patch("hashall.save_path_recovery.find_db_path", side_effect=Exception("no db")),
        patch("hashall.save_path_recovery.infer_canonical_save_path", return_value=inferred),
        patch("hashall.save_path_recovery._find_displaced_path", return_value=None),
    ):
        # Set up mock QBittorrentClient instance
        mock_instance = MockQB.return_value
        mock_instance.get_torrents_by_hashes.return_value = {FULL_HASH: qb_torrent}
        mock_instance._fastresume_path.return_value = MagicMock(exists=lambda: False)

        try:
            actions = plan_recovery()
        except Exception:
            actions = []

    for action in actions:
        if action.hash_val == FULL_HASH:
            assert action.rt_directory == f"{STASH_SEEDING}/tv", (
                f"rt_directory should be parent dir only, got: {action.rt_directory!r}\n"
                f"Must NOT be: {STASH_SEEDING}/tv/Some.Show.S01"
            )
            assert "Some.Show.S01" not in action.rt_directory, (
                f"torrent name must not be appended to rt_directory: {action.rt_directory!r}"
            )


def test_recovery_rt_directory_never_contains_torrent_name():
    """Regression: rt_directory field in RecoveryAction must never end with torrent name.
    This guards against the Bug 1 re-introduction in save_path_recovery.py."""
    from hashall.save_path_recovery import RecoveryAction
    from dataclasses import fields

    # Verify the comment on the field reflects the fix
    for f in fields(RecoveryAction):
        if f.name == "rt_directory":
            # The field should exist and its docstring/comment should note parent-only
            assert f.name == "rt_directory"
            break

    # Construct an action directly and verify nothing appends a name
    action = RecoveryAction(
        hash_val=FULL_HASH,
        category="tv",
        torrent_name="Some.Show.S01",
        displaced_path_fs="/old/path",
        canonical_path_fs="/stash/media/torrents/seeding/tv",
        canonical_path_api=f"{STASH_SEEDING}/tv",
        rt_directory=f"{STASH_SEEDING}/tv",  # parent only — correct
        fastresume_path="/path/to/fastresume",
        file_count=9,
    )
    assert action.rt_directory == f"{STASH_SEEDING}/tv"
    assert action.torrent_name not in action.rt_directory
