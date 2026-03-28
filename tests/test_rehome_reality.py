from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3

from click.testing import CliRunner

from hashall.bencode import bencode_dump, bencode_encode
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


def test_build_plan_reality_snapshot_classifies_legacy_runtime_root_when_catalog_already_targeted(tmp_path):
    source_root = tmp_path / "pool-media" / "_rehome-unique" / "abc123" / "Movie"
    target_root = source_root
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "Movie.mkv").write_bytes(b"new")

    legacy_runtime_root = tmp_path / "pool-media" / "cross-seed" / "seedpool (API)" / "Movie"
    legacy_runtime_root.mkdir(parents=True, exist_ok=True)
    (legacy_runtime_root / "Movie.mkv").write_bytes(b"old")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(legacy_runtime_root / "Movie.mkv"), save_path=str(source_root.parent))

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path=str(legacy_runtime_root.parent),
        qbt_save_path=str(legacy_runtime_root.parent),
    )

    plan = {
        "direction": "demote",
        "decision": "REUSE",
        "payload_hash": "payload-1",
        "source_path": str(source_root),
        "target_path": str(source_root),
        "affected_torrents": ["abc123"],
        "view_targets": [
            {
                "torrent_hash": "abc123",
                "source_save_path": str(source_root.parent),
                "target_save_path": str(source_root.parent),
                "root_name": source_root.name,
            }
        ],
    }

    qb = FakeQBClient(
        [
            SimpleNamespace(
                hash="abc123",
                name="Movie",
                state="missingFiles",
                progress=0.0,
                save_path=str(legacy_runtime_root.parent),
                content_path=str(legacy_runtime_root / "Movie.mkv"),
            )
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=plan,
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
    )

    assert snapshot["group_state"] == "ready_repoint_or_reconcile"
    row = snapshot["rows"][0]
    assert row["classification"] == "stale_runtime_and_fastresume_root"
    assert "stuck on an older runtime root" in row["operator_reason"]


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


def test_drift_audit_cli_reports_rt_drift(tmp_path, monkeypatch):
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

    rt_session_dir = tmp_path / "rt-session"
    rt_session_dir.mkdir()
    bencode_dump(
        rt_session_dir / "ABC123.torrent.rtorrent",
        {b"directory": str(source_root.parent).encode("utf-8")},
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
                save_path=str(target_root.parent),
                content_path=str(target_root),
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
            "--rt-session-dir",
            str(rt_session_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "rt_drift_rows: 1" in result.output
    assert "rt=drift" in result.output


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


def test_build_plan_reality_snapshot_treats_post_apply_transient_as_settling(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "Tracker" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "Tracker" / "Movie.mkv"
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
                state="checkingResumeData",
                progress=0.0,
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
        phase="post",
    )

    assert snapshot["group_state"] == "settling_after_apply"
    assert snapshot["rows"][0]["classification"] == "post_apply_settling"


def test_build_plan_reality_snapshot_keeps_preflight_transient_blocking(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "Tracker" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "Tracker" / "Movie.mkv"
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
                state="checkingResumeData",
                progress=0.0,
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
        phase="pre",
    )

    assert snapshot["group_state"] == "blocked_qbit_transient"
    assert snapshot["rows"][0]["classification"] == "qbit_transient"


def test_build_plan_reality_snapshot_reports_out_of_plan_siblings(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "Tracker" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "Tracker" / "Movie.mkv"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"old")
    target_root.write_bytes(b"new")

    catalog = tmp_path / "catalog.db"
    _make_catalog(catalog, payload_root=str(source_root), save_path=str(source_root.parent))
    conn = sqlite3.connect(catalog)
    try:
        conn.execute(
            """
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
            VALUES ('def456', 1, 231, ?, 'rehome')
            """,
            (str(source_root.parent),),
        )
        conn.commit()
    finally:
        conn.close()

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

    assert snapshot["summary"]["out_of_plan_siblings"] == 1
    assert snapshot["summary"]["payload_group_siblings"] == 2
    assert snapshot["out_of_plan_siblings"][0]["torrent_hash"] == "def456"
    assert snapshot["group_warnings"]


def test_build_plan_reality_snapshot_blocks_qbit_only_out_of_plan_siblings(tmp_path):
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
                size=3,
            ),
            SimpleNamespace(
                hash="orphan999",
                name="Movie.mkv",
                state="missingFiles",
                progress=0.0,
                save_path="/data/media/torrents/seeding/cross-seed/seedpool (API)",
                content_path="/data/media/torrents/seeding/cross-seed/seedpool (API)/Movie.mkv",
                size=3,
            ),
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=_make_plan(source_root, target_root) | {"total_bytes": 3},
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
    )

    assert snapshot["group_state"] == "blocked_qbit_sibling_gap"
    assert snapshot["summary"]["out_of_plan_siblings"] == 1
    assert snapshot["summary"]["qbit_out_of_plan_siblings"] == 1
    assert snapshot["out_of_plan_qbit_siblings"][0]["torrent_hash"] == "orphan999"
    assert any("same-name out-of-plan torrent" in warning for warning in snapshot["group_warnings"])


def test_build_plan_reality_snapshot_treats_same_batch_hashes_as_in_plan(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "Aither" / "EpisodeSet"
    target_root = tmp_path / "pool-media" / "cross-seed" / "Aither" / "EpisodeSet"
    source_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    (source_root / "ep1.mkv").write_bytes(b"a" * 8)

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
                name="EpisodeSet",
                state="stalledUP",
                progress=1.0,
                save_path=str(source_root.parent),
                content_path=str(source_root),
                size=8,
            ),
            SimpleNamespace(
                hash="sibling999",
                name="EpisodeSet",
                state="stalledUP",
                progress=1.0,
                save_path=str(source_root.parent),
                content_path=str(source_root),
                size=8,
            ),
        ]
    )

    snapshot = build_plan_reality_snapshot(
        plan=_make_plan(source_root, target_root) | {"total_bytes": 8},
        qb_client=qb,
        catalog_path=catalog,
        fastresume_dir=fastresume_dir,
        batch_torrent_hashes=["abc123", "sibling999"],
    )

    assert snapshot["group_state"] != "blocked_qbit_sibling_gap"
    assert snapshot["summary"]["out_of_plan_siblings"] == 0
    assert snapshot["summary"]["qbit_out_of_plan_siblings"] == 0


def test_build_plan_reality_snapshot_reports_legacy_shared_payload_rows(tmp_path):
    source_root = tmp_path / "pool-data" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    target_root = tmp_path / "pool-media" / "cross-seed" / "seedpool (API)" / "Movie.mkv"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    target_root.parent.mkdir(parents=True, exist_ok=True)
    source_root.write_bytes(b"old")
    target_root.write_bytes(b"new")

    catalog = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog)
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
            VALUES (1, 'payload-1', 141, ?, 'complete')
            """,
            (str(target_root),),
        )
        conn.executemany(
            """
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, tags)
            VALUES (?, 1, 141, ?, 'rehome')
            """,
            [
                ("abc123", str(target_root.parent)),
                ("def456", str(target_root.parent)),
            ],
        )
        conn.commit()
    finally:
        conn.close()

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

    assert snapshot["summary"]["shared_payload_rows"] == 1
    assert snapshot["summary"]["shared_payload_torrents"] == 2
    assert any("shared payload row(s)" in warning for warning in snapshot["group_warnings"])
    assert {row["torrent_hash"] for row in snapshot["shared_payload_members"]} == {"abc123", "def456"}
