import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-60_nohl-apply-group-batch.sh"


def _write_fake_zpool(fake_bin: Path) -> None:
    script = textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from pathlib import Path

        state_path = Path(os.environ["FAKE_ZPOOL_STATE"])
        caps = [x.strip() for x in os.environ.get("FAKE_ZPOOL_CAPS", "87").split(",") if x.strip()]
        if not caps:
            caps = ["87"]
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            state = {"calls": 0}

        idx = int(state.get("calls", 0))
        state["calls"] = idx + 1
        state_path.write_text(json.dumps(state), encoding="utf-8")

        cap = caps[min(idx, len(caps) - 1)]
        # Expected usage from script: zpool list -H -o cap <pool>
        if "list" not in sys.argv:
            print("unsupported fake zpool invocation", file=sys.stderr)
            raise SystemExit(2)
        print(f"{cap}%")
        """
    )
    zpool_path = fake_bin / "zpool"
    zpool_path.write_text(script, encoding="utf-8")
    zpool_path.chmod(zpool_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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
            state = {"apply_calls": [], "other_calls": []}

        args = sys.argv[1:]
        if "-m" in args:
            m_idx = args.index("-m")
            module = args[m_idx + 1] if (m_idx + 1) < len(args) else ""
            subcmd = args[m_idx + 2] if (m_idx + 2) < len(args) else ""
            if module == "rehome.cli" and subcmd == "apply":
                plan_path = args[m_idx + 3] if (m_idx + 3) < len(args) else ""
                state["apply_calls"].append({"plan_path": plan_path, "args": args})
                state_path.write_text(json.dumps(state), encoding="utf-8")
                raise SystemExit(int(os.environ.get("FAKE_PYTHON_APPLY_RC", "0")))

        state["other_calls"].append(args)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        raise SystemExit(0)
        """
    )
    py_path = fake_bin / "python"
    py_path.write_text(script, encoding="utf-8")
    py_path.chmod(py_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _parse_path_from_output(stdout: str, key: str) -> Path:
    path = ""
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            path = line.split("=", 1)[1].strip()
    assert path, f"Missing {key}=... line in output"
    return (REPO_ROOT / path).resolve()


def _run_apply_script(tmp_path: Path, *, caps: str, plans_tsv: Path, min_free_pct: int = 15) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_zpool(fake_bin)
    _write_fake_python(fake_bin)

    zpool_state = tmp_path / "fake-zpool-state.json"
    python_state = tmp_path / "fake-python-state.json"
    zpool_state.write_text(json.dumps({"calls": 0}), encoding="utf-8")
    python_state.write_text(json.dumps({"apply_calls": [], "other_calls": []}), encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_ZPOOL_CAPS"] = caps
    env["FAKE_ZPOOL_STATE"] = str(zpool_state)
    env["FAKE_PYTHON_STATE"] = str(python_state)
    env["FAKE_PYTHON_APPLY_RC"] = "0"

    return subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--plans-file",
            str(plans_tsv),
            "--min-free-pct",
            str(min_free_pct),
            "--pool-name",
            "pool",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_apply_script_exits_early_when_pool_below_threshold(tmp_path: Path) -> None:
    plan_a = tmp_path / "a.json"
    plan_b = tmp_path / "b.json"
    plan_a.write_text("{}", encoding="utf-8")
    plan_b.write_text("{}", encoding="utf-8")
    plans_tsv = tmp_path / "plans.tsv"
    plans_tsv.write_text(
        f"{'a'*64}\t{plan_a}\n{'b'*64}\t{plan_b}\n",
        encoding="utf-8",
    )

    result = _run_apply_script(tmp_path, caps="88", plans_tsv=plans_tsv, min_free_pct=15)
    assert result.returncode == 10, result.stdout
    assert "gate=pool_space context=preflight status=blocked free_pct=12 required_min=15" in result.stdout
    assert "summary total=2 processed=0 ok=0 failed=0 deferred=2 aborted=1 reason=low_pool_space_preflight" in result.stdout

    python_state_path = tmp_path / "fake-python-state.json"
    state = json.loads(python_state_path.read_text(encoding="utf-8"))
    assert state["apply_calls"] == []

    deferred_path = _parse_path_from_output(result.stdout, "deferred_hashes")
    deferred_rows = [line.strip() for line in deferred_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(deferred_rows) == 2


def test_apply_script_halts_mid_batch_when_pool_drops_below_threshold(tmp_path: Path) -> None:
    plan_a = tmp_path / "a.json"
    plan_b = tmp_path / "b.json"
    plan_a.write_text("{}", encoding="utf-8")
    plan_b.write_text("{}", encoding="utf-8")
    hash_a = "a" * 64
    hash_b = "b" * 64
    plans_tsv = tmp_path / "plans.tsv"
    plans_tsv.write_text(f"{hash_a}\t{plan_a}\n{hash_b}\t{plan_b}\n", encoding="utf-8")

    # Calls: preflight=80%(free 20), first item=80%(free 20), second item=90%(free 10 -> blocked)
    result = _run_apply_script(tmp_path, caps="80,80,90", plans_tsv=plans_tsv, min_free_pct=15)
    assert result.returncode == 10, result.stdout
    assert "apply idx=1/2 payload=aaaaaaaaaaaaaaaa status=ok" in result.stdout
    assert "apply idx=2/2 payload=bbbbbbbbbbbbbbbb status=blocked_low_space" in result.stdout
    assert "summary total=2 processed=1 ok=1 failed=0 deferred=1 aborted=1 reason=low_pool_space_runtime" in result.stdout

    python_state_path = tmp_path / "fake-python-state.json"
    state = json.loads(python_state_path.read_text(encoding="utf-8"))
    assert len(state["apply_calls"]) == 1
    assert state["apply_calls"][0]["plan_path"] == str(plan_a)

    deferred_path = _parse_path_from_output(result.stdout, "deferred_hashes")
    deferred_rows = [line.strip() for line in deferred_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert deferred_rows == [hash_b]
