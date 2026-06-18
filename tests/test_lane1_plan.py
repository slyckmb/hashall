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
)
from hashall.lane1_plan import Lane1PlanItem, build_lane1_plan

SOURCE_DIR = "/pool/media/torrents/seeding/darkpeers/SomeRelease"
PARENT_DIR = "/pool/media/torrents/seeding/darkpeers"
TARGET_DIR = "/pool/media/torrents/seeding/cross-seed/darkpeers/SomeRelease"
TARGET_PARENT = "/pool/media/torrents/seeding/cross-seed/darkpeers"
CANONICAL_SAVE = "/pool/media/torrents/seeding/cross-seed/darkpeers"


def _make_resolution(
    qb_drift: DriftType = DriftType.CATEGORY_DRIFT,
    rt_drift: DriftType = DriftType.CATEGORY_DRIFT,
    save_path: str = SOURCE_DIR,
    rt_path: str = SOURCE_DIR,
    name: str = "SomeRelease",
    tor_hash: str = "a" * 40,
) -> ItemResolution:
    canonical = CanonicalPathResult(
        canonical_path=CANONICAL_SAVE,
        canonical_content_path=TARGET_DIR,
        item_type=ItemType.CROSS_SEED,
        seeding_device=SeedingDevice.POOL,
        category_subdir="cross-seed/darkpeers",
        payload_name=name,
    )
    qb_diff = ClientDiffResult(
        client="qb", drift_type=qb_drift, actual_path=save_path,
        canonical_path=CANONICAL_SAVE,
    )
    rt_diff = ClientDiffResult(
        client="rt", drift_type=rt_drift, actual_path=rt_path,
        canonical_path=CANONICAL_SAVE,
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
                source_exists=True, target_exists=False, parent_exists=True):
    """Helper to build plan with path-aware mocks.

    os.path.isdir returns True only for the source and its parent directories.
    os.path.isfile returns False for everything.
    os.stat returns src_dev for source paths and tgt_dev for target paths.
    """
    def fake_isdir(path):
        p = str(path)
        if not parent_exists and TARGET_PARENT in p and TARGET_DIR not in p:
            return False
        if not target_exists and TARGET_DIR in p:
            return False
        if not source_exists and SOURCE_DIR in p and TARGET_DIR not in p:
            return False
        return True

    def fake_stat(path):
        p = str(path)
        class FS:
            st_dev = src_dev if SOURCE_DIR in p and TARGET_DIR not in p else tgt_dev
        return FS()

    with patch("os.path.isdir", side_effect=fake_isdir), \
         patch("os.path.isfile", return_value=False), \
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
