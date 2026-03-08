"""Catalog identity repair helpers for fs_uuid-first reconciliation.

This module repairs legacy/stale rows in ``payloads`` and ``torrent_instances``
by reconciling identity in this order:

1) Existing valid ``fs_uuid``
2) Existing valid ``device_id`` -> ``fs_uuid`` via ``devices``
3) Related-row evidence (payload/torrent linkage, payload_hash peers)
4) Path-prefix inference (safe prefixes only, optional bind alias support)

Safety posture:
- Fail closed on ambiguity.
- No automatic ``/pool/media`` <-> ``/pool/data`` aliasing.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DeviceInfo:
    device_id: int
    fs_uuid: str
    mount_point: str
    preferred_mount_point: str


@dataclass
class RepairAction:
    table: str
    key: str
    before_device_id: Optional[int]
    before_fs_uuid: Optional[str]
    target_device_id: int
    target_fs_uuid: str
    reason: str
    path_hint: str


@dataclass
class RepairResult:
    generated_at: str
    db_path: str
    apply_mode: bool
    payload_candidates: int
    torrent_candidates: int
    actions_planned: int
    actions_applied: int
    unresolved_count: int
    reason_counts: Dict[str, int]
    unresolved_samples: List[Dict[str, str]]
    actions: List[RepairAction]

    def to_json(self) -> str:
        payload = {
            "tool": "hashall.identity_repair",
            "generated_at": self.generated_at,
            "db_path": self.db_path,
            "apply_mode": self.apply_mode,
            "summary": {
                "payload_candidates": self.payload_candidates,
                "torrent_candidates": self.torrent_candidates,
                "actions_planned": self.actions_planned,
                "actions_applied": self.actions_applied,
                "unresolved_count": self.unresolved_count,
                "reason_counts": self.reason_counts,
            },
            "unresolved_samples": self.unresolved_samples,
            "actions": [
                {
                    "table": a.table,
                    "key": a.key,
                    "before_device_id": a.before_device_id,
                    "before_fs_uuid": a.before_fs_uuid,
                    "target_device_id": a.target_device_id,
                    "target_fs_uuid": a.target_fs_uuid,
                    "reason": a.reason,
                    "path_hint": a.path_hint,
                }
                for a in self.actions
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def write_report(result: RepairResult, out_path: Path) -> Path:
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.to_json(), encoding="utf-8")
    return out


def _norm_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def _is_under(path: str, root: str) -> bool:
    p = _norm_path(path)
    r = _norm_path(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r + "/")


def _table_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(str(row[1]) == str(col) for row in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _load_devices(
    conn: sqlite3.Connection,
) -> Tuple[Dict[int, DeviceInfo], Dict[str, DeviceInfo], List[Tuple[str, DeviceInfo]]]:
    if not _table_exists(conn, "devices"):
        raise RuntimeError("devices table missing; cannot repair identity")

    rows = conn.execute(
        """
        SELECT device_id, fs_uuid, mount_point, preferred_mount_point
        FROM devices
        WHERE fs_uuid IS NOT NULL AND trim(fs_uuid) <> ''
        """
    ).fetchall()
    by_id: Dict[int, DeviceInfo] = {}
    by_uuid: Dict[str, DeviceInfo] = {}
    prefixes: List[Tuple[str, DeviceInfo]] = []
    for row in rows:
        try:
            device_id = int(row[0])
        except Exception:
            continue
        fs_uuid = str(row[1] or "").strip()
        if not fs_uuid:
            continue
        mount_point = _norm_path(str(row[2] or ""))
        preferred = _norm_path(str(row[3] or row[2] or ""))
        info = DeviceInfo(
            device_id=device_id,
            fs_uuid=fs_uuid,
            mount_point=mount_point,
            preferred_mount_point=preferred,
        )
        by_id[device_id] = info
        by_uuid[fs_uuid] = info
        for root in (preferred, mount_point):
            if root:
                prefixes.append((root, info))
    prefixes.sort(key=lambda x: len(x[0]), reverse=True)
    return by_id, by_uuid, prefixes


def _path_alias_candidates(path: str, *, allow_bind_aliases: bool) -> List[Tuple[str, str]]:
    """Return candidate path variants and reason tags.

    Only the known bind alias (/data/media <-> /stash/media) is supported, because
    both roots are expected to be the same filesystem in this deployment.
    """
    p = _norm_path(path)
    if not p:
        return []

    out: List[Tuple[str, str]] = [(p, "path_prefix")]
    if not allow_bind_aliases:
        return out

    if p == "/data/media" or p.startswith("/data/media/"):
        out.append(("/stash/media" + p[len("/data/media") :], "path_alias_data_to_stash"))
    elif p == "/stash/media" or p.startswith("/stash/media/"):
        out.append(("/data/media" + p[len("/stash/media") :], "path_alias_stash_to_data"))
    return out


def _infer_from_path(
    path: str,
    prefixes: List[Tuple[str, DeviceInfo]],
    *,
    allow_bind_aliases: bool,
) -> Optional[Tuple[int, str, str]]:
    for candidate, reason_base in _path_alias_candidates(path, allow_bind_aliases=allow_bind_aliases):
        # Keep longest-prefix wins, but fail closed on same-length multi-device ambiguity.
        best_len = -1
        best: Dict[int, DeviceInfo] = {}
        for root, info in prefixes:
            if not _is_under(candidate, root):
                continue
            root_len = len(root)
            if root_len > best_len:
                best_len = root_len
                best = {info.device_id: info}
            elif root_len == best_len:
                best[info.device_id] = info
        if len(best) == 1:
            info = next(iter(best.values()))
            return info.device_id, info.fs_uuid, reason_base
        if len(best) > 1:
            return None
    return None


def _pick_majority(items: Iterable[Tuple[int, str]], reason: str) -> Optional[Tuple[int, str, str]]:
    values = list(items)
    if not values:
        return None
    counts = Counter(values)
    top_count = max(counts.values())
    top_values = [key for key, count in counts.items() if count == top_count]
    if len(top_values) != 1:
        return None
    winner = top_values[0]
    return winner[0], winner[1], reason


def _payload_candidates(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.payload_id, p.payload_hash, p.device_id, p.fs_uuid, p.root_path
        FROM payloads p
        LEFT JOIN devices d_id ON d_id.device_id = p.device_id
        LEFT JOIN devices d_uuid ON d_uuid.fs_uuid = p.fs_uuid
        WHERE p.device_id IS NULL
           OR d_id.device_id IS NULL
           OR p.fs_uuid IS NULL
           OR trim(p.fs_uuid) = ''
           OR d_uuid.fs_uuid IS NULL
           OR (d_id.fs_uuid IS NOT NULL AND p.fs_uuid IS NOT NULL AND trim(p.fs_uuid) <> '' AND d_id.fs_uuid <> p.fs_uuid)
        ORDER BY p.payload_id
        """
    ).fetchall()


def _torrent_candidates(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ti.torrent_hash, ti.payload_id, ti.device_id, ti.fs_uuid, ti.save_path
        FROM torrent_instances ti
        LEFT JOIN devices d_id ON d_id.device_id = ti.device_id
        LEFT JOIN devices d_uuid ON d_uuid.fs_uuid = ti.fs_uuid
        WHERE ti.device_id IS NULL
           OR d_id.device_id IS NULL
           OR ti.fs_uuid IS NULL
           OR trim(ti.fs_uuid) = ''
           OR d_uuid.fs_uuid IS NULL
           OR (d_id.fs_uuid IS NOT NULL AND ti.fs_uuid IS NOT NULL AND trim(ti.fs_uuid) <> '' AND d_id.fs_uuid <> ti.fs_uuid)
        ORDER BY ti.torrent_hash
        """
    ).fetchall()


def _infer_payload_target(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    by_id: Dict[int, DeviceInfo],
    by_uuid: Dict[str, DeviceInfo],
    prefixes: List[Tuple[str, DeviceInfo]],
    *,
    allow_bind_aliases: bool,
) -> Optional[Tuple[int, str, str]]:
    current_fs = str(row["fs_uuid"] or "").strip()
    if current_fs and current_fs in by_uuid:
        info = by_uuid[current_fs]
        return info.device_id, info.fs_uuid, "payload_current_fs_uuid"

    current_dev = row["device_id"]
    if current_dev is not None:
        info = by_id.get(int(current_dev))
        if info:
            return info.device_id, info.fs_uuid, "payload_current_device_id"

    payload_id = int(row["payload_id"])
    linked_torrents = conn.execute(
        """
        SELECT ti.device_id, ti.fs_uuid
        FROM torrent_instances ti
        WHERE ti.payload_id = ?
        """,
        (payload_id,),
    ).fetchall()
    linked_pairs: List[Tuple[int, str]] = []
    for rel in linked_torrents:
        rel_fs = str(rel[1] or "").strip()
        if rel_fs in by_uuid:
            info = by_uuid[rel_fs]
            linked_pairs.append((info.device_id, info.fs_uuid))
            continue
        rel_dev = rel[0]
        if rel_dev is not None and int(rel_dev) in by_id:
            info = by_id[int(rel_dev)]
            linked_pairs.append((info.device_id, info.fs_uuid))
    inferred = _pick_majority(linked_pairs, "payload_linked_torrent_identity")
    if inferred:
        return inferred

    payload_hash = str(row["payload_hash"] or "").strip()
    if payload_hash:
        peers = conn.execute(
            """
            SELECT device_id, fs_uuid
            FROM payloads
            WHERE payload_hash = ?
            """,
            (payload_hash,),
        ).fetchall()
        peer_pairs: List[Tuple[int, str]] = []
        for peer in peers:
            peer_fs = str(peer[1] or "").strip()
            if peer_fs in by_uuid:
                info = by_uuid[peer_fs]
                peer_pairs.append((info.device_id, info.fs_uuid))
                continue
            peer_dev = peer[0]
            if peer_dev is not None and int(peer_dev) in by_id:
                info = by_id[int(peer_dev)]
                peer_pairs.append((info.device_id, info.fs_uuid))
        inferred = _pick_majority(peer_pairs, "payload_peer_payload_hash")
        if inferred:
            return inferred

    root_path = str(row["root_path"] or "")
    inferred_path = _infer_from_path(root_path, prefixes, allow_bind_aliases=allow_bind_aliases)
    if inferred_path:
        return inferred_path
    return None


def _infer_torrent_target(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    by_id: Dict[int, DeviceInfo],
    by_uuid: Dict[str, DeviceInfo],
    prefixes: List[Tuple[str, DeviceInfo]],
    *,
    pending_payload_targets: Dict[int, Tuple[int, str]],
    allow_bind_aliases: bool,
) -> Optional[Tuple[int, str, str]]:
    current_fs = str(row["fs_uuid"] or "").strip()
    if current_fs and current_fs in by_uuid:
        info = by_uuid[current_fs]
        return info.device_id, info.fs_uuid, "torrent_current_fs_uuid"

    current_dev = row["device_id"]
    if current_dev is not None:
        info = by_id.get(int(current_dev))
        if info:
            return info.device_id, info.fs_uuid, "torrent_current_device_id"

    payload_id = row["payload_id"]
    if payload_id is not None:
        pending = pending_payload_targets.get(int(payload_id))
        if pending:
            return pending[0], pending[1], "torrent_linked_payload_pending_repair"

        payload_row = conn.execute(
            """
            SELECT device_id, fs_uuid
            FROM payloads
            WHERE payload_id = ?
            """,
            (int(payload_id),),
        ).fetchone()
        if payload_row:
            p_fs = str(payload_row[1] or "").strip()
            if p_fs in by_uuid:
                info = by_uuid[p_fs]
                return info.device_id, info.fs_uuid, "torrent_linked_payload_fs_uuid"
            p_dev = payload_row[0]
            if p_dev is not None and int(p_dev) in by_id:
                info = by_id[int(p_dev)]
                return info.device_id, info.fs_uuid, "torrent_linked_payload_device_id"

    save_path = str(row["save_path"] or "")
    inferred_path = _infer_from_path(save_path, prefixes, allow_bind_aliases=allow_bind_aliases)
    if inferred_path:
        return inferred_path
    return None


def run_identity_repair(
    db_path: Path,
    *,
    apply_mode: bool = False,
    max_actions: int = 0,
    allow_bind_aliases: bool = True,
) -> RepairResult:
    db = Path(db_path).expanduser()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        if not _table_has_column(conn, "payloads", "fs_uuid") or not _table_has_column(
            conn, "torrent_instances", "fs_uuid"
        ):
            raise RuntimeError("fs_uuid columns missing; run migration 0012 first")

        by_id, by_uuid, prefixes = _load_devices(conn)
        actions: List[RepairAction] = []
        unresolved: List[Dict[str, str]] = []
        reason_counts: Counter[str] = Counter()
        pending_payload_targets: Dict[int, Tuple[int, str]] = {}

        payload_rows = _payload_candidates(conn)
        torrent_rows = _torrent_candidates(conn)

        for row in payload_rows:
            inferred = _infer_payload_target(
                conn,
                row,
                by_id,
                by_uuid,
                prefixes,
                allow_bind_aliases=allow_bind_aliases,
            )
            if not inferred:
                unresolved.append(
                    {
                        "table": "payloads",
                        "key": str(row["payload_id"]),
                        "path": str(row["root_path"] or ""),
                        "device_id": str(row["device_id"] if row["device_id"] is not None else "NULL"),
                        "fs_uuid": str(row["fs_uuid"] or ""),
                        "reason": "unresolved_payload",
                    }
                )
                continue
            tgt_dev, tgt_fs, reason = inferred
            pending_payload_targets[int(row["payload_id"])] = (tgt_dev, tgt_fs)
            before_dev = int(row["device_id"]) if row["device_id"] is not None else None
            before_fs = str(row["fs_uuid"] or "").strip() or None
            if before_dev == tgt_dev and before_fs == tgt_fs:
                continue
            reason_counts[reason] += 1
            actions.append(
                RepairAction(
                    table="payloads",
                    key=str(row["payload_id"]),
                    before_device_id=before_dev,
                    before_fs_uuid=before_fs,
                    target_device_id=tgt_dev,
                    target_fs_uuid=tgt_fs,
                    reason=reason,
                    path_hint=str(row["root_path"] or ""),
                )
            )

        for row in torrent_rows:
            inferred = _infer_torrent_target(
                conn,
                row,
                by_id,
                by_uuid,
                prefixes,
                pending_payload_targets=pending_payload_targets,
                allow_bind_aliases=allow_bind_aliases,
            )
            if not inferred:
                unresolved.append(
                    {
                        "table": "torrent_instances",
                        "key": str(row["torrent_hash"]),
                        "path": str(row["save_path"] or ""),
                        "device_id": str(row["device_id"] if row["device_id"] is not None else "NULL"),
                        "fs_uuid": str(row["fs_uuid"] or ""),
                        "reason": "unresolved_torrent",
                    }
                )
                continue
            tgt_dev, tgt_fs, reason = inferred
            before_dev = int(row["device_id"]) if row["device_id"] is not None else None
            before_fs = str(row["fs_uuid"] or "").strip() or None
            if before_dev == tgt_dev and before_fs == tgt_fs:
                continue
            reason_counts[reason] += 1
            actions.append(
                RepairAction(
                    table="torrent_instances",
                    key=str(row["torrent_hash"]),
                    before_device_id=before_dev,
                    before_fs_uuid=before_fs,
                    target_device_id=tgt_dev,
                    target_fs_uuid=tgt_fs,
                    reason=reason,
                    path_hint=str(row["save_path"] or ""),
                )
            )

        if max_actions > 0:
            actions = actions[: max_actions]

        applied = 0
        if apply_mode and actions:
            payload_has_updated_at = _table_has_column(conn, "payloads", "updated_at")
            torrent_has_updated_at = _table_has_column(conn, "torrent_instances", "updated_at")

            for action in actions:
                if action.table == "payloads":
                    if payload_has_updated_at:
                        conn.execute(
                            """
                            UPDATE payloads
                            SET device_id = ?, fs_uuid = ?, updated_at = datetime('now')
                            WHERE payload_id = ?
                            """,
                            (action.target_device_id, action.target_fs_uuid, int(action.key)),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE payloads
                            SET device_id = ?, fs_uuid = ?
                            WHERE payload_id = ?
                            """,
                            (action.target_device_id, action.target_fs_uuid, int(action.key)),
                        )
                else:
                    if torrent_has_updated_at:
                        conn.execute(
                            """
                            UPDATE torrent_instances
                            SET device_id = ?, fs_uuid = ?, updated_at = datetime('now')
                            WHERE torrent_hash = ?
                            """,
                            (action.target_device_id, action.target_fs_uuid, action.key),
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE torrent_instances
                            SET device_id = ?, fs_uuid = ?
                            WHERE torrent_hash = ?
                            """,
                            (action.target_device_id, action.target_fs_uuid, action.key),
                        )
                applied += 1
            conn.commit()

        return RepairResult(
            generated_at=datetime.now().isoformat(timespec="seconds"),
            db_path=str(db),
            apply_mode=bool(apply_mode),
            payload_candidates=len(payload_rows),
            torrent_candidates=len(torrent_rows),
            actions_planned=len(actions),
            actions_applied=applied,
            unresolved_count=len(unresolved),
            reason_counts=dict(sorted(reason_counts.items())),
            unresolved_samples=unresolved[:200],
            actions=actions,
        )
    finally:
        conn.close()
