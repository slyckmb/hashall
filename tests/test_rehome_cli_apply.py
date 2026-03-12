import json
from pathlib import Path
import sqlite3

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli
from hashall.bencode import bencode_encode


class _FakeExecutor:
    calls = []

    def __init__(self, catalog_path):
        self.catalog_path = catalog_path

    def dry_run(self, plan, **kwargs):
        type(self).calls.append(("dry_run", plan["payload_hash"], kwargs))

    def execute(self, plan, **kwargs):
        type(self).calls.append(("execute", plan["payload_hash"], kwargs))


def test_apply_accepts_batch_file_without_batch_marker(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    db_path.touch()

    plan_path = tmp_path / "batch.json"
    plan_path.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "payload_hash": "payload-1",
                        "decision": "MOVE",
                        "direction": "demote",
                        "affected_torrents": ["aaa"],
                        "source_path": "/old/root/one",
                        "target_path": "/new/root/one",
                    },
                    {
                        "payload_hash": "payload-2",
                        "decision": "REUSE",
                        "direction": "demote",
                        "affected_torrents": ["bbb"],
                        "source_path": "/old/root/two",
                        "target_path": "/new/root/two",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    _FakeExecutor.calls = []
    monkeypatch.setattr("rehome.cli.DemotionExecutor", _FakeExecutor)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "apply",
            str(plan_path),
            "--dryrun",
            "--catalog",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Batch plan: 2 payload(s)" in result.output
    assert _FakeExecutor.calls == [
        ("dry_run", "payload-1", {"cleanup_source_views": False, "cleanup_empty_dirs": False, "cleanup_duplicate_payload": False, "spot_check": 0}),
        ("dry_run", "payload-2", {"cleanup_source_views": False, "cleanup_empty_dirs": False, "cleanup_duplicate_payload": False, "spot_check": 0}),
    ]


def test_drift_audit_reports_out_of_plan_sibling_groups(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
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
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, status) VALUES (1, 'payload-1', 231, '/old/root/item', 'complete')"
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags) VALUES ('abc123', 1, 231, '/old/root', 'rehome')"
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags) VALUES ('def456', 1, 231, '/old/root', 'rehome')"
        )
        conn.commit()
    finally:
        conn.close()

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    (fastresume_dir / "abc123.fastresume").write_bytes(
        bencode_encode(
            {
                b"save_path": b"/old/root",
                b"qBt-savePath": b"/old/root",
                b"qBt-downloadPath": b"",
            }
        )
    )

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "plans": [
                    {
                        "payload_hash": "payload-1",
                        "decision": "MOVE",
                        "direction": "demote",
                        "source_path": "/old/root/item",
                        "target_path": "/new/root/item",
                        "affected_torrents": ["abc123"],
                        "view_targets": [
                            {
                                "torrent_hash": "abc123",
                                "source_save_path": "/old/root",
                                "target_save_path": "/new/root",
                                "root_name": "item",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeQB:
        def get_torrent_info(self, torrent_hash):
            from types import SimpleNamespace
            if str(torrent_hash).lower() != "abc123":
                return None
            return SimpleNamespace(
                hash="abc123",
                name="item",
                state="stalledUP",
                progress=1.0,
                save_path="/old/root",
                content_path="/old/root/item",
            )

    monkeypatch.setattr("rehome.cli.get_qbittorrent_client", lambda: FakeQB(), raising=False)
    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", lambda: FakeQB())
    monkeypatch.setattr("rehome.cli._wait_for_qb_ready", lambda qbit: None)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "drift-audit",
            "--plan",
            str(plan_path),
            "--catalog",
            str(db_path),
            "--fastresume-dir",
            str(fastresume_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "plans_with_out_of_plan_siblings: 1" in result.output
