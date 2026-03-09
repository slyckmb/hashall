from pathlib import Path
from types import SimpleNamespace
import sqlite3

from rehome.qb_missing import audit_missing_root_drift
from hashall.bencode import bencode_encode


class FakeQBClient:
    def __init__(self, torrents):
        self._torrents = torrents

    def get_torrents(self):
        return list(self._torrents)


def _write_fastresume(path: Path, *, save_path: str, qbt_save_path: str, qbt_download_path: str = "") -> None:
    payload = {
        b"save_path": str(save_path).encode("utf-8"),
        b"qBt-savePath": str(qbt_save_path).encode("utf-8"),
        b"qBt-downloadPath": str(qbt_download_path).encode("utf-8"),
    }
    path.write_bytes(bencode_encode(payload))


def _init_catalog(path: Path) -> None:
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
                payload_id INTEGER
            );
            CREATE TABLE rehome_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT,
                finished_at TEXT,
                direction TEXT,
                decision TEXT,
                payload_hash TEXT,
                status TEXT,
                source_path TEXT,
                target_path TEXT,
                cleanup_source_required INTEGER DEFAULT 0,
                cleanup_source_path TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, status) VALUES (1, ?, 231, ?, 'complete')",
            (
                "payload-1",
                "/pool/data/media/torrents/seeding/cross-seed/A/Title.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, 1)",
            ("abc123",),
        )
        conn.execute(
            """
            INSERT INTO rehome_runs (
                started_at, finished_at, direction, decision, payload_hash, status, source_path, target_path
            ) VALUES (
                '2026-02-20 00:00:00', '2026-02-20 00:00:01', 'demote', 'REUSE', ?, 'success', ?, ?
            )
            """,
            (
                "payload-1",
                "/pool/data/media/torrents/seeding/cross-seed/A/Title.mkv",
                "/pool/media/torrents/seeding/cross-seed/A/Title.mkv",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_audit_missing_root_drift_classifies_rehome_root_drift(tmp_path):
    catalog = tmp_path / "catalog.db"
    _init_catalog(catalog)

    target_path = tmp_path / "pool" / "media" / "torrents" / "seeding" / "cross-seed" / "A" / "Title.mkv"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"x")

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "abc123.fastresume",
        save_path="/pool/data/media/torrents/seeding/cross-seed/A",
        qbt_save_path="/pool/data/media/torrents/seeding/cross-seed/A",
    )

    torrents = [
        SimpleNamespace(
            hash="abc123",
            name="Title.mkv",
            state="missingFiles",
            progress=0.0,
            save_path="/pool/data/media/torrents/seeding/cross-seed/A",
            content_path="/pool/data/media/torrents/seeding/cross-seed/A/Title.mkv",
        )
    ]

    report = audit_missing_root_drift(
        qb_client=FakeQBClient(torrents),
        source_root="/pool/data/media/torrents/seeding",
        target_root=str(tmp_path / "pool" / "media" / "torrents" / "seeding"),
        fastresume_dir=fastresume_dir,
        catalog_path=catalog,
    )

    assert report["summary"]["rows"] == 1
    assert report["root_causes"] == {"root_drift_after_rehome_reuse": 1}
    row = report["rows"][0]
    assert row["mapped_target_exists"] is True
    assert row["fastresume_save_path"] == "/pool/data/media/torrents/seeding/cross-seed/A"
    assert row["latest_rehome_run"]["decision"] == "REUSE"


def test_audit_missing_root_drift_leaves_unclassified_without_mapped_target(tmp_path):
    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    torrents = [
        SimpleNamespace(
            hash="deadbeef",
            name="Broken",
            state="missingFiles",
            progress=0.0,
            save_path="/pool/data/media/torrents/seeding/movies",
            content_path="/pool/data/media/torrents/seeding/movies/Broken.mkv",
        )
    ]

    report = audit_missing_root_drift(
        qb_client=FakeQBClient(torrents),
        source_root="/pool/data/media/torrents/seeding",
        target_root="/pool/media/torrents/seeding",
        fastresume_dir=fastresume_dir,
        catalog_path=None,
    )

    assert report["summary"]["rows"] == 1
    assert report["root_causes"] == {"missing_payload_no_mapped_target": 1}
