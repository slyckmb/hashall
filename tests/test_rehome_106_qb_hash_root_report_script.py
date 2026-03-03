import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "qb-hash-root-report.sh"


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_106_help_lists_options() -> None:
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
    assert "--candidate-top-n" in result.stdout
    assert "--include-db-discovery" in result.stdout


def test_rehome_106_builds_hash_and_root_reports(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    target = tmp_path / "seeding" / "cross-seed" / "OnlyEncodes (API)"
    target.mkdir(parents=True, exist_ok=True)
    payload_file = target / "Episode.mkv"
    payload_file.write_text("x", encoding="utf-8")

    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [
                    {
                        "hash": "a" * 40,
                        "name": "Episode.mkv",
                        "state": "stoppedDL",
                        "save_path": str(tmp_path / "old" / "OnlyEncodes (API)"),
                        "content_path": str(tmp_path / "old" / "OnlyEncodes (API)" / "Episode.mkv"),
                        "tracker_key": "onlyencodes",
                        "tracker_name": "OnlyEncodes (API)",
                        "category": "cross-seed",
                        "best_candidate": str(target),
                        "best_payload_root": str(payload_file),
                        "best_score": 200,
                        "candidates": [
                            {
                                "rank": 1,
                                "path": str(target),
                                "payload_root": str(payload_file),
                                "score": 200,
                                "reason": "payload_root_path_exists",
                            }
                        ],
                    }
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
                    {
                        "hash": "a" * 40,
                        "name": "Episode.mkv",
                        "state": "stoppedDL",
                        "save_path": str(target),
                        "content_path": str(payload_file),
                        "category": "cross-seed",
                        "tracker_name": "OnlyEncodes (API)",
                        "tracker_key": "onlyencodes",
                    }
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
            "t106",
            "--candidate-top-n",
            "3",
            "--no-db-discovery",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    json_out = _extract_stdout_path(result.stdout, "json_output")
    root_json_out = _extract_stdout_path(result.stdout, "root_json_output")

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    root_payload = json.loads(root_json_out.read_text(encoding="utf-8"))

    assert payload["summary"]["hashes"] == 1
    assert payload["summary"]["hashes_with_routeable_candidates"] == 1
    assert root_payload["summary"]["roots"] >= 1

    row = payload["hashes"][0]
    assert row["hash"] == "a" * 40
    assert row["candidates"][0]["path"] == str(target)
    assert row["candidates"][0]["route_eligible"] is True
    assert "a" * 40 in row["candidates"][0]["owner_hashes"]

