import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-103_nohl-basics-qb-payload-ownership-audit.sh"


def test_rehome_103_help_lists_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--mapping-json" in result.stdout
    assert "--baseline-json" in result.stdout
    assert "--db PATH" in result.stdout


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_103_detects_shared_target_payload_conflict(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    target_root = tmp_path / "pool" / "cross-seed" / "OnlyEncodes (API)"
    target_root.mkdir(parents=True, exist_ok=True)
    target_payload = target_root / "Episode.mkv"
    target_payload.write_text("x", encoding="utf-8")

    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [
                    {
                        "hash": "a" * 40,
                        "confidence": "confident",
                        "name": "Episode A",
                        "state": "stoppedDL",
                        "save_path": str(tmp_path / "old" / "A"),
                        "current_payload_root": str(tmp_path / "old" / "A" / "Episode.mkv"),
                        "best_candidate": str(target_root),
                        "best_payload_root": str(target_payload),
                        "category": "cross-seed",
                        "tracker_key": "onlyencodes",
                    },
                    {
                        "hash": "b" * 40,
                        "confidence": "confident",
                        "name": "Episode B",
                        "state": "stoppedDL",
                        "save_path": str(tmp_path / "old" / "B"),
                        "current_payload_root": str(tmp_path / "old" / "B" / "Episode.mkv"),
                        "best_candidate": str(target_root),
                        "best_payload_root": str(target_payload),
                        "category": "cross-seed",
                        "tracker_key": "onlyencodes",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [
                    {"hash": "a" * 40, "name": "Episode A", "state": "stoppedDL"},
                    {"hash": "b" * 40, "name": "Episode B", "state": "stoppedDL"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--mapping-json",
            str(mapping),
            "--baseline-json",
            str(baseline),
            "--db",
            str(tmp_path / "missing.db"),
            "--output-prefix",
            "t103",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    json_out = _extract_stdout_path(result.stdout, "json_output")
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["conflict_count"] == 2
    assert summary["shared_target_payload_conflicts"] >= 2
