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
