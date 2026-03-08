import os
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashall.bencode import bencode_encode
from hashall import qb_zfs_relocate
from hashall.qb_zfs_relocate import QBZFSRelocationTool, load_hashes_file, write_json


class FakeClient:
    def __init__(self, torrents_by_hash):
        self.torrents_by_hash = torrents_by_hash
        self.pause_calls = []
        self.resume_calls = []
        self.recheck_calls = []

    def get_torrents(self):
        return list(self.torrents_by_hash.values())

    def get_torrents_by_hashes(self, hashes):
        return {
            torrent_hash: self.torrents_by_hash[torrent_hash]
            for torrent_hash in hashes
            if torrent_hash in self.torrents_by_hash
        }

    def get_torrent_info(self, torrent_hash):
        return self.torrents_by_hash.get(torrent_hash)

    def pause_torrents(self, hashes):
        self.pause_calls.append(list(hashes))
        for torrent_hash in hashes:
            self.torrents_by_hash[torrent_hash].state = "pausedUP"
        return True

    def resume_torrents(self, hashes):
        self.resume_calls.append(list(hashes))
        for torrent_hash in hashes:
            self.torrents_by_hash[torrent_hash].state = "stalledUP"
        return True

    def test_connection(self):
        return True

    def recheck_torrent(self, torrent_hash):
        self.recheck_calls.append(torrent_hash)
        return True


class FakeController:
    def __init__(self, stopped=True):
        self.stopped = stopped
        self.start_calls = 0
        self.stop_calls = 0

    def is_stopped(self):
        return self.stopped

    def stop(self):
        self.stopped = True
        self.stop_calls += 1

    def start(self):
        self.stopped = False
        self.start_calls += 1


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run(self, cmd, **kwargs):
        self.commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeVerifier:
    def __init__(self):
        self.calls = []

    def verify(
        self,
        torrent_path,
        candidate_path,
        report_path,
        *,
        timeout_seconds,
        quick_only,
        show_progress,
    ):
        self.calls.append(
            {
                "torrent_path": str(torrent_path),
                "candidate_path": str(candidate_path),
                "report_path": str(report_path),
                "timeout_seconds": float(timeout_seconds),
                "quick_only": bool(quick_only),
                "show_progress": bool(show_progress),
            }
        )
        payload = {
            "summary": {
                "verified": 1,
                "best_path": str(candidate_path),
                "best_classification": "verified_match",
            }
        }
        write_json(report_path, payload)
        return payload


def _torrent_info(torrent_hash, name, save_path, content_path, state="pausedUP", progress=1.0):
    return SimpleNamespace(
        hash=torrent_hash,
        name=name,
        save_path=save_path,
        content_path=content_path,
        category="",
        tags="",
        state=state,
        size=1,
        progress=progress,
        auto_tmm=False,
        amount_left=0,
        completed=1,
        downloaded=1,
        completion_on=1,
    )


def _write_fastresume(path: Path, save_path: str) -> None:
    path.write_bytes(
        bencode_encode(
            {
                b"save_path": save_path.encode("utf-8"),
                b"qBt-savePath": save_path.encode("utf-8"),
                b"qBt-downloadPath": b"",
            }
        )
    )


def _write_multi_file_torrent(path: Path, root_name: str) -> None:
    path.write_bytes(
        bencode_encode(
            {
                b"info": {
                    b"name": root_name.encode("utf-8"),
                    b"files": [
                        {b"length": 10, b"path": [b"disc1", b"track01.flac"]},
                        {b"length": 20, b"path": [b"disc1", b"track02.flac"]},
                    ],
                }
            }
        )
    )


def _write_verify_report(path: Path, candidate_path: Path, *, classification: str = "exact_tree", verified: int = 1) -> None:
    write_json(
        path,
        {
            "summary": {
                "verified": int(verified),
                "best_path": str(candidate_path),
                "best_classification": classification,
            }
        },
    )


def _manifest_row(tmp_path: Path, torrent_hash: str) -> dict:
    old_save_path = str(tmp_path / "old_ds" / "category")
    new_save_path = str(tmp_path / "new_ds" / "category")
    source_content = Path(old_save_path) / "Example Torrent"
    dest_content = Path(new_save_path) / "Example Torrent"
    source_content.mkdir(parents=True, exist_ok=True)
    dest_content.mkdir(parents=True, exist_ok=True)
    (dest_content / "payload.bin").write_bytes(b"payload")
    fastresume_path = tmp_path / "BT_backup" / f"{torrent_hash}.fastresume"
    torrent_path = tmp_path / "BT_backup" / f"{torrent_hash}.torrent"
    fastresume_path.parent.mkdir(parents=True, exist_ok=True)
    _write_fastresume(fastresume_path, old_save_path)
    _write_multi_file_torrent(torrent_path, "Example Torrent")
    return {
        "hash": torrent_hash,
        "name": "Example Torrent",
        "state": "pausedUP",
        "progress": 1.0,
        "selected": True,
        "fastresume_path": str(fastresume_path),
        "torrent_path": str(torrent_path),
        "old_save_path": old_save_path,
        "old_qbt_save_path": old_save_path,
        "old_qbt_download_path": "",
        "content_path": str(source_content),
        "source_root": str(tmp_path / "old_ds"),
        "dest_root": str(tmp_path / "new_ds"),
        "new_save_path": new_save_path,
        "dest_content_path": str(dest_content),
        "dest_exists": True,
        "dest_kind": "dir",
        "is_multi_file": True,
        "expected_root_name": "Example Torrent",
        "path_shape_match": True,
        "verified": True,
        "actionable": True,
        "copy_status": "pending",
        "verify_status": "pending",
        "verify_report_path": "",
        "verify_classification": "",
        "patch_status": "pending",
        "resume_status": "pending",
        "cleanup_status": "pending",
        "cleanup_ready": False,
        "cleanup_issues": [],
        "cleanup_staged_path": "",
        "plan_issues": [],
        "issues": [],
    }


def test_plan_preserves_multi_file_save_path_semantics(tmp_path):
    torrent_hash = "abc123def456abc123def456abc123def456abcd"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Live Set")
    info = _torrent_info(
        torrent_hash,
        "Live Set",
        str(tmp_path / "old_ds" / "music"),
        str(tmp_path / "old_ds" / "music" / "Live Set"),
    )
    client = FakeClient({torrent_hash: info})
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())
    manifest_path = tmp_path / "relocation.json"

    rc = tool.plan(
        manifest_path=manifest_path,
        hashes=[torrent_hash],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    assert rc == 0
    assert row["old_save_path"] == str(tmp_path / "old_ds" / "music")
    assert row["new_save_path"] == str(tmp_path / "new_ds" / "music")
    assert row["dest_content_path"] == str(tmp_path / "new_ds" / "music" / "Live Set")
    assert row["path_shape_match"] is True


def test_plan_auto_selects_torrents_under_source_root(tmp_path):
    torrent_hash = "abc123def456abc123def456abc123def456abcd"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Auto Set")
    matching = _torrent_info(
        torrent_hash,
        "Auto Set",
        str(tmp_path / "old_ds" / "music"),
        str(tmp_path / "old_ds" / "music" / "Auto Set"),
    )
    non_matching = _torrent_info(
        "ffff23def456abc123def456abc123def456abcd",
        "Other Set",
        str(tmp_path / "other_ds" / "music"),
        str(tmp_path / "other_ds" / "music" / "Other Set"),
    )
    client = FakeClient({torrent_hash: matching, non_matching.hash: non_matching})
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())
    manifest_path = tmp_path / "relocation.json"

    rc = tool.plan(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert manifest["selection"]["mode"] == "auto_source_root"
    assert manifest["selection"]["hashes"] == [torrent_hash]
    assert [row["hash"] for row in manifest["rows"]] == [torrent_hash]


def test_load_hashes_file_ignores_blank_and_comment_lines(tmp_path):
    hash_file = tmp_path / "selected-hashes.txt"
    hash_file.write_text(
        "# One qB infohash per line.\n\n# Example:\nabc123DEF456abc123def456abc123def456abcd\n",
        encoding="utf-8",
    )

    hashes = load_hashes_file(hash_file)

    assert hashes == ["abc123def456abc123def456abc123def456abcd"]


def test_copy_uses_rsync_and_pauses_selected_torrents(tmp_path):
    torrent_hash = "copyhash"
    row = _manifest_row(tmp_path, torrent_hash)
    manifest_path = tmp_path / "copy-manifest.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient({torrent_hash: _torrent_info(torrent_hash, row["name"], row["new_save_path"], row["dest_content_path"])})
    runner = FakeRunner()
    tool = QBZFSRelocationTool(qb_client=client, runner=runner, verifier=FakeVerifier())

    rc = tool.copy(manifest_path=manifest_path, apply=True)

    assert rc == 0
    assert client.pause_calls == [[torrent_hash]]
    assert runner.commands
    assert runner.commands[0][0] == "rsync"


def test_copy_apply_emits_progress_events_and_uses_rsync_progress_flag(tmp_path, capsys):
    torrent_hash = "copyprogress"
    row = _manifest_row(tmp_path, torrent_hash)
    manifest_path = tmp_path / "copy-progress.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {torrent_hash: _torrent_info(torrent_hash, row["name"], row["new_save_path"], row["dest_content_path"])}
    )
    runner = FakeRunner()
    tool = QBZFSRelocationTool(qb_client=client, runner=runner, verifier=FakeVerifier())

    rc = tool.copy(manifest_path=manifest_path, apply=True)

    output = capsys.readouterr().out
    assert rc == 0
    assert "--info=progress2" in runner.commands[0]
    assert "event=item_start phase=copy" in output
    assert "event=item_end phase=copy" in output


def test_copy_apply_refreshes_cached_qb_state_after_pause(tmp_path):
    torrent_hash = "copystate"
    row = _manifest_row(tmp_path, torrent_hash)
    row["state"] = "stalledUP"
    manifest_path = tmp_path / "copy-refresh.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["old_save_path"],
                row["content_path"],
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())

    rc = tool.copy(manifest_path=manifest_path, apply=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert manifest["rows"][0]["state"] == "pausedUP"


def test_migrate_limits_selection_with_batch_size(tmp_path):
    torrent_hash_a = "abc123def456abc123def456abc123def456abcd"
    torrent_hash_b = "bbb123def456abc123def456abc123def456abcd"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    for torrent_hash, root_name in (
        (torrent_hash_a, "Batch One"),
        (torrent_hash_b, "Batch Two"),
    ):
        _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
        _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", root_name)
        (tmp_path / "old_ds" / "music" / root_name).mkdir(parents=True, exist_ok=True)
        dest_content = tmp_path / "new_ds" / "music" / root_name
        dest_content.mkdir(parents=True, exist_ok=True)
        (dest_content / "payload.bin").write_bytes(b"payload")
    client = FakeClient(
        {
            torrent_hash_a: _torrent_info(
                torrent_hash_a,
                "Batch One",
                str(tmp_path / "old_ds" / "music"),
                str(tmp_path / "old_ds" / "music" / "Batch One"),
            ),
            torrent_hash_b: _torrent_info(
                torrent_hash_b,
                "Batch Two",
                str(tmp_path / "old_ds" / "music"),
                str(tmp_path / "old_ds" / "music" / "Batch Two"),
            ),
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())
    manifest_path = tmp_path / "migrate.json"

    rc = tool.migrate(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        batch_size=1,
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
        apply=False,
        timeout_seconds=30.0,
        quick_only=False,
        allow_partials=False,
        journal_path=tmp_path / "patch-journal.jsonl",
        auto_stop_qb=False,
        auto_cleanup_mode="off",
        cleanup_journal_path=None,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=True,
        recheck_on_failure=False,
        cleanup_pilot_size=1,
        cleanup_batch_size=0,
        cleanup_observe_seconds=0.0,
        cleanup_min_depth=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phases = [entry["phase"] for entry in manifest["phase_history"]]
    assert rc == 0
    assert manifest["selection"]["mode"] == "auto_source_root"
    assert manifest["selection"]["matched"] == 2
    assert manifest["selection"]["batch_size"] == 1
    assert manifest["selection"]["hashes"] == [torrent_hash_a]
    assert [row["hash"] for row in manifest["rows"]] == [torrent_hash_a]
    assert phases == ["plan", "copy", "verify", "validate", "patch", "resume"]


def test_migrate_apply_auto_stops_qb_before_validate(tmp_path):
    torrent_hash = "applystop123def456abc123def456abc123def4"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Apply Stop")
    source_content = tmp_path / "old_ds" / "music" / "Apply Stop"
    dest_content = tmp_path / "new_ds" / "music" / "Apply Stop"
    source_content.mkdir(parents=True, exist_ok=True)
    dest_content.mkdir(parents=True, exist_ok=True)
    (dest_content / "payload.bin").write_bytes(b"payload")
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                "Apply Stop",
                str(tmp_path / "old_ds" / "music"),
                str(source_content),
                state="pausedUP",
            )
        }
    )
    controller = FakeController(stopped=False)
    original_start = controller.start

    def _start_with_reloaded_path():
        client.torrents_by_hash[torrent_hash].save_path = str(tmp_path / "new_ds" / "music")
        original_start()

    controller.start = _start_with_reloaded_path
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )
    manifest_path = tmp_path / "migrate-apply.json"

    rc = tool.migrate(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        batch_size=0,
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
        apply=True,
        timeout_seconds=30.0,
        quick_only=False,
        allow_partials=False,
        journal_path=tmp_path / "patch-journal.jsonl",
        auto_stop_qb=True,
        auto_cleanup_mode="off",
        cleanup_journal_path=None,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=False,
        recheck_on_failure=False,
        cleanup_pilot_size=1,
        cleanup_batch_size=0,
        cleanup_observe_seconds=0.0,
        cleanup_min_depth=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert controller.stop_calls == 1
    assert controller.start_calls == 1
    assert manifest["global_issues"] == []
    assert manifest["rows"][0]["patch_status"] in {"patched", "no_change"}


def test_migrate_apply_auto_starts_qb_before_plan_when_initially_stopped(tmp_path):
    torrent_hash = "applystart123def456abc123def456abc123def"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Apply Start")
    source_content = tmp_path / "old_ds" / "music" / "Apply Start"
    dest_content = tmp_path / "new_ds" / "music" / "Apply Start"
    source_content.mkdir(parents=True, exist_ok=True)
    dest_content.mkdir(parents=True, exist_ok=True)
    (dest_content / "payload.bin").write_bytes(b"payload")
    controller = FakeController(stopped=True)

    class OfflineUntilStartedClient(FakeClient):
        def test_connection(self):
            return not controller.stopped

        def get_torrents(self):
            if controller.stopped:
                raise RuntimeError("qB offline")
            return super().get_torrents()

    client = OfflineUntilStartedClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                "Apply Start",
                str(tmp_path / "old_ds" / "music"),
                str(source_content),
                state="pausedUP",
            )
        }
    )
    original_start = controller.start

    def _start_with_reloaded_path():
        if controller.start_calls >= 1:
            client.torrents_by_hash[torrent_hash].save_path = str(tmp_path / "new_ds" / "music")
        original_start()

    controller.start = _start_with_reloaded_path
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )
    manifest_path = tmp_path / "migrate-start.json"

    rc = tool.migrate(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        batch_size=0,
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
        apply=True,
        timeout_seconds=30.0,
        quick_only=False,
        allow_partials=False,
        journal_path=tmp_path / "patch-journal.jsonl",
        auto_stop_qb=True,
        auto_cleanup_mode="off",
        cleanup_journal_path=None,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=False,
        recheck_on_failure=False,
        cleanup_pilot_size=1,
        cleanup_batch_size=0,
        cleanup_observe_seconds=0.0,
        cleanup_min_depth=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert controller.stop_calls == 1
    assert controller.start_calls == 2
    assert manifest["global_issues"] == []
    assert manifest["rows"][0]["patch_status"] in {"patched", "no_change"}


def test_migrate_apply_auto_cleanup_safe_cleans_source(tmp_path):
    torrent_hash = "autocleanup123def456abc123def456abc123de"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Auto Cleanup")
    source_content = tmp_path / "old_ds" / "music" / "Auto Cleanup"
    dest_content = tmp_path / "new_ds" / "music" / "Auto Cleanup"
    source_content.mkdir(parents=True, exist_ok=True)
    dest_content.mkdir(parents=True, exist_ok=True)
    (dest_content / "payload.bin").write_bytes(b"payload")
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                "Auto Cleanup",
                str(tmp_path / "old_ds" / "music"),
                str(source_content),
                state="pausedUP",
            )
        }
    )
    controller = FakeController(stopped=False)
    original_start = controller.start

    def _start_with_reloaded_path():
        client.torrents_by_hash[torrent_hash].save_path = str(tmp_path / "new_ds" / "music")
        original_start()

    controller.start = _start_with_reloaded_path
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )
    manifest_path = tmp_path / "migrate-autocleanup.json"
    cleanup_journal = tmp_path / "cleanup-journal.jsonl"

    rc = tool.migrate(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        batch_size=0,
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
        apply=True,
        timeout_seconds=30.0,
        quick_only=False,
        allow_partials=False,
        journal_path=tmp_path / "patch-journal.jsonl",
        auto_stop_qb=True,
        auto_cleanup_mode="safe",
        cleanup_journal_path=cleanup_journal,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=False,
        recheck_on_failure=False,
        cleanup_pilot_size=1,
        cleanup_batch_size=0,
        cleanup_observe_seconds=0.0,
        cleanup_min_depth=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phases = [entry["phase"] for entry in manifest["phase_history"]]
    assert rc == 0
    assert not source_content.exists()
    assert cleanup_journal.exists()
    assert phases == ["plan", "copy", "verify", "validate", "patch", "resume", "cleanup"]
    assert manifest["rows"][0]["cleanup_status"] == "cleaned"


def test_migrate_dryrun_skips_downstream_phases_until_destination_exists(tmp_path):
    torrent_hash = "skipverify123def456abc123def456abc123def4"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "music"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Needs Copy")
    source_content = tmp_path / "old_ds" / "music" / "Needs Copy"
    source_content.mkdir(parents=True, exist_ok=True)
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                "Needs Copy",
                str(tmp_path / "old_ds" / "music"),
                str(source_content),
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())
    manifest_path = tmp_path / "migrate-skip.json"

    rc = tool.migrate(
        manifest_path=manifest_path,
        hashes=[],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        batch_size=0,
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
        apply=False,
        timeout_seconds=30.0,
        quick_only=False,
        allow_partials=False,
        journal_path=tmp_path / "patch-journal.jsonl",
        auto_stop_qb=False,
        auto_cleanup_mode="off",
        cleanup_journal_path=None,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=True,
        recheck_on_failure=False,
        cleanup_pilot_size=1,
        cleanup_batch_size=0,
        cleanup_observe_seconds=0.0,
        cleanup_min_depth=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phases = [entry["phase"] for entry in manifest["phase_history"]]
    row = manifest["rows"][0]
    assert rc == 0
    assert phases == ["plan", "copy"]
    assert row["copy_status"] == "dryrun"
    assert row["verify_status"] == "pending"
    assert row["issues"] == []


def test_validate_can_skip_torrent_stopped_requirement(tmp_path):
    torrent_hash = "runok123def456abc123def456abc123def456"
    row = _manifest_row(tmp_path, torrent_hash)
    row["verified"] = True
    manifest_path = tmp_path / "validate-running.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["new_save_path"],
                row["dest_content_path"],
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())

    rc = tool.validate(
        manifest_path=manifest_path,
        allow_partials=False,
        for_patch=True,
        journal_path=tmp_path / "patch-journal.jsonl",
        require_stopped_qb=False,
        require_torrents_stopped=False,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    assert rc == 0
    assert row["actionable"] is True
    assert "torrent_not_stopped" not in row["issues"]


def test_validate_uses_cached_qb_state_when_qb_is_stopped(tmp_path):
    torrent_hash = "stoppedcache123def456abc123def456abc123"
    row = _manifest_row(tmp_path, torrent_hash)
    row["verified"] = True
    row["state"] = "pausedUP"
    manifest_path = tmp_path / "validate-stopped-cache.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )

    class ExplodingClient(FakeClient):
        def get_torrent_info(self, torrent_hash):
            raise AssertionError("validate should not query qB after stop")

    tool = QBZFSRelocationTool(
        qb_client=ExplodingClient({}),
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=FakeController(stopped=True),
    )

    rc = tool.validate(
        manifest_path=manifest_path,
        allow_partials=False,
        for_patch=True,
        journal_path=tmp_path / "patch-journal.jsonl",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    assert rc == 0
    assert row["actionable"] is True
    assert "qb_torrent_not_found" not in row["issues"]
    assert "qb_state_unavailable_while_stopped" not in row["issues"]


def test_verify_and_validate_mark_verified_rows_actionable(tmp_path):
    torrent_hash = "verifyhash"
    row = _manifest_row(tmp_path, torrent_hash)
    row["verified"] = False
    manifest_path = tmp_path / "verify-manifest.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient({torrent_hash: _torrent_info(torrent_hash, row["name"], row["new_save_path"], row["dest_content_path"])})
    controller = FakeController(stopped=True)
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )

    verify_rc = tool.verify(manifest_path=manifest_path, timeout_seconds=30.0, quick_only=False)
    validate_rc = tool.validate(
        manifest_path=manifest_path,
        allow_partials=False,
        for_patch=True,
        journal_path=tmp_path / "patch-journal.jsonl",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    assert verify_rc == 0
    assert validate_rc == 0
    assert row["verified"] is True
    assert row["actionable"] is True


def test_verify_emits_progress_events_and_requests_show_progress(tmp_path, capsys):
    torrent_hash = "verifyprogress"
    row = _manifest_row(tmp_path, torrent_hash)
    row["verified"] = False
    manifest_path = tmp_path / "verify-progress.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    verifier = FakeVerifier()
    client = FakeClient(
        {torrent_hash: _torrent_info(torrent_hash, row["name"], row["new_save_path"], row["dest_content_path"])}
    )
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=verifier,
    )

    rc = tool.verify(manifest_path=manifest_path, timeout_seconds=30.0, quick_only=False)

    output = capsys.readouterr().out
    assert rc == 0
    assert verifier.calls[0]["show_progress"] is True
    assert "event=item_start phase=verify" in output
    assert "event=item_end phase=verify" in output


def test_patch_and_rollback_round_trip_fastresume(tmp_path):
    torrent_hash = "patchhash"
    row = _manifest_row(tmp_path, torrent_hash)
    manifest_path = tmp_path / "patch-manifest.json"
    journal_path = tmp_path / "patch-journal.jsonl"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient({torrent_hash: _torrent_info(torrent_hash, row["name"], row["new_save_path"], row["dest_content_path"])})
    controller = FakeController(stopped=True)
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )

    patch_rc = tool.patch(
        manifest_path=manifest_path,
        journal_path=journal_path,
        apply=True,
        auto_stop_qb=False,
    )
    patched_blob = Path(row["fastresume_path"]).read_bytes()

    rollback_rc = tool.rollback(
        manifest_path=manifest_path,
        journal_path=journal_path,
        apply=True,
        auto_stop_qb=False,
    )
    restored_blob = Path(row["fastresume_path"]).read_bytes()

    assert patch_rc == 0
    assert rollback_rc == 0
    assert row["new_save_path"].encode("utf-8") in patched_blob
    assert row["old_save_path"].encode("utf-8") in restored_blob


def test_resume_starts_qb_and_batches_pilot_then_remaining(tmp_path):
    torrent_hash_a = "resumea"
    torrent_hash_b = "resumeb"
    row_a = _manifest_row(tmp_path, torrent_hash_a)
    row_b = _manifest_row(tmp_path, torrent_hash_b)
    row_a["patch_status"] = "patched"
    row_b["patch_status"] = "patched"
    manifest_path = tmp_path / "resume-manifest.json"
    write_json(
        manifest_path,
        {
            "rows": [row_a, row_b],
            "global_issues": [],
            "phase_history": [],
            "selection": {"hashes": [torrent_hash_a, torrent_hash_b]},
        },
    )
    client = FakeClient(
        {
            torrent_hash_a: _torrent_info(torrent_hash_a, row_a["name"], row_a["new_save_path"], row_a["dest_content_path"]),
            torrent_hash_b: _torrent_info(torrent_hash_b, row_b["name"], row_b["new_save_path"], row_b["dest_content_path"]),
        }
    )
    controller = FakeController(stopped=True)
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
    )

    rc = tool.resume(
        manifest_path=manifest_path,
        apply=True,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=True,
        recheck_on_failure=False,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    statuses = {row["hash"]: row["resume_status"] for row in manifest["rows"]}
    assert rc == 0
    assert controller.start_calls == 1
    assert client.resume_calls == [[torrent_hash_a], [torrent_hash_b]]
    assert statuses[torrent_hash_a] == "pilot_ok"
    assert statuses[torrent_hash_b] == "resumed_ok"


def test_resume_observe_honors_nonzero_soak_window(tmp_path):
    torrent_hash = "resumeobserve"
    row = _manifest_row(tmp_path, torrent_hash)
    row["patch_status"] = "patched"
    manifest_path = tmp_path / "resume-observe-manifest.json"
    write_json(
        manifest_path,
        {
            "rows": [row],
            "global_issues": [],
            "phase_history": [],
            "selection": {"hashes": [torrent_hash]},
        },
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["new_save_path"],
                row["dest_content_path"],
                state="stalledUP",
            )
        }
    )
    controller = FakeController(stopped=True)
    sleeps: list[float] = []
    fake_now = [100.0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now[0] += seconds

    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=FakeRunner(),
        verifier=FakeVerifier(),
        process_controller=controller,
        sleep_fn=fake_sleep,
    )
    original_time = qb_zfs_relocate.time.time
    try:
        qb_zfs_relocate.time.time = lambda: fake_now[0]
        rc = tool.resume(
            manifest_path=manifest_path,
            apply=True,
            pilot_size=1,
            observe_seconds=2.0,
            resume_remaining=True,
            recheck_on_failure=False,
        )
    finally:
        qb_zfs_relocate.time.time = original_time

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert sleeps == [1.0, 1.0]
    assert manifest["rows"][0]["resume_status"] == "pilot_ok"


def test_cleanup_requires_confirm_cleanup(tmp_path):
    torrent_hash = "cleanuphash"
    row = _manifest_row(tmp_path, torrent_hash)
    row["cleanup_ready"] = True
    manifest_path = tmp_path / "cleanup-manifest.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    tool = QBZFSRelocationTool(qb_client=FakeClient({}), runner=FakeRunner(), verifier=FakeVerifier())

    with pytest.raises(RuntimeError):
        tool.cleanup(manifest_path=manifest_path, apply=True, confirm_cleanup=False)


def test_cleanup_dryrun_validates_live_state_and_reports_ready_rows(tmp_path):
    torrent_hash = "cleanupdryrun"
    row = _manifest_row(tmp_path, torrent_hash)
    row["cleanup_ready"] = True
    report_path = tmp_path / "verify-report.json"
    _write_verify_report(report_path, Path(row["dest_content_path"]))
    row["verify_report_path"] = str(report_path)
    row["verify_classification"] = "exact_tree"
    manifest_path = tmp_path / "cleanup-dryrun.json"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["new_save_path"],
                row["dest_content_path"],
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())

    rc = tool.cleanup(
        manifest_path=manifest_path,
        apply=False,
        confirm_cleanup=False,
        cleanup_observe_seconds=0.0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert manifest["rows"][0]["cleanup_status"] == "dryrun"


def test_cleanup_apply_stages_observes_and_deletes_source(tmp_path):
    torrent_hash = "cleanupapply"
    row = _manifest_row(tmp_path, torrent_hash)
    row["cleanup_ready"] = True
    report_path = tmp_path / "verify-report.json"
    _write_verify_report(report_path, Path(row["dest_content_path"]))
    row["verify_report_path"] = str(report_path)
    row["verify_classification"] = "exact_tree"
    manifest_path = tmp_path / "cleanup-apply.json"
    cleanup_journal = tmp_path / "cleanup-journal.jsonl"
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["new_save_path"],
                row["dest_content_path"],
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())
    stage_path = tool._cleanup_stage_path(manifest_path, row)

    rc = tool.cleanup(
        manifest_path=manifest_path,
        apply=True,
        confirm_cleanup=True,
        journal_path=cleanup_journal,
        cleanup_observe_seconds=0.0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = Path(row["content_path"])
    actions = [json.loads(line)["action"] for line in cleanup_journal.read_text(encoding="utf-8").splitlines()]
    assert rc == 0
    assert not source_path.exists()
    assert not stage_path.exists()
    assert not stage_path.parent.exists()
    assert manifest["rows"][0]["cleanup_status"] == "cleaned"
    assert actions == ["stage", "observe", "delete"]


def test_cleanup_apply_can_resume_from_existing_staged_path(tmp_path):
    torrent_hash = "cleanupresume"
    row = _manifest_row(tmp_path, torrent_hash)
    row["cleanup_ready"] = True
    report_path = tmp_path / "verify-report.json"
    _write_verify_report(report_path, Path(row["dest_content_path"]))
    row["verify_report_path"] = str(report_path)
    row["verify_classification"] = "exact_tree"
    manifest_path = tmp_path / "cleanup-resume.json"
    temp_tool = QBZFSRelocationTool(qb_client=FakeClient({}), runner=FakeRunner(), verifier=FakeVerifier())
    source_path = Path(row["content_path"])
    stage_path = temp_tool._cleanup_stage_path(manifest_path, row)
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.rename(stage_path)
    row["cleanup_staged_path"] = str(stage_path)
    write_json(
        manifest_path,
        {"rows": [row], "global_issues": [], "phase_history": [], "selection": {"hashes": [torrent_hash]}},
    )
    client = FakeClient(
        {
            torrent_hash: _torrent_info(
                torrent_hash,
                row["name"],
                row["new_save_path"],
                row["dest_content_path"],
                state="stalledUP",
            )
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())

    rc = tool.cleanup(
        manifest_path=manifest_path,
        apply=True,
        confirm_cleanup=True,
        cleanup_observe_seconds=0.0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert not source_path.exists()
    assert not stage_path.exists()
    assert not stage_path.parent.exists()
    assert manifest["rows"][0]["cleanup_status"] == "cleaned"


def test_cleanup_blocks_overlapping_source_targets(tmp_path):
    torrent_hash_a = "cleanupoverlapa"
    torrent_hash_b = "cleanupoverlapb"
    row_a = _manifest_row(tmp_path, torrent_hash_a)
    row_b = _manifest_row(tmp_path, torrent_hash_b)
    parent_source = Path(row_a["content_path"]).parent / "Parent"
    child_source = parent_source / "Child"
    shutil.rmtree(Path(row_a["content_path"]))
    child_source.mkdir(parents=True, exist_ok=True)
    row_a["content_path"] = str(parent_source)
    row_b["content_path"] = str(child_source)
    row_a["cleanup_ready"] = True
    row_b["cleanup_ready"] = True
    for index, row in enumerate((row_a, row_b), start=1):
        report_path = tmp_path / f"verify-report-{index}.json"
        _write_verify_report(report_path, Path(row["dest_content_path"]))
        row["verify_report_path"] = str(report_path)
        row["verify_classification"] = "exact_tree"
    manifest_path = tmp_path / "cleanup-overlap.json"
    write_json(
        manifest_path,
        {
            "rows": [row_a, row_b],
            "global_issues": [],
            "phase_history": [],
            "selection": {"hashes": [torrent_hash_a, torrent_hash_b]},
        },
    )
    client = FakeClient(
        {
            torrent_hash_a: _torrent_info(torrent_hash_a, row_a["name"], row_a["new_save_path"], row_a["dest_content_path"]),
            torrent_hash_b: _torrent_info(torrent_hash_b, row_b["name"], row_b["new_save_path"], row_b["dest_content_path"]),
        }
    )
    tool = QBZFSRelocationTool(qb_client=client, runner=FakeRunner(), verifier=FakeVerifier())

    rc = tool.cleanup(
        manifest_path=manifest_path,
        apply=False,
        confirm_cleanup=False,
        cleanup_observe_seconds=0.0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    statuses = {row["hash"]: row["cleanup_status"] for row in manifest["rows"]}
    assert rc == 1
    assert statuses[torrent_hash_a] == "blocked"
    assert statuses[torrent_hash_b] == "blocked"


def test_end_to_end_dryrun_flow_records_phase_history(tmp_path):
    torrent_hash = "e2edryrun"
    bt_backup = tmp_path / "BT_backup"
    bt_backup.mkdir()
    _write_fastresume(bt_backup / f"{torrent_hash}.fastresume", str(tmp_path / "old_ds" / "site"))
    _write_multi_file_torrent(bt_backup / f"{torrent_hash}.torrent", "Dryrun Set")
    dest_content = tmp_path / "new_ds" / "site" / "Dryrun Set"
    dest_content.mkdir(parents=True, exist_ok=True)
    (dest_content / "sample.bin").write_bytes(b"payload")
    source_content = tmp_path / "old_ds" / "site" / "Dryrun Set"
    source_content.mkdir(parents=True, exist_ok=True)
    info = _torrent_info(
        torrent_hash,
        "Dryrun Set",
        str(tmp_path / "old_ds" / "site"),
        str(source_content),
    )
    client = FakeClient({torrent_hash: info})
    controller = FakeController(stopped=True)
    runner = FakeRunner()
    tool = QBZFSRelocationTool(
        qb_client=client,
        runner=runner,
        verifier=FakeVerifier(),
        process_controller=controller,
    )
    manifest_path = tmp_path / "e2e-manifest.json"
    journal_path = tmp_path / "patch-journal.jsonl"

    assert tool.plan(
        manifest_path=manifest_path,
        hashes=[torrent_hash],
        source_root=str(tmp_path / "old_ds"),
        dest_root=str(tmp_path / "new_ds"),
        fastresume_dir=bt_backup,
        torrent_dir=bt_backup,
        export_torrents_dir=None,
    ) == 0
    assert tool.copy(manifest_path=manifest_path, apply=False) == 0
    assert tool.verify(manifest_path=manifest_path, timeout_seconds=30.0, quick_only=False) == 0
    assert tool.validate(
        manifest_path=manifest_path,
        allow_partials=False,
        for_patch=True,
        journal_path=journal_path,
    ) == 0
    assert tool.patch(
        manifest_path=manifest_path,
        journal_path=journal_path,
        apply=False,
        auto_stop_qb=False,
    ) == 0
    assert tool.resume(
        manifest_path=manifest_path,
        apply=False,
        pilot_size=1,
        observe_seconds=0.0,
        resume_remaining=False,
        recheck_on_failure=False,
    ) == 0
    assert tool.cleanup(
        manifest_path=manifest_path,
        apply=False,
        confirm_cleanup=False,
    ) == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phases = [entry["phase"] for entry in manifest["phase_history"]]
    assert phases == ["plan", "copy", "verify", "validate", "patch", "resume", "cleanup"]
    assert any(cmd[0] == "rsync" and "--dry-run" in cmd for cmd in runner.commands)


def test_cli_help_lists_required_phases():
    result = subprocess.run(
        ["python3", "bin/qb-zfs-relocate.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "plan" in result.stdout
    assert "copy" in result.stdout
    assert "verify" in result.stdout
    assert "validate" in result.stdout
    assert "patch" in result.stdout
    assert "resume" in result.stdout
    assert "cleanup" in result.stdout
    assert "rollback" in result.stdout
    assert "migrate" in result.stdout


def test_cli_creates_persistent_logs_in_configured_directory(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    log_dir = tmp_path / "logs"
    result = subprocess.run(
        [
            "python3",
            "bin/qb-zfs-relocate.py",
            "plan",
            "--manifest",
            str(manifest_path),
            "--source-root",
            "/same/path",
            "--dest-root",
            "/same/path",
            "--fastresume-dir",
            str(tmp_path),
            "--torrent-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "QB_ZFS_RELOCATE_LOG_DIR": str(log_dir),
        },
    )

    log_files = sorted(log_dir.glob("*.log"))
    jsonl_files = sorted(log_dir.glob("*.jsonl"))
    assert result.returncode == 1
    assert log_files
    assert jsonl_files
    assert "text_log=" in result.stdout
    assert "jsonl_log=" in result.stdout
    assert "source_and_destination_roots_must_differ" in log_files[0].read_text(encoding="utf-8")
    assert '"event": "run_args"' in jsonl_files[0].read_text(encoding="utf-8")


def test_plan_wrapper_omits_hashes_file_when_missing(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "bin"
        / "migrate-pool-data-to-media_01_plan.sh"
    )
    out_dir = tmp_path / "out"
    run_stamp = "20260308-130000"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "OUT_DIR": str(out_dir),
            "PYTHON_BIN": "/bin/echo",
            "RUN_STAMP": run_stamp,
        },
        check=False,
    )

    assert result.returncode == 0
    assert "--hashes-file" not in result.stdout
    manifest_path = out_dir / "runs" / run_stamp / "manifest.json"
    assert f"--manifest {manifest_path}" in result.stdout
    assert (out_dir / "current-manifest.txt").read_text(encoding="utf-8").strip() == str(manifest_path)
    assert os.readlink(out_dir / "latest-manifest.json") == str(manifest_path)
    assert not (out_dir / "selected-hashes.txt").exists()


def test_plan_wrapper_ignores_comment_only_hash_file(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "bin"
        / "migrate-pool-data-to-media_01_plan.sh"
    )
    out_dir = tmp_path / "out"
    run_stamp = "20260308-130100"
    hash_file = out_dir / "selected-hashes.txt"
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text("# template only\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "OUT_DIR": str(out_dir),
            "PYTHON_BIN": "/bin/echo",
            "RUN_STAMP": run_stamp,
        },
        check=False,
    )

    assert result.returncode == 0
    assert "--hashes-file" not in result.stdout
    manifest_path = out_dir / "runs" / run_stamp / "manifest.json"
    assert f"--manifest {manifest_path}" in result.stdout
    assert (out_dir / "current-manifest.txt").read_text(encoding="utf-8").strip() == str(manifest_path)
    assert os.readlink(out_dir / "latest-manifest.json") == str(manifest_path)
    assert "ignoring empty/comment-only hash override file" in result.stderr


def test_migrate_wrapper_passes_batch_size_and_migrate_phase(tmp_path):
    script = Path(__file__).resolve().parents[1] / "bin" / "migrate-pool-data-to-media.sh"
    out_dir = tmp_path / "out"
    run_stamp = "20260308-130200"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "OUT_DIR": str(out_dir),
            "PYTHON_BIN": "/bin/echo",
            "BATCH_SIZE": "3",
            "RUN_STAMP": run_stamp,
        },
        check=False,
    )

    assert result.returncode == 0
    assert " migrate " in f" {result.stdout} "
    manifest_path = out_dir / "runs" / run_stamp / "manifest.json"
    assert f"--manifest {manifest_path}" in result.stdout
    assert (out_dir / "current-manifest.txt").read_text(encoding="utf-8").strip() == str(manifest_path)
    assert os.readlink(out_dir / "latest-manifest.json") == str(manifest_path)
    assert "--batch-size 3" in result.stdout
    assert "--resume-remaining" in result.stdout
    assert "--auto-stop-qb" in result.stdout
