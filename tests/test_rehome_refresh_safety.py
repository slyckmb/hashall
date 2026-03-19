import sqlite3
from contextlib import contextmanager
from pathlib import Path

from click.testing import CliRunner
import rehome.auto as auto_mod
import rehome.cli as cli_mod
import rehome.config as config_mod

from rehome.auto import _parse_link_plan_id, _parse_upgrade_summary, _run_catalog_preflight


class _DummyLock:
    def close(self) -> None:
        return None


def test_parse_upgrade_summary_extracts_counts() -> None:
    parsed = _parse_upgrade_summary(
        "noise\nupgrade_summary queued=12 started=12 completed=9 failed=3 elapsed_s=55\n"
    )
    assert parsed == {"queued": 12, "started": 12, "completed": 9, "failed": 3}


def test_parse_upgrade_summary_returns_none_without_marker() -> None:
    assert _parse_upgrade_summary("no summary line") is None


def test_parse_upgrade_summary_extracts_legacy_upgrade_stage_counts() -> None:
    parsed = _parse_upgrade_summary(
        "noise\nupgrade stage: queued=0 started=0 completed=0 failed=0\n"
    )
    assert parsed == {"queued": 0, "started": 0, "completed": 0, "failed": 0}


def test_parse_link_plan_id_extracts_machine_marker() -> None:
    assert _parse_link_plan_id("noise\nplan_id=12\n") == "12"


def test_parse_link_plan_id_extracts_human_summary_header() -> None:
    stdout = "📋 Plan #57: refresh-pool-media-20260306-230645\n   Execute with: hashall link execute 57 --dry-run\n"
    assert _parse_link_plan_id(stdout) == "57"


def test_run_refresh_executes_dedup_plans_when_stdout_uses_plan_header(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "catalog.db"
    db_path.write_text("")

    commands: list[list[str]] = []

    class _FakePopen:
        def __init__(self, cmd):
            commands.append(list(cmd))
            self.returncode = 0

        def poll(self):
            return self.returncode

    class _FakePopen:
        def __init__(self, cmd):
            commands.append(list(cmd))
            self.returncode = 0

        def poll(self):
            return self.returncode

    class _FakePopen:
        def __init__(self, cmd):
            commands.append(list(cmd))
            self.returncode = 0

        def poll(self):
            return self.returncode

    def _fake_stream(cmd, heartbeat_s=30):
        commands.append(list(cmd))
        label = " ".join(cmd)
        if " link plan " in f" {label} ":
            device = cmd[cmd.index("--device") + 1]
            plan_ids = {"stash": "55", "pool-media": "56"}
            stdout = f"📋 Plan #{plan_ids[device]}: refresh-{device}\n"
            return auto_mod.subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=""), stdout
        if " payload sync " in f" {label} ":
            stdout = "upgrade_summary queued=1 started=1 completed=1 failed=0 elapsed_s=1\n"
            return auto_mod.subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=""), stdout
        return auto_mod.subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), ""

    class _FakeRunLogger:
        def __init__(self, *args, **kwargs):
            self.verbose = False
            self.debug = False

        @contextmanager
        def patch_stdout(self):
            yield

        def write_raw(self, text: str) -> None:
            return None

        def record_step(self, *args, **kwargs) -> None:
            return None

        def dump_json(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    published = {}

    def _fake_publish_seed_root_state(cfg=None, path=None):
        published["cfg"] = dict(cfg or {})
        return (Path("/tmp/seed-root-state.json"), {"writer": "hashall"})

    monkeypatch.setattr(auto_mod, "_validate_refresh_roots", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auto_mod,
        "_run_catalog_preflight",
        lambda *args, **kwargs: (
            True,
            {"ok": True, "checks": [], "summary": {"failed_error": 0, "failed_warning": 0, "total_checks": 9}},
        ),
    )
    monkeypatch.setattr(auto_mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(auto_mod, "_stream_subprocess_output", _fake_stream)
    monkeypatch.setattr("rehome.runlog.RunLogger", _FakeRunLogger)
    monkeypatch.setattr("rehome.seed_state.publish_seed_root_state", _fake_publish_seed_root_state)
    monkeypatch.setattr("rehome.cli._acquire_refresh_lock", lambda: _DummyLock())

    exit_code = auto_mod.run_refresh(
        catalog_path=db_path,
        active_root="/stash/media",
        dest_root="/pool/media/torrents/seeding",
        active_device="stash",
        dest_device="pool-media",
        workers=1,
        skip_dedup=False,
        managed_roots=[],
        verbose=False,
        debug=False,
    )

    assert exit_code == 0
    command_lines = [" ".join(cmd) for cmd in commands]
    assert any("link execute 55 --yes" in line for line in command_lines)
    assert any("link execute 56 --yes" in line for line in command_lines)
    assert published["cfg"]["default_dest_root"] == "/pool/media/torrents/seeding"
    assert published["cfg"]["managed_roots"] == []


def test_run_refresh_passes_scan_hash_mode_and_drift_policy(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "catalog.db"
    db_path.write_text("")

    commands: list[list[str]] = []

    class _FakePopen:
        def __init__(self, cmd):
            commands.append(list(cmd))
            self.returncode = 0

        def poll(self):
            return self.returncode

    class _FakeRunLogger:
        def __init__(self, *args, **kwargs):
            self.verbose = False
            self.debug = False

        @contextmanager
        def patch_stdout(self):
            yield

        def write_raw(self, text: str) -> None:
            return None

        def record_step(self, *args, **kwargs) -> None:
            return None

        def dump_json(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def _fake_stream(cmd, heartbeat_s=30):
        commands.append(list(cmd))
        label = " ".join(cmd)
        if " payload sync " in f" {label} ":
            stdout = "upgrade_summary queued=0 started=0 completed=0 failed=0 elapsed_s=0\n"
            return auto_mod.subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr=""), stdout
        return auto_mod.subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), ""

    monkeypatch.setattr(auto_mod, "_validate_refresh_roots", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auto_mod,
        "_run_catalog_preflight",
        lambda *args, **kwargs: (
            True,
            {"ok": True, "checks": [], "summary": {"failed_error": 0, "failed_warning": 0, "total_checks": 1}},
        ),
    )
    monkeypatch.setattr(auto_mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(auto_mod, "_stream_subprocess_output", _fake_stream)
    monkeypatch.setattr("rehome.runlog.RunLogger", _FakeRunLogger)
    monkeypatch.setattr(
        "rehome.seed_state.publish_seed_root_state",
        lambda cfg=None, path=None: (Path("/tmp/seed-root-state.json"), {"writer": "hashall"}),
    )
    monkeypatch.setattr("rehome.cli._acquire_refresh_lock", lambda: _DummyLock())

    exit_code = auto_mod.run_refresh(
        catalog_path=db_path,
        active_root="/stash/media",
        dest_root="/pool/media/torrents/seeding",
        active_device="stash",
        dest_device="pool-media",
        workers=3,
        scan_hash_mode="full",
        drift_policy="quick",
        skip_dedup=True,
        managed_roots=[("/pool/data", "pool-data")],
        verbose=False,
        debug=False,
    )

    assert exit_code == 0

    scan_commands = [
        cmd for cmd in commands
        if len(cmd) >= 4 and cmd[:4] == [auto_mod.sys.executable, "-m", "hashall.cli", "scan"]
    ]
    assert scan_commands
    for cmd in scan_commands:
        assert "--hash-mode" in cmd
        assert cmd[cmd.index("--hash-mode") + 1] == "full"
        assert "--drift-policy" in cmd
        assert cmd[cmd.index("--drift-policy") + 1] == "quick"


def test_run_refresh_keeps_logger_open_while_patch_stdout_is_active(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "catalog.db"
    db_path.write_text("")

    class _FakePopen:
        def __init__(self, cmd):
            self.returncode = 0

        def poll(self):
            return self.returncode

    class _GuardedRunLogger:
        def __init__(self, *args, **kwargs):
            self.verbose = False
            self.debug = False
            self.closed = False

        @contextmanager
        def patch_stdout(self):
            if self.closed:
                raise RuntimeError("logger already closed")
            yield

        def write_raw(self, text: str) -> None:
            return None

        def record_step(self, *args, **kwargs) -> None:
            return None

        def dump_json(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True
            return None

    monkeypatch.setattr(auto_mod, "_validate_refresh_roots", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auto_mod,
        "_run_catalog_preflight",
        lambda *args, **kwargs: (
            True,
            {"ok": True, "checks": [], "summary": {"failed_error": 0, "failed_warning": 0, "total_checks": 1}},
        ),
    )
    monkeypatch.setattr(auto_mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(
        auto_mod,
        "_stream_subprocess_output",
        lambda cmd, heartbeat_s=30: (
            auto_mod.subprocess.CompletedProcess(
                cmd,
                0,
                stdout="upgrade_summary queued=0 started=0 completed=0 failed=0 elapsed_s=0\n",
                stderr="",
            ),
            "upgrade_summary queued=0 started=0 completed=0 failed=0 elapsed_s=0\n",
        ),
    )
    monkeypatch.setattr("rehome.runlog.RunLogger", _GuardedRunLogger)
    monkeypatch.setattr(
        "rehome.seed_state.publish_seed_root_state",
        lambda cfg=None, path=None: (Path("/tmp/seed-root-state.json"), {"writer": "hashall"}),
    )
    monkeypatch.setattr("rehome.cli._acquire_refresh_lock", lambda: _DummyLock())

    exit_code = auto_mod.run_refresh(
        catalog_path=db_path,
        active_root="/stash/media",
        dest_root="/pool/media/torrents/seeding",
        active_device="stash",
        dest_device="pool-media",
        workers=1,
        skip_dedup=True,
        managed_roots=[],
        verbose=False,
        debug=False,
    )

    assert exit_code == 0


def test_hashall_cli_run_header_includes_run_start_metadata(monkeypatch, capsys) -> None:
    import hashall.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_RUN_HEADER_EMITTED", False)
    monkeypatch.setattr(cli_mod, "_LOG_PATH", Path("/tmp/hashall.log"))
    monkeypatch.setattr(cli_mod.sys, "argv", ["hashall", "payload", "sync"])

    cli_mod._emit_run_header()
    out = capsys.readouterr().out
    assert "run_start pid=" in out
    assert "argv=payload sync" in out


def test_auto_cmd_preserves_explicit_source_root(monkeypatch, tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.db"
    catalog_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "DEFAULT_CATALOG_PATH", catalog_path)
    monkeypatch.setattr(
        config_mod,
        "load_config",
        lambda: {
            "catalog": str(catalog_path),
            "active_device": "stash",
            "default_dest_device": "pool-media",
            "default_dest_root": "/pool/media/torrents/seeding",
            "active_root": "/stash/media",
            "content_root": "/stash/media",
            "managed_roots": ["/pool/data:pool-data"],
        },
    )
    monkeypatch.setattr(config_mod, "parse_managed_roots", lambda _raw: [("/pool/data", "pool-data")])

    class _Conn:
        def close(self):
            return None

    from hashall import model as model_mod
    from hashall import device as device_mod
    monkeypatch.setattr(model_mod, "connect_db", lambda *args, **kwargs: _Conn())
    resolve_map = {"stash": 44, "pool-media": 141, "pool-data": 231}
    monkeypatch.setattr(device_mod, "resolve_device_id", lambda _conn, alias: resolve_map[alias])

    captured = {}

    def _fake_run_auto(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(auto_mod, "run_auto", _fake_run_auto)
    monkeypatch.setattr(auto_mod, "run_refresh", lambda **kwargs: 0)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["auto", "--from", "pool-data", "--to", "pool-media", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert captured["source_device_id"] == 231
    assert captured["extra_sources"] == [(231, "pool-data", "/pool/data")]


def test_run_catalog_preflight_reports_unknown_device_refs(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE devices (device_id INTEGER PRIMARY KEY, device_alias TEXT)")
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 999)")
    conn.commit()
    conn.close()

    ok, report = _run_catalog_preflight(Path(db_path))
    assert ok is False
    assert any(
        str(chk.get("name")) == "payload_device_refs_known" and not bool(chk.get("ok"))
        for chk in report.get("checks", [])
    )
