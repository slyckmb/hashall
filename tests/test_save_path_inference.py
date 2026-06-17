"""Tests for save_path_inference module."""

import pytest

from hashall.save_path_inference import (
    APPROVED_SAVE_ROOTS,
    check_path_alignment,
    detect_drift,
    infer_canonical_save_path,
)

STASH = APPROVED_SAVE_ROOTS[0]  # /data/media/torrents/seeding
POOL = APPROVED_SAVE_ROOTS[1]  # /pool/media/torrents/seeding


# ---- check_path_alignment ----


@pytest.mark.parametrize(
    "current,canonical,expected",
    [
        # Exact match
        (f"{STASH}/tv", f"{STASH}/tv", True),
        # Child path (single-file torrent: save_path/filename)
        (f"{STASH}/tv/Show.mkv", f"{STASH}/tv", True),
        # Nested child (multi-level, e.g. rt directory is deeper)
        (f"{STASH}/tv/Show/ep01.mkv", f"{STASH}/tv", True),
        # New-canonical cross-seed item is a child of its tracker dir
        (f"{STASH}/FileList.io/some.show", f"{STASH}/FileList.io", True),
        # Wrong sibling directory
        (f"{STASH}/movies", f"{STASH}/tv", False),
        # Empty current → False
        ("", f"{STASH}/tv", False),
        # Empty canonical → False
        (f"{STASH}/tv", "", False),
    ],
)
def test_check_path_alignment(current, canonical, expected):
    assert check_path_alignment(current, canonical) == expected


# ---- infer_canonical_save_path ----


@pytest.mark.parametrize(
    "category,tags,save_path,expected_canonical,expected_device,reliability",
    [
        # cross-seed: current save_path is bare tracker (damaged, OP-17)
        # canonical is cross-seed/<tracker>/ per CANONICAL-PATH-SPEC.md §3a
        (
            "cross-seed",
            "cross-seed, private, Aither (API)",
            f"{STASH}/Aither (API)",
            f"{STASH}/cross-seed/Aither (API)",
            "stash",
            "reliable",
        ),
        # cross-seed + ~noHL → pool device, canonical with cross-seed/ prefix
        (
            "cross-seed",
            "cross-seed, ~noHL, fearnopeer",
            f"{POOL}/fearnopeer",
            f"{POOL}/cross-seed/fearnopeer",
            "pool",
            "reliable",
        ),
        # cross-seed: legacy path (/seeding/cross-seed/<tracker>) → canonical preserves cross-seed/ prefix
        (
            "cross-seed",
            "cross-seed, private",
            f"{STASH}/cross-seed/FileList.io",
            f"{STASH}/cross-seed/FileList.io",
            "stash",
            "reliable",
        ),
        # Normal category
        (
            "tv",
            "private",
            f"{STASH}/tv",
            f"{STASH}/tv",
            "stash",
            "reliable",
        ),
        # ARR pre-import → transient
        (
            "sonarr",
            "private",
            f"{STASH}/sonarr",
            f"{STASH}/sonarr",
            "stash",
            "transient",
        ),
        # Uncategorized → root, ambiguous
        (
            "Uncategorized",
            "private",
            STASH,
            STASH,
            "stash",
            "ambiguous",
        ),
    ],
)
def test_infer_canonical_save_path(
    category, tags, save_path, expected_canonical, expected_device, reliability
):
    result = infer_canonical_save_path(
        category=category,
        tags=tags,
        current_save_path=save_path,
    )
    assert result.canonical_save_path == expected_canonical, (
        f"canonical mismatch: got {result.canonical_save_path!r}"
    )
    assert result.device == expected_device
    assert result.reliability == reliability


# ---- detect_drift ----


@pytest.mark.parametrize(
    "scenario,category,tags,qb_path,rt_dir,expected_drifted,expected_reason_contains",
    [
        # qB correct, RT correct — no drift
        (
            "clean",
            "tv", "private",
            f"{STASH}/tv", f"{STASH}/tv",
            False, None,
        ),
        # qB correct, RT not in cache (empty string) — not drift, note only
        (
            "rt_missing",
            "tv", "private",
            f"{STASH}/tv", "",
            False, None,
        ),
        # qB correct, RT path wrong — rt_path_mismatch
        (
            "rt_wrong",
            "tv", "private",
            f"{STASH}/tv", f"{STASH}/movies",
            True, "rt_path_mismatch",
        ),
        # qB legacy cross-seed-link path
        (
            "legacy",
            "tv", "private",
            f"{STASH}/cross-seed-link/FileList.io", "",
            True, "legacy_path",
        ),
        # qB on pool but device=stash (no ~noHL tag)
        (
            "wrong_device_stash",
            "tv", "private",
            f"{POOL}/tv", f"{POOL}/tv",
            True, "wrong_device_should_be_stash",
        ),
        # qB on stash but device=pool (~noHL tag present)
        (
            "wrong_device_pool",
            "tv", "private, ~noHL",
            f"{STASH}/tv", "",
            True, "wrong_device_should_be_pool",
        ),
        # qB correct, RT is a child path (single-file torrent) — not drift
        (
            "rt_child_path",
            "tv", "private",
            f"{STASH}/tv", f"{STASH}/tv/Show.S01E01.mkv",
            False, None,
        ),
        # sonarr (ARR transient) — skipped entirely, not drifted
        (
            "transient",
            "sonarr", "private",
            f"{STASH}/sonarr", f"{STASH}/sonarr",
            False, "transient_category_skipped",
        ),
    ],
)
def test_detect_drift(
    scenario, category, tags, qb_path, rt_dir,
    expected_drifted, expected_reason_contains
):
    report = detect_drift(
        torrent_hash="a" * 40,
        category=category,
        tags=tags,
        current_save_path=qb_path,
        current_rt_directory=rt_dir,
    )
    assert report.is_drifted == expected_drifted, (
        f"[{scenario}] expected is_drifted={expected_drifted}, "
        f"got {report.is_drifted} (reason={report.drift_reason!r}, notes={report.notes!r})"
    )
    if expected_reason_contains:
        assert expected_reason_contains in (report.drift_reason or ""), (
            f"[{scenario}] expected {expected_reason_contains!r} "
            f"in drift_reason={report.drift_reason!r}"
        )


# ---- pool device inference from path hint (no ~noHL tag) ----


def test_pool_device_inferred_from_catalog_save_path():
    """No ~noHL tag but catalog save_path on pool → device should be pool."""
    result = infer_canonical_save_path(
        category="cross-seed",
        tags="private,cross-seed,Aither",
        current_save_path=f"{POOL}/cross-seed/Aither (API)",
    )
    assert result.device == "pool", f"expected pool, got {result.device}"
    assert result.canonical_save_path.startswith(POOL), result.canonical_save_path
    assert any("device=pool" in n for n in result.notes), f"expected path-hint note, got {result.notes}"


def test_pool_device_tag_wins_over_path_hint():
    """~noHL tag takes priority even if current_save_path is on stash."""
    result = infer_canonical_save_path(
        category="tv",
        tags="private,~noHL",
        current_save_path=f"{STASH}/tv",  # stash path, but tag says pool
    )
    assert result.device == "pool"
    assert not any("device=pool inferred from path" in n for n in result.notes)


def test_stash_stays_stash_when_save_path_is_stash():
    """No ~noHL, save_path on stash → remains stash."""
    result = infer_canonical_save_path(
        category="tv",
        tags="private",
        current_save_path=f"{STASH}/tv",
    )
    assert result.device == "stash"
    assert not any("device=pool" in n for n in result.notes)


def test_staging_path_does_not_override_device():
    """A pool-rooted staging dir must NOT trigger pool device hint."""
    result = infer_canonical_save_path(
        category="cross-seed",
        tags="private,cross-seed,Aither",
        current_save_path=f"{POOL}/_rehome-unique/abcd1234abcd1234",
    )
    # staging path → no pool hint → defaults to stash
    assert result.device == "stash", (
        f"staging pool path must not override device; got {result.device}, notes={result.notes}"
    )
    assert not any("device=pool inferred from path" in n for n in result.notes)


def test_rt_directory_pool_hint_used_when_save_path_absent():
    """current_rt_directory on pool used as device hint when save_path is empty."""
    result = infer_canonical_save_path(
        category="cross-seed",
        tags="private,cross-seed",
        current_save_path="",
        current_rt_directory=f"{POOL}/Aither",
    )
    assert result.device == "pool"
    assert any("device=pool" in n for n in result.notes)
