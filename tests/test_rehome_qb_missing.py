from pathlib import Path
from types import SimpleNamespace
import sqlite3

from rehome.qb_missing import audit_missing_root_drift, build_missing_sibling_reconnect_batch
from rehome.executor import DemotionExecutor
from hashall.bencode import bencode_encode


class FakeQBClient:
    def __init__(self, torrents):
        self._torrents = torrents
        self._by_hash = {str(t.hash).lower(): t for t in torrents}

    def get_torrents(self):
        return list(self._torrents)

    def get_torrent_info(self, torrent_hash):
        return self._by_hash.get(str(torrent_hash).lower())

    def get_torrent_files(self, torrent_hash):
        return [SimpleNamespace(name="dummy", size=1)]


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


def test_audit_missing_root_drift_classifies_surviving_sibling_target(tmp_path):
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
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, status) VALUES (1, ?, 44, ?, 'complete')",
            (
                "payload-sibling",
                "/stash/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, status) VALUES (2, ?, 141, ?, 'complete')",
            (
                "payload-sibling",
                "/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, 1)",
            ("deadbeef",),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, 2)",
            ("goodcafe",),
        )
        conn.commit()
    finally:
        conn.close()

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "deadbeef.fastresume",
        save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
        qbt_save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
    )

    torrents = [
        SimpleNamespace(
            hash="deadbeef",
            name="Cleverman",
            state="missingFiles",
            progress=0.0,
            save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
            content_path="/data/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
        ),
        SimpleNamespace(
            hash="goodcafe",
            name="Cleverman",
            state="stalledUP",
            progress=1.0,
            save_path="/pool/media/torrents/seeding/cross-seed/Aither (API)",
            content_path="/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
        ),
    ]

    report = audit_missing_root_drift(
        qb_client=FakeQBClient(torrents),
        source_root="/data/media/torrents/seeding",
        target_root="/pool/media/torrents/seeding",
        fastresume_dir=fastresume_dir,
        catalog_path=catalog,
    )

    assert report["summary"]["rows"] == 1
    assert report["root_causes"] == {"root_drift_to_surviving_sibling_target": 1}
    row = report["rows"][0]
    assert row["payload_hash"] == "payload-sibling"
    assert row["mapped_target_exists"] is False
    assert row["sibling_target_count"] == 1
    assert row["sibling_targets"] == [
        {
            "torrent_hash": "goodcafe",
            "save_path": "/pool/media/torrents/seeding/cross-seed/Aither (API)",
            "root_path": "/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
            "ti_device_id": 0,
            "payload_device_id": 141,
            "status": "complete",
            "qb_state": "stalledUP",
            "qb_progress": 1.0,
            "healthy": True,
        }
    ]


def test_build_missing_sibling_reconnect_batch_builds_reuse_plan_with_unique_views(tmp_path):
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
                file_count INTEGER,
                total_bytes INTEGER,
                status TEXT
            );
            CREATE TABLE torrent_instances (
                torrent_hash TEXT PRIMARY KEY,
                payload_id INTEGER,
                device_id INTEGER,
                save_path TEXT,
                root_name TEXT
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
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (1, ?, 44, ?, 1, 123, 'complete')",
            (
                "payload-reconnect",
                "/stash/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (2, ?, 141, ?, 1, 123, 'complete')",
            (
                "payload-reconnect",
                "/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 1, 44, ?, ?)",
            (
                "deadbeef",
                "/data/media/torrents/seeding/cross-seed/PrivateHD",
                "Cleverman.S02",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 1, 44, ?, ?)",
            (
                "badf00d",
                "/data/media/torrents/seeding/cross-seed/PrivateHD",
                "Cleverman.S02",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 2, 141, ?, ?)",
            (
                "goodcafe",
                "/pool/media/torrents/seeding/cross-seed/Aither (API)",
                "Cleverman.S02",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "deadbeef.fastresume",
        save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
        qbt_save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
    )
    _write_fastresume(
        fastresume_dir / "badf00d.fastresume",
        save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
        qbt_save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
    )

    torrents = [
        SimpleNamespace(
            hash="deadbeef",
            name="Cleverman",
            state="missingFiles",
            progress=0.0,
            save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
            content_path="/data/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
        ),
        SimpleNamespace(
            hash="badf00d",
            name="Cleverman",
            state="missingFiles",
            progress=0.0,
            save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
            content_path="/data/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
        ),
        SimpleNamespace(
            hash="goodcafe",
            name="Cleverman",
            state="stalledUP",
            progress=1.0,
            save_path="/pool/media/torrents/seeding/cross-seed/Aither (API)",
            content_path="/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
        ),
    ]

    report = build_missing_sibling_reconnect_batch(
        qb_client=FakeQBClient(torrents),
        source_root="/data/media/torrents/seeding",
        target_root="/pool/media/torrents/seeding",
        fastresume_dir=fastresume_dir,
        catalog_path=catalog,
    )

    assert report["summary"]["plans"] == 1
    assert report["summary"]["unique_view_targets"] == 1
    plan = report["plans"][0]
    assert plan["decision"] == "REUSE"
    assert plan["payload_hash"] == "payload-reconnect"
    assert plan["target_path"] == "/pool/media/torrents/seeding/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv"
    assert plan["affected_torrents"] == ["badf00d", "deadbeef"]
    assert plan["normalization"]["mode"] == "qb_missing_sibling_reconnect"
    assert plan["normalization"]["view_collisions"] == 1
    assert plan["normalization"]["unique_view_targets"] == 1
    assert plan["view_targets"] == [
        {
            "torrent_hash": "badf00d",
            "source_save_path": "/data/media/torrents/seeding/cross-seed/PrivateHD",
            "target_save_path": "/pool/media/torrents/seeding/cross-seed/PrivateHD",
            "root_name": "Cleverman.S02",
        },
        {
            "torrent_hash": "deadbeef",
            "source_save_path": "/data/media/torrents/seeding/cross-seed/PrivateHD",
            "target_save_path": "/pool/media/torrents/seeding/_rehome-unique/deadbeef",
            "root_name": "Cleverman.S02",
        },
    ]


def test_build_missing_sibling_reconnect_batch_includes_fastresume_stale_rows_with_siblings(tmp_path):
    target_root = str(tmp_path / "pool" / "media" / "torrents" / "seeding")
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
                file_count INTEGER,
                total_bytes INTEGER,
                status TEXT
            );
            CREATE TABLE torrent_instances (
                torrent_hash TEXT PRIMARY KEY,
                payload_id INTEGER,
                device_id INTEGER,
                save_path TEXT,
                root_name TEXT
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
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (1, ?, 44, ?, 1, 123, 'complete')",
            (
                "payload-reconnect",
                "/stash/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (2, ?, 141, ?, 1, 123, 'complete')",
            (
                "payload-reconnect",
                f"{target_root}/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 1, 44, ?, ?)",
            (
                "deadbeef",
                "/data/media/torrents/seeding/cross-seed/PrivateHD",
                "Cleverman.S02",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 2, 141, ?, ?)",
            (
                "goodcafe",
                f"{target_root}/cross-seed/Aither (API)",
                "Cleverman.S02",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    mapped_target = Path(target_root) / "cross-seed" / "PrivateHD" / "Cleverman.S02" / "Movie.mkv"
    mapped_target.parent.mkdir(parents=True, exist_ok=True)
    mapped_target.write_bytes(b"x")

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "deadbeef.fastresume",
        save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
        qbt_save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
    )

    torrents = [
        SimpleNamespace(
            hash="deadbeef",
            name="Cleverman",
            state="missingFiles",
            progress=0.0,
            save_path="/data/media/torrents/seeding/cross-seed/PrivateHD",
            content_path="/data/media/torrents/seeding/cross-seed/PrivateHD/Cleverman.S02/Movie.mkv",
        ),
        SimpleNamespace(
            hash="goodcafe",
            name="Cleverman",
            state="stalledUP",
            progress=1.0,
            save_path=f"{target_root}/cross-seed/Aither (API)",
            content_path=f"{target_root}/cross-seed/Aither (API)/Cleverman.S02/Movie.mkv",
        ),
    ]

    report = build_missing_sibling_reconnect_batch(
        qb_client=FakeQBClient(torrents),
        source_root="/data/media/torrents/seeding",
        target_root=target_root,
        fastresume_dir=fastresume_dir,
        catalog_path=catalog,
    )

    assert report["summary"]["plans"] == 1
    assert report["plans"][0]["payload_hash"] == "payload-reconnect"


def test_build_missing_sibling_reconnect_batch_reuses_mapped_target_after_rehome_reuse(tmp_path):
    target_root = str(tmp_path / "pool" / "data" / "media" / "torrents" / "seeding")
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
                file_count INTEGER,
                total_bytes INTEGER,
                status TEXT
            );
            CREATE TABLE torrent_instances (
                torrent_hash TEXT PRIMARY KEY,
                payload_id INTEGER,
                device_id INTEGER,
                save_path TEXT,
                root_name TEXT
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
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (1, ?, 44, ?, 1, 123, 'complete')",
            (
                "payload-old",
                "/stash/media/torrents/seeding/cross-seed/seedpool (API)/Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status) VALUES (2, ?, 49, ?, 1, 123, 'complete')",
            (
                "payload-new",
                f"{target_root}/cross-seed/seedpool (API)/Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
            ),
        )
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name) VALUES (?, 1, 44, ?, ?)",
            (
                "deadbeef",
                "/data/media/torrents/seeding/cross-seed/seedpool (API)",
                "Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
            ),
        )
        conn.execute(
            """
            INSERT INTO rehome_runs (
                started_at, finished_at, direction, decision, payload_hash, status, source_path, target_path
            ) VALUES (
                '2026-02-21 00:00:00', '2026-02-21 00:00:01', 'demote', 'REUSE', ?, 'success', ?, ?
            )
            """,
            (
                "payload-old",
                "/data/media/torrents/seeding/cross-seed/seedpool (API)/Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
                f"{target_root}/cross-seed/seedpool (API)/Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    mapped_target = Path(target_root) / "cross-seed" / "seedpool (API)" / "Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv"
    mapped_target.parent.mkdir(parents=True, exist_ok=True)
    mapped_target.write_bytes(b"x")

    fastresume_dir = tmp_path / "BT_backup"
    fastresume_dir.mkdir()
    _write_fastresume(
        fastresume_dir / "deadbeef.fastresume",
        save_path="/data/media/torrents/seeding/cross-seed/seedpool (API)",
        qbt_save_path="/data/media/torrents/seeding/cross-seed/seedpool (API)",
    )

    torrents = [
        SimpleNamespace(
            hash="deadbeef",
            name="Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
            state="missingFiles",
            progress=0.0,
            save_path="/data/media/torrents/seeding/cross-seed/seedpool (API)",
            content_path="/data/media/torrents/seeding/cross-seed/seedpool (API)/Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
        ),
    ]

    report = build_missing_sibling_reconnect_batch(
        qb_client=FakeQBClient(torrents),
        source_root="/data/media/torrents/seeding",
        target_root=target_root,
        fastresume_dir=fastresume_dir,
        catalog_path=catalog,
    )

    assert report["summary"]["plans"] == 1
    plan = report["plans"][0]
    assert plan["payload_hash"] == "payload-new"
    assert plan["target_path"] == str(mapped_target)
    assert plan["affected_torrents"] == ["deadbeef"]
    assert plan["normalization"]["audit_root_causes"] == ["root_drift_after_rehome_reuse"]
    assert plan["normalization"]["donor_root_path"] == str(mapped_target)
    assert plan["view_targets"] == [
        {
            "torrent_hash": "deadbeef",
            "source_save_path": "/data/media/torrents/seeding/cross-seed/seedpool (API)",
            "target_save_path": f"{target_root}/cross-seed/seedpool (API)",
            "root_name": "Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv",
        }
    ]


def test_missing_reconnect_preflight_allows_missingfiles_state(tmp_path):
    executor = DemotionExecutor(catalog_path=tmp_path / "catalog.db")
    executor.qbit_client = FakeQBClient(
        [
            SimpleNamespace(
                hash="deadbeef",
                state="missingFiles",
                progress=0.0,
            ),
            SimpleNamespace(
                hash="badf00d",
                state="missingFiles",
                progress=0.0,
            ),
        ]
    )

    plan = {
        "affected_torrents": ["deadbeef", "badf00d"],
        "normalization": {"mode": "qb_missing_sibling_reconnect"},
    }

    executor._preflight_torrent_state_check(plan)
