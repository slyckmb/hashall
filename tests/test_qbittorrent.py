import json
from pathlib import Path
from types import SimpleNamespace

import requests

from hashall.qbittorrent import (
    DEFAULT_QB_CACHE_FILE,
    QBittorrentClient,
    QBitFile,
    QBitServerProfile,
    QBitTorrent,
    get_torrents_from_cache,
)


def test_get_torrent_root_path_prefers_content_path_without_files_api(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")

    def _unexpected_files_call(_hash):
        raise AssertionError("get_torrent_files should not be called when content_path is present")

    monkeypatch.setattr(client, "get_torrent_files", _unexpected_files_call)

    torrent = QBitTorrent(
        hash="abc",
        name="Torrent Name",
        save_path="/save",
        content_path="/data/media/item",
        category="",
        tags="",
        state="",
        size=0,
        progress=1.0,
    )

    root = client.get_torrent_root_path(torrent)
    assert root == "/data/media/item"
    assert client.root_path_files_fallback_calls == 0


def test_get_torrent_root_path_falls_back_to_files_api_for_single_file(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")

    monkeypatch.setattr(
        client,
        "get_torrent_files",
        lambda _hash: [QBitFile(name="movie.mkv", size=123)],
    )

    torrent = QBitTorrent(
        hash="abc",
        name="Torrent Name",
        save_path="/save",
        content_path="",
        category="",
        tags="",
        state="",
        size=0,
        progress=1.0,
    )

    root = client.get_torrent_root_path(torrent)
    assert root == "/save/movie.mkv"
    assert client.root_path_files_fallback_calls == 1


def test_get_torrent_info_retries_timeout_then_succeeds(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 2
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = {"count": 0}

    def fake_get(_url, params=None, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.Timeout("read timeout")
        assert params and params.get("hashes") == "abc123"
        return FakeResponse([{
            "hash": "abc123",
            "name": "name",
            "save_path": "/pool/data/seeds",
            "content_path": "/pool/data/seeds/name",
            "category": "",
            "tags": "",
            "state": "pausedUP",
            "size": 1,
            "progress": 1.0,
            "auto_tmm": False,
        }])

    monkeypatch.setattr(client.session, "get", fake_get)
    info = client.get_torrent_info("abc123")
    assert info is not None
    assert info.save_path == "/pool/data/seeds"
    assert calls["count"] == 2


def test_get_torrent_info_sets_last_error_after_retry_exhaustion(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 2
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def fake_get(_url, params=None, timeout=None):
        raise requests.Timeout("still timed out")

    monkeypatch.setattr(client.session, "get", fake_get)
    info = client.get_torrent_info("deadbeef")
    assert info is None
    assert client.last_error is not None
    assert "timed out" in client.last_error


def test_set_location_retries_transient_connection_with_exponential_backoff(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 3
    client.retry_backoff_base = 0.25
    client.retry_backoff_cap = 8.0
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)

    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    class FakeResponse:
        def raise_for_status(self):
            return None

    calls = {"count": 0}

    def fake_post(_url, data=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.ConnectionError("temporary overload")
        assert data and data.get("hashes") == "abc123"
        assert data.get("location") == "/pool/data/seeds/site"
        return FakeResponse()

    monkeypatch.setattr(client.session, "post", fake_post)
    ok = client.set_location("abc123", "/pool/data/seeds/site")
    assert ok is True
    assert calls["count"] == 3
    assert sleeps == [0.25, 0.5]


def test_is_reachable_uses_login_when_not_authenticated(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    calls = {"count": 0}

    def fake_login():
        calls["count"] += 1
        client._authenticated = True
        return True

    monkeypatch.setattr(client, "login", fake_login)

    assert client.is_reachable() is True
    assert calls["count"] == 1


def test_login_retries_transient_connection_failures(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 3
    client.retry_backoff_base = 0.25
    client.retry_backoff_cap = 8.0

    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    class FakeResponse:
        text = "Ok."

    calls = {"count": 0}

    def fake_post(_url, data=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.ConnectionError("temporary login reset")
        assert data == {"username": "u", "password": "p"}
        return FakeResponse()

    monkeypatch.setattr(client.session, "post", fake_post)

    assert client.login() is True
    assert client._authenticated is True
    assert client.last_error is None
    assert calls["count"] == 3
    assert sleeps == [0.25, 0.5]


def test_login_prints_warning_only_after_retry_exhaustion(monkeypatch, capsys):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 2
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    calls = {"count": 0}

    def fake_post(_url, data=None, timeout=None):
        calls["count"] += 1
        raise requests.ConnectionError("still unavailable")

    monkeypatch.setattr(client.session, "post", fake_post)

    assert client.login() is False
    assert client._authenticated is False
    assert calls["count"] == 2
    captured = capsys.readouterr()
    assert captured.out.count("qBittorrent login failed") == 1
    assert "still unavailable" in client.last_error


def test_is_reachable_reauthenticates_on_forbidden(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client._authenticated = True

    class FakeForbidden:
        status_code = 403
        text = "Forbidden"

        def raise_for_status(self):
            raise requests.HTTPError("forbidden", response=self)

    def fake_get(_url, timeout=None):
        return FakeForbidden()

    calls = {"count": 0}

    def fake_login():
        calls["count"] += 1
        client._authenticated = True
        return True

    monkeypatch.setattr(client.session, "get", fake_get)
    monkeypatch.setattr(client, "login", fake_login)

    assert client.is_reachable() is True
    assert calls["count"] == 1


def test_get_server_profile_collects_optional_endpoints(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)

    class FakeResponse:
        def __init__(self, text="", payload=None, status_code=200):
            self.text = text
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError("boom", response=self)

        def json(self):
            return self._payload

    calls = []

    def fake_get(url, timeout=None):
        calls.append(Path(url).name)
        if url.endswith("/api/v2/app/version"):
            return FakeResponse(text="5.0.4")
        if url.endswith("/api/v2/app/webapiVersion"):
            return FakeResponse(text="2.11.4")
        if url.endswith("/api/v2/app/buildInfo"):
            return FakeResponse(payload={"qt": "6.6.2", "libtorrent": "2.0.9.0"})
        raise AssertionError(url)

    monkeypatch.setattr(client.session, "get", fake_get)

    profile = client.get_server_profile()
    assert isinstance(profile, QBitServerProfile)
    assert profile.app_version == "5.0.4"
    assert profile.webapi_version == "2.11.4"
    assert profile.qt_version == "6.6.2"
    assert profile.libtorrent_version == "2.0.9.0"
    assert calls == ["version", "webapiVersion", "buildInfo"]


def test_get_server_profile_falls_back_to_cached_meta(monkeypatch, tmp_path):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.cache_meta_file = tmp_path / "torrents-info.meta.json"
    client.cache_meta_file.write_text(
        json.dumps(
            {
                "qb_profile": {
                    "app_version": "4.4.5",
                    "webapi_version": "2.8.5",
                    "qt_version": "6.4.1",
                    "libtorrent_version": "1.2.18.0",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(client, "_get_optional_text", lambda _endpoint: None)
    monkeypatch.setattr(client, "_get_optional_json", lambda _endpoint: None)

    profile = client.get_server_profile(force_refresh=True)

    assert profile.app_version == "4.4.5"
    assert profile.webapi_version == "2.8.5"


def test_get_torrent_info_falls_back_to_cache_on_timeout(monkeypatch, tmp_path):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.request_retries = 1
    client.cache_file = tmp_path / "torrents-info.json"
    client.cache_file.write_text(
        json.dumps(
            [
                {
                    "hash": "abc123",
                    "name": "Movie.mkv",
                    "save_path": "/pool/media/site",
                    "content_path": "/pool/media/site/Movie.mkv",
                    "state": "pausedUP",
                    "progress": 1.0,
                    "size": 100,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)

    def fake_get(_url, params=None, timeout=None):
        raise requests.Timeout("read timeout")

    monkeypatch.setattr(client.session, "get", fake_get)

    info = client.get_torrent_info("abc123")

    assert info is not None
    assert info.hash == "abc123"
    assert info.state == "stoppedUP"
    assert client.last_error is not None
    assert client.last_error.startswith("cache_fallback:")


def test_export_torrent_file_falls_back_to_bt_backup_on_404(monkeypatch, tmp_path):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.bt_backup_dir = tmp_path / "BT_backup"
    client.bt_backup_dir.mkdir()
    backup_torrent = client.bt_backup_dir / "abc123.torrent"
    backup_torrent.write_bytes(b"torrent-bytes")
    out_path = tmp_path / "exported" / "abc123.torrent"
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)

    class FakeResponse:
        status_code = 404
        text = "Not Found"

        def raise_for_status(self):
            raise requests.HTTPError("boom", response=self)

    monkeypatch.setattr(client.session, "get", lambda *_args, **_kwargs: FakeResponse())

    blob = client.export_torrent_file("abc123", out_path=out_path)

    assert blob == b"torrent-bytes"
    assert out_path.read_bytes() == b"torrent-bytes"


def test_export_torrent_file_uses_bt_backup_when_auth_fails(monkeypatch, tmp_path):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    client.bt_backup_dir = tmp_path / "BT_backup"
    client.bt_backup_dir.mkdir()
    backup_torrent = client.bt_backup_dir / "abc123.torrent"
    backup_torrent.write_bytes(b"torrent-bytes")

    def fail_auth():
        raise RuntimeError("Failed to authenticate with qBittorrent")

    monkeypatch.setattr(client, "_ensure_authenticated", fail_auth)

    blob = client.export_torrent_file("abc123")

    assert blob == b"torrent-bytes"


def test_get_torrents_from_cache_defaults_to_hashall_cache_path(monkeypatch, tmp_path):
    cache_file = tmp_path / "torrents-info.json"
    cache_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("hashall.qbittorrent.DEFAULT_QB_CACHE_FILE", cache_file)

    payload = get_torrents_from_cache(max_age_s=30.0)

    assert payload == []


def test_get_torrents_normalizes_pause_alias_and_derives_content_path(monkeypatch):
    client = QBittorrentClient(base_url="http://example", username="u", password="p")
    monkeypatch.setattr(client, "_ensure_authenticated", lambda: None)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [{
                "hash": "abc123",
                "name": "Movie.mkv",
                "save_path": "/pool/media/torrents/seeding/site",
                "content_path": "",
                "state": "pausedDL",
                "progress": 0.42,
                "size": 100,
                "added_on": 123,
            }]

    monkeypatch.setattr(client.session, "get", lambda url, params=None, timeout=None: FakeResponse())

    torrents = client.get_torrents()
    assert len(torrents) == 1
    torrent = torrents[0]
    assert torrent.state == "stoppedDL"
    assert torrent.state_raw == "pausedDL"
    assert torrent.content_path == "/pool/media/torrents/seeding/site/Movie.mkv"
    assert torrent.added_on == 123
