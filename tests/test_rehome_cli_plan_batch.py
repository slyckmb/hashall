"""Tests for rehome plan-batch CLI command."""

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli


def _write_hashes(path: Path, hashes):
    path.write_text("\n".join(hashes) + "\n", encoding="utf-8")


def test_plan_batch_writes_manifest_and_plans(monkeypatch, tmp_path: Path):
    calls = []

    class FakePlanner:
        def __init__(self, **_kwargs):
            pass

        def _get_db_connection(self):
            return sqlite3.connect(":memory:")

        def plan_batch_demotion_by_payload_hash(self, payload_hash: str, conn=None):
            assert conn is not None
            calls.append(payload_hash)
            return {
                "version": "1.0",
                "direction": "demote",
                "decision": "MOVE",
                "payload_hash": payload_hash,
                "source_path": f"/stash/media/{payload_hash[:8]}",
                "target_path": f"/pool/data/seeds/{payload_hash[:8]}",
                "affected_torrents": [f"{payload_hash[:8]}-torrent"],
            }

    monkeypatch.setattr("rehome.cli.collect_library_roots", lambda **_kwargs: ([], []))
    monkeypatch.setattr("rehome.cli.DemotionPlanner", FakePlanner)

    catalog = tmp_path / "catalog.db"
    catalog.touch()
    hashes_file = tmp_path / "hashes.txt"
    _write_hashes(hashes_file, ["a" * 64, "b" * 64])

    out_dir = tmp_path / "plans"
    manifest = tmp_path / "manifest.json"
    plannable = tmp_path / "plannable.txt"
    blocked = tmp_path / "blocked.txt"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "plan-batch",
            "--demote",
            "--payload-hashes-file",
            str(hashes_file),
            "--catalog",
            str(catalog),
            "--seeding-root",
            "/stash/media",
            "--seeding-root",
            "/pool/data",
            "--stash-device",
            "49",
            "--pool-device",
            "44",
            "--stash-seeding-root",
            "/stash/media/torrents/seeding",
            "--pool-seeding-root",
            "/pool/data/seeds",
            "--pool-payload-root",
            "/pool/data/seeds",
            "--output-dir",
            str(out_dir),
            "--manifest",
            str(manifest),
            "--plannable-hashes-out",
            str(plannable),
            "--blocked-hashes-out",
            str(blocked),
            "--output-prefix",
            "nohl",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["a" * 64, "b" * 64]

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["summary"]["input_hashes"] == 2
    assert data["summary"]["plannable"] == 2
    assert data["summary"]["blocked"] == 0
    assert data["summary"]["errors"] == 0

    entries = data["entries"]
    assert len(entries) == 2
    for entry in entries:
        plan_path = Path(entry["plan_path"])
        assert plan_path.exists()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert plan["decision"] == "MOVE"

    assert plannable.read_text(encoding="utf-8").strip().splitlines() == ["a" * 64, "b" * 64]
    assert blocked.read_text(encoding="utf-8").strip() == ""


def test_plan_batch_resume_skips_completed_entries(monkeypatch, tmp_path: Path):
    class FirstPlanner:
        def __init__(self, **_kwargs):
            pass

        def _get_db_connection(self):
            return sqlite3.connect(":memory:")

        def plan_batch_demotion_by_payload_hash(self, payload_hash: str, conn=None):
            assert conn is not None
            return {
                "version": "1.0",
                "direction": "demote",
                "decision": "REUSE",
                "payload_hash": payload_hash,
                "source_path": "/stash/media/src",
                "target_path": "/pool/data/seeds/dst",
                "affected_torrents": ["torrent-1"],
            }

    class ResumePlanner:
        def __init__(self, **_kwargs):
            pass

        def _get_db_connection(self):
            return sqlite3.connect(":memory:")

        def plan_batch_demotion_by_payload_hash(self, payload_hash: str, conn=None):
            raise AssertionError(f"planner should not be called during resume for {payload_hash}")

    monkeypatch.setattr("rehome.cli.collect_library_roots", lambda **_kwargs: ([], []))

    catalog = tmp_path / "catalog.db"
    catalog.touch()
    hashes_file = tmp_path / "hashes.txt"
    _write_hashes(hashes_file, ["c" * 64])

    out_dir = tmp_path / "plans"
    manifest = tmp_path / "manifest.json"

    runner = CliRunner()

    monkeypatch.setattr("rehome.cli.DemotionPlanner", FirstPlanner)
    first = runner.invoke(
        cli,
        [
            "plan-batch",
            "--demote",
            "--payload-hashes-file",
            str(hashes_file),
            "--catalog",
            str(catalog),
            "--seeding-root",
            "/stash/media",
            "--seeding-root",
            "/pool/data",
            "--stash-device",
            "49",
            "--pool-device",
            "44",
            "--stash-seeding-root",
            "/stash/media/torrents/seeding",
            "--pool-seeding-root",
            "/pool/data/seeds",
            "--pool-payload-root",
            "/pool/data/seeds",
            "--output-dir",
            str(out_dir),
            "--manifest",
            str(manifest),
            "--output-prefix",
            "nohl",
        ],
    )
    assert first.exit_code == 0, first.output

    monkeypatch.setattr("rehome.cli.DemotionPlanner", ResumePlanner)
    second = runner.invoke(
        cli,
        [
            "plan-batch",
            "--demote",
            "--payload-hashes-file",
            str(hashes_file),
            "--catalog",
            str(catalog),
            "--seeding-root",
            "/stash/media",
            "--seeding-root",
            "/pool/data",
            "--stash-device",
            "49",
            "--pool-device",
            "44",
            "--stash-seeding-root",
            "/stash/media/torrents/seeding",
            "--pool-seeding-root",
            "/pool/data/seeds",
            "--pool-payload-root",
            "/pool/data/seeds",
            "--output-dir",
            str(out_dir),
            "--manifest",
            str(manifest),
            "--resume",
            "--output-prefix",
            "nohl",
        ],
    )

    assert second.exit_code == 0, second.output
    assert "status=resume" in second.output
