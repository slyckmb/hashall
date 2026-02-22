import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-100_nohl-basics-qb-repair-baseline.sh"


def test_rehome_100_help_lists_required_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--output-prefix" in result.stdout
    assert "--limit N" in result.stdout
    assert "--include-state" in result.stdout
