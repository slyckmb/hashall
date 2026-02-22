import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-101_nohl-basics-qb-candidate-mapping.sh"


def _write_baseline(path: Path) -> None:
    obj = {
        "summary": {"queue_total": 2},
        "entries": [
            {
                "hash": "a" * 40,
                "state": "stoppedDL",
                "progress": 0.0,
                "amount_left": 100,
                "save_path": "/tmp/not-real-a",
                "content_path": "/tmp/not-real-a/file.mkv",
            },
            {
                "hash": "b" * 40,
                "state": "stoppedDL",
                "progress": 0.1,
                "amount_left": 200,
                "save_path": "/tmp/not-real-b",
                "content_path": "/incomplete_torrents/not-real-b/file.mkv",
            },
        ],
    }
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def test_rehome_101_help_lists_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--baseline-json" in result.stdout
    assert "--db PATH" in result.stdout
    assert "--output-prefix" in result.stdout


def test_rehome_101_runs_with_custom_baseline_and_missing_db(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--baseline-json",
            str(baseline),
            "--db",
            str(tmp_path / "missing.db"),
            "--output-prefix",
            "t101",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "summary mapped=2" in result.stdout
    assert "manual_only=" in result.stdout

