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


SEMVER = "0.1.0"


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
    for h, row in info.items():
        try:
            out[str(h).lower()] = float(row.progress or 0.0) * 100.0
        except Exception:
            continue
    return out


def _torrent_hashes_and_pct(val: Any, progress_map: Dict[str, float], prefix_len: int = 6) -> Tuple[str, str]:
    hashes = _parse_hash_list(val)
    if not hashes:
        return "-" * max(1, int(prefix_len)), "-"
    hs: List[str] = []
    ps: List[str] = []
    for h in hashes:
        hs.append(h[:prefix_len])
        p = progress_map.get(h)
        ps.append(f"{p:.2f}%" if p is not None else "-")
    return "|".join(hs) if hs else ("-" * max(1, int(prefix_len))), "|".join(ps) if ps else "-"


def _pad_tor_field(val: str, width: int) -> str:
    v = str(val or "").strip()
    if not v or v == "-":
        return "-" * max(1, int(width))
    if len(v) >= width:
        return v
    return v + (" " * (width - len(v)))


def _canon_sql(expr: str) -> str:
    return (
        "REPLACE(REPLACE(REPLACE(REPLACE("
        f"{expr}, "
        "'/stash/media/downloads/torrents/seeding', '/data/media/torrents/seeding'), "
        "'/pool/data/seeds', '/data/media/torrents/seeding'), "
        "'/pool/data/cross-seed-link', '/data/media/torrents/seeding/cross-seed-link'), "
        "'/stash/media', '/data/media')"
    )


def _lookup_torrent_hashes_for_path(conn: sqlite3.Connection, full_path: str) -> str:
    # Match any torrent whose canonical root path is equal to or ancestor of this file path.
    full_expr = _canon_sql("?")
    payload_root_expr = _canon_sql("p.root_path")
    ti_root_expr = _canon_sql("CASE WHEN COALESCE(ti.root_name,'') != '' THEN ti.save_path || '/' || ti.root_name ELSE ti.save_path END")
    sql = (
        "SELECT REPLACE(group_concat(DISTINCT x.torrent_hash), ',', '|') AS torrent_hashes "
        "FROM ( "
        "  SELECT ti.torrent_hash AS torrent_hash "
        "  FROM payloads p "
        "  JOIN torrent_instances ti ON ti.payload_id = p.payload_id "
        f" WHERE ({full_expr}) = ({payload_root_expr}) "
        f"    OR ({full_expr}) LIKE ({payload_root_expr}) || '/%' "
        "  UNION "
        "  SELECT ti.torrent_hash AS torrent_hash "
        "  FROM torrent_instances ti "
        f" WHERE ({full_expr}) = ({ti_root_expr}) "
        f"    OR ({full_expr}) LIKE ({ti_root_expr}) || '/%' "
        ") x"
    )
    # full_expr appears 4 times.
    params = [full_path, full_path, full_path, full_path]
    row = conn.execute(sql, params).fetchone()
    return str((row["torrent_hashes"] if row else "") or "")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Search hashall files_* tables with SQL-style wildcard matching.",
        epilog=(
            "Pattern rules:\n"
            "  - Use '%%' as SQL wildcard (any characters)\n"
            "  - '*' is accepted and converted to '%'\n"
            "Examples:\n"
            "  --pattern 'dexter%%s02%%720p%%x265%%zmnt%%'\n"
            "  --pattern '*modern*mind*' --suffix .mp3"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--db", default=_default_db(), help="SQLite DB path (default: ~/.hashall/catalog.db)")
    p.add_argument(
        "--pattern",
        required=True,
        help="Path match pattern (SQL LIKE). Use '%%' or '*' as wildcard.",
    )
    p.add_argument(
        "--suffix",
        default=".mkv",
        help="Optional file suffix filter (default: .mkv). Use '' to disable.",
    )
    p.add_argument(
        "--exclude-torrent-sidecars",
        action="store_true",
        help="Exclude files ending in .torrent.",
    )
    p.add_argument(
        "--include-deleted",
        action="store_true",
        help="Include non-active rows (default filters to status='active').",
    )
    p.add_argument("--limit", type=int, default=500, help="Max rows (default: 500)")
    p.add_argument(
        "--format",
        choices=("tsv", "json"),
        default="tsv",
        help="Output format (default: tsv)",
    )

    args = p.parse_args()

    db = os.path.expanduser(args.db)
    if not os.path.exists(db):
        print(f"ERROR db_not_found path={db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    tables = _discover_file_tables(conn)
    tables = [t for t in tables if _table_exists(conn, t)]
    if not tables:
        print("ERROR no files_* tables found", file=sys.stderr)
        return 2

    union_sql = _build_union_sql(conn, tables)
    like_pat = _wildcard_to_like(args.pattern).lower()
    suffix = (args.suffix or "").strip().lower()

    where = ["LOWER(COALESCE(full_path, path, '')) LIKE ?"]
    params: list[object] = [like_pat]

    if suffix:
        where.append("LOWER(COALESCE(full_path, path, '')) LIKE ?")
        params.append(f"%{suffix}")
    if args.exclude_torrent_sidecars:
        where.append("LOWER(COALESCE(full_path, path, '')) NOT LIKE '%.torrent'")
    if not args.include_deleted:
        where.append("LOWER(COALESCE(status,'')) = 'active'")

    sql = f"""
WITH u AS (
{union_sql}
)
SELECT
  inode,
  ROUND(size/1024.0/1024.0/1024.0, 2) AS size_gib,
  mtime,
  quick_hash,
  sha1,
  sha256,
  table_name,
  full_path,
  discovered_under,
  path,
  status
FROM u
WHERE {' AND '.join(where)}
ORDER BY inode ASC, full_path ASC
LIMIT ?
"""
    params.append(max(1, int(args.limit)))
    rows = conn.execute(sql, params).fetchall()
    rows_out: List[Dict[str, Any]] = []
    all_hashes: List[str] = []
    seen_hashes = set()
    for r in rows:
        fp_raw = str(r["full_path"] or "").strip()
        p_raw = str(r["path"] or "").strip()
        d_raw = str(r["discovered_under"] or "").strip()
        if fp_raw.startswith("/"):
            fp = fp_raw
        elif p_raw.startswith("/"):
            fp = p_raw
        elif d_raw:
            fp = f"{d_raw.rstrip('/')}/{p_raw.lstrip('/')}"
        else:
            fp = fp_raw or p_raw or "-"
        th = _lookup_torrent_hashes_for_path(conn, fp) if fp != "-" else ""
        for h in _parse_hash_list(th):
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            all_hashes.append(h)
        rows_out.append(
            {
                "inode": r["inode"],
                "size_gib": float(r["size_gib"] or 0.0),
                "mtime": _fmt_time(r["mtime"]),
                "quick6": _short(r["quick_hash"]),
                "sha1_6": _short(r["sha1"]),
                "sha256_6": _short(r["sha256"]),
                "torrent_hashes": th,
                "table": r["table_name"] or "-",
                "status": r["status"] or "-",
                "full_path": fp,
            }
        )
    progress_map = _fetch_qb_progress_map(all_hashes)

    print(f"start ts={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} script=hashall-db-find-files.py semver={SEMVER}", file=sys.stderr)

    if args.format == "json":
        import json

        out = []
        for r in rows_out:
            tor_h, tor_pct = _torrent_hashes_and_pct(r.get("torrent_hashes"), progress_map, prefix_len=6)
            r2 = dict(r)
            r2["tor_hash6"] = tor_h
            r2["tor_pct"] = tor_pct
            out.append(r2)
        print(json.dumps(out, indent=2))
    else:
        print("inode\tsize_gib\tmtime\tquick6\tsha1_6\tsha256_6\ttor_hash6\ttor_pct\tfull_path")
        rendered: List[Dict[str, Any]] = []
        for r in rows_out:
            tor_h, tor_pct = _torrent_hashes_and_pct(r.get("torrent_hashes"), progress_map, prefix_len=6)
            rendered.append({"row": r, "tor_h": tor_h, "tor_pct": tor_pct})

        tor_hash_w = max(len("tor_hash6"), max((len(x["tor_h"]) for x in rendered), default=6))
        tor_pct_w = max(len("tor_pct"), max((len(x["tor_pct"]) for x in rendered), default=1))

        prev_inode: Any = None
        for item in rendered:
            r = item["row"]
            tor_h = _pad_tor_field(item["tor_h"], tor_hash_w)
            tor_pct = _pad_tor_field(item["tor_pct"], tor_pct_w)
            inode = r.get("inode")
            if prev_inode is not None and inode != prev_inode:
                print("")
            print(
                f"{r['inode']}\t"
                f"{float(r['size_gib'] or 0.0):.2f}\t"
                f"{r['mtime']}\t"
                f"{r['quick6']}\t"
                f"{r['sha1_6']}\t"
                f"{r['sha256_6']}\t"
                f"{tor_h}\t"
                f"{tor_pct}\t"
                f"{r['full_path']}"
            )
            prev_inode = inode

    print(f"summary rows={len(rows_out)} db={db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
