import json

from hashall.qb_cache import agent_main, daemon_main
from hashall.qbittorrent import QBitServerProfile


class _FakeQBClient:
    def get_server_profile(self, force_refresh=False):
        assert force_refresh is True
        return QBitServerProfile(
            app_version="5.0.4",
            webapi_version="2.11.4",
            qt_version="6.6.2",
            libtorrent_version="2.0.9.0",
        )

    def get_torrents_payload(self):
        return [{
            "hash": "abc123",
            "name": "Example",
            "save_path": "/pool/media/site",
            "content_path": "/pool/media/site/Example",
            "state": "stoppedUP",
            "state_raw": "pausedUP",
            "progress": 1.0,
        }]


def test_daemon_once_writes_normalized_cache_and_profile(tmp_path, monkeypatch):
    cache_file = tmp_path / "torrents-info.json"
    meta_file = tmp_path / "torrents-info.meta.json"
    lease_dir = tmp_path / "leases"
    pid_file = tmp_path / "daemon.pid"
    lock_file = tmp_path / "daemon.lock"

    monkeypatch.setattr("hashall.qb_cache.get_qbittorrent_client", lambda **_: _FakeQBClient())

    rc = daemon_main([
        "--once",
        "--cache-file", str(cache_file),
        "--meta-file", str(meta_file),
        "--lease-dir", str(lease_dir),
        "--pid-file", str(pid_file),
        "--lock-file", str(lock_file),
    ])
    assert rc == 0

    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload[0]["state"] == "stoppedUP"
    assert payload[0]["state_raw"] == "pausedUP"

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["items"] == 1
    assert meta["qb_profile"]["app_version"] == "5.0.4"
    assert meta["qb_profile"]["webapi_version"] == "2.11.4"


def test_agent_status_reports_meta_and_cache_age(tmp_path, capsys):
    cache_file = tmp_path / "torrents-info.json"
    meta_file = tmp_path / "torrents-info.meta.json"
    lease_dir = tmp_path / "leases"
    pid_file = tmp_path / "daemon.pid"

    cache_file.write_text("[]", encoding="utf-8")
    meta_file.write_text(
        json.dumps({
            "fetched_at": 10,
            "qb_profile": {"app_version": "5.0.4"},
        }),
        encoding="utf-8",
    )

    rc = agent_main([
        "--status",
        "--cache-file", str(cache_file),
        "--meta-file", str(meta_file),
        "--lease-dir", str(lease_dir),
        "--pid-file", str(pid_file),
    ])
    assert rc == 0

    status = json.loads(capsys.readouterr().out)
    assert status["cache_exists"] is True
    assert status["meta"]["qb_profile"]["app_version"] == "5.0.4"
