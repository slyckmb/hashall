"""Read-only planning helpers for selected hitchhiker repairs."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .client_drift import (
    ClientDriftPolicy,
    DEFAULT_QB_CACHE_FILE,
    DEFAULT_RT_SHARED_CACHE_FILE,
    default_policy,
    load_qb_cache_rows,
    load_rt_cache_rows,
)
from .hitchhiker import audit_hitchhiker_groups, query_hitchhiker_groups
from .hitchhiker_split import _inspect_split_target, _seeding_roots_for_path
from .rtorrent import DEFAULT_RT_SESSION_DIR, rt_path_aligned
from .utils import find_db_path


def _norm_hash(value: Any) -> str:
    return str(value or "").strip().lower()


def _path_kind(path: str, policy: ClientDriftPolicy) -> str:
    text = str(path or "").rstrip("/")
    if not text:
        return ""
    for root in policy.stash_roots:
        root_text = str(root or "").rstrip("/")
        if root_text and (text == root_text or text.startswith(root_text + "/")):
            return "stash"
    for root in policy.pool_roots:
        root_text = str(root or "").rstrip("/")
        if root_text and (text == root_text or text.startswith(root_text + "/")):
            return "pool"
    return "other"


def _stat_path(path: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": path,
        "exists": False,
        "kind": "",
        "device": None,
        "inode": None,
        "nlink": None,
        "size": None,
    }
    if not path:
        return out
    try:
        st = os.stat(path)
    except OSError:
        return out
    p = Path(path)
    out.update(
        {
            "exists": True,
            "kind": "dir" if p.is_dir() else "file" if p.is_file() else "other",
            "device": st.st_dev,
            "inode": st.st_ino,
            "nlink": st.st_nlink,
            "size": st.st_size,
        }
    )
    return out


def _append_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    source: str,
    path: str,
    policy: ClientDriftPolicy,
) -> None:
    value = str(path or "").strip()
    if not value or value in seen:
        return
    seen.add(value)
    entry = _stat_path(value)
    entry["source"] = source
    entry["placement"] = _path_kind(value, policy)
    candidates.append(entry)


def _target_checks_for_candidate(path: str, torrent_hash: str) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        fs_root, api_root = _seeding_roots_for_path(path)
    except ValueError:
        return []
    src = Path(path)
    slug = torrent_hash[:16]
    target_parent_fs = Path(fs_root) / "_rehome-unique" / slug
    target_parent_api = f"{api_root}/_rehome-unique/{slug}"
    (
        target_content_fs,
        source_exists,
        target_parent_exists,
        target_content_exists,
        target_parent_entries,
        same_device,
        warnings,
        blockers,
    ) = _inspect_split_target(src, target_parent_fs)
    return [
        {
            "target_parent_fs": str(target_parent_fs),
            "target_parent_api": target_parent_api,
            "target_content_fs": target_content_fs,
            "source_exists": source_exists,
            "target_parent_exists": target_parent_exists,
            "target_content_exists": target_content_exists,
            "target_parent_entries": target_parent_entries,
            "same_device": same_device,
            "warnings": warnings,
            "blockers": blockers,
        }
    ]


def _catalog_rows_by_payload(db_path: Path) -> dict[int, dict[str, Any]]:
    rows = query_hitchhiker_groups(db_path=str(db_path))
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        payload_id = int(row["payload_id"])
        item = out.setdefault(
            payload_id,
            {
                "payload_id": payload_id,
                "root_path": row["root_path"],
                "file_count": row["file_count"],
                "total_bytes": row["total_bytes"],
                "hashes": [],
                "save_paths": [],
            },
        )
        item["hashes"].append(_norm_hash(row["torrent_hash"]))
        save_path = str(row.get("save_path") or "")
        if save_path and save_path not in item["save_paths"]:
            item["save_paths"].append(save_path)
    return out


def _same_payload_hash_families(db_path: Path, payload_ids: Iterable[int]) -> dict[int, list[dict[str, Any]]]:
    selected_ids = sorted({int(value) for value in payload_ids})
    if not selected_ids:
        return {}
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        payload_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(payloads)").fetchall()
        }
        if "payload_hash" not in payload_columns:
            return {payload_id: [] for payload_id in selected_ids}
        placeholders = ",".join("?" for _ in selected_ids)
        payload_hash_rows = conn.execute(
            f"SELECT payload_id, payload_hash FROM payloads WHERE payload_id IN ({placeholders})",
            selected_ids,
        ).fetchall()
        payload_hashes = sorted({str(row["payload_hash"] or "") for row in payload_hash_rows if row["payload_hash"]})
        if not payload_hashes:
            return {payload_id: [] for payload_id in selected_ids}
        hash_placeholders = ",".join("?" for _ in payload_hashes)
        family_rows = conn.execute(
            f"""
            SELECT p.payload_id, p.payload_hash, p.root_path, p.file_count, p.total_bytes,
                   GROUP_CONCAT(ti.torrent_hash) AS torrent_hashes
            FROM payloads p
            LEFT JOIN torrent_instances ti ON ti.payload_id = p.payload_id
            WHERE p.payload_hash IN ({hash_placeholders})
            GROUP BY p.payload_id
            ORDER BY p.payload_hash, p.payload_id
            """,
            payload_hashes,
        ).fetchall()
    finally:
        conn.close()

    by_payload_hash: dict[str, list[dict[str, Any]]] = {}
    for row in family_rows:
        torrent_hashes = [
            _norm_hash(value)
            for value in str(row["torrent_hashes"] or "").split(",")
            if _norm_hash(value)
        ]
        by_payload_hash.setdefault(str(row["payload_hash"]), []).append(
            {
                "payload_id": int(row["payload_id"]),
                "payload_hash": row["payload_hash"],
                "root_path": row["root_path"],
                "file_count": row["file_count"],
                "total_bytes": row["total_bytes"],
                "torrent_hashes": sorted(torrent_hashes),
            }
        )
    selected_payload_hash = {
        int(row["payload_id"]): str(row["payload_hash"])
        for row in payload_hash_rows
        if row["payload_hash"]
    }
    return {
        payload_id: by_payload_hash.get(selected_payload_hash.get(payload_id, ""), [])
        for payload_id in selected_ids
    }


def _select_catalog_groups(
    catalog_groups: dict[int, dict[str, Any]],
    *,
    hash_filters: Iterable[str],
    payload_ids: Iterable[int],
) -> list[dict[str, Any]]:
    prefixes = tuple(_norm_hash(item) for item in hash_filters if _norm_hash(item))
    payload_id_set = {int(item) for item in payload_ids if item is not None}
    selected = []
    for group in catalog_groups.values():
        hashes = list(group.get("hashes") or [])
        if payload_id_set and int(group["payload_id"]) in payload_id_set:
            selected.append(group)
            continue
        if prefixes and any(hash_value.startswith(prefix) for hash_value in hashes for prefix in prefixes):
            selected.append(group)
            continue
        if not prefixes and not payload_id_set:
            selected.append(group)
    return selected


def build_hitchhiker_repair_plan(
    *,
    db_path: str | Path | None = None,
    hash_filters: Iterable[str] = (),
    payload_ids: Iterable[int] = (),
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    rt_session_dir: Path = DEFAULT_RT_SESSION_DIR,
    policy: ClientDriftPolicy | None = None,
) -> dict[str, Any]:
    """Build a read-only evidence bundle for selected N-to-1 hitchhiker repairs."""
    db = find_db_path(str(db_path) if db_path is not None else None)
    active_policy = policy or default_policy()
    catalog_groups = _catalog_rows_by_payload(db)
    selected_groups = _select_catalog_groups(
        catalog_groups,
        hash_filters=hash_filters,
        payload_ids=payload_ids,
    )
    selected_payload_ids = [int(group["payload_id"]) for group in selected_groups]
    audited = audit_hitchhiker_groups(
        db_path=str(db),
        session_dir=rt_session_dir,
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
    )
    audited_by_payload = {int(group.payload_id): group for group in audited}
    qb_rows = load_qb_cache_rows(qb_cache_file)
    rt_rows = load_rt_cache_rows(rt_cache_file, session_dir=rt_session_dir, policy=active_policy)
    families = _same_payload_hash_families(db, selected_payload_ids)

    items: list[dict[str, Any]] = []
    for group in selected_groups:
        payload_id = int(group["payload_id"])
        audited_group = audited_by_payload.get(payload_id)
        notes = list(audited_group.notes if audited_group else [])
        status = str(audited_group.status.value if audited_group else "unknown")
        hashes = sorted({_norm_hash(value) for value in group.get("hashes") or [] if _norm_hash(value)})
        hash_items: list[dict[str, Any]] = []
        group_blockers: list[str] = []
        for torrent_hash in hashes:
            qb_row = qb_rows.get(torrent_hash)
            rt_row = rt_rows.get(torrent_hash)
            in_qb = qb_row is not None
            in_rt = rt_row is not None
            path_drift = False
            if in_qb and in_rt:
                path_drift = not rt_path_aligned(
                    rt_row.save_path,
                    qb_save_path=qb_row.save_path,
                    qb_content_path=qb_row.content_path,
                )
            candidates: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            if qb_row is not None:
                _append_candidate(candidates, seen_paths, source="qb_content", path=qb_row.content_path, policy=active_policy)
                _append_candidate(candidates, seen_paths, source="qb_save", path=qb_row.save_path, policy=active_policy)
            if rt_row is not None:
                _append_candidate(candidates, seen_paths, source="rt_content", path=rt_row.content_path, policy=active_policy)
                _append_candidate(candidates, seen_paths, source="rt_save", path=rt_row.save_path, policy=active_policy)
                _append_candidate(candidates, seen_paths, source="rt_target_qb_save", path=rt_row.target_qb_save_path, policy=active_policy)
            _append_candidate(candidates, seen_paths, source="catalog_root", path=str(group.get("root_path") or ""), policy=active_policy)
            for family in families.get(payload_id, []):
                source = "same_payload_hash_root"
                if int(family.get("payload_id") or 0) == payload_id:
                    source = "selected_payload_root"
                _append_candidate(candidates, seen_paths, source=source, path=str(family.get("root_path") or ""), policy=active_policy)
            for candidate in candidates:
                candidate["target_checks"] = _target_checks_for_candidate(candidate["path"], torrent_hash)

            blockers: list[str] = []
            if not in_qb and not in_rt:
                blockers.append("missing_from_both_qb_and_rt")
            if path_drift:
                blockers.append("same_hash_qb_rt_path_drift_requires_source_selection")
            if not any(candidate.get("exists") for candidate in candidates):
                blockers.append("no_existing_source_candidate")
            if status != "safe_to_split":
                blockers.append(f"hitchhiker_group_status:{status}")
            group_blockers.extend(blocker for blocker in blockers if blocker not in group_blockers)
            hash_items.append(
                {
                    "hash": torrent_hash,
                    "in_qb": in_qb,
                    "in_rt": in_rt,
                    "path_drift": path_drift,
                    "qb": qb_row.to_dict() if qb_row else None,
                    "rt": rt_row.to_dict() if rt_row else None,
                    "source_candidates": candidates,
                    "blockers": blockers,
                }
            )

        next_commands: list[str] = []
        if status == "safe_to_split" and not group_blockers:
            next_commands.append(f"make hitchhiker-split-dry PAYLOAD_ID={payload_id}")
        else:
            next_commands.append(f"make hitchhiker-plan PAYLOAD_ID={payload_id} JSON=1")
            next_commands.append("choose a real source path before any selected manual repair")

        items.append(
            {
                "payload_id": payload_id,
                "root_path": group.get("root_path"),
                "file_count": group.get("file_count"),
                "total_bytes": group.get("total_bytes"),
                "hashes": hashes,
                "status": status,
                "notes": notes,
                "blockers": group_blockers,
                "same_payload_hash_family": families.get(payload_id, []),
                "hash_items": hash_items,
                "next_commands": next_commands,
            }
        )

    return {
        "summary": {
            "db_path": str(db),
            "selected_groups": len(items),
            "hash_filters": [_norm_hash(item) for item in hash_filters if _norm_hash(item)],
            "payload_ids": selected_payload_ids,
            "qb_cache_file": str(Path(qb_cache_file).expanduser()),
            "rt_cache_file": str(Path(rt_cache_file).expanduser()),
            "rt_session_dir": str(Path(rt_session_dir).expanduser()),
        },
        "groups": items,
    }


def format_hitchhiker_repair_plan(plan: dict[str, Any], *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(plan, indent=2)
    lines = ["Hitchhiker Repair Plan"]
    summary = plan.get("summary") or {}
    lines.append(f"  selected_groups: {summary.get('selected_groups', 0)}")
    lines.append(f"  db: {summary.get('db_path')}")
    lines.append("")
    for group in plan.get("groups") or []:
        blockers = ",".join(group.get("blockers") or []) or "none"
        lines.append(
            f"  payload_id={group.get('payload_id')} status={group.get('status')} "
            f"hashes={len(group.get('hashes') or [])} blockers={blockers}"
        )
        lines.append(f"    root: {group.get('root_path')}")
        for note in group.get("notes") or []:
            lines.append(f"    note: {note}")
        for item in group.get("hash_items") or []:
            hash_blockers = ",".join(item.get("blockers") or []) or "none"
            lines.append(
                f"    {str(item.get('hash') or '')[:16]} "
                f"qb={'yes' if item.get('in_qb') else 'no'} "
                f"rt={'yes' if item.get('in_rt') else 'no'} "
                f"path_drift={'yes' if item.get('path_drift') else 'no'} "
                f"blockers={hash_blockers}"
            )
            for candidate in item.get("source_candidates") or []:
                exists = "exists" if candidate.get("exists") else "missing"
                lines.append(
                    f"      source={candidate.get('source')} placement={candidate.get('placement') or '-'} "
                    f"{exists} path={candidate.get('path')}"
                )
                for check in candidate.get("target_checks") or []:
                    check_blockers = ",".join(check.get("blockers") or []) or "none"
                    check_warnings = ",".join(check.get("warnings") or []) or "none"
                    lines.append(
                        f"        target={check.get('target_parent_api')} "
                        f"same_device={check.get('same_device')} blockers={check_blockers} warnings={check_warnings}"
                    )
        for command in group.get("next_commands") or []:
            lines.append(f"    next: {command}")
        lines.append("")
    return "\n".join(lines).rstrip()
