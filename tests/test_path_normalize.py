from pathlib import Path

from click.testing import CliRunner

from hashall.cli import cli
from hashall.path_normalize import (
    CrossSeedLinkNormalizationPlan,
    apply_cross_seed_link_normalization,
    build_cross_seed_link_normalization_plan,
)
from hashall.qbittorrent import QBitTorrent
from hashall.rtorrent import RTTorrentMeta


def test_build_cross_seed_link_plan_ready_same_fs(tmp_path: Path) -> None:
    source_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed-link" / "FileList.io"
    source_content = source_root / "Release.One"
    target_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed" / "FileList.io"
    source_content.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)

    qb = QBitTorrent(
        hash="abc123",
        name="Release.One",
        save_path=str(source_root),
        content_path=str(source_content),
        category="cross-seed",
        tags="",
        state="stoppedUP",
        size=10,
        progress=1.0,
        amount_left=0,
        auto_tmm=False,
    )
    rt_row = {
        "hash": "abc123",
        "directory": str(source_content),
        "state": "stalledUP",
    }

    plan = build_cross_seed_link_normalization_plan("abc123", qb_torrent=qb, rt_row=rt_row)

    assert plan.ready is True
    assert plan.qb_should_resume is False
    assert plan.rt_should_restart is True
    assert plan.qb_new_save_path == str(target_root)
    assert plan.qb_new_content_path == str(target_root / "Release.One")
    assert plan.rt_new_directory == str(target_root / "Release.One")
    assert plan.rt_new_apply_directory == str(target_root / "Release.One")
    assert plan.same_filesystem is True
    assert plan.issues == []


def test_build_cross_seed_link_plan_flags_target_and_auto_tmm_issues(tmp_path: Path) -> None:
    source_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed-link" / "DocsPedia"
    source_content = source_root / "Release.Two"
    target_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed" / "DocsPedia"
    target_content = target_root / "Release.Two"
    source_content.mkdir(parents=True, exist_ok=True)
    target_content.mkdir(parents=True, exist_ok=True)

    qb = QBitTorrent(
        hash="def456",
        name="Release.Two",
        save_path=str(source_root),
        content_path=str(source_content),
        category="cross-seed",
        tags="",
        state="uploading",
        size=10,
        progress=1.0,
        amount_left=0,
        auto_tmm=True,
    )
    rt_row = {
        "hash": "def456",
        "directory": str(source_content),
        "state": "stoppedUP",
    }

    plan = build_cross_seed_link_normalization_plan("def456", qb_torrent=qb, rt_row=rt_row)

    assert plan.ready is False
    assert "qb_auto_tmm_enabled" in plan.issues
    assert "target_content_already_exists" in plan.issues


class _FakeQBClient:
    def __init__(self, info: QBitTorrent):
        self.info = info
        self.pause_calls = 0
        self.resume_calls = 0
        self.set_location_calls: list[str] = []
        self.last_error = None

    def get_torrent_info(self, torrent_hash: str):
        assert torrent_hash == self.info.hash
        return self.info

    def pause_torrent(self, torrent_hash: str) -> bool:
        assert torrent_hash == self.info.hash
        self.pause_calls += 1
        return True

    def resume_torrent(self, torrent_hash: str) -> bool:
        assert torrent_hash == self.info.hash
        self.resume_calls += 1
        self.info.state = "uploading"
        return True

    def set_location(self, torrent_hash: str, new_location: str) -> bool:
        assert torrent_hash == self.info.hash
        self.set_location_calls.append(new_location)
        self.info.save_path = new_location
        self.info.content_path = str(Path(new_location) / self.info.name)
        return True


def test_apply_cross_seed_link_normalization_preserves_stopped_qb(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed-link" / "FileList.io"
    source_content = source_root / "Release.One"
    target_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed" / "FileList.io"
    source_content.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)

    info = QBitTorrent(
        hash="abc123",
        name="Release.One",
        save_path=str(source_root),
        content_path=str(source_content),
        category="cross-seed",
        tags="",
        state="stoppedUP",
        size=10,
        progress=1.0,
        amount_left=0,
        auto_tmm=False,
    )
    rt_row = {
        "hash": "abc123",
        "directory": str(source_content),
        "state": "stoppedUP",
    }
    plan = build_cross_seed_link_normalization_plan("abc123", qb_torrent=info, rt_row=rt_row)
    fake_qb = _FakeQBClient(info)
    rt_calls: list[tuple[str, str, bool]] = []

    def fake_rt_apply(torrent_hash: str, target_directory: str, *, rpc_url: str, restart: bool = True):
        rt_calls.append((torrent_hash, target_directory, restart))
        return ["d.stop", "d.close", "d.directory.set", "d.save_full_session", "session.save", "d.open"]

    def fake_wait_rt(
        torrent_hash: str,
        *,
        expected_directory: str,
        expected_save_path: str = "",
        expected_content_path: str = "",
        rpc_url: str,
        timeout_seconds: float = 10.0,
        interval_seconds: float = 0.5,
    ):
        return {"hash": torrent_hash, "directory": expected_directory, "state": "stoppedUP"}

    monkeypatch.setattr("hashall.path_normalize.rt_apply_directory_repoint", fake_rt_apply)
    monkeypatch.setattr("hashall.path_normalize._wait_for_rt_target", fake_wait_rt)

    result = apply_cross_seed_link_normalization(plan, qb_client=fake_qb)

    assert fake_qb.pause_calls == 1
    assert fake_qb.resume_calls == 0
    assert fake_qb.set_location_calls == [plan.qb_new_save_path]
    assert rt_calls == [("abc123", plan.rt_new_apply_directory, False)]
    assert result.actions == ["qb.pause", "qb.set_location", "rt.repoint"]
    assert result.qb_final_save_path == plan.qb_new_save_path
    assert result.rt_final_directory == plan.rt_new_directory


def test_build_cross_seed_link_plan_uses_rt_apply_parent_for_multi_file(tmp_path: Path) -> None:
    source_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed-link" / "FileList.io"
    source_content = source_root / "Release.One"
    target_root = tmp_path / "pool-media" / "torrents" / "seeding" / "cross-seed" / "FileList.io"
    source_content.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)

    qb = QBitTorrent(
        hash="abc123",
        name="Release.One",
        save_path=str(source_root),
        content_path=str(source_content),
        category="cross-seed",
        tags="",
        state="stoppedUP",
        size=10,
        progress=1.0,
        amount_left=0,
        auto_tmm=False,
    )
    rt_row = {
        "hash": "abc123",
        "directory": str(source_content),
        "state": "stoppedUP",
    }
    rt_meta = RTTorrentMeta(
        torrent_hash="abc123",
        info_name="Release.One",
        is_multi_file=True,
        file_count=2,
        total_bytes=10,
    )

    plan = build_cross_seed_link_normalization_plan("abc123", qb_torrent=qb, rt_row=rt_row, rt_meta=rt_meta)

    assert plan.rt_new_directory == str(target_root / "Release.One")
    assert plan.rt_new_apply_directory == str(target_root)


def test_payload_normalize_cross_seed_link_cli_dry_run(monkeypatch) -> None:
    fake_plan = CrossSeedLinkNormalizationPlan(
        torrent_hash="abc123",
        qb_state="stoppedUP",
        qb_should_resume=False,
        qb_old_save_path="/pool/media/torrents/seeding/cross-seed-link/FileList.io",
        qb_new_save_path="/pool/media/torrents/seeding/cross-seed/FileList.io",
        qb_old_content_path="/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One",
        qb_new_content_path="/pool/media/torrents/seeding/cross-seed/FileList.io/Release.One",
        rt_state="stoppedUP",
        rt_should_restart=False,
        rt_old_directory="/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One",
        rt_new_directory="/pool/media/torrents/seeding/cross-seed/FileList.io/Release.One",
        rt_old_apply_directory="/pool/media/torrents/seeding/cross-seed-link/FileList.io/Release.One",
        rt_new_apply_directory="/pool/media/torrents/seeding/cross-seed/FileList.io/Release.One",
        source_exists=True,
        target_exists=False,
        same_filesystem=True,
        source_device=1,
        target_device=1,
        issues=[],
    )

    monkeypatch.setattr("hashall.path_normalize.plan_cross_seed_link_normalization", lambda _hash: fake_plan)

    runner = CliRunner()
    result = runner.invoke(cli, ["payload", "normalize-cross-seed-link", "--hash", "abc123"])

    assert result.exit_code == 0
    assert "payload normalize-cross-seed-link" in result.output
    assert "ready: True" in result.output
    assert "lane: cross-seed-link -> cross-seed" in result.output
