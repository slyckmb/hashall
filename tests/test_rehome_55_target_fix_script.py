import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-55_nohl-fix-target-hash.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")


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


def _path_from_output(output: str, key: str) -> Path:
    for line in output.splitlines():
        if line.startswith(f"{key}="):
            return (REPO_ROOT / line.split("=", 1)[1].strip()).resolve()
    raise AssertionError(f"Missing output key: {key}")


def test_target_fix_script_resolves_hash_and_prints_commands(tmp_path: Path) -> None:
    payload_hash = "dee7dd49e7994d93999999999999999999999999999999999999999999999999"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "payload_hash": payload_hash,
                        "status": "ok",
                        "plan_path": str(plan_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        [
            "--payload-prefix",
            "dee7dd49e7994d93",
            "--manifest",
            str(manifest_path),
            "--execute",
            "0",
            "--apply",
            "1",
            "--min-free-pct",
            "15",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert f"full_hash={payload_hash}" in result.stdout
    assert "dryrun_cmd=bin/rehome-50_nohl-dryrun-group-batch.sh" in result.stdout
    assert "apply_cmd=bin/rehome-60_nohl-apply-group-batch.sh" in result.stdout
    assert "status=printed_only execute=0" in result.stdout

    hash_file = _path_from_output(result.stdout, "hash_file")
    plan_file = _path_from_output(result.stdout, "plan_file")
    assert hash_file.read_text(encoding="utf-8").strip() == payload_hash
    assert plan_file.read_text(encoding="utf-8").strip() == f"{payload_hash}\t{plan_path}"


def test_target_fix_script_rejects_ambiguous_prefix(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "payload_hash": "dee7dd49e7994d93aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        "status": "ok",
                        "plan_path": str(tmp_path / "a.json"),
                    },
                    {
                        "payload_hash": "dee7dd49e7994d93bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        "status": "ok",
                        "plan_path": str(tmp_path / "b.json"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(
        [
            "--payload-prefix",
            "dee7dd49e7994d93",
            "--manifest",
            str(manifest_path),
        ]
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 2
    assert "Multiple payload hashes match prefix: dee7dd49e7994d93" in output
