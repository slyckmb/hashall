import os
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.orphan_sweep import DatasetConfig, run_orphan_sweep, validate_orphan_hardlinks


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


def test_run_orphan_sweep_surfaces_empty_cross_seed_tracker_dirs(
    tmp_path: Path, monkeypatch
) -> None:
    seeding_root = tmp_path / "pool-data" / "media" / "torrents" / "seeding"
    (seeding_root / "cross-seed" / "Tracker.One").mkdir(parents=True, exist_ok=True)

    dataset = DatasetConfig(
        name="pool-data",
        seeding_roots=[seeding_root],
        dest=tmp_path / "pool-media" / "torrents" / "orphaned_data",
        cross_dataset=True,
    )

    monkeypatch.setattr("hashall.orphan_sweep.build_live_content_paths", lambda **_: (set(), {"rt_rows": 0, "qb_rows": 0, "warnings": []}))

    summary = run_orphan_sweep(
        dry_run=True,
        datasets=[dataset],
        dataset_names={"pool-data"},
    )

    assert len(summary["items"]) == 1
    assert summary["items"][0].path == seeding_root / "cross-seed" / "Tracker.One"
    assert summary["items"][0].skip_reason == "empty_dir"
    assert summary["items"][0].action == "dryrun_delete"


def test_run_orphan_sweep_limit_applies_to_empty_dir_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    seeding_root = tmp_path / "pool-data" / "media" / "torrents" / "seeding"
    (seeding_root / "cross-seed" / "Tracker.One").mkdir(parents=True, exist_ok=True)
    (seeding_root / "cross-seed" / "Tracker.Two").mkdir(parents=True, exist_ok=True)

    dataset = DatasetConfig(
        name="pool-data",
        seeding_roots=[seeding_root],
        dest=tmp_path / "pool-media" / "torrents" / "orphaned_data",
        cross_dataset=True,
    )

    monkeypatch.setattr("hashall.orphan_sweep.build_live_content_paths", lambda **_: (set(), {"rt_rows": 0, "qb_rows": 0, "warnings": []}))

    summary = run_orphan_sweep(
        dry_run=True,
        limit=1,
        datasets=[dataset],
        dataset_names={"pool-data"},
    )

    assert len(summary["items"]) == 1
    assert summary["items"][0].action == "dryrun_delete"


def _make_memory_db(files_rows: list[tuple[str, int, int]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE files (path TEXT, device_id INTEGER, inode INTEGER)"
    )
    for row in files_rows:
        conn.execute(
            "INSERT INTO files (path, device_id, inode) VALUES (?, ?, ?)", row
        )
    conn.commit()
    return conn


def test_validate_orphan_hardlinks_nlink1_safe(tmp_path: Path) -> None:
    orphan_dir = tmp_path / "orphans"
    orphan_dir.mkdir()
    file1 = orphan_dir / "file1.bin"
    file1.write_bytes(b"unique content")

    st = os.stat(file1)
    assert st.st_nlink == 1

    conn = _make_memory_db([])
    safe, skipped = validate_orphan_hardlinks(str(orphan_dir), conn)
    conn.close()

    assert len(safe) == 1
    assert len(skipped) == 0
    assert safe[0]["path"] == str(file1)
    assert safe[0]["device_id"] == st.st_dev
    assert safe[0]["inode"] == st.st_ino


def test_validate_orphan_hardlinks_nlink2_external_skipped(tmp_path: Path) -> None:
    orphan_dir = tmp_path / "orphans"
    orphan_dir.mkdir()
    seeding_dir = tmp_path / "seeding"
    seeding_dir.mkdir()

    orphan_file = orphan_dir / "orphan.bin"
    orphan_file.write_bytes(b"shared content")

    seeding_file = seeding_dir / "seeding.bin"
    os.link(orphan_file, seeding_file)

    st = os.stat(orphan_file)
    assert st.st_nlink == 2

    conn = _make_memory_db([
        (str(seeding_file), st.st_dev, st.st_ino),
    ])
    safe, skipped = validate_orphan_hardlinks(str(orphan_dir), conn)
    conn.close()

    assert len(safe) == 0
    assert len(skipped) == 1
    assert skipped[0]["path"] == str(orphan_file)
    assert skipped[0]["device_id"] == st.st_dev
    assert skipped[0]["inode"] == st.st_ino
    assert any("seeding" in p for p in skipped[0]["seeding_paths"])


def test_validate_orphan_hardlinks_nlink3_all_within_safe(tmp_path: Path) -> None:
    orphan_dir = tmp_path / "orphans"
    (orphan_dir / "sub").mkdir(parents=True)

    f1 = orphan_dir / "a.bin"
    f2 = orphan_dir / "b.bin"
    f3 = orphan_dir / "sub" / "c.bin"
    f1.write_bytes(b"shared in orphan")

    os.link(f1, f2)
    os.link(f1, f3)

    st = os.stat(f1)
    assert st.st_nlink == 3

    conn = _make_memory_db([])
    safe, skipped = validate_orphan_hardlinks(str(orphan_dir), conn)
    conn.close()

    assert len(safe) == 3
    assert len(skipped) == 0
    safe_paths = {s["path"] for s in safe}
    assert str(f1) in safe_paths
    assert str(f2) in safe_paths
    assert str(f3) in safe_paths


def test_validate_orphan_hardlinks_empty_dir(tmp_path: Path) -> None:
    orphan_dir = tmp_path / "empty_orphans"
    orphan_dir.mkdir()

    conn = _make_memory_db([])
    safe, skipped = validate_orphan_hardlinks(str(orphan_dir), conn)
    conn.close()

    assert len(safe) == 0
    assert len(skipped) == 0
