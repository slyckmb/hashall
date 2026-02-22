import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-57_qb-missing-remediate.sh"


def _run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _extract_output_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return (REPO_ROOT / line.split("=", 1)[1].strip()).resolve()
    raise AssertionError(f"Missing {key}=... in output")


def test_missing_remediate_dryrun_filters_and_limits_actions(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "torrent_hash": "a" * 40,
                        "current_save_path": "/pool/data/seeds/cross-seed/A",
                        "target_save_path": "/pool/data/seeds/movies",
                        "reason": "root_name_unique_candidate",
                        "confidence": 0.75,
                    },
                    {
                        "torrent_hash": "b" * 40,
                        "current_save_path": "/pool/data/seeds/cross-seed/B",
                        "target_save_path": "/pool/data/seeds/series",
                        "reason": "alias_path_mismatch",
                        "confidence": 0.95,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        [
            "--plan",
            str(plan_path),
            "--mode",
            "dryrun",
            "--only-reason",
            "alias_path_mismatch",
            "--limit",
            "1",
            "--output-prefix",
            "t57",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "actions_selected=1" in result.stdout
    assert "reason_count reason=alias_path_mismatch total=1" in result.stdout
    assert "item idx=1/1 hash=bbbbbbbbbbbbbbbb" in result.stdout
    assert "summary selected=1 ok=0 errors=0 dryrun=1" in result.stdout

    result_json = _extract_output_path(result.stdout, "result_json")
    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["summary"]["selected_actions"] == 1
    assert data["summary"]["dryrun"] == 1
    assert data["results"][0]["torrent_hash"] == "b" * 40
