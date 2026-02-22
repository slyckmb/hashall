import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-89_nohl-basics-qb-automation-audit.sh"


def test_rehome_89_help_lists_mode_and_qbit_manage_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--mode MODE" in result.stdout
    assert "--qbit-manage-config" in result.stdout
    assert "--qbit-manage-container" in result.stdout
