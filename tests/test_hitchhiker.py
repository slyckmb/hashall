"""Tests for hitchhiker module — N→1 payload group detection and SQL limit correctness."""

import sqlite3
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from hashall.cli import cli
from hashall.hitchhiker import HitchhikerStatus, audit_hitchhiker_groups, query_hitchhiker_groups
from hashall.hitchhiker_plan import build_hitchhiker_repair_plan
from hashall.hitchhiker_split import execute_split_group, plan_split_actions, split_hitchhiker_groups
from hashall.rtorrent import RTSessionEntry


@pytest.fixture
def hitchhiker_db(tmp_path):
    """
    Minimal DB with 3 hitchhiker groups (payload_id 1, 2, 3), each with 2 hashes.
    Total rows: 6 torrent_instances.
    """
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 1000
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '/data/media/torrents/seeding/tv',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    for pid in range(1, 4):
        conn.execute(
            "INSERT INTO payloads VALUES (?, ?, 1, 1000)",
            (pid, f"/data/media/torrents/seeding/tv/root{pid}"),
        )
        for h_suffix in range(2):
            conn.execute(
                "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, ?)",
                (f"{'a' * 38}{pid}{h_suffix}", pid),
            )
    conn.commit()
    conn.close()
    return str(db)


def test_query_no_limit_returns_all_groups(hitchhiker_db):
    rows = query_hitchhiker_groups(db_path=hitchhiker_db)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 3, f"Expected 3 groups, got {payload_ids}"
    assert len(rows) == 6, f"Expected 6 rows (3 groups × 2 hashes), got {len(rows)}"


def test_query_limit_1_returns_one_complete_group(hitchhiker_db):
    """LIMIT 1 must return 1 complete group (2 rows), not 1 row from a group."""
    rows = query_hitchhiker_groups(db_path=hitchhiker_db, limit=1)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 1, f"Expected 1 group, got {payload_ids}"
    assert len(rows) == 2, (
        f"LIMIT=1 should return all rows for 1 group (2 rows), got {len(rows)} — "
        f"SQL limit may be applying to rows rather than groups"
    )


def test_query_limit_2_returns_two_complete_groups(hitchhiker_db):
    """LIMIT 2 must return 2 complete groups (4 rows)."""
    rows = query_hitchhiker_groups(db_path=hitchhiker_db, limit=2)
    payload_ids = {r["payload_id"] for r in rows}
    assert len(payload_ids) == 2
    assert len(rows) == 4


def test_query_no_hitchhiker_groups(tmp_path):
    """DB with only singleton groups returns empty list."""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 0
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    conn.execute("INSERT INTO payloads VALUES (1, '/seeding/tv/root1', 1, 0)")
    conn.execute("INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES ('aaa', 1)")
    conn.commit()
    conn.close()

    rows = query_hitchhiker_groups(db_path=str(db))
    assert rows == []


def _write_hitchhiker_db(tmp_path, *, hashes, root_path="/pool/media/torrents/seeding/site/Release.mkv"):
    db = tmp_path / "hitchhiker.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 1000
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '/pool/media/torrents/seeding/site',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    conn.execute("INSERT INTO payloads VALUES (10, ?, 1, 1000)", (root_path,))
    for hash_val in hashes:
        conn.execute(
            "INSERT INTO torrent_instances (torrent_hash, payload_id) VALUES (?, 10)",
            (hash_val,),
        )
    conn.commit()
    conn.close()
    return str(db)


def _install_fake_qb(monkeypatch, rows):
    class FakeQB:
        def _normalize_torrent_payload(self, payload):
            return payload

        def _torrent_from_payload(self, payload):
            return SimpleNamespace(
                hash=payload.get("hash"),
                state=payload.get("state", "stoppedUP"),
                save_path=payload.get("save_path", ""),
                content_path=payload.get("content_path", ""),
            )

    monkeypatch.setattr("hashall.hitchhiker.get_torrents_from_cache", lambda *a, **k: rows)
    monkeypatch.setattr("hashall.hitchhiker.QBittorrentClient", FakeQB)


def test_audit_blocks_catalog_only_hashes(tmp_path, monkeypatch):
    hashes = ["aaa111", "bbb222"]
    db = _write_hitchhiker_db(tmp_path, hashes=hashes)
    _install_fake_qb(
        monkeypatch,
        [
            {
                "hash": "aaa111",
                "state": "stoppedUP",
                "save_path": "/pool/media/torrents/seeding/site",
                "content_path": "/pool/media/torrents/seeding/site/Release.mkv",
            }
        ],
    )
    monkeypatch.setattr(
        "hashall.hitchhiker.load_rt_cache_snapshot",
        lambda *a, **k: {"rows": [{"hash": "aaa111", "state": "stalledUP"}]},
    )
    monkeypatch.setattr(
        "hashall.hitchhiker.load_rt_session_directories",
        lambda *a, **k: {
            "aaa111": RTSessionEntry(
                torrent_hash="aaa111",
                directory="/pool/media/torrents/seeding/site",
                path_exists=True,
            )
        },
    )

    groups = audit_hitchhiker_groups(db_path=db)

    assert groups[0].status == HitchhikerStatus.BLOCKED
    assert any("bbb222"[:6] in note and "missing from both qB and RT" in note for note in groups[0].notes)


def test_audit_blocks_common_hash_path_drift(tmp_path, monkeypatch):
    hashes = ["aaa111", "bbb222"]
    db = _write_hitchhiker_db(tmp_path, hashes=hashes)
    _install_fake_qb(
        monkeypatch,
        [
            {
                "hash": hash_val,
                "state": "stoppedUP",
                "save_path": "/pool/media/torrents/seeding/site",
                "content_path": "/pool/media/torrents/seeding/site/Release.mkv",
            }
            for hash_val in hashes
        ],
    )
    monkeypatch.setattr(
        "hashall.hitchhiker.load_rt_cache_snapshot",
        lambda *a, **k: {"rows": [{"hash": hash_val, "state": "stalledUP"} for hash_val in hashes]},
    )
    monkeypatch.setattr(
        "hashall.hitchhiker.load_rt_session_directories",
        lambda *a, **k: {
            "aaa111": RTSessionEntry("aaa111", "/pool/media/torrents/seeding/site", True),
            "bbb222": RTSessionEntry("bbb222", "/data/media/torrents/seeding/site", True),
        },
    )

    groups = audit_hitchhiker_groups(db_path=db)

    assert groups[0].status == HitchhikerStatus.BLOCKED
    assert any("path drift blocks blind split" in note for note in groups[0].notes)


def test_split_plan_reports_existing_empty_target_stub(tmp_path, monkeypatch):
    seed_root = tmp_path / "pool" / "media" / "torrents" / "seeding"
    monkeypatch.setattr(
        "hashall.hitchhiker_split._SEEDING_ROOT_ALIASES",
        [(str(seed_root), str(seed_root))],
    )
    source = seed_root / "site" / "Release.mkv"
    source.parent.mkdir(parents=True)
    source.write_text("payload", encoding="utf-8")
    target_stub = seed_root / "_rehome-unique" / "bbb222"
    target_stub.mkdir(parents=True)
    group = SimpleNamespace(
        payload_id=10,
        root_path=str(source),
        file_count=1,
        total_bytes=7,
        hashes=["aaa111", "bbb222"],
        status=HitchhikerStatus.SAFE_TO_SPLIT,
        notes=[],
    )

    actions = plan_split_actions(group)
    result = execute_split_group(group, dry_run=True)

    assert actions[0].warnings == ["target_parent_exists_empty"]
    assert actions[0].blockers == []
    assert result.success is True


def test_split_plan_blocks_existing_target_content(tmp_path, monkeypatch):
    seed_root = tmp_path / "pool" / "media" / "torrents" / "seeding"
    monkeypatch.setattr(
        "hashall.hitchhiker_split._SEEDING_ROOT_ALIASES",
        [(str(seed_root), str(seed_root))],
    )
    source = seed_root / "site" / "Release.mkv"
    source.parent.mkdir(parents=True)
    source.write_text("payload", encoding="utf-8")
    target_dir = seed_root / "_rehome-unique" / "bbb222"
    target_dir.mkdir(parents=True)
    (target_dir / "Release.mkv").write_text("old", encoding="utf-8")
    group = SimpleNamespace(
        payload_id=10,
        root_path=str(source),
        file_count=1,
        total_bytes=7,
        hashes=["aaa111", "bbb222"],
        status=HitchhikerStatus.SAFE_TO_SPLIT,
        notes=[],
    )

    result = execute_split_group(group, dry_run=True)

    assert result.success is False
    assert "target_content_exists" in result.actions[0].blockers
    assert "target_parent_exists_non_empty" in result.actions[0].blockers


def test_cli_hitchhiker_split_execute_requires_selection():
    result = CliRunner().invoke(cli, ["payload", "hitchhiker-split", "--execute"])

    assert result.exit_code != 0
    assert "requires --hash or --payload-id" in result.output


def test_cli_hitchhiker_split_execute_returns_nonzero_for_blocked_selection(tmp_path, monkeypatch):
    db = _write_hitchhiker_db(tmp_path, hashes=["aaa111", "bbb222"])
    _install_fake_qb(monkeypatch, [])
    monkeypatch.setattr("hashall.hitchhiker.load_rt_cache_snapshot", lambda *a, **k: {"rows": []})
    monkeypatch.setattr("hashall.hitchhiker.load_rt_session_directories", lambda *a, **k: {})

    result = CliRunner().invoke(
        cli,
        [
            "payload",
            "hitchhiker-split",
            "--execute",
            "--payload-id",
            "10",
            "--db",
            db,
        ],
    )

    assert result.exit_code != 0
    assert "status=blocked" in result.output
    assert "execute failed" in result.output


def test_selected_split_reports_blocked_group():
    group = SimpleNamespace(
        payload_id=10,
        root_path="/pool/media/torrents/seeding/site/Release.mkv",
        file_count=1,
        total_bytes=7,
        hashes=["aaa111", "bbb222"],
        status=HitchhikerStatus.BLOCKED,
        notes=["blocked for test"],
    )

    assert split_hitchhiker_groups([group], dry_run=True) == []
    results = split_hitchhiker_groups([group], dry_run=True, include_unsafe=True)

    assert len(results) == 1
    assert results[0].success is False
    assert "group not safe to split" in results[0].error


def test_hitchhiker_plan_reports_selected_path_drift_sources(tmp_path):
    db = tmp_path / "hitchhiker.db"
    pool_seed = tmp_path / "pool" / "torrents" / "seeding" / "site"
    stash_seed = tmp_path / "stash" / "torrents" / "seeding" / "site"
    pool_seed.mkdir(parents=True)
    stash_seed.mkdir(parents=True)
    qb_content = pool_seed / "Alien.Resurrection.mkv"
    rt_content = stash_seed / "Alien.Resurrection.mkv"
    qb_content.write_text("payload", encoding="utf-8")
    rt_content.write_text("payload", encoding="utf-8")
    selected_hash = "4f454ed3bdf830f0aaa111"
    stale_hash = "bbb222"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            payload_hash TEXT,
            root_path TEXT,
            file_count INTEGER DEFAULT 1,
            total_bytes INTEGER DEFAULT 7
        );
        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            save_path TEXT DEFAULT '',
            FOREIGN KEY (payload_id) REFERENCES payloads(payload_id)
        );
    """)
    conn.execute(
        "INSERT INTO payloads VALUES (10, 'payloadhash1', ?, 1, 7)",
        (str(qb_content),),
    )
    conn.execute(
        "INSERT INTO torrent_instances VALUES (?, 10, ?)",
        (selected_hash, str(pool_seed)),
    )
    conn.execute(
        "INSERT INTO torrent_instances VALUES (?, 10, ?)",
        (stale_hash, str(pool_seed)),
    )
    conn.commit()
    conn.close()
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    qb_cache.write_text(
        f"""[
          {{
            "hash": "{selected_hash}",
            "name": "Alien.Resurrection.mkv",
            "save_path": "{pool_seed}",
            "content_path": "{qb_content}",
            "state": "stoppedUP",
            "progress": 1
          }}
        ]""",
        encoding="utf-8",
    )
    rt_cache.write_text(
        f"""[
          {{
            "hash": "{selected_hash}",
            "name": "Alien.Resurrection.mkv",
            "directory": "{rt_content}",
            "state": "stalledUP",
            "complete": 1
          }}
        ]""",
        encoding="utf-8",
    )

    plan = build_hitchhiker_repair_plan(
        db_path=db,
        hash_filters=(selected_hash[:16],),
        qb_cache_file=qb_cache,
        rt_cache_file=rt_cache,
        rt_session_dir=session_dir,
    )

    group = plan["groups"][0]
    selected = [item for item in group["hash_items"] if item["hash"] == selected_hash][0]
    assert group["status"] == "blocked"
    assert selected["path_drift"] is True
    assert "same_hash_qb_rt_path_drift_requires_source_selection" in selected["blockers"]
    sources = {(item["source"], item["path"]) for item in selected["source_candidates"]}
    assert ("qb_content", str(qb_content)) in sources
    assert ("rt_content", str(rt_content)) in sources
