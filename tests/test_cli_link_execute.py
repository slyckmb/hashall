import sqlite3
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from hashall.cli import cli


@dataclass
class _Plan:
    id: int = 1
    name: str = "test-plan"
    device_alias: str = "pool-media"
    device_id: int = 53
    actions_total: int = 0
    total_bytes_saveable: int = 0
    status: str = "pending"
    mount_point: str | None = None


class _Conn:
    def close(self) -> None:
        return None


def test_link_execute_returns_nonzero_when_execute_plan_raises() -> None:
    runner = CliRunner()
    with (
        patch("hashall.model.connect_db", return_value=_Conn()),
        patch("hashall.link_query.get_plan", return_value=_Plan()),
        patch("hashall.link_executor.execute_plan", side_effect=sqlite3.OperationalError("database is locked")),
    ):
        result = runner.invoke(
            cli,
            ["link", "execute", "1", "--yes", "--no-fix-perms", "--no-snapshot"],
        )

    assert result.exit_code == 1
    assert "Unexpected error: database is locked" in result.output
