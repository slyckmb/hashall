from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli


def test_scan_cli_passes_hash_progress(monkeypatch, tmp_path):
    captured = {}

    def _fake_scan_path(**kwargs):
        captured.update(kwargs)
        class _Stats:
            safety_guard_triggered = False
        return _Stats()

    monkeypatch.setattr("hashall.cli.scan_path", _fake_scan_path)

    root = tmp_path / "root"
    root.mkdir()
    db = tmp_path / "catalog.db"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "scan",
            str(root),
            "--db",
            str(db),
            "--hash-progress",
            "full",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["hash_progress"] == "full"
