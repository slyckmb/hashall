import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-107_nohl-basics-qb-repair-lane-plan.sh"


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_107_help_lists_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--hash-root-json" in result.stdout
    assert "--route-top-n" in result.stdout
    assert "--output-prefix" in result.stdout


def test_rehome_107_classifies_lanes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    route_target = tmp_path / "seeding" / "cross-seed" / "OnlyEncodes (API)"
    route_target.mkdir(parents=True, exist_ok=True)
    sibling_target = tmp_path / "seeding" / "cross-seed" / "Aither (API)"
    sibling_target.mkdir(parents=True, exist_ok=True)

    hash_root = tmp_path / "hash-root.json"
    hash_root.write_text(
        json.dumps(
            {
                "summary": {"hashes": 3},
                "hashes": [
                    {
                        "hash": "a" * 40,
                        "name": "A",
                        "state": "stoppedDL",
                        "tracker_key": "onlyencodes",
                        "category": "cross-seed",
                        "qb_save_path": str(tmp_path / "old" / "OnlyEncodes (API)"),
                        "qb_content_path": str(tmp_path / "old" / "OnlyEncodes (API)" / "A.mkv"),
                        "candidates": [
                            {
                                "rank": 1,
                                "path": str(route_target),
                                "score": 200,
                                "path_exists": True,
                                "route_eligible": True,
                                "owner_hashes": ["a" * 40],
                                "owner_conflicts": [],
                                "tracker_path_match": "exact",
                            }
                        ],
                    },
                    {
                        "hash": "b" * 40,
                        "name": "B",
                        "state": "stoppedDL",
                        "tracker_key": "aither",
                        "category": "cross-seed",
                        "qb_save_path": str(tmp_path / "old" / "Aither (API)"),
                        "qb_content_path": str(tmp_path / "old" / "Aither (API)" / "B.mkv"),
                        "candidates": [
                            {
                                "rank": 1,
                                "path": str(sibling_target),
                                "score": 180,
                                "path_exists": True,
                                "route_eligible": False,
                                "owner_hashes": ["c" * 40],
                                "owner_conflicts": ["c" * 40],
                                "tracker_path_match": "exact",
                            }
                        ],
                    },
                    {
                        "hash": "d" * 40,
                        "name": "D",
                        "state": "stoppedDL",
                        "tracker_key": "unknown",
                        "category": "movies",
                        "qb_save_path": str(tmp_path / "old" / "movies"),
                        "qb_content_path": str(tmp_path / "old" / "movies" / "D.mkv"),
                        "candidates": [],
                    },
                ],
                "roots": [],
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
            "--hash-root-json",
            str(hash_root),
            "--output-prefix",
            "t107",
            "--route-top-n",
            "3",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    json_out = _extract_stdout_path(result.stdout, "json_output")
    route_hashes = _extract_stdout_path(result.stdout, "route_hashes")
    sibling_hashes = _extract_stdout_path(result.stdout, "sibling_hashes")
    missing_hashes = _extract_stdout_path(result.stdout, "missing_hashes")

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["hashes"] == 3
    assert summary["route_found"] == 1
    assert summary["build_from_sibling"] == 1
    assert summary["true_missing"] == 1

    by_hash = {row["hash"]: row for row in payload["entries"]}
    assert by_hash["a" * 40]["lane"] == "route_found"
    assert by_hash["b" * 40]["lane"] == "build_from_sibling"
    assert by_hash["d" * 40]["lane"] == "true_missing"

    assert route_hashes.read_text(encoding="utf-8").strip() == "a" * 40
    assert sibling_hashes.read_text(encoding="utf-8").strip() == "b" * 40
    assert missing_hashes.read_text(encoding="utf-8").strip() == "d" * 40

