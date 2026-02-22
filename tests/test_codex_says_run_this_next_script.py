import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "codex-says-run-this-next.sh"


def _run_wrapper(args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["REHOME_PROCESS_MODE"] = "nohl-restart"
    env["REHOME_NOHL_EXECUTE"] = "0"
    env["REHOME_NOHL_FAST"] = "1"
    env["REHOME_NOHL_DEBUG"] = "0"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_min_free_pct_overrides_nohl_default() -> None:
    result = _run_wrapper(["--min-free-pct", "17"])
    assert result.returncode == 0, result.stderr
    assert "mode=nohl-restart min_free_pct=17" in result.stdout
    assert "--min-free-pct 17" in result.stdout


def test_cli_min_free_pct_rejects_non_numeric_values() -> None:
    result = _run_wrapper(["--min-free-pct", "abc"])
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 2
    assert "Invalid --min-free-pct value: abc" in output


def test_nohl_restart_includes_qb_automation_audit_and_watchdog_steps() -> None:
    result = _run_wrapper(["--min-free-pct", "15"])
    assert result.returncode == 0, result.stderr
    assert "bin/rehome-89_nohl-basics-qb-automation-audit.sh" in result.stdout
    assert "bin/rehome-99_qb-checking-watch.sh --interval" in result.stdout


def test_nohl_restart_watchdog_allow_file_is_rendered_when_set() -> None:
    result = _run_wrapper(
        ["--min-free-pct", "15"],
        extra_env={"REHOME_NOHL_WATCHDOG_ALLOW_FILE": "/tmp/watch-allow.txt"},
    )
    assert result.returncode == 0, result.stderr
    assert "--allow-file /tmp/watch-allow.txt" in result.stdout
