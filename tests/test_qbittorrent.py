from types import SimpleNamespace

import requests

from hashall.qbittorrent import QBittorrentClient, QBitFile, QBitTorrent


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
