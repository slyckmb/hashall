from importlib.machinery import SourceFileLoader
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
