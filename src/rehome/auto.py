"""
rehome auto — find safe MOVE candidates and optionally execute them.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

# States acceptable after a successful rehome (lower-case for comparison).
SEED_READY = {"uploading", "stalledup", "queuedup", "forcedup", "pausedup", "stoppedup"}


# ---------------------------------------------------------------------------
# Shared helpers (also imported by tests)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    payload_hash: str
    movable_bytes: int
    movable_pct_bytes: float
    recommendation: str


def _safe_candidates(groups: Iterable[dict], *, limit: int) -> list[Candidate]:
    """
    Filter *groups* (from build_status_report rehome_impact_groups) to
    payloads that are safe to fully MOVE and sort by movable_bytes descending.
    """
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

    picks.sort(key=lambda c: c.movable_bytes, reverse=True)
    return picks[: max(1, limit)]


def _is_qb_ready_state(state: Optional[str]) -> bool:
    """Return True if *state* is an acceptable post-rehome seed state."""
    if not state:
        return False
    s = str(state).strip().lower()
    if "checking" in s or "moving" in s:
        return False
    if s in {"error", "missingfiles"}:
        return False
    return s in SEED_READY


def _expected_save_path(plan: dict[str, Any], torrent_hash: str) -> str:
    """
    Return the expected qBittorrent save_path for *torrent_hash* after apply.

    Prefers per-torrent view_targets entry; falls back to parent of target_path.
    """
    targets = plan.get("view_targets") or []
    for row in targets:
        if row.get("torrent_hash") == torrent_hash and row.get("target_save_path"):
            return str(row["target_save_path"])
    target_path = plan.get("target_path")
    if not target_path:
        return ""
    return str(Path(target_path).parent)


# ---------------------------------------------------------------------------
# Candidate discovery (direct DB query — no filesystem dependency)
# ---------------------------------------------------------------------------

def _find_move_candidates(
    conn: sqlite3.Connection,
    stash_device_id: int,
    pool_device_id: int,
    limit: int,
) -> list[dict]:
    """
    Query the catalog for payloads safe to MOVE from stash to pool.

    Criteria:
      - Complete payload on stash device with ≥1 torrent reference
      - Complete payload on pool device (same payload_hash)
      - No copies on any other device (no external consumers)
      - total_bytes > 0 on stash
    """
    rows = conn.execute(
        """
        SELECT
            p_s.payload_hash,
            SUM(p_s.total_bytes)  AS stash_bytes,
            SUM(p_s.file_count)   AS stash_files,
            (
                SELECT COUNT(DISTINCT ti2.torrent_hash)
                FROM torrent_instances ti2
                JOIN payloads p2 ON p2.payload_id = ti2.payload_id
                WHERE p2.payload_hash = p_s.payload_hash
                  AND p2.device_id = ?
            ) AS torrent_count
        FROM payloads p_s
        WHERE p_s.device_id   = ?
          AND p_s.status      = 'complete'
          AND p_s.payload_hash IS NOT NULL
          AND p_s.total_bytes  > 0
          AND EXISTS (
              SELECT 1 FROM payloads p_p
              WHERE p_p.payload_hash = p_s.payload_hash
                AND p_p.device_id   = ?
                AND p_p.status      = 'complete'
          )
          AND EXISTS (
              SELECT 1 FROM torrent_instances ti
              WHERE ti.payload_id = p_s.payload_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM payloads p_o
              WHERE p_o.payload_hash = p_s.payload_hash
                AND p_o.device_id   != ?
                AND p_o.device_id   != ?
          )
        GROUP BY p_s.payload_hash
        HAVING stash_bytes > 0
        ORDER BY stash_bytes DESC
        LIMIT ?
        """,
        (
            stash_device_id,  # torrent_count subquery
            stash_device_id,  # WHERE p_s.device_id
            pool_device_id,   # pool copy EXISTS
            stash_device_id,  # NOT EXISTS other devices — exclude stash
            pool_device_id,   # NOT EXISTS other devices — exclude pool
            limit,
        ),
    ).fetchall()

    return [
        {
            "payload_hash": row[0],
            "stash_bytes": int(row[1]),
            "stash_files": int(row[2]),
            "torrent_count": int(row[3]),
        }
        for row in rows
    ]


def _device_info(conn: sqlite3.Connection, device_id: int) -> dict:
    """Return alias and mount_point for a device_id."""
    row = conn.execute(
        "SELECT device_alias, preferred_mount_point, mount_point FROM devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    if row:
        alias = str(row[0] or device_id)
        mount = str(row[1] or row[2] or "?")
    else:
        alias = str(device_id)
        mount = "?"
    return {"alias": alias, "mount": mount}


def _fmt_bytes(num_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(max(0, int(num_bytes)))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _validate_refresh_roots(
    catalog_path: Path,
    all_roots: list[tuple[str, str, str]],
) -> None:
    """
    Validate each scan root before any subprocess is launched.

    Checks:
      - path exists on disk
      - device alias exists in the catalog DB

    Prints a table and calls sys.exit(1) if anything fails.
    """
    import sqlite3 as _sqlite3

    print(f"\n[preflight] Validating {len(all_roots)} scan root(s)...")

    db_rows: dict[str, tuple] = {}
    conn = None
    if catalog_path.exists():
        try:
            conn = _sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True)
            for row in conn.execute(
                "SELECT device_alias, total_files, last_scanned_at FROM devices"
            ).fetchall():
                if row[0]:
                    db_rows[str(row[0])] = row
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    col_alias = max((len(a) for _, a, _ in all_roots), default=5)
    col_alias = max(col_alias, 5)
    failures: list[str] = []

    for path, alias, role in all_roots:
        path_ok = Path(path).exists()
        db_row = db_rows.get(alias)
        db_ok = db_row is not None

        if db_row:
            files = int(db_row[1] or 0)
            last = str(db_row[2] or "")[:10]
            db_note = f"files={files:,}  {last}"
        else:
            db_note = "NOT IN DB"

        exists_s = "YES" if path_ok else "NO "
        db_s = "YES" if db_ok else "NO "
        print(f"  {alias:<{col_alias}}  {role:<5}  exists={exists_s}  db={db_s} ({db_note})")

        if not path_ok or not db_ok:
            failures.append(alias)

    if failures:
        print(
            f"\n[preflight] ABORT: {len(failures)} root(s) failed validation"
            f" ({', '.join(failures)}) — fix config before running refresh."
        )
        sys.exit(1)

    print(f"[preflight] OK — {len(all_roots)} root(s) validated")


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


# ---------------------------------------------------------------------------
# Inline verify
# ---------------------------------------------------------------------------

def _inline_verify(
    qbit_client: Any,
    conn: sqlite3.Connection,
    plan: dict,
    pool_device_id: int,
) -> tuple[bool, str]:
    """
    Verify a completed rehome.

    Returns (ok, summary_str).
    """
    affected = plan.get("affected_torrents") or []
    source_path = plan.get("source_path")

    state_counts: dict[str, int] = {}
    progress_vals: list[float] = []
    alarm_hashes: list[str] = []
    catalog_ok = True

    for th in affected:
        info = qbit_client.get_torrent_info(th)
        if not info:
            alarm_hashes.append(th[:8])
            continue
        state = str(getattr(info, "state", "") or "").strip().lower()
        progress_raw = getattr(info, "progress", None)
        try:
            progress = float(progress_raw) if progress_raw is not None else 0.0
        except (TypeError, ValueError):
            progress = 0.0

        state_counts[state] = state_counts.get(state, 0) + 1
        progress_vals.append(progress)
        if not _is_qb_ready_state(state) or progress < 0.9999:
            alarm_hashes.append(th[:8])

    # Catalog check: all affected torrents' payload device_id should be pool
    for th in affected:
        row = conn.execute(
            """
            SELECT ti.payload_id, p.device_id
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE ti.torrent_hash = ?
            ORDER BY p.device_id = ? DESC
            LIMIT 1
            """,
            (th, pool_device_id),
        ).fetchone()
        if not row or int(row[1]) != pool_device_id:
            catalog_ok = False
            break

    # Source path gone
    source_gone = source_path is None or not Path(source_path).exists()

    ok = (not alarm_hashes) and catalog_ok and source_gone

    # Build summary string
    state_str = " ".join(
        f"{state}×{n}" for state, n in sorted(state_counts.items())
    ) or "?"
    pct_str = f"{max(progress_vals) * 100:.0f}%" if progress_vals else "?"
    catalog_str = "catalog OK" if catalog_ok else "catalog MISMATCH"
    src_str = "source gone" if source_gone else "source STILL EXISTS"
    summary = f"{state_str} · {pct_str} · {catalog_str} · {src_str}"
    if alarm_hashes:
        summary += f" · ALARM({','.join(alarm_hashes)})"

    return ok, summary


# ---------------------------------------------------------------------------
# Preflight refresh
# ---------------------------------------------------------------------------

def run_refresh(
    catalog_path: Path,
    seeding_root: str,
    pool_payload_root: str,
    stash_device: str,
    pool_device: str,
    workers: int = 8,
    apply_dedup: bool = False,
    skip_dedup: bool = False,
    extra_roots: list[tuple[str, str]] = [],
) -> int:
    """
    Preflight refresh: scan stash+pool, upgrade SHA256 for collision groups,
    optionally dedup (plan + dry-run, or execute), then sync qBit payloads.

    Steps:
      1. hashall scan <seeding_root> --parallel --workers N
      2. hashall scan <pool_payload_root> --parallel --workers N  (skip if same path)
      3a. hashall dupes --device <stash_device> --auto-upgrade
      3b. hashall dupes --device <pool_device> --auto-upgrade
      4a. hashall link plan <name> --device <alias> --min-size 1048576  (if not skip_dedup)
      4b. hashall link execute <plan_id> [--dry-run]                    (if not skip_dedup)
      5. hashall payload sync --upgrade-missing

    Returns exit code (0 = all steps succeeded, 1 = at least one failed).
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    python = sys.executable
    db_args = ["--db", str(catalog_path)]
    overall_ok = True

    def _run_step(label: str, cmd: list[str], *, capture: bool = False) -> tuple[bool, str]:
        """Run a subprocess step, print header + elapsed, return (ok, stdout)."""
        t0 = datetime.now()
        print(f"\n[refresh] {label}")
        print(f"  $ {' '.join(cmd)}")
        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True)
            # Always re-emit so the user sees output
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            stdout = result.stdout
        else:
            result = subprocess.run(cmd)
            stdout = ""
        elapsed = (datetime.now() - t0).total_seconds()
        ok = result.returncode == 0
        status = "OK" if ok else f"FAILED (exit={result.returncode})"
        print(f"  elapsed {_fmt_elapsed(elapsed)}  {status}")
        return ok, stdout

    # Build the full ordered root list for display + iteration
    all_roots: list[tuple[str, str, str]] = [
        (seeding_root, stash_device, "stash"),
        (pool_payload_root, pool_device, "pool"),
    ]
    if seeding_root == pool_payload_root:
        all_roots = all_roots[:1]  # deduped path
    for p, a in (extra_roots or []):
        all_roots.append((p, a, "extra"))

    dedup_mode = "execute" if apply_dedup else ("plan+dry-run" if not skip_dedup else "off")

    print(f"\nRehome Refresh  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  catalog  {catalog_path}")
    print(f"  workers  {workers}")
    print(f"  dedup    {dedup_mode}")
    print(f"\n  Scan roots ({len(all_roots)}):")
    for i, (path, alias, role) in enumerate(all_roots, 1):
        print(f"    [{i}] {alias:<20} {role:<6}  {path}")

    _validate_refresh_roots(catalog_path, all_roots)

    # ── Step 1: scan seeding_root ─────────────────────────────────────────
    ok, _ = _run_step(
        f"scan seeding_root ({seeding_root})",
        [python, "-m", "hashall.cli", "scan", seeding_root,
         "--parallel", "--workers", str(workers)] + db_args,
    )
    overall_ok = overall_ok and ok

    # ── Step 2: scan pool_payload_root ────────────────────────────────────
    if pool_payload_root != seeding_root:
        ok, _ = _run_step(
            f"scan pool_payload_root ({pool_payload_root})",
            [python, "-m", "hashall.cli", "scan", pool_payload_root,
             "--parallel", "--workers", str(workers)] + db_args,
        )
        overall_ok = overall_ok and ok

    # ── Step 3a: dupes auto-upgrade for stash ────────────────────────────
    ok, _ = _run_step(
        f"dupes auto-upgrade (stash={stash_device})",
        [python, "-m", "hashall.cli", "dupes",
         "--device", stash_device, "--auto-upgrade"] + db_args,
    )
    overall_ok = overall_ok and ok

    # ── Step 3b: dupes auto-upgrade for pool ─────────────────────────────
    ok, _ = _run_step(
        f"dupes auto-upgrade (pool={pool_device})",
        [python, "-m", "hashall.cli", "dupes",
         "--device", pool_device, "--auto-upgrade"] + db_args,
    )
    overall_ok = overall_ok and ok

    # ── Extra roots: scan + dupes (+ dedup if opted-in) ──────────────────
    for extra_path, extra_alias in (extra_roots or []):
        ok, _ = _run_step(
            f"scan extra root ({extra_path})",
            [python, "-m", "hashall.cli", "scan", extra_path,
             "--parallel", "--workers", str(workers)] + db_args,
        )
        overall_ok = overall_ok and ok

        ok, _ = _run_step(
            f"dupes auto-upgrade (extra={extra_alias})",
            [python, "-m", "hashall.cli", "dupes",
             "--device", extra_alias, "--auto-upgrade"] + db_args,
        )
        overall_ok = overall_ok and ok

        if not skip_dedup:
            plan_name = f"refresh-{extra_alias}-{timestamp}"
            ok, stdout = _run_step(
                f"link plan ({extra_alias})",
                [python, "-m", "hashall.cli", "link", "plan", plan_name,
                 "--device", extra_alias, "--min-size", "1048576"] + db_args,
                capture=True,
            )
            overall_ok = overall_ok and ok

            if ok:
                m = re.search(r"plan_id=(\d+)", stdout)
                if m:
                    plan_id = m.group(1)
                    execute_cmd = [
                        python, "-m", "hashall.cli", "link", "execute", plan_id,
                    ] + db_args
                    if not apply_dedup:
                        execute_cmd.append("--dry-run")
                    label = f"link execute plan_id={plan_id} ({extra_alias})" + (
                        "" if apply_dedup else " [dry-run]"
                    )
                    ok, _ = _run_step(label, execute_cmd)
                    overall_ok = overall_ok and ok
                else:
                    print(f"  [refresh] no plan_id found in link plan output for {extra_alias} — skipping execute")

    # ── Steps 4a/4b: dedup (opt-in) ──────────────────────────────────────
    if not skip_dedup:
        for dev_alias in (stash_device, pool_device):
            plan_name = f"refresh-{dev_alias}-{timestamp}"
            ok, stdout = _run_step(
                f"link plan ({dev_alias})",
                [python, "-m", "hashall.cli", "link", "plan", plan_name,
                 "--device", dev_alias, "--min-size", "1048576"] + db_args,
                capture=True,
            )
            overall_ok = overall_ok and ok

            if ok:
                m = re.search(r"plan_id=(\d+)", stdout)
                if m:
                    plan_id = m.group(1)
                    execute_cmd = [
                        python, "-m", "hashall.cli", "link", "execute", plan_id,
                    ] + db_args
                    if not apply_dedup:
                        execute_cmd.append("--dry-run")
                    label = f"link execute plan_id={plan_id} ({dev_alias})" + (
                        "" if apply_dedup else " [dry-run]"
                    )
                    ok, _ = _run_step(label, execute_cmd)
                    overall_ok = overall_ok and ok
                else:
                    print(f"  [refresh] no plan_id found in link plan output for {dev_alias} — skipping execute")

    # ── Step 5: payload sync --upgrade-missing ────────────────────────────
    ok, _ = _run_step(
        "payload sync --upgrade-missing",
        [python, "-m", "hashall.cli", "payload", "sync",
         "--upgrade-missing"] + db_args,
    )
    overall_ok = overall_ok and ok

    # ── Summary ───────────────────────────────────────────────────────────
    sep = "─" * 57
    print(f"\n{sep}")
    if overall_ok:
        print("refresh  OK — all steps succeeded")
    else:
        print("refresh  PARTIAL — one or more steps failed (see above)")

    return 0 if overall_ok else 1


# ---------------------------------------------------------------------------
# Main run_auto
# ---------------------------------------------------------------------------

def run_auto(
    catalog_path: Path,
    stash_device_id: int,
    pool_device_id: int,
    pool_payload_root: str,
    seeding_root: str,
    library_root: str,
    limit: int,
    do_apply: bool,
    plan_log_dir: Path,
    run_log_dir: Path,
) -> int:
    """
    Find safe MOVE candidates and rehome them.

    Returns exit code (0 = success, 1 = partial/error).
    """
    from hashall.model import connect_db
    from rehome.planner import DemotionPlanner
    from rehome.executor import DemotionExecutor
    from rehome.cli import _acquire_rehome_lock

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode_label = "apply" if do_apply else "dry-run"

    # ── Header ──────────────────────────────────────────────────────────────
    print(f"\nRehome Auto  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  catalog  {catalog_path}")

    conn = connect_db(catalog_path, read_only=not do_apply, apply_migrations=False)
    try:
        stash_info = _device_info(conn, stash_device_id)
        pool_info = _device_info(conn, pool_device_id)
        print(f"  stash    {stash_info['alias']} (id={stash_device_id}, {stash_info['mount']})")
        print(f"  pool     {pool_info['alias']} (id={pool_device_id}, {pool_info['mount']})")
        print(f"  mode     {mode_label}" + (
            "" if do_apply else "  (add --apply to execute)"
        ))
        print()

        # ── Candidate discovery ──────────────────────────────────────────────
        print("Scanning...", end=" ", flush=True)
        candidates = _find_move_candidates(conn, stash_device_id, pool_device_id, limit)
        # Count total available without limit
        total_available = conn.execute(
            """
            SELECT COUNT(DISTINCT p_s.payload_hash)
            FROM payloads p_s
            WHERE p_s.device_id = ?
              AND p_s.status = 'complete'
              AND p_s.payload_hash IS NOT NULL
              AND p_s.total_bytes > 0
              AND EXISTS (
                  SELECT 1 FROM payloads p_p
                  WHERE p_p.payload_hash = p_s.payload_hash
                    AND p_p.device_id = ?
                    AND p_p.status = 'complete'
              )
              AND EXISTS (
                  SELECT 1 FROM torrent_instances ti
                  WHERE ti.payload_id = p_s.payload_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM payloads p_o
                  WHERE p_o.payload_hash = p_s.payload_hash
                    AND p_o.device_id != ?
                    AND p_o.device_id != ?
              )
            """,
            (stash_device_id, pool_device_id, stash_device_id, pool_device_id),
        ).fetchone()[0]

        taking = len(candidates)
        print(f"{total_available} MOVE groups available, taking top {taking}")
        print()

        if not candidates:
            print("No eligible candidates found.")
            return 0

        # ── Planner and executor ─────────────────────────────────────────────
        planner = DemotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=[seeding_root],
            library_roots=[library_root] if library_root else [],
            stash_device=stash_device_id,
            pool_device=pool_device_id,
            stash_seeding_root=seeding_root,
            pool_payload_root=pool_payload_root,
        )
        executor = DemotionExecutor(catalog_path=catalog_path)

        # Acquire lock only for apply
        lock_fh = None
        if do_apply:
            lock_fh = _acquire_rehome_lock()

        run_log: list[dict] = []
        planned_count = 0
        applied_count = 0
        verified_count = 0
        freed_bytes = 0
        exit_code = 0

        try:
            for idx, cand in enumerate(candidates, 1):
                phash = cand["payload_hash"]
                stash_bytes = cand["stash_bytes"]
                torrent_count = cand["torrent_count"]

                print(f"[{idx}/{taking}]  {phash[:16]}...  "
                      f"{_fmt_bytes(stash_bytes)} · {torrent_count} torrent(s)")

                # ── Plan ────────────────────────────────────────────────────
                t0 = datetime.now()
                try:
                    plan = planner.plan_batch_demotion_by_payload_hash(phash)
                except Exception as e:
                    print(f"  plan    ERROR: {e}")
                    run_log.append({"payload_hash": phash, "stage": "plan", "error": str(e)})
                    exit_code = 1
                    continue

                decision = plan.get("decision", "?")
                target = plan.get("target_path") or "?"
                target_display = (target[:60] + "...") if len(target) > 63 else target
                if decision == "MOVE":
                    print(f"  plan    MOVE → {target_display:<50}  OK")
                elif decision == "BLOCK":
                    reasons = plan.get("reasons", [])
                    print(f"  plan    BLOCK: {reasons[0] if reasons else '?'}")
                    run_log.append({"payload_hash": phash, "stage": "plan", "decision": "BLOCK", "reasons": reasons})
                    exit_code = 1
                    print()
                    continue
                else:
                    print(f"  plan    {decision}: skipping")
                    run_log.append({"payload_hash": phash, "stage": "plan", "decision": decision})
                    print()
                    continue

                planned_count += 1

                # Save plan JSON
                plan_log_dir.mkdir(parents=True, exist_ok=True)
                plan_file = plan_log_dir / f"{timestamp}-{phash[:16]}.json"
                plan_file.write_text(json.dumps(plan, indent=2))

                # ── Dry-run check ────────────────────────────────────────────
                check_buf = io.StringIO()
                check_ok = True
                try:
                    with contextlib.redirect_stdout(check_buf):
                        executor.dry_run(plan)
                    print(f"  check   dryrun{'':<44}  OK")
                except Exception as e:
                    print(f"  check   dryrun FAIL: {e}")
                    run_log.append({"payload_hash": phash, "stage": "check", "error": str(e)})
                    check_ok = False
                    exit_code = 1

                if not check_ok:
                    print()
                    continue

                # ── Apply ────────────────────────────────────────────────────
                if do_apply:
                    t_apply = datetime.now()
                    apply_ok = True
                    try:
                        executor.execute(plan)
                        elapsed = (datetime.now() - t_apply).total_seconds()
                        print(f"  apply   {_fmt_bytes(stash_bytes)} · {_fmt_elapsed(elapsed)} · source deleted"
                              f"{'':>10}  OK")
                        applied_count += 1
                        freed_bytes += stash_bytes
                    except Exception as e:
                        elapsed = (datetime.now() - t_apply).total_seconds()
                        print(f"  apply   FAIL after {_fmt_elapsed(elapsed)}: {e}")
                        run_log.append({"payload_hash": phash, "stage": "apply", "error": str(e)})
                        apply_ok = False
                        exit_code = 1

                    if apply_ok:
                        # ── Inline verify ────────────────────────────────────
                        try:
                            verify_conn = connect_db(
                                catalog_path, read_only=True, apply_migrations=False
                            )
                            try:
                                verify_ok, verify_summary = _inline_verify(
                                    executor.qbit_client, verify_conn, plan, pool_device_id
                                )
                            finally:
                                verify_conn.close()
                        except Exception as e:
                            verify_ok = False
                            verify_summary = f"ERROR: {e}"

                        status = "OK" if verify_ok else "FAIL"
                        print(f"  verify  {verify_summary:<52}  {status}")
                        if verify_ok:
                            verified_count += 1
                        else:
                            exit_code = 1
                        run_log.append({
                            "payload_hash": phash,
                            "stage": "verify",
                            "ok": verify_ok,
                            "summary": verify_summary,
                        })
                else:
                    print(f"  apply   skipped")

                print()

        finally:
            if lock_fh is not None:
                lock_fh.close()

    finally:
        conn.close()

    # ── Final summary ────────────────────────────────────────────────────────
    sep = "─" * 57
    print(sep)
    if do_apply:
        print(
            f"applied  {applied_count}/{taking}   "
            f"verified  {verified_count}/{taking}   "
            f"freed  {_fmt_bytes(freed_bytes)} from stash"
        )
        run_log_dir.mkdir(parents=True, exist_ok=True)
        log_file = run_log_dir / f"{timestamp}.json"
        log_file.write_text(json.dumps({
            "timestamp": timestamp,
            "stash_device_id": stash_device_id,
            "pool_device_id": pool_device_id,
            "limit": limit,
            "planned": planned_count,
            "applied": applied_count,
            "verified": verified_count,
            "freed_bytes": freed_bytes,
            "runs": run_log,
        }, indent=2))
        print(f"log  {log_file}")
    else:
        print(
            f"dry-run  {planned_count}/{taking} planned  "
            f"{planned_count}/{taking} checked"
        )
        print(f"To apply: rehome auto --limit {limit} --apply")

    return exit_code
