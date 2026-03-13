"""
rehome auto — find safe MOVE candidates and optionally execute them.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
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
    source_device_id: int,
    pool_device_id: int,
    all_managed_ids: list[int],
    limit: int,
) -> list[dict]:
    """
    Query the catalog for payloads safe to MOVE from source_device to pool.

    Criteria:
      - Complete payload on source device with ≥1 torrent reference
      - Complete payload on pool device (same payload_hash)
      - No copies on any device outside the managed set (all_managed_ids)
      - total_bytes > 0 on source
    """
    placeholders = ",".join("?" * len(all_managed_ids))
    rows = conn.execute(
        f"""
        SELECT
            p_s.payload_hash,
            SUM(p_s.total_bytes)  AS source_bytes,
            SUM(p_s.file_count)   AS source_files,
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
                AND p_o.device_id NOT IN ({placeholders})
          )
        GROUP BY p_s.payload_hash
        HAVING source_bytes > 0
        ORDER BY source_bytes DESC
        LIMIT ?
        """,
        (
            source_device_id,   # torrent_count subquery
            source_device_id,   # WHERE p_s.device_id
            pool_device_id,     # pool copy EXISTS
            *all_managed_ids,   # NOT IN managed set
            limit,
        ),
    ).fetchall()

    return [
        {
            "payload_hash": row[0],
            "source_bytes": int(row[1]),
            "source_files": int(row[2]),
            "torrent_count": int(row[3]),
            "source_device_id": source_device_id,
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


def _run_catalog_preflight(catalog_path: Path) -> tuple[bool, dict[str, Any]]:
    """
    Run hashall catalog preflight checks directly against the DB.

    Returns:
      (ok, report_dict)
    """
    from hashall.model import connect_db
    from hashall.preflight import run_catalog_preflight

    conn = connect_db(catalog_path, read_only=True, apply_migrations=False)
    try:
        report = run_catalog_preflight(conn)
    finally:
        conn.close()
    return bool(report.get("ok")), report


_UPGRADE_SUMMARY_RE = re.compile(
    r"(?:upgrade_summary|upgrade stage:)\s+queued=(\d+)\s+started=(\d+)\s+completed=(\d+)\s+failed=(\d+)"
)

_LINK_PLAN_ID_PATTERNS = (
    re.compile(r"\bplan_id=(\d+)\b", re.IGNORECASE),
    re.compile(r"\bPlan #(\d+)\b"),
    re.compile(r"\blink show-plan (\d+)\b"),
    re.compile(r"\blink execute (\d+)\b"),
)


def _parse_upgrade_summary(stdout: str) -> Optional[dict[str, int]]:
    """Parse `upgrade_summary ...` counters from payload sync output."""
    match = None
    for m in _UPGRADE_SUMMARY_RE.finditer(str(stdout or "")):
        match = m
    if match is None:
        return None
    return {
        "queued": int(match.group(1)),
        "started": int(match.group(2)),
        "completed": int(match.group(3)),
        "failed": int(match.group(4)),
    }


def _parse_link_plan_id(stdout: str) -> Optional[str]:
    """
    Parse a link plan id from `hashall link plan` output.

    Accept both older machine-readable output (``plan_id=12``) and the
    current human summary/header form (``Plan #12``).
    """
    text = str(stdout or "")
    for pattern in _LINK_PLAN_ID_PATTERNS:
        match = None
        for found in pattern.finditer(text):
            match = found
        if match is not None:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Inline verify
# ---------------------------------------------------------------------------

def _inline_verify(
    qbit_client: Any,
    conn: sqlite3.Connection,
    plan: dict,
    dest_device_id: int,
) -> tuple[bool, str]:
    """
    Verify a completed rehome.

    Returns (ok, summary_str).
    """
    affected = plan.get("affected_torrents") or []
    source_path = plan.get("source_path")
    decision = str(plan.get("decision") or "").strip().upper()

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

    # Catalog check: all affected torrents' payload device_id should be dest
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
            (th, dest_device_id),
        ).fetchone()
        if not row or int(row[1]) != dest_device_id:
            catalog_ok = False
            break

    # Source path gone
    source_gone = source_path is None or not Path(source_path).exists()
    cleanup_pending = decision == "REUSE" and not source_gone
    source_ok = True if decision == "REUSE" else source_gone

    ok = (not alarm_hashes) and catalog_ok and source_ok

    # Build summary string
    state_str = " ".join(
        f"{state}×{n}" for state, n in sorted(state_counts.items())
    ) or "?"
    pct_str = f"{max(progress_vals) * 100:.0f}%" if progress_vals else "?"
    catalog_str = "catalog OK" if catalog_ok else "catalog MISMATCH"
    if source_gone:
        src_str = "source gone"
    elif cleanup_pending:
        src_str = "cleanup pending"
    else:
        src_str = "source STILL EXISTS"
    summary = f"{state_str} · {pct_str} · {catalog_str} · {src_str}"
    if alarm_hashes:
        summary += f" · ALARM({','.join(alarm_hashes)})"

    return ok, summary


# ---------------------------------------------------------------------------
# Preflight refresh
# ---------------------------------------------------------------------------

def run_refresh(
    catalog_path: Path,
    active_root: str = "",
    dest_root: str = "",
    active_device: str = "",
    dest_device: str = "",
    workers: int = 8,
    skip_dedup: bool = False,
    managed_roots: "list[tuple[str, str]]" = [],
    verbose: bool = False,
    debug: bool = False,
    # Backwards-compat params (old names)
    seeding_root: "str | None" = None,
    pool_payload_root: "str | None" = None,
    stash_device: "str | None" = None,
    pool_device: "str | None" = None,
    extra_roots: "list[tuple[str, str]] | None" = None,
) -> int:
    """
    Preflight refresh: scan all managed roots, upgrade SHA256 for collision groups,
    optionally dedup (plan + execute), then sync qBit payloads.

    Steps:
      1. hashall scan <active_root> --parallel --workers N
      2. hashall scan <dest_root> --parallel --workers N  (skip if same path)
      3a. hashall dupes --device <active_device> --auto-upgrade
      3b. hashall dupes --device <dest_device> --auto-upgrade
      3c. (for each managed root) hashall dupes --device <alias> --auto-upgrade
      4a. hashall link plan <name> --device <alias> --min-size 1048576  (if not skip_dedup)
      4b. hashall link execute <plan_id> [--dry-run]                    (if not skip_dedup)
      5. hashall payload sync --upgrade-missing

    Returns exit code (0 = all steps succeeded, 1 = at least one failed).
    """
    # Apply backwards-compat fallbacks
    active_root = active_root or seeding_root or ""
    dest_root = dest_root or pool_payload_root or ""
    active_device = active_device or stash_device or ""
    dest_device = dest_device or pool_device or ""
    managed_roots = managed_roots or extra_roots or []
    published_seed_state_path: Optional[Path] = None
    try:
        from rehome.seed_state import publish_seed_root_state
        _cfg = {
            "active_device": active_device,
            "active_root": active_root,
            "default_dest_device": dest_device,
            "default_dest_root": dest_root,
            "managed_roots": [f"{path}:{alias}" for path, alias in managed_roots],
        }
        published_seed_state_path, _seed_state = publish_seed_root_state(cfg=_cfg)
    except Exception:
        published_seed_state_path = None

    from rehome.runlog import RunLogger
    from rehome.cli import _acquire_refresh_lock

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    python = sys.executable
    db_args = ["--db", str(catalog_path)]
    overall_ok = True

    log_dir = Path.home() / ".logs" / "hashall" / "rehome" / "refresh"
    log_path = log_dir / f"{timestamp}.log"
    json_path = log_dir / f"{timestamp}.json"

    lock_fh = _acquire_refresh_lock()
    try:
        with RunLogger(log_path, verbose=verbose, debug=debug) as logger:
            def _run_step(label: str, cmd: list[str], *, capture: bool = False) -> tuple[bool, str]:
                """Run a subprocess step, print header + elapsed, return (ok, stdout)."""
                t0 = datetime.now()
                print(f"\n[refresh] {label}")
                print(f"  $ {' '.join(cmd)}")
                should_capture = capture or logger.verbose
                if should_capture:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.stdout:
                        print(result.stdout, end="")
                    if result.stderr:
                        # stderr goes to stderr; write_raw ensures it lands in the log too
                        print(result.stderr, end="", file=sys.stderr)
                        logger.write_raw(result.stderr)
                    stdout = result.stdout or ""
                else:
                    try:
                        heartbeat_s = max(5, int(os.environ.get("REHOME_REFRESH_HEARTBEAT_S", "30")))
                    except ValueError:
                        heartbeat_s = 30
                    started_monotonic = time.monotonic()
                    next_heartbeat = started_monotonic + heartbeat_s
                    proc = subprocess.Popen(cmd)
                    while True:
                        rc = proc.poll()
                        if rc is not None:
                            result = subprocess.CompletedProcess(cmd, rc)
                            break
                        now_monotonic = time.monotonic()
                        if now_monotonic >= next_heartbeat:
                            elapsed_hb = int(now_monotonic - started_monotonic)
                            print(
                                "  [refresh] still running "
                                f"label={label} elapsed={elapsed_hb}s "
                                "watch='tail -n0 -F ~/.logs/hashall/hashall.log'"
                            )
                            next_heartbeat = now_monotonic + heartbeat_s
                        time.sleep(1.0)
                    stdout = ""
                elapsed = (datetime.now() - t0).total_seconds()
                ok = result.returncode == 0
                status = "OK" if ok else f"FAILED (exit={result.returncode})"
                print(f"  elapsed {_fmt_elapsed(elapsed)}  {status}")
                logger.record_step(label, cmd, ok, elapsed, stdout=stdout)
                return ok, stdout

            # Build the full ordered root list for display + preflight validation
            all_roots: list[tuple[str, str, str]] = [
                (active_root, active_device, "active"),
                (dest_root, dest_device, "dest"),
            ]
            if active_root == dest_root:
                all_roots = all_roots[:1]
            for p, a in (managed_roots or []):
                all_roots.append((p, a, "managed"))

            dedup_mode = "execute" if not skip_dedup else "off"

        with logger.patch_stdout():
            print(f"\nRehome Refresh  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            print(f"  catalog  {catalog_path}")
            print(f"  workers  {workers}")
            print(f"  dedup    {dedup_mode}")
            if logger.verbose:
                print(f"  log      {log_path}")
            if published_seed_state_path is not None:
                print(f"  seed-state  {published_seed_state_path}")
            print(f"\n  Scan roots ({len(all_roots)}):")
            for i, (path, alias, role) in enumerate(all_roots, 1):
                print(f"    [{i}] {alias:<20} {role:<7}  {path}")

            _validate_refresh_roots(catalog_path, all_roots)

            # ── Preflight: fail closed on catalog integrity issues ────────────────
            preflight_label = "doctor preflight"
            preflight_cmd = [python, "-m", "hashall.cli", "doctor", "preflight"] + db_args
            preflight_t0 = datetime.now()
            preflight_ok = False
            preflight_report: dict[str, Any] = {}
            preflight_error = ""
            print(f"\n[refresh] {preflight_label}")
            print(f"  $ {' '.join(preflight_cmd)}")
            try:
                preflight_ok, preflight_report = _run_catalog_preflight(catalog_path)
            except Exception as exc:
                preflight_ok = False
                preflight_error = str(exc)
                preflight_report = {
                    "ok": False,
                    "error": preflight_error,
                    "checks": [],
                    "summary": {"total_checks": 0, "failed_error": 1, "failed_warning": 0},
                }
            preflight_elapsed = (datetime.now() - preflight_t0).total_seconds()
            print(f"  elapsed {_fmt_elapsed(preflight_elapsed)}  {'OK' if preflight_ok else 'FAILED'}")
            logger.record_step(
                preflight_label,
                preflight_cmd,
                preflight_ok,
                preflight_elapsed,
                stdout=json.dumps(preflight_report, indent=2),
            )
            summary = preflight_report.get("summary", {})
            print(
                "  preflight_summary "
                f"failed_error={int(summary.get('failed_error', 0) or 0)} "
                f"failed_warning={int(summary.get('failed_warning', 0) or 0)} "
                f"total_checks={int(summary.get('total_checks', 0) or 0)}"
            )
            if preflight_error:
                print(f"  preflight_error {preflight_error}")
            if not preflight_ok:
                for check in preflight_report.get("checks", []):
                    if bool(check.get("ok")):
                        continue
                    print(
                        "    fail "
                        f"{str(check.get('severity') or 'error')} "
                        f"{str(check.get('name') or 'unknown')} "
                        f"{str(check.get('message') or '')}"
                    )
                print("  [refresh] catalog preflight failed — skipping refresh execution steps")
            overall_ok = overall_ok and preflight_ok

            if preflight_ok:
                # ── Step 1: scan active_root ──────────────────────────────────────────
                ok, _ = _run_step(
                    f"scan active_root ({active_root})",
                    [python, "-m", "hashall.cli", "scan", active_root,
                     "--parallel", "--workers", str(workers)] + db_args,
                )
                overall_ok = overall_ok and ok

                # ── Step 2: scan dest_root ────────────────────────────────────────────
                if dest_root != active_root:
                    ok, _ = _run_step(
                        f"scan dest_root ({dest_root})",
                        [python, "-m", "hashall.cli", "scan", dest_root,
                         "--parallel", "--workers", str(workers)] + db_args,
                    )
                    overall_ok = overall_ok and ok

                # ── Step 3a: dupes auto-upgrade for active ────────────────────────────
                ok, _ = _run_step(
                    f"dupes auto-upgrade (active={active_device})",
                    [python, "-m", "hashall.cli", "dupes",
                     "--device", active_device, "--auto-upgrade"] + db_args,
                )
                overall_ok = overall_ok and ok

                # ── Step 3b: dupes auto-upgrade for dest ─────────────────────────────
                ok, _ = _run_step(
                    f"dupes auto-upgrade (dest={dest_device})",
                    [python, "-m", "hashall.cli", "dupes",
                     "--device", dest_device, "--auto-upgrade"] + db_args,
                )
                overall_ok = overall_ok and ok

                # ── Managed roots: scan + dupes (+ dedup if opted-in) ────────────────
                for managed_path, managed_alias in (managed_roots or []):
                    ok, _ = _run_step(
                        f"scan managed root ({managed_path})",
                        [python, "-m", "hashall.cli", "scan", managed_path,
                         "--parallel", "--workers", str(workers)] + db_args,
                    )
                    overall_ok = overall_ok and ok

                    ok, _ = _run_step(
                        f"dupes auto-upgrade (managed={managed_alias})",
                        [python, "-m", "hashall.cli", "dupes",
                         "--device", managed_alias, "--auto-upgrade"] + db_args,
                    )
                    overall_ok = overall_ok and ok

                    if not skip_dedup:
                        plan_name = f"refresh-{managed_alias}-{timestamp}"
                        ok, stdout = _run_step(
                            f"link plan ({managed_alias})",
                            [python, "-m", "hashall.cli", "link", "plan", plan_name,
                             "--device", managed_alias, "--min-size", "1048576"] + db_args,
                            capture=True,
                    )
                    overall_ok = overall_ok and ok

                    if ok:
                        plan_id = _parse_link_plan_id(stdout)
                        if plan_id:
                            execute_cmd = [
                                python, "-m", "hashall.cli", "link", "execute", plan_id,
                                "--yes",
                            ] + db_args
                            label = f"link execute plan_id={plan_id} ({managed_alias})"
                            print("  [refresh] delegated progress may continue in: tail -n0 -F ~/.logs/hashall/hashall.log")
                            ok, _ = _run_step(label, execute_cmd)
                            overall_ok = overall_ok and ok
                        else:
                            print(f"  [refresh] no parsable plan_id in link plan output for {managed_alias} — skipping execute")

                # ── Steps 4a/4b: dedup for active + dest ─────────────────────────────
                if not skip_dedup:
                    for dev_alias in (active_device, dest_device):
                        plan_name = f"refresh-{dev_alias}-{timestamp}"
                        ok, stdout = _run_step(
                            f"link plan ({dev_alias})",
                            [python, "-m", "hashall.cli", "link", "plan", plan_name,
                             "--device", dev_alias, "--min-size", "1048576"] + db_args,
                            capture=True,
                        )
                        overall_ok = overall_ok and ok

                        if ok:
                            plan_id = _parse_link_plan_id(stdout)
                            if plan_id:
                                execute_cmd = [
                                    python, "-m", "hashall.cli", "link", "execute", plan_id,
                                    "--yes",
                                ] + db_args
                                label = f"link execute plan_id={plan_id} ({dev_alias})"
                                print("  [refresh] delegated progress may continue in: tail -n0 -F ~/.logs/hashall/hashall.log")
                                ok, _ = _run_step(label, execute_cmd)
                                overall_ok = overall_ok and ok
                            else:
                                print(f"  [refresh] no parsable plan_id in link plan output for {dev_alias} — skipping execute")

                # ── Step 5: payload sync --upgrade-missing ────────────────────────────
                ok, payload_stdout = _run_step(
                    "payload sync --upgrade-missing",
                    [python, "-m", "hashall.cli", "payload", "sync",
                     "--upgrade-missing"] + db_args,
                    capture=True,
                )
                overall_ok = overall_ok and ok
                if ok:
                    upgrade_summary = _parse_upgrade_summary(payload_stdout)
                    min_ratio_env = os.environ.get("HASHALL_REFRESH_UPGRADE_MIN_COMPLETE_RATIO", "0.90")
                    try:
                        min_ratio = float(min_ratio_env)
                    except ValueError:
                        min_ratio = 0.90
                    min_ratio = max(0.0, min(1.0, min_ratio))
                    if upgrade_summary is None:
                        overall_ok = False
                        print("  [refresh] payload sync quality gate FAILED: missing upgrade_summary")
                    else:
                        queued = int(upgrade_summary.get("queued", 0))
                        completed = int(upgrade_summary.get("completed", 0))
                        failed = int(upgrade_summary.get("failed", 0))
                        ratio = 1.0 if queued <= 0 else (float(completed) / float(queued))
                        print(
                            "  payload_sync_gate "
                            f"min_complete_ratio={min_ratio:.3f} "
                            f"queued={queued} completed={completed} failed={failed} ratio={ratio:.3f}"
                        )
                        if failed > 0 or ratio < min_ratio:
                            overall_ok = False
                            print("  [refresh] payload sync quality gate FAILED")

            # ── Summary ───────────────────────────────────────────────────────────
            sep = "─" * 57
            print(f"\n{sep}")
            if overall_ok:
                print("refresh  OK — all steps succeeded")
            else:
                print("refresh  PARTIAL — one or more steps failed (see above)")
            print(f"log  {log_path}")

            logger.dump_json(json_path)
    finally:
        lock_fh.close()

    return 0 if overall_ok else 1


# ---------------------------------------------------------------------------
# Main run_auto
# ---------------------------------------------------------------------------

def _make_planner(
    catalog_path: Path,
    active_device_id: int,
    dest_device_id: int,
    source_id: int,
    source_root: str,
    dest_root: str,
    content_root: str,
    active_root: str,
) -> Any:
    """
    Select and instantiate the appropriate planner for a source→dest move.

    - Dest == active filesystem  →  PromotionPlanner (returning home)
    - Dest != active filesystem  →  DemotionPlanner  (rehoming to storage)
    """
    from rehome.planner import DemotionPlanner, PromotionPlanner

    if dest_device_id == active_device_id:
        # Moving TO active device — PromotionPlanner
        # In PromotionPlanner convention: stash_device=dest, pool_device=source
        return PromotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=[source_root],
            library_roots=[content_root] if content_root else [],
            stash_device=dest_device_id,
            pool_device=source_id,
            stash_seeding_root=active_root,
            pool_seeding_root=source_root,
        )
    else:
        # Moving FROM any device TO storage — DemotionPlanner
        # Hardlink check applies: files outside source_root blocked if they have
        # external hardlinks (consumed content affinity)
        return DemotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=[source_root],
            library_roots=[content_root] if content_root else [],
            stash_device=source_id,
            pool_device=dest_device_id,
            stash_seeding_root=source_root,
            pool_payload_root=dest_root,
        )


def run_auto(
    catalog_path: Path,
    active_device_id: int = 0,
    dest_device_id: int = 0,
    dest_root: str = "",
    active_root: str = "",
    content_root: str = "",
    limit: int = 5,
    do_apply: bool = False,
    plan_log_dir: Path = Path("."),
    run_log_dir: Path = Path("."),
    source_device_id: "int | None" = None,
    extra_sources: "list[tuple[int, str, str]] | None" = None,
    verbose: bool = False,
    debug: bool = False,
    # Backwards-compat params (old names)
    stash_device_id: "int | None" = None,
    pool_device_id: "int | None" = None,
    pool_payload_root: "str | None" = None,
    seeding_root: "str | None" = None,
    library_root: "str | None" = None,
    extra_source_roots: "list[tuple[str, str]] | None" = None,
) -> int:
    """
    Find safe MOVE candidates across all managed source filesystems and rehome them.

    Sources queried:
      - If source_device_id is given: only that device
      - Otherwise: active_device + all extra_sources

    Planner selection per source:
      - dest == active device  →  PromotionPlanner (returning home)
      - dest != active device  →  DemotionPlanner  (hardlink check applies for active source)

    Returns exit code (0 = success, 1 = partial/error).
    """
    # Apply backwards-compat fallbacks
    active_device_id = active_device_id or stash_device_id or 0
    dest_device_id = dest_device_id or pool_device_id or 0
    dest_root = dest_root or pool_payload_root or ""
    active_root = active_root or seeding_root or ""
    content_root = content_root or library_root or ""

    from hashall.model import connect_db
    from hashall.device import resolve_device_id
    from rehome.executor import DemotionExecutor
    from rehome.cli import _acquire_rehome_lock
    from rehome.runlog import RunLogger

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode_label = "apply" if do_apply else "dry-run"

    log_dir = Path.home() / ".logs" / "hashall" / "rehome" / "auto"
    log_path = log_dir / f"{timestamp}.log"
    json_path = log_dir / f"{timestamp}.json"
    _logger = RunLogger(log_path, verbose=verbose, debug=debug)
    _stdout_ctx = _logger.patch_stdout()
    _stdout_ctx.__enter__()

    # ── Header ──────────────────────────────────────────────────────────────
    print(f"\nRehome Auto  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  catalog  {catalog_path}")

    conn = connect_db(catalog_path, read_only=not do_apply, apply_migrations=False)
    try:
        dest_info = _device_info(conn, dest_device_id)
        active_info = _device_info(conn, active_device_id)
        is_promotion = (dest_device_id == active_device_id)

        print(f"  dest     {dest_info['alias']} (id={dest_device_id}, {dest_info['mount']})"
              + ("  active" if is_promotion else ""))

        # Build source list
        # Each entry: (device_id, alias, root_path)
        if source_device_id is not None:
            src_info = _device_info(conn, source_device_id)
            src_root = active_root if source_device_id == active_device_id else ""
            # Try to find root from extra_sources if available
            if extra_sources:
                for xid, _, xroot in extra_sources:
                    if xid == source_device_id:
                        src_root = xroot
                        break
            sources: list[tuple[int, str, str]] = [(source_device_id, src_info["alias"], src_root)]
        else:
            # Default: active device + all extra_sources
            sources = [(active_device_id, active_info["alias"], active_root)]
            for xid, xalias, xpath in (extra_sources or []):
                sources.append((xid, xalias, xpath))

        # Also resolve any old-style extra_source_roots (path, alias) pairs
        if extra_source_roots and source_device_id is None:
            for xpath, xalias in extra_source_roots:
                try:
                    xid = resolve_device_id(conn, xalias)
                    if not any(s[0] == xid for s in sources):
                        sources.append((xid, xalias, xpath))
                except (ValueError, Exception) as e:
                    print(f"  managed  {xalias} — WARNING: not in DB ({e}), skipping")

        all_managed_ids = [dest_device_id] + [s[0] for s in sources]

        # Print sources with role labels; also build source records for JSON
        source_records = []
        for i, (sid, salias, _spath) in enumerate(sources, 1):
            sinfo = _device_info(conn, sid)
            role_label = "active — hardlink check applies" if sid == active_device_id else "storage"
            if is_promotion:
                role_label = "storage → active (promotion)"
            print(f"  sources  [{i}] {salias:<20} (id={sid}, {sinfo['mount']})  {role_label}")
            source_records.append({
                "device_id": sid,
                "alias": salias,
                "mount": sinfo["mount"],
                "role": "active" if sid == active_device_id else "storage",
            })

        print(f"  mode     {mode_label}" + (
            "" if do_apply else "  (add --apply to execute)"
        ))
        print()

        # ── Build run_record skeleton ─────────────────────────────────────────
        run_record: dict = {
            "mode": mode_label,
            "catalog": str(catalog_path),
            "active_device": {"id": active_device_id, "alias": active_info["alias"], "mount": active_info["mount"]},
            "dest_device":   {"id": dest_device_id,   "alias": dest_info["alias"],   "mount": dest_info["mount"]},
            "limit": limit,
            "sources": source_records,
            "discovery": {},
            "candidates": [],
            "summary": {},
        }

        # ── Candidate discovery across all source devices ────────────────────
        print("Scanning...", end=" ", flush=True)
        all_candidates: list[dict] = []
        source_counts: dict[str, int] = {}
        for src_id, src_alias, src_path in sources:
            cands = _find_move_candidates(conn, src_id, dest_device_id, all_managed_ids, limit * 10)
            for c in cands:
                c["source_root"] = src_path
                c["source_alias"] = src_alias
            all_candidates.extend(cands)
            source_counts[src_alias] = len(cands)

        # Merge, dedup by payload_hash, sort by size desc
        seen_hashes: set[str] = set()
        merged: list[dict] = []
        for c in sorted(all_candidates, key=lambda x: x["source_bytes"], reverse=True):
            if c["payload_hash"] not in seen_hashes:
                seen_hashes.add(c["payload_hash"])
                merged.append(c)
        candidates = merged[:limit]

        total_available = len(merged)
        taking = len(candidates)
        counts_str = "  ".join(f"{a}:{n}" for a, n in source_counts.items())
        print(f"{total_available} MOVE groups available ({counts_str}), taking top {taking}")
        print()

        run_record["discovery"] = {
            "total_available": total_available,
            "taking": taking,
            "source_counts": source_counts,
        }

        if not candidates:
            print("No eligible candidates found.")
            run_record["summary"] = {"planned": 0, "blocked": 0, "applied": 0, "verified": 0, "freed_bytes": 0, "exit_code": 0}
            print(f"log  {log_path}")
            _stdout_ctx.__exit__(None, None, None)
            _logger.dump_json(json_path, extra=run_record)
            _logger.close()
            return 0

        executor = DemotionExecutor(catalog_path=catalog_path)

        # Acquire lock only for apply
        lock_fh = None
        if do_apply:
            lock_fh = _acquire_rehome_lock()

        planned_count = 0
        blocked_count = 0
        applied_count = 0
        verified_count = 0
        freed_bytes = 0
        cleanup_pending_count = 0
        exit_code = 0

        try:
            for idx, cand in enumerate(candidates, 1):
                phash = cand["payload_hash"]
                src_bytes = cand["source_bytes"]
                torrent_count = cand["torrent_count"]
                src_id = cand["source_device_id"]
                src_root = cand.get("source_root", active_root)
                src_alias = cand.get("source_alias", "?")

                print(f"[{idx}/{taking}]  {phash[:16]}...  "
                      f"{_fmt_bytes(src_bytes)} · {torrent_count} torrent(s)"
                      + (f"  [{src_alias}]" if len(sources) > 1 else ""))

                cand_rec: dict = {
                    "payload_hash": phash,
                    "source_alias": src_alias,
                    "source_device_id": src_id,
                    "source_bytes": src_bytes,
                    "torrent_count": torrent_count,
                    "plan": None,
                    "check": None,
                    "apply": None,
                    "verify": None,
                }

                # Build per-candidate planner (source may vary across candidates)
                planner = _make_planner(
                    catalog_path=catalog_path,
                    active_device_id=active_device_id,
                    dest_device_id=dest_device_id,
                    source_id=src_id,
                    source_root=src_root,
                    dest_root=dest_root,
                    content_root=content_root,
                    active_root=active_root,
                )

                # ── Plan ────────────────────────────────────────────────────
                t_plan = datetime.now()
                try:
                    if dest_device_id == active_device_id:
                        plan = planner.plan_batch_promotion_by_payload_hash(phash)
                    else:
                        plan = planner.plan_batch_demotion_by_payload_hash(phash)
                except Exception as e:
                    plan_elapsed = (datetime.now() - t_plan).total_seconds()
                    print(f"  plan    ERROR: {e}")
                    cand_rec["plan"] = {"decision": "ERROR", "ok": False, "elapsed_s": round(plan_elapsed, 3), "error": str(e)}
                    run_record["candidates"].append(cand_rec)
                    exit_code = 1
                    continue

                plan_elapsed = (datetime.now() - t_plan).total_seconds()
                decision = plan.get("decision", "?")
                target = plan.get("target_path") or "?"
                reasons = plan.get("reasons", [])
                target_display = (target[:60] + "...") if len(target) > 63 else target

                if decision in ("MOVE", "REUSE"):
                    arrow = "→" if decision == "MOVE" else "≡"
                    print(f"  plan    {decision} {arrow} {target_display:<50}  OK")
                    # Save plan JSON
                    plan_log_dir.mkdir(parents=True, exist_ok=True)
                    plan_file = plan_log_dir / f"{timestamp}-{phash[:16]}.json"
                    plan_file.write_text(json.dumps(plan, indent=2))
                    cand_rec["plan"] = {
                        "decision": decision,
                        "target_path": target,
                        "reasons": reasons,
                        "ok": True,
                        "elapsed_s": round(plan_elapsed, 3),
                        "plan_file": str(plan_file),
                    }
                elif decision == "BLOCK":
                    print(f"  plan    BLOCK: {reasons[0] if reasons else '?'}")
                    cand_rec["plan"] = {
                        "decision": "BLOCK",
                        "reasons": reasons,
                        "ok": False,
                        "elapsed_s": round(plan_elapsed, 3),
                    }
                    run_record["candidates"].append(cand_rec)
                    blocked_count += 1
                    exit_code = 1
                    print()
                    continue
                else:
                    print(f"  plan    {decision}: skipping")
                    cand_rec["plan"] = {"decision": decision, "ok": False, "elapsed_s": round(plan_elapsed, 3)}
                    run_record["candidates"].append(cand_rec)
                    print()
                    continue

                planned_count += 1

                # ── Dry-run check ────────────────────────────────────────────
                check_buf = io.StringIO()
                check_ok = True
                t_check = datetime.now()
                try:
                    with contextlib.redirect_stdout(check_buf):
                        executor.dry_run(plan)
                    check_elapsed = (datetime.now() - t_check).total_seconds()
                    print(f"  check   dryrun{'':<44}  OK")
                    cand_rec["check"] = {"ok": True, "elapsed_s": round(check_elapsed, 3), "error": None}
                except Exception as e:
                    check_elapsed = (datetime.now() - t_check).total_seconds()
                    print(f"  check   dryrun FAIL: {e}")
                    cand_rec["check"] = {"ok": False, "elapsed_s": round(check_elapsed, 3), "error": str(e)}
                    check_ok = False
                    exit_code = 1

                if not check_ok:
                    run_record["candidates"].append(cand_rec)
                    print()
                    continue

                # ── Apply ────────────────────────────────────────────────────
                if do_apply:
                    t_apply = datetime.now()
                    apply_ok = True
                    try:
                        executor.execute(plan)
                        apply_elapsed = (datetime.now() - t_apply).total_seconds()
                        decision = str(plan.get("decision") or "").strip().upper()
                        cleanup_pending = bool(plan.get("cleanup_source_deferred"))
                        if decision == "REUSE":
                            cleanup_label = "cleanup pending" if cleanup_pending else "source gone"
                            print(
                                f"  apply   {_fmt_bytes(src_bytes)} · {_fmt_elapsed(apply_elapsed)} · {cleanup_label}"
                                f"{'':>9}  OK"
                            )
                            cand_rec["apply"] = {
                                "ok": True,
                                "elapsed_s": round(apply_elapsed, 3),
                                "freed_bytes": 0,
                                "source_cleanup": "pending_manual_cleanup" if cleanup_pending else "already_absent",
                                "error": None,
                            }
                            if cleanup_pending:
                                cleanup_pending_count += 1
                        else:
                            print(
                                f"  apply   {_fmt_bytes(src_bytes)} · {_fmt_elapsed(apply_elapsed)} · source deleted"
                                f"{'':>10}  OK"
                            )
                            cand_rec["apply"] = {
                                "ok": True,
                                "elapsed_s": round(apply_elapsed, 3),
                                "freed_bytes": src_bytes,
                                "source_cleanup": "source_deleted",
                                "error": None,
                            }
                            freed_bytes += src_bytes
                        applied_count += 1
                    except Exception as e:
                        apply_elapsed = (datetime.now() - t_apply).total_seconds()
                        print(f"  apply   FAIL after {_fmt_elapsed(apply_elapsed)}: {e}")
                        cand_rec["apply"] = {
                            "ok": False,
                            "elapsed_s": round(apply_elapsed, 3),
                            "freed_bytes": 0,
                            "source_cleanup": "unknown",
                            "error": str(e),
                        }
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
                                    executor.qbit_client, verify_conn, plan, dest_device_id
                                )
                            finally:
                                verify_conn.close()
                        except Exception as e:
                            verify_ok = False
                            verify_summary = f"ERROR: {e}"

                        status = "OK" if verify_ok else "FAIL"
                        print(f"  verify  {verify_summary:<52}  {status}")
                        cand_rec["verify"] = {"ok": verify_ok, "summary": verify_summary, "error": None if verify_ok else verify_summary}
                        if verify_ok:
                            verified_count += 1
                        else:
                            exit_code = 1
                else:
                    print(f"  apply   skipped")

                run_record["candidates"].append(cand_rec)
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
        summary_line = (
            f"applied  {applied_count}/{taking}   "
            f"verified  {verified_count}/{taking}   "
            f"freed  {_fmt_bytes(freed_bytes)} from sources"
        )
        if cleanup_pending_count:
            summary_line += f"   cleanup pending  {cleanup_pending_count}"
        print(summary_line)
    else:
        print(
            f"dry-run  {planned_count}/{taking} planned  "
            f"{planned_count}/{taking} checked"
        )
        print(f"To apply: hashall rehome auto --limit {limit} --apply")

    run_record["summary"] = {
        "planned": planned_count,
        "blocked": blocked_count,
        "applied": applied_count,
        "verified": verified_count,
        "freed_bytes": freed_bytes,
        "cleanup_pending": cleanup_pending_count,
        "exit_code": exit_code,
    }

    print(f"log  {log_path}")
    _stdout_ctx.__exit__(None, None, None)
    _logger.dump_json(json_path, extra=run_record)
    _logger.close()
    return exit_code
