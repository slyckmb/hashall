"""Follow-up verification and cleanup for rehome apply runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any, Dict, Iterable, Optional

from hashall.qbittorrent import get_qbittorrent_client


VERIFY_PENDING_TAG = "rehome_verify_pending"
VERIFY_OK_TAG = "rehome_verify_ok"
VERIFY_FAILED_TAG = "rehome_verify_failed"
CLEANUP_REQUIRED_TAG = "rehome_cleanup_source_required"
DEFAULT_CLEANUP_OBSERVE_SECONDS = 60.0
DEFAULT_CLEANUP_POLL_SECONDS = 5.0
DEFAULT_CLEANUP_STAGE_DIRNAME = ".rehome-cleanup-stage"
PATH_ALIAS_PREFIXES = (
    ("/data/media", "/stash/media"),
    ("/stash/media", "/data/media"),
)

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


@dataclass
class CleanupSource:
    payload_id: int
    device_id: int
    root_path: Path
    file_count: int
    total_bytes: int
    stage_path: Path


def _classify_cleanup_disposition(
    *,
    cleanup_required: bool,
    cleanup_sources: list["CleanupSource"],
    outcome: str,
    db_reasons: list[str],
    source_reasons: list[str],
    stale_refs: int,
) -> tuple[str, list[str]]:
    if not cleanup_required:
        return "not_required", []

    if not cleanup_sources:
        return "already_cleaned", ["no_source_payload_rows"]

    existing_sources = [source for source in cleanup_sources if source.root_path.exists()]
    if not existing_sources:
        return "already_cleaned", ["source_paths_absent"]

    if stale_refs > 0:
        return "blocked_stale_refs", ["stale_refs_on_source_payload"]

    if outcome != "ok":
        reasons = sorted(set(db_reasons + source_reasons))
        if not reasons:
            reasons = ["retain_for_rollback"]
        return "retain_for_rollback", reasons

    return "cleanup_safe_now", []


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


def _alias_variants(path: Optional[str]) -> set[str]:
    normalized = _normalize_path(path)
    if not normalized:
        return set()
    variants = {normalized}
    for old_prefix, new_prefix in PATH_ALIAS_PREFIXES:
        if normalized == old_prefix:
            variants.add(new_prefix)
        elif normalized.startswith(old_prefix + "/"):
            variants.add(new_prefix + normalized[len(old_prefix) :])
    return variants


def _source_save_prefixes(source_rows: Iterable[sqlite3.Row]) -> set[str]:
    prefixes: set[str] = set()
    for row in source_rows:
        root_path = str(row["root_path"] or "").strip()
        if not root_path:
            continue
        root = Path(root_path)
        candidates = {root_path}
        if root.parent != root:
            candidates.add(str(root.parent))
        for candidate in candidates:
            prefixes.update(_alias_variants(candidate))
    return {prefix.rstrip("/") or "/" for prefix in prefixes if prefix}


def _path_matches_any_prefix(path: Optional[str], prefixes: set[str]) -> bool:
    normalized = _normalize_path(path)
    if not normalized:
        return False
    normalized = normalized.rstrip("/") or "/"
    for prefix in prefixes:
        base = prefix.rstrip("/") or "/"
        if normalized == base or normalized.startswith(base + "/"):
            return True
    return False


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


def _collect_torrent_snapshot(qbit_client) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for torrent in qbit_client.get_torrents():
        torrent_hash = str(getattr(torrent, "hash", "") or "").strip().lower()
        if torrent_hash:
            snapshot[torrent_hash] = torrent
    return snapshot


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _path_stats(path: Path) -> dict[str, int | bool]:
    target = Path(path)
    if not target.exists():
        return {"exists": False, "is_file": False, "file_count": 0, "total_bytes": 0}
    if target.is_file():
        return {
            "exists": True,
            "is_file": True,
            "file_count": 1,
            "total_bytes": int(target.stat().st_size),
        }
    file_count = 0
    total_bytes = 0
    for candidate in target.rglob("*"):
        if not candidate.is_file():
            continue
        file_count += 1
        total_bytes += int(candidate.stat().st_size)
    return {
        "exists": True,
        "is_file": False,
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def _format_stats(path: Path, stats: dict[str, int | bool], *, expected_count: int, expected_bytes: int) -> str:
    return (
        f"path={path} exists={str(bool(stats['exists'])).lower()} "
        f"actual_files={int(stats['file_count'])} expected_files={int(expected_count)} "
        f"actual_bytes={int(stats['total_bytes'])} expected_bytes={int(expected_bytes)}"
    )


def _build_torrent_gate(
    *,
    torrent_hash: str,
    info: Any,
    expected_save: str,
) -> TorrentGate:
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

    return TorrentGate(
        torrent_hash=torrent_hash,
        ok=(len(reasons) == 0),
        reasons=reasons,
        progress=progress,
        state=state,
        auto_tmm=auto_tmm,
        save_path=save_path,
        tags=info_tags,
    )


def _make_stage_path(source_path: Path, payload_hash: str) -> Path:
    return source_path.parent / DEFAULT_CLEANUP_STAGE_DIRNAME / payload_hash / source_path.name


def _load_cleanup_sources(rows: Iterable[sqlite3.Row], payload_hash: str) -> list[CleanupSource]:
    return [
        CleanupSource(
            payload_id=int(row["payload_id"] or 0),
            device_id=int(row["device_id"] or 0),
            root_path=Path(str(row["root_path"] or "")),
            file_count=int(row["file_count"] or 0),
            total_bytes=int(row["total_bytes"] or 0),
            stage_path=_make_stage_path(Path(str(row["root_path"] or "")), payload_hash),
        )
        for row in rows
    ]


def _find_stale_payload_refs(
    conn: sqlite3.Connection,
    *,
    payload_hash: str,
    target_device: int,
    source_save_prefixes: set[str],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ti.torrent_hash,
               ti.device_id AS ti_device_id,
               ti.save_path AS ti_save_path,
               p.payload_id,
               p.device_id AS payload_device_id,
               p.root_path
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE p.payload_hash = ?
        ORDER BY ti.torrent_hash
        """,
        (payload_hash,),
    ).fetchall()
    stale_rows: list[dict[str, Any]] = []
    for row in rows:
        ti_device = int(row["ti_device_id"] or 0)
        payload_device = int(row["payload_device_id"] or 0)
        save_path = str(row["ti_save_path"] or "")
        stale = (
            (target_device and ti_device != target_device)
            or (target_device and payload_device != target_device)
            or _path_matches_any_prefix(save_path, source_save_prefixes)
        )
        if not stale:
            continue
        stale_rows.append(
            {
                "torrent_hash": str(row["torrent_hash"] or ""),
                "ti_device_id": ti_device,
                "payload_device_id": payload_device,
                "save_path": save_path,
                "root_path": str(row["root_path"] or ""),
                "payload_id": int(row["payload_id"] or 0),
            }
        )
    return stale_rows


def _derive_target_root(row: sqlite3.Row, expected_save: str) -> str:
    root_path = str(row["root_path"] or "").strip()
    if not root_path or not expected_save:
        return ""
    root_name = Path(root_path).name
    if not root_name:
        return ""
    return _normalize_path(str(Path(expected_save) / root_name))


def _find_target_payload_row(
    conn: sqlite3.Connection,
    *,
    payload_hash: str,
    target_device: int,
    target_root: str,
) -> Optional[sqlite3.Row]:
    if not payload_hash or not target_device or not target_root:
        target_root = ""
    exact = conn.execute(
        """
        SELECT payload_id, device_id, root_path, status
        FROM payloads
        WHERE payload_hash = ?
          AND device_id = ?
          AND root_path = ?
          AND status = 'complete'
        ORDER BY payload_id
        LIMIT 1
        """,
        (payload_hash, target_device, target_root),
    ).fetchone()
    if exact:
        return exact
    return conn.execute(
        """
        SELECT payload_id, device_id, root_path, status
        FROM payloads
        WHERE payload_hash = ?
          AND device_id = ?
          AND status = 'complete'
        ORDER BY payload_id
        LIMIT 1
        """,
        (payload_hash, target_device),
    ).fetchone()


def _observe_cleanup_gate(
    *,
    qbit_client,
    candidate_hashes: list[str],
    expected_saves: dict[str, str],
    observe_seconds: float,
    poll_seconds: float,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    deadline = time.monotonic() + max(0.0, float(observe_seconds))
    while True:
        snapshot = _collect_torrent_snapshot(qbit_client)
        qb_checks: list[dict[str, Any]] = []
        reasons: list[str] = []
        for torrent_hash in candidate_hashes:
            info = snapshot.get(str(torrent_hash).lower()) or qbit_client.get_torrent_info(torrent_hash)
            if not info:
                gate = TorrentGate(
                    torrent_hash=torrent_hash,
                    ok=False,
                    reasons=["missing_in_qbit"],
                    progress=None,
                    state=None,
                    auto_tmm=None,
                    save_path=None,
                    tags=None,
                )
            else:
                gate = _build_torrent_gate(
                    torrent_hash=torrent_hash,
                    info=info,
                    expected_save=expected_saves.get(torrent_hash, ""),
                )
            qb_checks.append(gate.__dict__)
            reasons.extend(gate.reasons)
        if not reasons:
            return True, qb_checks, []
        if time.monotonic() >= deadline:
            return False, qb_checks, sorted(set(reasons))
        time.sleep(max(0.1, float(poll_seconds)))


def _cleanup_sources_with_staging(
    *,
    qbit_client,
    payload_hash: str,
    candidate_hashes: list[str],
    expected_saves: dict[str, str],
    source_rows: list[CleanupSource],
    observe_seconds: float,
    poll_seconds: float,
) -> tuple[str, list[str], list[str], list[str], list[dict[str, Any]]]:
    cleanup_errors: list[str] = []
    deleted_paths: list[str] = []
    staged_paths: list[str] = []
    cleanup_checks: list[dict[str, Any]] = []

    for source in source_rows:
        stats = _path_stats(source.root_path)
        if not bool(stats["exists"]):
            continue
        if int(stats["file_count"]) != source.file_count or int(stats["total_bytes"]) != source.total_bytes:
            cleanup_errors.append(
                "source_stats_mismatch "
                + _format_stats(
                    source.root_path,
                    stats,
                    expected_count=source.file_count,
                    expected_bytes=source.total_bytes,
                )
            )
        if source.stage_path.exists():
            cleanup_errors.append(f"cleanup_stage_path_exists path={source.stage_path}")
    if cleanup_errors:
        return "failed", deleted_paths, cleanup_errors, staged_paths, cleanup_checks

    renamed: list[CleanupSource] = []
    try:
        for source in source_rows:
            if not source.root_path.exists():
                continue
            source.stage_path.parent.mkdir(parents=True, exist_ok=True)
            source.root_path.rename(source.stage_path)
            renamed.append(source)
            staged_paths.append(str(source.stage_path))

        observed_ok, cleanup_checks, observe_reasons = _observe_cleanup_gate(
            qbit_client=qbit_client,
            candidate_hashes=candidate_hashes,
            expected_saves=expected_saves,
            observe_seconds=observe_seconds,
            poll_seconds=poll_seconds,
        )
        if not observed_ok:
            raise RuntimeError(",".join(observe_reasons or ["cleanup_observe_failed"]))

        for source in renamed:
            if not source.stage_path.exists():
                continue
            _delete_path(source.stage_path)
            deleted_paths.append(str(source.root_path))
        return "done", deleted_paths, cleanup_errors, staged_paths, cleanup_checks
    except Exception as exc:
        cleanup_errors.append(str(exc))
        for source in reversed(renamed):
            if source.stage_path.exists() and not source.root_path.exists():
                source.stage_path.rename(source.root_path)
        return "restored", deleted_paths, cleanup_errors, staged_paths, cleanup_checks


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
    cleanup_observe_seconds: float = DEFAULT_CLEANUP_OBSERVE_SECONDS,
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
        candidate_hashes = sorted(candidate_map.keys())
        payload_hash_by_torrent: dict[str, str] = {}
        if candidate_hashes:
            chunk_size = 500
            for i in range(0, len(candidate_hashes), chunk_size):
                chunk = candidate_hashes[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""
                    SELECT lower(ti.torrent_hash) AS torrent_hash, p.payload_hash
                    FROM torrent_instances ti
                    JOIN payloads p ON p.payload_id = ti.payload_id
                    WHERE lower(ti.torrent_hash) IN ({placeholders})
                    """,
                    [item.lower() for item in chunk],
                ).fetchall()
                for row in rows:
                    torrent_hash = str(row["torrent_hash"] or "").strip().lower()
                    payload_hash = str(row["payload_hash"] or "").strip()
                    if torrent_hash and payload_hash:
                        payload_hash_by_torrent[torrent_hash] = payload_hash

        torrent_snapshot = _collect_torrent_snapshot(qbit)
        tag_updates = []

        for torrent_hash, initial_tags in candidate_map.items():
            payload_hash = payload_hash_by_torrent.get(str(torrent_hash).lower(), "")
            if not payload_hash:
                missing_payload += 1
                continue

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
        cleanup_safe_now = 0
        cleanup_retain_for_rollback = 0
        cleanup_blocked = 0
        cleanup_already_cleaned = 0
        cleanup_not_required = 0

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
            candidate_rows = [row_by_hash[h] for h in candidate_hashes if h in row_by_hash]

            device_counts: dict[int, int] = {}
            for row in candidate_rows:
                device_id = int(row["ti_device_id"] or 0)
                device_counts[device_id] = device_counts.get(device_id, 0) + 1
            target_device = 0
            if device_counts:
                target_device = sorted(device_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

            source_rows = [
                row for row in conn.execute(
                    """
                    SELECT payload_id, device_id, root_path, file_count, total_bytes, status
                    FROM payloads
                    WHERE payload_hash = ? AND status = 'complete'
                    ORDER BY payload_id
                    """,
                    (payload_hash,),
                ).fetchall()
                if int(row["device_id"] or 0) != target_device
            ]

            source_device = int(source_rows[0]["device_id"]) if source_rows else 0
            source_save_prefixes = _source_save_prefixes(source_rows)

            qb_checks: list[dict[str, Any]] = []
            qb_reasons: list[str] = []
            db_reasons: list[str] = []
            source_reasons: list[str] = []
            expected_saves: dict[str, str] = {}

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

                expected_save = _normalize_path(str(row["ti_save_path"] or ""))
                expected_saves[torrent_hash] = expected_save
                info = torrent_snapshot.get(str(torrent_hash).lower())
                if not info:
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
                tag_updates.append((str(getattr(info, "tags", "") or ""), torrent_hash))

                gate = _build_torrent_gate(
                    torrent_hash=torrent_hash,
                    info=info,
                    expected_save=expected_save,
                )

                reconciled_row = row
                if target_device and gate.ok and (
                    int(row["ti_device_id"] or 0) != target_device
                    or int(row["payload_device_id"] or 0) != target_device
                ):
                    target_root = _derive_target_root(row, expected_save)
                    target_payload = _find_target_payload_row(
                        conn,
                        payload_hash=payload_hash,
                        target_device=target_device,
                        target_root=target_root,
                    )
                    if target_payload:
                        conn.execute(
                            """
                            UPDATE torrent_instances
                            SET payload_id = ?,
                                device_id = ?,
                                save_path = ?,
                                last_seen_at = CURRENT_TIMESTAMP
                            WHERE torrent_hash = ?
                            """,
                            (
                                int(target_payload["payload_id"] or 0),
                                target_device,
                                expected_save,
                                torrent_hash,
                            ),
                        )
                        reconciled_row = conn.execute(
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
                            WHERE ti.torrent_hash = ?
                            """,
                            (torrent_hash,),
                        ).fetchone() or row
                        row_by_hash[torrent_hash] = reconciled_row

                if target_device and int(reconciled_row["ti_device_id"] or 0) != target_device:
                    db_reasons.append(f"torrent_device_not_target:{torrent_hash[:12]}")
                if target_device and int(reconciled_row["payload_device_id"] or 0) != target_device:
                    db_reasons.append(f"payload_device_not_target:{torrent_hash[:12]}")
                qb_reasons.extend(gate.reasons)
                qb_checks.append(gate.__dict__)

            cleanup_required = CLEANUP_REQUIRED_TAG in group["tags"]
            cleanup_sources = _load_cleanup_sources(source_rows, payload_hash) if cleanup_required else []
            stale_ref_details: list[dict[str, Any]] = []
            if target_device:
                stale_ref_details = _find_stale_payload_refs(
                    conn,
                    payload_hash=payload_hash,
                    target_device=target_device,
                    source_save_prefixes=source_save_prefixes,
                )
            stale_refs = len(stale_ref_details)
            if stale_refs > 0 and cleanup and cleanup_required:
                db_reasons.append("stale_refs_on_source_payload")
                source_reasons.append("source_has_torrent_refs")

            all_reasons = qb_reasons + db_reasons + source_reasons
            if not all_reasons:
                outcome = "ok"
            elif _is_hard_failure(all_reasons):
                outcome = "failed"
            else:
                outcome = "pending"

            cleanup_disposition, cleanup_disposition_reasons = _classify_cleanup_disposition(
                cleanup_required=cleanup_required,
                cleanup_sources=cleanup_sources,
                outcome=outcome,
                db_reasons=sorted(set(db_reasons)),
                source_reasons=sorted(set(source_reasons)),
                stale_refs=stale_refs,
            )
            if cleanup_disposition == "cleanup_safe_now":
                cleanup_safe_now += 1
            elif cleanup_disposition == "retain_for_rollback":
                cleanup_retain_for_rollback += 1
            elif cleanup_disposition == "blocked_stale_refs":
                cleanup_blocked += 1
            elif cleanup_disposition == "already_cleaned":
                cleanup_already_cleaned += 1
            elif cleanup_disposition == "not_required":
                cleanup_not_required += 1

            cleanup_result = "skipped"
            cleanup_errors: list[str] = []
            deleted_paths: list[str] = []
            staged_paths: list[str] = []
            cleanup_checks: list[dict[str, Any]] = []
            if cleanup and cleanup_disposition == "cleanup_safe_now":
                cleanup_attempted += 1
                cleanup_result, deleted_paths, cleanup_errors, staged_paths, cleanup_checks = _cleanup_sources_with_staging(
                    qbit_client=qbit,
                    payload_hash=payload_hash,
                    candidate_hashes=candidate_hashes,
                    expected_saves=expected_saves,
                    source_rows=cleanup_sources,
                    observe_seconds=cleanup_observe_seconds,
                    poll_seconds=DEFAULT_CLEANUP_POLL_SECONDS,
                )

                if cleanup_result == "done":
                    cleanup_done += 1
                else:
                    cleanup_failed += 1

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
                    "cleanup_staged_paths": staged_paths,
                    "cleanup_errors": cleanup_errors,
                    "cleanup_checks": cleanup_checks,
                    "cleanup_observe_seconds": float(cleanup_observe_seconds),
                    "cleanup_disposition": cleanup_disposition,
                    "cleanup_disposition_reasons": cleanup_disposition_reasons,
                    "cleanup_safe_now": cleanup_disposition == "cleanup_safe_now",
                    "qb_checks": qb_checks,
                    "db_reasons": sorted(set(db_reasons)),
                    "source_reasons": sorted(set(source_reasons)),
                    "stale_ref_details": stale_ref_details,
                }
            )

        if tag_updates:
            conn.executemany(
                """
                UPDATE torrent_instances
                SET tags = ?, last_seen_at = CURRENT_TIMESTAMP
                WHERE torrent_hash = ?
                """,
                tag_updates,
            )
        conn.commit()
        return {
            "checked_at": datetime.now().astimezone().isoformat(),
            "catalog": str(catalog_path),
            "cleanup_requested": bool(cleanup),
            "cleanup_mode": "staged_safe" if cleanup else "skipped",
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
                "cleanup_safe_now": cleanup_safe_now,
                "cleanup_retain_for_rollback": cleanup_retain_for_rollback,
                "cleanup_blocked": cleanup_blocked,
                "cleanup_already_cleaned": cleanup_already_cleaned,
                "cleanup_not_required": cleanup_not_required,
            },
            "entries": entries,
        }
    finally:
        conn.close()
