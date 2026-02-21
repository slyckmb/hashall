import json
import os
import sqlite3
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-56_qb-missing-audit.sh"


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


def test_missing_audit_generates_actionable_plan_from_input_json(tmp_path: Path) -> None:
    save_a = tmp_path / "save-a"
    save_b = tmp_path / "save-b"
    save_c = tmp_path / "save-c"
    save_a.mkdir(parents=True)
    save_b.mkdir(parents=True)
    save_c.mkdir(parents=True)
    existing_file = save_b / "Movie.2024.1080p.mkv"
    existing_file.write_bytes(b"x")

    input_json = tmp_path / "qbit.json"
    input_json.write_text(
        json.dumps(
            {
                "torrents": [
                    {
                        "hash": "m1" * 20,
                        "name": "Missing One",
                        "save_path": str(save_a),
                        "content_path": str(save_a / "Movie.2024.1080p.mkv"),
                        "tags": "rehome,~noHL",
                        "state": "missingFiles",
                        "progress": 1.0,
                    },
                    {
                        "hash": "c1" * 20,
                        "name": "Candidate One",
                        "save_path": str(save_b),
                        "content_path": str(existing_file),
                        "tags": "cross-seed",
                        "state": "pausedUP",
                        "progress": 1.0,
                    },
                    {
                        "hash": "m2" * 20,
                        "name": "Missing Two",
                        "save_path": str(save_c),
                        "content_path": str(save_c / "Ghost.2024.1080p.mkv"),
                        "tags": "",
                        "state": "missingFiles",
                        "progress": 1.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE payloads (
          payload_id INTEGER PRIMARY KEY,
          payload_hash TEXT,
          device_id INTEGER,
          root_path TEXT,
          file_count INTEGER,
          total_bytes INTEGER,
          status TEXT
        );
        CREATE TABLE torrent_instances (
          torrent_hash TEXT PRIMARY KEY,
          payload_id INTEGER,
          device_id INTEGER,
          save_path TEXT,
          root_name TEXT,
          category TEXT,
          tags TEXT,
          last_seen_at REAL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO payloads(payload_id,payload_hash,device_id,root_path,file_count,total_bytes,status)
        VALUES (1,NULL,NULL,?,?,?,'incomplete')
        """,
        (str(save_c / "Ghost.2024.1080p.mkv"), 1, 1),
    )
    conn.execute(
        """
        INSERT INTO torrent_instances(torrent_hash,payload_id,save_path,root_name)
        VALUES (?,?,?,?)
        """,
        ("m2" * 20, 1, str(save_c), "Ghost.2024.1080p.mkv"),
    )
    conn.commit()
    conn.close()

    result = _run_script(
        [
            "--input-json",
            str(input_json),
            "--db",
            str(db_path),
            "--output-prefix",
            "t56",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "summary missing_total=2 actionable_total=1" in result.stdout

    plan_json = _extract_output_path(result.stdout, "plan_json")
    plan = json.loads(plan_json.read_text(encoding="utf-8"))
    assert plan["summary"]["actions_total"] == 1
    action = plan["actions"][0]
    assert action["torrent_hash"] == ("m1" * 20)
    assert action["target_save_path"] == str(save_b)
    assert action["reason"] == "root_name_unique_candidate"
