from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3

from click.testing import CliRunner

from hashall.bencode import bencode_encode
from rehome.cli import cli
from rehome.reality import build_plan_reality_snapshot


class FakeQBClient:
    def __init__(self, torrents):
        self._by_hash = {str(item.hash).lower(): item for item in torrents}

    def get_torrent_info(self, torrent_hash):
        return self._by_hash.get(str(torrent_hash).lower())

    def get_torrents(self):
        return list(self._by_hash.values())


def _write_fastresume(path: Path, *, save_path: str, qbt_save_path: str) -> None:
    payload = {
        b"save_path": str(save_path).encode("utf-8"),
        b"qBt-savePath": str(qbt_save_path).encode("utf-8"),
        b"qBt-downloadPath": b"",
    }
    path.write_bytes(bencode_encode(payload))


def _make_catalog(path: Path, *, payload_root: str, save_path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE payloads (
                payload_id INTEGER PRIMARY KEY,
                payload_hash TEXT,
                device_id INTEGER,
                root_path TEXT,
                status TEXT
            );
            CREATE TABLE torrent_instances (
                torrent_hash TEXT PRIMARY KEY,
                payload_id INTEGER,
                device_id INTEGER,
                save_path TEXT,
                tags TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, status)
            VALUES (1, 'payload-1', 231, ?, 'complete')
            """,
            (payload_root,),
        )
        conn.execute(
            """
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
            VALUES ('abc123', 1, 231, ?, 'rehome')
            """,
            (save_path,),
        )
        conn.commit()
    finally:
        conn.close()


def _make_plan(source_root: Path, target_root: Path) -> dict:
    source_save = source_root.parent
    target_save = target_root.parent
    return {
        "direction": "demote",
        "decision": "MOVE",
        "payload_hash": "payload-1",
        "source_path": str(source_root),
        "target_path": str(target_root),
        "affected_torrents": ["abc123"],
        "view_targets": [
            {
                "torrent_hash": "abc123",
                "source_save_path": str(source_save),
                "target_save_path": str(target_save),
                "root_name": target_root.name,
            }
        ],
    }


def test_build_plan_reality_snapshot_classifies_stale_runtime_and_fastresume_root(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"old")
    target_root.write_bytes(b"new")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(source_root), save_path=str(source_root.parent))

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path=str(source_root.parent),
        qbt_save_path=str(source_root.parent),
    )

    qb = FakeQBClient(
        [
            SimpleNamespace(
                hash="abc123",
                name="Movie.mkv",
                state="stalledUP",
                progress=1.0,
                save_path=str(source_root.parent),
                content_path=str(source_root),
            )
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=_make_plan(source_root, target_root),
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
    )

    assert snapshot["group_state"] == "ready_repoint_or_reconcile"
    row = snapshot["rows"][0]
    assert row["classification"] == "stale_runtime_and_fastresume_root"
    assert "still pointing at the old source root" in row["operator_reason"]


def test_build_plan_reality_snapshot_classifies_catalog_drift_already_targeted(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"old")
    target_root.write_bytes(b"new")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(source_root), save_path=str(source_root.parent))

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path=str(target_root.parent),
        qbt_save_path=str(target_root.parent),
    )

    qb = FakeQBClient(
        [
            SimpleNamespace(
                hash="abc123",
                name="Movie.mkv",
                state="stalledUP",
                progress=1.0,
                save_path=str(target_root.parent),
                content_path=str(target_root),
            )
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=_make_plan(source_root, target_root),
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
    )

    assert snapshot["group_state"] == "ready_catalog_reconcile"
    row = snapshot["rows"][0]
    assert row["classification"] == "catalog_drift_already_targeted"
    assert "catalog still reflects older state" in row["operator_reason"]


def test_drift_audit_cli_prints_group_state(tmp_path, monkeypatch):
    source_root = tmp_path / "pool-data" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"old")
    target_root.write_bytes(b"new")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(source_root), save_path=str(source_root.parent))

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path=str(source_root.parent),
        qbt_save_path=str(source_root.parent),
    )

    plan = _make_plan(source_root, target_root)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"plans": [plan]}), encoding="utf-8")

    qb = FakeQBClient(
        [
            SimpleNamespace(
                hash="abc123",
                name="Movie.mkv",
                state="stalledUP",
                progress=1.0,
                save_path=str(source_root.parent),
                content_path=str(source_root),
            )
        ]
    )

    monkeypatch.setattr("rehome.cli.get_qbittorrent_client", lambda: qb, raising=False)
    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", lambda: qb)
    monkeypatch.setattr("rehome.cli._wait_for_qb_ready", lambda qbit: None)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "drift-audit",
            "--plan",
            str(plan_path),
            "--catalog",
            str(catalog),
            "--fastresume-dir",
            str(fastresume_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "ready_repoint_or_reconcile" in result.output
    assert "stale_runtime_and_fastresume_root" in result.output


def test_build_plan_reality_snapshot_classifies_move_source_only(tmp_path):
    source_root = tmp_path / "pool-data" / "thegeeks" / "Book.epub"
    target_root = tmp_path / "pool-media" / "thegeeks" / "Book.epub"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"book")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(source_root), save_path=str(source_root.parent))

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path=str(source_root.parent),
        qbt_save_path=str(source_root.parent),
    )

    qb = FakeQBClient(
        [
            SimpleNamespace(
                hash="abc123",
                name="Book.epub",
                state="stalledUP",
                progress=1.0,
                save_path=str(source_root.parent),
                content_path=str(source_root),
            )
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=_make_plan(source_root, target_root),
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
    )

    assert snapshot["group_state"] == "ready_repoint_or_reconcile"
    assert snapshot["rows"][0]["classification"] == "source_only"
