import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-101_nohl-basics-qb-candidate-mapping.sh"


def _write_baseline(path: Path) -> None:
    obj = {
        "summary": {"queue_total": 2},
        "entries": [
            {
                "hash": "a" * 40,
                "state": "stoppedDL",
                "progress": 0.0,
                "amount_left": 100,
                "save_path": "/tmp/not-real-a",
                "content_path": "/tmp/not-real-a/file.mkv",
            },
            {
                "hash": "b" * 40,
                "state": "stoppedDL",
                "progress": 0.1,
                "amount_left": 200,
                "save_path": "/tmp/not-real-b",
                "content_path": "/incomplete_torrents/not-real-b/file.mkv",
            },
        ],
    }
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def test_rehome_101_help_lists_options() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--baseline-json" in result.stdout
    assert "--db PATH" in result.stdout
    assert "--output-prefix" in result.stdout
    assert "--tracker-aware" in result.stdout
    assert "--candidate-top-n" in result.stdout


def test_rehome_101_runs_with_custom_baseline_and_missing_db(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)
    allowed_root = tmp_path / "allowed-root"
    allowed_root.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--baseline-json",
            str(baseline),
            "--db",
            str(tmp_path / "missing.db"),
            "--output-prefix",
            "t101",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "MAP_ALLOWED_ROOTS": str(allowed_root),
            "MAP_ENABLE_DISCOVERY_SCAN": "0",
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "summary mapped=2" in result.stdout
    assert "unresolved=" in result.stdout


def _extract_stdout_path(stdout: str, key: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return Path(line.split("=", 1)[1].strip())
    raise AssertionError(f"missing {key}=... in stdout:\n{stdout}")


def test_rehome_101_tracker_aware_prefers_tracker_matching_path(tmp_path: Path) -> None:
    allowed_root = tmp_path / "seeding"
    onlyencodes = allowed_root / "cross-seed" / "OnlyEncodes (API)"
    aither = allowed_root / "cross-seed" / "Aither (API)"
    current = allowed_root / "cross-seed" / "SomeTracker"
    onlyencodes.mkdir(parents=True, exist_ok=True)
    aither.mkdir(parents=True, exist_ok=True)
    current.mkdir(parents=True, exist_ok=True)
    (onlyencodes / "Episode.mkv").write_text("x", encoding="utf-8")
    (aither / "Episode.mkv").write_text("x", encoding="utf-8")

    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "summary": {"queue_total": 1},
                "entries": [
                    {
                        "hash": "a" * 40,
                        "name": "Episode.mkv",
                        "state": "stoppedDL",
                        "progress": 0.0,
                        "amount_left": 1234,
                        "save_path": str(current),
                        "content_path": str(current / "Episode.mkv"),
                        "category": "cross-seed",
                        "tags": "onlyencodes,cross-seed",
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

    registry = tmp_path / "tracker-registry.yml"
    registry.write_text(
        "\n".join(
            [
                "version: 1",
                "trackers:",
                "  onlyencodes:",
                "    display_name: OnlyEncodes (API)",
                "    qbitmanage:",
                "      category: onlyencodes",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    common_env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "MAP_ALLOWED_ROOTS": str(allowed_root),
        "MAP_ENABLE_DISCOVERY_SCAN": "1",
    }

    no_tracker = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--baseline-json",
            str(baseline),
            "--db",
            str(tmp_path / "missing.db"),
            "--output-prefix",
            "t101a",
            "--candidate-top-n",
            "4",
            "--tracker-registry",
            str(registry),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=common_env,
    )
    assert no_tracker.returncode == 0, no_tracker.stdout + no_tracker.stderr
    no_tracker_json = _extract_stdout_path(no_tracker.stdout, "json_output")
    no_tracker_payload = json.loads(no_tracker_json.read_text(encoding="utf-8"))
    best_without = str(no_tracker_payload["entries"][0]["best_candidate"])
    assert best_without.endswith("/cross-seed/Aither (API)")

    tracker_enabled = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--baseline-json",
            str(baseline),
            "--db",
            str(tmp_path / "missing.db"),
            "--output-prefix",
            "t101b",
            "--candidate-top-n",
            "4",
            "--tracker-aware",
            "--tracker-registry",
            str(registry),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=common_env,
    )
    assert tracker_enabled.returncode == 0, tracker_enabled.stdout + tracker_enabled.stderr
    tracker_json = _extract_stdout_path(tracker_enabled.stdout, "json_output")
    tracker_payload = json.loads(tracker_json.read_text(encoding="utf-8"))
    best_with = str(tracker_payload["entries"][0]["best_candidate"])
    assert best_with.endswith("/cross-seed/OnlyEncodes (API)")
