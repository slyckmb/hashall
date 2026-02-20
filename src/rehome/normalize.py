"""Path normalization helpers for pool-side payload roots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote

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


def _table_has_columns(conn: sqlite3.Connection, table_name: str, required: Set[str]) -> bool:
    if not _table_exists(conn, table_name):
        return False
    cols = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if len(row) > 1
    }
    return required.issubset(cols)


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
        SELECT ti.torrent_hash, ti.save_path, ti.root_name, ti.category, ti.tags
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
    source_path: Path,
    expected_file_count: int,
    expected_total_bytes: int,
) -> Tuple[Optional[Path], str]:
    source_name = source_path.name

    def _single_file_matches(path: Path) -> bool:
        if not path.exists():
            return False
        if path.is_file():
            try:
                return int(path.stat().st_size) == int(expected_total_bytes)
            except OSError:
                return False
        if not path.is_dir():
            return False
        single_size: Optional[int] = None
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            if single_size is not None:
                return False
            try:
                single_size = int(item.stat().st_size)
            except OSError:
                return False
        if single_size is None:
            return False
        return single_size == int(expected_total_bytes)

    # Prefer original source->target relative path from successful demote runs.
    run_fallback: Optional[Path] = None
    if _table_has_columns(conn, "rehome_runs", {"direction", "payload_hash", "status", "source_path"}):
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
            run_source_path = _canonical(source_raw)
            rel = _resolve_rel(run_source_path, stash_root)
            if rel is None or str(rel) == ".":
                continue
            candidate = _canonical(pool_root / rel)
            if not is_under(candidate, pool_root):
                continue
            if expected_file_count != 1:
                return candidate, "rehome_runs"
            if _single_file_matches(candidate):
                return candidate, "rehome_runs"
            if source_name:
                alt = _canonical(candidate.parent / source_name)
                if is_under(alt, pool_root) and _single_file_matches(alt):
                    return alt, "rehome_runs_single_file_name"
            if run_fallback is None:
                run_fallback = candidate
    if run_fallback is not None:
        return run_fallback, "rehome_runs"

    # Fallback: infer from torrent save_path + root_name.
    save_fallback: Optional[Path] = None
    for row in pool_torrents:
        save_path_raw = str(row["save_path"] or "").strip()
        root_name = str(row["root_name"] or "").strip()
        if not save_path_raw or not root_name:
            continue
        save_path = _canonical(save_path_raw)
        candidates: List[Tuple[Path, str]] = [(_canonical(save_path / root_name), "torrent_save_path")]
        if expected_file_count == 1 and source_name:
            single_file_candidate = _canonical(save_path / source_name)
            if single_file_candidate != candidates[0][0]:
                candidates.append((single_file_candidate, "torrent_save_path_single_file_name"))
        for candidate, hint in candidates:
            if not is_under(candidate, pool_root):
                continue
            if expected_file_count != 1:
                return candidate, "torrent_save_path"
            if _single_file_matches(candidate):
                return candidate, hint
            if save_fallback is None:
                save_fallback = candidate
    if save_fallback is not None:
        return save_fallback, "torrent_save_path"

    return None, "no_expected_target"


def _split_tags(raw_tags: str) -> List[str]:
    if not raw_tags:
        return []
    return [tag.strip() for tag in str(raw_tags).split(",") if tag and tag.strip()]


def _sanitize_path_component(value: str) -> str:
    text = str(value or "").strip().replace("/", "_")
    return text or "_uncategorized"


def _select_tracker_group(pool_torrents: Sequence[sqlite3.Row], pool_root: Path) -> Optional[str]:
    # Prefer existing cross-seed folder already seen in torrent save_path.
    for row in pool_torrents:
        save_path_raw = str(row["save_path"] or "").strip()
        if not save_path_raw:
            continue
        save_path = _canonical(save_path_raw)
        rel = to_relpath(save_path, pool_root)
        if rel is None or len(rel.parts) < 2:
            continue
        if rel.parts[0] == "cross-seed":
            return rel.parts[1]

    # Then prefer tags that look like tracker labels.
    ignored = {
        "cross-seed",
        "cross_seed",
        "crossseed",
        "rehome",
        "rehome_verify_pending",
        "rehome_verify_ok",
        "rehome_verify_failed",
    }
    for row in pool_torrents:
        for tag in _split_tags(str(row["tags"] or "")):
            lowered = tag.lower()
            if lowered in ignored:
                continue
            if "(" in tag or "." in tag or "-" in tag or "_" in tag:
                return tag
    return None


def _fallback_expected_target(
    *,
    source_path: Path,
    pool_root: Path,
    pool_torrents: Sequence[sqlite3.Row],
) -> Tuple[Path, str, str, bool]:
    categories = [
        str(row["category"] or "").strip()
        for row in pool_torrents
        if str(row["category"] or "").strip()
    ]
    category = categories[0] if categories else ""
    category_lower = category.lower()
    is_cross_seed = category_lower in {"cross-seed", "cross_seed", "crossseed"}
    if not is_cross_seed:
        is_cross_seed = any(
            "cross-seed" in tag.lower()
            for row in pool_torrents
            for tag in _split_tags(str(row["tags"] or ""))
        )

    leaf = source_path.name
    if is_cross_seed:
        tracker_group = _select_tracker_group(pool_torrents, pool_root)
        if tracker_group:
            return (
                _canonical(pool_root / "cross-seed" / _sanitize_path_component(tracker_group) / leaf),
                "qb_fallback_cross_seed",
                "medium",
                False,
            )
        return (
            _canonical(pool_root / "cross-seed" / "_unknown_tracker" / leaf),
            "qb_fallback_cross_seed_unknown_tracker",
            "low",
            True,
        )

    if category:
        return (
            _canonical(pool_root / _sanitize_path_component(category) / leaf),
            "qb_fallback_category",
            "medium",
            False,
        )

    return (
        _canonical(pool_root / "_uncategorized" / leaf),
        "qb_fallback_uncategorized",
        "low",
        True,
    )


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
    catalog_uri = (
        f"file:{quote(str(Path(catalog_path).expanduser().resolve()))}?mode=ro&immutable=1"
    )
    conn = sqlite3.connect(catalog_uri, uri=True)
    conn.row_factory = sqlite3.Row
    pool_root = _canonical(pool_seeding_root)
    stash_root = _canonical(stash_seeding_root) if stash_seeding_root else None

    plans: List[Dict] = []
    skipped: List[NormalizationSkip] = []
    payload_group_cache: Dict[str, List[Dict]] = {}

    def _source_row_score(row: sqlite3.Row) -> int:
        score = 0
        source = _canonical(str(row["root_path"]))
        if not is_under(source, pool_root):
            return -10_000
        score += 100
        if not flat_only or source.parent == pool_root:
            score += 30
        file_count = int(row["file_count"] or 0)
        total_bytes = int(row["total_bytes"] or 0)
        try:
            if source.exists():
                score += 40
                if file_count == 1 and source.is_file():
                    score += 70
                    if int(source.stat().st_size) == total_bytes:
                        score += 30
                elif file_count > 1 and source.is_dir():
                    score += 40
        except OSError:
            pass
        score += max(0, 10_000 - int(row["payload_id"]))
        return score

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

        payload_rows_by_hash: Dict[str, List[sqlite3.Row]] = {}
        payload_hash_order: List[str] = []
        for row in payload_rows:
            payload_hash = str(row["payload_hash"] or "").strip()
            if not payload_hash:
                continue
            if payload_hashes and payload_hash not in payload_hashes:
                continue
            if payload_hash not in payload_rows_by_hash:
                payload_rows_by_hash[payload_hash] = []
                payload_hash_order.append(payload_hash)
            payload_rows_by_hash[payload_hash].append(row)

        for payload_hash in payload_hash_order:
            rows_for_hash = payload_rows_by_hash[payload_hash]
            in_scope_rows: List[sqlite3.Row] = []
            for row in rows_for_hash:
                source = _canonical(str(row["root_path"]))
                if not is_under(source, pool_root):
                    continue
                if flat_only and source.parent != pool_root:
                    continue
                in_scope_rows.append(row)
            if not in_scope_rows:
                continue

            row = max(in_scope_rows, key=_source_row_score)
            payload_id = int(row["payload_id"])

            source_path = _canonical(str(row["root_path"]))
            file_count = int(row["file_count"] or 0)
            total_bytes = int(row["total_bytes"] or 0)

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
                source_path,
                file_count,
                total_bytes,
            )
            confidence = "high" if source_hint.startswith("rehome_runs") else "medium"
            review_required = False
            fallback_used = False
            if target_path is None:
                target_path, source_hint, confidence, review_required = _fallback_expected_target(
                    source_path=source_path,
                    pool_root=pool_root,
                    pool_torrents=pool_torrents,
                )
                fallback_used = True
            elif target_path == source_path and source_hint.startswith("torrent_save_path"):
                # qB save_path/root_name can mirror the current flat payload root.
                # In that case, apply category/tag fallback to produce a normalized layout.
                fb_target, fb_hint, fb_confidence, fb_review = _fallback_expected_target(
                    source_path=source_path,
                    pool_root=pool_root,
                    pool_torrents=pool_torrents,
                )
                if fb_target != source_path:
                    target_path = fb_target
                    source_hint = fb_hint
                    confidence = fb_confidence
                    review_required = fb_review
                    fallback_used = True

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

            if file_count == 1 and target_path.exists():
                if target_path.is_file():
                    try:
                        if int(target_path.stat().st_size) != total_bytes:
                            skipped.append(
                                NormalizationSkip(
                                    payload_id=payload_id,
                                    payload_hash=payload_hash,
                                    source_path=str(source_path),
                                    reason="single_file_target_size_mismatch",
                                )
                            )
                            continue
                    except OSError:
                        skipped.append(
                            NormalizationSkip(
                                payload_id=payload_id,
                                payload_hash=payload_hash,
                                source_path=str(source_path),
                                reason="single_file_target_unreadable",
                            )
                        )
                        continue
                elif target_path.is_dir():
                    candidate = _canonical(target_path.parent / source_path.name)
                    if candidate.exists() and candidate.is_file():
                        try:
                            if int(candidate.stat().st_size) == total_bytes:
                                target_path = candidate
                                source_hint = "torrent_save_path_single_file_name"
                            else:
                                skipped.append(
                                    NormalizationSkip(
                                        payload_id=payload_id,
                                        payload_hash=payload_hash,
                                        source_path=str(source_path),
                                        reason="single_file_target_size_mismatch",
                                    )
                                )
                                continue
                        except OSError:
                            skipped.append(
                                NormalizationSkip(
                                    payload_id=payload_id,
                                    payload_hash=payload_hash,
                                    source_path=str(source_path),
                                    reason="single_file_target_unreadable",
                                )
                            )
                            continue
                    else:
                        skipped.append(
                            NormalizationSkip(
                                payload_id=payload_id,
                                payload_hash=payload_hash,
                                source_path=str(source_path),
                                reason="single_file_target_dir_conflict",
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
                        WHERE payload_hash = ? AND device_id = ?
                        ORDER BY payload_id
                        """,
                        (payload_hash, int(pool_device)),
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
                "file_count": file_count,
                "total_bytes": total_bytes,
                "normalization": {
                    "mode": "pool_path",
                    "source_hint": source_hint,
                    "confidence": confidence,
                    "fallback_used": bool(fallback_used),
                    "review_required": bool(review_required),
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
            "fallback_used": sum(
                1 for p in plans if bool((p.get("normalization") or {}).get("fallback_used"))
            ),
            "review_required": sum(
                1 for p in plans if bool((p.get("normalization") or {}).get("review_required"))
            ),
        },
    }
