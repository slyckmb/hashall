"""Follow-up verification and cleanup for rehome apply runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, Iterable, Optional

from hashall.qbittorrent import get_qbittorrent_client


VERIFY_PENDING_TAG = "rehome_verify_pending"
VERIFY_OK_TAG = "rehome_verify_ok"
VERIFY_FAILED_TAG = "rehome_verify_failed"
CLEANUP_REQUIRED_TAG = "rehome_cleanup_source_required"

GOOD_STATES = {"uploading", "stalledup", "queuedup", "forcedup", "pausedup"}
TRANSIENT_REASONS = {
    "progress_below_100",
    "state_transient",
    "stale_refs_on_source_payload",
    "source_has_torrent_refs",
}


@dataclass
class TorrentGate:
    torrent_hash: str
    ok: bool
    reasons: list[str]
    progress: Optional[float]
    state: Optional[str]
    auto_tmm: Optional[bool]
    save_path: Optional[str]
    tags: Optional[str]


def _split_tags(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part and part.strip()}


def _normalize_path(path: Optional[str]) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def _state_reason(state: Optional[str]) -> Optional[str]:
    if state is None:
        return "state_not_ready"
    s = str(state).strip().lower()
    if "checking" in s or "moving" in s or "allocating" in s or "queued" in s:
        return "state_transient"
    if s in {"error", "missingfiles"}:
        return "state_error"
    if s in GOOD_STATES:
        return None
    return "state_not_ready"


def _is_hard_failure(reasons: Iterable[str]) -> bool:
    for reason in reasons:
        if reason not in TRANSIENT_REASONS:
            return True
    return False


def _collect_candidate_hashes(qbit_client, include_failed: bool) -> dict[str, set[str]]:
    by_hash: dict[str, set[str]] = {}
    tags = [VERIFY_PENDING_TAG, CLEANUP_REQUIRED_TAG]
    if include_failed:
        tags.append(VERIFY_FAILED_TAG)

    for tag in tags:
        for torrent in qbit_client.get_torrents(tag=tag):
            if not torrent.hash:
                continue
            by_hash.setdefault(torrent.hash, set()).update(_split_tags(torrent.tags))

    return by_hash


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _update_verify_tags(qbit_client, torrent_hash: str, outcome: str, cleanup_done: bool) -> None:
    remove_tags = [VERIFY_PENDING_TAG, VERIFY_OK_TAG, VERIFY_FAILED_TAG]
    if cleanup_done:
        remove_tags.append(CLEANUP_REQUIRED_TAG)
    qbit_client.remove_tags(torrent_hash, remove_tags)

    if outcome == "pending":
        qbit_client.add_tags(torrent_hash, [VERIFY_PENDING_TAG])
    elif outcome == "failed":
        qbit_client.add_tags(torrent_hash, [VERIFY_FAILED_TAG])
    else:
        qbit_client.add_tags(torrent_hash, [VERIFY_OK_TAG])


def run_followup(
    *,
    catalog_path: Path,
    cleanup: bool = False,
    payload_hashes: Optional[set[str]] = None,
    limit: int = 0,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Run a follow-up pass for rehome tag state and optional source cleanup."""
    qbit = get_qbittorrent_client()
    if not qbit.test_connection() or not qbit.login():
        raise RuntimeError("qB connection/login failed")

    conn = sqlite3.connect(catalog_path)
    conn.row_factory = sqlite3.Row
    try:
        candidate_map = _collect_candidate_hashes(qbit, include_failed=retry_failed)
        if not candidate_map:
            return {
                "checked_at": datetime.now().astimezone().isoformat(),
                "catalog": str(catalog_path),
                "cleanup_requested": bool(cleanup),
                "summary": {
                    "groups_total": 0,
                    "groups_ok": 0,
                    "groups_pending": 0,
                    "groups_failed": 0,
                    "cleanup_attempted": 0,
                    "cleanup_done": 0,
                    "cleanup_failed": 0,
                },
                "entries": [],
            }

        payload_candidates: dict[str, dict[str, Any]] = {}
        missing_payload = 0
        for torrent_hash, initial_tags in candidate_map.items():
            row = conn.execute(
                """
                SELECT p.payload_hash
                FROM torrent_instances ti
                JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE ti.torrent_hash = ?
                LIMIT 1
                """,
                (torrent_hash,),
            ).fetchone()
            if not row or not row["payload_hash"]:
                missing_payload += 1
                continue

            payload_hash = str(row["payload_hash"])
            if payload_hashes and payload_hash not in payload_hashes:
                continue
            payload_candidates.setdefault(payload_hash, {"torrent_hashes": set(), "tags": set()})
            payload_candidates[payload_hash]["torrent_hashes"].add(torrent_hash)
            payload_candidates[payload_hash]["tags"].update(initial_tags)

        payload_keys = sorted(payload_candidates.keys())
        if limit and limit > 0:
            payload_keys = payload_keys[:limit]

        entries: list[dict[str, Any]] = []
        groups_ok = 0
        groups_pending = 0
        groups_failed = 0
        cleanup_attempted = 0
        cleanup_done = 0
        cleanup_failed = 0

        for payload_hash in payload_keys:
            group = payload_candidates[payload_hash]
            candidate_hashes = sorted(group["torrent_hashes"])
            db_rows = conn.execute(
                """
                SELECT ti.torrent_hash,
                       ti.device_id AS ti_device_id,
                       ti.save_path AS ti_save_path,
                       ti.tags AS ti_tags,
                       p.payload_id,
                       p.device_id AS payload_device_id,
                       p.root_path,
                       p.status
                FROM torrent_instances ti
                JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE p.payload_hash = ?
                ORDER BY ti.torrent_hash
                """,
                (payload_hash,),
            ).fetchall()
            row_by_hash = {str(r["torrent_hash"]): r for r in db_rows}

            device_counts: dict[int, int] = {}
            for row in db_rows:
                device_id = int(row["ti_device_id"] or 0)
                device_counts[device_id] = device_counts.get(device_id, 0) + 1
            target_device = 0
            if device_counts:
                target_device = sorted(device_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

            source_rows = [
                row for row in conn.execute(
                    """
                    SELECT payload_id, device_id, root_path, status
                    FROM payloads
                    WHERE payload_hash = ? AND status = 'complete'
                    ORDER BY payload_id
                    """,
                    (payload_hash,),
                ).fetchall()
                if int(row["device_id"] or 0) != target_device
            ]

            source_device = int(source_rows[0]["device_id"]) if source_rows else 0
            stale_refs = 0
            if source_device:
                stale_refs = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM torrent_instances ti
                        JOIN payloads p ON p.payload_id = ti.payload_id
                        WHERE p.payload_hash = ? AND p.device_id = ?
                        """,
                        (payload_hash, source_device),
                    ).fetchone()[0]
                    or 0
                )

            qb_checks: list[dict[str, Any]] = []
            qb_reasons: list[str] = []
            db_reasons: list[str] = []
            source_reasons: list[str] = []

            for torrent_hash in candidate_hashes:
                row = row_by_hash.get(torrent_hash)
                if not row:
                    db_reasons.append(f"missing_torrent_instance:{torrent_hash[:12]}")
                    qb_checks.append(
                        TorrentGate(
                            torrent_hash=torrent_hash,
                            ok=False,
                            reasons=["missing_torrent_instance"],
                            progress=None,
                            state=None,
                            auto_tmm=None,
                            save_path=None,
                            tags=None,
                        ).__dict__
                    )
                    continue

                if str(row["status"] or "") != "complete":
                    db_reasons.append(f"payload_not_complete:{torrent_hash[:12]}")
                if target_device and int(row["ti_device_id"] or 0) != target_device:
                    db_reasons.append(f"torrent_device_not_target:{torrent_hash[:12]}")
                if target_device and int(row["payload_device_id"] or 0) != target_device:
                    db_reasons.append(f"payload_device_not_target:{torrent_hash[:12]}")

                expected_save = _normalize_path(str(row["ti_save_path"] or ""))
                info = qbit.get_torrent_info(torrent_hash)
                if not info:
                    reasons = ["missing_in_qbit"]
                    qb_reasons.extend(reasons)
                    qb_checks.append(
                        TorrentGate(
                            torrent_hash=torrent_hash,
                            ok=False,
                            reasons=reasons,
                            progress=None,
                            state=None,
                            auto_tmm=None,
                            save_path=None,
                            tags=None,
                        ).__dict__
                    )
                    continue

                # Keep DB tags reasonably fresh after follow-up reads.
                conn.execute(
                    """
                    UPDATE torrent_instances
                    SET tags = ?, last_seen_at = CURRENT_TIMESTAMP
                    WHERE torrent_hash = ?
                    """,
                    (str(getattr(info, "tags", "") or ""), torrent_hash),
                )

                progress = float(getattr(info, "progress", 0.0))
                state = str(getattr(info, "state", ""))
                auto_tmm = bool(getattr(info, "auto_tmm", False))
                save_path = _normalize_path(str(getattr(info, "save_path", "") or ""))
                info_tags = str(getattr(info, "tags", "") or "")

                reasons: list[str] = []
                if progress < 0.9999:
                    reasons.append("progress_below_100")
                state_reason = _state_reason(state)
                if state_reason:
                    reasons.append(state_reason)
                if auto_tmm:
                    reasons.append("auto_tmm_enabled")
                if expected_save and save_path and expected_save != save_path:
                    reasons.append("save_path_mismatch")

                qb_reasons.extend(reasons)
                qb_checks.append(
                    TorrentGate(
                        torrent_hash=torrent_hash,
                        ok=(len(reasons) == 0),
                        reasons=reasons,
                        progress=progress,
                        state=state,
                        auto_tmm=auto_tmm,
                        save_path=save_path,
                        tags=info_tags,
                    ).__dict__
                )

            if stale_refs > 0:
                db_reasons.append("stale_refs_on_source_payload")
                source_reasons.append("source_has_torrent_refs")

            all_reasons = qb_reasons + db_reasons + source_reasons
            if not all_reasons:
                outcome = "ok"
            elif _is_hard_failure(all_reasons):
                outcome = "failed"
            else:
                outcome = "pending"

            cleanup_required = CLEANUP_REQUIRED_TAG in group["tags"]
            cleanup_result = "skipped"
            cleanup_errors: list[str] = []
            deleted_paths: list[str] = []
            if cleanup and cleanup_required and outcome == "ok":
                cleanup_attempted += 1
                for row in source_rows:
                    source_path = Path(str(row["root_path"] or ""))
                    if not source_path.exists():
                        continue
                    try:
                        _delete_path(source_path)
                        deleted_paths.append(str(source_path))
                    except Exception as exc:
                        cleanup_errors.append(f"{source_path}: {exc}")

                if cleanup_errors:
                    cleanup_result = "failed"
                    cleanup_failed += 1
                else:
                    cleanup_result = "done"
                    cleanup_done += 1

            for torrent_hash in candidate_hashes:
                _update_verify_tags(
                    qbit,
                    torrent_hash=torrent_hash,
                    outcome=outcome,
                    cleanup_done=(cleanup_result == "done"),
                )

            if outcome == "ok":
                groups_ok += 1
            elif outcome == "failed":
                groups_failed += 1
            else:
                groups_pending += 1

            entries.append(
                {
                    "payload_hash": payload_hash,
                    "outcome": outcome,
                    "candidate_torrents": candidate_hashes,
                    "target_device_id": target_device,
                    "source_device_id": source_device,
                    "cleanup_required": cleanup_required,
                    "cleanup_result": cleanup_result,
                    "cleanup_deleted_paths": deleted_paths,
                    "cleanup_errors": cleanup_errors,
                    "qb_checks": qb_checks,
                    "db_reasons": sorted(set(db_reasons)),
                    "source_reasons": sorted(set(source_reasons)),
                }
            )

        conn.commit()
        return {
            "checked_at": datetime.now().astimezone().isoformat(),
            "catalog": str(catalog_path),
            "cleanup_requested": bool(cleanup),
            "retry_failed": bool(retry_failed),
            "missing_payload_rows": missing_payload,
            "summary": {
                "groups_total": len(entries),
                "groups_ok": groups_ok,
                "groups_pending": groups_pending,
                "groups_failed": groups_failed,
                "cleanup_attempted": cleanup_attempted,
                "cleanup_done": cleanup_done,
                "cleanup_failed": cleanup_failed,
            },
            "entries": entries,
        }
    finally:
        conn.close()
