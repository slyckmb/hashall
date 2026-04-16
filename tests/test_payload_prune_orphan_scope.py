import os
import sqlite3
import time
from pathlib import Path

import hashall.payload as payload_mod
from hashall.model import connect_db
from hashall.payload import prune_orphan_payloads, ORPHAN_GC_MIN_SEEN_RUNS, ORPHAN_GC_MIN_AGE_SECONDS


def test_prune_orphans_large_scope_does_not_hit_sql_expression_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)
    try:
        roots = [f"/pool/data/seeds/path-{idx}" for idx in range(2500)]
        stats = prune_orphan_payloads(conn, roots=roots, sample_limit=3)
    finally:
        conn.close()

    assert stats["candidates"] == 0
    assert stats["total_payloads"] == 0
    assert stats["pruned"] == 0


def test_prune_orphans_scope_filter_works_with_many_roots(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)
    try:
        conn.execute("INSERT INTO payloads (root_path) VALUES (?)", ("/pool/data/seeds/a",))
        conn.execute("INSERT INTO payloads (root_path) VALUES (?)", ("/pool/data/orphaned/b",))
        conn.execute("INSERT INTO payloads (root_path) VALUES (?)", ("/stash/media/keep/c",))
        conn.commit()

        roots = [f"/tmp/no-match-{idx}" for idx in range(1500)]
        roots.extend(["/pool/data/seeds", "/pool/data/orphaned"])
        stats = prune_orphan_payloads(conn, roots=roots, sample_limit=5)

        gc_rows = conn.execute("SELECT COUNT(*) FROM payload_orphan_gc").fetchone()
        gc_count = int(gc_rows[0]) if gc_rows else 0
    finally:
        conn.close()

    assert stats["total_payloads"] == 2
    assert stats["candidates"] == 2
    assert stats["tracked_candidates"] == 2
    assert stats["new_candidates"] == 2
    assert stats["pruned"] == 0
    assert gc_count == 2


def _insert_aged_orphan(conn, root_path: str, payload_id: int) -> None:
    """Insert a payload and a fully-aged orphan GC record for it."""
    conn.execute(
        "INSERT INTO payloads (payload_id, root_path) VALUES (?, ?)",
        (payload_id, root_path),
    )
    old_time = time.time() - (ORPHAN_GC_MIN_AGE_SECONDS + 1)
    conn.execute(
        """
        INSERT INTO payload_orphan_gc
            (payload_id, first_seen_at, last_seen_at, seen_count, last_root_path, last_device_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payload_id, old_time, old_time, ORPHAN_GC_MIN_SEEN_RUNS, root_path, 1),
    )
    conn.commit()


def test_orphan_gc_env_max_prune_count_overrides_default(tmp_path: Path, monkeypatch) -> None:
    """HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT env var raises the count ceiling at call time."""
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)
    try:
        # Insert 1500 payloads (above default limit of 1000) all as orphans in scope
        roots = [f"/pool/seeds/{i}" for i in range(1500)]
        for i, root in enumerate(roots):
            _insert_aged_orphan(conn, root, payload_id=i + 1)

        # Default limit (1000) → blocked
        stats_default = prune_orphan_payloads(conn, roots=["/pool/seeds"], sample_limit=1)
        assert stats_default["block_reason"] is not None
        assert "candidate_count_exceeds_limit" in stats_default["block_reason"]

        # Override to 2000 → unblocked, all 1500 pruned
        monkeypatch.setenv("HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT", "2000")
        monkeypatch.setenv("HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION", "1.0")
        stats_override = prune_orphan_payloads(conn, roots=["/pool/seeds"], sample_limit=1)
        assert stats_override["block_reason"] is None
        assert stats_override["pruned"] == 1500
        assert stats_override["max_prune_count"] == 2000
    finally:
        conn.close()


def test_orphan_gc_env_max_prune_fraction_overrides_default(tmp_path: Path, monkeypatch) -> None:
    """HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION env var raises the fraction ceiling at call time."""
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)
    # Lower spike_min_total to 1 so the fraction guard triggers even with a tiny dataset.
    # total_payloads is scoped to the roots= argument, so 3 orphaned payloads under
    # /pool/orphans gives total=3, candidates=3, fraction=100% > 25% default.
    monkeypatch.setattr(payload_mod, "ORPHAN_GC_SPIKE_MIN_TOTAL", 1)
    try:
        for i in range(3):
            _insert_aged_orphan(conn, f"/pool/orphans/{i}", payload_id=100 + i)

        # Default fraction (0.25) → blocked (3/3 = 100% > 25%)
        stats_default = prune_orphan_payloads(conn, roots=["/pool/orphans"], sample_limit=1)
        assert stats_default["block_reason"] is not None
        assert "candidate_fraction_exceeds_limit" in stats_default["block_reason"]

        # Override fraction to 1.0 → unblocked
        monkeypatch.setenv("HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION", "1.0")
        stats_override = prune_orphan_payloads(conn, roots=["/pool/orphans"], sample_limit=1)
        assert stats_override["block_reason"] is None
        assert stats_override["pruned"] == 3
        assert stats_override["max_prune_fraction"] == 1.0
    finally:
        conn.close()
