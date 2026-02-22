import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-99_qb-checking-watch.sh"


def test_rehome_99_help_lists_watchdog_flags() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--enforce-paused-dl" in result.stdout
    assert "--allow-file" in result.stdout
    assert "--events-jsonl" in result.stdout
    assert "--max-iterations" in result.stdout


def test_rehome_99_rejects_non_numeric_max_iterations() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--max-iterations", "abc"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 2
    assert "--max-iterations must be a non-negative integer" in output
