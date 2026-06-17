"""Tests for canonical_path_resolver.py — Steps 0-5 decision tree core."""

from dataclasses import replace

import pytest

from hashall.client_drift import ClientTorrentRow
from hashall.canonical_path_resolver import (
    STASH_ROOT,
    POOL_ROOT,
    ItemType,
    SeedingDevice,
    DriftType,
    _is_staging_path,
    classify_item_type,
    classify_seeding_device,
    resolve_category_subdir,
    assemble_canonical_path,
    diff_client_path,
    resolve_canonical_path,
)

STASH = STASH_ROOT
POOL = POOL_ROOT


# ═══════════════════════════════════════════════════════
# _is_staging_path
# ═══════════════════════════════════════════════════════


class TestIsStagingPath:
    def test_rehome_unique(self):
        assert _is_staging_path(f"{STASH}/_rehome-unique/abc123") is True

    def test_qb_finish(self):
        assert _is_staging_path(f"{STASH}/_qb-finish/abc123") is True

    def test_qb_unique_repair(self):
        assert _is_staging_path(f"{STASH}/_qb-unique-repair/abc123") is True

    def test_qb_repair_v2(self):
        assert _is_staging_path(f"{STASH}/_qb-repair-v2/abc123") is True

    def test_normal_path(self):
        assert _is_staging_path(f"{STASH}/tv/Some.Show") is False


# ═══════════════════════════════════════════════════════
# classify_item_type
# ═══════════════════════════════════════════════════════


class TestClassifyItemType:
    def test_cross_seed_category(self):
        typ, hint = classify_item_type("cross-seed", "private")
        assert typ == ItemType.CROSS_SEED
        assert hint == ""

    def test_sonarr_pre_import(self):
        typ, hint = classify_item_type("sonarr", "private")
        assert typ == ItemType.ARR_PRE_IMPORT
        assert hint == "tv"

    def test_radarr_pre_import(self):
        typ, hint = classify_item_type("radarr", "private")
        assert typ == ItemType.ARR_PRE_IMPORT
        assert hint == "movies"

    def test_tv_post_import(self):
        typ, hint = classify_item_type("tv", "private")
        assert typ == ItemType.ARR_POST_IMPORT
        assert hint == "tv"

    def test_movies_post_import(self):
        typ, hint = classify_item_type("movies", "private")
        assert typ == ItemType.ARR_POST_IMPORT
        assert hint == "movies"

    def test_abtorrents_other_explicit(self):
        typ, hint = classify_item_type("abtorrents", "private")
        assert typ == ItemType.OTHER_EXPLICIT
        assert hint == "abtorrents"

    def test_uncategorized_with_cross_seed_tag(self):
        typ, hint = classify_item_type("", "cross-seed,fearnopeer")
        assert typ == ItemType.CROSS_SEED
        assert hint == ""

    def test_uncategorized_with_tracker_tag(self):
        typ, hint = classify_item_type("Uncategorized", "fearnopeer,private")
        assert typ == ItemType.QBM_TRACKER_TAGGED
        assert hint == "fearnopeer"

    def test_empty_category_empty_tags(self):
        typ, hint = classify_item_type("", "")
        assert typ == ItemType.UNKNOWN
        assert hint == ""


# ═══════════════════════════════════════════════════════
# classify_seeding_device
# ═══════════════════════════════════════════════════════


class TestClassifySeedingDevice:
    def test_cross_seed_with_nohl(self):
        assert classify_seeding_device(ItemType.CROSS_SEED, "~noHL,private") == SeedingDevice.POOL

    def test_cross_seed_no_nohl_no_nlinks(self):
        assert classify_seeding_device(ItemType.CROSS_SEED, "private") == SeedingDevice.POOL

    def test_cross_seed_no_nohl_with_nlinks(self):
        assert classify_seeding_device(
            ItemType.CROSS_SEED, "private", catalog_nlinks=3
        ) == SeedingDevice.STASH

    def test_arr_post_with_nohl(self):
        assert classify_seeding_device(ItemType.ARR_POST_IMPORT, "~noHL,private") == SeedingDevice.POOL

    def test_arr_post_no_nohl(self):
        assert classify_seeding_device(ItemType.ARR_POST_IMPORT, "private") == SeedingDevice.STASH

    def test_arr_post_with_nlinks(self):
        assert classify_seeding_device(
            ItemType.ARR_POST_IMPORT, "private", catalog_nlinks=2
        ) == SeedingDevice.STASH

    def test_full_scan_not_implemented(self):
        with pytest.raises(NotImplementedError):
            classify_seeding_device(ItemType.CROSS_SEED, "", full_scan=True)


# ═══════════════════════════════════════════════════════
# resolve_category_subdir
# ═══════════════════════════════════════════════════════


class TestResolveCategorySubdir:
    def test_cross_seed_from_path(self):
        subdir, notes = resolve_category_subdir(
            ItemType.CROSS_SEED, "cross-seed", "private",
            save_path=f"{STASH}/cross-seed/darkpeers/SomeRelease",
        )
        assert subdir == "cross-seed/darkpeers"

    def test_cross_seed_bare_tracker_from_tags(self):
        subdir, notes = resolve_category_subdir(
            ItemType.CROSS_SEED, "cross-seed", "cross-seed,darkpeers,private",
            save_path=f"{STASH}/darkpeers/SomeRelease",
        )
        assert subdir == "cross-seed/darkpeers"

    def test_cross_seed_no_path_no_tags(self):
        subdir, notes = resolve_category_subdir(
            ItemType.CROSS_SEED, "cross-seed", "",
        )
        assert subdir == "cross-seed"

    def test_arr_pre_import_sonarr(self):
        subdir, notes = resolve_category_subdir(
            ItemType.ARR_PRE_IMPORT, "sonarr", "private",
        )
        assert subdir == "tv"

    def test_arr_pre_import_radarr(self):
        subdir, notes = resolve_category_subdir(
            ItemType.ARR_PRE_IMPORT, "radarr", "private",
        )
        assert subdir == "movies"

    def test_arr_post_import_tv(self):
        subdir, notes = resolve_category_subdir(
            ItemType.ARR_POST_IMPORT, "tv", "private",
        )
        assert subdir == "tv"

    def test_arr_post_import_movies(self):
        subdir, notes = resolve_category_subdir(
            ItemType.ARR_POST_IMPORT, "movies", "private",
        )
        assert subdir == "movies"

    def test_other_explicit_prowlarr(self):
        subdir, notes = resolve_category_subdir(
            ItemType.OTHER_EXPLICIT, "prowlarr", "private",
        )
        assert subdir == "prowlarr"

    def test_uncategorized(self):
        subdir, notes = resolve_category_subdir(
            ItemType.UNCATEGORIZED, "", "",
        )
        assert subdir == ""

    def test_unknown(self):
        subdir, notes = resolve_category_subdir(
            ItemType.UNKNOWN, "", "",
        )
        assert subdir == ""


# ═══════════════════════════════════════════════════════
# assemble_canonical_path
# ═══════════════════════════════════════════════════════


class TestAssembleCanonicalPath:
    def test_cross_seed_stash(self):
        result = assemble_canonical_path(SeedingDevice.STASH, "cross-seed/darkpeers", "SomeRelease")
        assert result == f"{STASH}/cross-seed/darkpeers/SomeRelease"

    def test_cross_seed_pool(self):
        result = assemble_canonical_path(SeedingDevice.POOL, "cross-seed/fearnopeer", "SomeRelease")
        assert result == f"{POOL}/cross-seed/fearnopeer/SomeRelease"

    def test_tv_show(self):
        result = assemble_canonical_path(SeedingDevice.STASH, "tv", "Show.S01")
        assert result == f"{STASH}/tv/Show.S01"

    def test_no_subdir(self):
        result = assemble_canonical_path(SeedingDevice.STASH, "", "bare-file.mkv")
        assert result == f"{STASH}/bare-file.mkv"


# ═══════════════════════════════════════════════════════
# diff_client_path (includes ROOT_DRIFT fix)
# ═══════════════════════════════════════════════════════


class TestDiffClientPath:
    def test_none_is_missing(self):
        assert diff_client_path(None, f"{STASH}/tv/Show") == DriftType.PATH_MISSING

    def test_staging_path(self):
        assert diff_client_path(
            f"{STASH}/_rehome-unique/abc/Show", f"{STASH}/tv/Show"
        ) == DriftType.STAGING_NEEDS_REPAIR

    def test_exact_match(self):
        assert diff_client_path(
            f"{STASH}/tv/Show.S01", f"{STASH}/tv/Show.S01"
        ) == DriftType.CANONICAL

    def test_stash_host_normalization(self):
        # /stash/media/... is the host alias for /data/media/...
        assert diff_client_path(
            "/stash/media/torrents/seeding/tv/Show.S01",
            f"{STASH}/tv/Show.S01",
        ) == DriftType.CANONICAL

    def test_root_drift_same_relative_stash_to_pool(self):
        actual = f"{POOL}/cross-seed/darkpeers/SomeRelease"
        canonical = f"{STASH}/cross-seed/darkpeers/SomeRelease"
        assert diff_client_path(actual, canonical) == DriftType.ROOT_DRIFT

    def test_root_drift_same_relative_pool_to_stash(self):
        actual = f"{STASH}/tv/Show.S01"
        canonical = f"{POOL}/tv/Show.S01"
        assert diff_client_path(actual, canonical) == DriftType.ROOT_DRIFT

    def test_category_drift_bare_tracker(self):
        actual = f"{STASH}/darkpeers/SomeRelease"
        canonical = f"{STASH}/cross-seed/darkpeers/SomeRelease"
        assert diff_client_path(actual, canonical) == DriftType.CATEGORY_DRIFT

    def test_category_drift_different_root_and_path(self):
        actual = f"{POOL}/darkpeers/SomeRelease"
        canonical = f"{STASH}/cross-seed/darkpeers/SomeRelease"
        assert diff_client_path(actual, canonical) == DriftType.CATEGORY_DRIFT


# ═══════════════════════════════════════════════════════
# resolve_canonical_path — integration tests
# ═══════════════════════════════════════════════════════


class TestResolveCanonicalPath:
    def test_cross_seed_canonical(self):
        qb = ClientTorrentRow(
            client="qb",
            torrent_hash="a" * 40,
            name="SomeRelease",
            save_path=f"{POOL}/cross-seed/darkpeers/SomeRelease",
            content_path=f"{POOL}/cross-seed/darkpeers/SomeRelease",
            category="cross-seed",
            tags="darkpeers,private,~noHL",
        )
        rt = f"{POOL}/cross-seed/darkpeers/SomeRelease"
        res = resolve_canonical_path(qb, rt)
        assert res.canonical.canonical_path == f"{POOL}/cross-seed/darkpeers/SomeRelease"
        assert res.qb_diff.drift_type == DriftType.CANONICAL
        assert res.rt_diff.drift_type == DriftType.CANONICAL
        assert "correctly placed" in res.action

    def test_cross_seed_op17_missing_prefix(self):
        qb = ClientTorrentRow(
            client="qb",
            torrent_hash="b" * 40,
            name="SomeRelease",
            save_path=f"{POOL}/darkpeers/SomeRelease",
            content_path=f"{POOL}/darkpeers/SomeRelease",
            category="cross-seed",
            tags="darkpeers,private,~noHL",
        )
        rt = f"{POOL}/darkpeers/SomeRelease"
        res = resolve_canonical_path(qb, rt)
        assert res.canonical.canonical_path == f"{POOL}/cross-seed/darkpeers/SomeRelease"
        assert res.qb_diff.drift_type == DriftType.CATEGORY_DRIFT
        assert res.rt_diff.drift_type == DriftType.CATEGORY_DRIFT
        assert "Rename" in res.action

    def test_arr_staging(self):
        qb = ClientTorrentRow(
            client="qb",
            torrent_hash="c" * 40,
            name="Show.S01",
            save_path=f"{STASH}/_rehome-unique/abc123/Show.S01",
            content_path=f"{STASH}/_rehome-unique/abc123/Show.S01",
            category="tv",
            tags="private",
        )
        rt = f"{STASH}/_rehome-unique/abc123/Show.S01"
        res = resolve_canonical_path(qb, rt)
        assert res.qb_diff.drift_type == DriftType.STAGING_NEEDS_REPAIR
        assert res.rt_diff.drift_type == DriftType.STAGING_NEEDS_REPAIR
        assert "repair tool" in res.action
