"""
Operational status report for hashall catalogs.

Generates a user-focused summary of:
- Root inventory and hardlink density
- Duplicate "pockets" (heat map style rankings)
- Payload group health and rehome opportunities
- Suggested next cleanup commands
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Optional

from hashall.fs_utils import get_filesystem_uuid, get_mount_source
from hashall.model import connect_db
from hashall.payload_completion import load_completed_torrent_hashes
from hashall.pathing import canonicalize_path, is_under
from hashall.scan import _canonicalize_root


@dataclass
class RootContext:
    root_input: str
    canonical_root: str
    device_id: int
    device_alias: str
    rel_root: str
    root_kind: str
    fs_uuid: str
    scan_last_scanned_at: Optional[str]


def _fmt_bytes(num_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(max(0, int(num_bytes)))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _utc_stamp() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _classify_root(root: str) -> str:
    root_norm = str(Path(root))
    if root_norm.startswith("/pool/"):
        return "pool"
    if root_norm.startswith("/stash/"):
        return "stash"
    if root_norm.startswith("/data/media"):
        return "media"
    return root_norm


def _path_in_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _discover_roots(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT root_path
        FROM scan_roots
        WHERE root_path IS NOT NULL AND root_path != ''
        ORDER BY COALESCE(last_scanned_at, '') DESC, root_path ASC
        """
    ).fetchall()
    roots: list[str] = []
    seen: set[str] = set()
    for row in rows:
        root = str(row[0])
        if root not in seen:
            roots.append(root)
            seen.add(root)
    if roots:
        return roots

    payload_rows = conn.execute("SELECT DISTINCT root_path FROM payloads ORDER BY root_path").fetchall()
    for row in payload_rows:
        root = str(row[0])
        if root not in seen:
            roots.append(root)
            seen.add(root)
    return roots


def _resolve_roots(conn: sqlite3.Connection, roots_arg: Optional[str]) -> list[str]:
    if roots_arg:
        return [r.strip() for r in roots_arg.split(",") if r.strip()]
    return _discover_roots(conn)


def _resolve_root_context(conn: sqlite3.Connection, root: str) -> RootContext:
    root_input = str(Path(root))
    root_resolved = Path(root).resolve()
    root_canonical = canonicalize_path(root_resolved)
    device_id = os.stat(root_canonical).st_dev

    row = conn.execute(
        "SELECT device_alias, mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()

    if row:
        device_alias = str(row[0] or device_id)
        current_mount = Path(str(row[1]))
        preferred_mount = Path(str(row[2] or row[1]))
    else:
        device_alias = str(device_id)
        current_mount = Path(root_canonical.anchor if root_canonical.anchor else "/")
        preferred_mount = current_mount

    mount_source = get_mount_source(str(root_canonical)) or ""
    canonical_root = _canonicalize_root(
        root_canonical,
        current_mount,
        preferred_mount,
        allow_remap=bool(mount_source),
    )
    effective_mount = preferred_mount if is_under(canonical_root, preferred_mount) else current_mount
    try:
        rel_root = str(canonical_root.relative_to(effective_mount))
    except ValueError:
        rel_root = "."

    scan_row = conn.execute(
        """
        SELECT last_scanned_at
        FROM scan_roots
        WHERE root_path = ?
        ORDER BY COALESCE(last_scanned_at, '') DESC
        LIMIT 1
        """,
        (str(canonical_root),),
    ).fetchone()

    return RootContext(
        root_input=root_input,
        canonical_root=str(canonical_root),
        device_id=device_id,
        device_alias=device_alias,
        rel_root=rel_root,
        root_kind=_classify_root(root_input),
        fs_uuid=get_filesystem_uuid(str(root_canonical)),
        scan_last_scanned_at=str(scan_row[0]) if scan_row and scan_row[0] else None,
    )


def _scope_clause(rel_root: str) -> tuple[str, tuple]:
    if rel_root == ".":
        return "1=1", ()
    pattern = f"{rel_root.rstrip('/')}/%"
    return "(path = ? OR path LIKE ?)", (rel_root, pattern)


def _relative_to_scope(table_path: str, rel_root: str) -> str:
    if rel_root == ".":
        return table_path
    prefix = rel_root.rstrip("/")
    if table_path == prefix:
        return "."
    with_slash = prefix + "/"
    if table_path.startswith(with_slash):
        return table_path[len(with_slash):]
    return table_path


def _pocket_for_path(ctx: RootContext, table_path: str, depth: int) -> str:
    rel = _relative_to_scope(table_path, ctx.rel_root)
    rel_path = Path(rel)
    parent_parts = [p for p in rel_path.parent.parts if p and p != "."]
    if not parent_parts:
        pocket_parts = ["."]
    else:
        pocket_parts = parent_parts[: max(1, depth)]
    return str(Path(ctx.canonical_root).joinpath(*pocket_parts))


def _collect_root_file_metrics(conn: sqlite3.Connection, ctx: RootContext) -> dict:
    table_name = f"files_{ctx.device_id}"
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not table_exists:
        return {
            "active_files": 0,
            "active_bytes": 0,
            "unique_inodes": 0,
            "hardlinked_files": 0,
            "hardlink_ratio": 0.0,
            "duplicate_sha256_groups": 0,
            "link_actions_nonzero": 0,
            "link_actions_zero_bytes": 0,
            "link_actions_possible": 0,
            "bytes_saveable": 0,
            "duplicate_pockets": [],
        }

    scope_sql, scope_params = _scope_clause(ctx.rel_root)

    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS active_files,
            COALESCE(SUM(size), 0) AS active_bytes,
            COUNT(DISTINCT inode) AS unique_inodes
        FROM {table_name}
        WHERE status = 'active' AND {scope_sql}
        """,
        scope_params,
    ).fetchone()
    active_files = int(row[0] or 0)
    active_bytes = int(row[1] or 0)
    unique_inodes = int(row[2] or 0)
    hardlinked_files = max(0, active_files - unique_inodes)
    hardlink_ratio = (hardlinked_files / active_files) if active_files else 0.0

    dup_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS groups,
            COALESCE(SUM(CASE WHEN size > 0 THEN (unique_inodes - 1) ELSE 0 END), 0) AS actions_nonzero,
            COALESCE(SUM(CASE WHEN size = 0 THEN (unique_inodes - 1) ELSE 0 END), 0) AS actions_zero,
            COALESCE(SUM(CASE WHEN size > 0 THEN (unique_inodes - 1) * size ELSE 0 END), 0) AS bytes_saveable
        FROM (
            SELECT sha256, size, COUNT(DISTINCT inode) AS unique_inodes
            FROM {table_name}
            WHERE status = 'active' AND sha256 IS NOT NULL AND {scope_sql}
            GROUP BY sha256, size
            HAVING COUNT(DISTINCT inode) > 1
        )
        """,
        scope_params,
    ).fetchone()
    duplicate_sha256_groups = int(dup_row[0] or 0)
    link_actions_nonzero = int(dup_row[1] or 0)
    link_actions_zero_bytes = int(dup_row[2] or 0)
    link_actions_possible = link_actions_nonzero + link_actions_zero_bytes
    bytes_saveable = int(dup_row[3] or 0)

    return {
        "active_files": active_files,
        "active_bytes": active_bytes,
        "unique_inodes": unique_inodes,
        "hardlinked_files": hardlinked_files,
        "hardlink_ratio": hardlink_ratio,
        "duplicate_sha256_groups": duplicate_sha256_groups,
        "link_actions_nonzero": link_actions_nonzero,
        "link_actions_zero_bytes": link_actions_zero_bytes,
        "link_actions_possible": link_actions_possible,
        "bytes_saveable": bytes_saveable,
    }


def _collect_duplicate_pockets(
    conn: sqlite3.Connection,
    ctx: RootContext,
    *,
    pocket_depth: int,
    top_n: int,
) -> list[dict]:
    table_name = f"files_{ctx.device_id}"
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    if not table_exists:
        return []

    scope_sql, scope_params = _scope_clause(ctx.rel_root)
    rows = conn.execute(
        f"""
        SELECT sha256, size, inode, path
        FROM {table_name}
        WHERE status = 'active' AND sha256 IS NOT NULL AND {scope_sql}
        ORDER BY sha256, size, path
        """,
        scope_params,
    ).fetchall()

    pockets: dict[str, dict] = {}
    current_key: Optional[tuple] = None
    inode_paths: dict[int, str] = {}

    def _commit_group(group_key: Optional[tuple], representatives: dict[int, str]) -> None:
        if group_key is None:
            return
        size = int(group_key[1])
        if len(representatives) <= 1:
            return

        sorted_items = sorted(representatives.items(), key=lambda item: (item[0], len(item[1]), item[1]))
        canonical_inode, _ = sorted_items[0]
        touched_pockets: set[str] = set()

        for inode, path in sorted_items:
            if inode == canonical_inode:
                continue
            pocket = _pocket_for_path(ctx, path, pocket_depth)
            stats = pockets.setdefault(
                pocket,
                {
                    "pocket": pocket,
                    "actions": 0,
                    "bytes_saveable": 0,
                    "groups": 0,
                    "sample_path": str(Path(ctx.canonical_root) / _relative_to_scope(path, ctx.rel_root)),
                },
            )
            stats["actions"] += 1
            stats["bytes_saveable"] += size
            if pocket not in touched_pockets:
                stats["groups"] += 1
                touched_pockets.add(pocket)

    for sha256, size, inode, path in rows:
        key = (str(sha256), int(size))
        if current_key is None:
            current_key = key
        if key != current_key:
            _commit_group(current_key, inode_paths)
            inode_paths = {}
            current_key = key
        inode_paths.setdefault(int(inode), str(path))
    _commit_group(current_key, inode_paths)

    ranked = sorted(
        pockets.values(),
        key=lambda item: (int(item["bytes_saveable"]), int(item["actions"]), int(item["groups"])),
        reverse=True,
    )
    return ranked[:top_n]


def _load_payload_rows(
    conn: sqlite3.Connection,
    *,
    completed_hashes: set[str],
    completion_filter_active: bool,
) -> list[dict]:
    payload_rows = conn.execute(
        """
        SELECT payload_id, payload_hash, status, file_count, total_bytes, root_path, device_id
        FROM payloads
        ORDER BY payload_id
        """
    ).fetchall()

    ref_rows = conn.execute("SELECT payload_id, torrent_hash FROM torrent_instances").fetchall()
    ref_counts: dict[int, int] = {}
    complete_ref_by_payload: dict[int, bool] = {}
    completed_lc = {h.lower() for h in completed_hashes}
    for payload_id, torrent_hash in ref_rows:
        pid = int(payload_id)
        ref_counts[pid] = ref_counts.get(pid, 0) + 1
        if (
            completion_filter_active
            and torrent_hash
            and str(torrent_hash).lower() in completed_lc
        ):
            complete_ref_by_payload[pid] = True

    rows = []
    for row in payload_rows:
        payload_id = int(row[0])
        rows.append(
            {
                "payload_id": payload_id,
                "payload_hash": str(row[1]) if row[1] else None,
                "status": str(row[2]),
                "file_count": int(row[3] or 0),
                "total_bytes": int(row[4] or 0),
                "root_path": str(row[5]),
                "device_id": int(row[6]) if row[6] is not None else None,
                "ref_count": int(ref_counts.get(payload_id, 0)),
                "has_complete_ref": bool(complete_ref_by_payload.get(payload_id, False)),
            }
        )
    return rows


def _root_for_payload(payload_root: str, contexts: list[RootContext]) -> Optional[RootContext]:
    for ctx in contexts:
        if _path_in_root(payload_root, ctx.root_input) or _path_in_root(payload_root, ctx.canonical_root):
            return ctx
    return None


def _collect_payload_metrics(
    contexts: list[RootContext],
    payload_rows: list[dict],
    *,
    completion_filter_active: bool,
) -> dict:
    per_root = {
        ctx.root_input: {
            "payload_total": 0,
            "payload_complete": 0,
            "payload_incomplete": 0,
            "payload_needs_upgrade": 0,
            "payload_incomplete_zero_files": 0,
            "dirty_actionable": 0,
            "dirty_noncomplete": 0,
            "dirty_orphan": 0,
        }
        for ctx in contexts
    }

    for row in payload_rows:
        ctx = _root_for_payload(row["root_path"], contexts)
        if ctx is None:
            continue
        bucket = per_root[ctx.root_input]
        bucket["payload_total"] += 1
        if row["status"] == "complete":
            bucket["payload_complete"] += 1
        else:
            bucket["payload_incomplete"] += 1
            if int(row["file_count"]) > 0:
                bucket["payload_needs_upgrade"] += 1
            else:
                bucket["payload_incomplete_zero_files"] += 1

        if int(row["file_count"]) == 0:
            ref_count = int(row.get("ref_count", 0))
            if ref_count > 0:
                if completion_filter_active and not bool(row.get("has_complete_ref", False)):
                    bucket["dirty_noncomplete"] += 1
                else:
                    bucket["dirty_actionable"] += 1
            else:
                bucket["dirty_orphan"] += 1

    return per_root


def _collect_payload_groups(
    contexts: list[RootContext],
    payload_rows: list[dict],
    *,
    media_root: str,
    top_n: int,
    completion_filter_active: bool,
) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in payload_rows:
        if row["status"] != "complete":
            continue
        payload_hash = row["payload_hash"]
        if not payload_hash:
            continue
        if _root_for_payload(row["root_path"], contexts) is None:
            continue
        groups[payload_hash].append(row)

    group_summaries: list[dict] = []
    stash_to_pool_groups = 0
    stash_to_pool_bytes = 0
    pool_to_stash_groups = 0
    pool_to_stash_bytes = 0
    stash_to_pool_no_growth_groups = 0
    stash_to_pool_no_growth_bytes = 0
    no_growth_group_summaries: list[dict] = []
    impact_summaries: list[dict] = []
    recommendation_counts = {"MOVE": 0, "PARTIAL_REVIEW": 0, "SKIP": 0}

    for payload_hash, rows in groups.items():
        if len(rows) < 2:
            continue

        roots_present: set[str] = set()
        for row in rows:
            owner = _root_for_payload(row["root_path"], contexts)
            if owner:
                roots_present.add(owner.root_kind)

        has_media = any(_path_in_root(row["root_path"], media_root) for row in rows)
        has_stash = "stash" in roots_present
        has_pool = "pool" in roots_present
        total_bytes = max(int(row["total_bytes"]) for row in rows)

        if has_stash and not has_media:
            stash_to_pool_groups += 1
            stash_to_pool_bytes += total_bytes
        if has_pool and has_media:
            pool_to_stash_groups += 1
            pool_to_stash_bytes += total_bytes
        if has_stash and has_pool:
            stash_to_pool_no_growth_groups += 1
            stash_to_pool_no_growth_bytes += total_bytes
            no_growth_group_summaries.append(
                {
                    "payload_hash": payload_hash,
                    "copies": len(rows),
                    "total_bytes": total_bytes,
                    "sample_paths": sorted(row["root_path"] for row in rows)[:4],
                }
            )

        if has_stash:
            stash_rows: list[dict] = []
            for row in rows:
                owner = _root_for_payload(row["root_path"], contexts)
                if owner and owner.root_kind == "stash":
                    stash_rows.append(row)
            stash_files = sum(int(row.get("file_count", 0)) for row in stash_rows)
            stash_bytes = sum(int(row.get("total_bytes", 0)) for row in stash_rows)
            movable_files = 0
            movable_bytes = 0
            blocked_files = 0
            blocked_bytes = 0
            block_reason_counts: dict[str, int] = defaultdict(int)

            for row in stash_rows:
                row_files = int(row.get("file_count", 0))
                row_bytes = int(row.get("total_bytes", 0))
                ref_count = int(row.get("ref_count", 0))
                has_complete_ref = bool(row.get("has_complete_ref", True))

                block_reason: Optional[str] = None
                if has_media:
                    block_reason = "external_media_copy"
                elif not has_pool:
                    block_reason = "pool_copy_missing"
                elif ref_count == 0:
                    block_reason = "no_torrent_refs"
                elif completion_filter_active and not has_complete_ref:
                    block_reason = "noncomplete_refs"

                if block_reason is None:
                    movable_files += row_files
                    movable_bytes += row_bytes
                else:
                    blocked_files += row_files
                    blocked_bytes += row_bytes
                    block_reason_counts[block_reason] += 1

            movable_pct_files = (movable_files / stash_files) if stash_files else 0.0
            movable_pct_bytes = (movable_bytes / stash_bytes) if stash_bytes else 0.0

            if movable_bytes <= 0:
                recommendation = "SKIP"
            elif movable_pct_bytes >= 0.90:
                recommendation = "MOVE"
            elif movable_pct_bytes >= 0.40:
                recommendation = "PARTIAL_REVIEW"
            else:
                recommendation = "SKIP"
            recommendation_counts[recommendation] += 1

            impact_summaries.append(
                {
                    "payload_hash": payload_hash,
                    "copies": len(rows),
                    "stash_total_files": stash_files,
                    "stash_total_bytes": stash_bytes,
                    "movable_files": movable_files,
                    "movable_bytes": movable_bytes,
                    "blocked_files": blocked_files,
                    "blocked_bytes": blocked_bytes,
                    "movable_pct_files": movable_pct_files,
                    "movable_pct_bytes": movable_pct_bytes,
                    "recommendation": recommendation,
                    "block_reason_counts": dict(sorted(block_reason_counts.items())),
                    "sample_paths": sorted(row["root_path"] for row in rows)[:4],
                }
            )

        group_summaries.append(
            {
                "payload_hash": payload_hash,
                "copies": len(rows),
                "roots": sorted(roots_present),
                "has_media_consumer_copy": has_media,
                "total_bytes": total_bytes,
                "sample_paths": sorted(row["root_path"] for row in rows)[:3],
            }
        )

    group_summaries.sort(key=lambda item: (item["copies"], item["total_bytes"]), reverse=True)
    top_groups = group_summaries[:top_n]
    no_growth_group_summaries.sort(key=lambda item: (item["total_bytes"], item["copies"]), reverse=True)
    top_no_growth_groups = no_growth_group_summaries[:top_n]
    impact_summaries.sort(
        key=lambda item: (item["movable_bytes"], item["movable_pct_bytes"], item["copies"]),
        reverse=True,
    )
    top_impact_groups = impact_summaries[:top_n]

    return {
        "confirmed_groups": len(group_summaries),
        "top_groups": top_groups,
        "top_no_growth_groups": top_no_growth_groups,
        "top_impact_groups": top_impact_groups,
        "impact_summary": {
            "move": int(recommendation_counts["MOVE"]),
            "partial_review": int(recommendation_counts["PARTIAL_REVIEW"]),
            "skip": int(recommendation_counts["SKIP"]),
        },
        "rehome_opportunities": {
            "stash_to_pool_groups": stash_to_pool_groups,
            "stash_to_pool_estimated_bytes": stash_to_pool_bytes,
            "pool_to_stash_groups": pool_to_stash_groups,
            "pool_to_stash_estimated_bytes": pool_to_stash_bytes,
            "stash_to_pool_no_growth_groups": stash_to_pool_no_growth_groups,
            "stash_to_pool_no_growth_estimated_bytes": stash_to_pool_no_growth_bytes,
        },
    }


def _path_to_rel_for_context(path: str, ctx: RootContext) -> Optional[str]:
    try:
        normalized = str(canonicalize_path(Path(path)))
    except Exception:
        normalized = str(Path(path))
    for base in (ctx.canonical_root, ctx.root_input):
        if normalized == base:
            return "."
        prefix = base.rstrip("/") + "/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
    return None


def _collect_recovery_no_growth(
    conn: sqlite3.Connection,
    *,
    contexts: list[RootContext],
    recovery_prefix: str,
    top_n: int,
) -> dict:
    stash_ctx = next((c for c in contexts if c.root_kind == "stash"), None)
    pool_ctx = next((c for c in contexts if c.root_kind == "pool"), None)
    if stash_ctx is None or pool_ctx is None:
        return {
            "available": False,
            "reason": "missing_pool_or_stash_root",
            "recovery_prefix": recovery_prefix,
            "matched_files": 0,
            "matched_bytes": 0,
            "unmatched_files": 0,
            "unmatched_bytes": 0,
            "samples": [],
        }

    rel_prefix = _path_to_rel_for_context(recovery_prefix, stash_ctx)
    if rel_prefix is None:
        return {
            "available": False,
            "reason": "prefix_not_under_stash_root",
            "recovery_prefix": recovery_prefix,
            "matched_files": 0,
            "matched_bytes": 0,
            "unmatched_files": 0,
            "unmatched_bytes": 0,
            "samples": [],
        }

    stash_table = f"files_{stash_ctx.device_id}"
    pool_table = f"files_{pool_ctx.device_id}"
    stash_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (stash_table,),
    ).fetchone()
    pool_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (pool_table,),
    ).fetchone()
    if not stash_exists or not pool_exists:
        return {
            "available": False,
            "reason": "missing_pool_or_stash_file_tables",
            "recovery_prefix": recovery_prefix,
            "matched_files": 0,
            "matched_bytes": 0,
            "unmatched_files": 0,
            "unmatched_bytes": 0,
            "samples": [],
        }

    if rel_prefix == ".":
        scope_sql = "1=1"
        scope_params: tuple = ()
    else:
        scope_sql = "(path = ? OR path LIKE ?)"
        scope_params = (rel_prefix, f"{rel_prefix.rstrip('/')}/%")

    totals_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_files,
            COALESCE(SUM(size), 0) AS total_bytes,
            COALESCE(SUM(CASE WHEN sha256 IS NOT NULL THEN 1 ELSE 0 END), 0) AS hashed_files,
            COALESCE(SUM(CASE WHEN sha256 IS NOT NULL THEN size ELSE 0 END), 0) AS hashed_bytes
        FROM {stash_table}
        WHERE status = 'active' AND {scope_sql}
        """,
        scope_params,
    ).fetchone()
    total_files = int(totals_row[0] or 0)
    total_bytes = int(totals_row[1] or 0)
    hashed_files = int(totals_row[2] or 0)
    hashed_bytes = int(totals_row[3] or 0)

    matched_row = conn.execute(
        f"""
        WITH rec AS (
            SELECT path, size, sha256
            FROM {stash_table}
            WHERE status = 'active' AND sha256 IS NOT NULL AND {scope_sql}
        ),
        pool AS (
            SELECT DISTINCT sha256, size
            FROM {pool_table}
            WHERE status = 'active' AND sha256 IS NOT NULL
        )
        SELECT
            COUNT(*) AS matched_files,
            COALESCE(SUM(rec.size), 0) AS matched_bytes
        FROM rec
        JOIN pool ON pool.sha256 = rec.sha256 AND pool.size = rec.size
        """,
        scope_params,
    ).fetchone()
    matched_files = int(matched_row[0] or 0)
    matched_bytes = int(matched_row[1] or 0)

    sample_rows = conn.execute(
        f"""
        WITH rec AS (
            SELECT path, size, sha256
            FROM {stash_table}
            WHERE status = 'active' AND sha256 IS NOT NULL AND {scope_sql}
        ),
        pool AS (
            SELECT DISTINCT sha256, size
            FROM {pool_table}
            WHERE status = 'active' AND sha256 IS NOT NULL
        )
        SELECT rec.path, rec.size
        FROM rec
        JOIN pool ON pool.sha256 = rec.sha256 AND pool.size = rec.size
        ORDER BY rec.size DESC, rec.path ASC
        LIMIT ?
        """,
        (*scope_params, max(1, top_n)),
    ).fetchall()
    samples = []
    for row in sample_rows:
        rel_path = str(row[0])
        abs_path = (
            str(Path(stash_ctx.canonical_root) / rel_path)
            if rel_path != "."
            else stash_ctx.canonical_root
        )
        samples.append({"path": abs_path, "bytes": int(row[1] or 0)})

    return {
        "available": True,
        "reason": None,
        "recovery_prefix": recovery_prefix,
        "recovery_rel_prefix": rel_prefix,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "hashed_files": hashed_files,
        "hashed_bytes": hashed_bytes,
        "matched_files": matched_files,
        "matched_bytes": matched_bytes,
        "unmatched_files": max(0, hashed_files - matched_files),
        "unmatched_bytes": max(0, hashed_bytes - matched_bytes),
        "samples": samples,
    }


def _collect_orphan_gc(conn: sqlite3.Connection) -> dict:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='payload_orphan_gc'"
    ).fetchone()
    if not table_exists:
        return {
            "tracked": 0,
            "aged": 0,
            "samples": [],
        }

    tracked = int(conn.execute("SELECT COUNT(*) FROM payload_orphan_gc").fetchone()[0] or 0)
    aged = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM payload_orphan_gc
            WHERE seen_count >= 2 AND first_seen_at <= (strftime('%s','now') - 86400)
            """
        ).fetchone()[0]
        or 0
    )
    samples = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT COALESCE(last_root_path, '<unknown>')
            FROM payload_orphan_gc
            ORDER BY last_seen_at DESC
            LIMIT 5
            """
        ).fetchall()
    ]
    return {
        "tracked": tracked,
        "aged": aged,
        "samples": samples,
    }


def _collect_db_health(conn: sqlite3.Connection) -> dict:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()
    quick_check_status = str(quick_check[0]) if quick_check else "unknown"
    return {"quick_check": quick_check_status}


def _db_fingerprint(db_path: Path) -> dict:
    db_stat = db_path.stat()
    wal_path = Path(f"{db_path}-wal")
    shm_path = Path(f"{db_path}-shm")
    wal_stat = wal_path.stat() if wal_path.exists() else None
    shm_stat = shm_path.stat() if shm_path.exists() else None
    return {
        "db_path": str(db_path.resolve()),
        "db_mtime_ns": int(db_stat.st_mtime_ns),
        "db_size": int(db_stat.st_size),
        "wal_mtime_ns": int(wal_stat.st_mtime_ns) if wal_stat else 0,
        "wal_size": int(wal_stat.st_size) if wal_stat else 0,
        "shm_mtime_ns": int(shm_stat.st_mtime_ns) if shm_stat else 0,
        "shm_size": int(shm_stat.st_size) if shm_stat else 0,
    }


def _cache_key(
    *,
    db_path: Path,
    roots_arg: Optional[str],
    media_root: str,
    pocket_depth: int,
    top_n: int,
    recovery_prefix: str,
) -> dict:
    roots_norm = ",".join(
        sorted({part.strip() for part in (roots_arg or "").split(",") if part.strip()})
    )
    return {
        "fingerprint": _db_fingerprint(db_path),
        "roots": roots_norm,
        "media_root": str(Path(media_root)),
        "pocket_depth": int(pocket_depth),
        "top_n": int(top_n),
        "recovery_prefix": str(Path(recovery_prefix)),
    }


def _cache_file(output_dir: str) -> Path:
    return Path(output_dir) / "hashall-status-cache.json"


def _load_cached_report(
    *,
    cache_path: Path,
    expected_key: dict,
    ttl_seconds: int,
) -> Optional[dict]:
    if ttl_seconds <= 0 or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    created_at = float(payload.get("created_at_epoch", 0))
    if created_at <= 0 or (time.time() - created_at) > ttl_seconds:
        return None

    if payload.get("key") != expected_key:
        return None

    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    return report


def _write_cached_report(*, cache_path: Path, cache_key: dict, report: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "created_at_epoch": time.time(),
        "key": cache_key,
        "report": report,
    }
    cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class _Spinner(AbstractContextManager):
    def __init__(self, message: str, *, enabled: bool) -> None:
        self._message = message
        self._enabled = enabled
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_Spinner":
        if not self._enabled:
            return self

        def _run() -> None:
            frames = "|/-\\"
            i = 0
            while not self._stop.is_set():
                frame = frames[i % len(frames)]
                sys.stderr.write(f"\r{self._message} {frame}")
                sys.stderr.flush()
                i += 1
                self._stop.wait(0.1)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        if not self._enabled:
            return None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        sys.stderr.write(f"\r{self._message} done\n")
        sys.stderr.flush()
        return None


def _build_actions(report: dict) -> list[dict]:
    actions: list[dict] = []
    roots_csv = ",".join(item["root"] for item in report["roots"])

    if report["totals"]["dirty_actionable"] > 0:
        actions.append(
            {
                "priority": "P0",
                "reason": "actionable dirty payload rows exist",
                "command": f"make payload-auto ROOTS='{roots_csv}'",
            }
        )

    if report["totals"]["link_actions_nonzero"] > 0:
        actions.append(
            {
                "priority": "P0",
                "reason": "hardlink actions are available",
                "command": f"make hardlink-auto ROOTS='{roots_csv}' HARDLINK_AUTO_EXECUTE=1",
            }
        )

    if report["totals"]["payload_needs_upgrade"] > 0:
        actions.append(
            {
                "priority": "P1",
                "reason": "payload rows have files but are still incomplete (missing SHA256)",
                "command": f"make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1 PAYLOAD_PATH_PREFIXES='{' '.join(item['root'] for item in report['roots'])}'",
            }
        )

    if report["totals"]["dirty_noncomplete"] > 0:
        actions.append(
            {
                "priority": "P3",
                "reason": "refs below 100% completion were ignored (informational noise)",
                "command": "make payload-workflow PW_PATHS='/pool/data /stash/media /data/media'",
            }
        )

    if report["orphans"]["tracked"] > 0:
        actions.append(
            {
                "priority": "P1",
                "reason": "orphan staging rows need review",
                "command": f"make payload-orphan-audit PAYLOAD_ORPHAN_AUDIT_PATH_PREFIXES='{' '.join(item['root'] for item in report['roots'])}'",
            }
        )

    if report["rehome"]["stash_to_pool_groups"] > 0 or report["rehome"]["pool_to_stash_groups"] > 0:
        actions.append(
            {
                "priority": "P2",
                "reason": "rehome opportunities detected (review before apply)",
                "command": "make rehome-checklist",
            }
        )
    if report["rehome"]["stash_to_pool_no_growth_groups"] > 0:
        actions.append(
            {
                "priority": "P1",
                "reason": "no-pool-growth stash demote candidates detected",
                "command": "make rehome-checklist",
            }
        )
    if int(report.get("rehome_impact_summary", {}).get("partial_review", 0)) > 0:
        actions.append(
            {
                "priority": "P2",
                "reason": "some payload groups are mostly movable but partially blocked",
                "command": "make rehome-checklist",
            }
        )

    return actions


def build_status_report(
    conn: sqlite3.Connection,
    *,
    roots_arg: Optional[str],
    media_root: str,
    pocket_depth: int,
    top_n: int,
    recovery_prefix: str,
    completed_hashes: Optional[set[str]] = None,
    completion_filter_active: Optional[bool] = None,
    completion_filter_error: Optional[str] = None,
) -> dict:
    roots = _resolve_roots(conn, roots_arg)
    if not roots:
        raise RuntimeError("No roots discovered. Pass --roots or run scans first.")

    if completion_filter_active is None:
        completed_hashes, completion_filter_active, completion_filter_error = load_completed_torrent_hashes()
    completed_hashes = set(completed_hashes or set())
    completion_filter_active = bool(completion_filter_active)

    contexts = [_resolve_root_context(conn, root) for root in roots]

    roots_out: list[dict] = []
    total_active_files = 0
    total_active_bytes = 0
    total_duplicate_groups = 0
    total_link_actions_nonzero = 0
    total_link_actions_zero = 0
    total_link_actions = 0
    total_saveable_bytes = 0
    all_pockets: list[dict] = []
    scope_metrics_cache: dict[tuple[int, str], dict] = {}
    scope_primary_root: dict[tuple[int, str], str] = {}

    for ctx in contexts:
        scope_key = (ctx.device_id, ctx.rel_root)
        alias_of = None
        if scope_key not in scope_metrics_cache:
            file_metrics = _collect_root_file_metrics(conn, ctx)
            pockets = _collect_duplicate_pockets(conn, ctx, pocket_depth=pocket_depth, top_n=top_n)
            scope_metrics_cache[scope_key] = file_metrics
            scope_primary_root[scope_key] = ctx.root_input
            all_pockets.extend(pockets)

            total_active_files += int(file_metrics["active_files"])
            total_active_bytes += int(file_metrics["active_bytes"])
            total_duplicate_groups += int(file_metrics["duplicate_sha256_groups"])
            total_link_actions_nonzero += int(file_metrics["link_actions_nonzero"])
            total_link_actions_zero += int(file_metrics["link_actions_zero_bytes"])
            total_link_actions += int(file_metrics["link_actions_possible"])
            total_saveable_bytes += int(file_metrics["bytes_saveable"])
        else:
            file_metrics = scope_metrics_cache[scope_key]
            alias_of = scope_primary_root[scope_key]

        roots_out.append(
            {
                "root": ctx.root_input,
                "canonical_root": ctx.canonical_root,
                "device_id": ctx.device_id,
                "device_alias": ctx.device_alias,
                "fs_uuid": ctx.fs_uuid,
                "rel_root": ctx.rel_root,
                "scan_last_scanned_at": ctx.scan_last_scanned_at,
                "scope_alias_of": alias_of,
                **file_metrics,
            }
        )

    payload_rows = _load_payload_rows(
        conn,
        completed_hashes=completed_hashes,
        completion_filter_active=completion_filter_active,
    )
    payload_per_root = _collect_payload_metrics(
        contexts,
        payload_rows,
        completion_filter_active=completion_filter_active,
    )
    payload_groups = _collect_payload_groups(
        contexts,
        payload_rows,
        media_root=media_root,
        top_n=top_n,
        completion_filter_active=completion_filter_active,
    )
    recovery_no_growth = _collect_recovery_no_growth(
        conn,
        contexts=contexts,
        recovery_prefix=recovery_prefix,
        top_n=top_n,
    )

    for root_entry in roots_out:
        payload_metrics = payload_per_root.get(root_entry["root"], {})
        root_entry.update(payload_metrics)

    pocket_index: dict[str, dict] = {}
    for item in all_pockets:
        key = item["pocket"]
        agg = pocket_index.setdefault(
            key,
            {
                "pocket": key,
                "actions": 0,
                "bytes_saveable": 0,
                "groups": 0,
                "sample_path": item["sample_path"],
            },
        )
        agg["actions"] += int(item["actions"])
        agg["bytes_saveable"] += int(item["bytes_saveable"])
        agg["groups"] += int(item["groups"])
    top_pockets = sorted(
        pocket_index.values(),
        key=lambda item: (item["bytes_saveable"], item["actions"], item["groups"]),
        reverse=True,
    )
    top_nonzero = [row for row in top_pockets if int(row["bytes_saveable"]) > 0][:top_n]
    if top_nonzero:
        top_pockets = top_nonzero
    else:
        top_pockets = top_pockets[:top_n]

    orphan_gc = _collect_orphan_gc(conn)
    db_health = _collect_db_health(conn)

    totals = {
        "active_files": total_active_files,
        "active_bytes": total_active_bytes,
        "duplicate_sha256_groups": total_duplicate_groups,
        "link_actions_nonzero": total_link_actions_nonzero,
        "link_actions_zero_bytes": total_link_actions_zero,
        "link_actions_possible": total_link_actions,
        "bytes_saveable": total_saveable_bytes,
        "payload_total": sum(int(r.get("payload_total", 0)) for r in roots_out),
        "payload_complete": sum(int(r.get("payload_complete", 0)) for r in roots_out),
        "payload_incomplete": sum(int(r.get("payload_incomplete", 0)) for r in roots_out),
        "payload_needs_upgrade": sum(int(r.get("payload_needs_upgrade", 0)) for r in roots_out),
        "payload_incomplete_zero_files": sum(int(r.get("payload_incomplete_zero_files", 0)) for r in roots_out),
        "dirty_actionable": sum(int(r.get("dirty_actionable", 0)) for r in roots_out),
        "dirty_noncomplete": sum(int(r.get("dirty_noncomplete", 0)) for r in roots_out),
        "dirty_orphan": sum(int(r.get("dirty_orphan", 0)) for r in roots_out),
    }

    report = {
        "generated_at": _now_stamp(),
        "generated_at_utc": _utc_stamp(),
        "media_root": media_root,
        "recovery_prefix": recovery_prefix,
        "roots": roots_out,
        "totals": totals,
        "completion_filter_active": completion_filter_active,
        "completion_filter_error": completion_filter_error,
        "duplicate_pockets": top_pockets,
        "payload_groups": payload_groups["top_groups"],
        "payload_groups_no_growth": payload_groups["top_no_growth_groups"],
        "rehome_impact_groups": payload_groups["top_impact_groups"],
        "rehome_impact_summary": payload_groups["impact_summary"],
        "payload_group_count": payload_groups["confirmed_groups"],
        "rehome": payload_groups["rehome_opportunities"],
        "recovery_no_growth": recovery_no_growth,
        "orphans": orphan_gc,
        "db_health": db_health,
    }
    report["actions"] = _build_actions(report)
    return report


def _render_markdown(report: dict, db_path: str) -> str:
    lines: list[str] = []
    lines.append("# Hashall Operations Status Report")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Database: `{db_path}`")
    lines.append(f"- Media root policy anchor: `{report['media_root']}`")
    lines.append(f"- Recovery prefix: `{report['recovery_prefix']}`")
    lines.append("")

    totals = report["totals"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Active files: **{totals['active_files']:,}**")
    lines.append(f"- Catalog bytes: **{_fmt_bytes(totals['active_bytes'])}**")
    lines.append(f"- Duplicate hash groups: **{totals['duplicate_sha256_groups']:,}**")
    lines.append(
        "- Link actions possible (nonzero/zero-byte): "
        f"**{totals['link_actions_nonzero']:,} / {totals['link_actions_zero_bytes']:,}** "
        f"(total {totals['link_actions_possible']:,})"
    )
    lines.append(f"- Estimated bytes saveable: **{_fmt_bytes(totals['bytes_saveable'])}**")
    lines.append(
        f"- Payloads complete/incomplete: **{totals['payload_complete']:,} / {totals['payload_incomplete']:,}**"
    )
    lines.append(
        "- Dirty payloads (actionable/noncomplete/orphan): "
        f"**{totals['dirty_actionable']:,} / {totals['dirty_noncomplete']:,} / {totals['dirty_orphan']:,}**"
    )
    lines.append(
        "- Incomplete payload rows (needs-upgrade/zero-files): "
        f"**{totals['payload_needs_upgrade']:,} / {totals['payload_incomplete_zero_files']:,}**"
    )
    if report.get("completion_filter_active"):
        lines.append("- qB completion filter: **active** (refs below 100% are informational)")
    elif report.get("completion_filter_error"):
        lines.append(f"- qB completion filter: **disabled** ({report['completion_filter_error']})")
    lines.append("")

    lines.append("## Roots")
    lines.append("")
    lines.append("| Root | Device | Active files | Hardlinked files | Dup groups | Actions (nonzero/zero) | Saveable | Payload complete/incomplete | Needs upgrade | Dirty actionable/noncomplete/orphan | Scope note |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in report["roots"]:
        lines.append(
            "| {root} | {device} | {files:,} | {hardlinked:,} ({ratio:.1%}) | {dups:,} | {actions_nonzero:,}/{actions_zero:,} | {saveable} | {pc:,}/{pi:,} | {needs_upgrade:,} | {da:,}/{dn:,}/{do:,} | {scope_note} |".format(
                root=row["root"],
                device=row["device_id"],
                files=int(row["active_files"]),
                hardlinked=int(row["hardlinked_files"]),
                ratio=float(row["hardlink_ratio"]),
                dups=int(row["duplicate_sha256_groups"]),
                actions_nonzero=int(row.get("link_actions_nonzero", 0)),
                actions_zero=int(row.get("link_actions_zero_bytes", 0)),
                saveable=_fmt_bytes(int(row["bytes_saveable"])),
                pc=int(row.get("payload_complete", 0)),
                pi=int(row.get("payload_incomplete", 0)),
                needs_upgrade=int(row.get("payload_needs_upgrade", 0)),
                da=int(row.get("dirty_actionable", 0)),
                dn=int(row.get("dirty_noncomplete", 0)),
                do=int(row.get("dirty_orphan", 0)),
                scope_note=(
                    f"alias of `{row['scope_alias_of']}`"
                    if row.get("scope_alias_of")
                    else "-"
                ),
            )
        )
    lines.append("")

    lines.append("## Duplicate Pocket Heat Map")
    lines.append("")
    lines.append("| Pocket | Groups | Actions | Saveable | Sample |")
    lines.append("|---|---:|---:|---:|---|")
    for pocket in report["duplicate_pockets"]:
        lines.append(
            "| {pocket} | {groups:,} | {actions:,} | {saveable} | `{sample}` |".format(
                pocket=pocket["pocket"],
                groups=int(pocket["groups"]),
                actions=int(pocket["actions"]),
                saveable=_fmt_bytes(int(pocket["bytes_saveable"])),
                sample=pocket["sample_path"],
            )
        )
    if not report["duplicate_pockets"]:
        lines.append("| _none_ | 0 | 0 | 0 B | - |")
    elif int(report["totals"]["link_actions_nonzero"]) == 0 and int(report["totals"]["link_actions_zero_bytes"]) > 0:
        lines.append("")
        lines.append("_Note: current duplicate pockets are zero-byte opportunities (metadata cleanup, not space reclaim)._")
    lines.append("")

    lines.append("## Payload Groups & Rehome Signals")
    lines.append("")
    lines.append(f"- Confirmed payload groups (copies >= 2): **{report['payload_group_count']:,}**")
    lines.append(
        f"- Rehome opportunities stash -> pool: **{report['rehome']['stash_to_pool_groups']:,}** groups "
        f"(~{_fmt_bytes(report['rehome']['stash_to_pool_estimated_bytes'])})"
    )
    lines.append(
        f"- Rehome opportunities pool -> stash: **{report['rehome']['pool_to_stash_groups']:,}** groups "
        f"(~{_fmt_bytes(report['rehome']['pool_to_stash_estimated_bytes'])})"
    )
    lines.append(
        "- No-pool-growth stash demote candidates (already on pool): "
        f"**{report['rehome']['stash_to_pool_no_growth_groups']:,}** groups "
        f"(~{_fmt_bytes(report['rehome']['stash_to_pool_no_growth_estimated_bytes'])})"
    )
    lines.append("")
    lines.append("| Payload hash | Copies | Roots | Has media copy | Bytes | Sample paths |")
    lines.append("|---|---:|---|---|---:|---|")
    for group in report["payload_groups"]:
        lines.append(
            "| `{h}` | {copies:,} | {roots} | {media} | {bytes} | {samples} |".format(
                h=str(group["payload_hash"])[:16],
                copies=int(group["copies"]),
                roots=", ".join(group["roots"]),
                media="yes" if group["has_media_consumer_copy"] else "no",
                bytes=_fmt_bytes(int(group["total_bytes"])),
                samples="; ".join(f"`{p}`" for p in group["sample_paths"]),
            )
        )
    if not report["payload_groups"]:
        lines.append("| _none_ | 0 | - | - | 0 B | - |")
    lines.append("")

    lines.append("## No-Pool-Growth Shortlist")
    lines.append("")
    lines.append("| Payload hash | Bytes | Copies | Sample paths |")
    lines.append("|---|---:|---:|---|")
    for group in report["payload_groups_no_growth"]:
        lines.append(
            "| `{h}` | {bytes} | {copies:,} | {samples} |".format(
                h=str(group["payload_hash"])[:16],
                bytes=_fmt_bytes(int(group["total_bytes"])),
                copies=int(group["copies"]),
                samples="; ".join(f"`{p}`" for p in group["sample_paths"]),
            )
        )
    if not report["payload_groups_no_growth"]:
        lines.append("| _none_ | 0 B | 0 | - |")
    lines.append("")

    lines.append("## Rehome Move Impact (Stash -> Pool)")
    lines.append("")
    impact_summary = report.get("rehome_impact_summary", {})
    lines.append(
        "- Recommendation counts "
        f"(MOVE/PARTIAL_REVIEW/SKIP): **{int(impact_summary.get('move', 0)):,} / "
        f"{int(impact_summary.get('partial_review', 0)):,} / "
        f"{int(impact_summary.get('skip', 0)):,}**"
    )
    lines.append("")
    lines.append(
        "| Payload hash | Movable files | Movable bytes | Blocked files | Blocked bytes | Move impact (files/bytes) | Recommendation | Top block reasons |"
    )
    lines.append("|---|---:|---:|---:|---:|---|---|---|")
    for group in report.get("rehome_impact_groups", []):
        reasons = ", ".join(
            f"{k}:{v}" for k, v in sorted(group.get("block_reason_counts", {}).items())
        ) or "-"
        lines.append(
            "| `{h}` | {mf:,}/{tf:,} | {mb}/{tb} | {bf:,} | {bb} | {pf:.0%}/{pb:.0%} | {rec} | {reasons} |".format(
                h=str(group["payload_hash"])[:16],
                mf=int(group.get("movable_files", 0)),
                tf=int(group.get("stash_total_files", 0)),
                mb=_fmt_bytes(int(group.get("movable_bytes", 0))),
                tb=_fmt_bytes(int(group.get("stash_total_bytes", 0))),
                bf=int(group.get("blocked_files", 0)),
                bb=_fmt_bytes(int(group.get("blocked_bytes", 0))),
                pf=float(group.get("movable_pct_files", 0.0)),
                pb=float(group.get("movable_pct_bytes", 0.0)),
                rec=str(group.get("recommendation", "SKIP")),
                reasons=reasons,
            )
        )
    if not report.get("rehome_impact_groups"):
        lines.append("| _none_ | 0/0 | 0 B/0 B | 0 | 0 B | 0%/0% | SKIP | - |")
    lines.append("")

    lines.append("## Recovery Dataset (Non-qB)")
    lines.append("")
    rec = report["recovery_no_growth"]
    if rec.get("available"):
        lines.append(
            "- Recovery files (total/hashed): "
            f"**{rec['total_files']:,} / {rec['hashed_files']:,}** "
            f"(bytes {_fmt_bytes(rec['total_bytes'])} / {_fmt_bytes(rec['hashed_bytes'])})"
        )
        lines.append(
            "- Already on pool (no-growth candidates): "
            f"**{rec['matched_files']:,}** (~{_fmt_bytes(rec['matched_bytes'])})"
        )
        lines.append(
            "- Not on pool yet: "
            f"**{rec['unmatched_files']:,}** (~{_fmt_bytes(rec['unmatched_bytes'])})"
        )
        if rec.get("samples"):
            lines.append("- Matched samples:")
            for sample in rec["samples"][:5]:
                lines.append(f"  - `{sample['path']}` ({_fmt_bytes(sample['bytes'])})")
    else:
        lines.append(f"- Not available: `{rec.get('reason')}`")
    lines.append("")

    lines.append("## Orphan GC & DB Health")
    lines.append("")
    lines.append(f"- Orphan GC tracked: **{report['orphans']['tracked']:,}**")
    lines.append(f"- Orphan GC aged-ready: **{report['orphans']['aged']:,}**")
    if report["orphans"]["samples"]:
        lines.append(f"- Orphan samples: {', '.join(f'`{s}`' for s in report['orphans']['samples'])}")
    lines.append(f"- DB quick_check: **{report['db_health']['quick_check']}**")
    lines.append("")

    lines.append("## Suggested Next Steps")
    lines.append("")
    if report["actions"]:
        for action in report["actions"]:
            lines.append(f"- `{action['priority']}` {action['reason']}: `{action['command']}`")
    else:
        lines.append("- No immediate cleanup actions detected.")
    lines.append("")
    return "\n".join(lines)


def _render_phone(report: dict, *, width: int, top: int) -> str:
    totals = report["totals"]
    db_ok = str(report.get("db_health", {}).get("quick_check", "")).lower() == "ok"
    dirty_actionable = int(totals.get("dirty_actionable", 0))
    dirty_noncomplete = int(totals.get("dirty_noncomplete", 0))
    dirty_orphan = int(totals.get("dirty_orphan", 0))
    payload_incomplete = int(totals.get("payload_incomplete", 0))
    payload_needs_upgrade = int(totals.get("payload_needs_upgrade", 0))
    link_nonzero = int(totals.get("link_actions_nonzero", 0))
    link_zero = int(totals.get("link_actions_zero_bytes", 0))
    saveable_bytes = int(totals.get("bytes_saveable", 0))
    rehome_stash_to_pool = int(report.get("rehome", {}).get("stash_to_pool_groups", 0))
    rehome_stash_to_pool_bytes = int(report.get("rehome", {}).get("stash_to_pool_estimated_bytes", 0))
    rehome_no_growth = int(report.get("rehome", {}).get("stash_to_pool_no_growth_groups", 0))
    rehome_no_growth_bytes = int(report.get("rehome", {}).get("stash_to_pool_no_growth_estimated_bytes", 0))
    rehome_impact = report.get("rehome_impact_summary", {})
    rehome_move = int(rehome_impact.get("move", 0))
    rehome_partial = int(rehome_impact.get("partial_review", 0))
    rehome_skip = int(rehome_impact.get("skip", 0))
    recovery_no_growth = report.get("recovery_no_growth", {})

    if not db_ok:
        posture = "critical"
    elif dirty_actionable > 0 or link_nonzero > 0:
        posture = "action_required"
    elif payload_needs_upgrade > 0:
        posture = "watch"
    else:
        posture = "stable"

    lines: list[str] = []
    lines.append(
        "snapshot: "
        f"posture={posture} "
        f"db={'ok' if db_ok else report.get('db_health', {}).get('quick_check', 'unknown')}"
    )
    lines.append(
        "inventory: "
        f"files={totals['active_files']:,} "
        f"dup_groups={totals['duplicate_sha256_groups']:,} "
        f"payload_complete={totals['payload_complete']:,}"
    )
    lines.append(
        "pressure: "
        f"dirty_actionable={dirty_actionable:,} "
        f"dirty_noncomplete={dirty_noncomplete:,} "
        f"dirty_orphan={dirty_orphan:,} "
        f"needs_upgrade={payload_needs_upgrade:,}"
    )
    lines.append(
        "cleanup: "
        f"link_nonzero={link_nonzero:,} "
        f"maintenance_zero={link_zero:,} "
        f"reclaim_now={_fmt_bytes(saveable_bytes)}"
    )
    lines.append(
        "rehome: "
        f"stash_to_pool={rehome_stash_to_pool:,} "
        f"({ _fmt_bytes(rehome_stash_to_pool_bytes) }) "
        f"no_growth={rehome_no_growth:,} ({_fmt_bytes(rehome_no_growth_bytes)})"
    )
    lines.append(
        "rehome_impact: "
        f"move={rehome_move:,} partial={rehome_partial:,} skip={rehome_skip:,}"
    )
    if recovery_no_growth.get("available"):
        lines.append(
            "recovery: "
            f"matched={int(recovery_no_growth.get('matched_files', 0)):,} "
            f"({_fmt_bytes(int(recovery_no_growth.get('matched_bytes', 0)))}) "
            f"unmatched={int(recovery_no_growth.get('unmatched_files', 0)):,}"
        )
    if report.get("completion_filter_active"):
        lines.append("qbit_filter: active (refs <100% excluded from actionable counts)")
    elif report.get("completion_filter_error"):
        lines.append(f"qbit_filter: disabled ({report['completion_filter_error']})")

    pockets = report.get("duplicate_pockets", [])
    if pockets:
        top_actions = max(int(p.get("actions", 0)) for p in pockets)
        top_saveable = max(int(p.get("bytes_saveable", 0)) for p in pockets)
        lines.append(
            "heat: "
            f"pockets={len(pockets):,} "
            f"top_actions={top_actions:,} "
            f"top_saveable={_fmt_bytes(top_saveable)}"
        )

    lines.append("do_now:")
    step_num = 1
    if dirty_actionable > 0:
        lines.append(
            f"{step_num}. converge payload state ({dirty_actionable:,} actionable): "
            "make payload-auto ROOTS='/pool/data,/stash/media,/data/media'"
        )
        step_num += 1
    if link_nonzero > 0:
        lines.append(
            f"{step_num}. reclaim duplicate file bytes now ({_fmt_bytes(saveable_bytes)}): "
            "make hardlink-auto ROOTS='/pool/data,/stash/media,/data/media' HARDLINK_AUTO_EXECUTE=1"
        )
        step_num += 1
    elif link_zero > 0 and link_nonzero == 0:
        lines.append(
            f"{step_num}. zero-byte metadata cleanup pending ({link_zero:,}); defer to maintenance window"
        )
        step_num += 1
    if payload_needs_upgrade > 0:
        lines.append(
            f"{step_num}. upgrade incomplete payload rows with files ({payload_needs_upgrade:,}): "
            "make payload-sync PAYLOAD_UPGRADE_MISSING=1 PAYLOAD_PARALLEL=1 "
            "PAYLOAD_PATH_PREFIXES='/pool/data /stash/media /data/media'"
        )
        step_num += 1
    if payload_incomplete > 0 and payload_needs_upgrade == 0:
        lines.append(
            f"{step_num}. incomplete rows are currently zero-file records ({payload_incomplete:,}); "
            "make payload-workflow PW_PATHS='/pool/data /stash/media /data/media'"
        )
        step_num += 1
    if dirty_noncomplete > 0:
        lines.append(
            f"{step_num}. refs below 100% are ignored ({dirty_noncomplete:,}); resume/finish those torrents or ignore"
        )
        step_num += 1
    if rehome_stash_to_pool > 0:
        lines.append(
            f"{step_num}. review rehome queue (stash->pool={rehome_stash_to_pool:,}): "
            "make rehome-checklist"
        )
        step_num += 1
    if rehome_no_growth > 0:
        lines.append(
            f"{step_num}. prioritize no-pool-growth demotes ({rehome_no_growth:,} groups): make rehome-checklist"
        )
        step_num += 1
    if step_num == 1:
        lines.append("1. no immediate actions required")

    return "\n".join(_truncate_line(line, width=max(20, width)) for line in lines)


def _truncate_line(line: str, width: int) -> str:
    if width <= 0 or len(line) <= width:
        return line
    if width <= 3:
        return "." * width
    return line[: width - 3] + "..."


def _resolve_phone_width(requested_width: int) -> int:
    if requested_width > 0:
        return max(20, requested_width)
    detected = shutil.get_terminal_size(fallback=(100, 24)).columns
    return max(20, int(detected))


def write_report_files(report: dict, *, output_dir: str, db_path: str) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"hashall-status-{stamp}.json"
    md_path = out_dir / f"hashall-status-{stamp}.md"

    json_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(report, db_path=db_path) + "\n", encoding="utf-8")
    return md_path, json_path


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate hashall operational status report")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--roots", help="Comma-separated roots (auto-discover if omitted)")
    parser.add_argument("--output-dir", default="out/reports")
    parser.add_argument("--media-root", default="/data/media")
    parser.add_argument("--recovery-prefix", default="/data/media/torrents/seeding/recovery_20260211")
    parser.add_argument("--pocket-depth", type=int, default=2)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--cache-ttl-seconds", type=int, default=300)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--print-phone", action="store_true", help="Print compact phone-friendly summary")
    parser.add_argument("--phone-width", type=int, default=0, help="0 = auto-detect terminal width")
    parser.add_argument("--phone-top", type=int, default=5)
    parser.add_argument("--print-json", action="store_true", help="Print JSON summary to stdout")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db)
    cache_key = _cache_key(
        db_path=db_path,
        roots_arg=args.roots,
        media_root=args.media_root,
        pocket_depth=max(1, args.pocket_depth),
        top_n=max(1, args.top),
        recovery_prefix=args.recovery_prefix,
    )
    cache_path = _cache_file(args.output_dir)

    report = None
    cache_used = False
    if not args.refresh_cache:
        report = _load_cached_report(
            cache_path=cache_path,
            expected_key=cache_key,
            ttl_seconds=max(0, args.cache_ttl_seconds),
        )
        cache_used = report is not None

    if report is None:
        with _Spinner("Generating status report", enabled=sys.stderr.isatty()):
            conn = connect_db(db_path, read_only=True, apply_migrations=False)
            try:
                report = build_status_report(
                    conn,
                    roots_arg=args.roots,
                    media_root=args.media_root,
                    pocket_depth=max(1, args.pocket_depth),
                    top_n=max(1, args.top),
                    recovery_prefix=args.recovery_prefix,
                )
            finally:
                conn.close()
        _write_cached_report(cache_path=cache_path, cache_key=cache_key, report=report)

    md_path, json_path = write_report_files(report, output_dir=args.output_dir, db_path=args.db)

    print("Hashall status report generated")
    print(f"  DB: {args.db}")
    print(f"  Roots: {', '.join(item['root'] for item in report['roots'])}")
    print(
        "  Cache: "
        + (
            f"hit (ttl={max(0, args.cache_ttl_seconds)}s)"
            if cache_used
            else f"miss (ttl={max(0, args.cache_ttl_seconds)}s)"
        )
    )
    print(f"  Markdown: {md_path}")
    print(f"  JSON: {json_path}")
    print(
        "  Summary: "
        f"saveable={_fmt_bytes(report['totals']['bytes_saveable'])} "
        f"actionable_dirty={report['totals']['dirty_actionable']} "
        f"ignored_noncomplete={report['totals']['dirty_noncomplete']} "
        f"rehome(stash->pool)={report['rehome']['stash_to_pool_groups']} "
        f"rehome_no_growth(stash->pool)={report['rehome']['stash_to_pool_no_growth_groups']} "
        f"rehome(pool->stash)={report['rehome']['pool_to_stash_groups']}"
    )
    if args.print_phone:
        phone_width = _resolve_phone_width(args.phone_width)
        print()
        print(_render_phone(report, width=phone_width, top=max(1, args.phone_top)))
    if args.print_json:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
