import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "codex-says-run-this-next.sh"


def _run_wrapper(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["REHOME_PROCESS_MODE"] = "nohl-restart"
    env["REHOME_NOHL_EXECUTE"] = "0"
    env["REHOME_NOHL_FAST"] = "1"
    env["REHOME_NOHL_DEBUG"] = "0"
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
