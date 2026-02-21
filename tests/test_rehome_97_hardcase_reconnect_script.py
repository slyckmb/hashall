import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-97_nohl-basics-qb-missing-hardcase-reconnect.sh"


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def test_phase_97_filters_hard_cases_and_runs_dryrun_remediation(tmp_path: Path) -> None:
    audit_json = tmp_path / "audit.json"
    plan_json = tmp_path / "plan.json"

    _write_json(
        audit_json,
        {
            "entries": [
                {
                    "torrent_hash": "a" * 40,
                    "root_cause": "ambiguous_root_name_candidates",
                    "save_path": "/pool/data/seeds/cross-seed/A",
                    "content_path": "/pool/data/seeds/cross-seed/A/file.mkv",
                    "db_root_path": "/pool/data/seeds/cross-seed/A",
                },
                {
                    "torrent_hash": "b" * 40,
                    "root_cause": "root_name_relink_candidate",
                    "save_path": "/pool/data/seeds/cross-seed/B",
                    "content_path": "/pool/data/seeds/cross-seed/B/file.mkv",
                    "db_root_path": "/pool/data/seeds/cross-seed/B",
                },
            ]
        },
    )
    _write_json(
        plan_json,
        {
            "generated_at": "2026-02-21T00:00:00",
            "actions": [
                {
                    "torrent_hash": "a" * 40,
                    "reason": "root_name_unique_candidate",
                    "current_save_path": "/pool/data/seeds/cross-seed/A",
                    "target_save_path": "/pool/data/seeds/cross-seed/A-fixed",
                },
                {
                    "torrent_hash": "b" * 40,
                    "reason": "root_name_unique_candidate",
                    "current_save_path": "/pool/data/seeds/cross-seed/B",
                    "target_save_path": "/pool/data/seeds/cross-seed/B-fixed",
                },
            ],
        },
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--audit-json",
            str(audit_json),
            "--plan-json",
            str(plan_json),
            "--mode",
            "dryrun",
            "--refresh-audit",
            "0",
            "--rebuild",
            "0",
            "--output-prefix",
            "t97",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "hard_cases=1" in result.stdout
    assert "actions=1" in result.stdout

    filtered = sorted((REPO_ROOT / "out" / "reports" / "rehome-normalize").glob("t97-qb-missing-hardcase-plan-*.json"))[-1]
    obj = json.loads(filtered.read_text(encoding="utf-8"))
    assert obj["actions_total"] == 1
    assert obj["actions"][0]["torrent_hash"] == "a" * 40


def test_phase_97_exits_cleanly_when_no_hard_cases(tmp_path: Path) -> None:
    audit_json = tmp_path / "audit-empty.json"
    plan_json = tmp_path / "plan-empty.json"

    _write_json(
        audit_json,
        {
            "entries": [
                {
                    "torrent_hash": "c" * 40,
                    "root_cause": "root_name_relink_candidate",
                    "save_path": "/pool/data/seeds/cross-seed/C",
                }
            ]
        },
    )
    _write_json(plan_json, {"actions": []})

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--audit-json",
            str(audit_json),
            "--plan-json",
            str(plan_json),
            "--refresh-audit",
            "0",
            "--rebuild",
            "0",
            "--output-prefix",
            "t97-empty",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "hard_cases=0" in result.stdout
    assert "no-hard-cases-found" in result.stdout
