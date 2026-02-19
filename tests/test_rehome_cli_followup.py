"""Tests for rehome followup CLI command."""

from pathlib import Path

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli


def test_followup_cli_prints_summary(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    db_path.touch()

    monkeypatch.setattr(
        "rehome.cli.run_followup",
        lambda **_kwargs: {
            "summary": {
                "groups_total": 1,
                "groups_ok": 1,
                "groups_pending": 0,
                "groups_failed": 0,
                "cleanup_attempted": 0,
                "cleanup_done": 0,
                "cleanup_failed": 0,
            },
            "entries": [
                {
                    "payload_hash": "abc123",
                    "outcome": "ok",
                    "cleanup_required": False,
                    "cleanup_result": "skipped",
                    "db_reasons": [],
                    "source_reasons": [],
                    "qb_checks": [],
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["followup", "--catalog", str(db_path)])

    assert result.exit_code == 0
    assert "groups: 1" in result.output
    assert "pending: 0" in result.output
    assert "failed: 0" in result.output


def test_followup_cli_strict_fails_with_pending(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    db_path.touch()

    monkeypatch.setattr(
        "rehome.cli.run_followup",
        lambda **_kwargs: {
            "summary": {
                "groups_total": 1,
                "groups_ok": 0,
                "groups_pending": 1,
                "groups_failed": 0,
                "cleanup_attempted": 0,
                "cleanup_done": 0,
                "cleanup_failed": 0,
            },
            "entries": [],
        },
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["followup", "--catalog", str(db_path), "--strict"])

    assert result.exit_code == 1
