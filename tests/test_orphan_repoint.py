"""Tests for hashall orphan-repoint."""

from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.orphan_repoint import (
    OrphanRef,
    _is_orphan_path,
    resolve_canonical_path,
    repoint_rt,
    repoint_qb,
    run_orphan_repoint,
    scan_rt,
    scan_qb,
    build_qb_lookup,
)
from hashall.rtorrent import RTSessionEntry


# ── _is_orphan_path ──────────────────────────────────────────────────────────


def test_is_orphan_path_matches_pool_prefix():
    assert _is_orphan_path("/pool/media/torrents/orphans/some/dir")


def test_is_orphan_path_matches_pool_prefix_exact():
    assert _is_orphan_path("/pool/media/torrents/orphans")


def test_is_orphan_path_matches_alt_prefix():
    assert _is_orphan_path("/data/media/torrents/orphans/some/dir")


def test_is_orphan_path_rejects_non_orphan():
    assert not _is_orphan_path("/pool/media/torrents/seeding/movies/Film")


def test_is_orphan_path_rejects_empty():
    assert not _is_orphan_path("")


def test_is_orphan_path_rejects_none_prefix():
    assert not _is_orphan_path("/stash/media/torrents/orphans/some")


def test_is_orphan_path_trailing_slash():
    assert _is_orphan_path("/pool/media/torrents/orphans/His.Three.Daughters.2024/")
    assert not _is_orphan_path("/pool/media/torrents/seeding/movies/")


# ── scan_rt ──────────────────────────────────────────────────────────────────


def test_scan_rt_finds_orphan_entries(monkeypatch):
    fake_entries = {
        "f37b9983": RTSessionEntry(
            torrent_hash="f37b9983",
            directory="/pool/media/torrents/orphans/His.Three.Daughters.2024",
            path_exists=False,
        ),
        "abc12345": RTSessionEntry(
            torrent_hash="abc12345",
            directory="/pool/media/torrents/seeding/movies/Some.Movie.2025",
            path_exists=True,
        ),
    }
    monkeypatch.setattr(
        "hashall.orphan_repoint.load_rt_session_directories",
        lambda *a, **kw: fake_entries,
    )
    hits = scan_rt()
    assert len(hits) == 1
    assert hits[0].torrent_hash == "f37b9983"
    assert hits[0].source == "RT"
    assert "orphans" in hits[0].current_path


def test_scan_rt_returns_empty_when_no_orphans(monkeypatch):
    fake_entries = {
        "xyz789": RTSessionEntry(
            torrent_hash="xyz789",
            directory="/pool/media/torrents/seeding/tv/Show",
            path_exists=True,
        ),
    }
    monkeypatch.setattr(
        "hashall.orphan_repoint.load_rt_session_directories",
        lambda *a, **kw: fake_entries,
    )
    assert scan_rt() == []


# ── scan_qb ──────────────────────────────────────────────────────────────────


def test_scan_qb_finds_orphan_entries_from_cache(monkeypatch):
    fake_cache = [
        {"hash": "qbhash01", "name": "Movie.One.2025", "save_path": "/pool/media/torrents/orphans/Movie.One.2025"},
        {"hash": "qbhash02", "name": "Movie.Two.2025", "save_path": "/pool/media/torrents/seeding/movies/Movie.Two.2025"},
    ]
    monkeypatch.setattr("hashall.orphan_repoint.get_torrents_from_cache", lambda **_: fake_cache)
    hits = scan_qb()
    assert len(hits) == 1
    assert hits[0].torrent_hash == "qbhash01"
    assert hits[0].source == "qB"


def test_scan_qb_finds_orphan_entries_from_live(monkeypatch):
    class FakeTorrent:
        hash = "live01"
        name = "Live.Movie"
        save_path = "/pool/media/torrents/orphans/Live.Movie"
    monkeypatch.setattr("hashall.orphan_repoint.get_torrents_from_cache", lambda **_: None)
    monkeypatch.setattr("hashall.orphan_repoint.QBittorrentClient", lambda: type("FakeClient", (), {"get_torrents": lambda self: [FakeTorrent()]})())
    hits = scan_qb()
    assert len(hits) == 1
    assert hits[0].torrent_hash == "live01"
    assert hits[0].source == "qB"


# ── resolve_canonical_path ───────────────────────────────────────────────────


def test_resolve_canonical_path_for_qb_with_qb_lookup(monkeypatch):
    ref = OrphanRef(
        torrent_hash="abc123",
        name="Test Movie",
        source="qB",
        current_path="/pool/media/torrents/orphans/Test.Movie.2025",
        canonical_path=None,
    )
    qb_lookup = {
        "abc123": {
            "hash": "abc123",
            "name": "Test Movie",
            "save_path": "/pool/media/torrents/orphans/Test.Movie.2025",
            "content_path": "/pool/media/torrents/orphans/Test.Movie.2025",
            "category": "movies",
            "tags": "~noHL",
        }
    }
    monkeypatch.setattr(
        "hashall.orphan_repoint.infer_canonical_save_path",
        lambda **kwargs: type("Inferred", (), {
            "canonical_save_path": "/pool/media/torrents/seeding/movies/Test.Movie.2025",
            "reliability": "reliable",
        })(),
    )
    result = resolve_canonical_path(ref, qb_lookup=qb_lookup)
    assert result == "/pool/media/torrents/seeding/movies/Test.Movie.2025"


def test_resolve_canonical_path_for_rt_via_qb_mirror(monkeypatch):
    ref = OrphanRef(
        torrent_hash="f37b9983",
        name="His.Three.Daughters.2024",
        source="RT",
        current_path="/pool/media/torrents/orphans/His.Three.Daughters.2024",
        canonical_path=None,
    )
    qb_lookup = {
        "f37b9983": {
            "hash": "f37b9983",
            "name": "His.Three.Daughters.2024",
            "save_path": "/pool/media/torrents/orphans/His.Three.Daughters.2024",
            "content_path": "/pool/media/torrents/orphans/His.Three.Daughters.2024",
            "category": "movies",
            "tags": "~noHL",
        }
    }
    monkeypatch.setattr(
        "hashall.orphan_repoint.infer_canonical_save_path",
        lambda **kwargs: type("Inferred", (), {
            "canonical_save_path": "/pool/media/torrents/seeding/movies/His.Three.Daughters.2024",
            "reliability": "reliable",
        })(),
    )
    result = resolve_canonical_path(ref, qb_lookup=qb_lookup)
    assert result == "/pool/media/torrents/seeding/movies/His.Three.Daughters.2024"


def test_resolve_canonical_path_returns_none_when_ambiguous(monkeypatch):
    ref = OrphanRef(
        torrent_hash="abc123",
        name="Unknown",
        source="qB",
        current_path="/pool/media/torrents/orphans/Unknown",
        canonical_path=None,
    )
    monkeypatch.setattr(
        "hashall.orphan_repoint.infer_canonical_save_path",
        lambda **kwargs: type("Inferred", (), {
            "canonical_save_path": "",
            "reliability": "ambiguous",
        })(),
    )
    result = resolve_canonical_path(ref, qb_lookup={})
    assert result is None


# ── repoint_rt ───────────────────────────────────────────────────────────────


def test_repoint_rt_calls_apply_repoint(monkeypatch):
    called = {}
    def fake_repoint(torrent_hash, target_directory, *, rpc_url, restart, check_before_start):
        called.update(hash=torrent_hash, target=target_directory, rpc=rpc_url)
        return ["ok"]
    monkeypatch.setattr("hashall.orphan_repoint.rt_apply_directory_repoint", fake_repoint)

    ref = OrphanRef(
        torrent_hash="f37b9983",
        name="His.Three.Daughters.2024",
        source="RT",
        current_path="/pool/media/torrents/orphans/His.Three.Daughters.2024",
        canonical_path="/pool/media/torrents/seeding/movies/His.Three.Daughters.2024",
    )
    ok = repoint_rt(ref, rpc_url="http://test:18000/")
    assert ok
    assert called["hash"] == "f37b9983"
    assert called["target"] == "/pool/media/torrents/seeding/movies/His.Three.Daughters.2024"
    assert called["rpc"] == "http://test:18000/"


def test_repoint_rt_returns_false_without_canonical_path():
    ref = OrphanRef(
        torrent_hash="abc", name="Test", source="RT",
        current_path="/orphans/x", canonical_path=None,
    )
    assert not repoint_rt(ref)


def test_repoint_rt_returns_false_on_exception(monkeypatch):
    def fake_repoint(**kwargs):
        raise RuntimeError("fail")
    monkeypatch.setattr("hashall.orphan_repoint.rt_apply_directory_repoint", fake_repoint)

    ref = OrphanRef(
        torrent_hash="abc", name="Test", source="RT",
        current_path="/orphans/x", canonical_path="/pool/media/seeding/movies/Test",
    )
    assert not repoint_rt(ref)


# ── repoint_qb ───────────────────────────────────────────────────────────────


def test_repoint_qb_calls_set_location(monkeypatch):
    called = {}
    class FakeClient:
        def set_location(self, hash, new_location, resume_after=True):
            called.update(hash=hash, location=new_location)
            return True
    monkeypatch.setattr("hashall.orphan_repoint.QBittorrentClient", lambda: FakeClient())

    ref = OrphanRef(
        torrent_hash="qb001", name="Movie", source="qB",
        current_path="/orphans/Movie", canonical_path="/pool/media/seeding/movies/Movie",
    )
    ok = repoint_qb(ref)
    assert ok
    assert called["hash"] == "qb001"
    assert called["location"] == "/pool/media/seeding/movies/Movie"


def test_repoint_qb_returns_false_without_canonical_path():
    ref = OrphanRef(
        torrent_hash="abc", name="Test", source="qB",
        current_path="/orphans/x", canonical_path=None,
    )
    assert not repoint_qb(ref)


def test_repoint_qb_returns_false_on_exception(monkeypatch):
    class FakeClient:
        def set_location(self, hash, new_location, resume_after=True):
            raise RuntimeError("fail")
    monkeypatch.setattr("hashall.orphan_repoint.QBittorrentClient", lambda: FakeClient())

    ref = OrphanRef(
        torrent_hash="abc", name="Test", source="qB",
        current_path="/orphans/x", canonical_path="/pool/media/seeding/movies/Test",
    )
    assert not repoint_qb(ref)


# ── run_orphan_repoint (integration-ish) ─────────────────────────────────────


def test_run_orphan_repoint_dry_run_scans_and_resolves(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.load_rt_session_directories",
        lambda *a, **kw: {
            "f37b9983": RTSessionEntry(
                torrent_hash="f37b9983",
                directory="/pool/media/torrents/orphans/His.Three.Daughters.2024",
                path_exists=False,
            ),
        },
    )
    monkeypatch.setattr(
        "hashall.orphan_repoint.get_torrents_from_cache",
        lambda *a, **kw: [
            {
                "hash": "qb001",
                "name": "Other.Orphan",
                "save_path": "/pool/media/torrents/orphans/Other.Orphan",
            },
            {
                "hash": "qb002",
                "name": "Clean",
                "save_path": "/pool/media/torrents/seeding/movies/Clean",
            },
        ],
    )
    monkeypatch.setattr(
        "hashall.orphan_repoint.infer_canonical_save_path",
        lambda **kwargs: type("Inferred", (), {
            "canonical_save_path": "/pool/media/torrents/seeding/movies/" + kwargs.get("category", "unknown"),
            "reliability": "reliable",
        })(),
    )

    summary = run_orphan_repoint(dry_run=True)
    assert summary["dry_run"] is True
    assert summary["total_orphan_refs"] == 2
    assert summary["rt_scanned"] == 1
    assert summary["qb_scanned"] == 1
    for r in summary["results"]:
        assert r["action"] == "dry_run" or r["action"] == "no_canonical_path"


def test_run_orphan_repoint_all_clear_when_no_orphans(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.load_rt_session_directories",
        lambda *a, **kw: {},
    )
    monkeypatch.setattr(
        "hashall.orphan_repoint.get_torrents_from_cache",
        lambda *a, **kw: [],
    )
    summary = run_orphan_repoint(dry_run=True)
    assert summary["total_orphan_refs"] == 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_orphan_repoint_cli_dry_run(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.run_orphan_repoint",
        lambda **kwargs: {
            "dry_run": True,
            "rt_scanned": 1,
            "qb_scanned": 1,
            "total_orphan_refs": 2,
            "rt_repointed": 0,
            "qb_repointed": 0,
            "failed": 0,
            "results": [
                {
                    "torrent_hash": "f37b9983",
                    "name": "His.Three.Daughters.2024",
                    "source": "RT",
                    "current_path": "/pool/media/torrents/orphans/His.Three.Daughters.2024",
                    "canonical_path": "/pool/media/torrents/seeding/movies/His.Three.Daughters.2024",
                    "action": "dry_run",
                },
            ],
        },
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["orphan", "repoint"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert "f37b9983" in result.output


def test_orphan_repoint_cli_execute(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.run_orphan_repoint",
        lambda **kwargs: {
            "dry_run": False,
            "rt_scanned": 0,
            "qb_scanned": 0,
            "total_orphan_refs": 0,
            "rt_repointed": 0,
            "qb_repointed": 0,
            "failed": 0,
            "results": [],
        },
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["orphan", "repoint", "--execute"])
    assert result.exit_code == 0
    assert "EXECUTION" in result.output
    assert "All clear" in result.output


# ── build_qb_lookup ──────────────────────────────────────────────────────────


def test_orphan_repoint_cli_execute_without_hash_filters_fails():
    runner = CliRunner()
    result = runner.invoke(cli, ["orphan", "repoint", "--execute"])
    assert result.exit_code != 0
    assert "require explicit hash filters" in result.output


def test_orphan_repoint_cli_execute_with_hash_filters_succeeds_and_filters(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.run_orphan_repoint",
        lambda **kwargs: {
            "dry_run": False,
            "rt_scanned": 1,
            "qb_scanned": 0,
            "total_orphan_refs": 1,
            "rt_repointed": 1,
            "qb_repointed": 0,
            "failed": 0,
            "results": [
                {
                    "torrent_hash": "f37b9983",
                    "name": "His.Three.Daughters.2024",
                    "source": "RT",
                    "current_path": "/pool/media/torrents/orphans/His.Three.Daughters.2024",
                    "canonical_path": "/pool/media/torrents/seeding/movies/His.Three.Daughters.2024",
                    "action": "repointed_rt",
                },
            ],
        },
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["orphan", "repoint", "--execute", "--hash", "f37b"])
    assert result.exit_code == 0
    assert "EXECUTION" in result.output
    assert "f37b9983" in result.output
    assert "RT repointed: 1" in result.output


def test_build_qb_lookup_from_cache(monkeypatch):
    monkeypatch.setattr(
        "hashall.orphan_repoint.get_torrents_from_cache",
        lambda **_: [
            {"hash": "ABC123", "name": "Test"},
            {"hash": "DEF456", "name": "Test2"},
        ],
    )
    lookup = build_qb_lookup()
    assert "abc123" in lookup
    assert lookup["abc123"]["hash"] == "ABC123"
    assert "def456" in lookup
