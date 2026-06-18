"""Tests for lane1_plan.py — Lane 1 dry-run plan generator."""

import os
from unittest.mock import patch

import pytest

from hashall.canonical_path_resolver import (
    DriftType,
    CanonicalPathResult,
    ClientDiffResult,
    ItemResolution,
    ItemType,
    SeedingDevice,
    STASH_ROOT,
    POOL_ROOT,
)
from hashall.lane1_plan import Lane1PlanItem, build_lane1_plan, _is_safe_source_dir

SOURCE_DIR = "/pool/media/torrents/seeding/darkpeers"
PARENT_DIR = "/pool/media/torrents/seeding"
TARGET_DIR = "/pool/media/torrents/seeding/cross-seed/darkpeers/SomeRelease"
TARGET_PARENT = "/pool/media/torrents/seeding/cross-seed/darkpeers"
CANONICAL_SAVE = "/pool/media/torrents/seeding/cross-seed/darkpeers"
STASH_SOURCE = "/data/media/torrents/seeding/XSpeeds"
STASH_CANONICAL = "/data/media/torrents/seeding/cross-seed/XSpeeds"


def _make_resolution(
    qb_drift: DriftType = DriftType.CATEGORY_DRIFT,
    rt_drift: DriftType = DriftType.CATEGORY_DRIFT,
    save_path: str = SOURCE_DIR,
    rt_path: str = SOURCE_DIR,
    name: str = "SomeRelease",
    tor_hash: str = "a" * 40,
    canonical_save: str = CANONICAL_SAVE,
) -> ItemResolution:
    content_path = f"{canonical_save}/{name}"
    device = (SeedingDevice.POOL if "/pool/" in canonical_save
              else SeedingDevice.STASH)
    canonical = CanonicalPathResult(
        canonical_path=canonical_save,
        canonical_content_path=content_path,
        item_type=ItemType.CROSS_SEED,
        seeding_device=device,
        category_subdir="cross-seed/darkpeers",
        payload_name=name,
    )
    qb_diff = ClientDiffResult(
        client="qb", drift_type=qb_drift, actual_path=save_path,
        canonical_path=canonical_save,
    )
    rt_diff = ClientDiffResult(
        client="rt", drift_type=rt_drift, actual_path=rt_path,
        canonical_path=canonical_save,
    )
    return ItemResolution(
        torrent_hash=tor_hash,
        canonical=canonical,
        qb_diff=qb_diff,
        rt_diff=rt_diff,
        action="Rename directory and/or repoint both.",
        needs_human_review=False,
    )


def _build_plan(resolutions, src_dev=42, tgt_dev=42,
                source_exists=True, target_exists=False, parent_exists=True,
                category_dir_exists=False):
    """Helper to build plan with path-aware mocks."""

    def fake_isdir(path):
        p = str(path).rstrip("/")
        if not parent_exists and p == TARGET_PARENT:
            return False
        if not target_exists and p == TARGET_DIR:
            return False
        if not source_exists and p == SOURCE_DIR:
            return False
        return True

    def fake_exists(path):
        return category_dir_exists if str(path) == CANONICAL_SAVE else False

    def fake_stat(path):
        p = str(path).rstrip("/")
        class FS:
            st_dev = src_dev if p == SOURCE_DIR else tgt_dev
        return FS()

    with patch("os.path.isdir", side_effect=fake_isdir), \
         patch("os.path.isfile", return_value=False), \
         patch("os.path.exists", side_effect=fake_exists), \
         patch("os.stat", side_effect=fake_stat):
        return build_lane1_plan(resolutions)


class TestBuildLane1Plan:
    def test_both_drift_safe(self):
        """Both clients CATEGORY_DRIFT, source exists, target absent, same device → safe."""
        res = _make_resolution()
        plan = _build_plan([res])
        assert len(plan) == 1
        assert plan[0].safe is True
        assert plan[0].source_exists is True
        assert plan[0].target_exists is False
        assert plan[0].same_device is True

    def test_source_missing(self):
        """Source directory does not exist → safe=False."""
        res = _make_resolution()
        plan = _build_plan([res], source_exists=False)
        assert len(plan) == 1
        assert plan[0].safe is False
        assert plan[0].source_exists is False

    def test_target_exists(self):
        """Target already exists → safe=False."""
        res = _make_resolution()
        plan = _build_plan([res], target_exists=True)
        assert len(plan) == 1
        assert plan[0].safe is False
        assert plan[0].target_exists is True

    def test_cross_device(self):
        """Different device → safe=False."""
        res = _make_resolution()
        plan = _build_plan([res], src_dev=42, tgt_dev=99)
        assert len(plan) == 1
        assert plan[0].safe is False
        assert plan[0].same_device is False

    def test_one_canonical_one_drift(self):
        """One client CANONICAL, other CATEGORY_DRIFT → included in plan."""
        res = _make_resolution(qb_drift=DriftType.CANONICAL, rt_drift=DriftType.CATEGORY_DRIFT)
        plan = _build_plan([res])
        assert len(plan) == 1
        assert plan[0].safe is True

    def test_root_drift_excluded(self):
        """ROOT_DRIFT item → excluded from plan."""
        res = _make_resolution(qb_drift=DriftType.ROOT_DRIFT, rt_drift=DriftType.ROOT_DRIFT)
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_path_missing_excluded(self):
        """PATH_MISSING item → excluded from plan."""
        res = _make_resolution(qb_drift=DriftType.PATH_MISSING, rt_drift=DriftType.PATH_MISSING)
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_staging_needs_repair_excluded(self):
        """STAGING_NEEDS_REPAIR item → excluded from plan."""
        res = _make_resolution(
            qb_drift=DriftType.STAGING_NEEDS_REPAIR,
            rt_drift=DriftType.STAGING_NEEDS_REPAIR,
        )
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_multiple_items_mixed(self):
        """Mixed items: only eligible items appear in plan."""
        safe_res = _make_resolution(tor_hash="s" * 40, name="Safe")
        skip_res = _make_resolution(
            tor_hash="x" * 40, name="Skip",
            qb_drift=DriftType.ROOT_DRIFT, rt_drift=DriftType.ROOT_DRIFT,
        )
        plan = _build_plan([safe_res, skip_res])
        assert len(plan) == 1
        assert plan[0].name == "Safe"

    def test_compound_drift_pool_to_stash_excluded(self):
        """Source on POOL, canonical on STASH → excluded (compound drift)."""
        res = _make_resolution(
            save_path=SOURCE_DIR,
            canonical_save=STASH_CANONICAL,
        )
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_compound_drift_stash_to_pool_excluded(self):
        """Source on STASH, canonical on POOL → excluded (compound drift)."""
        res = _make_resolution(
            save_path=STASH_SOURCE,
            canonical_save=CANONICAL_SAVE,
        )
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_same_root_stash_eligible(self):
        """Source on STASH, canonical on STASH (different subdir) → eligible."""
        res = _make_resolution(
            save_path=STASH_SOURCE,
            canonical_save=STASH_CANONICAL,
        )
        def stash_isdir(path):
            p = str(path)
            if "cross-seed" in p:
                return False  # target doesn't exist
            return True  # source exists
        def stash_stat(path):
            return type("", (), {"st_dev": 42})()
        with patch("os.path.isdir", side_effect=stash_isdir), \
             patch("os.path.isfile", return_value=False), \
             patch("os.path.exists", return_value=False), \
             patch("os.stat", side_effect=stash_stat):
            plan = build_lane1_plan([res])
        assert len(plan) == 1
        assert plan[0].safe is True

    def test_same_root_pool_eligible(self):
        """Source on POOL, canonical on POOL (different subdir) → eligible."""
        res = _make_resolution()
        plan = _build_plan([res])
        assert len(plan) == 1
        assert plan[0].safe is True

    def test_source_path_none_excluded(self):
        """source_path=None (PATH_MISSING) → excluded."""
        res = _make_resolution(save_path="", rt_path="")
        plan = _build_plan([res])
        assert len(plan) == 0


class TestIsSafeSourceDir:
    def test_category_level_valid(self):
        """One level below root (darkpeers) → valid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding/darkpeers") is True

    def test_cross_seed_tracker_valid(self):
        """cross-seed/<tracker> (two levels) → valid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding/cross-seed/darkpeers") is True

    def test_seeding_root_invalid(self):
        """Seeding root itself → invalid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding") is False

    def test_cross_seed_root_invalid(self):
        """cross-seed root (no tracker subdir) → invalid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding/cross-seed") is False

    def test_content_subdir_invalid(self):
        """Two levels below root (darkpeers/SomeRelease) → invalid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding/darkpeers/SomeRelease") is False

    def test_deep_path_invalid(self):
        """Three levels below root → invalid."""
        assert _is_safe_source_dir("/pool/media/torrents/seeding/tv/Show.S01/S01E01") is False

    def test_none_invalid(self):
        assert _is_safe_source_dir(None) is False

    def test_empty_invalid(self):
        assert _is_safe_source_dir("") is False


class TestBuildLane1PlanDepthFilter:
    """Lane 1 eligibility with source depth filtering."""

    def test_source_at_seeding_root_excluded(self):
        """Source at seeding root level → excluded."""
        res = _make_resolution(
            save_path="/pool/media/torrents/seeding",
        )
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_source_at_cross_seed_root_excluded(self):
        """Source at cross-seed category root → excluded."""
        res = _make_resolution(
            save_path="/pool/media/torrents/seeding/cross-seed",
            canonical_save="/pool/media/torrents/seeding/cross-seed/torrentleech",
        )
        plan = _build_plan([res])
        assert len(plan) == 0

    def test_source_at_content_subdir_excluded(self):
        """Source at content subdir (3 levels deep) → excluded."""
        res = _make_resolution(
            save_path="/pool/media/torrents/seeding/tv/Show.S01",
            canonical_save="/pool/media/torrents/seeding/torrentleech",
        )
        plan = _build_plan([res])
        assert len(plan) == 0
