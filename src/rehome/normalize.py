"""Path normalization helpers for pool-side payload roots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from hashall.pathing import canonicalize_path, is_under, remap_to_mount_alias, to_relpath


@dataclass(frozen=True)
class NormalizationSkip:
    payload_id: int
    payload_hash: str
    source_path: str
    reason: str


def _canonical(path: str | Path) -> Path:
    return canonicalize_path(Path(path))


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _resolve_rel(
    source_path: Path,
    base_root: Optional[Path],
) -> Optional[Path]:
    if base_root is None:
        return None
    rel = to_relpath(source_path, base_root)
    if rel is not None:
        return rel
    remapped = remap_to_mount_alias(source_path, base_root)
    if remapped is None:
        return None
    return to_relpath(remapped, base_root)


def _fetch_pool_torrents(
    conn: sqlite3.Connection,
    payload_hash: str,
    pool_device: int,
) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ti.torrent_hash, ti.save_path, ti.root_name
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE p.payload_hash = ? AND p.device_id = ?
        ORDER BY ti.torrent_hash
        """,
        (payload_hash, pool_device),
    ).fetchall()


def _preferred_expected_target(
    conn: sqlite3.Connection,
    payload_hash: str,
    pool_root: Path,
    stash_root: Optional[Path],
    pool_torrents: Sequence[sqlite3.Row],
) -> Tuple[Optional[Path], str]:
    # Prefer original source->target relative path from successful demote runs.
    if _table_exists(conn, "rehome_runs"):
        run_rows = conn.execute(
            """
            SELECT source_path
            FROM rehome_runs
            WHERE status = 'success'
              AND direction = 'demote'
              AND payload_hash = ?
              AND source_path IS NOT NULL
            ORDER BY id DESC
            LIMIT 25
            """,
            (payload_hash,),
        ).fetchall()
        for run_row in run_rows:
            source_raw = str(run_row[0] or "").strip()
            if not source_raw:
                continue
            source_path = _canonical(source_raw)
            rel = _resolve_rel(source_path, stash_root)
            if rel is None or str(rel) == ".":
                continue
            candidate = _canonical(pool_root / rel)
            if is_under(candidate, pool_root):
                return candidate, "rehome_runs"

    # Fallback: infer from torrent save_path + root_name.
    for row in pool_torrents:
        save_path_raw = str(row["save_path"] or "").strip()
        root_name = str(row["root_name"] or "").strip()
        if not save_path_raw or not root_name:
            continue
        save_path = _canonical(save_path_raw)
        candidate = _canonical(save_path / root_name)
        if is_under(candidate, pool_root):
            return candidate, "torrent_save_path"

    return None, "no_expected_target"


def build_pool_path_normalization_batch(
    *,
    catalog_path: Path,
    pool_device: int,
    pool_seeding_root: str,
    stash_seeding_root: Optional[str] = None,
    payload_hashes: Optional[Set[str]] = None,
    limit: int = 0,
    flat_only: bool = True,
) -> Dict:
    """
    Build batch plans to normalize pool payload root paths.

    The generated plans are REUSE (when target already exists) or MOVE
    (when target is absent). They are safe to execute with existing
    `rehome apply` workflow.
    """
    conn = sqlite3.connect(catalog_path)
    conn.row_factory = sqlite3.Row
    pool_root = _canonical(pool_seeding_root)
    stash_root = _canonical(stash_seeding_root) if stash_seeding_root else None

    plans: List[Dict] = []
    skipped: List[NormalizationSkip] = []
    payload_group_cache: Dict[str, List[Dict]] = {}

    try:
        payload_rows = conn.execute(
            """
            SELECT payload_id, payload_hash, root_path, file_count, total_bytes
            FROM payloads
            WHERE device_id = ? AND status = 'complete'
            ORDER BY payload_id
            """,
            (pool_device,),
        ).fetchall()

        for row in payload_rows:
            payload_id = int(row["payload_id"])
            payload_hash = str(row["payload_hash"] or "").strip()
            if not payload_hash:
                continue
            if payload_hashes and payload_hash not in payload_hashes:
                continue

            source_path = _canonical(str(row["root_path"]))
            if not is_under(source_path, pool_root):
                continue
            if flat_only and source_path.parent != pool_root:
                continue

            pool_torrents = _fetch_pool_torrents(conn, payload_hash, pool_device)
            if not pool_torrents:
                skipped.append(
                    NormalizationSkip(
                        payload_id=payload_id,
                        payload_hash=payload_hash,
                        source_path=str(source_path),
                        reason="no_pool_torrents",
                    )
                )
                continue

            target_path, source_hint = _preferred_expected_target(
                conn,
                payload_hash,
                pool_root,
                stash_root,
                pool_torrents,
            )
            if target_path is None:
                skipped.append(
                    NormalizationSkip(
                        payload_id=payload_id,
                        payload_hash=payload_hash,
                        source_path=str(source_path),
                        reason="no_expected_target",
                    )
                )
                continue

            if source_path == target_path:
                continue
            if not is_under(target_path, pool_root):
                skipped.append(
                    NormalizationSkip(
                        payload_id=payload_id,
                        payload_hash=payload_hash,
                        source_path=str(source_path),
                        reason="expected_target_out_of_scope",
                    )
                )
                continue

            affected_torrents: List[str] = []
            view_targets: List[Dict[str, str]] = []
            for torrent_row in pool_torrents:
                torrent_hash = str(torrent_row["torrent_hash"] or "").strip()
                save_path_raw = str(torrent_row["save_path"] or "").strip()
                root_name = str(torrent_row["root_name"] or "").strip()
                if not torrent_hash or not save_path_raw:
                    continue
                save_path = _canonical(save_path_raw)
                if not is_under(save_path, pool_root):
                    continue
                affected_torrents.append(torrent_hash)
                if root_name:
                    view_targets.append(
                        {
                            "torrent_hash": torrent_hash,
                            "source_save_path": str(save_path),
                            "target_save_path": str(save_path),
                            "root_name": root_name,
                        }
                    )

            if not affected_torrents:
                skipped.append(
                    NormalizationSkip(
                        payload_id=payload_id,
                        payload_hash=payload_hash,
                        source_path=str(source_path),
                        reason="no_in_scope_torrents",
                    )
                )
                continue

            if payload_hash not in payload_group_cache:
                payload_group_cache[payload_hash] = [
                    {
                        "payload_id": int(p["payload_id"]),
                        "device_id": int(p["device_id"]) if p["device_id"] is not None else None,
                        "root_path": str(p["root_path"]),
                        "file_count": int(p["file_count"] or 0),
                        "total_bytes": int(p["total_bytes"] or 0),
                        "status": str(p["status"] or ""),
                    }
                    for p in conn.execute(
                        """
                        SELECT payload_id, device_id, root_path, file_count, total_bytes, status
                        FROM payloads
                        WHERE payload_hash = ?
                        ORDER BY payload_id
                        """,
                        (payload_hash,),
                    ).fetchall()
                ]

            decision = "REUSE" if target_path.exists() else "MOVE"
            plan = {
                "version": "1.0",
                "direction": "demote",
                "decision": decision,
                "torrent_hash": affected_torrents[0],
                "payload_id": payload_id,
                "payload_hash": payload_hash,
                "reasons": [
                    f"Normalize pool payload path from {source_path} to {target_path} ({source_hint})"
                ],
                "affected_torrents": affected_torrents,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "source_device_id": int(pool_device),
                "target_device_id": int(pool_device),
                "seeding_roots": [str(pool_root)],
                "library_roots": [],
                "view_targets": view_targets,
                "payload_group": payload_group_cache[payload_hash],
                "file_count": int(row["file_count"] or 0),
                "total_bytes": int(row["total_bytes"] or 0),
                "normalization": {
                    "mode": "pool_path",
                    "source_hint": source_hint,
                    "flat_only": bool(flat_only),
                },
            }
            plans.append(plan)
            if limit > 0 and len(plans) >= limit:
                break
    finally:
        conn.close()

    return {
        "version": "1.0",
        "batch": True,
        "mode": "normalize_pool_paths",
        "generated_at": datetime.now().astimezone().isoformat(),
        "pool_device": int(pool_device),
        "pool_seeding_root": str(pool_root),
        "stash_seeding_root": str(stash_root) if stash_root else None,
        "flat_only": bool(flat_only),
        "plans": plans,
        "skipped": [
            {
                "payload_id": s.payload_id,
                "payload_hash": s.payload_hash,
                "source_path": s.source_path,
                "reason": s.reason,
            }
            for s in skipped
        ],
        "summary": {
            "candidates": len(plans),
            "skipped": len(skipped),
            "decision_reuse": sum(1 for p in plans if p.get("decision") == "REUSE"),
            "decision_move": sum(1 for p in plans if p.get("decision") == "MOVE"),
        },
    }

