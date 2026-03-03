#!/usr/bin/env python3
"""Query helper for the hashall SQLite catalog."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.model import connect_db

SEMVER = "0.1.8"
SCRIPT_NAME = Path(__file__).name


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit_start() -> str:
    now = ts_iso()
    print(f"start ts={now} script={SCRIPT_NAME} semver={SEMVER}")
    return now


def parse_scopes(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in str(text or "").replace("|", ",").split(","):
        s = part.strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def parse_csv_tokens(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in str(text or "").replace("|", ",").split(","):
        s = part.strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def fetch_rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append({k: row[k] for k in row.keys()})
    return out


def get_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def get_table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(r[1]) for r in rows]


def safe_table_name(name: str) -> bool:
    if not name:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    for ch in name[1:]:
        if not (ch.isalnum() or ch == "_"):
            return False
    return True


def print_table(rows: List[Dict[str, Any]], max_width: int = 72) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    widths: Dict[str, int] = {}
    for c in cols:
        w = len(c)
        for r in rows:
            txt = "" if r.get(c) is None else str(r.get(c))
            if len(txt) > w:
                w = len(txt)
        widths[c] = min(max_width, w)

    def _clip(val: Any, width: int) -> str:
        s = "" if val is None else str(val)
        if len(s) <= width:
            return s
        if width <= 1:
            return s[:width]
        return s[: width - 1] + "…"

    header = "  ".join(c.ljust(widths[c]) for c in cols)
    line = "  ".join("-" * widths[c] for c in cols)
    print(header)
    print(line)
    for row in rows:
        print("  ".join(_clip(row.get(c), widths[c]).ljust(widths[c]) for c in cols))


def print_tsv(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    print("\t".join(cols))
    for row in rows:
        print("\t".join("" if row.get(c) is None else str(row.get(c)) for c in cols))


def like_param(text: str) -> str:
    return f"%{str(text or '').lower()}%"


def query_torrents(
    conn: sqlite3.Connection,
    *,
    term: str,
    hash_token: str,
    name: str,
    path: str,
    category: str,
    tag: str,
    payload_hash: str,
    limit: int,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if term:
        clauses.append(
            "("
            "LOWER(COALESCE(ti.torrent_hash,'')) LIKE ? OR "
            "LOWER(COALESCE(ti.root_name,'')) LIKE ? OR "
            "LOWER(COALESCE(ti.save_path,'')) LIKE ? OR "
            "LOWER(COALESCE(ti.category,'')) LIKE ? OR "
            "LOWER(COALESCE(ti.tags,'')) LIKE ? OR "
            "LOWER(COALESCE(p.root_path,'')) LIKE ? OR "
            "LOWER(COALESCE(p.payload_hash,'')) LIKE ?"
            ")"
        )
        for _ in range(7):
            params.append(like_param(term))

    if hash_token:
        ht = str(hash_token).strip().lower()
        if len(ht) >= 40:
            clauses.append("LOWER(ti.torrent_hash) = ?")
            params.append(ht)
        else:
            clauses.append("LOWER(ti.torrent_hash) LIKE ?")
            params.append(ht + "%")

    if name:
        clauses.append("LOWER(COALESCE(ti.root_name,'')) LIKE ?")
        params.append(like_param(name))

    if path:
        clauses.append(
            "("
            "LOWER(COALESCE(ti.save_path,'')) LIKE ? OR "
            "LOWER(COALESCE(p.root_path,'')) LIKE ?"
            ")"
        )
        params.extend([like_param(path), like_param(path)])

    if category:
        clauses.append("LOWER(COALESCE(ti.category,'')) LIKE ?")
        params.append(like_param(category))

    if tag:
        clauses.append("LOWER(COALESCE(ti.tags,'')) LIKE ?")
        params.append(like_param(tag))

    if payload_hash:
        ph = str(payload_hash).strip().lower()
        if len(ph) >= 64:
            clauses.append("LOWER(COALESCE(p.payload_hash,'')) = ?")
            params.append(ph)
        else:
            clauses.append("LOWER(COALESCE(p.payload_hash,'')) LIKE ?")
            params.append(ph + "%")

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""

    sql = (
        "SELECT "
        "ti.torrent_hash, ti.root_name, ti.save_path, ti.category, ti.tags, ti.device_id AS ti_device_id, "
        "ti.last_seen_at, "
        "p.payload_id, p.payload_hash, p.root_path AS payload_root, p.status AS payload_status, "
        "p.file_count, p.total_bytes "
        "FROM torrent_instances ti "
        "LEFT JOIN payloads p ON p.payload_id = ti.payload_id "
        f"{where_sql} "
        "ORDER BY (ti.last_seen_at IS NULL) ASC, ti.last_seen_at DESC, ti.torrent_hash "
        "LIMIT ?"
    )
    params.append(max(1, int(limit)))
    rows = fetch_rows(conn, sql, params)
    for row in rows:
        row["scope"] = "torrent"
    return rows


def query_payloads(
    conn: sqlite3.Connection,
    *,
    term: str,
    name: str,
    path: str,
    payload_hash: str,
    limit: int,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if term:
        clauses.append(
            "("
            "LOWER(COALESCE(p.root_path,'')) LIKE ? OR "
            "LOWER(COALESCE(p.payload_hash,'')) LIKE ? OR "
            "LOWER(COALESCE(p.status,'')) LIKE ?"
            ")"
        )
        params.extend([like_param(term), like_param(term), like_param(term)])

    if path:
        clauses.append("LOWER(COALESCE(p.root_path,'')) LIKE ?")
        params.append(like_param(path))

    if name:
        clauses.append("LOWER(COALESCE(p.root_path,'')) LIKE ?")
        params.append(like_param(name))

    if payload_hash:
        ph = str(payload_hash).strip().lower()
        if len(ph) >= 64:
            clauses.append("LOWER(COALESCE(p.payload_hash,'')) = ?")
            params.append(ph)
        else:
            clauses.append("LOWER(COALESCE(p.payload_hash,'')) LIKE ?")
            params.append(ph + "%")

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT "
        "p.payload_id, p.payload_hash, p.device_id, p.root_path, p.status, p.file_count, p.total_bytes, "
        "COUNT(ti.torrent_hash) AS torrent_refs "
        "FROM payloads p "
        "LEFT JOIN torrent_instances ti ON ti.payload_id = p.payload_id "
        f"{where_sql} "
        "GROUP BY p.payload_id, p.payload_hash, p.device_id, p.root_path, p.status, p.file_count, p.total_bytes "
        "ORDER BY p.updated_at DESC, p.payload_id DESC "
        "LIMIT ?"
    )
    params.append(max(1, int(limit)))
    rows = fetch_rows(conn, sql, params)
    for row in rows:
        row["scope"] = "payload"
    return rows


def query_files_tables(
    conn: sqlite3.Connection,
    *,
    term: str,
    path: str,
    name: str,
    hash_token: str,
    path_suffixes: Sequence[str],
    exclude_torrent_sidecars: bool,
    include_deleted: bool,
    limit: int,
) -> List[Dict[str, Any]]:
    tables = [t for t in get_tables(conn) if t.startswith("files_")]
    out: List[Dict[str, Any]] = []

    needs_filter = bool(term or path or name or hash_token)
    if not needs_filter:
        return out

    def _col_expr(cols: set, col: str, alias: str | None = None) -> str:
        use_alias = alias or col
        if col in cols:
            return f"{col} AS {use_alias}" if use_alias != col else col
        return f"NULL AS {use_alias}"

    def _canon_sql(expr: str) -> str:
        return (
            "REPLACE(REPLACE(REPLACE(REPLACE("
            f"{expr}, "
            "'/stash/media/downloads/torrents/seeding', '/data/media/torrents/seeding'), "
            "'/pool/data/seeds', '/data/media/torrents/seeding'), "
            "'/pool/data/cross-seed-link', '/data/media/torrents/seeding/cross-seed-link'), "
            "'/stash/media', '/data/media')"
        )

    for table in tables:
        if not safe_table_name(table):
            continue
        cols = set(get_table_columns(conn, table))
        if "path" not in cols:
            continue
        where_parts: List[str] = []
        params: List[Any] = []

        if not include_deleted and "status" in cols:
            where_parts.append("COALESCE(status,'active') = 'active'")

        path_like = term or path or name
        if path_like and "path" in cols:
            where_parts.append("LOWER(path) LIKE ?")
            params.append(like_param(path_like))

        suffixes = [str(s or "").strip().lower() for s in path_suffixes if str(s or "").strip()]
        if suffixes and "path" in cols:
            suffix_parts: List[str] = []
            for sfx in suffixes:
                suffix_parts.append("LOWER(path) LIKE ?")
                params.append(f"%{sfx}")
            where_parts.append("(" + " OR ".join(suffix_parts) + ")")

        if exclude_torrent_sidecars and "path" in cols:
            where_parts.append("LOWER(path) NOT LIKE '%.torrent'")

        if hash_token:
            ht = str(hash_token).strip().lower()
            hash_cols = [c for c in ("quick_hash", "sha1", "sha256") if c in cols]
            if hash_cols:
                hash_parts = []
                for c in hash_cols:
                    if len(ht) >= 40:
                        hash_parts.append(f"LOWER(COALESCE({c},'')) = ?")
                        params.append(ht)
                    else:
                        hash_parts.append(f"LOWER(COALESCE({c},'')) LIKE ?")
                        params.append(ht + "%")
                where_parts.append("(" + " OR ".join(hash_parts) + ")")

        if not where_parts:
            continue

        where_sql = " WHERE " + " AND ".join(where_parts)
        status_expr = "status" if "status" in cols else "'active'"
        full_path_expr = (
            "CASE "
            "WHEN substr(path,1,1)='/' THEN path "
            "WHEN COALESCE(discovered_under,'') != '' THEN discovered_under || '/' || path "
            "ELSE path END"
            if "discovered_under" in cols
            else "path"
        )
        full_path_canon_expr = _canon_sql(full_path_expr)
        payload_root_canon_expr = _canon_sql("p.root_path")
        ti_root_expr = "CASE WHEN COALESCE(ti.root_name,'') != '' THEN ti.save_path || '/' || ti.root_name ELSE ti.save_path END"
        ti_root_canon_expr = _canon_sql(ti_root_expr)
        mtime_local_expr = (
            "datetime(mtime,'unixepoch','localtime')"
            if "mtime" in cols
            else "NULL"
        )
        order_prefix = "last_seen_at DESC, " if "last_seen_at" in cols else ""
        sql = (
            f"SELECT "
            f"'{table}' AS table_name, "
            f"path, "
            f"{full_path_expr} AS full_path, "
            f"{_col_expr(cols, 'size')}, "
            f"{_col_expr(cols, 'inode')}, "
            f"{_col_expr(cols, 'quick_hash')}, "
            f"{_col_expr(cols, 'sha1')}, "
            f"{_col_expr(cols, 'sha256')}, "
            f"{_col_expr(cols, 'hash_source')}, "
            f"{_col_expr(cols, 'mtime')}, "
            f"{mtime_local_expr} AS mtime_local, "
            f"{_col_expr(cols, 'first_seen_at')}, "
            f"{_col_expr(cols, 'last_seen_at')}, "
            f"{_col_expr(cols, 'last_modified_at')}, "
            f"{status_expr} AS status, "
            f"{_col_expr(cols, 'discovered_under')}, "
            f"COALESCE(( "
            f"  SELECT REPLACE(group_concat(DISTINCT z.torrent_hash), ',', '|') "
            f"  FROM ( "
            f"    SELECT ti.torrent_hash AS torrent_hash "
            f"    FROM payloads p "
            f"    JOIN torrent_instances ti ON ti.payload_id = p.payload_id "
            f"    WHERE ({full_path_canon_expr}) = ({payload_root_canon_expr}) "
            f"       OR ({full_path_canon_expr}) LIKE ({payload_root_canon_expr}) || '/%' "
            f"    UNION "
            f"    SELECT ti.torrent_hash AS torrent_hash "
            f"    FROM torrent_instances ti "
            f"    WHERE ({full_path_canon_expr}) = ({ti_root_canon_expr}) "
            f"       OR ({full_path_canon_expr}) LIKE ({ti_root_canon_expr}) || '/%' "
            f"  ) z "
            f"), '') AS torrent_hashes "
            f"FROM {table}{where_sql} "
            f"ORDER BY {order_prefix}path "
            f"LIMIT ?"
        )
        rows = fetch_rows(conn, sql, params + [max(1, int(limit))])
        for row in rows:
            row["table"] = table
            row["scope"] = "files"
            out.append(row)
    out.sort(
        key=lambda r: (
            1 if r.get("inode") is None else 0,
            int(r.get("inode") or 0),
            str(r.get("full_path") or r.get("path") or ""),
        )
    )
    return out[:limit]


def _short_hash(val: Any) -> str:
    s = str(val or "").strip()
    return s[:8] if s else ("-" * 8)


def _short_hash_list(val: Any, prefix_len: int = 12) -> str:
    raw = str(val or "").strip()
    if not raw:
        return ""
    for sep in (",", " ", "\t", "\n"):
        raw = raw.replace(sep, "|")
    tokens: List[str] = []
    seen = set()
    for tok in raw.split("|"):
        h = tok.strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        tokens.append(h[:prefix_len])
    return "|".join(tokens)


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


def fetch_qb_progress_map(hashes: Sequence[str]) -> Dict[str, float]:
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


def format_torrent_refs(val: Any, progress_map: Dict[str, float], prefix_len: int = 12) -> str:
    hashes = _parse_hash_list(val)
    if not hashes:
        return ""
    refs: List[str] = []
    for h in hashes:
        p = progress_map.get(h)
        if p is None:
            refs.append(f"{h[:prefix_len]}:?")
        else:
            refs.append(f"{h[:prefix_len]}:{p:.2f}%")
    return "|".join(refs)


def compact_files_rows_for_table(rows: List[Dict[str, Any]], progress_map: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        size = row.get("size")
        try:
            size_gib = float(size) / (1024.0 ** 3)
        except Exception:
            size_gib = 0.0
        mtime = row.get("mtime_local") or row.get("last_modified_at") or row.get("last_seen_at") or ""
        out.append(
            {
                "inode": row.get("inode"),
                "size_gib": f"{size_gib:.2f}",
                "mtime": mtime,
                "quick8": _short_hash(row.get("quick_hash")),
                "sha1_8": _short_hash(row.get("sha1")),
                "sha256_8": _short_hash(row.get("sha256")),
                "torrent_hashes": format_torrent_refs(row.get("torrent_hashes"), progress_map, prefix_len=12),
                "full_path": row.get("full_path") or row.get("path") or "",
            }
        )
    out.sort(
        key=lambda r: (
            1 if r.get("inode") in (None, "") else 0,
            int(r.get("inode") or 0),
            str(r.get("full_path") or ""),
        )
    )
    return out


def _short_hash_len(val: Any, n: int) -> str:
    s = str(val or "").strip()
    return s[:n] if s else ("-" * max(1, int(n)))


def _minimal_time(val: Any) -> str:
    s = str(val or "").strip()
    if not s:
        return "-"
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
    except Exception:
        pass
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").strftime("%m-%d %H:%M")
    except Exception:
        pass
    if len(s) >= 16 and s[4] == "-":
        return s[5:16].replace("T", " ")
    return s


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
    return "|".join(hs) if hs else "-", "|".join(ps) if ps else "-"


def compact_files_rows_for_tsv(rows: List[Dict[str, Any]], progress_map: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        size = row.get("size")
        try:
            size_gib = f"{float(size) / (1024.0 ** 3):.2f}"
        except Exception:
            size_gib = "-"
        mtime_src = row.get("mtime_local") or row.get("last_modified_at") or row.get("last_seen_at")
        tor_h, tor_pct = _torrent_hashes_and_pct(row.get("torrent_hashes"), progress_map, prefix_len=6)
        inode = row.get("inode")
        out.append(
            {
                "inode": str(inode) if inode not in (None, "") else "-",
                "size_gib": size_gib,
                "mtime": _minimal_time(mtime_src),
                "quick6": _short_hash_len(row.get("quick_hash"), 6),
                "sha1_6": _short_hash_len(row.get("sha1"), 6),
                "sha256_6": _short_hash_len(row.get("sha256"), 6),
                "tor_hash6": tor_h,
                "tor_pct": tor_pct,
                "full_path": str(row.get("full_path") or row.get("path") or "-"),
            }
        )
    out.sort(
        key=lambda r: (
            1 if r.get("inode") in (None, "", "-") else 0,
            int(r.get("inode") or 0) if str(r.get("inode")).isdigit() else 0,
            str(r.get("full_path") or ""),
        )
    )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Search/query hashall SQLite catalog quickly.")
    p.add_argument("--db", default="~/.hashall/catalog.db", help="SQLite DB path (default: ~/.hashall/catalog.db)")
    p.add_argument("--scope", default="torrents,payloads", help="Comma-separated scopes: torrents,payloads,files")
    p.add_argument("--q", default="", help="Broad case-insensitive search term")
    p.add_argument("--hash", default="", help="Torrent/content hash token (prefix accepted)")
    p.add_argument("--name", default="", help="Name text (root_name/path substring)")
    p.add_argument("--path", default="", help="Path substring")
    p.add_argument("--category", default="", help="Category substring (torrent scope)")
    p.add_argument("--tag", default="", help="Tag substring (torrent scope)")
    p.add_argument("--payload-hash", default="", help="Payload hash token (prefix accepted)")
    p.add_argument(
        "--files-suffix",
        default="",
        help="Optional file suffix filter for files scope (comma-separated, e.g. .mkv,.mp3)",
    )
    p.add_argument(
        "--exclude-torrent-sidecars",
        action="store_true",
        help="Exclude paths ending with .torrent in files scope",
    )
    p.add_argument("--include-deleted", action="store_true", help="Include non-active rows when scanning files_*")
    p.add_argument("--limit", type=int, default=50, help="Max rows returned per run (default: 50)")
    p.add_argument("--format", choices=("table", "json", "tsv"), default="table", help="Output format")
    p.add_argument("--max-width", type=int, default=72, help="Max cell width for table output")
    p.add_argument("--sql", default="", help="Run raw SQL (read-only) and ignore scope filters")
    p.add_argument("--list-tables", action="store_true", help="List tables with row counts")
    p.add_argument("--describe", default="", help="Describe a table schema (PRAGMA table_info)")
    return p


def main() -> int:
    args = build_parser().parse_args()
    emit_start()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"ERROR: db_not_found path={db_path}")
        return 2

    conn = connect_db(db_path, read_only=True, apply_migrations=False)
    try:
        if args.describe:
            table = str(args.describe).strip()
            if not table:
                print("ERROR: empty_table_name")
                return 2
            if not safe_table_name(table):
                print(f"ERROR: unsafe_table_name name={table}")
                return 2
            cols = fetch_rows(conn, f"PRAGMA table_info({table})", [])
            if args.format == "json":
                print(json.dumps(cols, indent=2))
            elif args.format == "tsv":
                print_tsv(cols)
            else:
                print_table(cols, max_width=int(args.max_width))
            return 0

        if args.list_tables:
            rows: List[Dict[str, Any]] = []
            for table in get_tables(conn):
                if not safe_table_name(table):
                    continue
                count_row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                rows.append({"table": table, "rows": int(count_row[0])})
            if args.format == "json":
                print(json.dumps(rows, indent=2))
            elif args.format == "tsv":
                print_tsv(rows)
            else:
                print_table(rows, max_width=int(args.max_width))
            return 0

        if args.sql:
            sql = str(args.sql).strip()
            if not sql:
                print("ERROR: empty_sql")
                return 2
            if ";" in sql:
                print("ERROR: multi_statement_not_allowed")
                return 2
            rows = fetch_rows(conn, sql, [])
            if args.format == "json":
                print(json.dumps(rows, indent=2))
            elif args.format == "tsv":
                print_tsv(rows)
            else:
                print_table(rows, max_width=int(args.max_width))
            print(f"summary rows={len(rows)}")
            return 0

        scopes = parse_scopes(args.scope)
        if not scopes:
            scopes = ["torrents", "payloads"]
        file_suffixes = parse_csv_tokens(args.files_suffix)

        rows: List[Dict[str, Any]] = []
        limit = max(1, int(args.limit))

        if "torrents" in scopes:
            rows.extend(
                query_torrents(
                    conn,
                    term=str(args.q or ""),
                    hash_token=str(args.hash or ""),
                    name=str(args.name or ""),
                    path=str(args.path or ""),
                    category=str(args.category or ""),
                    tag=str(args.tag or ""),
                    payload_hash=str(args.payload_hash or ""),
                    limit=limit,
                )
            )

        if "payloads" in scopes and len(rows) < limit:
            payload_relevant = bool(args.q or args.path or args.payload_hash or args.name)
            if payload_relevant:
                rows.extend(
                    query_payloads(
                        conn,
                        term=str(args.q or ""),
                        name=str(args.name or ""),
                        path=str(args.path or ""),
                        payload_hash=str(args.payload_hash or ""),
                        limit=max(1, limit - len(rows)),
                    )
                )

        if "files" in scopes and len(rows) < limit:
            rows.extend(
                query_files_tables(
                    conn,
                    term=str(args.q or ""),
                    path=str(args.path or ""),
                    name=str(args.name or ""),
                    hash_token=str(args.hash or ""),
                    path_suffixes=file_suffixes,
                    exclude_torrent_sidecars=bool(args.exclude_torrent_sidecars),
                    include_deleted=bool(args.include_deleted),
                    limit=max(1, limit - len(rows)),
                )
            )

        rows = rows[:limit]
        if args.format in {"table", "tsv"} and scopes == ["files"] and rows:
            all_hashes: List[str] = []
            seen_hashes = set()
            for row in rows:
                for h in _parse_hash_list(row.get("torrent_hashes")):
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)
                    all_hashes.append(h)
            progress_map = fetch_qb_progress_map(all_hashes)
            if args.format == "tsv":
                rows = compact_files_rows_for_tsv(rows, progress_map)
            else:
                rows = compact_files_rows_for_table(rows, progress_map)

        if args.format == "json":
            print(json.dumps(rows, indent=2))
        elif args.format == "tsv":
            print_tsv(rows)
        else:
            print_table(rows, max_width=int(args.max_width))
        print(f"summary rows={len(rows)} scopes={','.join(scopes)} db={db_path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
