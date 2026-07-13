import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from hashall.cli import cli
from hashall.incomplete_rehome import build_source_inode_manifest
from hashall.incomplete_rehome import build_incomplete_rehome_plan
from hashall.incomplete_rehome import build_incomplete_rehome_pilot_dryrun
from hashall.incomplete_rehome import build_plan_c_source_cleanup_dryrun
from hashall.incomplete_rehome import build_qb_snapshot_from_cache
from hashall.incomplete_rehome import build_rt_snapshot_from_cache
from hashall.incomplete_rehome import execute_plan_c_source_cleanup
from hashall.incomplete_rehome import execute_incomplete_rehome_pilot
from hashall.incomplete_rehome import expected_incomplete_piece_gate
from hashall.incomplete_rehome import validate_incomplete_rehome_post_pilot


def _make_catalog(tmp_path: Path) -> Path:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE files_49 (
            path TEXT NOT NULL,
            inode INTEGER NOT NULL,
            size INTEGER NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _insert_file(conn: sqlite3.Connection, path: Path, *, catalog_path: str | None = None) -> None:
    st = path.stat()
    conn.execute(
        "INSERT INTO files_49 (path, inode, size, status) VALUES (?, ?, ?, 'active')",
        (catalog_path or str(path), int(st.st_ino), int(st.st_size)),
    )


def test_source_inode_manifest_marks_repair_hardlink_as_cleanup_candidate(tmp_path: Path) -> None:
    db_path = _make_catalog(tmp_path)
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")

    stale = tmp_path / "data" / "media" / "torrents" / "seeding" / "_qb-finish" / "hash" / "Dexter.S02"
    stale.mkdir(parents=True)
    stale_file = stale / "episode.mkv"
    stale_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file)
    _insert_file(conn, stale_file)
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        target_roots=[tmp_path / "pool" / "media" / "torrents" / "seeding" / "speedcd" / "Dexter.S02"],
        library_roots=[],
    )

    assert manifest["summary"]["source_files"] == 1
    assert manifest["summary"]["catalog_matches"] == 2
    assert str(stale_file) in manifest["cleanup_candidates_after_verify"]
    assert str(source_file) not in manifest["cleanup_candidates_after_verify"]


def test_source_inode_manifest_resolves_relative_catalog_cleanup_paths(monkeypatch, tmp_path: Path) -> None:
    data_media = tmp_path / "data" / "media"
    monkeypatch.setattr("hashall.incomplete_rehome.CATALOG_RELATIVE_ROOTS", (str(data_media),))
    db_path = _make_catalog(tmp_path)
    source = data_media / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    stale = data_media / "torrents" / "seeding" / "_qb-finish" / "hash" / "Dexter.S02"
    stale.mkdir(parents=True)
    stale_file = stale / "episode.mkv"
    stale_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file, catalog_path="torrents/seeding/SpeedCD/Dexter.S02/episode.mkv")
    _insert_file(conn, stale_file, catalog_path="torrents/seeding/_qb-finish/hash/Dexter.S02/episode.mkv")
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        library_roots=[],
    )

    assert "torrents/seeding/_qb-finish/hash/Dexter.S02/episode.mkv" in manifest["cleanup_candidates_after_verify"]
    assert str(stale_file) in manifest["existing_cleanup_paths_after_verify"]
    refs = [
        row for row in manifest["catalog_inode_refs"]
        if row["path"] == "torrents/seeding/_qb-finish/hash/Dexter.S02/episode.mkv"
    ]
    assert refs[0]["existing_cleanup_paths_after_verify"] == [str(stale_file)]


def test_source_inode_manifest_groups_data_stash_alias_cleanup_paths(monkeypatch, tmp_path: Path) -> None:
    data_media = tmp_path / "data" / "media"
    stash_media = tmp_path / "stash" / "media"
    monkeypatch.setattr(
        "hashall.incomplete_rehome.CATALOG_RELATIVE_ROOTS",
        (str(data_media), str(stash_media)),
    )
    db_path = _make_catalog(tmp_path)
    source = data_media / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    data_stale = data_media / "torrents" / "seeding" / "_qb-finish" / "hash" / "Dexter.S02"
    stash_stale = stash_media / "torrents" / "seeding" / "_qb-finish" / "hash" / "Dexter.S02"
    data_stale.mkdir(parents=True)
    stash_stale.mkdir(parents=True)
    data_stale_file = data_stale / "episode.mkv"
    stash_stale_file = stash_stale / "episode.mkv"
    data_stale_file.hardlink_to(source_file)
    stash_stale_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file, catalog_path="torrents/seeding/SpeedCD/Dexter.S02/episode.mkv")
    _insert_file(conn, data_stale_file, catalog_path="torrents/seeding/_qb-finish/hash/Dexter.S02/episode.mkv")
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        library_roots=[],
    )

    groups = manifest["cleanup_path_groups_after_verify"]
    assert len(groups) == 1
    assert groups[0]["paths"] == sorted([str(data_stale_file), str(stash_stale_file)])
    assert groups[0]["delete_paths_after_verify"] == [str(data_stale_file)]
    assert manifest["delete_paths_after_verify"] == [str(data_stale_file)]


def test_source_inode_manifest_keeps_distinct_stale_hardlink_delete_paths(monkeypatch, tmp_path: Path) -> None:
    data_media = tmp_path / "data" / "media"
    stash_media = tmp_path / "stash" / "media"
    monkeypatch.setattr(
        "hashall.incomplete_rehome.CATALOG_RELATIVE_ROOTS",
        (str(data_media), str(stash_media)),
    )
    db_path = _make_catalog(tmp_path)
    source = data_media / "torrents" / "seeding" / "SpeedCD" / "Dexter.S07"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    finish = data_media / "torrents" / "seeding" / "_qb-finish" / "hash"
    recycle = data_media / "torrents" / "seeding" / "cross-seed" / "SpeedCD" / "RecycleBin" / "Dexter.S07"
    finish.mkdir(parents=True)
    recycle.mkdir(parents=True)
    finish_file = finish / "episode.mkv"
    recycle_file = recycle / "episode.mkv"
    finish_file.hardlink_to(source_file)
    recycle_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file, catalog_path="torrents/seeding/SpeedCD/Dexter.S07/episode.mkv")
    _insert_file(conn, finish_file, catalog_path="torrents/seeding/_qb-finish/hash/episode.mkv")
    _insert_file(conn, recycle_file, catalog_path="torrents/seeding/cross-seed/SpeedCD/RecycleBin/Dexter.S07/episode.mkv")
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        library_roots=[],
    )

    assert sorted(manifest["delete_paths_after_verify"]) == sorted([str(finish_file), str(recycle_file)])
    assert len(manifest["cleanup_path_groups_after_verify"]) == 1
    assert sorted(manifest["cleanup_path_groups_after_verify"][0]["delete_paths_after_verify"]) == sorted(
        [str(finish_file), str(recycle_file)]
    )


def test_source_inode_manifest_protects_library_anchor_even_with_repair_marker(tmp_path: Path) -> None:
    db_path = _make_catalog(tmp_path)
    source = tmp_path / "stash" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S07"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")

    library = tmp_path / "stash" / "media" / "tv" / "Dexter" / "Season 07"
    library.mkdir(parents=True)
    library_file = library / "_qb-finish episode.mkv"
    library_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file)
    _insert_file(conn, library_file)
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        library_roots=[str(tmp_path / "stash" / "media" / "tv")],
    )

    library_refs = [
        row for row in manifest["catalog_inode_refs"] if row["path"] == str(library_file)
    ]
    assert library_refs
    assert library_refs[0]["is_library_anchor"] is True
    assert str(library_file) not in manifest["cleanup_candidates_after_verify"]


def test_source_inode_manifest_protects_relative_library_anchor(monkeypatch, tmp_path: Path) -> None:
    stash_media = tmp_path / "stash" / "media"
    monkeypatch.setattr("hashall.incomplete_rehome.CATALOG_RELATIVE_ROOTS", (str(stash_media),))
    db_path = _make_catalog(tmp_path)
    source = stash_media / "torrents" / "seeding" / "SpeedCD" / "Dexter.S07"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    library = stash_media / "tv" / "Dexter" / "Season 07"
    library.mkdir(parents=True)
    library_file = library / "_qb-finish episode.mkv"
    library_file.hardlink_to(source_file)

    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file, catalog_path="torrents/seeding/SpeedCD/Dexter.S07/episode.mkv")
    _insert_file(conn, library_file, catalog_path="tv/Dexter/Season 07/_qb-finish episode.mkv")
    conn.commit()
    conn.close()

    manifest = build_source_inode_manifest(
        source_roots=[source],
        catalog_path=db_path,
        library_roots=[str(stash_media / "tv")],
    )

    refs = [
        row for row in manifest["catalog_inode_refs"]
        if row["path"] == "tv/Dexter/Season 07/_qb-finish episode.mkv"
    ]
    assert refs[0]["is_library_anchor"] is True
    assert "tv/Dexter/Season 07/_qb-finish episode.mkv" not in manifest["cleanup_candidates_after_verify"]


def test_cli_source_inode_manifest_writes_json(tmp_path: Path) -> None:
    db_path = _make_catalog(tmp_path)
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file)
    conn.commit()
    conn.close()

    output = tmp_path / "manifest.json"
    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "source-inode-manifest",
            "--source-root",
            str(source),
            "--catalog",
            str(db_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema"] == "hashall.incomplete_rehome.source_inode_manifest.v1"
    assert data["summary"]["source_files"] == 1


def test_expected_incomplete_piece_gate_accepts_single_boundary_piece() -> None:
    result = SimpleNamespace(
        pieces_fail=1,
        pieces_missing=0,
        failed_pieces=[
            SimpleNamespace(
                piece_index=0,
                status="mismatch",
                classification="sidecar_media_boundary_piece",
            )
        ],
    )

    gate = expected_incomplete_piece_gate(result)

    assert gate["ok"] is True
    assert gate["failed_piece_indexes"] == [0]


def test_expected_incomplete_piece_gate_accepts_verify_json_dict() -> None:
    result = {
        "pieces_fail": 1,
        "pieces_missing": 0,
        "failed_pieces": [
            {
                "piece_index": 0,
                "status": "mismatch",
                "classification": "sidecar_media_boundary_piece",
            }
        ],
    }

    gate = expected_incomplete_piece_gate(result)

    assert gate["ok"] is True


def test_expected_incomplete_piece_gate_rejects_complete_verify() -> None:
    result = SimpleNamespace(pieces_fail=0, pieces_missing=0, failed_pieces=[])

    gate = expected_incomplete_piece_gate(result)

    assert gate["ok"] is False
    assert gate["reasons"] == ["verify_is_complete"]


def test_expected_incomplete_piece_gate_rejects_unexpected_media_piece() -> None:
    result = SimpleNamespace(
        pieces_fail=1,
        pieces_missing=0,
        failed_pieces=[
            SimpleNamespace(
                piece_index=12,
                status="mismatch",
                classification="media_piece_mismatch",
            )
        ],
    )

    gate = expected_incomplete_piece_gate(result)

    assert gate["ok"] is False
    assert "unexpected_piece:12" in gate["reasons"]
    assert "unexpected_classification:media_piece_mismatch" in gate["reasons"]


def test_incomplete_rehome_plan_ready_for_missing_target(tmp_path: Path) -> None:
    db_path = _make_catalog(tmp_path)
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    conn = sqlite3.connect(db_path)
    _insert_file(conn, source_file)
    conn.commit()
    conn.close()

    plan = build_incomplete_rehome_plan(
        torrent_hash="245f",
        source_roots=[source],
        target_root=tmp_path / "pool" / "media" / "torrents" / "seeding" / "speedcd" / "Dexter.S02",
        catalog_path=db_path,
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    assert plan["status"] == "ready_for_pilot"
    assert plan["target"]["class"] == "missing"
    assert plan["copy_plan"]["argv"][0:2] == ["rsync", "-aHAX"]
    assert plan["cleanup_gate"]["delete_before_verify"] is False


def test_incomplete_rehome_plan_blocks_nonzero_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.mkv").write_bytes(b"other")

    plan = build_incomplete_rehome_plan(
        torrent_hash="245f",
        source_roots=[source],
        target_root=target,
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    assert plan["status"] == "blocked"
    assert "target_contains_nonzero_files" in plan["blockers"]


def test_incomplete_rehome_plan_warns_when_qb_save_path_equals_payload_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "pool" / "Release"

    plan = build_incomplete_rehome_plan(
        torrent_hash="245f",
        source_roots=[source],
        target_root=target,
        qb_save_path=str(target),
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    assert "qb_save_path_equals_payload_root_may_create_nested_content_path" in plan["warnings"]


def test_incomplete_rehome_pilot_dryrun_emits_plan_c_sequences(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553",
        source_roots=[source],
        target_root=target,
        qb_save_path=str(target.parent),
        rt_target_directory=str(target),
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)

    assert pilot["status"] == "ready_for_live_approval"
    rt_operation = [op for op in pilot["operations"] if op["phase"] == "rt"][0]
    qb_operation = [op for op in pilot["operations"] if op["phase"] == "qb"][0]
    assert rt_operation["xmlrpc_sequence"][-3:] == ["d.open", "d.check_hash", "d.start"]
    assert "set_location(resume_after=False)" in qb_operation["api_sequence"]
    assert qb_operation["api_sequence"][-1] == "pause_torrent"


def test_incomplete_rehome_pilot_dryrun_refuses_blocked_plan(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.mkv").write_bytes(b"nonzero")
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553",
        source_roots=[source],
        target_root=target,
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)

    assert pilot["status"] == "blocked"
    assert "target_contains_nonzero_files" in pilot["blockers"]


def test_incomplete_rehome_pilot_execute_defaults_to_dry_run(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553b12dc1",
        source_roots=[source],
        target_root=target,
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )
    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)
    calls = []

    report = execute_incomplete_rehome_pilot(
        pilot=pilot,
        run_func=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert report["status"] == "dry_run_ready"
    assert calls == []


def test_incomplete_rehome_pilot_execute_blocks_apply_without_approval(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553b12dc1",
        source_roots=[source],
        target_root=target,
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )
    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)
    calls = []

    report = execute_incomplete_rehome_pilot(
        pilot=pilot,
        apply=True,
        approval="approve something vague",
        run_func=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert report["status"] == "blocked"
    assert "approval_string_missing_plan_c_hash_no_cleanup" in report["blockers"]
    assert calls == []


def test_incomplete_rehome_pilot_execute_mocked_apply_sequence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553b12dc1",
        source_roots=[source],
        target_root=target,
        qb_save_path=str(target.parent),
        rt_target_directory=str(target),
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )
    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)
    run_calls = []
    rt_calls = []

    class FakeQbit:
        def __init__(self) -> None:
            self.calls = []

        def pause_torrent(self, torrent_hash):
            self.calls.append(("pause", torrent_hash))
            return True

        def set_location(self, torrent_hash, save_path, resume_after=True):
            self.calls.append(("set_location", torrent_hash, save_path, resume_after))
            return True

        def recheck_torrent(self, torrent_hash):
            self.calls.append(("recheck", torrent_hash))
            return True

    fake_qbit = FakeQbit()

    report = execute_incomplete_rehome_pilot(
        pilot=pilot,
        apply=True,
        approval="approve Plan C e36553b12dc1 no cleanup",
        qbit_client=fake_qbit,
        rt_repoint_func=lambda *args, **kwargs: rt_calls.append(("repoint", args, kwargs)),
        rt_start_func=lambda *args, **kwargs: rt_calls.append(("xmlrpc", args, kwargs)),
        run_func=lambda *args, **kwargs: run_calls.append((args, kwargs)),
    )

    assert report["status"] == "applied_no_cleanup"
    assert run_calls
    assert rt_calls[0][0] == "repoint"
    assert [call[1][0] for call in rt_calls[1:]] == ["d.check_hash", "d.start"]
    assert [call[0] for call in fake_qbit.calls] == ["pause", "set_location", "recheck", "pause"]
    assert fake_qbit.calls[1][-1] is False


def test_incomplete_rehome_post_validate_accepts_expected_waiting_states(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.mkv").write_bytes(b"payload")
    target = tmp_path / "target"
    target.mkdir()
    plan = build_incomplete_rehome_plan(
        torrent_hash="e36553b12dc1",
        source_roots=[source],
        target_root=target,
        qb_save_path=str(target.parent),
        rt_target_directory=str(target),
        verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )
    pilot = build_incomplete_rehome_pilot_dryrun(plan=plan)
    execute_report = {
        "status": "applied_no_cleanup",
        "hash": "e36553b12dc1",
        "pilot": pilot,
    }

    report = validate_incomplete_rehome_post_pilot(
        execute_report=execute_report,
        target_verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
        qb_snapshot={
            "state": "stoppedDL",
            "save_path": str(target.parent),
            "progress": 0.999,
            "amount_left": 2097152,
        },
        rt_snapshot={
            "state": "stalledDL",
            "directory": str(target),
            "complete": 0,
            "left_bytes": 2097152,
        },
    )

    assert report["status"] == "validated_ready_for_cleanup_approval"
    assert report["blockers"] == []
    assert report["target_verify_gate"]["ok"] is True


def test_incomplete_rehome_post_validate_blocks_unapplied_execute_report(tmp_path: Path) -> None:
    pilot = {
        "hash": "e36553b12dc1",
        "operations": [],
        "cleanup_gate": {},
    }

    report = validate_incomplete_rehome_post_pilot(
        execute_report={"status": "dry_run_ready", "hash": "e36553b12dc1", "pilot": pilot},
        target_verify_result={
            "pieces_fail": 1,
            "pieces_missing": 0,
            "failed_pieces": [
                {
                    "piece_index": 0,
                    "status": "mismatch",
                    "classification": "sidecar_media_boundary_piece",
                }
            ],
        },
    )

    assert report["status"] == "blocked"
    assert "execute_not_applied:dry_run_ready" in report["blockers"]


def test_build_qb_snapshot_from_cache_extracts_validator_fields(tmp_path: Path) -> None:
    cache = tmp_path / "qb.json"
    cache.write_text(
        json.dumps(
            [
                {
                    "hash": "245f2bce6afaf96b0a48ad216366c4281fdd864f",
                    "name": "Dexter.S02.720p.x265-ZMNT",
                    "state": "stoppedDL",
                    "save_path": "/pool/media/torrents/seeding/cross-seed/speedcd",
                    "content_path": "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S02.720p.x265-ZMNT",
                    "progress": 0.9997,
                    "amount_left": 2097152,
                    "num_seeds": 0,
                    "num_leechs": 0,
                }
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_qb_snapshot_from_cache(torrent_hash="245f2bce6afa", cache_file=cache)

    assert snapshot["schema"] == "hashall.incomplete_rehome.qb_snapshot.v1"
    assert snapshot["status"] == "found"
    assert snapshot["state"] == "stoppedDL"
    assert snapshot["save_path"] == "/pool/media/torrents/seeding/cross-seed/speedcd"
    assert snapshot["amount_left"] == 2097152


def test_build_rt_snapshot_from_cache_extracts_validator_fields(tmp_path: Path) -> None:
    cache = tmp_path / "rt.json"
    cache.write_text(
        json.dumps(
            [
                {
                    "hash": "e36553b12dc118d8c52575a1d6711532882ae1c3",
                    "name": "Dexter.S07.720p.x265-ZMNT",
                    "state": "stalledDL",
                    "save_path": "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S07.720p.x265-ZMNT",
                    "progress_pct": 99.96,
                    "size": 5757836898,
                    "seeds": 0,
                    "peers": 0,
                    "tracker": "speedcd",
                }
            ]
        ),
        encoding="utf-8",
    )

    snapshot = build_rt_snapshot_from_cache(torrent_hash="e36553b12dc1", cache_file=cache)

    assert snapshot["schema"] == "hashall.incomplete_rehome.rt_snapshot.v1"
    assert snapshot["status"] == "found"
    assert snapshot["state"] == "stalledDL"
    assert snapshot["directory"] == "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S07.720p.x265-ZMNT"
    assert snapshot["complete"] is False
    assert snapshot["left_bytes"] > 0


def test_cli_incomplete_rehome_snapshot_writes_qb_json(tmp_path: Path) -> None:
    cache = tmp_path / "qb.json"
    cache.write_text(
        json.dumps(
            [
                {
                    "hash": "245f2bce6afaf96b0a48ad216366c4281fdd864f",
                    "name": "Dexter.S02.720p.x265-ZMNT",
                    "state": "stoppedDL",
                    "save_path": "/pool/media/torrents/seeding/cross-seed/speedcd",
                    "content_path": "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S02.720p.x265-ZMNT",
                    "progress": 0.9997,
                    "amount_left": 2097152,
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "snapshot.json"

    result = CliRunner().invoke(
        cli,
        [
            "client-drift",
            "incomplete-rehome-snapshot",
            "245f2bce6afa",
            "--side",
            "qb",
            "--qb-cache-file",
            str(cache),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema"] == "hashall.incomplete_rehome.qb_snapshot.v1"
    assert data["state"] == "stoppedDL"


def test_plan_c_source_cleanup_blocks_exact_client_reference(tmp_path: Path) -> None:
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    qb_cache.write_text(
        json.dumps(
            [
                {
                    "hash": "clienthash",
                    "name": "Dexter.S02",
                    "state": "stoppedUP",
                    "content_path": str(source),
                    "root_path": str(source),
                }
            ]
        ),
        encoding="utf-8",
    )
    rt_cache.write_text("[]", encoding="utf-8")
    plan = {
        "hash": "245f",
        "source_inode_manifest": {
            "catalog_inode_refs": [
                {
                    "path": str(source_file),
                    "inode": source_file.stat().st_ino,
                    "is_library_anchor": False,
                    "existing_path_aliases": [str(source_file)],
                }
            ]
        },
    }
    post = {"status": "validated_ready_for_cleanup_approval", "target_verify_gate": {"ok": True}}

    report = build_plan_c_source_cleanup_dryrun(
        plan=plan,
        post_validate=post,
        source_roots=[source],
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        library_roots=[],
    )

    assert report["status"] == "blocked"
    assert report["roots"][0]["blockers"] == ["exact_client_reference_present"]
    assert report["roots"][0]["exact_client_hits"][0]["side"] == "qb"


def test_plan_c_source_cleanup_allows_unreferenced_source_root(tmp_path: Path) -> None:
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    source_file = source / "episode.mkv"
    source_file.write_bytes(b"payload")
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text("[]", encoding="utf-8")
    plan = {
        "hash": "245f",
        "source_inode_manifest": {
            "catalog_inode_refs": [
                {
                    "path": str(source_file),
                    "inode": source_file.stat().st_ino,
                    "is_library_anchor": False,
                    "existing_path_aliases": [str(source_file)],
                }
            ]
        },
    }
    post = {"status": "validated_ready_for_cleanup_approval", "target_verify_gate": {"ok": True}}

    report = build_plan_c_source_cleanup_dryrun(
        plan=plan,
        post_validate=post,
        source_roots=[source],
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        library_roots=[],
    )

    assert report["status"] == "ready_for_source_cleanup_approval"
    assert report["roots"][0]["delete_root_after_approval"] == str(source)


def test_plan_c_source_cleanup_execute_previews_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    (source / "episode.mkv").write_bytes(b"payload")
    dryrun = {
        "schema": "hashall.incomplete_rehome.source_cleanup_dryrun.v1",
        "mode": "read_only",
        "hash": "245f2bce6afaf96b0a48ad216366c4281fdd864f",
        "status": "ready_for_source_cleanup_approval",
        "target_verify_gate_ok": True,
        "roots": [
            {
                "source_root": str(source),
                "status": "eligible_for_source_cleanup_approval",
                "blockers": [],
                "exact_client_hits": [],
                "library_hits": [],
                "delete_root_after_approval": str(source),
            }
        ],
    }
    calls = []

    report = execute_plan_c_source_cleanup(
        dryrun=dryrun,
        delete_func=lambda path: calls.append(path),
        min_depth=1,
    )

    assert report["status"] == "dry_run_ready"
    assert calls == []
    assert source.exists()


def test_plan_c_source_cleanup_execute_blocks_apply_without_precise_approval(tmp_path: Path) -> None:
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    (source / "episode.mkv").write_bytes(b"payload")
    dryrun = {
        "schema": "hashall.incomplete_rehome.source_cleanup_dryrun.v1",
        "mode": "read_only",
        "hash": "245f2bce6afaf96b0a48ad216366c4281fdd864f",
        "status": "ready_for_source_cleanup_approval",
        "target_verify_gate_ok": True,
        "roots": [
            {
                "source_root": str(source),
                "status": "eligible_for_source_cleanup_approval",
                "blockers": [],
                "exact_client_hits": [],
                "library_hits": [],
                "delete_root_after_approval": str(source),
            }
        ],
    }
    calls = []

    report = execute_plan_c_source_cleanup(
        dryrun=dryrun,
        apply=True,
        approval="approve cleanup",
        delete_func=lambda path: calls.append(path),
        min_depth=1,
    )

    assert report["status"] == "blocked"
    assert "approval_string_missing_plan_c_source_cleanup_delete_hash_path" in report["blockers"]
    assert calls == []
    assert source.exists()


def test_plan_c_source_cleanup_execute_deletes_approved_root(tmp_path: Path) -> None:
    source = tmp_path / "data" / "media" / "torrents" / "seeding" / "SpeedCD" / "Dexter.S02"
    source.mkdir(parents=True)
    (source / "episode.mkv").write_bytes(b"payload")
    dryrun = {
        "schema": "hashall.incomplete_rehome.source_cleanup_dryrun.v1",
        "mode": "read_only",
        "hash": "245f2bce6afaf96b0a48ad216366c4281fdd864f",
        "status": "ready_for_source_cleanup_approval",
        "target_verify_gate_ok": True,
        "roots": [
            {
                "source_root": str(source),
                "status": "eligible_for_source_cleanup_approval",
                "blockers": [],
                "exact_client_hits": [],
                "library_hits": [],
                "delete_root_after_approval": str(source),
            }
        ],
    }

    report = execute_plan_c_source_cleanup(
        dryrun=dryrun,
        apply=True,
        approval=f"approve Plan C source cleanup delete 245f2bce6afa {source}",
        min_depth=1,
    )

    assert report["status"] == "deleted"
    assert report["events"][0]["status"] == "deleted"
    assert not source.exists()
