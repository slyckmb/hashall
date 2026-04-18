from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.orphan_sweep import DatasetConfig, run_orphan_sweep


def test_run_orphan_sweep_orders_small_first_and_applies_limit(tmp_path: Path, monkeypatch) -> None:
    seeding_root = tmp_path / "pool-data" / "media" / "torrents" / "seeding"
    small = seeding_root / "tracker-a" / "small.bin"
    large = seeding_root / "tracker-a" / "large.bin"
    small.parent.mkdir(parents=True, exist_ok=True)
    small.write_bytes(b"a" * 3)
    large.write_bytes(b"b" * 9)

    dataset = DatasetConfig(
        name="pool-data",
        seeding_roots=[seeding_root],
        dest=tmp_path / "pool-media" / "torrents" / "orphaned_data",
        cross_dataset=True,
    )

    monkeypatch.setattr("hashall.orphan_sweep.build_live_content_paths", lambda **_: (set(), {"rt_rows": 0, "qb_rows": 0, "warnings": []}))
    monkeypatch.setattr("hashall.orphan_sweep._free_bytes", lambda _: 10_000)

    summary = run_orphan_sweep(
        dry_run=True,
        limit=1,
        datasets=[dataset],
        order="small-first",
        dataset_names={"pool-data"},
    )

    assert summary["moved"] == 1
    assert summary["skipped"] == 0
    assert len(summary["items"]) == 1
    assert summary["items"][0].path == small
    assert summary["items"][0].action == "dryrun_move"
    assert summary["bytes_planned"] == 3
    assert summary["bytes_moved"] == 3


def test_run_orphan_sweep_skips_cross_dataset_move_when_space_budget_is_too_small(
    tmp_path: Path, monkeypatch
) -> None:
    seeding_root = tmp_path / "pool-data" / "media" / "torrents" / "seeding"
    orphan = seeding_root / "tracker-b" / "episode.mkv"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x" * 12)

    dataset = DatasetConfig(
        name="pool-data",
        seeding_roots=[seeding_root],
        dest=tmp_path / "pool-media" / "torrents" / "orphaned_data",
        cross_dataset=True,
    )

    monkeypatch.setattr("hashall.orphan_sweep.build_live_content_paths", lambda **_: (set(), {"rt_rows": 0, "qb_rows": 0, "warnings": []}))
    monkeypatch.setattr("hashall.orphan_sweep._free_bytes", lambda _: 8)

    summary = run_orphan_sweep(
        dry_run=True,
        datasets=[dataset],
        reserve_gib=0,
    )

    assert summary["moved"] == 0
    assert summary["skipped"] == 1
    assert summary["skipped_space"] == 1
    assert len(summary["items"]) == 1
    assert summary["items"][0].action == "skipped"
    assert "insufficient destination space" in summary["items"][0].skip_reason


def test_payload_orphan_sweep_cli_accepts_new_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_orphan_sweep(**kwargs):
        captured.update(kwargs)
        return {
            "dry_run": True,
            "cache_diag": {"rt_rows": 0, "qb_rows": 0, "warnings": [], "rt_freshness": "fresh", "rt_age_s": 0, "qb_age_s": 0},
            "items": [],
            "moved": 0,
            "skipped": 0,
            "skipped_space": 0,
            "warned_nlinks": 0,
            "bad_deleted": 0,
            "bytes_planned": 0,
            "bytes_moved": 0,
        }

    monkeypatch.setattr("hashall.orphan_sweep.run_orphan_sweep", fake_run_orphan_sweep)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "payload",
            "orphan-sweep",
            "--limit",
            "5",
            "--order",
            "small-first",
            "--reserve-gib",
            "25",
            "--dataset",
            "pool-data",
            "--dataset",
            "stash",
        ],
    )

    assert result.exit_code == 0
    assert captured["limit"] == 5
    assert captured["order"] == "small-first"
    assert captured["reserve_gib"] == 25
    assert captured["dataset_names"] == {"pool-data", "stash"}
    assert "skipped (space):      0" in result.output
