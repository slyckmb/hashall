import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-108_nohl-basics-qb-build-strict-map.sh"


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_108_help_lists_options() -> None:
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
    assert "--audit-json" in result.stdout
    assert "--failure-cache-json" in result.stdout
    assert "--min-score-gap" in result.stdout
    assert "--require-unique-target" in result.stdout


def test_rehome_108_builds_strict_map_and_quarantines_known_failures(tmp_path: Path) -> None:
    m1 = tmp_path / "target" / "A"
    m2 = tmp_path / "target" / "B"
    m1.mkdir(parents=True, exist_ok=True)
    m2.mkdir(parents=True, exist_ok=True)

    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [
                    {
                        "hash": "a" * 40,
                        "name": "A",
                        "confidence": "confident",
                        "state": "stoppedDL",
                        "best_candidate": str(m1),
                        "best_score": 220,
                        "candidates": [
                            {"rank": 1, "path": str(m1), "score": 220},
                            {"rank": 2, "path": str(m2), "score": 180},
                        ],
                    },
                    {
                        "hash": "b" * 40,
                        "name": "B",
                        "confidence": "confident",
                        "state": "stoppedDL",
                        "best_candidate": str(m2),
                        "best_score": 215,
                        "candidates": [
                            {"rank": 1, "path": str(m2), "score": 215},
                            {"rank": 2, "path": str(m1), "score": 160},
                        ],
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
                    {"hash": "a" * 40, "content_path": str(tmp_path / "ok" / "A.mkv")},
                    {"hash": "b" * 40, "content_path": str(tmp_path / "ok" / "B.mkv")},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [],
                "conflicts": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    failure_cache = tmp_path / "cache.json"
    failure_cache.write_text(
        json.dumps(
            {
                "entries": {
                    "b" * 40: {
                        str(m2): {
                            "count": 2,
                            "errors": {"content_path_mismatch_post_move": 2},
                        }
                    }
                },
                "meta": {"threshold": 1},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    strict_out = tmp_path / "strict.json"
    quarantine_out = tmp_path / "quarantine.json"
    hashes_out = tmp_path / "strict-hashes.txt"
    quarantine_hashes_out = tmp_path / "quarantine-hashes.txt"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--mapping-json",
            str(mapping),
            "--baseline-json",
            str(baseline),
            "--audit-json",
            str(audit),
            "--failure-cache-json",
            str(failure_cache),
            "--result-glob",
            str(tmp_path / "no-results-*.json"),
            "--strict-map",
            str(strict_out),
            "--quarantine-json",
            str(quarantine_out),
            "--hashes-txt",
            str(hashes_out),
            "--quarantine-hashes-txt",
            str(quarantine_hashes_out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    strict_map = json.loads(strict_out.read_text(encoding="utf-8"))
    assert len(strict_map["entries"]) == 1
    assert strict_map["entries"][0]["hash"] == "a" * 40

    quarantine = json.loads(quarantine_out.read_text(encoding="utf-8"))
    assert quarantine["summary"]["quarantined_entries"] == 1
    qhashes = {row["hash"] for row in quarantine["quarantine"]}
    assert qhashes == {"b" * 40}

    assert hashes_out.read_text(encoding="utf-8").strip() == "a" * 40
    assert quarantine_hashes_out.read_text(encoding="utf-8").strip() == "b" * 40

