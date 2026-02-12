"""Tests for rehome audit-tags CLI command."""

import sqlite3
from pathlib import Path

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE rehome_runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT,
            finished_at TEXT,
            direction TEXT,
            decision TEXT,
            payload_hash TEXT,
            payload_id INTEGER,
            torrent_count INTEGER,
            status TEXT,
            message TEXT
        );

        CREATE TABLE torrent_instances (
            torrent_hash TEXT PRIMARY KEY,
            payload_id INTEGER NOT NULL,
            device_id INTEGER,
            save_path TEXT,
            root_name TEXT,
            category TEXT,
            tags TEXT,
            last_seen_at REAL
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_audit_tags_latest_success_compliant(tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO rehome_runs (
            id, started_at, finished_at, direction, decision, payload_hash, payload_id, torrent_count, status, message
        ) VALUES (
            10, '2026-02-12 11:00:00', '2026-02-12 11:01:00', 'demote', 'MOVE', 'abc123', 7, 1, 'success', ''
        );

        INSERT INTO torrent_instances (
            torrent_hash, payload_id, tags
        ) VALUES (
            'torrent_ok', 7, 'seed,rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260212'
        );
        """
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["audit-tags", "--catalog", str(db_path)])

    assert result.exit_code == 0
    assert "non_compliant: 0" in result.output
    assert "Rehome tags are compliant" in result.output


def test_audit_tags_run_non_compliant(tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        INSERT INTO rehome_runs (
            id, started_at, finished_at, direction, decision, payload_hash, payload_id, torrent_count, status, message
        ) VALUES (
            11, '2026-02-12 11:00:00', '2026-02-12 11:01:00', 'promote', 'REUSE', 'def456', 9, 1, 'success', ''
        );

        INSERT INTO torrent_instances (
            torrent_hash, payload_id, tags
        ) VALUES (
            'torrent_bad', 9, 'seed,rehome,rehome_from_pool'
        );
        """
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["audit-tags", "--catalog", str(db_path), "--run-id", "11"],
    )

    assert result.exit_code == 1
    assert "non_compliant: 1" in result.output
    assert "missing_core=rehome_to_stash" in result.output
    assert "has_rehome_at=no" in result.output



def test_audit_tags_falls_back_to_payload_hash_ids(tmp_path: Path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY,
            payload_hash TEXT,
            device_id INTEGER,
            root_path TEXT,
            file_count INTEGER,
            total_bytes INTEGER,
            status TEXT,
            last_built_at REAL
        );

        INSERT INTO rehome_runs (
            id, started_at, finished_at, direction, decision, payload_hash, payload_id, torrent_count, status, message
        ) VALUES (
            12, '2026-02-12 11:00:00', '2026-02-12 11:01:00', 'demote', 'MOVE', 'hash-shared', 100, 1, 'success', ''
        );

        INSERT INTO payloads (payload_id, payload_hash, device_id, root_path, file_count, total_bytes, status)
        VALUES
            (100, 'hash-shared', 49, '/pool/data/old', 0, 0, 'incomplete'),
            (101, 'hash-shared', 49, '/pool/data/new', 1, 100, 'complete');

        INSERT INTO torrent_instances (
            torrent_hash, payload_id, tags
        ) VALUES (
            'torrent_fallback', 101, 'rehome,rehome_from_stash,rehome_to_pool,rehome_at_20260212'
        );
        """
    )
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["audit-tags", "--catalog", str(db_path), "--run-id", "12"])

    assert result.exit_code == 0
    assert "payload_ids_checked: [100, 101]" in result.output
    assert "non_compliant: 0" in result.output
