import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-102_nohl-basics-qb-repair-pilot.sh"


def test_rehome_102_help_lists_options() -> None:
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
    assert "--mode MODE" in result.stdout
    assert "--timeout-s" in result.stdout
    assert "--candidate-top-n" in result.stdout
    assert "--candidate-fallback" in result.stdout
    assert "--ownership-audit-json" in result.stdout


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_102_dryrun_preserves_ranked_candidates(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    target1 = tmp_path / "pool" / "cross-seed" / "OnlyEncodes (API)"
    target2 = tmp_path / "pool" / "cross-seed" / "Aither (API)"
    target1.mkdir(parents=True, exist_ok=True)
    target2.mkdir(parents=True, exist_ok=True)

    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "summary": {},
                "entries": [
                    {
                        "hash": "a" * 40,
                        "confidence": "confident",
                        "recoverable": True,
                        "save_path": str(tmp_path / "pool" / "cross-seed" / "OldTracker"),
                        "best_candidate": str(target1),
                        "best_payload_root": str(target1 / "Episode.mkv"),
                        "best_score": 120,
                        "best_reason": "payload_root_path_exists",
                        "best_evidence": ["expected_name_exists"],
                        "best_expected_matches": ["Episode.mkv"],
                        "candidates": [
                            {
                                "rank": 1,
                                "path": str(target1),
                                "payload_root": str(target1 / "Episode.mkv"),
                                "score": 120,
                                "reason": "payload_root_path_exists",
                            },
                            {
                                "rank": 2,
                                "path": str(target2),
                                "payload_root": str(target2 / "Episode.mkv"),
                                "score": 119,
                                "reason": "payload_root_path_exists",
                            },
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
                        "save_path": str(tmp_path / "pool" / "cross-seed" / "OldTracker"),
                        "size": 1234,
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
            "--mode",
            "dryrun",
            "--limit",
            "1",
            "--candidate-top-n",
            "2",
            "--candidate-fallback",
            "--mapping-json",
            str(mapping),
            "--baseline-json",
            str(baseline),
            "--output-prefix",
            "t102",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "HASHALL_QB_HTTP_TIMEOUT": "0.2",
            "HASHALL_QB_HTTP_RETRIES": "1",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan_json = _extract_stdout_path(result.stdout, "plan_json")
    payload = json.loads(plan_json.read_text(encoding="utf-8"))
    assert payload["summary"]["candidate_top_n"] == 2
    assert payload["summary"]["candidate_fallback"] == 1
    plan = payload["plan"][0]
    assert len(plan["candidates"]) == 2
    assert plan["candidates"][0]["path"] == str(target1)
    assert plan["candidates"][1]["path"] == str(target2)
