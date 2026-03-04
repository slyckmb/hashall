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
    active_root: str = "",
    dest_root: str = "",
    active_device: str = "",
    dest_device: str = "",
    workers: int = 8,
    apply_dedup: bool = False,
    skip_dedup: bool = False,
    managed_roots: "list[tuple[str, str]]" = [],
    # Backwards-compat params (old names)
    seeding_root: "str | None" = None,
    pool_payload_root: "str | None" = None,
    stash_device: "str | None" = None,
    pool_device: "str | None" = None,
    extra_roots: "list[tuple[str, str]] | None" = None,
) -> int:
    """
    Preflight refresh: scan all managed roots, upgrade SHA256 for collision groups,
    optionally dedup (plan + dry-run, or execute), then sync qBit payloads.

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

    # Build the full ordered root list for display + preflight validation
    all_roots: list[tuple[str, str, str]] = [
        (active_root, active_device, "active"),
        (dest_root, dest_device, "dest"),
    ]
    if active_root == dest_root:
        all_roots = all_roots[:1]
    for p, a in (managed_roots or []):
        all_roots.append((p, a, "managed"))

    dedup_mode = "execute" if apply_dedup else ("plan+dry-run" if not skip_dedup else "off")

    print(f"\nRehome Refresh  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  catalog  {catalog_path}")
    print(f"  workers  {workers}")
    print(f"  dedup    {dedup_mode}")
    print(f"\n  Scan roots ({len(all_roots)}):")
    for i, (path, alias, role) in enumerate(all_roots, 1):
        print(f"    [{i}] {alias:<20} {role:<7}  {path}")

    _validate_refresh_roots(catalog_path, all_roots)

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
                m = re.search(r"plan_id=(\d+)", stdout)
                if m:
                    plan_id = m.group(1)
                    execute_cmd = [
                        python, "-m", "hashall.cli", "link", "execute", plan_id,
                    ] + db_args
                    if not apply_dedup:
                        execute_cmd.append("--dry-run")
                    label = f"link execute plan_id={plan_id} ({managed_alias})" + (
                        "" if apply_dedup else " [dry-run]"
                    )
                    ok, _ = _run_step(label, execute_cmd)
                    overall_ok = overall_ok and ok
                else:
                    print(f"  [refresh] no plan_id in link plan output for {managed_alias} — skipping execute")

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
                    print(f"  [refresh] no plan_id in link plan output for {dev_alias} — skipping execute")

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

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode_label = "apply" if do_apply else "dry-run"

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

        # Print sources with role labels
        for i, (sid, salias, _spath) in enumerate(sources, 1):
            sinfo = _device_info(conn, sid)
            role_label = "active — hardlink check applies" if sid == active_device_id else "storage"
            if is_promotion:
                role_label = "storage → active (promotion)"
            print(f"  sources  [{i}] {salias:<20} (id={sid}, {sinfo['mount']})  {role_label}")

        print(f"  mode     {mode_label}" + (
            "" if do_apply else "  (add --apply to execute)"
        ))
        print()

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

        if not candidates:
            print("No eligible candidates found.")
            return 0

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
                src_bytes = cand["source_bytes"]
                torrent_count = cand["torrent_count"]
                src_id = cand["source_device_id"]
                src_root = cand.get("source_root", active_root)
                src_alias = cand.get("source_alias", "?")

                print(f"[{idx}/{taking}]  {phash[:16]}...  "
                      f"{_fmt_bytes(src_bytes)} · {torrent_count} torrent(s)"
                      + (f"  [{src_alias}]" if len(sources) > 1 else ""))

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
                try:
                    if dest_device_id == active_device_id:
                        plan = planner.plan_batch_promotion_by_payload_hash(phash)
                    else:
                        plan = planner.plan_batch_demotion_by_payload_hash(phash)
                except Exception as e:
                    print(f"  plan    ERROR: {e}")
                    run_log.append({"payload_hash": phash, "stage": "plan", "error": str(e)})
                    exit_code = 1
                    continue

                decision = plan.get("decision", "?")
                target = plan.get("target_path") or "?"
                target_display = (target[:60] + "...") if len(target) > 63 else target
                if decision in ("MOVE", "REUSE"):
                    arrow = "→" if decision == "MOVE" else "≡"
                    print(f"  plan    {decision} {arrow} {target_display:<50}  OK")
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
                        print(f"  apply   {_fmt_bytes(src_bytes)} · {_fmt_elapsed(elapsed)} · source deleted"
                              f"{'':>10}  OK")
                        applied_count += 1
                        freed_bytes += src_bytes
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
                                    executor.qbit_client, verify_conn, plan, dest_device_id
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
            f"freed  {_fmt_bytes(freed_bytes)} from sources"
        )
        run_log_dir.mkdir(parents=True, exist_ok=True)
        log_file = run_log_dir / f"{timestamp}.json"
        log_file.write_text(json.dumps({
            "timestamp": timestamp,
            "active_device_id": active_device_id,
            "dest_device_id": dest_device_id,
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
