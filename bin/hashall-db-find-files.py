#!/usr/bin/env python3
"""Find file rows across hashall files_* tables using SQL wildcard matching.

Examples:
  bin/hashall-db-find-files.py --pattern 'dexter%s02%720p%x265%zmnt%'
  bin/hashall-db-find-files.py --pattern '*modern*mind*' --suffix .mp3
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.script_metadata import register as register_script_metadata

SCRIPT_NAME = Path(__file__).name
SEMVER = "0.1.0"
LAST_UPDATED = "2026-04-09T07:05:00-04:00"
register_script_metadata(SCRIPT_NAME, SEMVER, LAST_UPDATED, argv=" ".join(sys.argv[1:]))


def _default_db() -> str:
    return str(Path.home() / ".hashall" / "catalog.db")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _discover_file_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'files_%' ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {str(r[1]) for r in rows}


def _wildcard_to_like(pat: str) -> str:
    # let users type shell-ish '*' while still supporting raw SQL '%' patterns
    return pat.replace("*", "%")


def _build_union_sql(conn: sqlite3.Connection, tables: Iterable[str]) -> str:
    parts = []
    for t in tables:
        cols = _table_columns(conn, t)
        full_path_expr = "full_path" if "full_path" in cols else "path"
        quick_expr = "quick_hash" if "quick_hash" in cols else "NULL"
        sha1_expr = "sha1" if "sha1" in cols else "NULL"
        sha256_expr = "sha256" if "sha256" in cols else "NULL"
        status_expr = "status" if "status" in cols else "'active'"
        inode_expr = "inode" if "inode" in cols else "NULL"
        mtime_expr = "mtime" if "mtime" in cols else "NULL"
        size_expr = "size" if "size" in cols else "0"
        path_expr = "path" if "path" in cols else "''"
        discovered_under_expr = "discovered_under" if "discovered_under" in cols else "NULL"
        parts.append(
            f"SELECT '{t}' AS table_name, {path_expr} AS path, {full_path_expr} AS full_path, "
            f"{size_expr} AS size, {inode_expr} AS inode, {mtime_expr} AS mtime, {status_expr} AS status, "
            f"{quick_expr} AS quick_hash, {sha1_expr} AS sha1, {sha256_expr} AS sha256, "
            f"{discovered_under_expr} AS discovered_under FROM \"{t}\""
        )
    if not parts:
        return "SELECT '' AS table_name, '' AS path, '' AS full_path, 0 AS size, 0 AS inode, 0 AS mtime, '' AS status, '' AS quick_hash, '' AS sha1, '' AS sha256, '' AS discovered_under WHERE 0"
    return "\nUNION ALL\n".join(parts)


def _fmt_time(epoch: float | int | None) -> str:
    if not epoch:
        return "-"
    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%m-%d %H:%M")
    except Exception:
        return "-"


def _short(s: str | None, n: int = 6) -> str:
    v = (s or "").strip()
    return v[:n] if v else ("-" * max(1, int(n)))


def _parse_hash_list(val: Any) -> List[str]:
    raw = str(val or "").strip()
    if not raw:
        return []
    for sep in (",", " ", "\t", "\n"):
        raw = raw.replace(sep, "|")
    out: List[str] = []
    seen = set()
    for tok in raw.split("|"):
        h = tok.strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def _fetch_qb_progress_map(hashes: Sequence[str]) -> Dict[str, float]:
    if not hashes:
        return {}
    try:
        from hashall.qbittorrent import get_qbittorrent_client
    except Exception:
        return {}
    try:
        qb = get_qbittorrent_client()
        if not qb.test_connection() or not qb.login():
            return {}
        info = qb.get_torrents_by_hashes(list(hashes))
    except Exception:
        return {}
    out: Dict[str, float] = {}
    for row in info.values():
        h = str(row.get("hash") or "").strip().lower()
        if not h:
            continue
        try:
            out[h] = float(row.get("progress", 0.0) or 0.0)
        except Exception:
            out[h] = 0.0
    return out


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=_default_db(), help="SQLite DB path")
    p.add_argument("--pattern", required=True, help="SQL LIKE pattern for path/full_path (supports * as %%)")
    p.add_argument("--suffix", default="", help="Optional filename suffix filter")
    p.add_argument("--limit", type=int, default=200, help="Maximum rows to print")
    p.add_argument("--show-qb-progress", action="store_true", help="Fetch qB progress for matching torrent hashes")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print(f"DB not found: {db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    tables = _discover_file_tables(conn)
    if not tables:
        print("No files_* tables found.", file=sys.stderr)
        return 1

    union_sql = _build_union_sql(conn, tables)
    pattern = _wildcard_to_like(args.pattern)
    suffix = str(args.suffix or "")
    where = "(full_path LIKE ? OR path LIKE ?)"
    params: list[Any] = [pattern, pattern]
    if suffix:
        where += " AND full_path LIKE ?"
        params.append(f"%{suffix}")

    sql = f"""
    WITH unioned AS (
    {union_sql}
    )
    SELECT *
    FROM unioned
    WHERE {where}
    ORDER BY size DESC, full_path ASC
    LIMIT ?
    """
    params.append(int(args.limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    qb_progress = {}
    if args.show_qb_progress and rows:
        hashes = []
        for row in rows:
            hashes.extend(_parse_hash_list(row["quick_hash"]))
        qb_progress = _fetch_qb_progress_map(hashes)

    print(f"matches={len(rows)} pattern={pattern} suffix={suffix or '-'}")
    for row in rows:
        qh = _short(row["quick_hash"])
        sh1 = _short(row["sha1"])
        sh256 = _short(row["sha256"])
        progress_label = ""
        if qb_progress:
            hashes = _parse_hash_list(row["quick_hash"])
            if hashes:
                prog = max((qb_progress.get(h, 0.0) for h in hashes), default=0.0)
                progress_label = f" qb_progress={prog:.3f}"
        print(
            f"{row['table_name']:>9s}  size={int(row['size'] or 0):>12,d}  "
            f"mtime={_fmt_time(row['mtime'])}  status={row['status'] or '-':<8s}  "
            f"q={qh} s1={sh1} s256={sh256}{progress_label}"
        )
        print(f"  path={row['path']}")
        print(f"  full={row['full_path']}")
        if row["discovered_under"]:
            print(f"  under={row['discovered_under']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
