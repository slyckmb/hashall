import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "qb-verify-hash.py"
SPEC = importlib.util.spec_from_file_location("qb_verify_hash", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_collect_candidate_paths_prefers_distinct_qb_hints() -> None:
    qb = SimpleNamespace(get_torrent_root_path=lambda torrent: "/pool/media/root/file.mkv")
    torrent = SimpleNamespace(
        name="Example.mkv",
        content_path="/pool/media/root/file.mkv",
        save_path="/pool/media/root",
    )

    out = MODULE.collect_candidate_paths(
        qb,
        torrent,
        include_qb_paths=True,
        content_path_only=False,
        save_path_only=False,
        extra_paths=["/pool/media/root/file.mkv", "/alt/path"],
        path_maps=[],
    )

    assert [item["path"] for item in out] == [
        "/pool/media/root/file.mkv",
        "/pool/media/root",
        "/pool/media/root/Example.mkv",
        "/alt/path",
    ]
    assert [item["source"] for item in out] == [
        "qb_content_path",
        "qb_save_path",
        "qb_save_path_plus_name",
        "user_path",
    ]


def test_collect_candidate_paths_honors_content_path_only() -> None:
    qb = SimpleNamespace(get_torrent_root_path=lambda torrent: "/pool/media/root/file.mkv")
    torrent = SimpleNamespace(
        name="Example.mkv",
        content_path="/pool/media/root/file.mkv",
        save_path="/pool/media/root",
    )

    out = MODULE.collect_candidate_paths(
        qb,
        torrent,
        include_qb_paths=True,
        content_path_only=True,
        save_path_only=False,
        extra_paths=[],
        path_maps=[],
    )

    assert [item["path"] for item in out] == ["/pool/media/root/file.mkv"]


def test_collect_candidate_paths_applies_path_maps() -> None:
    qb = SimpleNamespace(get_torrent_root_path=lambda torrent: "/incomplete_torrents/NOAH_HDCLUB")
    torrent = SimpleNamespace(
        name="NOAH_HDCLUB",
        content_path="/incomplete_torrents/NOAH_HDCLUB",
        save_path="/data/media/torrents/seeding/privatehd",
    )

    out = MODULE.collect_candidate_paths(
        qb,
        torrent,
        include_qb_paths=True,
        content_path_only=False,
        save_path_only=False,
        extra_paths=[],
        path_maps=[("/incomplete_torrents", "/dump/torrents/incomplete_vpn")],
    )

    assert [item["path"] for item in out] == [
        "/dump/torrents/incomplete_vpn/NOAH_HDCLUB",
        "/data/media/torrents/seeding/privatehd",
        "/data/media/torrents/seeding/privatehd/NOAH_HDCLUB",
    ]
    assert out[0]["mapped"] is True
    assert out[0]["source"] == "qb_content_path"


def test_effective_path_maps_adds_auto_defaults() -> None:
    out = MODULE.effective_path_maps([], include_auto=True)
    assert ("/incomplete_torrents", "/dump/torrents/incomplete_vpn") in out


def test_determine_exit_code_compare_all_requires_every_candidate_verified() -> None:
    report = {
        "summary": {"verified_candidates": 1},
        "verifier_report": {
            "results": [
                {"verified": True},
                {"verified": False},
            ]
        },
    }

    assert MODULE.determine_exit_code(0, report, compare_all=True) == 1
    assert MODULE.determine_exit_code(0, report, compare_all=False) == 0


def test_main_writes_wrapper_json_and_uses_verifier_report(monkeypatch, tmp_path) -> None:
    exported = tmp_path / "exported.torrent"
    verifier_json = tmp_path / "verifier.json"
    wrapper_json = tmp_path / "wrapper.json"

    class FakeQB:
        def __init__(self, *args, **kwargs):
            pass

        def get_torrent_info(self, torrent_hash):
            return SimpleNamespace(
                hash=torrent_hash,
                name="Example.mkv",
                save_path="/pool/media/root",
                content_path="/pool/media/root/Example.mkv",
                category="movies",
                tags="",
                state="stalledUP",
                size=123,
                progress=1.0,
                auto_tmm=False,
                amount_left=0,
                completed=123,
                downloaded=123,
                completion_on=0,
            )

        def get_torrent_root_path(self, torrent):
            return torrent.content_path

        def export_torrent_file(self, torrent_hash, out_path=None):
            assert out_path is not None
            Path(out_path).write_bytes(b"torrent")
            return b"torrent"

    monkeypatch.setattr(MODULE, "QBittorrentClient", FakeQB)

    def fake_export(qb, torrent_hash, requested_out):
        exported.write_bytes(b"torrent")
        return exported, False

    def fake_run(verifier_script, torrent_file, candidate_paths, args, verifier_json_path):
        verifier_json_path.write_text(
            '{"summary":{"verified":1,"partial":0,"best_classification":"exact_tree","best_path":"/pool/media/root/Example.mkv"},"results":[{"verified":true,"path":"/pool/media/root/Example.mkv"}]}',
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(MODULE, "export_torrent_file", fake_export)
    monkeypatch.setattr(MODULE, "run_verifier", fake_run)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qb-verify-hash.py",
            "abc123",
            "--json-out",
            str(wrapper_json),
            "--torrent-out",
            str(exported),
        ],
    )

    rc = MODULE.main()

    assert rc == 0
    payload = MODULE.load_json(wrapper_json)
    assert payload["hash"] == "abc123"
    assert payload["summary"]["best_classification"] == "exact_tree"
    assert payload["candidate_paths"] == [
        "/pool/media/root/Example.mkv",
        "/pool/media/root",
    ]
    assert payload["candidate_details"][0]["source"] == "qb_content_path"
    assert payload["path_maps"] == [{"from": "/incomplete_torrents", "to": "/dump/torrents/incomplete_vpn"}]
