from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    return SourceFileLoader(
        "qb_repair_v2_mod", str(REPO_ROOT / "bin" / "qb-repair-v2.py")
    ).load_module()


def test_detect_path_flags_captures_overlapping_variants() -> None:
    mod = _load_module()
    flags = mod.detect_path_flags(
        "/data/media/downloads/complete/Show",
        "/data/media/torrents/seeding/cross-seed-link/seedpool (API)/Show/file.mkv",
    )
    assert "legacy_downloads_complete" in flags
    assert "cross_seed_link" in flags
    assert "save_content_mismatch" in flags


def test_choose_repair_strategy_prefers_split_for_single_file_mismatch() -> None:
    mod = _load_module()
    manifest = [mod.ManifestEntry(rel_path="Movie.mkv", name="Movie.mkv", size=123)]
    strategy, flags = mod.choose_repair_strategy(
        manifest,
        "/data/media/torrents/seeding/movies",
        "/data/media/torrents/seeding/cross-seed/Aither (API)/Movie.mkv",
        "/data/media/torrents/seeding/cross-seed/Aither (API)",
    )
    assert strategy == "split_unique_hardlink"
    assert "single_file_torrent" in flags
    assert "save_content_mismatch" in flags


def test_detect_target_root_conflicts_reports_extra_files(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "target"
    (root / "payload").mkdir(parents=True)
    (root / "payload" / "wanted.mkv").write_text("a", encoding="utf-8")
    (root / "payload" / "extra.nfo").write_text("b", encoding="utf-8")
    scan = mod.detect_target_root_conflicts(root, ["payload/wanted.mkv"])
    assert scan["extra_files"] == ["payload/extra.nfo"]
    assert scan["missing_files"] == []
    assert scan["overlap_files"] == ["payload/wanted.mkv"]


def test_prepare_from_plan_dryrun_detects_extra_target_files(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    source = tmp_path / "source"
    (source / "payload").mkdir(parents=True)
    (source / "payload" / "wanted.mkv").write_text("good", encoding="utf-8")

    target_save = tmp_path / "repair-save"
    target_root = target_save / "payload"
    target_root.mkdir(parents=True)
    (target_root / "wanted.mkv").write_text("old", encoding="utf-8")
    (target_root / "extra.sfv").write_text("noise", encoding="utf-8")

    plan_path = tmp_path / "plan.json"
    plan = {
        "results": [
            {
                "hash": "a" * 40,
                "status": "planned_exact",
                "mapping": {"payload/wanted.mkv": "payload/wanted.mkv"},
                "target_save": str(target_save),
                "target_root": str(target_root),
                "source_save": str(source),
                "repair_strategy": "split_unique_hardlink",
            }
        ]
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    class DummyQB:
        def get_torrents(self):
            return []

    monkeypatch.setattr(mod, "get_qbittorrent_client", lambda: DummyQB())
    args = SimpleNamespace(
        plan=str(plan_path),
        apply=False,
        allow_modes="planned_exact",
        quarantine_exclusive_root=False,
        report_json=str(tmp_path / "out.json"),
    )
    rc = mod.prepare_from_plan(args)
    assert rc == 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    row = out["results"][0]
    assert row["status"] == "prepare_error"
    assert row["reason"] == "target_root_extra_files:1"


def test_prepare_from_plan_dryrun_records_split_strategy_and_quarantine(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    source = tmp_path / "source"
    (source / "payload").mkdir(parents=True)
    (source / "payload" / "wanted.mkv").write_text("good", encoding="utf-8")

    target_save = tmp_path / "repair-save"
    target_root = target_save / "payload"
    target_root.mkdir(parents=True)
    (target_root / "wanted.mkv").write_text("good", encoding="utf-8")

    plan_path = tmp_path / "plan.json"
    plan = {
        "results": [
            {
                "hash": "b" * 40,
                "status": "planned_exact",
                "mapping": {"payload/wanted.mkv": "payload/wanted.mkv"},
                "target_save": str(target_save),
                "target_root": str(target_root),
                "source_save": str(source),
                "repair_strategy": "split_unique_hardlink",
            }
        ]
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    class DummyQB:
        def get_torrents(self):
            return []

    monkeypatch.setattr(mod, "get_qbittorrent_client", lambda: DummyQB())
    args = SimpleNamespace(
        plan=str(plan_path),
        apply=False,
        allow_modes="planned_exact",
        quarantine_exclusive_root=True,
        report_json=str(tmp_path / "out.json"),
    )
    rc = mod.prepare_from_plan(args)
    assert rc == 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    row = out["results"][0]
    assert row["status"] == "prepared"
    assert row["prepare_strategy"] == "split_unique_hardlink"
    assert row["prepare_quarantine"].startswith("would_rename:")
