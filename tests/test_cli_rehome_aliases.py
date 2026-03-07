from click.testing import CliRunner

from hashall.cli import cli


def test_hashall_top_level_exposes_refresh_and_rehome():
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "refresh" in result.output
    assert "rehome" in result.output


def test_hashall_refresh_help_works():
    runner = CliRunner()

    result = runner.invoke(cli, ["refresh", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "--verbose" in result.output


def test_hashall_rehome_help_works():
    runner = CliRunner()

    result = runner.invoke(cli, ["rehome", "--help"])

    assert result.exit_code == 0
    assert "hashall refresh" in result.output
    assert "hashall rehome auto --limit 5" in result.output
