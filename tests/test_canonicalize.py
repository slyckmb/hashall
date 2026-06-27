"""
Tests for hashall.canonicalize: placement + path drift detection.

Covers all 6 drift gate scenarios:
  1. ok          — no placement drift, no path structure drift
  2. fix_path_only     — correct device, wrong subdir
  3. fix_placement_only — wrong device, correct subdir
  4. fix_both          — wrong device AND wrong subdir
  5. staging_dir       — transient, no drift flagged
  6. blocked           — external consumer prevents repair
"""

from unittest.mock import patch

import pytest
import sqlite3

from hashall.canonicalize import (
    CanonicalizeRequest,
    CanonicalizeConfig,
    canonicalize_torrent,
    generate_repair_plan,
)
from hashall.client_drift import ClientDriftPolicy
from hashall.payload import Payload, TorrentInstance
from hashall.save_path_inference import InferredSavePath
from rehome.planner import ExternalConsumer as RehomeExternalConsumer


DEFAULT_POOL_ROOTS = ("/pool/media/torrents/seeding",)
DEFAULT_STASH_ROOTS = ("/data/media/torrents/seeding", "/stash/media/torrents/seeding")


@pytest.fixture
def policy():
    return ClientDriftPolicy(
        pool_roots=DEFAULT_POOL_ROOTS,
        stash_roots=DEFAULT_STASH_ROOTS,
    )


@pytest.fixture
def db_session():
    return sqlite3.connect(":memory:")


def make_planner_mock():
    planner = type("FakePlanner", (), {})()
    planner.stash_device = 50
    planner.pool_device = 49
    planner._refresh_identity_cache = lambda _conn: None
    planner._detect_external_consumers = lambda _conn, _root: []
    planner._payload_exists_on_pool = lambda _conn, _hash: None
    return planner


def make_config(planner, policy, **kw):
    return CanonicalizeConfig(planner=planner, policy=policy, **kw)


@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_1_ok(
    mock_infer, mock_get_payload, mock_get_torrent, db_session, policy,
):
    planner = make_planner_mock()
    config = make_config(planner, policy)

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h01", payload_id=1, device_id=49,
        save_path="/pool/media/torrents/seeding",
        root_name="Item", category="cross-seed", tags="Provider",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=1, payload_hash="abc", device_id=49,
        root_path="/pool/media/torrents/seeding/cross-seed/Provider/Item",
        file_count=1, total_bytes=1024, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/pool/media/torrents/seeding/cross-seed/Provider",
        device="pool", category="cross-seed", subdir="cross-seed/Provider",
        reliability="reliable", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h01", category="cross-seed", tags="Provider",
        save_path="/pool/media/torrents/seeding/cross-seed/Provider",
        content_path="/pool/media/torrents/seeding/cross-seed/Provider/Item",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.placement_drift is False
    assert verdict.path_structure_drift is False
    assert verdict.reliability == "reliable"
    assert plan.plan_type == "ok"


@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_2_fix_path_only(
    mock_infer, mock_get_payload, mock_get_torrent, db_session, policy,
):
    planner = make_planner_mock()
    config = make_config(planner, policy)

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h02", payload_id=2, device_id=49,
        save_path="/pool/media/torrents/seeding",
        root_name="Item", category="cross-seed", tags="Provider",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=2, payload_hash="def", device_id=49,
        root_path="/pool/media/torrents/seeding/Provider/Item",
        file_count=1, total_bytes=2048, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/pool/media/torrents/seeding/cross-seed/Provider",
        device="pool", category="cross-seed", subdir="cross-seed/Provider",
        reliability="reliable", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h02", category="cross-seed", tags="Provider",
        save_path="/pool/media/torrents/seeding/Provider",
        content_path="/pool/media/torrents/seeding/Provider/Item",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.placement_drift is False
    assert verdict.path_structure_drift is True
    assert plan.plan_type == "fix_path_only"
    assert plan.move_required is False


@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_3_fix_placement_only(
    mock_infer, mock_get_payload, mock_get_torrent, db_session, policy,
):
    planner = make_planner_mock()
    config = make_config(planner, policy)

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h03", payload_id=3, device_id=50,
        save_path="/stash/media/torrents/seeding",
        root_name="Item", category="cross-seed", tags="Provider",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=3, payload_hash="ghi", device_id=50,
        root_path="/stash/media/torrents/seeding/cross-seed/Provider/Item",
        file_count=1, total_bytes=3072, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/pool/media/torrents/seeding/cross-seed/Provider",
        device="pool", category="cross-seed", subdir="cross-seed/Provider",
        reliability="reliable", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h03", category="cross-seed", tags="Provider",
        save_path="/stash/media/torrents/seeding/cross-seed/Provider",
        content_path="/stash/media/torrents/seeding/cross-seed/Provider/Item",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.placement_drift is True
    assert verdict.path_structure_drift is False
    assert plan.plan_type == "fix_placement_only"


@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_4_fix_both(
    mock_infer, mock_get_payload, mock_get_torrent, db_session, policy,
):
    planner = make_planner_mock()
    config = make_config(planner, policy)

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h04", payload_id=4, device_id=50,
        save_path="/stash/media/torrents/seeding",
        root_name="Item", category="cross-seed", tags="Provider",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=4, payload_hash="jkl", device_id=50,
        root_path="/stash/media/torrents/seeding/Provider/Item",
        file_count=1, total_bytes=4096, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/pool/media/torrents/seeding/cross-seed/Provider",
        device="pool", category="cross-seed", subdir="cross-seed/Provider",
        reliability="reliable", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h04", category="cross-seed", tags="Provider",
        save_path="/stash/media/torrents/seeding/Provider",
        content_path="/stash/media/torrents/seeding/Provider/Item",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.placement_drift is True
    assert verdict.path_structure_drift is True
    assert plan.plan_type == "fix_both"
    assert plan.move_required is True


@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_5_staging_dir_exclusion(
    mock_infer, mock_get_payload, mock_get_torrent, db_session, policy,
):
    planner = make_planner_mock()
    config = make_config(planner, policy)

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h05", payload_id=5, device_id=49,
        save_path="/pool/media/torrents/seeding",
        root_name="ABCD1234", category="cross-seed", tags="",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=5, payload_hash="mno", device_id=49,
        root_path="/pool/media/torrents/seeding/_rehome-unique/ABCD1234",
        file_count=1, total_bytes=512, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/pool/media/torrents/seeding/_rehome-unique",
        device="pool", category="cross-seed", subdir="_rehome-unique",
        reliability="transient", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h05", category="cross-seed", tags="",
        save_path="/pool/media/torrents/seeding/_rehome-unique/ABCD1234",
        content_path="/pool/media/torrents/seeding/_rehome-unique/ABCD1234",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.reliability == "transient"
    assert verdict.placement_drift is False
    assert verdict.path_structure_drift is False
    assert plan.plan_type == "ok"


@patch("hashall.canonicalize.get_payloads_by_hash")
@patch("hashall.canonicalize.get_torrent_instance")
@patch("hashall.canonicalize.get_payload_by_id")
@patch("hashall.canonicalize.infer_canonical_save_path")
def test_scenario_6_blocked(
    mock_infer, mock_get_payload, mock_get_torrent, mock_get_payloads_by_hash, db_session, policy,
):
    planner = make_planner_mock()
    planner._detect_external_consumers = lambda _conn, _root: [
        RehomeExternalConsumer(
            file_path="/data/media/tv/Show/Season 1/Show - S01E01.mkv",
            external_link_paths=[
                "/data/media/tv/Show/Season 1/Show - S01E01.mkv",
            ],
        ),
    ]
    config = make_config(planner, policy)

    mock_get_payloads_by_hash.return_value = []

    mock_get_torrent.return_value = TorrentInstance(
        torrent_hash="h06", payload_id=6, device_id=49,
        save_path="/pool/media/torrents/seeding",
        root_name="Show - S01E01", category="tv", tags="",
        last_seen_at=1000.0,
    )
    mock_get_payload.return_value = Payload(
        payload_id=6, payload_hash="pqr", device_id=49,
        root_path="/pool/media/torrents/seeding/Provider/Show - S01E01",
        file_count=1, total_bytes=8192, status="complete", last_built_at=1000.0,
    )
    mock_infer.return_value = InferredSavePath(
        canonical_save_path="/data/media/torrents/seeding/tv",
        device="stash", category="tv", subdir="tv",
        reliability="reliable", notes=[],
    )

    request = CanonicalizeRequest(
        torrent_hash="h06", category="tv", tags="",
        save_path="/pool/media/torrents/seeding/Provider",
        content_path="/pool/media/torrents/seeding/Provider/Show - S01E01",
        rt_directory="", state="uploading",
    )

    verdict = canonicalize_torrent(request, db_session, config)
    plan = generate_repair_plan(verdict)

    assert verdict.blocked is True
    assert plan.plan_type == "blocked"
