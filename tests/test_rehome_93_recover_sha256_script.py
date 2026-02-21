import os
import sqlite3
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-93_nohl-recover-sha256-from-deleted.sh"


def _init_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE files_44 (
            path TEXT PRIMARY KEY,
            size INTEGER,
            mtime REAL,
            quick_hash TEXT,
            sha1 TEXT,
            sha256 TEXT,
            hash_source TEXT,
            inode INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            last_modified_at TEXT,
            status TEXT,
            discovered_under TEXT
        )
        """
    )
    rows = [
        # Recoverable move pair (same inode/size/quick_hash).
        (
            "seeds/_flat/TAAAAA~1",
            111,
            1000.0,
            "qh-a",
            "sha1-a",
            "sha256-a",
            "calculated",
            1001,
            "2026-02-01 00:00:00",
            "2026-02-02 00:00:00",
            "2026-02-02 00:00:00",
            "deleted",
            "/pool/data",
        ),
        (
            "seeds/shows/A/file.mkv",
            111,
            1000.0,
            "qh-a",
            None,
            None,
            None,
            1001,
            "2026-02-02 00:00:00",
            "2026-02-03 00:00:00",
            "2026-02-03 00:00:00",
            "active",
            "/pool/data",
        ),
        # Not recoverable due to quick-hash mismatch.
        (
            "seeds/_flat/TBBBBB~2",
            222,
            2000.0,
            "qh-old",
            "sha1-b",
            "sha256-b",
            "calculated",
            1002,
            "2026-02-01 00:00:00",
            "2026-02-02 00:00:00",
            "2026-02-02 00:00:00",
            "deleted",
            "/pool/data",
        ),
        (
            "seeds/shows/B/file.mkv",
            222,
            2000.0,
            "qh-new",
            None,
            None,
            None,
            1002,
            "2026-02-02 00:00:00",
            "2026-02-03 00:00:00",
            "2026-02-03 00:00:00",
            "active",
            "/pool/data",
        ),
        # Active already has sha256; should remain untouched.
        (
            "seeds/shows/C/file.mkv",
            333,
            3000.0,
            "qh-c",
            "sha1-c",
            "sha256-c",
            "calculated",
            1003,
            "2026-02-02 00:00:00",
            "2026-02-03 00:00:00",
            "2026-02-03 00:00:00",
            "active",
            "/pool/data",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO files_44 (
            path, size, mtime, quick_hash, sha1, sha256, hash_source, inode,
            first_seen_at, last_seen_at, last_modified_at, status, discovered_under
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _run_script(db_path: Path, log_dir: Path, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--db",
            str(db_path),
            "--device-id",
            "44",
            "--log-dir",
            str(log_dir),
            "--output-prefix",
            "t93",
            "--sample",
            "5",
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_recover_sha93_dryrun_does_not_modify_db(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    log_dir = tmp_path / "logs"
    _init_db(db_path)

    result = _run_script(db_path, log_dir, [])
    assert result.returncode == 0, result.stderr
    assert "mode=dryrun" in result.stdout
    assert "recoverable_candidates=1" in result.stdout
    assert "result=ok mode=dryrun recoverable_candidates=1" in result.stdout

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT sha256 FROM files_44 WHERE path = ?",
        ("seeds/shows/A/file.mkv",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] is None


def test_recover_sha93_apply_updates_only_recoverable_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    log_dir = tmp_path / "logs"
    _init_db(db_path)

    result = _run_script(db_path, log_dir, ["--apply"])
    assert result.returncode == 0, result.stderr
    assert "mode=apply" in result.stdout
    assert "updated_rows=1" in result.stdout
    assert "result=ok mode=apply updated_rows=1" in result.stdout

    conn = sqlite3.connect(str(db_path))
    recovered = conn.execute(
        "SELECT sha1, sha256 FROM files_44 WHERE path = ?",
        ("seeds/shows/A/file.mkv",),
    ).fetchone()
    still_missing = conn.execute(
        "SELECT sha1, sha256 FROM files_44 WHERE path = ?",
        ("seeds/shows/B/file.mkv",),
    ).fetchone()
    conn.close()

    assert recovered == ("sha1-a", "sha256-a")
    assert still_missing == (None, None)
