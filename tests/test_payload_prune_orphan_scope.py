import sqlite3
from pathlib import Path

from hashall.model import connect_db
from hashall.payload import prune_orphan_payloads


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
