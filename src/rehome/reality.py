"""Live reality snapshots for rehome plans.

This module builds a low-trust view of the current world for a planned
payload-group relocation by comparing:

- qBittorrent runtime state
- qB fastresume paths
- catalog payload / torrent-instance rows
- expected target views from the plan
- actual filesystem existence at source/target
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from hashall.bencode import as_text
from hashall.fastresume import normalize_save_path, read_fastresume


TRANSIENT_STATE_MARKERS = ("checking", "moving", "allocating")
DEFAULT_FASTRESUME_DIR = Path(
    "/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
)


def _ts_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_path(path: Any) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        return normalize_save_path(raw)
    except Exception:
        return raw.rstrip("/") or raw


def _safe_exists(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:
        return False


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1] or "")
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        if len(row) > 1
    }


def _read_fastresume_fields(fastresume_dir: Optional[Path], torrent_hash: str) -> Dict[str, Any]:
    if fastresume_dir is None:
        return {
            "fastresume_path": "",
            "fastresume_exists": False,
            "fastresume_save_path": "",
            "fastresume_qbt_save_path": "",
            "fastresume_qbt_download_path": "",
        }
    fastresume_path = Path(fastresume_dir) / f"{torrent_hash}.fastresume"
    if not fastresume_path.exists():
        return {
            "fastresume_path": str(fastresume_path),
            "fastresume_exists": False,
            "fastresume_save_path": "",
            "fastresume_qbt_save_path": "",
            "fastresume_qbt_download_path": "",
        }
    try:
        payload = read_fastresume(fastresume_path)
        return {
            "fastresume_path": str(fastresume_path),
            "fastresume_exists": True,
            "fastresume_save_path": _normalize_path(as_text(payload.get(b"save_path", b""))),
            "fastresume_qbt_save_path": _normalize_path(as_text(payload.get(b"qBt-savePath", b""))),
            "fastresume_qbt_download_path": _normalize_path(
                as_text(payload.get(b"qBt-downloadPath", b""))
            ),
        }
    except Exception as exc:
        return {
            "fastresume_path": str(fastresume_path),
            "fastresume_exists": "error",
            "fastresume_error": str(exc),
            "fastresume_save_path": "",
            "fastresume_qbt_save_path": "",
            "fastresume_qbt_download_path": "",
        }


def _derive_expected_content_path(save_path: str, root_name: str, fallback: str) -> str:
    save = _normalize_path(save_path)
    root = str(root_name or "").strip()
    if save and root:
        return str(Path(save) / root)
    return _normalize_path(fallback)


def _catalog_rows_by_hash(
    catalog_path: Optional[Path],
    torrent_hashes: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    hashes = [str(item or "").strip().lower() for item in torrent_hashes if str(item or "").strip()]
    if not catalog_path or not hashes:
        return {}

    uri = f"file:{Path(catalog_path).expanduser().resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ti_columns = _table_columns(conn, "torrent_instances")
        save_path_expr = "ti.save_path" if "save_path" in ti_columns else "''"
        tags_expr = "ti.tags" if "tags" in ti_columns else "''"
        ti_device_expr = "ti.device_id" if "device_id" in ti_columns else "0"
        placeholders = ",".join("?" for _ in hashes)
        rows = conn.execute(
            f"""
            SELECT lower(ti.torrent_hash) AS torrent_hash,
                   {save_path_expr} AS ti_save_path,
                   {tags_expr} AS ti_tags,
                   {ti_device_expr} AS ti_device_id,
                   p.payload_id,
                   p.payload_hash,
                   p.device_id AS payload_device_id,
                   p.root_path AS payload_root_path,
                   p.status AS payload_status
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) IN ({placeholders})
            """,
            hashes,
        ).fetchall()
        return {
            str(row["torrent_hash"] or "").strip().lower(): {
                "catalog_ti_save_path": _normalize_path(row["ti_save_path"]),
                "catalog_ti_tags": str(row["ti_tags"] or ""),
                "catalog_ti_device_id": int(row["ti_device_id"] or 0),
                "catalog_payload_id": int(row["payload_id"] or 0),
                "catalog_payload_hash": str(row["payload_hash"] or ""),
                "catalog_payload_device_id": int(row["payload_device_id"] or 0),
                "catalog_payload_root_path": _normalize_path(row["payload_root_path"]),
                "catalog_payload_status": str(row["payload_status"] or ""),
            }
            for row in rows
        }
    finally:
        conn.close()


def _catalog_payload_group_members(
    catalog_path: Optional[Path],
    payload_hash: str,
) -> List[Dict[str, Any]]:
    payload_hash = str(payload_hash or "").strip()
    if not catalog_path or not payload_hash:
        return []

    uri = f"file:{Path(catalog_path).expanduser().resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ti_columns = _table_columns(conn, "torrent_instances")
        save_path_expr = "ti.save_path" if "save_path" in ti_columns else "''"
        ti_device_expr = "ti.device_id" if "device_id" in ti_columns else "0"
        rows = conn.execute(
            f"""
            SELECT lower(ti.torrent_hash) AS torrent_hash,
                   {save_path_expr} AS ti_save_path,
                   {ti_device_expr} AS ti_device_id,
                   p.payload_id AS payload_id,
                   p.root_path AS payload_root_path,
                   p.device_id AS payload_device_id
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE p.payload_hash = ?
            ORDER BY lower(ti.torrent_hash)
            """,
            (payload_hash,),
        ).fetchall()
        return [
            {
                "torrent_hash": str(row["torrent_hash"] or "").strip().lower(),
                "catalog_ti_save_path": _normalize_path(row["ti_save_path"]),
                "catalog_ti_device_id": int(row["ti_device_id"] or 0),
                "catalog_payload_id": int(row["payload_id"] or 0),
                "catalog_payload_root_path": _normalize_path(row["payload_root_path"]),
                "catalog_payload_device_id": int(row["payload_device_id"] or 0),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _qb_out_of_plan_siblings(
    *,
    plan: Dict[str, Any],
    qb_client: Any,
    affected_hashes: set[str],
    catalog_sibling_hashes: set[str],
    matched_names: Iterable[str],
) -> List[Dict[str, Any]]:
    """
    Find qB-visible sibling candidates that are not covered by the current plan.

    These rows are especially important when older rehome waves left behind
    qB-only stale references that the current catalog no longer ties to the
    active payload hash. Match conservatively on exact name plus exact size.
    """
    try:
        torrents = list(qb_client.get_torrents() or [])
    except Exception:
        return []

    names = {str(name or "").strip() for name in matched_names if str(name or "").strip()}
    size_hint = int(plan.get("total_bytes") or 0)
    uncovered: List[Dict[str, Any]] = []
    for info in torrents:
        torrent_hash = str(getattr(info, "hash", "") or "").strip().lower()
        if not torrent_hash:
            continue
        if torrent_hash in affected_hashes or torrent_hash in catalog_sibling_hashes:
            continue

        name = str(getattr(info, "name", "") or "").strip()
        if names and name not in names:
            continue

        try:
            size = int(getattr(info, "size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        if size_hint and size and size != size_hint:
            continue

        try:
            progress = float(getattr(info, "progress", 0.0) or 0.0)
        except (TypeError, ValueError):
            progress = 0.0
        uncovered.append(
            {
                "torrent_hash": torrent_hash,
                "qbit_name": name,
                "qbit_state": str(getattr(info, "state", "") or ""),
                "qbit_progress": progress,
                "qbit_save_path": _normalize_path(getattr(info, "save_path", "")),
                "qbit_content_path": _normalize_path(getattr(info, "content_path", "")),
                "qbit_size": size,
            }
        )

    uncovered.sort(key=lambda row: (str(row.get("qbit_name") or ""), str(row.get("torrent_hash") or "")))
    return uncovered


def _classify_row(row: Dict[str, Any], *, phase: str = "pre") -> tuple[str, str, str]:
    qbit_state = str(row.get("qbit_state") or "").strip().lower()
    qbit_progress = float(row.get("qbit_progress") or 0.0)
    qbit_save = _normalize_path(row.get("qbit_save_path"))
    fastresume_save = _normalize_path(row.get("fastresume_qbt_save_path") or row.get("fastresume_save_path"))
    catalog_save = _normalize_path(row.get("catalog_ti_save_path"))
    catalog_root = _normalize_path(row.get("catalog_payload_root_path"))
    expected_target_save = _normalize_path(row.get("expected_target_save_path"))
    expected_target_content = _normalize_path(row.get("expected_target_content_path"))
    expected_source_save = _normalize_path(row.get("expected_source_save_path"))
    target_exists = bool(row.get("target_content_exists"))
    source_exists = bool(row.get("source_content_exists"))
    catalog_on_target = expected_target_save and catalog_save == expected_target_save
    payload_on_target = expected_target_content and catalog_root == expected_target_content
    qbit_on_target = expected_target_save and qbit_save == expected_target_save
    qbit_on_source = expected_source_save and qbit_save == expected_source_save
    fr_on_target = expected_target_save and fastresume_save == expected_target_save
    fr_on_source = expected_source_save and fastresume_save == expected_source_save

    if not bool(row.get("qbit_present")):
        return (
            "qbit_missing",
            "qB does not currently expose this torrent, so rehome cannot safely trust any cached path state for it.",
            "Confirm the torrent still exists in qB before trying to migrate or clean up this payload group.",
        )

    if any(marker in qbit_state for marker in TRANSIENT_STATE_MARKERS):
        if phase == "post" and qbit_on_target and fr_on_target and target_exists:
            return (
                "post_apply_settling",
                "qB is still settling on the already-repointed target view immediately after apply.",
                "Wait for qB to finish its post-apply checks before treating this row as drift.",
            )
        return (
            "qbit_transient",
            "qB is actively checking or moving this torrent right now, so its current state is still in flux.",
            "Wait for qB to settle before re-running this plan.",
        )

    if qbit_progress < 0.9999 and qbit_state != "missingfiles":
        return (
            "incomplete_torrent",
            "qB does not currently consider this torrent complete, so the migration lane should treat it as repair work instead of a clean move.",
            "Repair or recheck the torrent first, then retry migration once it is back at 100%.",
        )

    if qbit_on_target and fr_on_target:
        if catalog_on_target and payload_on_target:
            return (
                "aligned_target",
                "qB, fastresume, and the catalog already agree on the new target location.",
                "No relocation is needed; this row is already converged.",
            )
        return (
            "catalog_drift_already_targeted",
            "qB and fastresume already point at the new target, but the catalog still reflects older state.",
            "Run catalog reconcile only; do not rebuild or recopy this payload.",
        )

    if qbit_on_source and fr_on_source and target_exists:
        return (
            "stale_runtime_and_fastresume_root",
            "The good target view exists, but both qB and fastresume are still pointing at the old source root.",
            "Safe reconnect/repoint candidate: patch fastresume and qB to the target view, then reconcile the catalog.",
        )

    if (
        target_exists
        and catalog_on_target
        and qbit_save
        and fastresume_save
        and qbit_save == fastresume_save
        and qbit_save != expected_target_save
    ):
        return (
            "stale_runtime_and_fastresume_root",
            "The good target view exists and the catalog already points there, but qB and fastresume are still stuck on an older runtime root.",
            "Safe reconnect/repoint candidate: patch fastresume and qB to the target view, then reconcile the catalog.",
        )

    if qbit_on_source and target_exists:
        return (
            "stale_runtime_root",
            "The destination view exists, but qB is still using the old source save path.",
            "Repoint qB to the target view and then reconcile the catalog.",
        )

    if fr_on_source and qbit_on_target:
        return (
            "stale_fastresume_root",
            "qB is already on the target, but fastresume still remembers the old source path.",
            "Patch the fastresume path fields before a future qB restart turns this back into drift.",
        )

    if qbit_on_source and source_exists and not target_exists:
        return (
            "source_only",
            "This torrent is still only backed by the old source payload; no target copy/view is ready yet.",
            "Copy or build the target payload/view first, then repoint the torrent.",
        )

    if expected_target_content and not target_exists:
        return (
            "target_view_missing",
            "The new destination view that this torrent expects does not exist yet in the required shape.",
            "Build or repair the target view before attempting to repoint this torrent.",
        )

    return (
        "mixed_drift",
        "The runtime, fastresume, catalog, and filesystem state disagree in a way that does not match a known safe pattern.",
        "Stop and inspect this payload group before applying or cleaning up anything.",
    )


def _summarize_group(rows: List[Dict[str, Any]], *, phase: str = "pre") -> tuple[str, str]:
    states = Counter(str(row.get("classification") or "") for row in rows)
    if not rows:
        return ("empty", "No rows were present in the reality snapshot.")
    if phase == "post" and set(states).issubset(
        {"aligned_target", "catalog_drift_already_targeted", "post_apply_settling"}
    ):
        return (
            "settling_after_apply",
            "The group is already on the target and qB is only doing short post-apply checks.",
        )
    if states.get("qbit_transient"):
        return (
            "blocked_qbit_transient",
            "One or more torrents are still in a qB checking/moving state, so the group should be retried later.",
        )
    if states.get("incomplete_torrent"):
        return (
            "blocked_incomplete",
            "At least one torrent is not fully complete in qB, so the group should be treated as repair work instead of a clean migration.",
        )
    if states.get("target_view_missing"):
        return (
            "blocked_target_view_missing",
            "At least one torrent still lacks the destination view shape it expects, so the group is not yet safe to repoint.",
        )
    if states.get("mixed_drift") or states.get("qbit_missing"):
        return (
            "mixed_attention_required",
            "The group contains rows whose live state does not match any known safe migration pattern.",
        )
    if set(states).issubset({"aligned_target", "catalog_drift_already_targeted"}):
        return (
            "ready_catalog_reconcile",
            "All rows are already physically aligned on the target; only catalog reconciliation remains.",
        )
    if set(states).issubset(
        {
            "aligned_target",
            "catalog_drift_already_targeted",
            "stale_runtime_and_fastresume_root",
            "stale_runtime_root",
            "stale_fastresume_root",
            "source_only",
        }
    ):
        return (
            "ready_repoint_or_reconcile",
            "The group matches a known safe relocation pattern and can be repointed or reconciled once the missing target views are resolved.",
        )
    return (
        "mixed_attention_required",
        "The group needs manual review before apply/cleanup because its rows do not all point at the same safe migration state.",
    )


def build_plan_reality_snapshot(
    *,
    plan: Dict[str, Any],
    qb_client: Any,
    catalog_path: Optional[Path] = None,
    fastresume_dir: Optional[Path] = None,
    phase: str = "pre",
) -> Dict[str, Any]:
    affected = [
        str(torrent_hash or "").strip().lower()
        for torrent_hash in (plan.get("affected_torrents") or [])
        if str(torrent_hash or "").strip()
    ]
    catalog_rows = _catalog_rows_by_hash(catalog_path, affected)
    payload_group_members = _catalog_payload_group_members(catalog_path, plan.get("payload_hash") or "")
    view_targets = {
        str(target.get("torrent_hash") or "").strip().lower(): dict(target)
        for target in (plan.get("view_targets") or [])
        if str(target.get("torrent_hash") or "").strip()
    }

    rows: List[Dict[str, Any]] = []
    for torrent_hash in affected:
        target = view_targets.get(torrent_hash, {})
        info = qb_client.get_torrent_info(torrent_hash)
        qbit_present = info is not None
        qbit_name = str(getattr(info, "name", "") or "") if info is not None else ""
        qbit_state = str(getattr(info, "state", "") or "") if info is not None else ""
        progress_raw = getattr(info, "progress", 0.0) if info is not None else 0.0
        try:
            qbit_progress = float(progress_raw or 0.0)
        except (TypeError, ValueError):
            qbit_progress = 0.0
        qbit_save_path = _normalize_path(getattr(info, "save_path", "") if info is not None else "")
        qbit_content_path = _normalize_path(getattr(info, "content_path", "") if info is not None else "")

        expected_target_save_path = _normalize_path(target.get("target_save_path") or "")
        source_fallback = str(target.get("source_save_path") or "").strip()
        if not source_fallback:
            source_path = str(plan.get("source_path") or "").strip()
            source_fallback = str(Path(source_path).parent) if source_path else ""
        expected_source_save_path = _normalize_path(source_fallback)
        root_name = str(target.get("root_name") or Path(str(plan.get("target_path") or "")).name)
        expected_target_content_path = _derive_expected_content_path(
            expected_target_save_path,
            root_name,
            str(plan.get("target_path") or ""),
        )
        expected_source_content_path = _derive_expected_content_path(
            expected_source_save_path,
            root_name,
            str(plan.get("source_path") or ""),
        )

        row: Dict[str, Any] = {
            "torrent_hash": torrent_hash,
            "name": qbit_name,
            "decision": str(plan.get("decision") or ""),
            "qbit_present": qbit_present,
            "qbit_state": qbit_state,
            "qbit_progress": qbit_progress,
            "qbit_save_path": qbit_save_path,
            "qbit_content_path": qbit_content_path,
            "expected_source_save_path": expected_source_save_path,
            "expected_target_save_path": expected_target_save_path,
            "expected_source_content_path": expected_source_content_path,
            "expected_target_content_path": expected_target_content_path,
            "expected_root_name": root_name,
            "source_content_exists": _safe_exists(expected_source_content_path),
            "target_content_exists": _safe_exists(expected_target_content_path),
        }
        row.update(catalog_rows.get(torrent_hash, {}))
        row.update(_read_fastresume_fields(fastresume_dir, torrent_hash))
        classification, operator_reason, operator_action = _classify_row(row, phase=phase)
        row["classification"] = classification
        row["operator_reason"] = operator_reason
        row["operator_action"] = operator_action
        rows.append(row)

    summary_counts = Counter(str(row.get("classification") or "") for row in rows)
    affected_set = set(affected)
    sibling_members = [member for member in payload_group_members if member.get("torrent_hash")]
    payload_id_counts = Counter(
        int(member.get("catalog_payload_id") or 0)
        for member in sibling_members
        if int(member.get("catalog_payload_id") or 0) > 0
    )
    shared_payload_members = [
        member
        for member in sibling_members
        if int(member.get("catalog_payload_id") or 0) > 0
        and payload_id_counts[int(member.get("catalog_payload_id") or 0)] > 1
    ]
    shared_payload_rows = sum(1 for count in payload_id_counts.values() if count > 1)
    uncovered_catalog_members = [
        member for member in sibling_members if member["torrent_hash"] not in affected_set
    ]
    catalog_sibling_hashes = {
        str(member.get("torrent_hash") or "").strip().lower()
        for member in sibling_members
        if str(member.get("torrent_hash") or "").strip()
    }
    matched_names = {
        str(row.get("name") or "").strip()
        for row in rows
        if str(row.get("name") or "").strip()
    }
    expected_root_name = str(
        Path(str(plan.get("target_path") or plan.get("source_path") or "")).name
    ).strip()
    if expected_root_name:
        matched_names.add(expected_root_name)
    uncovered_qbit_members = _qb_out_of_plan_siblings(
        plan=plan,
        qb_client=qb_client,
        affected_hashes=affected_set,
        catalog_sibling_hashes=catalog_sibling_hashes,
        matched_names=matched_names,
    )
    uncovered_members = uncovered_catalog_members + uncovered_qbit_members
    group_warnings: List[str] = []
    if uncovered_catalog_members:
        sample_hashes = ",".join(member["torrent_hash"][:16] for member in uncovered_catalog_members[:5])
        group_warnings.append(
            "Catalog still has "
            f"{len(uncovered_catalog_members)} out-of-plan sibling torrent(s) for this payload hash; "
            "full cleanup/convergence should wait until they are audited too "
            f"(sample={sample_hashes})."
        )
    if uncovered_qbit_members:
        sample_hashes = ",".join(member["torrent_hash"][:16] for member in uncovered_qbit_members[:5])
        group_warnings.append(
            "qB still has "
            f"{len(uncovered_qbit_members)} same-name out-of-plan torrent(s) that match this payload's size; "
            "moving only the selected row could strand those stale sibling refs "
            f"(sample={sample_hashes})."
        )
    if shared_payload_rows:
        sample_hashes = ",".join(member["torrent_hash"][:16] for member in shared_payload_members[:5])
        group_warnings.append(
            "Catalog still groups "
            f"{len(shared_payload_members)} torrent(s) for this payload hash into "
            f"{shared_payload_rows} shared payload row(s); newly constructed migrations should "
            "de-hitchhike these hashes into unique target payload roots "
            f"(sample={sample_hashes})."
        )
    group_state, group_reason = _summarize_group(rows, phase=phase)
    if uncovered_qbit_members and phase == "pre":
        group_state = "blocked_qbit_sibling_gap"
        group_reason = (
            "qB still has same-name sibling torrents outside this plan, so the migration should not mutate a "
            "partial view until those stale refs are audited or reconnected."
        )
    return {
        "generated_at": _ts_iso(),
        "phase": phase,
        "payload_hash": str(plan.get("payload_hash") or ""),
        "decision": str(plan.get("decision") or ""),
        "direction": str(plan.get("direction") or ""),
        "source_path": _normalize_path(plan.get("source_path")),
        "target_path": _normalize_path(plan.get("target_path")),
        "group_state": group_state,
        "group_reason": group_reason,
        "summary": {
            "rows": len(rows),
            "classifications": dict(summary_counts),
            "payload_group_siblings": len(sibling_members),
            "plan_rows": len(affected),
            "out_of_plan_siblings": len(uncovered_members),
            "catalog_out_of_plan_siblings": len(uncovered_catalog_members),
            "qbit_out_of_plan_siblings": len(uncovered_qbit_members),
            "shared_payload_rows": shared_payload_rows,
            "shared_payload_torrents": len(shared_payload_members),
        },
        "group_warnings": group_warnings,
        "out_of_plan_siblings": uncovered_members,
        "out_of_plan_catalog_siblings": uncovered_catalog_members,
        "out_of_plan_qbit_siblings": uncovered_qbit_members,
        "shared_payload_members": shared_payload_members,
        "rows": rows,
    }
