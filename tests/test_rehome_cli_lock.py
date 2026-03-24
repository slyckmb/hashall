from pathlib import Path

import pytest

from rehome import cli as cli_mod


def test_acquire_rehome_lock_writes_holder_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("rehome.cli.fcntl.flock", lambda *_args, **_kwargs: None)

    lock_fh = cli_mod._acquire_rehome_lock()
    try:
        content = (tmp_path / ".hashall" / "rehome.lock").read_text(encoding="utf-8")
    finally:
        lock_fh.close()

    assert "pid=" in content
    assert "host=" in content
    assert "started_at=" in content
    assert "cwd=" in content


def test_acquire_rehome_lock_reports_existing_holder_metadata(tmp_path, monkeypatch, capsys):
    lock_dir = tmp_path / ".hashall"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "rehome.lock"
    lock_path.write_text(
        "pid=4242\nhost=testbox\nstarted_at=2026-03-11T22:00:00-04:00\ncwd=/tmp/run\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_flock(*_args, **_kwargs):
        raise OSError("busy")

    monkeypatch.setattr("rehome.cli.fcntl.flock", fake_flock)

    with pytest.raises(SystemExit):
        cli_mod._acquire_rehome_lock()

    err = capsys.readouterr().err
    assert "Another rehome apply is already running" in err
    assert "pid=4242" in err
    assert "host=testbox" in err


def test_acquire_refresh_lock_reports_existing_holder_metadata(tmp_path, monkeypatch, capsys):
    lock_dir = tmp_path / ".hashall"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "refresh.lock"
    lock_path.write_text(
        "pid=5150\nhost=testbox\nstarted_at=2026-03-13T13:00:00-04:00\ncwd=/tmp/run\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(tmp_path))

    def fake_flock(*_args, **_kwargs):
        raise OSError("busy")

    monkeypatch.setattr("rehome.cli.fcntl.flock", fake_flock)

    with pytest.raises(SystemExit):
        cli_mod._acquire_refresh_lock()

    err = capsys.readouterr().err
    assert "Another hashall refresh is already running" in err
    assert "pid=5150" in err


def test_acquire_refresh_lock_rejects_live_refresh_even_after_lock_recreated(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("rehome.cli.fcntl.flock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "rehome.cli._iter_other_refresh_holders",
        lambda: [
            {
                "pid": 203069,
                "cwd": "/home/michael/dev/work/hashall/.agent/worktrees/cr-hashall-20260319-130301-codex",
                "cmdline": [
                    "/home/michael/.venvs/hashall/bin/python",
                    "/home/michael/.venvs/hashall/bin/hashall",
                    "refresh",
                    "--verbose",
                ],
            }
        ],
    )

    with pytest.raises(SystemExit):
        cli_mod._acquire_refresh_lock()

    err = capsys.readouterr().err
    assert "Another hashall refresh process is already running" in err
    assert "pid=203069" in err
    assert "hashall refresh --verbose" in err
