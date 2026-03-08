from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(path: Path, name: str):
    return SourceFileLoader(name, str(path)).load_module()


def test_source_preference_rank_prefers_qb_siblings_over_db_global() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-drain.py", "qb_stoppeddl_drain_mod")
    assert mod.source_preference_rank("qb_same_name_exact:stalledup") > mod.source_preference_rank(
        "db_global_payload_root"
    )
    assert mod.source_preference_rank("qb_same_name_size:stalledup") > mod.source_preference_rank(
        "db_global_save_root"
    )


def test_build_plan_skips_single_file_basename_mismatch(tmp_path: Path) -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")

    wrong = tmp_path / "wrong-file.mkv"
    wrong.write_bytes(b"x")

    drain_obj = {
        "entries": [
            {
                "hash": "a" * 40,
                "name": "Expected.Name.2025.1080p.mkv",
                "classification": "b",
                "recommended_path": str(wrong),
                "recommended_source": "db_global_payload_root",
                "best_result": {
                    "path": str(wrong),
                    "verified": True,
                    "verify_ratio": 1.0,
                    "expected_files": 1,
                },
            }
        ]
    }

    rows = mod.build_plan(
        drain_obj=drain_obj,
        allow_classes={"a", "b", "c"},
        allowed_hashes=set(),
        require_verified=True,
        min_ratio=1.0,
        allowed_roots=[str(tmp_path)],
        forbidden_roots=[],
    )
    assert rows.rows == []


def test_build_plan_rejects_forbidden_root(tmp_path: Path) -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")

    bad_dir = tmp_path / "forbidden"
    bad_dir.mkdir(parents=True, exist_ok=True)
    bad = bad_dir / "Expected.Name.2025.1080p.mkv"
    bad.write_bytes(b"x")

    drain_obj = {
        "entries": [
            {
                "hash": "b" * 40,
                "name": "Expected.Name.2025.1080p.mkv",
                "classification": "b",
                "recommended_path": str(bad),
                "recommended_source": "qb_same_name_exact:stalledup",
                "best_result": {
                    "path": str(bad),
                    "verified": True,
                    "verify_ratio": 1.0,
                    "expected_files": 1,
                },
            }
        ]
    }

    rows = mod.build_plan(
        drain_obj=drain_obj,
        allow_classes={"a", "b", "c"},
        allowed_hashes=set(),
        require_verified=True,
        min_ratio=1.0,
        allowed_roots=[str(tmp_path)],
        forbidden_roots=[str(bad_dir)],
    )
    assert rows.rows == []
    assert len(rows.root_policy_rejected) == 1
    assert str(rows.root_policy_rejected[0].get("reason", "")).startswith("forbidden_root:")


def test_wait_recheck_tolerates_transient_missing() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")

    class DummyQB:
        def __init__(self) -> None:
            self.calls = 0
            self.last_error = "Connection reset by peer"

        def get_torrent_info(self, _h: str):
            self.calls += 1
            if self.calls <= 2:
                self.last_error = "Connection reset by peer"
                return None
            self.last_error = ""
            return SimpleNamespace(state="stalledUP", progress=1.0)

        def pause_torrent(self, _h: str) -> bool:
            return True

    item = {"steps": []}
    status, detail = mod.wait_recheck_terminal(
        qb=DummyQB(),
        torrent_hash="c" * 40,
        poll_seconds=0.01,
        timeout_seconds=1.0,
        show_progress=False,
        progress_interval=0.1,
        protect_download=True,
        transient_miss_retries=3,
        item=item,
    )
    assert status == "ok"
    assert detail.startswith("seed_ready:")
    missing_steps = [s for s in item["steps"] if s.get("step") == "poll_missing"]
    assert len(missing_steps) == 2


def test_drain_root_policy_check_blocks_forbidden_path() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-drain.py", "qb_stoppeddl_drain_mod")
    ok, reason = mod.root_policy_check(
        "/data/media/torrents/seeding/foo",
        ["/pool/media", "/pool/data"],
        ["/data/media", "/stash/media"],
    )
    assert ok is False
    assert reason == "forbidden_root:/data/media"


def test_apply_path_equivalent_does_not_alias_pool_data_to_data_media() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")
    assert mod.path_equivalent(
        "/pool/data/seeds/cross-seed/example",
        "/data/media/torrents/seeding/cross-seed/example",
    ) is False


def test_apply_same_filesystem_paths_blocks_cross_storage_root_on_missing_mounts() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")
    ok, reason = mod.same_filesystem_paths(
        "/pool/data/seeds/cross-seed/example",
        "/data/media/torrents/seeding/cross-seed/example",
    )
    assert ok is False
    assert reason.startswith("storage_root_mismatch:") or reason.startswith("device_mismatch:")


def test_drain_alias_variants_do_not_expand_to_pool_data_from_data_media() -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-drain.py", "qb_stoppeddl_drain_mod")
    variants = mod.alias_variants("/data/media/torrents/seeding/cross-seed/example")
    assert "/pool/data/seeds/cross-seed/example" not in variants


def test_drain_seed_root_policy_uses_pool_roots_only(tmp_path: Path) -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-drain.py", "qb_stoppeddl_drain_mod")
    state_path = tmp_path / "seed-root-state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-03-07T12:00:00-05:00",
                "generation": 1,
                "writer": "hashall",
                "active": {"seeding_root": "/pool/media/torrents/seeding", "device_alias": "pool-media"},
                "target": {"seeding_root": "/pool/media/torrents/seeding", "device_alias": "pool-media"},
                "cross_seed": {"link_root": "/pool/media/torrents/seeding/cross-seed", "category": "cross-seed"},
                "migration": {
                    "state": "in_progress",
                    "source_roots": [
                        "/pool/data/media/torrents/seeding",
                        "/data/media/torrents/seeding",
                    ],
                    "target_root": "/pool/media/torrents/seeding",
                },
                "aliases": [],
                "mirror_roots": [
                    "/pool/media/torrents/seeding",
                    "/pool/data/media/torrents/seeding",
                    "/data/media/torrents/seeding",
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = mod.load_seed_root_policy(state_path)
    assert policy["allowed_save_roots"] == [
        "/pool/media/torrents/seeding",
        "/pool/data/media/torrents/seeding",
    ]
    assert policy["allowed_donor_roots"] == [
        "/pool/media/torrents/seeding",
        "/pool/data/media/torrents/seeding",
    ]


def test_apply_seed_root_policy_uses_pool_roots_only(tmp_path: Path) -> None:
    mod = _load_module(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py", "qb_stoppeddl_apply_mod")
    state_path = tmp_path / "seed-root-state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-03-07T12:00:00-05:00",
                "generation": 1,
                "writer": "hashall",
                "active": {"seeding_root": "/pool/media/torrents/seeding", "device_alias": "pool-media"},
                "target": {"seeding_root": "/pool/media/torrents/seeding", "device_alias": "pool-media"},
                "cross_seed": {"link_root": "/pool/media/torrents/seeding/cross-seed", "category": "cross-seed"},
                "migration": {
                    "state": "in_progress",
                    "source_roots": [
                        "/pool/data/media/torrents/seeding",
                        "/stash/media/torrents/seeding",
                    ],
                    "target_root": "/pool/media/torrents/seeding",
                },
                "aliases": [],
                "mirror_roots": [
                    "/pool/media/torrents/seeding",
                    "/pool/data/media/torrents/seeding",
                    "/stash/media/torrents/seeding",
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = mod.load_seed_root_policy(state_path)
    assert policy["allowed_save_roots"] == [
        "/pool/media/torrents/seeding",
        "/pool/data/media/torrents/seeding",
    ]
