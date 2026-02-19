#!/usr/bin/env python3
"""Verify and cleanup phase for rehome-safe runs."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from hashall.qbittorrent import get_qbittorrent_client


GOOD_STATES = {"uploading", "stalledup", "queuedup", "forcedup", "pausedup"}


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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_tags(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part and part.strip()}


def _is_qb_ready_state(state: Optional[str]) -> bool:
    if not state:
        return False
    s = str(state).strip().lower()
    if "checking" in s or "moving" in s:
        return False
    if s in {"error", "missingfiles"}:
        return False
    return s in GOOD_STATES


def _expected_save_path(plan: dict[str, Any], torrent_hash: str) -> str:
    targets = plan.get("view_targets") or []
    for row in targets:
        if row.get("torrent_hash") == torrent_hash and row.get("target_save_path"):
            return str(row["target_save_path"])
    target_path = plan.get("target_path")
    if not target_path:
        return ""
    return str(Path(target_path).parent)


def _prune_empty_ancestors(source_path: Path, seeding_roots: list[Path]) -> int:
    removed = 0
    p = source_path.parent
    roots = [r.resolve() for r in seeding_roots]
    while True:
        if not p.exists() or not p.is_dir():
            break
        if any(p == r for r in roots):
            break
        try:
            next(p.iterdir())
            break
        except StopIteration:
            p.rmdir()
            removed += 1
            p = p.parent
        except OSError:
            break
    return removed


def _latest_run_log(run_log_dir: Path) -> Path:
    runs = sorted(run_log_dir.glob("rehome-safe-run-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        raise FileNotFoundError(f"No run logs in {run_log_dir}")
    return runs[0]


def _verify_candidate(
    *,
    conn: sqlite3.Connection,
    qbit,
    candidate: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    payload_hash = str(candidate.get("payload_hash") or "")
    source_path = Path(str(plan.get("source_path") or ""))
    source_device_id = int(plan.get("source_device_id") or 0)
    target_device_id = int(plan.get("target_device_id") or 0)
    affected = list(plan.get("affected_torrents") or [])

    torrent_gates: list[TorrentGate] = []
    for th in affected:
        reasons: list[str] = []
        info = qbit.get_torrent_info(th)
        if not info:
            torrent_gates.append(
                TorrentGate(th, False, ["missing_in_qbit"], None, None, None, None, None)
            )
            continue

        progress = float(getattr(info, "progress", 0.0))
        state = str(getattr(info, "state", ""))
        auto_tmm = bool(getattr(info, "auto_tmm", False))
        save_path = str(getattr(info, "save_path", ""))
        tags = str(getattr(info, "tags", ""))

        if progress < 0.9999:
            reasons.append("progress_below_100")
        if not _is_qb_ready_state(state):
            reasons.append("state_not_ready")
        if auto_tmm:
            reasons.append("auto_tmm_enabled")
        exp_save = _expected_save_path(plan, th)
        if exp_save and str(Path(save_path).resolve()) != str(Path(exp_save).resolve()):
            reasons.append("save_path_mismatch")
        tag_set = _split_tags(tags)
        required = {"rehome", "rehome_from_stash", "rehome_to_pool"}
        if not required.issubset(tag_set):
            reasons.append("missing_rehome_tags")
        if not any(tag.startswith("rehome_at_") for tag in tag_set):
            reasons.append("missing_rehome_at_tag")

        torrent_gates.append(
            TorrentGate(th, len(reasons) == 0, reasons, progress, state, auto_tmm, save_path, tags)
        )

    db_reasons: list[str] = []
    for th in affected:
        row = conn.execute(
            """
            SELECT ti.device_id, ti.save_path, p.device_id, p.payload_hash
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE ti.torrent_hash = ?
            """,
            (th,),
        ).fetchone()
        if not row:
            db_reasons.append(f"missing_torrent_instance:{th[:12]}")
            continue
        ti_device, ti_save, payload_device, payload_hash_row = row
        if int(ti_device or 0) != target_device_id:
            db_reasons.append(f"torrent_device_not_target:{th[:12]}")
        if int(payload_device or 0) != target_device_id:
            db_reasons.append(f"payload_device_not_target:{th[:12]}")
        if str(payload_hash_row or "") != payload_hash:
            db_reasons.append(f"payload_hash_mismatch:{th[:12]}")
        exp_save = _expected_save_path(plan, th)
        if exp_save and str(Path(str(ti_save or "")).resolve()) != str(Path(exp_save).resolve()):
            db_reasons.append(f"db_save_path_mismatch:{th[:12]}")

    stale_refs = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE p.payload_hash = ? AND p.device_id = ?
            """,
            (payload_hash, source_device_id),
        ).fetchone()[0]
        or 0
    )
    if stale_refs > 0:
        db_reasons.append("stale_refs_on_source_payload")

    source_exists = bool(source_path and source_path.exists())
    source_refs = int(candidate.get("cleanup_backlog", {}).get("source_torrent_refs", 0) or 0)
    source_reasons: list[str] = []
    if source_refs != 0:
        source_reasons.append("source_has_torrent_refs")

    qb_ok = all(g.ok for g in torrent_gates)
    db_ok = len(db_reasons) == 0
    source_ok = len(source_reasons) == 0
    ready_for_cleanup = qb_ok and db_ok and source_ok

    return {
        "payload_hash": payload_hash,
        "plan_path": candidate.get("plan_path"),
        "decision": plan.get("decision"),
        "source_path": str(source_path),
        "source_exists": source_exists,
        "stale_source_refs": stale_refs,
        "qb_ok": qb_ok,
        "db_ok": db_ok,
        "source_ok": source_ok,
        "ready_for_cleanup": ready_for_cleanup,
        "qb_checks": [g.__dict__ for g in torrent_gates],
        "db_reasons": db_reasons,
        "source_reasons": source_reasons,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify and cleanup rehome-safe run")
    p.add_argument("--run-log", help="Path to rehome-safe-run-*.json (defaults to latest)")
    p.add_argument("--run-log-dir", default="out/reports/rehome-safe-runs")
    p.add_argument("--db", help="Override DB path (defaults to run-log db)")
    p.add_argument("--cleanup", action="store_true", help="Delete source paths for verified-clean groups")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any group is not ready")
    p.add_argument("--output", help="Write verification report JSON")
    p.add_argument(
        "--print-torrents",
        action="store_true",
        help="Print per-torrent gate details to stdout",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    run_log_path = Path(args.run_log) if args.run_log else _latest_run_log(Path(args.run_log_dir))
    run_log = _load_json(run_log_path)
    db_path = Path(args.db) if args.db else Path(str(run_log.get("db")))

    qbit = get_qbittorrent_client()
    if not qbit.test_connection() or not qbit.login():
        print("ERROR: qB connection/login failed", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    try:
        entries: list[dict[str, Any]] = []
        for cand in run_log.get("candidates", []):
            plan_path = Path(str(cand.get("plan_path", "")))
            if not plan_path.exists():
                entries.append(
                    {
                        "payload_hash": cand.get("payload_hash"),
                        "plan_path": str(plan_path),
                        "ready_for_cleanup": False,
                        "error": "missing_plan_file",
                    }
                )
                continue
            plan = _load_json(plan_path)
            entries.append(_verify_candidate(conn=conn, qbit=qbit, candidate=cand, plan=plan))
    finally:
        conn.close()

    cleanup_deleted = 0
    cleanup_pruned_dirs = 0
    if args.cleanup:
        for entry in entries:
            if not entry.get("ready_for_cleanup"):
                continue
            source_path = Path(str(entry.get("source_path") or ""))
            if not source_path.exists():
                continue
            if source_path.is_dir():
                shutil.rmtree(source_path)
            else:
                source_path.unlink()
            cleanup_deleted += 1

            # Prune empty ancestors under seeding roots from plan.
            plan = _load_json(Path(str(entry["plan_path"])))
            seeding_roots = [Path(p) for p in (plan.get("seeding_roots") or [])]
            cleanup_pruned_dirs += _prune_empty_ancestors(source_path, seeding_roots)

    ready = sum(1 for e in entries if e.get("ready_for_cleanup"))
    pending = len(entries) - ready
    report = {
        "run_log": str(run_log_path),
        "run_mode": run_log.get("mode"),
        "db": str(db_path),
        "checked_at": datetime.now().astimezone().isoformat(),
        "cleanup_requested": bool(args.cleanup),
        "summary": {
            "groups_total": len(entries),
            "groups_ready": ready,
            "groups_pending": pending,
            "cleanup_deleted_sources": cleanup_deleted,
            "cleanup_pruned_dirs": cleanup_pruned_dirs,
        },
        "entries": entries,
    }

    if args.output:
        output_path = Path(args.output)
    else:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        output_path = Path(args.run_log_dir) / f"rehome-safe-verify-{stamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"verify_report={output_path}")
    print(
        "summary="
        f"total:{len(entries)} ready:{ready} pending:{pending} "
        f"cleanup_deleted:{cleanup_deleted} pruned_dirs:{cleanup_pruned_dirs}"
    )
    for entry in entries:
        payload = str(entry.get("payload_hash", ""))[:16]
        print(
            "payload="
            f"{payload} "
            f"ready={str(bool(entry.get('ready_for_cleanup'))).lower()} "
            f"qb_ok={str(bool(entry.get('qb_ok'))).lower()} "
            f"db_ok={str(bool(entry.get('db_ok'))).lower()} "
            f"source_ok={str(bool(entry.get('source_ok'))).lower()} "
            f"source_exists={str(bool(entry.get('source_exists'))).lower()}"
        )
        if entry.get("db_reasons"):
            print("  db_reasons=" + ",".join(entry["db_reasons"]))
        if entry.get("source_reasons"):
            print("  source_reasons=" + ",".join(entry["source_reasons"]))
        if args.print_torrents:
            for gate in entry.get("qb_checks", []):
                reasons = gate.get("reasons") or []
                reason_text = ",".join(reasons) if reasons else "none"
                print(
                    "  torrent="
                    f"{str(gate.get('torrent_hash', ''))[:16]} "
                    f"ok={str(bool(gate.get('ok'))).lower()} "
                    f"progress={gate.get('progress')} "
                    f"state={gate.get('state')} "
                    f"auto_tmm={gate.get('auto_tmm')} "
                    f"reasons={reason_text}"
                )

    if args.strict and pending > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
