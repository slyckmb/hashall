import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashall.bencode import bencode_encode
from hashall.qb_zfs_relocate import QBZFSRelocationTool, write_json


class FakeClient:
    def __init__(self, torrents_by_hash):
        self.torrents_by_hash = torrents_by_hash
        self.pause_calls = []
        self.resume_calls = []
        self.recheck_calls = []

    def get_torrents_by_hashes(self, hashes):
        return {torrent_hash: self.torrents_by_hash[torrent_hash] for torrent_hash in hashes}

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
    def verify(self, torrent_path, candidate_path, report_path, *, timeout_seconds, quick_only):
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
        "patch_status": "pending",
        "resume_status": "pending",
        "cleanup_status": "pending",
        "cleanup_ready": False,
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
