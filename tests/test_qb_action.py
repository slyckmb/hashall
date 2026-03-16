from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "qb-action.py"

spec = importlib.util.spec_from_file_location("qb_action", MODULE_PATH)
qb_action = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(qb_action)


class DummyClient:
    def __init__(self, *, resume_ok: bool = True, pause_ok: bool = True):
        self.resume_ok = resume_ok
        self.pause_ok = pause_ok
        self.resume_calls: list[list[str]] = []
        self.pause_calls: list[list[str]] = []
        self.last_error = "dummy_error"

    def resume_torrents(self, hashes):
        self.resume_calls.append(list(hashes))
        return self.resume_ok

    def pause_torrents(self, hashes):
        self.pause_calls.append(list(hashes))
        return self.pause_ok


def test_split_hashes_filters_empty_parts():
    assert qb_action._split_hashes("AA||bb| |CC") == ["aa", "bb", "cc"]


def test_main_uses_resume_torrents(monkeypatch, capsys):
    client = DummyClient()
    monkeypatch.setattr(qb_action, "get_qbittorrent_client", lambda **kwargs: client)

    rc = qb_action.main(["resume", "AA|bb"])

    assert rc == 0
    assert client.resume_calls == [["aa", "bb"]]
    assert capsys.readouterr().out.strip() == "resume ok hashes=2"


def test_main_reports_pause_failure(monkeypatch, capsys):
    client = DummyClient(pause_ok=False)
    monkeypatch.setattr(qb_action, "get_qbittorrent_client", lambda **kwargs: client)

    rc = qb_action.main(["pause", "AA"])

    assert rc == 1
    assert client.pause_calls == [["aa"]]
    assert "pause failed hashes=1 last_error=dummy_error" in capsys.readouterr().err
