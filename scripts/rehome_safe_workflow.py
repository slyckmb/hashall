#!/usr/bin/env python3
"""Run safe stash->pool rehomes for fully movable payload groups."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from hashall.model import connect_db
from hashall.status_report import build_status_report


@dataclass(frozen=True)
class Candidate:
    payload_hash: str
    movable_bytes: int
    movable_pct_bytes: float
    recommendation: str


def _under_root(path: str, root: str) -> bool:
    norm_path = str(Path(path).resolve())
    norm_root = str(Path(root).resolve())
    return norm_path == norm_root or norm_path.startswith(norm_root.rstrip("/") + "/")


def _safe_candidates(groups: Iterable[dict], *, limit: int) -> list[Candidate]:
    picks: list[Candidate] = []
    for row in groups:
        try:
            payload_hash = str(row.get("payload_hash") or "").strip()
            recommendation = str(row.get("recommendation") or "").strip().upper()
            movable_bytes = int(row.get("movable_bytes") or 0)
            movable_pct_bytes = float(row.get("movable_pct_bytes") or 0.0)
        except (TypeError, ValueError):
            continue

        if not payload_hash:
            continue
        if recommendation != "MOVE":
            continue
        if movable_bytes <= 0:
            continue
        if movable_pct_bytes < 0.999999:
            continue

        picks.append(
            Candidate(
                payload_hash=payload_hash,
                movable_bytes=movable_bytes,
                movable_pct_bytes=movable_pct_bytes,
                recommendation=recommendation,
            )
        )

    picks.sort(key=lambda item: item.movable_bytes, reverse=True)
    return picks[: max(1, limit)]


def _run(cmd: list[str], *, env: dict[str, str], dry_run: bool) -> int:
    print(" -> " + " ".join(cmd))
    if dry_run:
        print("    (dry-run skipped)")
        return 0
    result = subprocess.run(cmd, env=env)
    return int(result.returncode)


def _cleanup_backlog(
    *,
    db_path: Path,
    payload_hash: str,
    source_path: str | None,
    seeding_root: str,
    stash_device: int,
    pool_device: int,
) -> dict:
    conn = connect_db(db_path, read_only=True, apply_migrations=False)
    try:
        rows = conn.execute(
            """
            SELECT payload_id, root_path, device_id, status
            FROM payloads
            WHERE payload_hash = ? AND status = 'complete'
            """,
            (payload_hash,),
        ).fetchall()
        stash_rows = [row for row in rows if int(row[2]) == int(stash_device)]
        pool_rows = [row for row in rows if int(row[2]) == int(pool_device)]
        stash_in_seed = [row for row in stash_rows if _under_root(str(row[1]), seeding_root)]

        source_exists = bool(source_path and Path(source_path).exists())
        source_catalog_rows = 0
        source_with_refs = 0
        if source_path:
            source_catalog_rows = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM payloads
                    WHERE payload_hash = ? AND status = 'complete' AND root_path = ?
                    """,
                    (payload_hash, source_path),
                ).fetchone()[0]
                or 0
            )
            source_with_refs = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM payloads p
                    JOIN torrent_instances t ON t.payload_id = p.payload_id
                    WHERE p.payload_hash = ?
                      AND p.status = 'complete'
                      AND p.root_path = ?
                    """,
                    (payload_hash, source_path),
                ).fetchone()[0]
                or 0
            )

        return {
            "pool_rows": len(pool_rows),
            "stash_rows": len(stash_rows),
            "stash_rows_under_seeding_root": len(stash_in_seed),
            "source_path": source_path,
            "source_exists": source_exists,
            "source_catalog_rows": source_catalog_rows,
            "source_torrent_refs": source_with_refs,
            "cleanup_needed": bool(source_exists or source_with_refs > 0 or len(stash_in_seed) > 0),
        }
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe rehome workflow for 100% movable groups")
    parser.add_argument("--db", required=True, help="Catalog DB path")
    parser.add_argument("--roots", default="/pool/data,/stash/media,/data/media")
    parser.add_argument("--media-root", default="/data/media")
    parser.add_argument("--recovery-prefix", default="/data/media/torrents/seeding/recovery_20260211")
    parser.add_argument("--top", type=int, default=15, help="Status report group depth")
    parser.add_argument("--limit", type=int, default=5, help="How many safe groups to process")
    parser.add_argument("--seeding-root", default="/stash/media")
    parser.add_argument("--library-root", default="/stash/media")
    parser.add_argument("--stash-device", required=True,
                        help="Device alias (e.g. 'stash') or integer device_id")
    parser.add_argument("--pool-device", required=True,
                        help="Device alias (e.g. 'pool') or integer device_id")
    parser.add_argument("--out-dir", default=str(Path.home() / ".logs/hashall/reports/rehome-plans"))
    parser.add_argument("--run-log-dir", default=str(Path.home() / ".logs/hashall/reports/rehome-safe-runs"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute apply after dry-run; otherwise dry-run only",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    conn = connect_db(db_path, read_only=True, apply_migrations=False)
    try:
        from hashall.device import resolve_device_id
        try:
            args.stash_device = resolve_device_id(conn, args.stash_device)
            args.pool_device = resolve_device_id(conn, args.pool_device)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        report = build_status_report(
            conn,
            roots_arg=args.roots,
            media_root=args.media_root,
            pocket_depth=2,
            top_n=max(args.top, args.limit),
            recovery_prefix=args.recovery_prefix,
        )
    finally:
        conn.close()

    picks = _safe_candidates(report.get("rehome_impact_groups", []), limit=args.limit)
    print(
        "Safe candidates: "
        f"{len(picks)} (MOVE + 100% movable by bytes), "
        f"requested limit={args.limit}"
    )
    if not picks:
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[1]
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}" if existing_pythonpath else src_path

    run_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    py = sys.executable
    plan_success = 0
    dry_success = 0
    apply_success = 0
    run_log: dict = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "db": str(db_path),
        "roots": args.roots,
        "mode": "apply" if args.apply else "dryrun",
        "limit": int(args.limit),
        "candidates": [],
    }
    cleanup_needed_count = 0

    for idx, candidate in enumerate(picks, start=1):
        hash16 = candidate.payload_hash[:16]
        plan_path = out_dir / f"rehome-safe-{run_id}-{idx:02d}-{hash16}.json"
        print(
            f"[{idx}/{len(picks)}] payload={hash16} "
            f"movable={candidate.movable_bytes}B"
        )
        candidate_log = {
            "index": idx,
            "payload_hash": candidate.payload_hash,
            "movable_bytes": int(candidate.movable_bytes),
            "movable_pct_bytes": float(candidate.movable_pct_bytes),
            "plan_path": str(plan_path),
            "plan_rc": None,
            "decision": None,
            "dryrun_rc": None,
            "apply_rc": None,
            "cleanup_backlog": None,
            "cleanup_command": (
                f"make rehome-apply REHOME_PLAN='{plan_path}' "
                "REHOME_CLEANUP_SOURCE_VIEWS=1 REHOME_CLEANUP_EMPTY_DIRS=1"
            ),
        }

        plan_cmd = [
            py,
            "-m",
            "rehome.cli",
            "plan",
            "--demote",
            "--payload-hash",
            candidate.payload_hash,
            "--catalog",
            str(db_path),
            "--seeding-root",
            args.seeding_root,
            "--library-root",
            args.library_root,
            "--cross-seed-config",
            "/dev/null",
            "--tracker-registry",
            "/dev/null",
            "--stash-device",
            str(args.stash_device),
            "--pool-device",
            str(args.pool_device),
            "--output",
            str(plan_path),
        ]
        rc = _run(plan_cmd, env=env, dry_run=False)
        candidate_log["plan_rc"] = int(rc)
        if rc != 0:
            print(f"   plan failed rc={rc}")
            run_log["candidates"].append(candidate_log)
            continue
        plan_success += 1

        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print("   plan parse failed")
            continue

        decision = str(plan.get("decision", "BLOCK")).upper()
        candidate_log["decision"] = decision
        if decision not in {"MOVE", "REUSE"}:
            print(f"   skipped decision={decision}")
            candidate_log["cleanup_backlog"] = _cleanup_backlog(
                db_path=db_path,
                payload_hash=candidate.payload_hash,
                source_path=plan.get("source_path"),
                seeding_root=args.seeding_root,
                stash_device=args.stash_device,
                pool_device=args.pool_device,
            )
            if candidate_log["cleanup_backlog"]["cleanup_needed"]:
                cleanup_needed_count += 1
            run_log["candidates"].append(candidate_log)
            continue

        dry_cmd = [
            py,
            "-m",
            "rehome.cli",
            "apply",
            str(plan_path),
            "--dryrun",
            "--catalog",
            str(db_path),
        ]
        rc = _run(dry_cmd, env=env, dry_run=False)
        candidate_log["dryrun_rc"] = int(rc)
        if rc != 0:
            print(f"   dry-run failed rc={rc}")
            candidate_log["cleanup_backlog"] = _cleanup_backlog(
                db_path=db_path,
                payload_hash=candidate.payload_hash,
                source_path=plan.get("source_path"),
                seeding_root=args.seeding_root,
                stash_device=args.stash_device,
                pool_device=args.pool_device,
            )
            if candidate_log["cleanup_backlog"]["cleanup_needed"]:
                cleanup_needed_count += 1
            run_log["candidates"].append(candidate_log)
            continue
        dry_success += 1

        if not args.apply:
            candidate_log["cleanup_backlog"] = _cleanup_backlog(
                db_path=db_path,
                payload_hash=candidate.payload_hash,
                source_path=plan.get("source_path"),
                seeding_root=args.seeding_root,
                stash_device=args.stash_device,
                pool_device=args.pool_device,
            )
            if candidate_log["cleanup_backlog"]["cleanup_needed"]:
                cleanup_needed_count += 1
            run_log["candidates"].append(candidate_log)
            continue

        apply_cmd = [
            py,
            "-m",
            "rehome.cli",
            "apply",
            str(plan_path),
            "--force",
            "--catalog",
            str(db_path),
        ]
        rc = _run(apply_cmd, env=env, dry_run=False)
        candidate_log["apply_rc"] = int(rc)
        if rc != 0:
            print(f"   apply failed rc={rc}")
            candidate_log["cleanup_backlog"] = _cleanup_backlog(
                db_path=db_path,
                payload_hash=candidate.payload_hash,
                source_path=plan.get("source_path"),
                seeding_root=args.seeding_root,
                stash_device=args.stash_device,
                pool_device=args.pool_device,
            )
            if candidate_log["cleanup_backlog"]["cleanup_needed"]:
                cleanup_needed_count += 1
            run_log["candidates"].append(candidate_log)
            continue
        apply_success += 1
        candidate_log["cleanup_backlog"] = _cleanup_backlog(
            db_path=db_path,
            payload_hash=candidate.payload_hash,
            source_path=plan.get("source_path"),
            seeding_root=args.seeding_root,
            stash_device=args.stash_device,
            pool_device=args.pool_device,
        )
        if candidate_log["cleanup_backlog"]["cleanup_needed"]:
            cleanup_needed_count += 1
        run_log["candidates"].append(candidate_log)

    run_log["finished_at"] = datetime.now().astimezone().isoformat()
    run_log["summary"] = {
        "selected": len(picks),
        "planned_ok": plan_success,
        "dryrun_ok": dry_success,
        "apply_ok": apply_success,
        "cleanup_needed_groups": cleanup_needed_count,
    }
    run_log_dir = Path(args.run_log_dir)
    run_log_dir.mkdir(parents=True, exist_ok=True)
    run_log_path = run_log_dir / f"rehome-safe-run-{run_id}.json"
    run_log_path.write_text(json.dumps(run_log, indent=2) + "\n", encoding="utf-8")

    print(
        "Summary: "
        f"planned={plan_success}/{len(picks)} "
        f"dryrun_ok={dry_success}/{len(picks)} "
        f"apply_ok={apply_success}/{len(picks)} "
        f"cleanup_needed={cleanup_needed_count}"
    )
    print(f"Run log: {run_log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
