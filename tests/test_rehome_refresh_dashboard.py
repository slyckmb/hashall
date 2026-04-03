from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli


def test_refresh_dashboard_shows_done_in_progress_and_warning(tmp_path: Path) -> None:
    log_path = tmp_path / "refresh.log"
    log_path.write_text(
        "\n".join(
            [
                "Rehome Refresh  2026-03-24 06:00",
                "  catalog  /home/michael/.hashall/catalog.db",
                "  workers  8",
                "  scan-hash-mode  fast",
                "  drift-policy  quick",
                "  dedup    execute",
                "",
                "  Scan roots (4):",
                "    [1] stash                active   /stash/media",
                "    [2] pool-media           dest     /pool/media/torrents/seeding",
                "    [3] spare                managed  /mnt/hotspare6tb",
                "    [4] pool-data            managed  /pool/data",
                "",
                "[refresh] doctor preflight",
                "  elapsed 1s  OK",
                "[refresh] scan active_root (/stash/media)",
                "  elapsed 2m  OK",
                "[refresh] scan dest_root (/pool/media/torrents/seeding)",
                "  elapsed 30s  OK",
                "[refresh] dupes auto-upgrade (active=stash)",
                "  elapsed 20m  OK",
                "[refresh] dupes auto-upgrade (dest=pool-media)",
                "  elapsed 10m  OK",
                "[refresh] scan managed root (/mnt/hotspare6tb)",
                "  elapsed 10m  OK",
                "[refresh] dupes auto-upgrade (managed=spare)",
                "  elapsed 5m  OK",
                "[refresh] link plan (spare)",
                "  elapsed 10s  OK",
                "[refresh] link execute plan_id=140 (spare)",
                "  elapsed 45s  OK",
                "[refresh] scan managed root (/pool/data)",
                "  elapsed 10m  OK",
                "[refresh] dupes auto-upgrade (managed=pool-data)",
                "  elapsed 5m  OK",
                "[refresh] link plan (pool-data)",
                "  elapsed 10s  OK",
                "[refresh] link execute plan_id=141 (pool-data)",
                "  elapsed 45s  OK",
                "[refresh] link plan (stash)",
                "  elapsed 10s  OK",
                "[refresh] link execute plan_id=142 (stash)",
                "  elapsed 45s  OK",
                "[refresh] link plan (pool-media)",
                "  elapsed 10s  OK",
                "[refresh] link execute plan_id=143 (pool-media)",
                "❌ Unexpected error: database is locked",
                "  elapsed 45s  OK",
                "[refresh] payload sync --upgrade-missing",
                "  [refresh] still running elapsed=100s watch='tail -n0 -F ~/.logs/hashall/hashall.log'",
                "   upgrade_progress roots_done=100/200 completed=100 failed=0",
                "  [refresh] still running elapsed=130s watch='tail -n0 -F ~/.logs/hashall/hashall.log'",
                "   upgrade_progress roots_done=101/200 completed=101 failed=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["refresh-dashboard", "--log", str(log_path)])

    assert result.exit_code == 0
    assert "TASK" in result.output
    assert "STATUS" in result.output
    assert "START" in result.output
    assert "STOP" in result.output
    assert "DURATION" in result.output
    assert "doctor preflight" in result.output
    assert "done" in result.output
    assert "payload sync --upgrade-missing" in result.output
    assert "in_progress" in result.output
    assert "link plan (pool-media)" in result.output
    assert "link execute (pool-media)" in result.output
    assert "warning" in result.output
    assert "2026-03-24 06:00:00" in result.output
    assert "2m" in result.output or "120s" in result.output
    assert "(" in result.output and ")" in result.output
    assert "timestamps are inferred from run start + phase durations" in result.output
