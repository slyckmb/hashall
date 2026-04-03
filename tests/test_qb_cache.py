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
            "tracker": "http://tracker.example:8080/announce",
            "trackers_count": 2,
            "magnet_uri": (
                "magnet:?xt=urn:btih:abc123"
                "&tr=http%3A%2F%2Ftracker.example%3A8080%2Fannounce"
                "&tr=https%3A%2F%2Fbackup.example%2Fannounce"
            ),
        }]

    def enrich_torrents_payload_with_trackers(self, torrents):
        enriched = []
        for row in torrents:
            payload = dict(row)
            payload["tracker_urls"] = [
                "http://tracker.example:8080/announce",
                "https://backup.example/announce",
            ]
            payload["tracker_urls_http"] = list(payload["tracker_urls"])
            payload["primary_tracker"] = "http://tracker.example:8080/announce"
            payload["real_trackers_count"] = 2
            payload["tracker_domains"] = ["tracker.example", "backup.example"]
            payload["tracker_enrichment_source"] = "magnet_uri"
            enriched.append(payload)
        return enriched, {
            "mode": "magnet_uri_with_fastresume_fallback",
            "sources": {"magnet_uri": 1},
            "fallback_rows": 0,
        }


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
    assert payload[0]["tracker_urls"] == [
        "http://tracker.example:8080/announce",
        "https://backup.example/announce",
    ]
    assert payload[0]["tracker_urls_http"] == payload[0]["tracker_urls"]
    assert payload[0]["primary_tracker"] == "http://tracker.example:8080/announce"
    assert payload[0]["trackers_count"] == 2
    assert payload[0]["real_trackers_count"] == 2
    assert payload[0]["tracker_domains"] == ["tracker.example", "backup.example"]
    assert payload[0]["tracker_enrichment_source"] == "magnet_uri"

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["items"] == 1
    assert meta["qb_profile"]["app_version"] == "5.0.4"
    assert meta["qb_profile"]["webapi_version"] == "2.11.4"
    assert meta["tracker_enrichment"]["mode"] == "magnet_uri_with_fastresume_fallback"
    assert meta["tracker_enrichment"]["sources"] == {"magnet_uri": 1}


def test_daemon_once_resets_consecutive_failures_on_success(tmp_path, monkeypatch):
    """Successful fetch must zero out consecutive_failures even when previous meta had failures."""
    cache_file = tmp_path / "torrents-info.json"
    meta_file = tmp_path / "torrents-info.meta.json"
    lease_dir = tmp_path / "leases"
    pid_file = tmp_path / "daemon.pid"
    lock_file = tmp_path / "daemon.lock"

    # Simulate a meta file left behind after N consecutive failures
    meta_file.write_text(
        json.dumps({"consecutive_failures": 42, "last_error": "connection refused"}),
        encoding="utf-8",
    )

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

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["consecutive_failures"] == 0, (
        "consecutive_failures must be reset to 0 after a successful fetch"
    )
    assert meta["last_error"] == "", "last_error must be cleared after a successful fetch"


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
