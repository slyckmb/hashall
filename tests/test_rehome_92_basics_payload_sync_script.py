import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-92_nohl-basics-payload-sync.sh"


def _write_fake_python(fake_bin: Path) -> None:
    script = textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        state_path = Path(os.environ["FAKE_PYTHON_STATE"])
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            state = {"calls": [], "payload_calls": []}

        args = sys.argv[1:]
        state["calls"].append(args)

        if args[:4] == ["-m", "hashall.cli", "payload", "sync"]:
            state["payload_calls"].append(args)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            raise SystemExit(int(os.environ.get("FAKE_PYTHON_PAYLOAD_RC", "0")))

        if args and args[0] == "-":
            mode = os.environ.get("MODE", "")
            missing_gib = float(os.environ.get("FAKE_MISSING_GIB", "300") or "300")
            min_upgrade_gib = float(os.environ.get("MIN_UPGRADE_GIB", "200") or "200")
            yes_upgrade = str(os.environ.get("YES_UPGRADE", "0")).strip().lower() in {"1", "true", "yes", "on"}

            preflight_json = os.environ.get("PREFLIGHT_JSON", "").strip()
            if preflight_json:
                Path(preflight_json).write_text(
                    json.dumps(
                        {
                            "mode": mode,
                            "missing_gib": missing_gib,
                            "roots_with_missing": 1,
                            "top_roots": [],
                        }
                    ),
                    encoding="utf-8",
                )
                print(
                    f"preflight mode={mode} prefixes=1 roots_with_missing=1 "
                    f"missing_files=10 missing_gib={missing_gib:.1f}"
                )
                print(f"preflight_json={preflight_json}")

                if mode != "map-only" and missing_gib >= min_upgrade_gib and not yes_upgrade:
                    print(
                        f"gate=upgrade_preflight status=blocked missing_gib={missing_gib:.1f} "
                        f"threshold_gib={min_upgrade_gib:.1f}"
                    )
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                    raise SystemExit(4)

        state_path.write_text(json.dumps(state), encoding="utf-8")
        raise SystemExit(0)
        """
    )
    py_path = fake_bin / "python"
    py_path.write_text(script, encoding="utf-8")
    py_path.chmod(py_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_script(
    tmp_path: Path,
    args: list[str],
    *,
    missing_gib: float = 300.0,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_python(fake_bin)

    state_path = tmp_path / "fake-python-state.json"
    state_path.write_text(json.dumps({"calls": [], "payload_calls": []}), encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_PYTHON_STATE"] = str(state_path)
    env["FAKE_MISSING_GIB"] = str(missing_gib)
    env["FAKE_PYTHON_PAYLOAD_RC"] = "0"

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return result, state


def test_phase_92_map_only_runs_without_upgrade_flags(tmp_path: Path) -> None:
    result, state = _run_script(
        tmp_path,
        [
            "--mode",
            "map-only",
            "--output-prefix",
            "t92-map-only",
            "--min-upgrade-gib",
            "1",
        ],
        missing_gib=999.0,
    )
    assert result.returncode == 0, result.stderr
    assert "mode=map-only" in result.stdout
    assert len(state["payload_calls"]) == 1
    payload_args = state["payload_calls"][0]
    assert "--upgrade-missing" not in payload_args


def test_phase_92_upgrade_blocks_without_yes_upgrade(tmp_path: Path) -> None:
    result, state = _run_script(
        tmp_path,
        [
            "--mode",
            "upgrade-full",
            "--output-prefix",
            "t92-blocked",
            "--min-upgrade-gib",
            "200",
        ],
        missing_gib=250.0,
    )
    assert result.returncode == 4
    assert "gate=upgrade_preflight status=blocked" in result.stdout
    assert state["payload_calls"] == []


def test_phase_92_upgrade_with_yes_upgrade_passes_flags(tmp_path: Path) -> None:
    result, state = _run_script(
        tmp_path,
        [
            "--mode",
            "upgrade-full",
            "--yes-upgrade",
            "--output-prefix",
            "t92-yes",
            "--min-upgrade-gib",
            "200",
            "--upgrade-order",
            "input",
            "--upgrade-root-limit",
            "7",
            "--upgrade-parallel",
            "1",
            "--workers",
            "3",
        ],
        missing_gib=250.0,
    )
    assert result.returncode == 0, result.stderr
    assert "gate=upgrade_preflight status=allowed" in result.stdout
    assert len(state["payload_calls"]) == 1
    payload_args = state["payload_calls"][0]
    assert "--upgrade-missing" in payload_args
    assert "--upgrade-order" in payload_args
    assert "input" in payload_args
    assert "--upgrade-root-limit" in payload_args
    assert "7" in payload_args
    assert "--parallel" in payload_args
    assert "--workers" in payload_args
    assert "3" in payload_args
