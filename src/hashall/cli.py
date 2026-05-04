# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/cli.py
# ✅ Minimal fix: Added --no-export, fixed missing arg to verify_trees

import click
import hashlib
import time
import os
import re
import sys
import threading
import shutil
import subprocess
import grp
import json
from pathlib import Path
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify_trees import verify_trees
from hashall.hash_progress import HashProgressReporter
from hashall.progress import TwoLineProgress
from hashall.device import get_files_table_name
from hashall.rt_cache import (
    DEFAULT_RT_SHARED_CACHE_FILE,
    DEFAULT_RT_SHARED_CACHE_META_FILE,
)
from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    live_rt_root_paths,
    load_rt_inventory_rows,
)
from hashall import __version__

DEFAULT_DB_PATH = Path.home() / ".hashall" / "catalog.db"
DEFAULT_JDUPES_LOG_DIR = Path.home() / ".logs" / "hashall" / "jdupes"
DEFAULT_PERMS_LOG_DIR = Path.home() / ".logs" / "hashall" / "perms"

_LOG_SETUP = False
_LOG_FILE = None
_LOG_PATH = None
_RUN_HEADER_EMITTED = False
_PIPE_BROKEN = False

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _payload_sync_upgrade_state_dir() -> Path:
    return Path.home() / ".hashall" / "payload-sync-upgrade-state"


def _payload_sync_upgrade_scope(
    *,
    db_path: Path,
    source: str = "qb",
    path_prefixes: list[Path],
    category: str | None,
    tag: str | None,
    limit: int,
    upgrade_order: str,
    upgrade_root_limit: int,
) -> str:
    payload = {
        "db_path": str(db_path.expanduser().resolve()),
        "source": str(source or "qb").lower(),
        "path_prefixes": [str(Path(p)) for p in path_prefixes],
        "category": str(category or ""),
        "tag": str(tag or ""),
        "limit": int(limit or 0),
        "upgrade_order": str(upgrade_order or "small-first").lower(),
        "upgrade_root_limit": int(upgrade_root_limit or 0),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _payload_sync_upgrade_root_key(item: dict) -> str:
    return f"{int(item.get('device_id') or 0)}::{str(item.get('root_path') or '')}"


def _payload_sync_upgrade_state_path(scope: str) -> Path:
    safe_scope = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(scope or "").strip()) or "default"
    return _payload_sync_upgrade_state_dir() / f"{safe_scope}.json"


def _load_payload_sync_upgrade_state(state_path: Path) -> dict:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"completed_roots": {}}
    except Exception:
        return {"completed_roots": {}}
    completed = data.get("completed_roots")
    if not isinstance(completed, dict):
        completed = {}
    return {"completed_roots": dict(completed)}


def _write_payload_sync_upgrade_state(state_path: Path, state: dict) -> None:
    _payload_sync_upgrade_state_dir().mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(state_path)


def _prune_unseen_incomplete_rt_instances(conn, *, seen_hashes: set[str]) -> dict[str, int]:
    """
    Remove stale incomplete RT rows that were not present in the current session load.

    Restrict this to zero-file incomplete payload links so complete mappings and any
    active content-bearing rows remain untouched.
    """
    rows = conn.execute(
        """
        SELECT ti.torrent_hash, ti.payload_id
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE p.status = 'incomplete' AND p.file_count = 0
        """
    ).fetchall()
    stale_hashes = [str(row[0]) for row in rows if str(row[0]) not in seen_hashes]
    stale_payload_ids = {int(row[1]) for row in rows if str(row[0]) not in seen_hashes}
    if stale_hashes:
        placeholders = ",".join(["?"] * len(stale_hashes))
        conn.execute(
            f"DELETE FROM torrent_instances WHERE torrent_hash IN ({placeholders})",
            stale_hashes,
        )
    return {
        "torrent_instances": len(stale_hashes),
        "payload_candidates": len(stale_payload_ids),
    }


def _payload_sync_recount_for_hashes(conn, *, torrent_hashes: set[str]) -> dict[str, int]:
    if not torrent_hashes:
        return {"complete": 0, "incomplete": 0, "missing_in_catalog": 0}
    placeholders = ",".join(["?"] * len(torrent_hashes))
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN p.status = 'complete' THEN 1 ELSE 0 END) AS complete_count,
            SUM(CASE WHEN p.status != 'complete' THEN 1 ELSE 0 END) AS incomplete_count,
            SUM(CASE WHEN p.file_count = 0 THEN 1 ELSE 0 END) AS missing_count
        FROM torrent_instances ti
        JOIN payloads p ON p.payload_id = ti.payload_id
        WHERE ti.torrent_hash IN ({placeholders})
        """,
        sorted(torrent_hashes),
    ).fetchone()
    complete_count, incomplete_count, missing_count = row or (0, 0, 0)
    return {
        "complete": int(complete_count or 0),
        "incomplete": int(incomplete_count or 0),
        "missing_in_catalog": int(missing_count or 0),
    }


def _find_matching_complete_payload_id(
    conn,
    *,
    root_name: str,
    expected_file_count: int,
    expected_total_bytes: int,
    save_path: str,
    torrent_hash: str = "",
) -> int | None:
    """
    Return a uniquely matching complete payload for a dead RT root when possible.

    Matching is intentionally strict: expected file count and total bytes must match,
    and the payload root must end with the torrent root name. If a provider hint from
    the save path narrows the candidate set to one row, use it; otherwise only accept
    a globally unique match.
    """
    root_name = str(root_name or "").strip()
    if not root_name or expected_file_count <= 0 or expected_total_bytes < 0:
        return None

    rows = conn.execute(
        """
        SELECT payload_id, root_path
        FROM payloads
        WHERE status = 'complete' AND file_count = ? AND total_bytes = ?
        """,
        (int(expected_file_count), int(expected_total_bytes)),
    ).fetchall()
    if not rows:
        return None

    root_candidates = []
    suffix = f"/{root_name}"
    nested_suffix = f"/{root_name}/"
    normalized_hash = str(torrent_hash or "").strip().lower()
    for payload_id, root_path in rows:
        root_path = str(root_path or "")
        normalized_root = root_path.rstrip(" /")
        if normalized_root.endswith(suffix) or nested_suffix in normalized_root:
            root_candidates.append((int(payload_id), root_path))
    if not root_candidates:
        return None
    if len(root_candidates) == 1:
        return root_candidates[0][0]

    if normalized_hash:
        hashed = [
            (payload_id, root_path)
            for payload_id, root_path in root_candidates
            if f"/{normalized_hash}/" in str(root_path or "").lower()
        ]
        if len(hashed) == 1:
            return hashed[0][0]

    save_parts = [part for part in Path(str(save_path or "")).parts if part]
    generic_parts = {
        "downloads", "complete", "cross-seed", "_qb-finish", "_qb-unique-repair",
        "seeding", "torrents", "data", "media", "stash", "pool",
    }
    provider_hints = [
        part for part in reversed(save_parts)
        if part not in generic_parts and part != root_name
    ]
    for hint in provider_hints:
        hinted = [(payload_id, root_path) for payload_id, root_path in root_candidates if hint in root_path]
        if len(hinted) == 1:
            return hinted[0][0]
    return None


def _iter_files_tables(conn) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'files_%' ORDER BY name"
        ).fetchall()
    ]


def _collect_complete_payload_candidates(
    conn,
    *,
    root_name: str,
    expected_file_count: int,
    expected_total_bytes: int,
    limit: int = 10,
) -> list[dict]:
    root_name = str(root_name or "").strip()
    if not root_name:
        return []
    rows = conn.execute(
        """
        SELECT payload_id, payload_hash, root_path, file_count, total_bytes, status
        FROM payloads
        WHERE status = 'complete'
          AND file_count = ?
          AND total_bytes = ?
        ORDER BY payload_id
        """,
        (int(expected_file_count or 0), int(expected_total_bytes or 0)),
    ).fetchall()
    suffix = f"/{root_name}"
    nested_suffix = f"/{root_name}/"
    out = []
    for row in rows:
        root_path = str(row[2] or "")
        normalized_root = root_path.rstrip(" /")
        if normalized_root.endswith(suffix) or nested_suffix in normalized_root:
            out.append(
                {
                    "payload_id": int(row[0]),
                    "payload_hash": row[1],
                    "root_path": root_path,
                    "file_count": int(row[3] or 0),
                    "total_bytes": int(row[4] or 0),
                    "status": row[5],
                }
            )
        if len(out) >= limit:
            break
    return out


def _collect_sidecar_hits(conn, *, root_name: str, limit: int = 20) -> dict[str, list[dict]]:
    root_name = str(root_name or "").strip()
    if not root_name:
        return {"nfo": [], "txt": [], "sample_mkv": []}
    patterns = {
        "nfo": f"%{root_name}%.nfo",
        "txt": f"%{root_name}%.txt",
        "sample_mkv": f"%{root_name}%Sample.mkv",
    }
    tables = _iter_files_tables(conn)
    out: dict[str, list[dict]] = {key: [] for key in patterns}
    for label, pattern in patterns.items():
        hits = []
        for table in tables:
            rows = conn.execute(
                f"SELECT path, size, status, sha256 FROM {table} WHERE path LIKE ? ORDER BY size DESC LIMIT ?",
                (pattern, int(limit)),
            ).fetchall()
            for row in rows:
                hits.append(
                    {
                        "path": str(row[0]),
                        "size": int(row[1] or 0),
                        "status": str(row[2] or ""),
                        "sha256": row[3],
                    }
                )
        hits.sort(key=lambda item: (item["size"], item["path"]), reverse=True)
        out[label] = hits[:limit]
    return out


def _build_rt_repair_worksheet_rows(conn, *, session_dir: Path, hash_filters: list[str] | None = None) -> list[dict]:
    rt_rows = {row.torrent_hash: row for row in load_rt_inventory_rows(session_dir)}
    requested = [str(item).strip().lower() for item in (hash_filters or []) if str(item).strip()]
    if requested:
        hashes = requested
    else:
        hashes = [
            str(row[0]).strip().lower()
            for row in conn.execute(
                """
                SELECT ti.torrent_hash
                FROM torrent_instances ti
                JOIN payloads p ON p.payload_id = ti.payload_id
                WHERE p.status = 'incomplete' AND p.file_count = 0
                ORDER BY ti.torrent_hash
                """
            ).fetchall()
        ]

    out = []
    for torrent_hash in hashes:
        rt_row = rt_rows.get(torrent_hash)
        ti_row = conn.execute(
            """
            SELECT ti.torrent_hash, ti.payload_id, ti.save_path, ti.root_name, ti.category, ti.tags,
                   p.root_path, p.file_count, p.total_bytes, p.status
            FROM torrent_instances ti
            LEFT JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE ti.torrent_hash = ?
            """,
            (torrent_hash,),
        ).fetchone()
        root_name = ""
        if rt_row is not None:
            root_name = str(rt_row.root_name or "").strip()
        elif ti_row is not None:
            root_name = str(ti_row[3] or "").strip()
        expected_file_count = int(getattr(rt_row, "expected_file_count", 0) or 0)
        expected_total_bytes = int(getattr(rt_row, "expected_total_bytes", 0) or 0)
        candidate_rows = _collect_complete_payload_candidates(
            conn,
            root_name=root_name,
            expected_file_count=expected_file_count,
            expected_total_bytes=expected_total_bytes,
        )
        sidecar_hits = _collect_sidecar_hits(conn, root_name=root_name)
        out.append(
            {
                "torrent_hash": torrent_hash,
                "root_name": root_name,
                "rt_present": rt_row is not None,
                "rt_save_path": str(getattr(rt_row, "save_path", "") or ""),
                "rt_content_path": str(getattr(rt_row, "content_path", "") or ""),
                "expected_file_count": expected_file_count,
                "expected_total_bytes": expected_total_bytes,
                "catalog_payload_id": int(ti_row[1]) if ti_row and ti_row[1] is not None else None,
                "catalog_payload_root": str(ti_row[6] or "") if ti_row else "",
                "catalog_payload_status": str(ti_row[9] or "") if ti_row else "",
                "complete_candidates": candidate_rows,
                "sidecar_hits": sidecar_hits,
            }
        )
    return out


def _rt_current_client_path(row: dict) -> str:
    return str(row.get("rt_content_path") or row.get("rt_save_path") or "").strip()


def _build_rt_repair_assistant_row(row: dict) -> dict:
    current_client_path = _rt_current_client_path(row)
    current_path_exists = bool(current_client_path and Path(current_client_path).exists())
    rt_present = bool(row.get("rt_present"))
    catalog_status = str(row.get("catalog_payload_status") or "").strip()
    candidates = list(row.get("complete_candidates") or [])
    exact_candidates = [
        candidate
        for candidate in candidates
        if int(candidate.get("file_count") or 0) == int(row.get("expected_file_count") or 0)
        and int(candidate.get("total_bytes") or 0) == int(row.get("expected_total_bytes") or 0)
    ]

    broken_reasons: list[str] = []
    if not rt_present:
        broken_reasons.append("rt_missing")
    if current_client_path and not current_path_exists:
        broken_reasons.append("current_path_missing")
    if catalog_status != "complete":
        broken_reasons.append("catalog_incomplete")

    broken_now = bool(broken_reasons)
    best_candidate_path = ""
    confidence = "low"
    safe_to_mutate = "no"
    why_parts: list[str] = []

    if not broken_now:
        why_parts.append("current_rt_path_exists and catalog is complete")
    elif len(exact_candidates) == 1:
        best_candidate_path = str(exact_candidates[0].get("root_path") or "").strip()
        candidate_exists = bool(best_candidate_path and Path(best_candidate_path).exists())
        if candidate_exists:
            confidence = "high"
            why_parts.append("single exact complete candidate")
            if "current_path_missing" in broken_reasons or current_client_path != best_candidate_path:
                safe_to_mutate = "yes"
                why_parts.append("candidate exists and differs from broken current path")
            else:
                safe_to_mutate = "no"
                why_parts.append("candidate matches current path")
        else:
            confidence = "medium"
            why_parts.append("single exact candidate but path missing")
    elif len(exact_candidates) > 1:
        confidence = "low"
        why_parts.append(f"ambiguous exact candidates={len(exact_candidates)}")
    elif candidates:
        confidence = "low"
        why_parts.append("complete candidates exist but exact proof is insufficient")
    else:
        confidence = "low"
        why_parts.append("no complete candidate found")

    if broken_reasons:
        why_parts.insert(0, "broken:" + ",".join(broken_reasons))

    return {
        "broken_now": broken_now,
        "current_client_path": current_client_path,
        "best_candidate_path": best_candidate_path,
        "confidence": confidence,
        "why": "; ".join(why_parts),
        "safe_to_mutate": safe_to_mutate,
    }


def _apply_low_priority() -> None:
    pid = os.getpid()
    try:
        os.nice(15)
        click.echo("🐢 Low priority: nice +15")
    except OSError as e:
        click.echo(f"⚠️  Could not set nice: {e}")
    try:
        ionice = shutil.which("ionice")
        if ionice:
            subprocess.run([ionice, "-c3", "-p", str(pid)], check=False)
            click.echo("🐢 Low priority: ionice idle")
        else:
            click.echo("⚠️  ionice not found; skipping IO priority")
    except Exception as e:
        click.echo(f"⚠️  Could not set ionice: {e}")


class _TeeStream:
    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary
        self.encoding = getattr(primary, "encoding", "utf-8")
        self._log_raw = os.environ.get("HASHALL_LOG_RAW") == "1"
        self._secondary_buf = ""

    def _write_secondary_sanitized(self, text: str) -> None:
        # Strip ANSI codes and collapse carriage-return updates into the final newline-delimited line.
        cleaned = _ANSI_ESCAPE_RE.sub("", text)
        for ch in cleaned:
            if ch == "\r":
                self._secondary_buf = ""
                continue
            if ch == "\n":
                self._secondary.write(self._secondary_buf + "\n")
                self._secondary_buf = ""
                continue
            code = ord(ch)
            if code < 32 and ch not in ("\t",):
                continue
            self._secondary_buf += ch

    def write(self, data):
        global _PIPE_BROKEN
        if _PIPE_BROKEN:
            return 0
        if isinstance(data, bytes):
            text = data.decode(self.encoding, errors="replace")
        else:
            text = str(data)
        try:
            result = self._primary.write(text)
        except BrokenPipeError:
            _PIPE_BROKEN = True
            return 0
        try:
            if self._log_raw:
                self._secondary.write(text)
            else:
                self._write_secondary_sanitized(text)
        except BrokenPipeError:
            _PIPE_BROKEN = True
        except Exception:
            pass
        return result

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        global _PIPE_BROKEN
        if _PIPE_BROKEN:
            return
        try:
            self._primary.flush()
        except BrokenPipeError:
            _PIPE_BROKEN = True
            return
        try:
            self._secondary.flush()
        except Exception:
            pass

    def isatty(self):
        return self._primary.isatty()

    def fileno(self):
        return self._primary.fileno()

    def writable(self):
        return True


def _setup_master_log() -> None:
    global _LOG_SETUP, _LOG_FILE, _LOG_PATH
    if _LOG_SETUP:
        return
    if os.environ.get("HASHALL_LOG_DISABLED") == "1":
        _LOG_SETUP = True
        return
    try:
        log_dir = os.environ.get("HASHALL_LOG_DIR")
        log_file = os.environ.get("HASHALL_LOG_FILE")
        if log_file:
            log_path = Path(os.path.expanduser(log_file))
        else:
            base_dir = Path(log_dir) if log_dir else (Path.home() / ".logs" / "hashall")
            log_path = base_dir / "hashall.log"
        _LOG_PATH = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        _LOG_SETUP = True
        return
    sys.stdout = _TeeStream(sys.stdout, _LOG_FILE)
    sys.stderr = _TeeStream(sys.stderr, _LOG_FILE)
    _LOG_SETUP = True


def _emit_run_header() -> None:
    global _RUN_HEADER_EMITTED
    if _RUN_HEADER_EMITTED:
        return
    argv = [str(arg) for arg in sys.argv[1:]]
    if "--json-output" in argv or argv[:2] == ["client-drift", "policy-template"]:
        _RUN_HEADER_EMITTED = True
        return
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    script = Path(sys.argv[0]).name or "hashall"
    argv_text = " ".join(argv)
    run_boundary = "═" * 68
    print(run_boundary)
    print(f"🧾 {script} v{__version__} @ {timestamp}")
    print(f"🧾 run_start pid={os.getpid()} argv={argv_text or '<none>'}")
    if _LOG_PATH:
        print(f"🧾 log: {_LOG_PATH}")
    print(run_boundary)
    _RUN_HEADER_EMITTED = True


# Initialize logging as early as possible for CLI usage.
if os.environ.get("HASHALL_LOG_DISABLED") != "1":
    _setup_master_log()

@click.group()
@click.version_option(__version__)
def cli():
    """Hashall — file hashing, verification, and migration tools"""
    _setup_master_log()
    _emit_run_header()
    pass

@cli.command("scan")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--parallel", is_flag=True, help="Use thread pool to hash faster.")
@click.option("--workers", type=int, default=None, help="Worker count for parallel scan (default: cpu_count).")
@click.option("--batch-size", type=int, default=None, help="Batch size for parallel DB writes.")
@click.option("--hash-mode", type=click.Choice(['fast', 'full', 'upgrade'], case_sensitive=False),
              default='fast', help="Hash mode: fast (1MB only), full (SHA256 + legacy SHA1), upgrade (add full to existing).")
@click.option("--fast", "hash_mode_flag", flag_value='fast', help="Shortcut for --hash-mode=fast")
@click.option("--full", "hash_mode_flag", flag_value='full', help="Shortcut for --hash-mode=full")
@click.option("--upgrade", "hash_mode_flag", flag_value='upgrade', help="Shortcut for --hash-mode=upgrade")
@click.option("--show-path", is_flag=True, help="Show current file path above progress bar.")
@click.option(
    "--scan-nested-datasets/--no-scan-nested-datasets",
    default=True,
    show_default=True,
    help="Detect nested mountpoints/datasets and scan them separately.",
)
@click.option(
    "--drift-policy",
    type=click.Choice(["metadata", "quick", "full"], case_sensitive=False),
    default="metadata",
    show_default=True,
    help="How aggressively to rehash files whose size+mtime appear unchanged.",
)
@click.option(
    "--hash-progress",
    type=click.Choice(["auto", "minimal", "full"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Hash progress detail level for full/upgrade hashing.",
)
@click.option("--low-priority", is_flag=True, help="Lower CPU/IO priority (nice +15, ionice idle).")
def scan_cmd(path, db, parallel, workers, batch_size, hash_mode, hash_mode_flag, show_path, scan_nested_datasets, drift_policy, hash_progress, low_priority):
    """Scan a directory and store file metadata in SQLite."""
    if low_priority:
        _apply_low_priority()
    # Use flag if provided, otherwise use hash_mode
    mode = hash_mode_flag if hash_mode_flag else hash_mode
    stats = scan_path(db_path=Path(db), root_path=Path(path), parallel=parallel,
                      workers=workers, batch_size=batch_size, hash_mode=mode,
                      show_current_path=show_path, scan_nested_datasets=scan_nested_datasets,
                      drift_policy=drift_policy.lower(),
                      hash_progress=hash_progress.lower())
    if getattr(stats, "safety_guard_triggered", False):
        raise click.ClickException(
            "Scan safety guard blocked deletion due path-resolution errors; "
            "catalog was preserved."
        )

@cli.command("export")
@click.argument("db_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--root", "-r", type=click.Path(exists=True, file_okay=False),
              help="Optional source root path for context")
@click.option("--out", "-o", type=click.Path(),
              help="Output JSON file (default ~/.hashall/hashall.json)")
def export_cmd(db_path, root, out):
    """Export metadata from SQLite to JSON."""
    export_json(db_path=Path(db_path),
                root_path=Path(root) if root else None,
                out_path=out)

@cli.command("verify-trees")
@click.argument("src", type=click.Path(exists=True, file_okay=False))
@click.argument("dst", type=click.Path(exists=True, file_okay=False))
@click.option("--repair", is_flag=True, help="Run rsync repair if mismatches found.")
@click.option("--rsync-source", type=click.Path(exists=True, file_okay=False),
              help="Alternate rsync source path.")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--force", is_flag=True, help="Actually perform scan and repair; otherwise dry-run.")
@click.option("--no-export", is_flag=True, help="Don't auto-write .hashall/hashall.json after scan.")
def verify_trees_cmd(src, dst, repair, rsync_source, db, force, no_export):
    """Verify that DST matches SRC, using SHA256 where available."""
    verify_trees(
        src_root=Path(src),
        dst_root=Path(dst),
        db_path=Path(db),
        repair=repair,
        dry_run=not force,
        rsync_source=Path(rsync_source) if rsync_source else None,
        auto_export=not no_export,
    )


@cli.group()
def doctor():
    """Safety and integrity diagnostics."""
    pass


@doctor.command("preflight")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--json-output", is_flag=True, help="Emit JSON report.")
@click.option(
    "--strict/--no-strict",
    default=True,
    show_default=True,
    help="Return non-zero when error-severity checks fail.",
)
def doctor_preflight(db, json_output, strict):
    """Run fail-closed catalog integrity checks used by migration/repair tooling."""
    from hashall.model import connect_db
    from hashall.preflight import run_catalog_preflight

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    report = run_catalog_preflight(conn)
    conn.close()

    if json_output:
        click.echo(json.dumps(report, indent=2))
    else:
        summary = report.get("summary", {})
        click.echo(
            "preflight "
            f"ok={bool(report.get('ok'))} "
            f"total_checks={int(summary.get('total_checks', 0) or 0)} "
            f"failed_error={int(summary.get('failed_error', 0) or 0)} "
            f"failed_warning={int(summary.get('failed_warning', 0) or 0)}"
        )
        for check in report.get("checks", []):
            status = "OK" if bool(check.get("ok")) else "FAIL"
            severity = str(check.get("severity") or "info").upper()
            name = str(check.get("name") or "unknown")
            msg = str(check.get("message") or "")
            click.echo(f"  [{status}] [{severity}] {name} - {msg}")

    if strict and not bool(report.get("ok")):
        raise click.ClickException("catalog preflight failed (error-severity checks)")


@doctor.command("repair-identity")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--apply", is_flag=True, help="Apply inferred device_id/fs_uuid repairs.")
@click.option(
    "--max-actions",
    type=int,
    default=0,
    show_default=True,
    help="Limit number of update actions (0 means no limit).",
)
@click.option(
    "--allow-bind-alias/--no-allow-bind-alias",
    default=True,
    show_default=True,
    help="Allow /data/media <-> /stash/media bind-alias inference.",
)
@click.option(
    "--report-json",
    type=click.Path(),
    default=None,
    help="Write full JSON report to this path.",
)
@click.option("--json-output", is_flag=True, help="Print full JSON report to stdout.")
def doctor_repair_identity(db, apply, max_actions, allow_bind_alias, report_json, json_output):
    """Repair stale identity rows using fs_uuid-first inference."""
    from hashall.identity_repair import run_identity_repair, write_report

    result = run_identity_repair(
        Path(db),
        apply_mode=bool(apply),
        max_actions=max(0, int(max_actions or 0)),
        allow_bind_aliases=bool(allow_bind_alias),
    )

    if report_json:
        out_path = write_report(result, Path(report_json))
        click.echo(f"report_json={out_path}")

    if json_output:
        click.echo(result.to_json().rstrip())
        return

    click.echo(
        "identity_repair "
        f"apply={str(bool(apply)).lower()} "
        f"payload_candidates={result.payload_candidates} "
        f"torrent_candidates={result.torrent_candidates} "
        f"scan_session_candidates={result.scan_session_candidates} "
        f"actions_planned={result.actions_planned} "
        f"actions_applied={result.actions_applied} "
        f"unresolved={result.unresolved_count}"
    )
    if result.reason_counts:
        click.echo("reason_counts:")
        for reason, count in result.reason_counts.items():
            click.echo(f"  {reason}={count}")
    if result.unresolved_samples:
        click.echo("unresolved_samples:")
        for item in result.unresolved_samples[:10]:
            click.echo(
                f"  table={item.get('table')} key={item.get('key')} "
                f"device_id={item.get('device_id')} fs_uuid={item.get('fs_uuid')} "
                f"path={item.get('path')}"
            )

# Payload command group
@cli.group()
def payload():
    """Payload identity and torrent mapping commands."""
    pass


@payload.command("sync")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--source",
    type=click.Choice(["qb", "rt"], case_sensitive=False),
    default="qb",
    show_default=True,
    help="Torrent client inventory source.",
)
@click.option("--qbit-url", default=None, help="qBittorrent URL (default: http://localhost:9003)")
@click.option("--qbit-user", default=None, help="qBittorrent username (default: admin)")
@click.option("--qbit-pass", default=None, help="qBittorrent password")
@click.option(
    "--rt-session-dir",
    type=click.Path(exists=True, file_okay=False),
    default=str(DEFAULT_RT_SESSION_DIR),
    show_default=True,
    help="rTorrent session directory for --source rt.",
)
@click.option("--category", default=None, help="Filter torrents by category")
@click.option("--tag", default=None, help="Filter torrents by tag")
@click.option(
    "--path-prefix",
    "path_prefixes",
    multiple=True,
    help="Only process torrents whose payload root is under this path (repeatable).",
)
@click.option(
    "--path-prefix-file",
    type=click.Path(exists=True),
    default=None,
    help="Read additional --path-prefix entries from a newline-delimited file.",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    show_default=True,
    help="Limit number of torrents processed (after filtering). 0 means no limit.",
)
@click.option("--dry-run", is_flag=True, help="Compute payload mapping but do not write to DB.")
@click.option("--upgrade-missing", is_flag=True,
              help="Hash missing SHA256s for payload files (inode-aware).")
@click.option("--parallel", is_flag=True, help="Parallel SHA256 hashing for --upgrade-missing.")
@click.option("--workers", type=int, default=None,
              help="Worker threads for --parallel (default: CPU count).")
@click.option(
    "--hash-progress",
    type=click.Choice(["auto", "minimal", "full"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Hash progress detail level for --upgrade-missing.",
)
@click.option(
    "--upgrade-order",
    type=click.Choice(["input", "small-first"], case_sensitive=False),
    default="small-first",
    show_default=True,
    help="Root processing order for --upgrade-missing.",
)
@click.option(
    "--upgrade-root-limit",
    type=int,
    default=0,
    show_default=True,
    help="Limit number of queued incomplete roots to hash-upgrade (0 means all).",
)
@click.option("--low-priority", is_flag=True, help="Lower CPU/IO priority (nice +15, ionice idle).")
def payload_sync(
    db,
    source,
    qbit_url,
    qbit_user,
    qbit_pass,
    rt_session_dir,
    category,
    tag,
    path_prefixes,
    path_prefix_file,
    limit,
    dry_run,
    upgrade_missing,
    parallel,
    workers,
    hash_progress,
    upgrade_order,
    upgrade_root_limit,
    low_priority,
):
    """
    Sync torrent instances from the selected client inventory and map to payloads.

    Connects to the selected client inventory source, retrieves torrent list, maps torrents
    to on-disk payload roots, computes payload hashes, and updates the database.

    This command is idempotent and can be run multiple times.
    """
    from hashall.model import connect_db
    from hashall.qbittorrent import get_qbittorrent_client
    from hashall.payload import (
        build_payload, upsert_payload, upsert_torrent_instance, TorrentInstance,
        upgrade_payload_missing_sha256, prune_orphan_payloads, count_missing_sha256_for_path,
        summarize_missing_sha256_for_path, get_payload_by_id,
    )
    from hashall.pathing import canonicalize_path, is_under, remap_to_mount_alias

    if low_priority:
        _apply_low_priority()

    # Connect to database
    # In dry-run mode, open read-only and skip migrations to guarantee "no writes".
    conn = connect_db(Path(db), read_only=dry_run, apply_migrations=not dry_run)

    source = str(source or "qb").lower()
    qbit = None
    inventory_rows: list[dict[str, str]] = []
    root_path_from_content_path = 0
    root_path_files_fallback_calls = 0

    if source == "qb":
        print("🔌 Connecting to qBittorrent...")
        qbit = get_qbittorrent_client(qbit_url, qbit_user, qbit_pass)

        if not qbit.test_connection():
            err = getattr(qbit, "last_error", None)
            msg = f"Failed to connect to qBittorrent at {qbit.base_url}"
            if err:
                msg = f"{msg}: {err}"
            msg = f"{msg}\nHint: uses QBITTORRENT_API_URL and /mnt/config/secrets/qbittorrent/api.env"
            raise click.ClickException(msg)

        if not qbit.login():
            err = getattr(qbit, "last_error", None)
            msg = "Failed to authenticate with qBittorrent"
            if err:
                msg = f"{msg}: {err}"
            raise click.ClickException(msg)

        print("✅ Connected to qBittorrent")
    else:
        if category or tag:
            raise click.ClickException("--category/--tag are only supported with --source qb")
        session_path = Path(rt_session_dir).expanduser()
        print(f"📥 Loading rTorrent session inventory from {session_path}...")
        inventory_rows = [
            {
                "hash": row.torrent_hash,
                "name": row.root_name,
                "save_path": row.save_path,
                "content_path": row.content_path,
                "expected_file_count": row.expected_file_count,
                "expected_total_bytes": row.expected_total_bytes,
                "category": "",
                "tags": "",
            }
            for row in load_rt_inventory_rows(session_path)
        ]
        print(f"✅ Loaded {len(inventory_rows)} rTorrent session rows")

    if dry_run and upgrade_missing:
        print("⚠️  DRY-RUN: ignoring --upgrade-missing (would modify DB)")
        upgrade_missing = False

    prefix_inputs = list(path_prefixes)
    if path_prefix_file:
        for raw in Path(path_prefix_file).read_text(encoding="utf-8").splitlines():
            cleaned = raw.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            prefix_inputs.append(cleaned)

    prefix_paths = []
    for p in prefix_inputs:
        try:
            prefix_paths.append(canonicalize_path(Path(p)))
        except Exception:
            prefix_paths.append(Path(p))

    def _canonicalize_payload_root_path(root_path: str) -> Path:
        """
        Normalize torrent roots onto the device preferred mount point when possible.

        qBittorrent may report paths under an alternate mount target (e.g. /data/media)
        while scans were performed under the preferred mount (e.g. /stash/media).
        """
        p = Path(root_path)
        if p.is_absolute():
            try:
                p = canonicalize_path(p)
            except Exception:
                p = Path(root_path)

        try:
            dev_id = os.stat(p).st_dev
        except (OSError, IOError):
            return p

        try:
            row = conn.execute(
                "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
                (dev_id,),
            ).fetchone()
        except Exception:
            row = None

        if row:
            mount_point = Path(row[0]) if row[0] else None
            preferred_mount = Path(row[1] or row[0]) if row[0] else None
            for base in (preferred_mount, mount_point):
                if base is None:
                    continue
                remapped = remap_to_mount_alias(p, base)
                if remapped is not None:
                    return remapped

        return p

    # Get torrents
    if source == "qb":
        print("📥 Fetching torrents...")
        torrents = qbit.get_torrents(category=category, tag=tag)
        print(f"   Found {len(torrents)} torrents")
        for torrent in torrents:
            root_path = qbit.get_torrent_root_path(torrent)
            if torrent.content_path:
                root_path_from_content_path += 1
            inventory_rows.append(
                {
                    "hash": torrent.hash,
                    "name": torrent.name,
                    "save_path": torrent.save_path,
                    "content_path": torrent.content_path,
                    "category": torrent.category,
                    "tags": torrent.tags,
                    "root_path": root_path,
                }
            )
        root_path_files_fallback_calls = getattr(qbit, "root_path_files_fallback_calls", 0)
    else:
        print("📥 Using preloaded rTorrent inventory rows...")
        print(f"   Found {len(inventory_rows)} torrents")
    seen_hashes = {
        str(torrent.get("hash") or "").strip()
        for torrent in inventory_rows
        if str(torrent.get("hash") or "").strip()
    }

    # Process each torrent
    synced_count = 0
    incomplete_count = 0
    missing_in_catalog = 0
    skipped_prefix = 0
    processed = 0
    checked = 0
    processed_torrent_hashes: set[str] = set()
    prune_stats = None
    stale_rt_stats = None
    write_batch_ops = 0
    write_batch_threshold = 400
    upgrade_queue: dict[str, dict] = {}
    upgrade_started = 0
    upgrade_completed = 0
    upgrade_failed = 0

    with TwoLineProgress(
        total=len(inventory_rows),
        prefix="📦 Syncing payloads",
        unit="torrents",
        enabled=not dry_run
    ) as progress:
        for torrent in inventory_rows:
            if limit and processed >= limit:
                break

            # Get torrent root path
            root_path = str(torrent.get("root_path") or torrent.get("content_path") or "").strip()
            root_canon = _canonicalize_payload_root_path(root_path)

            if prefix_paths:
                if not any(is_under(root_canon, pref) for pref in prefix_paths):
                    skipped_prefix += 1
                    checked += 1
                    if checked % 500 == 0:
                        print(
                            f"\n   ⏳ Prefix filter progress: checked={checked}/{len(inventory_rows)} "
                            f"processed={processed} skipped={skipped_prefix}"
                        )
                    progress.update(
                        desc=f"filtering checked={checked}/{len(inventory_rows)} "
                             f"processed={processed} skipped={skipped_prefix}",
                        advance=1,
                    )
                    continue

            torrent_name = str(
                torrent.get("name")
                or torrent.get("root_name")
                or ""
            ).strip()
            torrent_hash = str(torrent.get("hash") or "").strip()
            if torrent_hash:
                processed_torrent_hashes.add(torrent_hash)

            progress.update(desc=f"{torrent_name[:60]}", advance=0)

            print(f"\n🔄 Processing: {torrent_name[:50]}...")
            print(f"   Hash: {torrent_hash}")
            print(f"   Path: {root_path}")
            if str(root_canon) != root_path:
                print(f"   Canonical: {root_canon}")

            payload = build_payload(conn, str(root_canon), device_id=None, already_canonical=False)
            if source == "rt" and payload.file_count == 0:
                matched_payload_id = _find_matching_complete_payload_id(
                    conn,
                    root_name=torrent_name,
                    expected_file_count=int(torrent.get("expected_file_count") or 0),
                    expected_total_bytes=int(torrent.get("expected_total_bytes") or 0),
                    save_path=str(torrent.get("save_path") or ""),
                    torrent_hash=str(torrent.get("hash") or ""),
                )
                if matched_payload_id is not None:
                    matched_payload = get_payload_by_id(conn, matched_payload_id)
                    if matched_payload is not None:
                        payload = matched_payload
                        print(
                            f"   ♻️  Reused complete payload #{matched_payload_id}: "
                            f"{matched_payload.root_path}"
                        )
            if payload.file_count == 0:
                missing_in_catalog += 1

            if (not dry_run) and payload.status != 'complete' and upgrade_missing:
                key = str(root_canon)
                if key not in upgrade_queue:
                    missing_stats = {"files": 0, "bytes": 0}
                    if payload.device_id is not None:
                        try:
                            missing_stats = summarize_missing_sha256_for_path(conn, str(root_canon), payload.device_id)
                        except Exception:
                            missing_stats = {"files": 0, "bytes": 0}
                    upgrade_queue[key] = {
                        "root_path": key,
                        "device_id": payload.device_id,
                        "first_torrent": torrent_name,
                        "first_hash": torrent_hash,
                        "first_seen_order": processed,
                        "file_count": int(missing_stats.get("files") or payload.file_count or 0),
                        "total_bytes": int(missing_stats.get("bytes") or payload.total_bytes or 0),
                    }

            if not dry_run:
                # Insert/update payload
                payload_id = upsert_payload(conn, payload, commit=False)

                # Insert/update torrent instance
                torrent_instance = TorrentInstance(
                    torrent_hash=torrent_hash,
                    payload_id=payload_id,
                    device_id=payload.device_id,
                    fs_uuid=payload.fs_uuid,
                    save_path=str(torrent.get("save_path") or ""),
                    root_name=str(torrent.get("name") or ""),
                    category=str(torrent.get("category") or ""),
                    tags=str(torrent.get("tags") or ""),
                    last_seen_at=time.time()
                )
                upsert_torrent_instance(conn, torrent_instance, commit=False)
                write_batch_ops += 2
                if write_batch_ops >= write_batch_threshold:
                    conn.commit()
                    write_batch_ops = 0

            if payload.status == 'complete':
                print(f"   ✅ Payload complete (hash: {payload.payload_hash[:16]}...)")
                print(f"      {payload.file_count} files, {payload.total_bytes:,} bytes")
                synced_count += 1
            else:
                if (not dry_run) and upgrade_missing:
                    print("   ⚠️  Payload incomplete (missing SHA256s; queued for upgrade)")
                else:
                    print("   ⚠️  Payload incomplete (missing SHA256s)")
                incomplete_count += 1
            processed += 1
            checked += 1
            progress.update(advance=1)

    if (not dry_run) and upgrade_missing and upgrade_queue:
        print("------------------------------------------------------------")
        print("Phase: upgrade-hash-backfill")
        print("What this does: fill missing payload hashes after sync mapping is complete.")
        print("------------------------------------------------------------")
        upgrade_stage_start = time.monotonic()
        queue_items = list(upgrade_queue.values())
        queued_root_count = len(queue_items)
        order_mode = (upgrade_order or "small-first").lower()
        if order_mode == "small-first":
            queue_items.sort(
                key=lambda item: (
                    int(item.get("total_bytes") or 0) <= 0,
                    int(item.get("total_bytes") or 0),
                    int(item.get("file_count") or 0),
                    int(item.get("first_seen_order") or 0),
                )
            )
        else:
            queue_items.sort(key=lambda item: int(item.get("first_seen_order") or 0))

        if upgrade_root_limit > 0:
            queue_items = queue_items[:upgrade_root_limit]

        if write_batch_ops:
            conn.commit()
            write_batch_ops = 0

        upgrade_scope = _payload_sync_upgrade_scope(
            db_path=Path(db),
            source=source,
            path_prefixes=prefix_paths,
            category=category,
            tag=tag,
            limit=limit,
            upgrade_order=order_mode,
            upgrade_root_limit=upgrade_root_limit,
        )
        upgrade_state_path = _payload_sync_upgrade_state_path(upgrade_scope)
        upgrade_state = _load_payload_sync_upgrade_state(upgrade_state_path)
        completed_roots = upgrade_state["completed_roots"]
        skipped_resumed = 0
        skipped_zero_file_roots = 0
        pending_queue_items = []
        for item in queue_items:
            root_key = _payload_sync_upgrade_root_key(item)
            root_path = str(item.get("root_path") or "")
            device_id = int(item.get("device_id") or 0)
            if root_key in completed_roots and count_missing_sha256_for_path(conn, device_id, root_path) == 0:
                skipped_resumed += 1
                continue
            if device_id > 0:
                try:
                    missing_stats = summarize_missing_sha256_for_path(conn, root_path, device_id)
                except Exception:
                    missing_stats = {"files": 0, "bytes": 0}
                item["file_count"] = int(missing_stats.get("files") or 0)
                item["total_bytes"] = int(missing_stats.get("bytes") or 0)
            if int(item.get("file_count") or 0) <= 0:
                skipped_zero_file_roots += 1
                print(
                    f"   ⚠️  skipping zero-file upgrade root: root={root_path} "
                    f"device_id={device_id or 'unknown'}"
                )
                continue
            pending_queue_items.append(item)
        queue_items = pending_queue_items

        total_upgrade_roots = len(queue_items)
        total_upgrade_bytes = sum(max(0, int(item.get("total_bytes") or 0)) for item in queue_items)
        print(
            "\n🔧 Upgrade stage queued roots: "
            f"{total_upgrade_roots} order={order_mode} "
            f"total_bytes={total_upgrade_bytes:,}"
        )
        if upgrade_root_limit > 0:
            print(f"   upgrade root limit applied: {upgrade_root_limit}")
        if skipped_resumed:
            print(
                f"   resume checkpoint: skipped already-complete roots={skipped_resumed} "
                f"state={upgrade_state_path}"
            )
        if skipped_zero_file_roots:
            print(f"   zero-file roots skipped: {skipped_zero_file_roots}")

        for root_idx, item in enumerate(queue_items, start=1):
            root_path = str(item.get("root_path") or "")
            torrent_label = str(item.get("first_torrent") or "")
            torrent_hash = str(item.get("first_hash") or "")
            root_bytes = max(0, int(item.get("total_bytes") or 0))
            root_files = max(0, int(item.get("file_count") or 0))
            print(
                f"\n🔧 Upgrading root {root_idx}/{total_upgrade_roots}: "
                f"{Path(root_path).name or root_path}"
            )
            print(
                f"   root={root_path} files={root_files} bytes={root_bytes:,} "
                f"seed_torrent={torrent_hash[:16]}"
            )
            print(
                f"   upgrade_progress roots_done={root_idx - 1}/{total_upgrade_roots} "
                f"completed={upgrade_completed} failed={upgrade_failed}"
            )
            upgrade_started += 1

            hash_log_state = {
                "last_done": 0,
                "last_total": 0,
                "last_bytes_done": 0,
                "last_bytes_total": 0,
                "last_path": "",
                "done_event_seen": False,
            }
            hash_reporter = HashProgressReporter(label=torrent_label or root_path, mode=hash_progress.lower())
            heartbeat_stop = threading.Event()
            heartbeat_thread = None

            def _hash_progress(event, done, total, abs_path, **meta):
                hash_log_state["last_done"] = max(0, int(done or 0))
                hash_log_state["last_total"] = max(0, int(total or 0))
                hash_log_state["last_path"] = str(abs_path or hash_log_state["last_path"])
                hash_log_state["last_bytes_done"] = max(
                    0,
                    int(meta.get("hashed_bytes") or hash_log_state["last_bytes_done"]),
                )
                hash_log_state["last_bytes_total"] = max(
                    0,
                    int(meta.get("total_bytes") or hash_log_state["last_bytes_total"]),
                )
                if event == "done":
                    hash_log_state["done_event_seen"] = True
                if event == "start":
                    hash_reporter.start(
                        total_groups=hash_log_state["last_total"],
                        total_bytes=hash_log_state["last_bytes_total"],
                    )
                else:
                    hash_reporter.update(
                        event=event,
                        done_groups=hash_log_state["last_done"],
                        total_groups=hash_log_state["last_total"],
                        path=abs_path,
                        file_bytes_done=meta.get("group_bytes_done"),
                        file_bytes_total=meta.get("group_bytes_total"),
                        batch_bytes_done=hash_log_state["last_bytes_done"],
                        batch_bytes_total=hash_log_state["last_bytes_total"],
                    )
            if hash_progress.lower() == "full":
                def _heartbeat_loop():
                    while not heartbeat_stop.wait(5.0):
                        if hash_log_state["last_total"] <= 0:
                            continue
                        hash_reporter.update(
                            event="heartbeat",
                            done_groups=hash_log_state["last_done"],
                            total_groups=hash_log_state["last_total"],
                            path=hash_log_state["last_path"] or root_path,
                            batch_bytes_done=hash_log_state["last_bytes_done"],
                            batch_bytes_total=hash_log_state["last_bytes_total"],
                            force=True,
                        )

                heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
                heartbeat_thread.start()

            try:
                upgraded_groups = upgrade_payload_missing_sha256(
                    conn,
                    root_path,
                    device_id=item.get("device_id"),
                    parallel=parallel,
                    workers=workers,
                    progress_cb=_hash_progress,
                )
            except Exception as exc:
                upgrade_failed += 1
                print(f"   ❌ Upgrade failed: {exc}")
                continue
            finally:
                heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=0.2)

            if hash_log_state["last_total"] > 0 and not hash_log_state["done_event_seen"]:
                hash_reporter.finish(
                    done_groups=hash_log_state["last_done"],
                    total_groups=hash_log_state["last_total"],
                    batch_bytes_done=hash_log_state["last_bytes_done"],
                    batch_bytes_total=hash_log_state["last_bytes_total"],
                )

            refreshed = build_payload(conn, root_path, device_id=item.get("device_id"), already_canonical=False)
            upsert_payload(conn, refreshed, commit=False)
            write_batch_ops += 1
            if write_batch_ops >= write_batch_threshold:
                conn.commit()
                write_batch_ops = 0

            if refreshed.status == "complete":
                upgrade_completed += 1
                completed_roots[_payload_sync_upgrade_root_key(item)] = {
                    "root_path": root_path,
                    "device_id": int(item.get("device_id") or 0),
                    "completed_at": int(time.time()),
                    "payload_hash": str(refreshed.payload_hash or ""),
                }
                _write_payload_sync_upgrade_state(upgrade_state_path, upgrade_state)
                print(
                    f"   ✅ Upgrade complete: groups={upgraded_groups} "
                    f"payload_hash={str(refreshed.payload_hash or '')[:16]}"
                )
            else:
                print(f"   ⚠️  Upgrade ended incomplete: groups={upgraded_groups}")
        upgrade_elapsed = int(time.monotonic() - upgrade_stage_start)
        print(
            "upgrade_summary "
            f"queued={total_upgrade_roots} started={upgrade_started} "
            f"completed={upgrade_completed} failed={upgrade_failed} elapsed_s={upgrade_elapsed}"
        )
        if queued_root_count > 0 and upgrade_completed == 0 and upgrade_failed == 0 and total_upgrade_roots > 0:
            print(
                "   ⚠️  upgrade stage completed with zero successful roots; "
                "queued paths may not resolve to scanned files"
            )
        if upgrade_failed == 0 and total_upgrade_roots == upgrade_completed:
            try:
                upgrade_state_path.unlink()
            except FileNotFoundError:
                pass
        print("------------------------------------------------------------")

    if not dry_run and write_batch_ops:
        conn.commit()

    if (not dry_run) and source == "rt":
        stale_rt_stats = _prune_unseen_incomplete_rt_instances(conn, seen_hashes=seen_hashes)
        if stale_rt_stats["torrent_instances"]:
            conn.commit()
            print(
                "   🧹 pruned stale unseen rt rows: "
                f"torrent_instances={stale_rt_stats['torrent_instances']} "
                f"payload_candidates={stale_rt_stats['payload_candidates']}"
            )

    if (not dry_run) and limit == 0:
        prune_roots = [str(p) for p in prefix_paths] if prefix_paths else None
        try:
            prune_stats = prune_orphan_payloads(conn, roots=prune_roots, sample_limit=5)
        except Exception as exc:
            print(f"   ⚠️  orphan prune failed (non-fatal): {exc}")
            prune_stats = None

    if not dry_run:
        recount = _payload_sync_recount_for_hashes(conn, torrent_hashes=processed_torrent_hashes)
        synced_count = recount["complete"]
        incomplete_count = recount["incomplete"]
        missing_in_catalog = recount["missing_in_catalog"]

    if dry_run:
        print(f"\n✅ DRY-RUN complete (no DB changes)")
    else:
        print(f"\n✅ Sync complete!")
    print(f"   processed: {processed}")
    if prefix_paths:
        print(f"   skipped (path-prefix): {skipped_prefix}")
        if processed == 0 and len(inventory_rows) > 0:
            sample_prefixes = ", ".join(str(p) for p in prefix_paths[:3])
            print("   ⚠️  no torrents matched current path-prefix filters")
            print(f"      prefixes(sample): {sample_prefixes}")
            if source == "qb":
                print("      hint: verify canonical roots from qB content_path/save_path")
            else:
                print("      hint: verify rt session directory paths and mount aliases")
    print(f"   complete payloads: {synced_count}")
    print(f"   incomplete payloads: {incomplete_count}")
    print(f"   missing in catalog: {missing_in_catalog}")
    if source == "qb":
        print(
            "   root path source: "
            f"content_path={root_path_from_content_path}, "
            f"files_api_fallback={root_path_files_fallback_calls}"
        )
    else:
        print(f"   root path source: rt_session_rows={len(inventory_rows)}")
    if stale_rt_stats is not None:
        print(f"   stale unseen rt rows pruned: {stale_rt_stats['torrent_instances']}")
    if upgrade_missing and not dry_run:
        print(
            "   upgrade stage: "
            f"queued={total_upgrade_roots} started={upgrade_started} "
            f"completed={upgrade_completed} failed={upgrade_failed}"
        )
    if prune_stats is not None:
        print(
            "   orphan gc candidates: "
            f"{prune_stats['tracked_candidates']} "
            f"(new={prune_stats['new_candidates']}, aged={prune_stats['aged_candidates']})"
        )
        print(f"   orphan payloads pruned: {prune_stats['pruned']}")
        if prune_stats["kept_alias_ambiguous"] > 0:
            print(f"   orphan prune skipped (alias-ambiguous): {prune_stats['kept_alias_ambiguous']}")
        if prune_stats["block_reason"]:
            print(f"   orphan prune blocked: {prune_stats['block_reason']}")
        if prune_stats["samples"]:
            print(f"   pruned samples: {', '.join(prune_stats['samples'])}")
    elif (not dry_run) and limit > 0:
        print("   orphan payload prune: skipped (limit applied)")


def _payload_table_has_column(conn, table_name: str, column_name: str) -> bool:
    table_ident = _quote_sql_identifier(table_name)
    rows = conn.execute(f"PRAGMA table_info({table_ident})").fetchall()
    return any(row[1] == column_name for row in rows)


def _quote_sql_identifier(name: str) -> str:
    """Quote a SQLite identifier so dynamic table names stay syntactically safe."""
    return f'"{name.replace("\"", "\"\"")}"'


def _payload_root_relpath_for_device(root_path: str, mount_point: str | None, preferred_mount: str | None) -> str | None:
    if not Path(root_path).is_absolute():
        return root_path

    for base in (preferred_mount, mount_point):
        if not base:
            continue
        if root_path == base:
            return "."
        prefix = base.rstrip("/") + "/"
        if root_path.startswith(prefix):
            return root_path[len(prefix):]

    return None


def _batch_count_active_payload_roots(conn, keys: list[tuple[int, str]]) -> dict[tuple[int, str], int]:
    """Batch count active files under payload roots for unmanaged inventory."""
    if not keys:
        return {}

    out: dict[tuple[int, str], int] = {(device_id, root_path): 0 for device_id, root_path in keys}

    has_devices = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
    ).fetchone()
    device_mounts: dict[int, tuple[str | None, str | None]] = {}
    if has_devices:
        for row in conn.execute(
            "SELECT device_id, mount_point, preferred_mount_point FROM devices"
        ).fetchall():
            did = int(row[0])
            mount_point = row[1]
            preferred_mount = row[2] or row[1]
            device_mounts[did] = (mount_point, preferred_mount)

    by_device: dict[int, list[str]] = {}
    for device_id, root_path in keys:
        by_device.setdefault(int(device_id), []).append(root_path)

    for device_id, root_paths in by_device.items():
        table_name = get_files_table_name(conn.cursor(), device_id=device_id)
        if not table_name:
            continue
        table_ident = _quote_sql_identifier(table_name)
        if not conn.execute(
            "SELECT name FROM sqlite_master WHERE name=?",
            (table_name,),
        ).fetchone():
            continue

        status_clause = "f.status='active' AND " if _payload_table_has_column(conn, table_name, "status") else ""
        mount_point, preferred_mount = device_mounts.get(device_id, (None, None))

        rel_to_roots: dict[str, list[str]] = {}
        all_roots: list[str] = []
        for root_path in root_paths:
            rel_root = _payload_root_relpath_for_device(root_path, mount_point, preferred_mount)
            if rel_root is None:
                continue
            if rel_root == ".":
                all_roots.append(root_path)
            else:
                rel_to_roots.setdefault(rel_root, []).append(root_path)

        if all_roots:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_ident} f WHERE {status_clause}1=1"
            ).fetchone()
            count_all = int(row[0] or 0)
            for root_path in all_roots:
                out[(device_id, root_path)] = count_all

        if rel_to_roots:
            rel_root_counts: dict[str, int] = {rel_root: 0 for rel_root in rel_to_roots.keys()}
            rel_root_lookup = set(rel_root_counts.keys())
            path_rows = conn.execute(
                f"SELECT path FROM {table_ident} f WHERE {status_clause}1=1"
            ).fetchall()

            for row in path_rows:
                file_path = row[0]
                if not file_path:
                    continue

                if file_path in rel_root_lookup:
                    rel_root_counts[file_path] += 1

                idx = 0
                while True:
                    idx = file_path.find("/", idx)
                    if idx <= 0:
                        break
                    prefix = file_path[:idx]
                    if prefix in rel_root_lookup:
                        rel_root_counts[prefix] += 1
                    idx += 1

            for rel_root, count in rel_root_counts.items():
                for root_path in rel_to_roots.get(rel_root, []):
                    out[(device_id, root_path)] = int(count or 0)

    return out


@payload.command("unmanaged")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--path-prefix",
    "path_prefixes",
    multiple=True,
    help="Only include payload roots under this path (repeatable).",
)
@click.option(
    "--samples",
    type=int,
    default=5,
    show_default=True,
    help="Number of sample roots to print per bucket.",
)
def payload_unmanaged_cmd(db, path_prefixes, samples):
    """
    List payload rows that have no active torrent reference.

    Buckets:
    - true orphan: no torrent refs and no active catalog files under root
    - alias artifact: no torrent refs but active catalog files still exist under root
    """
    from hashall.model import connect_db
    from hashall.pathing import canonicalize_path

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)

    def _is_under_fast(path_str: str, prefix_str: str) -> bool:
        return path_str == prefix_str or path_str.startswith(prefix_str.rstrip("/") + "/")

    def _remap_mount(path_str: str, source_mount: str | None, target_mount: str | None) -> str | None:
        if not source_mount or not target_mount:
            return None
        if path_str == source_mount:
            return target_mount
        source_prefix = source_mount.rstrip("/") + "/"
        if path_str.startswith(source_prefix):
            suffix = path_str[len(source_prefix):]
            return target_mount.rstrip("/") + "/" + suffix
        return None

    prefix_strings = []
    prefix_paths_canon = []
    for p in path_prefixes:
        try:
            canon = canonicalize_path(Path(p))
            prefix_paths_canon.append(canon)
            prefix_strings.append(str(canon))
        except Exception:
            raw = Path(p)
            prefix_paths_canon.append(raw)
            prefix_strings.append(str(raw))

    device_mounts: dict[int, tuple[str | None, str | None]] = {}
    has_devices = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
    ).fetchone()
    if has_devices:
        for dev_row in conn.execute(
            "SELECT device_id, mount_point, preferred_mount_point FROM devices"
        ).fetchall():
            did = int(dev_row[0])
            mount_point = dev_row[1]
            preferred_mount = dev_row[2] or dev_row[1]
            device_mounts[did] = (mount_point, preferred_mount)

    rows = conn.execute(
        """
        SELECT p.payload_id, p.device_id, p.root_path, p.status, p.file_count, p.total_bytes
        FROM payloads p
        LEFT JOIN (
            SELECT payload_id, COUNT(*) AS ref_count
            FROM torrent_instances
            GROUP BY payload_id
        ) ti ON ti.payload_id = p.payload_id
        WHERE COALESCE(ti.ref_count, 0) = 0
        ORDER BY p.root_path
        """
    ).fetchall()

    skipped_prefix = 0
    filtered_rows = []
    for row in rows:
        root_path = row["root_path"]

        if prefix_strings:
            in_scope = any(_is_under_fast(root_path, pref) for pref in prefix_strings)

            if not in_scope and row["device_id"] is not None:
                mount_point, preferred_mount = device_mounts.get(int(row["device_id"]), (None, None))
                remapped = _remap_mount(root_path, mount_point, preferred_mount)
                if remapped is None:
                    remapped = _remap_mount(root_path, preferred_mount, mount_point)
                if remapped:
                    in_scope = any(_is_under_fast(remapped, pref) for pref in prefix_strings)

            if not in_scope:
                # Last-resort canonicalization for odd path cases.
                try:
                    root_canon = canonicalize_path(Path(root_path))
                    in_scope = any(
                        _is_under_fast(str(root_canon), str(pref_path))
                        for pref_path in prefix_paths_canon
                    )
                except Exception:
                    in_scope = False

            if not in_scope:
                skipped_prefix += 1
                continue

        filtered_rows.append(row)

    active_count_keys = [
        (int(row["device_id"]), row["root_path"])
        for row in filtered_rows
        if row["device_id"] is not None and int(row["file_count"] or 0) == 0
    ]
    live_counts = _batch_count_active_payload_roots(conn, active_count_keys)

    total = len(filtered_rows)
    true_orphan = 0
    alias_artifact = 0
    true_samples = []
    alias_samples = []

    for row in filtered_rows:
        root_path = row["root_path"]
        device_id = row["device_id"]
        live_count = int(row["file_count"] or 0)
        if live_count == 0 and device_id is not None:
            live_count = live_counts.get((int(device_id), root_path), 0)

        if live_count > 0:
            alias_artifact += 1
            if len(alias_samples) < samples:
                alias_samples.append(root_path)
        else:
            true_orphan += 1
            if len(true_samples) < samples:
                true_samples.append(root_path)

    print("🔎 Unmanaged payload inventory")
    print(f"   unmanaged payloads: {total}")
    if prefix_strings:
        print(f"   skipped (path-prefix): {skipped_prefix}")
    print(f"   true orphans (no refs + no active files): {true_orphan}")
    print(f"   alias artifacts (no refs + active files): {alias_artifact}")

    if true_samples:
        print(f"   true orphan samples: {', '.join(true_samples)}")
    if alias_samples:
        print(f"   alias artifact samples: {', '.join(alias_samples)}")

    conn.close()


@payload.command("orphan-audit")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--path-prefix",
    "path_prefixes",
    multiple=True,
    help="Only include payload roots under this path (repeatable).",
)
@click.option(
    "--samples",
    type=int,
    default=5,
    show_default=True,
    help="Number of sample roots to print per bucket.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON summary.")
def payload_orphan_audit_cmd(db, path_prefixes, samples, json_output):
    """Audit orphan payload state without deleting anything."""
    from hashall.model import connect_db
    from hashall.pathing import canonicalize_path
    from hashall.payload import ORPHAN_GC_MIN_SEEN_RUNS, ORPHAN_GC_MIN_AGE_SECONDS

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)

    def _is_under_fast(path_str, prefix_str):
        return path_str == prefix_str or path_str.startswith(prefix_str.rstrip("/") + "/")

    def _remap_mount(path_str, source_mount, target_mount):
        if not source_mount or not target_mount:
            return None
        if path_str == source_mount:
            return target_mount
        source_prefix = source_mount.rstrip("/") + "/"
        if path_str.startswith(source_prefix):
            suffix = path_str[len(source_prefix):]
            return target_mount.rstrip("/") + "/" + suffix
        return None

    prefix_strings = []
    prefix_paths_canon = []
    for p in path_prefixes:
        try:
            canon = canonicalize_path(Path(p))
            prefix_paths_canon.append(canon)
            prefix_strings.append(str(canon))
        except Exception:
            raw = Path(p)
            prefix_paths_canon.append(raw)
            prefix_strings.append(str(raw))

    device_mounts = {}
    has_devices = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
    ).fetchone()
    if has_devices:
        for dev_row in conn.execute(
            "SELECT device_id, mount_point, preferred_mount_point FROM devices"
        ).fetchall():
            did = int(dev_row[0])
            mount_point = dev_row[1]
            preferred_mount = dev_row[2] or dev_row[1]
            device_mounts[did] = (mount_point, preferred_mount)

    rows = conn.execute(
        """
        SELECT p.payload_id, p.device_id, p.root_path, p.status, p.file_count, p.total_bytes
        FROM payloads p
        LEFT JOIN (
            SELECT payload_id, COUNT(*) AS ref_count
            FROM torrent_instances
            GROUP BY payload_id
        ) ti ON ti.payload_id = p.payload_id
        WHERE COALESCE(ti.ref_count, 0) = 0
        ORDER BY p.root_path
        """
    ).fetchall()

    skipped_prefix = 0
    filtered_rows = []
    for row in rows:
        root_path = row["root_path"]

        if prefix_strings:
            in_scope = any(_is_under_fast(root_path, pref) for pref in prefix_strings)

            if not in_scope and row["device_id"] is not None:
                mount_point, preferred_mount = device_mounts.get(int(row["device_id"]), (None, None))
                remapped = _remap_mount(root_path, mount_point, preferred_mount)
                if remapped is None:
                    remapped = _remap_mount(root_path, preferred_mount, mount_point)
                if remapped:
                    in_scope = any(_is_under_fast(remapped, pref) for pref in prefix_strings)

            if not in_scope:
                try:
                    root_canon = canonicalize_path(Path(root_path))
                    in_scope = any(
                        _is_under_fast(str(root_canon), str(pref_path))
                        for pref_path in prefix_paths_canon
                    )
                except Exception:
                    in_scope = False

            if not in_scope:
                skipped_prefix += 1
                continue

        filtered_rows.append(row)

    active_count_keys = [
        (int(row["device_id"]), row["root_path"])
        for row in filtered_rows
        if row["device_id"] is not None and int(row["file_count"] or 0) == 0
    ]
    live_counts = _batch_count_active_payload_roots(conn, active_count_keys)

    true_orphans = []
    alias_artifacts = []
    for row in filtered_rows:
        root_path = row["root_path"]
        payload_id = int(row["payload_id"])
        device_id = row["device_id"]
        live_count = int(row["file_count"] or 0)
        if live_count == 0 and device_id is not None:
            live_count = live_counts.get((int(device_id), root_path), 0)

        if live_count > 0:
            alias_artifacts.append((payload_id, root_path))
        else:
            true_orphans.append((payload_id, root_path))

    gc_rows = {}
    gc_table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='payload_orphan_gc'"
    ).fetchone()
    if gc_table_exists and true_orphans:
        orphan_ids = [pid for pid, _ in true_orphans]
        placeholders = ",".join("?" for _ in orphan_ids)
        for row in conn.execute(
            f"""
            SELECT payload_id, first_seen_at, last_seen_at, seen_count
            FROM payload_orphan_gc
            WHERE payload_id IN ({placeholders})
            """,
            orphan_ids,
        ).fetchall():
            gc_rows[int(row[0])] = {
                "first_seen_at": float(row[1]),
                "last_seen_at": float(row[2]),
                "seen_count": int(row[3]),
            }

    now = time.time()
    tracked_count = 0
    aged_count = 0
    for payload_id, _ in true_orphans:
        entry = gc_rows.get(payload_id)
        if not entry:
            continue
        tracked_count += 1
        age_seconds = max(0.0, now - float(entry["first_seen_at"]))
        if int(entry["seen_count"]) >= ORPHAN_GC_MIN_SEEN_RUNS and age_seconds >= ORPHAN_GC_MIN_AGE_SECONDS:
            aged_count += 1

    true_samples = [root for _, root in true_orphans[: max(1, samples)]]
    alias_samples = [root for _, root in alias_artifacts[: max(1, samples)]]

    if json_output:
        payload = {
            "scoped_unmanaged_payloads": len(filtered_rows),
            "skipped_path_prefix": skipped_prefix,
            "true_orphans": len(true_orphans),
            "alias_artifacts": len(alias_artifacts),
            "gc_table_exists": bool(gc_table_exists),
            "gc_tracked_true_orphans": tracked_count,
            "gc_aged_true_orphans": aged_count,
            "gc_min_seen_runs": ORPHAN_GC_MIN_SEEN_RUNS,
            "gc_min_age_seconds": ORPHAN_GC_MIN_AGE_SECONDS,
            "true_orphan_samples": true_samples,
            "alias_artifact_samples": alias_samples,
            "path_prefixes": prefix_strings,
        }
        print(json.dumps(payload, sort_keys=True))
        conn.close()
        return

    print("🔎 Payload orphan audit (non-destructive)")
    print(f"   scoped unmanaged payloads: {len(filtered_rows)}")
    if prefix_strings:
        print(f"   skipped (path-prefix): {skipped_prefix}")
    print(f"   true orphans (eligible class): {len(true_orphans)}")
    print(f"   alias artifacts (not eligible): {len(alias_artifacts)}")

    if gc_table_exists:
        print(f"   gc tracked true orphans: {tracked_count}")
        print(f"   gc aged true orphans: {aged_count}")
        print(
            "   gc thresholds: "
            f"seen>={ORPHAN_GC_MIN_SEEN_RUNS}, age>={int(ORPHAN_GC_MIN_AGE_SECONDS/3600)}h"
        )
    else:
        print("   gc staging table: missing (will initialize on payload sync)")

    if true_samples:
        print(f"   true orphan samples: {', '.join(true_samples)}")
    if alias_samples:
        print(f"   alias artifact samples: {', '.join(alias_samples)}")

    conn.close()


@payload.command("orphan-sweep")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--dry-run/--execute",
    default=True,
    show_default=True,
    help="Dry-run by default; pass --execute to actually move/delete.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N orphan items (for staged runs).",
)
@click.option(
    "--order",
    type=click.Choice(["small-first", "large-first", "input"]),
    default="input",
    show_default=True,
    help="Order orphan move candidates before applying --limit.",
)
@click.option(
    "--reserve-gib",
    type=int,
    default=0,
    show_default=True,
    help="Keep at least this many GiB free on destination before cross-dataset moves.",
)
@click.option(
    "--dataset",
    "datasets",
    multiple=True,
    type=click.Choice(["pool-data", "pool-media", "stash"]),
    help="Restrict sweep to one or more datasets.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Print live (non-orphan) items too.",
)
@click.option(
    "--rt-cache", "rt_cache_file",
    default=str(DEFAULT_RT_SHARED_CACHE_FILE),
    show_default=True,
    help="Silo RT shared cache file.",
)
@click.option(
    "--qb-cache", "qb_cache_file",
    default=str(DEFAULT_QB_CACHE_FILE),
    show_default=True,
    help="hashall qB shared cache file.",
)
def payload_orphan_sweep_cmd(db, dry_run, limit, order, reserve_gib, datasets, verbose, rt_cache_file, qb_cache_file):
    """
    Sweep seeding trees and relocate orphaned content to orphaned_data/.

    Scans /pool/data/media/torrents/seeding, /pool/media/torrents/seeding,
    and /stash/media/torrents/seeding for content not backed by an active RT
    or qBittorrent torrent.

    Orphaned items are moved to /pool/media/torrents/orphans/<tracker>/.
    Items with active catalog references (hitchhiker groups) are skipped.
    .bad.* and __hl_tmp__* files are deleted unconditionally.

    Runs dry-run by default.  Pass --execute to perform moves.
    """
    from hashall.orphan_sweep import run_orphan_sweep
    from pathlib import Path as _Path

    if dry_run:
        print("🔍 DRY-RUN mode — no files will be moved or deleted")
    else:
        print("⚡ EXECUTE mode — files will be moved/deleted")

    summary = run_orphan_sweep(
        dry_run=dry_run,
        limit=limit,
        db_path=_Path(db) if db else None,
        rt_cache_file=_Path(rt_cache_file),
        qb_cache_file=_Path(qb_cache_file),
        order=order,
        reserve_gib=reserve_gib,
        dataset_names=set(datasets) if datasets else None,
        verbose=verbose,
    )

    diag = summary["cache_diag"]
    print(
        f"\n📡 Cache: RT {diag['rt_rows']} rows ({diag.get('rt_freshness','?')},"
        f" {diag.get('rt_age_s', 0):.0f}s old),"
        f" qB {diag['qb_rows']} rows ({diag.get('qb_age_s', 0):.0f}s old)"
    )
    for w in diag.get("warnings", []):
        print(f"   ⚠️  {w}")

    items = summary["items"]
    orphans = [i for i in items if i.is_orphan]
    live_count = len(items) - len(orphans)

    print(f"\n📊 Results:")
    print(f"   total items scanned:  {len(items)}")
    print(f"   live (backed):        {live_count}")
    print(f"   orphaned:             {len(orphans)}")
    print(f"   moved:                {summary['moved']}")
    print(f"   skipped:              {summary['skipped']}")
    print(f"   skipped (space):      {summary['skipped_space']}")
    print(f"   nlinks>1 warnings:    {summary['warned_nlinks']}")
    print(f"   bad files deleted:    {summary['bad_deleted']}")
    print(f"   bytes planned:        {summary['bytes_planned']}")
    print(f"   bytes moved:          {summary['bytes_moved']}")

    empty_dirs = [i for i in orphans if i.skip_reason == "empty_dir"]
    movers = [i for i in orphans if i.skip_reason != "empty_dir"]
    if empty_dirs:
        verb = "DRY-RUN: Would delete" if dry_run else "Deleted"
        print(f"\n{verb} empty dirs ({len(empty_dirs)}):")
        for item in empty_dirs:
            print(f"   [{item.dataset_name}] {item.path}")
    if movers:
        verb = "DRY-RUN: Would move" if dry_run else "Moved"
        print(f"\n{verb} orphans ({len(movers)}):")
        for item in movers:
            nl_tag = " ⚠️ nlinks>1" if item.warn_nlinks else ""
            ref_tag = f" (refs={item.catalog_refs})" if item.catalog_refs else ""
            skip_tag = f" → SKIP: {item.skip_reason}" if item.skip_reason else ""
            dest_tag = f" → {item.dest_path}" if item.dest_path else ""
            print(
                f"   [{item.dataset_name}/{item.tracker_label}] {item.path.name}"
                f"{nl_tag}{ref_tag}{skip_tag}{dest_tag}"
            )


@payload.command("normalize-cross-seed-link")
@click.option("--hash", "torrent_hash", required=True, help="Torrent hash to normalize from cross-seed-link -> cross-seed.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute qB setLocation + RT repoint. Default is dry-run.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def payload_normalize_cross_seed_link_cmd(torrent_hash, rpc_url, do_apply, json_output):
    """Normalize a single same-filesystem cross-seed-link payload across qB and RT."""
    from hashall.path_normalize import (
        apply_cross_seed_link_normalization,
        plan_cross_seed_link_normalization,
    )

    torrent_key = str(torrent_hash or "").strip().lower()
    plan = plan_cross_seed_link_normalization(torrent_key)

    if do_apply and not plan.ready:
        if json_output:
            print(json.dumps({"plan": plan.to_dict(), "error": "plan_not_ready"}, indent=2))
            raise SystemExit(1)
        raise click.ClickException(f"plan_not_ready issues={','.join(plan.issues)}")

    result = None
    if do_apply:
        try:
            result = apply_cross_seed_link_normalization(plan, rpc_url=rpc_url)
        except Exception as exc:
            if json_output:
                print(json.dumps({"plan": plan.to_dict(), "error": str(exc)}, indent=2))
                raise SystemExit(1)
            raise click.ClickException(str(exc))

    if json_output:
        payload = {"plan": plan.to_dict(), "apply": bool(do_apply)}
        if result is not None:
            payload["result"] = result.to_dict()
        print(json.dumps(payload, indent=2))
        return

    print("🧭 payload normalize-cross-seed-link")
    print(f"   hash: {plan.torrent_hash}")
    print(f"   apply: {do_apply}")
    print(f"   ready: {plan.ready}")
    print("   lane: cross-seed-link -> cross-seed")
    print(f"   qb_state: {plan.qb_state}")
    print(f"   qb_resume_after: {plan.qb_should_resume}")
    print(f"   qb_old_save_path: {plan.qb_old_save_path}")
    print(f"   qb_new_save_path: {plan.qb_new_save_path}")
    print(f"   qb_old_content_path: {plan.qb_old_content_path}")
    print(f"   qb_new_content_path: {plan.qb_new_content_path}")
    print(f"   rt_state: {plan.rt_state}")
    print(f"   rt_restart_after: {plan.rt_should_restart}")
    print(f"   rt_old_directory: {plan.rt_old_directory}")
    print(f"   rt_new_directory: {plan.rt_new_directory}")
    print(f"   rt_old_apply_directory: {plan.rt_old_apply_directory}")
    print(f"   rt_new_apply_directory: {plan.rt_new_apply_directory}")
    print(f"   source_exists: {plan.source_exists}")
    print(f"   target_exists: {plan.target_exists}")
    print(f"   same_filesystem: {plan.same_filesystem}")
    if plan.source_device is not None or plan.target_device is not None:
        print(f"   devices: source={plan.source_device} target={plan.target_device}")
    print(f"   issues: {len(plan.issues)}")
    for issue in plan.issues:
        print(f"      - {issue}")

    if result is None:
        return

    print(f"   outcome: {result.outcome}")
    print(f"   actions: {', '.join(result.actions) if result.actions else '(none)'}")
    if result.error:
        print(f"   error: {result.error}")
    if result.warnings:
        print(f"   warnings: {', '.join(result.warnings)}")
    else:
        print("   warnings: none")
    print(f"   qb_final_state: {result.qb_final_state}")
    print(f"   qb_final_save_path: {result.qb_final_save_path}")
    print(f"   qb_final_content_path: {result.qb_final_content_path}")
    print(f"   rt_final_state: {result.rt_final_state}")
    print(f"   rt_final_directory: {result.rt_final_directory}")


@payload.command("hitchhiker-audit")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--json-output", is_flag=True, help="Emit JSON output.")
@click.option("--limit", type=int, default=None, help="Limit number of catalog groups queried.")
def payload_hitchhiker_audit_cmd(db, json_output, limit):
    """
    Audit N→1 hitchhiker payload groups (multiple hashes sharing one on-disk tree).

    A hitchhiker group must be split into per-hash views (via hardlinks) before
    path repair can be safely applied. This command enumerates all groups and
    classifies them by safety to split: SAFE_TO_SPLIT, UNSPLIT, PARTIALLY_SPLIT, BUSY.
    """
    from hashall.hitchhiker import audit_hitchhiker_groups, format_hitchhiker_report

    groups = audit_hitchhiker_groups(db_path=db, limit=limit)
    report = format_hitchhiker_report(groups, json_output=json_output)
    print(report)


@payload.command("hitchhiker-split")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--dry-run/--execute",
    default=True,
    help="Dry-run (default) shows planned actions. --execute performs hardlinks + qB/RT repoint.",
)
@click.option("--limit", type=int, default=None, help="Limit number of groups to split.")
@click.option("--json-output", is_flag=True, help="Emit JSON output.")
def payload_hitchhiker_split_cmd(db, dry_run, limit, json_output):
    """
    Split N→1 hitchhiker payload groups: for each secondary hash, create a
    hardlinked copy of the shared content tree under _rehome-unique/<hash16>/
    and repoint qB + RT to the new per-hash location.

    Only processes SAFE_TO_SPLIT groups (all hashes stopped/paused, none in
    checking/active state). Groups are processed smallest-first.

    Run with --dry-run first (default) to preview what will happen.
    Then re-run with --execute to perform the split.
    """
    from hashall.hitchhiker import audit_hitchhiker_groups
    from hashall.hitchhiker_split import split_hitchhiker_groups, format_split_report

    groups = audit_hitchhiker_groups(db_path=db)
    results = split_hitchhiker_groups(groups, dry_run=dry_run, limit=limit)
    report = format_split_report(results, dry_run=dry_run, json_output=json_output)
    print(report)


@payload.command("save-path-audit")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--json-output", is_flag=True, help="Emit JSON output.")
@click.option("--limit", type=int, default=None, help="Limit number of torrents audited.")
@click.option("--drifted-only", is_flag=True, help="Show only drifted items.")
def payload_save_path_audit_cmd(db, json_output, limit, drifted_only):
    """
    Audit save-path drift across all qBittorrent torrents.

    Compares inferred canonical save paths (from category/tags) against actual
    qB and RT paths. Reports items that have drifted due to device mismatch,
    legacy paths, category changes, or qB/RT misalignment.

    Skips transient ARR categories (sonarr, radarr, etc.) which may be in transit.
    """
    import json

    from hashall.qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
    from hashall.rt_cache import load_rt_cache_snapshot
    from hashall.save_path_inference import detect_drift

    # Load qB torrents from file cache (avoids live API hit)
    qb_torrents = []
    try:
        cached_raw = get_torrents_from_cache(max_age_s=300, cache_path=DEFAULT_QB_CACHE_FILE)
        if cached_raw is not None:
            qb_client = QBittorrentClient()
            qb_torrents = [
                qb_client._torrent_from_payload(qb_client._normalize_torrent_payload(r))
                for r in cached_raw
            ]
        else:
            # Fallback to live if cache absent/stale
            qb_torrents = QBittorrentClient().get_torrents() or []
    except Exception as e:
        click.echo(f"Error loading qB torrent data: {e}", err=True)
        return

    # Load RT cache and index by hash
    rt_by_hash: dict = {}
    try:
        snapshot = load_rt_cache_snapshot() or {}
        rows = snapshot.get("rows") or []
        rt_by_hash = {str(r.get("hash") or "").lower(): r for r in rows}
    except Exception:
        pass

    # Audit each torrent
    drift_reports = []
    count = 0
    for qb_torrent in qb_torrents:
        if limit and count >= limit:
            break

        rt_info = rt_by_hash.get(qb_torrent.hash.lower(), {})

        report = detect_drift(
            torrent_hash=qb_torrent.hash,
            category=qb_torrent.category,
            tags=qb_torrent.tags,
            current_save_path=qb_torrent.save_path,
            current_content_path=qb_torrent.content_path,
            current_rt_directory=rt_info.get("directory", ""),
            current_qb_state=qb_torrent.state,
        )

        # Filter by drift status
        if drifted_only and not report.is_drifted:
            continue

        drift_reports.append(report)
        count += 1

    # Output results
    if json_output:
        output = json.dumps(
            [
                {
                    "hash": r.torrent_hash[:16],
                    "category": r.category,
                    "is_drifted": r.is_drifted,
                    "reason": r.drift_reason,
                    "qb_save_path": r.qb_current_save_path,
                    "rt_directory": r.rt_current_directory,
                    "canonical_path": r.canonical_save_path,
                    "notes": r.notes,
                }
                for r in drift_reports
            ],
            indent=2,
        )
        print(output)
    else:
        # Text output
        drifted_count = sum(1 for r in drift_reports if r.is_drifted)
        clean_count = len(drift_reports) - drifted_count

        print(f"Save-Path Audit: {len(drift_reports)} torrents scanned")
        print(f"  ✅ Clean: {clean_count}")
        print(f"  ⚠️  Drifted: {drifted_count}")
        print()

        if drifted_count > 0:
            print("DRIFTED ITEMS:")
            for r in drift_reports:
                if not r.is_drifted:
                    continue
                print(f"  {r.torrent_hash[:16]}  {r.category}")
                print(f"    qb_save: {r.qb_current_save_path}")
                print(f"    rt_dir:  {r.rt_current_directory}")
                print(f"    expected: {r.canonical_save_path}")
                print(f"    reason: {r.drift_reason}")
                for note in r.notes:
                    print(f"    note: {note}")


@payload.command("save-path-repair")
@click.option(
    "--dry-run/--execute",
    default=True,
    help="Dry-run (default) shows planned moves. --execute performs the repair.",
)
@click.option("--limit", type=int, default=None, help="Limit number of hashes to repair.")
@click.option("--json-output", is_flag=True, help="Emit JSON output.")
def payload_save_path_repair_cmd(dry_run, limit, json_output):
    """
    Move secondary hashes from _rehome-unique/<hash16>/ to canonical save paths.

    After hitchhiker-split, secondary hashes live in temporary _rehome-unique/
    locations. This command moves them to their canonical seeding paths based on
    category/tags and device (stash vs pool) placement rules.

    Infers canonical paths using the catalog's original save_path as a category hint.

    Run with --dry-run first (default) to preview what will happen.
    Then re-run with --execute to perform the repair.
    """
    from hashall.save_path_repair import audit_repair_candidates, execute_repair, format_repair_report

    # Audit repair candidates
    actions = audit_repair_candidates()
    if not actions:
        print("No repair candidates found (no hashes in _rehome-unique/).")
        return

    if limit:
        actions = actions[:limit]

    # Execute repairs
    results = []
    for i, action in enumerate(actions, 1):
        result = execute_repair(action.hash_val, dry_run=dry_run)
        results.append(result)
        if (i % 10) == 0:
            click.echo(f"  [{i}/{len(actions)}] processed...", err=True)

    report = format_repair_report(results, dry_run=dry_run, json_output=json_output)
    print(report)


@payload.command("save-path-recover")
@click.option(
    "--dry-run/--execute",
    default=True,
    help="Dry-run (default) shows recovery plan. --execute performs the recovery.",
)
@click.option("--limit", type=int, default=None, help="Limit number of hashes to recover.")
@click.option("--json-output", is_flag=True, help="Emit JSON output.")
def payload_save_path_recover_cmd(dry_run, limit, json_output):
    """
    Recover hashes displaced by the broken save-path-repair run.

    Finds all missingFiles hashes in qBittorrent, locates their displaced files
    on filesystem, moves them to correct canonical paths, then (--execute only)
    stops qB, patches fastresume files in batch, restarts qB, and rechecks all.

    Run with --dry-run first to verify the recovery plan, then --execute to fix.
    """
    from hashall.save_path_recovery import plan_recovery, execute_recovery, format_recovery_report

    click.echo("Planning recovery (fetching qB state)...", err=True)
    actions = plan_recovery()
    if not actions:
        print("No missingFiles hashes found — nothing to recover.")
        return

    if limit:
        actions = actions[:limit]

    click.echo(f"Found {len(actions)} missingFiles hashes to recover.", err=True)

    if dry_run:
        report = format_recovery_report(actions, [], dry_run=True, json_output=json_output)
        print(report)
        return

    click.echo("Executing recovery...", err=True)
    results = execute_recovery(actions, dry_run=False)

    report = format_recovery_report(actions, results, dry_run=False, json_output=json_output)
    print(report)


@payload.command("show")
@click.argument("torrent_hash")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def payload_show(torrent_hash, db):
    """
    Display payload information for a torrent hash.

    Shows payload_id, payload_hash, device, root_path, file count, and size.
    """
    from hashall.model import connect_db
    from hashall.payload import get_torrent_instance, get_payload_by_id

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)

    # Get torrent instance
    torrent = get_torrent_instance(conn, torrent_hash)
    if not torrent:
        print(f"❌ Torrent not found: {torrent_hash}")
        return

    # Get payload
    payload = get_payload_by_id(conn, torrent.payload_id)
    if not payload:
        print(f"❌ Payload not found for torrent")
        return

    # Display information
    print(f"🔍 Torrent: {torrent_hash}")
    print(f"   Category: {torrent.category or 'None'}")
    print(f"   Tags: {torrent.tags or 'None'}")
    print(f"   Save Path: {torrent.save_path}")
    print(f"   Root Name: {torrent.root_name}")
    print()
    print(f"📦 Payload ID: {payload.payload_id}")
    print(f"   Status: {payload.status}")
    print(f"   Root Path: {payload.root_path}")
    print(f"   Files: {payload.file_count}")
    print(f"   Size: {payload.total_bytes:,} bytes")

    if payload.payload_hash:
        print(f"   Hash: {payload.payload_hash}")
    else:
        print(f"   Hash: (incomplete - missing SHA256s)")

    if payload.last_built_at:
        import datetime
        dt = datetime.datetime.fromtimestamp(payload.last_built_at)
        print(f"   Last Built: {dt.strftime('%Y-%m-%d %H:%M:%S')}")


@payload.command("siblings")
@click.argument("torrent_hash")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def payload_siblings(torrent_hash, db):
    """
    List all torrent hashes that map to the same payload.

    This shows torrent "siblings" - different torrents with the same content.
    """
    from hashall.model import connect_db
    from hashall.payload import get_torrent_siblings, get_torrent_instance

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)

    # Get siblings
    siblings = get_torrent_siblings(conn, torrent_hash)

    if not siblings:
        print(f"❌ Torrent not found: {torrent_hash}")
        return

    print(f"🔗 Torrent siblings for: {torrent_hash}")
    print(f"   Found {len(siblings)} torrent(s) with same payload:\n")

    for i, sibling_hash in enumerate(siblings, 1):
        is_self = sibling_hash == torrent_hash
        marker = " (this torrent)" if is_self else ""
        print(f"   {i}. {sibling_hash}{marker}")

        # Get details
        torrent = get_torrent_instance(conn, sibling_hash)
        if torrent:
            print(f"      Category: {torrent.category or 'None'}")
            print(f"      Root: {torrent.root_name}")
            print()


@cli.group()
def content():
    """Read-only inventory/reporting for non-qB content roots."""
    pass


@cli.group()
def rt():
    """Read-only rtorrent session inspection."""
    pass


@cli.group("client-drift")
def client_drift():
    """Audit and remediate qB/rt membership drift."""
    pass


def _filtered_client_drift_rows(report: dict, *, side: str, action: str, limit: int) -> list[dict]:
    rows = list(report.get("rows") or [])
    side_filter = str(side or "").strip()
    action_filter = str(action or "").strip()
    if side_filter:
        rows = [row for row in rows if str(row.get("side") or "") == side_filter]
    if action_filter:
        rows = [row for row in rows if str(row.get("action") or "") == action_filter]
    if limit > 0:
        rows = rows[:limit]
    return rows


def _load_client_drift_report(
    *,
    qb_cache_file: str,
    rt_cache_file: str,
    rt_session_dir: str,
    policy_path: str | None,
    policy_mode: str,
) -> dict:
    from hashall.client_drift import build_client_drift_report, load_policy

    policy = load_policy(
        Path(policy_path).expanduser() if policy_path else None,
        mode=policy_mode,
    )
    return build_client_drift_report(
        qb_cache_file=Path(qb_cache_file).expanduser(),
        rt_cache_file=Path(rt_cache_file).expanduser(),
        rt_session_dir=Path(rt_session_dir).expanduser(),
        policy=policy,
    )


def _read_client_drift_journal(journal_path: Path) -> set[str]:
    completed: set[str] = set()
    if not journal_path.exists():
        return completed
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        verify = event.get("verify")
        verify_failed = isinstance(verify, dict) and verify.get("ok") is False
        if event.get("status") in {"ok", "already_present"} and not event.get("error") and not verify_failed:
            torrent_hash = str(event.get("hash") or "").strip().lower()
            if torrent_hash:
                completed.add(torrent_hash)
    return completed


def _append_client_drift_journal(journal_path: Path, event: dict) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", time.time())
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _verify_qb_import_complete(qbit, torrent_hash: str, *, timeout_s: float, interval_s: float) -> dict:
    deadline = time.time() + max(0.0, float(timeout_s))
    interval = max(0.5, float(interval_s))
    last = None
    while True:
        remaining_s = max(0.0, deadline - time.time())
        info = qbit.get_torrent_info(torrent_hash)
        if info is not None:
            last = {
                "state": info.state,
                "progress": float(info.progress),
                "amount_left": int(info.amount_left),
                "save_path": info.save_path,
                "content_path": info.content_path,
            }
            _rt_qb_progress(
                f"verify poll state={info.state} progress={float(info.progress):.3f} "
                f"left={int(info.amount_left)} timeout_left={remaining_s:.0f}s"
            )
            if info.progress >= 0.999 and int(info.amount_left) == 0:
                return {"ok": True, **last}
        else:
            _rt_qb_progress(f"verify poll state=missing timeout_left={remaining_s:.0f}s")
        if time.time() >= deadline:
            break
        time.sleep(interval)
    return {"ok": False, **(last or {"state": "missing", "progress": 0.0, "amount_left": -1})}


def _rt_qb_progress(message: str) -> None:
    print(f"      {_rt_qb_style('…', fg='yellow', bold=True)} {message}", flush=True)


def _rt_qb_color_enabled() -> bool:
    override = str(os.environ.get("HASHALL_COLOR") or "").strip().lower()
    if override in {"1", "true", "yes", "always"}:
        return True
    if override in {"0", "false", "no", "never"}:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if str(os.environ.get("CLICOLOR_FORCE") or "").strip().lower() in {"1", "true", "yes", "always"}:
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _rt_qb_style(text: object, *, fg: str | None = None, bold: bool = False) -> str:
    value = str(text)
    if not _rt_qb_color_enabled():
        return value
    return click.style(value, fg=fg, bold=bold)


def _rt_qb_bool(value: bool) -> str:
    return _rt_qb_style("True", fg="green", bold=True) if value else _rt_qb_style("False", fg="yellow", bold=True)


def _print_rt_qb_summary(title: str, rows: list[tuple[str, object, str | None]]) -> None:
    print(_rt_qb_style(f"╭─ {title}", fg="cyan", bold=True))
    for label, value, color in rows:
        label_text = f"{label + ':':<24}"
        print(f"│ {_rt_qb_style(label_text, fg='bright_black')} {_rt_qb_style(value, fg=color, bold=color in {'green', 'yellow', 'red'})}")
    print(_rt_qb_style("╰─", fg="cyan", bold=True))


def _rt_qb_added_text(raw_added_on: object) -> str:
    try:
        added_on = int(raw_added_on or 0)
    except (TypeError, ValueError):
        added_on = 0
    if added_on <= 0:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(added_on))


def _print_rt_qb_candidate(row: dict, *, index: int | None = None) -> None:
    rt_row = row.get("rt") or {}
    hash_prefix = str(row.get("hash") or "")[:16]
    name = str(row.get("name") or "")
    save_path = str(rt_row.get("target_qb_save_path") or rt_row.get("save_path") or "")
    category = str(rt_row.get("category") or "")
    added = str(rt_row.get("added_display") or "").strip() or _rt_qb_added_text(rt_row.get("added_on"))
    prefix = f"{index:>3}. " if index is not None else "   "
    category_text = f"{category or '-':<14}"
    print(
        f"{_rt_qb_style(prefix, fg='bright_black')}"
        f"{_rt_qb_style(hash_prefix, fg='cyan', bold=True)} "
        f"{_rt_qb_style(category_text, fg='magenta')} "
        f"{_rt_qb_style(name, fg='bright_white', bold=True)}"
    )
    print(
        f"     {_rt_qb_style('added:', fg='bright_black')} {_rt_qb_style(added, fg='yellow')}"
    )
    print(
        f"     {_rt_qb_style('path:', fg='bright_black')} {_rt_qb_style(save_path, fg='bright_blue')}"
    )


def _print_rt_qb_event_status(event: dict) -> None:
    status = str(event.get("status") or "")
    status_color = "green" if status in {"ok", "already_present"} else "red"
    print(f"      status: {_rt_qb_style(status, fg=status_color, bold=True)}")
    if "recheck_started" in event:
        print(f"      recheck_started: {_rt_qb_bool(bool(event['recheck_started']))}")
    if "verify" in event:
        verify = event["verify"]
        if isinstance(verify, dict) and verify.get("ok") is True:
            print(
                "      verify: "
                f"{_rt_qb_style('ok', fg='green', bold=True)} "
                f"state={verify.get('state')} progress={float(verify.get('progress') or 0):.3f} "
                f"left={verify.get('amount_left')}"
            )
        else:
            print(f"      verify: {_rt_qb_style(verify, fg='yellow')}")


_RT_QB_COMPLETE_STATES = {"pausedUP", "stoppedUP", "queuedUP", "stalledUP", "uploading", "forcedUP"}
_RT_QB_DOWNLOADING_STATES = {
    "allocating",
    "checkingDL",
    "checkingResumeData",
    "downloading",
    "forcedDL",
    "metaDL",
    "moving",
    "queuedDL",
    "stalledDL",
    "stoppedDL",
    "pausedDL",
}


def _rt_qb_monitor_classify(info) -> tuple[str, str]:
    if info is None:
        return "pending", "missing_from_qb"
    state = str(info.state or "")
    progress = float(info.progress or 0.0)
    amount_left = int(info.amount_left)
    if progress >= 0.999 and amount_left == 0 and state in _RT_QB_COMPLETE_STATES:
        return "success", f"{state} 100%"
    if state in _RT_QB_DOWNLOADING_STATES and not state.startswith("checking"):
        return "failure", f"transitioned_to_downloading state={state} progress={progress:.3f} left={amount_left}"
    return "pending", f"{state or 'unknown'} progress={progress:.3f} left={amount_left}"


def _monitor_rt_qb_rechecks(
    qbit,
    torrent_hashes: list[str],
    *,
    timeout_s: float,
    interval_s: float,
    stop_after_check: bool = True,
    stalled_dl_grace: int = 3,
) -> dict[str, dict]:
    pending = {str(item or "").strip().lower() for item in torrent_hashes if str(item or "").strip()}
    results: dict[str, dict] = {}
    if not pending:
        return results
    timeout = max(1.0, float(timeout_s))
    interval = max(1.0, float(interval_s))
    deadline = time.time() + timeout
    _print_rt_qb_summary(
        "Monitoring qB rechecks",
        [
            ("total", len(pending), "yellow"),
            ("poll_interval", f"{interval:.0f}s", None),
            ("timeout", f"{timeout:.0f}s", None),
            ("stop_after_check", "yes" if stop_after_check else "no", None),
        ],
    )
    # Grace counter: stoppedDL is the normal initial state before qB processes the recheck
    # command. Track consecutive stoppedDL observations per hash; only fail after the grace
    # window expires so we don't misclassify a queued recheck as a download failure.
    stalled_dl_seen: dict[str, int] = {}
    while pending and time.time() < deadline:
        for torrent_hash in list(pending):
            info = qbit.get_torrent_info(torrent_hash)
            raw_state = str(info.state or "") if info is not None else ""
            if raw_state == "stoppedDL":
                count = stalled_dl_seen.get(torrent_hash, 0) + 1
                stalled_dl_seen[torrent_hash] = count
                if count <= stalled_dl_grace:
                    status = "pending"
                    detail = f"stoppedDL (grace {count}/{stalled_dl_grace}, waiting for recheck)"
                else:
                    status, detail = _rt_qb_monitor_classify(info)
            else:
                stalled_dl_seen.pop(torrent_hash, None)
                status, detail = _rt_qb_monitor_classify(info)
            if status == "success":
                stopped_ok: bool | None = None
                if stop_after_check:
                    stopped_ok = qbit.pause_torrent(torrent_hash)
                    if stopped_ok:
                        detail = f"{detail} → stopped"
                    else:
                        detail = f"{detail} → stop_failed"
                print(f"{_rt_qb_style('✓', fg='green', bold=True)} {torrent_hash[:16]} {detail}", flush=True)
                results[torrent_hash] = {"status": "success", "detail": detail, "stopped": stopped_ok}
                pending.remove(torrent_hash)
            elif status == "failure":
                print(f"{_rt_qb_style('✗', fg='red', bold=True)} {torrent_hash[:16]} {detail}", flush=True)
                results[torrent_hash] = {"status": "failure", "detail": detail, "stopped": None}
                pending.remove(torrent_hash)
            else:
                print(f"{_rt_qb_style('…', fg='yellow', bold=True)} {torrent_hash[:16]} {detail}", flush=True)
        if pending:
            time.sleep(min(interval, max(0.0, deadline - time.time())))
    for torrent_hash in sorted(pending):
        detail = "monitor_timeout"
        print(f"{_rt_qb_style('!', fg='red', bold=True)} {torrent_hash[:16]} {detail}", flush=True)
        results[torrent_hash] = {"status": "timeout", "detail": detail, "stopped": None}
    stopped_count = sum(1 for item in results.values() if item.get("stopped") is True)
    counts = {
        "success": sum(1 for item in results.values() if item["status"] == "success"),
        "failed": sum(1 for item in results.values() if item["status"] == "failure"),
        "timeout": sum(1 for item in results.values() if item["status"] == "timeout"),
        "total": len(results),
    }
    summary_rows = [
        ("success", counts["success"], "green" if counts["success"] else None),
        ("failed", counts["failed"], "red" if counts["failed"] else "green"),
        ("timeout", counts["timeout"], "red" if counts["timeout"] else "green"),
        ("total", counts["total"], None),
    ]
    if stop_after_check:
        summary_rows.append(("stopped", stopped_count, "green" if stopped_count == counts["success"] else "yellow"))
    _print_rt_qb_summary("RT→qB mirror summary", summary_rows)
    return results


def _select_client_drift_mirror_rows(
    report: dict,
    *,
    hash_filters: tuple[str, ...] | list[str] = (),
    limit: int = 0,
    journal_path: Path | None = None,
) -> tuple[list[dict], int, int]:
    rows = _filtered_client_drift_rows(report, side="rt_only", action="mirror_rt_to_qb", limit=0)
    hash_prefixes = [str(item or "").strip().lower() for item in hash_filters if str(item or "").strip()]
    if hash_prefixes:
        rows = [
            row for row in rows
            if any(str(row.get("hash") or "").lower().startswith(prefix) for prefix in hash_prefixes)
        ]
    completed = _read_client_drift_journal(journal_path) if journal_path else set()
    selected = [row for row in rows if str(row.get("hash") or "").lower() not in completed]
    if limit > 0:
        selected = selected[:limit]
    return selected, len(rows), len(completed)


def _apply_client_drift_mirror_rows(
    rows: list[dict],
    *,
    do_apply: bool,
    journal: Path,
    extra_tags: tuple[str, ...] | list[str] = (),
    skip_checking: bool = False,
    recheck_after_add: bool = False,
    verify_timeout: float = 0.0,
    verify_interval: float = 5.0,
    sleep_row: float = 0.0,
    qbit=None,
) -> list[dict]:
    events: list[dict] = []
    if do_apply and qbit is None:
        from hashall.qbittorrent import get_qbittorrent_client

        qbit = get_qbittorrent_client()

    for index, row in enumerate(rows, start=1):
        rt_row = row.get("rt") or {}
        _print_rt_qb_candidate(row, index=index)
        if not do_apply:
            continue
        assert qbit is not None
        torrent_hash = str(row.get("hash") or "").strip().lower()
        _rt_qb_progress("checking qB for existing torrent")
        existing = qbit.get_torrent_info(torrent_hash)
        if existing is not None:
            verify = {}
            if recheck_after_add:
                _rt_qb_progress("already present; starting qB recheck")
                qbit.recheck_torrent(torrent_hash)
            if verify_timeout > 0:
                _rt_qb_progress(f"verifying qB completion for up to {verify_timeout:.0f}s")
                verify = _verify_qb_import_complete(
                    qbit,
                    torrent_hash,
                    timeout_s=verify_timeout,
                    interval_s=verify_interval,
                )
            event = {
                "event": "finished",
                "hash": torrent_hash,
                "status": "already_present",
                "verify": verify,
            }
            _append_client_drift_journal(journal, event)
            events.append(event)
            _print_rt_qb_event_status(event)
            continue
        tags = ["hashall-client-drift", *extra_tags]
        _rt_qb_progress("adding torrent to qB as stopped")
        ok = qbit.add_torrent_file(
            Path(str(rt_row.get("torrent_file") or "")),
            save_path=str(rt_row.get("target_qb_save_path") or rt_row.get("save_path") or ""),
            category=str(rt_row.get("category") or ""),
            tags=tags,
            stopped=True,
            skip_checking=skip_checking,
        )
        event = {
            "event": "finished",
            "hash": torrent_hash,
            "status": "ok" if ok else "error",
            "action": "mirror_rt_to_qb",
            "save_path": str(rt_row.get("target_qb_save_path") or rt_row.get("save_path") or ""),
            "category": str(rt_row.get("category") or ""),
            "error": "" if ok else str(qbit.last_error or "unknown"),
        }
        if ok and recheck_after_add:
            _rt_qb_progress("starting qB recheck")
            recheck_ok = qbit.recheck_torrent(torrent_hash)
            event["recheck_started"] = bool(recheck_ok)
            if not recheck_ok:
                event["error"] = str(qbit.last_error or "qbit_recheck_failed")
        if ok and not event["error"] and verify_timeout > 0:
            _rt_qb_progress(f"verifying qB completion for up to {verify_timeout:.0f}s")
            verify = _verify_qb_import_complete(
                qbit,
                torrent_hash,
                timeout_s=verify_timeout,
                interval_s=verify_interval,
            )
            event["verify"] = verify
            if not verify.get("ok"):
                event["error"] = f"verify_incomplete:{verify}"
        _append_client_drift_journal(journal, event)
        events.append(event)
        _print_rt_qb_event_status(event)
        if event["error"]:
            print(f"      error: {_rt_qb_style(event['error'], fg='red', bold=True)}")
            raise click.ClickException(f"client drift apply failed hash={torrent_hash}: {event['error']}")
        if sleep_row > 0:
            time.sleep(sleep_row)
    return events


@client_drift.command("policy-template")
def client_drift_policy_template_cmd():
    """Print a conservative client-drift policy template."""
    payload = {
        "mode": "conservative",
        "mirror_roots": [],
        "_example_mirror_roots": [
            "/data/media/torrents/seeding",
            "/pool/media/torrents/seeding",
            "/stash/media/torrents/seeding",
        ],
        "mirror_rt_to_qb_categories": [],
        "mirror_qb_to_rt_categories": [],
        "ignore_rt_only_categories": [],
        "ignore_qb_only_categories": [],
        "ignore_rt_only_path_prefixes": [],
        "ignore_qb_only_path_prefixes": [],
        "remove_from_rt_categories": [],
        "remove_from_qb_categories": [],
        "remove_from_rt_path_prefixes": [],
        "remove_from_qb_path_prefixes": [],
        "recent_seconds": 0,
    }
    print(json.dumps(payload, indent=2))


@client_drift.command("audit")
@click.option("--qb-cache-file", default=str(DEFAULT_QB_CACHE_FILE), show_default=True, help="Shared qB cache JSON.")
@click.option("--rt-cache-file", default=str(DEFAULT_RT_SHARED_CACHE_FILE), show_default=True, help="Shared RT cache JSON.")
@click.option("--rt-session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent session metadata.")
@click.option("--policy", "policy_path", type=click.Path(exists=True, dir_okay=False), help="JSON policy file for intentional one-client rows and safe actions.")
@click.option("--policy-mode", type=click.Choice(["conservative", "rt-authoritative-mirror"]), default="conservative", show_default=True, help="Built-in defaults to use before applying --policy.")
@click.option("--side", type=click.Choice(["rt_only", "qb_only"]), default=None, help="Only show one drift side.")
@click.option("--action", default="", help="Only show rows with this classified action.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit shown rows; 0 means no limit.")
@click.option("--output", type=click.Path(dir_okay=False), help="Write the full JSON report to this path.")
@click.option("--json-output", is_flag=True, help="Emit JSON report to stdout.")
def client_drift_audit_cmd(
    qb_cache_file,
    rt_cache_file,
    rt_session_dir,
    policy_path,
    policy_mode,
    side,
    action,
    limit,
    output,
    json_output,
):
    """Classify qB/RT membership drift without mutating either client."""
    report = _load_client_drift_report(
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
        rt_session_dir=rt_session_dir,
        policy_path=policy_path,
        policy_mode=policy_mode,
    )
    rows = _filtered_client_drift_rows(report, side=side, action=action, limit=limit)
    payload = {"summary": dict(report["summary"], rows_shown=len(rows)), "rows": rows}
    if output:
        out_path = Path(output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if json_output:
        print(json.dumps(payload, indent=2))
        return

    summary = payload["summary"]
    print("🧭 client drift audit")
    print(f"   policy_mode: {summary['policy_mode']}")
    print(f"   qb_total: {summary['qb_total']}")
    print(f"   rt_total: {summary['rt_total']}")
    print(f"   common: {summary['common']}")
    print(f"   qb_only: {summary['qb_only']}")
    print(f"   rt_only: {summary['rt_only']}")
    print(f"   action_counts: {summary['action_counts']}")
    if output:
        print(f"   output: {Path(output).expanduser()}")
    for row in rows:
        client_row = row.get("rt") if row.get("side") == "rt_only" else row.get("qb")
        client_row = client_row or {}
        blockers = ",".join(row.get("blockers") or [])
        reason = ",".join(row.get("reasons") or [])
        print(
            f"   {row['side']:7s} {row['action']:28s} {row['confidence']:6s} "
            f"{row['hash'][:16]} {row.get('name') or ''}"
        )
        print(f"      state={client_row.get('state') or ''} category={client_row.get('category') or ''} path={client_row.get('content_path') or client_row.get('save_path') or ''}")
        if blockers:
            print(f"      blockers={blockers}")
        if reason:
            print(f"      reasons={reason}")


@client_drift.command("apply")
@click.option("--qb-cache-file", default=str(DEFAULT_QB_CACHE_FILE), show_default=True, help="Shared qB cache JSON.")
@click.option("--rt-cache-file", default=str(DEFAULT_RT_SHARED_CACHE_FILE), show_default=True, help="Shared RT cache JSON.")
@click.option("--rt-session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent session metadata.")
@click.option("--policy", "policy_path", type=click.Path(exists=True, dir_okay=False), help="JSON policy file for intentional one-client rows and safe actions.")
@click.option("--policy-mode", type=click.Choice(["conservative", "rt-authoritative-mirror"]), default="conservative", show_default=True, help="Built-in defaults to use before applying --policy.")
@click.option("--action", default="mirror_rt_to_qb", show_default=True, help="Action class to apply. Currently only mirror_rt_to_qb is executable.")
@click.option("--hash", "hash_filters", multiple=True, help="Restrict apply to specific torrent hash(es). Prefixes are accepted.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit selected rows; 0 means no limit.")
@click.option("--sleep-row", type=float, default=5.0, show_default=True, help="Seconds to sleep after each applied row.")
@click.option("--journal", "journal_path", type=click.Path(dir_okay=False), default="out/client-drift/apply.jsonl", show_default=True, help="JSONL journal for resume/skip.")
@click.option("--tag", "extra_tags", multiple=True, help="Additional qB tag(s) for imported torrents.")
@click.option("--skip-checking", is_flag=True, help="Ask qB to skip checking on add. Default leaves checking behavior to qB.")
@click.option("--recheck-after-add", is_flag=True, help="Trigger qB recheck after import.")
@click.option("--verify-timeout", type=float, default=0.0, show_default=True, help="Seconds to wait for qB import to reach complete after recheck; 0 disables wait.")
@click.option("--verify-interval", type=float, default=5.0, show_default=True, help="Seconds between qB import verification polls.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually mutate qB. Default is dry-run.")
def client_drift_apply_cmd(
    qb_cache_file,
    rt_cache_file,
    rt_session_dir,
    policy_path,
    policy_mode,
    action,
    hash_filters,
    limit,
    sleep_row,
    journal_path,
    extra_tags,
    skip_checking,
    recheck_after_add,
    verify_timeout,
    verify_interval,
    do_apply,
):
    """Apply safe client-drift actions with journaling. Does not delete data."""
    if action != "mirror_rt_to_qb":
        raise click.ClickException("only mirror_rt_to_qb is executable; remove actions are audit-only")

    report = _load_client_drift_report(
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
        rt_session_dir=rt_session_dir,
        policy_path=policy_path,
        policy_mode=policy_mode,
    )
    journal = Path(journal_path).expanduser()
    selected, candidate_count, completed_count = _select_client_drift_mirror_rows(
        report,
        hash_filters=hash_filters,
        limit=limit,
        journal_path=journal,
    )

    print("🛠️  client drift apply")
    print(f"   action: {action}")
    print(f"   policy_mode: {report['summary']['policy_mode']}")
    print(f"   apply: {do_apply}")
    print(f"   hash_filters: {len([h for h in hash_filters if str(h or '').strip()])}")
    print(f"   recheck_after_add: {recheck_after_add}")
    print(f"   verify_timeout: {verify_timeout}")
    print(f"   candidates: {candidate_count}")
    print(f"   journal_completed: {completed_count}")
    print(f"   selected: {len(selected)}")
    print(f"   journal: {journal}")
    _apply_client_drift_mirror_rows(
        selected,
        do_apply=do_apply,
        journal=journal,
        extra_tags=extra_tags,
        skip_checking=skip_checking,
        recheck_after_add=recheck_after_add,
        verify_timeout=verify_timeout,
        verify_interval=verify_interval,
        sleep_row=sleep_row,
    )


DEFAULT_RT_QB_MIRROR_QUEUE_DIR = Path.home() / ".cache" / "hashall-rt-qb-mirror" / "queue"
DEFAULT_RT_QB_MIRROR_JOURNAL = Path("out") / "rt-qb-mirror" / "apply.jsonl"


def _mirror_hash_key(value: str) -> str:
    return re.sub(r"[^a-fA-F0-9]", "", str(value or "")).lower()


def _read_json_file(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _rt_qb_mirror_disabled_reason(config_path: str | None) -> str:
    env_value = str(os.environ.get("HASHALL_QB_MIRROR_ENABLED", "")).strip().lower()
    if env_value in {"0", "false", "no", "off", "disabled"}:
        return "env:HASHALL_QB_MIRROR_ENABLED=0"
    if config_path:
        payload = _read_json_file(Path(config_path).expanduser())
        if isinstance(payload, dict) and payload.get("enabled") is False:
            return f"config:{Path(config_path).expanduser()}"
    return ""


def _queue_path(queue_dir: Path, torrent_hash: str) -> Path:
    key = _mirror_hash_key(torrent_hash)
    if not key:
        raise click.ClickException("missing or invalid torrent hash")
    return queue_dir.expanduser() / f"{key}.json"


def _load_queue_entries(queue_dir: Path, *, min_age_s: float, now: float) -> tuple[list[dict], list[dict]]:
    ready: list[dict] = []
    waiting: list[dict] = []
    for path in sorted(queue_dir.expanduser().glob("*.json")):
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            payload = {}
        torrent_hash = _mirror_hash_key(str(payload.get("hash") or path.stem))
        if not torrent_hash:
            continue
        try:
            first_seen = float(payload.get("first_seen") or path.stat().st_mtime)
        except Exception:
            first_seen = path.stat().st_mtime
        entry = {
            "hash": torrent_hash,
            "path": str(path),
            "first_seen": first_seen,
            "age_s": max(0.0, now - first_seen),
            "source": str(payload.get("source") or "queue"),
        }
        if entry["age_s"] >= min_age_s:
            ready.append(entry)
        else:
            waiting.append(entry)
    return ready, waiting


@cli.group("rt-qb-mirror")
def rt_qb_mirror():
    """Mirror complete RT additions into qB as stopped torrents."""
    pass


@rt_qb_mirror.command("enqueue")
@click.argument("torrent_hash")
@click.option("--queue-dir", type=click.Path(file_okay=False), default=str(DEFAULT_RT_QB_MIRROR_QUEUE_DIR), show_default=True)
@click.option("--config", "config_path", type=click.Path(dir_okay=False), help="Optional JSON config; {\"enabled\": false} disables the mirror.")
@click.option("--source", default="rt-finished-hook", show_default=True)
def rt_qb_mirror_enqueue_cmd(torrent_hash, queue_dir, config_path, source):
    """Queue a completed RT hash for delayed qB mirror import."""
    disabled = _rt_qb_mirror_disabled_reason(config_path)
    if disabled:
        print(f"rt-qb-mirror enqueue disabled reason={disabled}")
        return
    key = _mirror_hash_key(torrent_hash)
    if not key:
        raise click.ClickException("missing or invalid torrent hash")
    qdir = Path(queue_dir).expanduser()
    qdir.mkdir(parents=True, exist_ok=True)
    path = _queue_path(qdir, key)
    if path.exists():
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            payload = {"hash": key, "first_seen": time.time()}
        payload["last_seen"] = time.time()
        payload["source"] = str(source or payload.get("source") or "rt-finished-hook")
    else:
        payload = {
            "hash": key,
            "first_seen": time.time(),
            "last_seen": time.time(),
            "source": str(source or "rt-finished-hook"),
        }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    print(f"rt-qb-mirror queued hash={key[:16]} path={path}")


@rt_qb_mirror.command("sync")
@click.option("--qb-cache-file", default=str(DEFAULT_QB_CACHE_FILE), show_default=True, help="Shared qB cache JSON.")
@click.option("--rt-cache-file", default=str(DEFAULT_RT_SHARED_CACHE_FILE), show_default=True, help="Shared RT cache JSON.")
@click.option("--rt-session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True)
@click.option("--policy", "policy_path", type=click.Path(exists=True, dir_okay=False), help="JSON policy file for intentional one-client rows and safe actions.")
@click.option("--policy-mode", type=click.Choice(["conservative", "rt-authoritative-mirror"]), default="rt-authoritative-mirror", show_default=True)
@click.option("--config", "config_path", type=click.Path(dir_okay=False), help="Optional JSON config; {\"enabled\": false} disables the mirror.")
@click.option("--hash", "hash_filters", multiple=True, help="Restrict sync to hash prefixes.")
@click.option("--limit", type=int, default=0, show_default=True)
@click.option("--sleep-row", type=float, default=5.0, show_default=True)
@click.option("--journal", "journal_path", type=click.Path(dir_okay=False), default=str(DEFAULT_RT_QB_MIRROR_JOURNAL), show_default=True)
@click.option("--tag", "extra_tags", multiple=True, default=("hashall-rt-qb-mirror",), help="Additional qB tag(s) for imported torrents.")
@click.option("--skip-checking", is_flag=True, help="Ask qB to skip checking on add.")
@click.option(
    "--recheck-after-add/--no-recheck-after-add",
    default=True,
    show_default=True,
    help="Trigger qB recheck after import so qB can verify the stopped mirror at its existing files.",
)
@click.option("--verify-timeout", type=float, default=0.0, show_default=True)
@click.option("--verify-interval", type=float, default=5.0, show_default=True)
@click.option("--wait-for-check", is_flag=True, help="Wait for qB recheck to reach 100%; uses --verify-timeout or 180s by default.")
@click.option("--monitor/--no-monitor", default=True, show_default=True, help="After queueing all rechecks, monitor them to success/failure.")
@click.option("--monitor-timeout", type=float, default=900.0, show_default=True, help="Seconds to monitor batch rechecks.")
@click.option("--monitor-interval", type=float, default=10.0, show_default=True, help="Seconds between batch monitor polls.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually mutate qB. Default is dry-run.")
def rt_qb_mirror_sync_cmd(
    qb_cache_file,
    rt_cache_file,
    rt_session_dir,
    policy_path,
    policy_mode,
    config_path,
    hash_filters,
    limit,
    sleep_row,
    journal_path,
    extra_tags,
    skip_checking,
    recheck_after_add,
    verify_timeout,
    verify_interval,
    wait_for_check,
    monitor,
    monitor_timeout,
    monitor_interval,
    do_apply,
):
    """Mirror safe RT-only rows into qB as stopped torrents."""
    disabled = _rt_qb_mirror_disabled_reason(config_path)
    if disabled:
        print(f"rt-qb-mirror sync disabled reason={disabled}")
        return
    report = _load_client_drift_report(
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
        rt_session_dir=rt_session_dir,
        policy_path=policy_path,
        policy_mode=policy_mode,
    )
    journal = Path(journal_path).expanduser()
    selected, candidate_count, completed_count = _select_client_drift_mirror_rows(
        report,
        hash_filters=hash_filters,
        limit=limit,
        journal_path=journal,
    )
    qb_only_count = report["summary"]["qb_only"]
    _print_rt_qb_summary(
        f"RT→qB mirror sync ({'APPLY' if do_apply else 'DRY RUN'})",
        [
            ("apply", "yes" if do_apply else "no", "green" if do_apply else "yellow"),
            ("policy_mode", report["summary"]["policy_mode"], "cyan"),
            ("rt_only", report["summary"]["rt_only"], "yellow" if report["summary"]["rt_only"] else "green"),
            ("qb_only", qb_only_count, "yellow" if qb_only_count else None),
            ("candidates", candidate_count, "yellow" if candidate_count else "green"),
            ("journal_completed", completed_count, None),
            ("selected", len(selected), "yellow" if selected else "green"),
            ("journal", journal, None),
        ],
    )
    if qb_only_count:
        qb_only_rows = _filtered_client_drift_rows(report, side="qb_only", action=None, limit=0)
        for row in qb_only_rows:
            qb_row = row.get("qb") or {}
            hash_prefix = str(row.get("hash") or "")[:16]
            name = str(row.get("name") or "")
            category = str(qb_row.get("category") or "")
            save_path = str(qb_row.get("save_path") or "")
            state = str(qb_row.get("state") or "")
            cat_text = f"{category or '-':<14}"
            print(
                f"  {_rt_qb_style('qb-only', fg='yellow')} "
                f"{_rt_qb_style(hash_prefix, fg='cyan', bold=True)} "
                f"{_rt_qb_style(cat_text, fg='magenta')} "
                f"{_rt_qb_style(name, fg='bright_white', bold=True)}"
            )
            print(f"     {_rt_qb_style('state:', fg='bright_black')} {state}   "
                  f"{_rt_qb_style('path:', fg='bright_black')} {_rt_qb_style(save_path, fg='bright_blue')}")
    effective_verify_timeout = verify_timeout
    if wait_for_check and effective_verify_timeout <= 0:
        effective_verify_timeout = 180.0
    qbit = None
    if do_apply and monitor:
        from hashall.qbittorrent import get_qbittorrent_client

        qbit = get_qbittorrent_client()
    events = _apply_client_drift_mirror_rows(
        selected,
        do_apply=do_apply,
        journal=journal,
        extra_tags=extra_tags,
        skip_checking=skip_checking,
        recheck_after_add=recheck_after_add,
        verify_timeout=effective_verify_timeout,
        verify_interval=verify_interval,
        sleep_row=sleep_row,
        qbit=qbit,
    )
    if do_apply and monitor and qbit is not None:
        monitor_hashes = [
            str(event.get("hash") or "").lower()
            for event in events
            if event.get("status") in {"ok", "already_present"} and not event.get("error")
        ]
        _monitor_rt_qb_rechecks(
            qbit,
            monitor_hashes,
            timeout_s=monitor_timeout,
            interval_s=monitor_interval,
        )


@rt_qb_mirror.command("process-queue")
@click.option("--queue-dir", type=click.Path(file_okay=False), default=str(DEFAULT_RT_QB_MIRROR_QUEUE_DIR), show_default=True)
@click.option("--min-age", type=float, default=120.0, show_default=True, help="Seconds a queued hash must age before sync.")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--config", "config_path", type=click.Path(dir_okay=False), help="Optional JSON config; {\"enabled\": false} disables the mirror.")
@click.option("--qb-cache-file", default=str(DEFAULT_QB_CACHE_FILE), show_default=True)
@click.option("--rt-cache-file", default=str(DEFAULT_RT_SHARED_CACHE_FILE), show_default=True)
@click.option("--rt-session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True)
@click.option("--policy", "policy_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--policy-mode", type=click.Choice(["conservative", "rt-authoritative-mirror"]), default="rt-authoritative-mirror", show_default=True)
@click.option("--sleep-row", type=float, default=5.0, show_default=True)
@click.option("--journal", "journal_path", type=click.Path(dir_okay=False), default=str(DEFAULT_RT_QB_MIRROR_JOURNAL), show_default=True)
@click.option("--tag", "extra_tags", multiple=True, default=("hashall-rt-qb-mirror",))
@click.option("--skip-checking", is_flag=True)
@click.option(
    "--recheck-after-add/--no-recheck-after-add",
    default=True,
    show_default=True,
)
@click.option("--verify-timeout", type=float, default=0.0, show_default=True)
@click.option("--verify-interval", type=float, default=5.0, show_default=True)
@click.option("--wait-for-check", is_flag=True, help="Wait for qB recheck to reach 100%; uses --verify-timeout or 180s by default.")
@click.option("--monitor/--no-monitor", default=True, show_default=True, help="After queueing all rechecks, monitor them to success/failure.")
@click.option("--monitor-timeout", type=float, default=900.0, show_default=True, help="Seconds to monitor batch rechecks.")
@click.option("--monitor-interval", type=float, default=10.0, show_default=True, help="Seconds between batch monitor polls.")
@click.option("--apply", "do_apply", is_flag=True)
def rt_qb_mirror_process_queue_cmd(
    queue_dir,
    min_age,
    limit,
    config_path,
    qb_cache_file,
    rt_cache_file,
    rt_session_dir,
    policy_path,
    policy_mode,
    sleep_row,
    journal_path,
    extra_tags,
    skip_checking,
    recheck_after_add,
    verify_timeout,
    verify_interval,
    wait_for_check,
    monitor,
    monitor_timeout,
    monitor_interval,
    do_apply,
):
    """Process delayed RT completion queue entries."""
    disabled = _rt_qb_mirror_disabled_reason(config_path)
    if disabled:
        print(f"rt-qb-mirror process-queue disabled reason={disabled}")
        return
    qdir = Path(queue_dir).expanduser()
    qdir.mkdir(parents=True, exist_ok=True)
    ready, waiting = _load_queue_entries(qdir, min_age_s=min_age, now=time.time())
    if limit > 0:
        ready = ready[:limit]
    hash_filters = tuple(entry["hash"] for entry in ready)
    report = _load_client_drift_report(
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
        rt_session_dir=rt_session_dir,
        policy_path=policy_path,
        policy_mode=policy_mode,
    )
    journal = Path(journal_path).expanduser()
    selected, candidate_count, completed_count = _select_client_drift_mirror_rows(
        report,
        hash_filters=hash_filters,
        limit=0,
        journal_path=journal,
    )
    _print_rt_qb_summary(
        f"RT→qB mirror queue ({'APPLY' if do_apply else 'DRY RUN'})",
        [
            ("apply", "yes" if do_apply else "no", "green" if do_apply else "yellow"),
            ("queue_dir", qdir, None),
            ("ready", len(ready), "yellow" if ready else "green"),
            ("waiting", len(waiting), None),
            ("candidates", candidate_count, "yellow" if candidate_count else "green"),
            ("journal_completed", completed_count, None),
            ("selected", len(selected), "yellow" if selected else "green"),
        ],
    )
    effective_verify_timeout = verify_timeout
    if wait_for_check and effective_verify_timeout <= 0:
        effective_verify_timeout = 180.0
    qbit = None
    if do_apply and monitor:
        from hashall.qbittorrent import get_qbittorrent_client

        qbit = get_qbittorrent_client()
    events = _apply_client_drift_mirror_rows(
        selected,
        do_apply=do_apply,
        journal=journal,
        extra_tags=extra_tags,
        skip_checking=skip_checking,
        recheck_after_add=recheck_after_add,
        verify_timeout=effective_verify_timeout,
        verify_interval=verify_interval,
        sleep_row=sleep_row,
        qbit=qbit,
    )
    if do_apply and monitor and qbit is not None:
        monitor_hashes = [
            str(event.get("hash") or "").lower()
            for event in events
            if event.get("status") in {"ok", "already_present"} and not event.get("error")
        ]
        _monitor_rt_qb_rechecks(
            qbit,
            monitor_hashes,
            timeout_s=monitor_timeout,
            interval_s=monitor_interval,
        )
    finished = {
        str(event.get("hash") or "").lower()
        for event in events
        if event.get("status") in {"ok", "already_present"} and not event.get("error")
    }
    selected_hashes = {str(row.get("hash") or "").lower() for row in selected}
    def matched_selected(key: str) -> bool:
        return any(full == key or full.startswith(key) for full in selected_hashes)

    def matched_finished(key: str) -> bool:
        return any(full == key or full.startswith(key) for full in finished)

    for entry in ready:
        key = str(entry["hash"]).lower()
        if do_apply:
            if matched_finished(key):
                Path(entry["path"]).unlink(missing_ok=True)
        elif matched_selected(key):
            print(f"   dry-run would_remove_queue hash={key[:16]} path={entry['path']}")
    blocked = [entry for entry in ready if not matched_selected(str(entry["hash"]).lower())]
    for entry in blocked[:20]:
        print(f"   queued_not_ready_for_mirror hash={entry['hash'][:16]} age_s={entry['age_s']:.0f}")


def _default_content_base_roots() -> list[str]:
    return [
        "/pool/data/orphaned_data",
        "/pool/data/seeds",
        "/pool/data/RecycleBin",
    ]


@content.command("inventory")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--root",
    "base_roots",
    multiple=True,
    help="Base non-qB root to inventory (repeatable). Defaults to orphans/orphaned_data/seeds/RecycleBin.",
)
@click.option("--kind", "root_kind", type=click.Choice(["archive", "orphan", "recovery", "other"]), help="Filter by root kind.")
@click.option("--status", type=click.Choice(["complete", "incomplete"]), help="Filter by hash-completeness status.")
@click.option("--path-contains", help="Only include roots whose path contains this substring.")
@click.option("--min-bytes", type=int, default=0, show_default=True, help="Only include roots at or above this size.")
@click.option("--sort", "sort_by", type=click.Choice(["bytes", "files", "path"]), default="bytes", show_default=True, help="Sort order.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def content_inventory_cmd(db, base_roots, root_kind, status, path_contains, min_bytes, sort_by, limit, json_output):
    """Discover canonical non-qB content roots from scanned files_* metadata."""
    from hashall.content_inventory import discover_content_roots, filter_content_roots, sort_content_roots
    from hashall.model import connect_db

    roots = list(base_roots) or _default_content_base_roots()
    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    items = discover_content_roots(conn, roots)
    conn.close()
    items = filter_content_roots(
        items,
        root_kind=root_kind,
        status=status,
        path_contains=path_contains,
        min_bytes=min_bytes,
    )
    items = sort_content_roots(items, sort_by=sort_by)
    if limit > 0:
        items = items[:limit]

    if json_output:
        print(json.dumps([item.__dict__ for item in items], indent=2))
        return

    print("🗂️  Content inventory (read-only)")
    print(f"   base_roots: {len(roots)}")
    print(f"   discovered_roots: {len(items)}")
    for item in items:
        print(
            f"   {item.root_kind:8s} {item.status:10s} "
            f"files={item.file_count:<6d} sha256={item.files_with_sha256}/{item.file_count} "
            f"bytes={item.total_bytes:,} root={item.root_path}"
        )


@content.command("duplicates")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--root",
    "base_roots",
    multiple=True,
    help="Base non-qB root to inventory (repeatable). Defaults to orphans/orphaned_data/seeds/RecycleBin.",
)
@click.option("--path-contains", help="Only include duplicate groups whose paths contain this substring.")
@click.option("--min-bytes", type=int, default=0, show_default=True, help="Only include groups at or above this size.")
@click.option("--sort", "sort_by", type=click.Choice(["bytes", "count", "path"]), default="bytes", show_default=True, help="Sort order.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit groups shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def content_duplicates_cmd(db, base_roots, path_contains, min_bytes, sort_by, limit, json_output):
    """List exact duplicate non-qB content roots."""
    from hashall.content_inventory import (
        discover_content_roots,
        duplicate_content_roots,
        filter_duplicate_groups,
        sort_duplicate_groups,
    )
    from hashall.model import connect_db

    roots = list(base_roots) or _default_content_base_roots()
    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    groups = duplicate_content_roots(discover_content_roots(conn, roots))
    conn.close()
    groups = filter_duplicate_groups(groups, path_contains=path_contains, min_bytes=min_bytes)
    groups = sort_duplicate_groups(groups, sort_by=sort_by)
    if limit > 0:
        groups = groups[:limit]

    if json_output:
        print(json.dumps([[item.__dict__ for item in group] for group in groups], indent=2))
        return

    print("🔁 Exact duplicate content roots")
    print(f"   groups: {len(groups)}")
    for idx, group in enumerate(groups, start=1):
        first = group[0]
        print(
            f"   [{idx}] files={first.file_count} bytes={first.total_bytes:,} "
            f"tree_hash={str(first.tree_hash or '')[:16]}"
        )
        for item in group:
            print(f"      - {item.root_path}")


@content.command("donors")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--torrent", "torrent_hash", required=True, help="Torrent hash to find donor roots for.")
@click.option(
    "--root",
    "base_roots",
    multiple=True,
    help="Base non-qB root to inventory (repeatable). Defaults to orphans/orphaned_data/seeds/RecycleBin.",
)
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def content_donors_cmd(db, torrent_hash, base_roots, json_output):
    """Find non-qB donor candidates for a qB payload/torrent."""
    from hashall.content_inventory import discover_content_roots, donors_for_torrent
    from hashall.model import connect_db

    roots = list(base_roots) or _default_content_base_roots()
    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    report = donors_for_torrent(conn, torrent_hash, discover_content_roots(conn, roots))
    conn.close()

    if json_output:
        payload = dict(report)
        payload["exact_non_qb_donors"] = [item.__dict__ for item in report["exact_non_qb_donors"]]
        payload["candidate_non_qb_donors"] = [item.__dict__ for item in report["candidate_non_qb_donors"]]
        payload["ranked_candidates"] = [item.__dict__ for item in report.get("ranked_candidates", [])]
        print(json.dumps(payload, indent=2))
        return

    print(f"🩹 Donor candidates for {report['torrent_hash']}")
    print(f"   root_path: {report['root_path']}")
    print(f"   payload_hash: {report['payload_hash'] or '(incomplete)'}")
    print(f"   files={report['file_count']} bytes={report['total_bytes']:,}")
    print(f"   exact_non_qb_donors: {len(report['exact_non_qb_donors'])}")
    for item in report["exact_non_qb_donors"]:
        print(f"      - {item.root_path} ({item.root_kind})")
    print(f"   candidate_non_qb_donors: {len(report['candidate_non_qb_donors'])}")
    for item in report["candidate_non_qb_donors"][:10]:
        print(f"      - {item.root_path} ({item.status} {item.root_kind})")


@content.command("reclaim-report")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--root",
    "base_roots",
    multiple=True,
    help="Base non-qB root to inventory (repeatable). Defaults to orphans/orphaned_data/seeds/RecycleBin.",
)
@click.option("--path-contains", help="Only include duplicate groups whose paths contain this substring.")
@click.option("--min-bytes", type=int, default=0, show_default=True, help="Only include groups at or above this size.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit groups shown; 0 means no limit.")
@click.option("--include-fully-protected", is_flag=True, help="Include duplicate groups where every root is protected by live qB ownership.")
@click.option("--rt-session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="rTorrent session directory used to protect live rt-owned roots.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def content_reclaim_report_cmd(db, base_roots, path_contains, min_bytes, limit, include_fully_protected, rt_session_dir, json_output):
    """Rank exact duplicate non-qB roots into keep/purge candidates."""
    from hashall.content_inventory import (
        discover_content_roots,
        duplicate_content_roots,
        filter_duplicate_groups,
        live_qb_root_paths,
        rank_reclaim_groups,
    )
    from hashall.model import connect_db

    roots = list(base_roots) or _default_content_base_roots()
    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    groups = duplicate_content_roots(discover_content_roots(conn, roots))
    protected_qb_roots = live_qb_root_paths(conn)
    protected_rt_roots = live_rt_root_paths(Path(rt_session_dir).expanduser())
    conn.close()
    groups = filter_duplicate_groups(groups, path_contains=path_contains, min_bytes=min_bytes)
    ranked = rank_reclaim_groups(
        groups,
        protected_qb_roots=protected_qb_roots,
        protected_rt_roots=protected_rt_roots,
        include_fully_protected=include_fully_protected,
    )
    if limit > 0:
        ranked = ranked[:limit]

    if json_output:
        payload = [
            {
                "tree_hash": group.tree_hash,
                "file_count": group.file_count,
                "total_bytes": group.total_bytes,
                "reclaimable_bytes": sum(item.total_bytes for item in group.purge),
                "keep": group.keep.__dict__,
                "purge": [item.__dict__ for item in group.purge],
            }
            for group in ranked
        ]
        print(json.dumps(payload, indent=2))
        return

    total_reclaimable = sum(sum(item.total_bytes for item in group.purge) for group in ranked)
    print("🧹 Duplicate reclaim report (read-only)")
    print(f"   groups: {len(ranked)}")
    print(f"   reclaimable_bytes: {total_reclaimable:,}")
    print(f"   protected_qb_roots: {len(protected_qb_roots)}")
    print(f"   protected_rt_roots: {len(protected_rt_roots)}")
    for idx, group in enumerate(ranked, start=1):
        reclaimable = sum(item.total_bytes for item in group.purge)
        print(
            f"   [{idx}] files={group.file_count} bytes={group.total_bytes:,} "
            f"reclaimable={reclaimable:,} tree_hash={group.tree_hash[:16]}"
        )
        print(f"      keep:  {group.keep.root_path} ({group.keep.reason})")
        for item in group.purge:
            print(f"      purge: {item.root_path}")


@rt.command("session-audit")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent .torrent.rtorrent session files.")
@click.option("--path-contains", help="Only include session rows whose directory contains this substring.")
@click.option("--missing-only", is_flag=True, help="Only include rows whose current rt session path is missing on disk.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def rt_session_audit_cmd(session_dir, path_contains, missing_only, limit, json_output):
    """Audit current rtorrent session roots for missing/existing paths."""
    from hashall.rtorrent import load_rt_session_directories

    rows = list(load_rt_session_directories(Path(session_dir).expanduser()).values())
    needle = str(path_contains or "").strip().lower()
    filtered = []
    for row in rows:
        if missing_only and row.path_exists:
            continue
        if needle and needle not in row.directory.lower():
            continue
        filtered.append(row)
    filtered.sort(key=lambda row: (row.path_exists, row.directory.lower(), row.torrent_hash))
    if limit > 0:
        filtered = filtered[:limit]

    summary = {
        "session_dir": str(Path(session_dir).expanduser()),
        "total_rows": len(rows),
        "missing_rows": sum(1 for row in rows if not row.path_exists),
        "existing_rows": sum(1 for row in rows if row.path_exists),
    }

    if json_output:
        payload = {
            "summary": summary,
            "rows": [row.__dict__ for row in filtered],
        }
        print(json.dumps(payload, indent=2))
        return

    print("🧭 rt session audit")
    print(f"   session_dir: {summary['session_dir']}")
    print(f"   total_rows: {summary['total_rows']}")
    print(f"   missing_rows: {summary['missing_rows']}")
    print(f"   existing_rows: {summary['existing_rows']}")
    for row in filtered:
        state = "exists" if row.path_exists else "missing"
        print(f"   {state:7s} {row.torrent_hash[:16]} {row.directory}")


@rt.command("state-audit")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--cache-file", default=str(DEFAULT_RT_SHARED_CACHE_FILE), show_default=True, help="Shared silo RT cache rows JSON.")
@click.option("--meta-file", default=str(DEFAULT_RT_SHARED_CACHE_META_FILE), show_default=True, help="Shared silo RT cache metadata JSON.")
@click.option("--cache-max-age", type=float, default=60.0, show_default=True, help="Freshness threshold for shared RT cache in seconds.")
@click.option("--live", "use_live", is_flag=True, help="Bypass shared cache and query rTorrent XMLRPC directly. Use only for explicit diagnostics.")
@click.option("--state", "state_filters", multiple=True, help="Only include rows in these derived states.")
@click.option("--bad-only", is_flag=True, help="Only include rows not already in uploading/stalledUP/stoppedUP.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
def rt_state_audit_cmd(rpc_url, cache_file, meta_file, cache_max_age, use_live, state_filters, bad_only, limit, json_output):
    """Audit current rtorrent torrent states from shared cache or live XMLRPC."""
    from hashall.rt_cache import load_rt_cache_snapshot
    from hashall.rtorrent import fetch_rt_status_rows

    if use_live:
        rows = fetch_rt_status_rows(rpc_url=rpc_url)
        summary = {
            "read_mode": "live",
            "rpc_url": rpc_url,
            "rows": len(rows),
            "state_counts": {},
        }
    else:
        snapshot = load_rt_cache_snapshot(
            cache_file=Path(cache_file).expanduser(),
            meta_file=Path(meta_file).expanduser(),
            max_age_s=float(cache_max_age),
        )
        rows = list(snapshot["rows"])
        summary = {
            "read_mode": snapshot["read_mode"],
            "cache_file": snapshot["cache_file"],
            "meta_file": snapshot["meta_file"],
            "cache_source": snapshot["cache_source"],
            "cache_age_s": snapshot["cache_age_s"],
            "cache_max_age_s": snapshot["max_age_s"],
            "freshness": snapshot["freshness"],
            "last_error": snapshot["last_error"],
            "xmlrpc_url": snapshot["xmlrpc_url"],
            "consecutive_failures": snapshot["consecutive_failures"],
            "rows": len(rows),
            "state_counts": {},
        }
    wanted = {str(item).strip() for item in state_filters if str(item).strip()}
    if bad_only:
        rows = [row for row in rows if row["state"] not in {"uploading", "stalledUP", "stoppedUP"}]
    if wanted:
        rows = [row for row in rows if row["state"] in wanted]
    rows.sort(key=lambda row: (row["state"], row["name"].lower(), row["hash"]))
    if limit > 0:
        rows = rows[:limit]

    summary["rows"] = len(rows)
    for row in rows:
        summary["state_counts"][row["state"]] = summary["state_counts"].get(row["state"], 0) + 1

    if json_output:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
        return

    print("📊 rt state audit")
    print(f"   read_mode: {summary['read_mode']}")
    if use_live:
        print(f"   rpc_url: {summary['rpc_url']}")
    else:
        print(f"   cache_file: {summary['cache_file']}")
        print(f"   meta_file: {summary['meta_file']}")
        print(f"   freshness: {summary['freshness']}")
        print(f"   cache_source: {summary['cache_source']}")
        print(f"   cache_age_s: {summary['cache_age_s']}")
        if summary["xmlrpc_url"]:
            print(f"   xmlrpc_url: {summary['xmlrpc_url']}")
        if summary["last_error"]:
            print(f"   last_error: {summary['last_error']}")
        if summary["consecutive_failures"]:
            print(f"   consecutive_failures: {summary['consecutive_failures']}")
    print(f"   rows: {summary['rows']}")
    print(f"   state_counts: {summary['state_counts']}")
    for row in rows:
        print(f"   {row['state']:10s} {row['hash'][:16]} {row['name']} :: {row['directory']}")


@rt.command("repoint")
@click.option("--hash", "torrent_hash", required=True, help="Torrent hash to repoint.")
@click.option("--target-directory", required=True, help="Directory to write via d.directory.set.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute the repoint. Default is dry-run.")
def rt_repoint_cmd(torrent_hash, target_directory, rpc_url, do_apply):
    """Directly repoint a single rtorrent hash to a new directory."""
    from hashall.rtorrent import (
        DEFAULT_RT_SESSION_DIR,
        load_rt_torrent_meta,
        normalize_rt_target_directory,
        rt_apply_directory_repoint,
    )

    torrent_key = str(torrent_hash).strip().lower()
    torrent_meta = load_rt_torrent_meta(DEFAULT_RT_SESSION_DIR, torrent_key)
    normalized_target = normalize_rt_target_directory(target_directory, torrent_meta)

    print("↪️  rt repoint")
    print(f"   hash: {torrent_key}")
    print(f"   target_directory: {target_directory}")
    if normalized_target != target_directory:
        print(f"   normalized_target_directory: {normalized_target}")
    print(f"   rpc_url: {rpc_url}")
    print(f"   apply: {do_apply}")
    if not do_apply:
        return
    completed = rt_apply_directory_repoint(torrent_key, normalized_target, rpc_url=rpc_url)
    print(f"   completed: {completed}")


@rt.command("recheck")
@click.option("--hash", "hash_filters", multiple=True, required=True, help="Torrent hash(es) to recheck.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute the recheck. Default is dry-run.")
def rt_recheck_cmd(hash_filters, rpc_url, do_apply):
    """Force rtorrent to hash-check and restart one or more torrents."""
    from hashall.rtorrent import rt_recheck_torrent

    hashes = [str(item).strip().lower() for item in hash_filters if str(item).strip()]
    print("🔁 rt recheck")
    print(f"   rpc_url: {rpc_url}")
    print(f"   apply: {do_apply}")
    print(f"   hashes: {len(hashes)}")
    for torrent_key in hashes:
        print(f"   hash: {torrent_key}")
        if not do_apply:
            continue
        completed = rt_recheck_torrent(torrent_key, rpc_url=rpc_url)
        print(f"      completed: {completed}")


@rt.command("session-reset")
@click.option("--hash", "hash_filters", multiple=True, required=True, help="Torrent hash(es) to reset from session.")
@click.option("--target-directory", required=True, help="Desired content root to restore after reload.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent session files.")
@click.option("--backup-root", type=click.Path(file_okay=False), default="out/rt-session-reset", show_default=True, help="Backup directory for copied session files.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--rpc-timeout", type=int, default=20, show_default=True, help="Per-call XMLRPC timeout in seconds.")
@click.option("--verify-timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for reload verification.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute the session reset. Default is dry-run.")
def rt_session_reset_cmd(hash_filters, target_directory, session_dir, backup_root, rpc_url, rpc_timeout, verify_timeout, do_apply):
    """Rebuild one or more rt torrents from .torrent plus existing data."""
    from hashall.rtorrent import rt_reset_torrent_session

    hashes = [str(item).strip().lower() for item in hash_filters if str(item).strip()]
    session_path = Path(session_dir).expanduser()
    backup_path = Path(backup_root).expanduser()
    print("♻️  rt session reset")
    print(f"   session_dir: {session_path}")
    print(f"   backup_root: {backup_path}")
    print(f"   target_directory: {target_directory}")
    print(f"   rpc_url: {rpc_url}")
    print(f"   apply: {do_apply}")
    print(f"   hashes: {len(hashes)}")
    for torrent_key in hashes:
        print(f"   hash: {torrent_key}")
        if not do_apply:
            continue
        result = rt_reset_torrent_session(
            torrent_key,
            target_directory=target_directory,
            session_dir=session_path,
            backup_root=backup_path,
            rpc_url=rpc_url,
            rpc_timeout=rpc_timeout,
            verify_timeout_s=verify_timeout,
        )
        status = result.get("status", "unknown")
        print(f"      status: {status}")
        print(f"      backup_dir: {result['backup_dir']}")
        if result["normalized_target_directory"] != target_directory:
            print(f"      normalized_target_directory: {result['normalized_target_directory']}")
        print(f"      completed: {result['completed']}")
        if result.get("recovery_completed"):
            print(f"      recovery_completed: {result['recovery_completed']}")
        if result.get("error"):
            print(f"      error: {result['error']}")
        if status not in {"verified", "verified_after_timeout"}:
            raise click.ClickException(f"rt session reset blocked hash={torrent_key} status={status}")


@rt.command("torrent-replace")
@click.option("--hash", "torrent_hash", required=True, help="Hash (or short prefix) of the RT torrent to replace.")
@click.option("--torrent-file", "torrent_file", type=click.Path(exists=True), default=None, help="Path to replacement .torrent file.")
@click.option("--prowlarr", "use_prowlarr", is_flag=True, help="Search Prowlarr for replacement torrent automatically.")
@click.option("--target-dir", "target_dir", default=None, help="Override save directory (default: current RT directory).")
@click.option("--backup-root", "backup_root", default="out/rt-torrent-replace", show_default=True, help="Directory for session file backups.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=None, help="RT session directory.")
@click.option("--rpc-url", default=None, help="rTorrent XMLRPC endpoint.")
@click.option("--prowlarr-url", default="http://localhost:9696", show_default=True, help="Prowlarr API URL.")
@click.option("--prowlarr-api-key-file", "prowlarr_key_file", default="", help="Prowlarr API key file.")
@click.option("--apply", "do_apply", is_flag=True, help="Execute replacement. Default is dry-run (validation only).")
def rt_torrent_replace_cmd(
    torrent_hash, torrent_file, use_prowlarr, target_dir, backup_root,
    session_dir, rpc_url, prowlarr_url, prowlarr_key_file, do_apply,
):
    """Replace a compromised or corrupted RT torrent, reusing existing on-disk data.

    Supports two input modes (mutually exclusive):

      --torrent-file <path>   Use a locally downloaded .torrent file.
      --prowlarr              Search Prowlarr for a replacement automatically.

    Without --apply, runs in dry-run mode: validates the replacement and reports
    what would happen without touching RT or the session directory.
    """
    from hashall.rt_torrent_replace import (
        validate_replacement,
        fetch_prowlarr_replacement,
        rt_get_torrent_info_live,
        replace_torrent,
    )
    from hashall.rtorrent import DEFAULT_RT_SESSION_DIR, DEFAULT_RT_RPC_URL

    if not torrent_file and not use_prowlarr:
        raise click.UsageError("Provide --torrent-file or --prowlarr.")
    if torrent_file and use_prowlarr:
        raise click.UsageError("--torrent-file and --prowlarr are mutually exclusive.")

    resolved_session = Path(session_dir).expanduser() if session_dir else DEFAULT_RT_SESSION_DIR
    resolved_rpc = rpc_url or DEFAULT_RT_RPC_URL

    print("🔄 rt torrent-replace")
    print(f"   hash:        {torrent_hash}")
    print(f"   source:      {'prowlarr' if use_prowlarr else torrent_file}")
    print(f"   apply:       {do_apply}")

    # Resolve full hash and current RT state
    info = rt_get_torrent_info_live(torrent_hash, rpc_url=resolved_rpc)
    if info is None:
        # Try resolving short hash via session files
        from hashall.rtorrent import load_rt_session_directories
        session_rows = load_rt_session_directories(resolved_session)
        matches = [h for h in session_rows if h.lower().startswith(torrent_hash.lower())]
        if len(matches) == 1:
            torrent_hash = matches[0]
            info = rt_get_torrent_info_live(torrent_hash, rpc_url=resolved_rpc)
        elif len(matches) > 1:
            raise click.ClickException(f"Ambiguous short hash; matches: {matches}")

    if info is None:
        raise click.ClickException(
            f"Hash not found in live RT: {torrent_hash}. "
            "Is the torrent loaded? (paused torrents are still visible)"
        )

    full_hash = torrent_hash.strip().lower()
    current_name = info["name"]
    current_directory = target_dir or info["directory"]
    current_label = info["label"]
    current_size = info["size"]
    current_trackers = info["trackers"]

    print(f"   name:        {current_name}")
    print(f"   directory:   {current_directory}")
    print(f"   label:       {current_label}")
    print(f"   size:        {current_size:,} bytes")
    print(f"   trackers:    {len(current_trackers)} (current)")

    # Acquire replacement bytes
    replacement_bytes: bytes
    if torrent_file:
        replacement_bytes = Path(torrent_file).read_bytes()
        print(f"\n   replacement: {torrent_file}")
    else:
        tracker_host = ""
        # Use first private tracker host as indexer hint — more specific than label.
        # Fall back to label only when the tracker list is fully public (corruption case).
        from hashall.rt_torrent_replace import _PUBLIC_TRACKER_FRAGMENTS as _pub_frags
        from urllib.parse import urlparse
        private_trackers = [u for u in current_trackers if not any(f in u.lower() for f in _pub_frags)]
        if private_trackers:
            tracker_host = urlparse(private_trackers[0]).hostname or ""
        else:
            # All trackers are public (corrupted list) — label is the only reliable hint.
            tracker_host = current_label or ""
        print(f"\n   searching Prowlarr for: {current_name!r} on {tracker_host or '(any)'}...")
        replacement_bytes, source = fetch_prowlarr_replacement(
            current_name,
            tracker_host,
            prowlarr_url=prowlarr_url,
            api_key_file=prowlarr_key_file,
        )
        if replacement_bytes is None:
            raise click.ClickException(f"Prowlarr search returned no result: {source}")
        print(f"   replacement: {source}")

    # Validate
    validation = validate_replacement(full_hash, current_name, current_size, replacement_bytes)
    rep_meta = validation.replacement_meta

    print(f"\n📋 Validation")
    print(f"   ok:           {validation.ok}")
    print(f"   reason:       {validation.reason}")
    if rep_meta:
        print(f"   repl_name:    {rep_meta.name}")
        print(f"   repl_hash:    {rep_meta.infohash}")
        print(f"   repl_size:    {rep_meta.total_bytes:,} bytes")
        print(f"   repl_private: {rep_meta.is_private}")
        print(f"   repl_trackers:{rep_meta.tracker_count}")
        if rep_meta.has_public_trackers:
            print("   ⚠️  replacement still contains public trackers")
        if not rep_meta.is_private:
            print("   ⚠️  replacement is not marked private=1")

    if not validation.ok:
        raise click.ClickException(f"Validation failed: {validation.reason}")

    same_hash = validation.same_hash

    # If replacement has no trackers, inject private ones from current RT state.
    inject_trackers: list[str] = []
    if rep_meta and rep_meta.tracker_count == 0 and current_trackers:
        from hashall.rt_torrent_replace import _PUBLIC_TRACKER_FRAGMENTS as _pub_frags
        inject_trackers = [
            u for u in current_trackers
            if not any(f in u.lower() for f in _pub_frags)
        ]
        if inject_trackers:
            print(f"   inject_trackers: {len(inject_trackers)} private tracker(s) from current state")

    print(f"   operation:    {'same_hash (overwrite + reset)' if same_hash else 'new_hash (load + erase old)'}")

    if not do_apply:
        print("\n✅ Dry-run complete. Pass --apply to execute.")
        return

    print(f"\n⚙️  Executing replacement (apply=True)")
    result = replace_torrent(
        full_hash,
        replacement_bytes,
        directory=current_directory,
        label=current_label,
        inject_trackers=inject_trackers or None,
        session_dir=resolved_session,
        backup_root=Path(backup_root),
        rpc_url=resolved_rpc,
        same_hash=same_hash,
    )

    status = result["status"]
    print(f"   status:      {status}")
    print(f"   old_hash:    {result['old_hash'][:16]}...")
    if result.get("new_hash") and result["new_hash"] != result["old_hash"]:
        print(f"   new_hash:    {result['new_hash'][:16]}...")
    if result.get("backup_dir"):
        print(f"   backup_dir:  {result['backup_dir']}")
    print(f"   completed:   {result['completed']}")
    if result.get("error"):
        print(f"   error:       {result['error']}")

    if status not in {"verified", "verified_after_timeout"}:
        raise click.ClickException(f"Replacement did not complete: status={status}")

    print("\n✅ Replacement complete.")
    if result.get("new_hash") and result["new_hash"] != result["old_hash"]:
        print(f"   Run `hashall payload sync` to update the catalog with the new hash.")


def _load_rt_session_reset_manifest(manifest_path: Path, session_dir: Path) -> list[dict]:
    from hashall.rtorrent import (
        derive_rt_target_directory,
        load_rt_torrent_meta,
        normalize_rt_target_directory,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        source_rows = payload.get("rows") or payload.get("items") or payload.get("repairs") or []
    else:
        source_rows = payload
    if not isinstance(source_rows, list):
        raise click.ClickException("manifest must be a JSON list or object containing rows/items/repairs")

    rows: list[dict] = []
    for raw in source_rows:
        if not isinstance(raw, dict):
            continue
        torrent_hash = str(raw.get("hash") or raw.get("torrent_hash") or "").strip().lower()
        if not torrent_hash:
            continue
        meta = load_rt_torrent_meta(session_dir, torrent_hash)
        target_directory = str(raw.get("target_directory") or raw.get("normalized_target_directory") or "").strip()
        if not target_directory:
            target_directory = derive_rt_target_directory(
                qb_save_path=raw.get("qb_save_path"),
                qb_content_path=raw.get("qb_content_path"),
                torrent_meta=meta,
            )
        target_directory = normalize_rt_target_directory(target_directory, meta)
        rows.append(
            {
                "hash": torrent_hash,
                "name": raw.get("name") or raw.get("torrent_name") or "",
                "target_directory": target_directory,
                "target_exists": bool(target_directory and Path(target_directory).exists()),
            }
        )
    return rows


def _read_rt_session_reset_journal(journal_path: Path) -> set[str]:
    completed: set[str] = set()
    if not journal_path.exists():
        return completed
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("status") in {"verified", "verified_after_timeout"}:
            torrent_hash = str(event.get("hash") or "").strip().lower()
            if torrent_hash:
                completed.add(torrent_hash)
    return completed


def _append_rt_session_reset_journal(journal_path: Path, event: dict) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", time.time())
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


@rt.command("session-reset-batch")
@click.option("--manifest", "manifest_path", type=click.Path(exists=True, dir_okay=False), required=True, help="JSON manifest with hash/target_directory rows.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent session files.")
@click.option("--backup-root", type=click.Path(file_okay=False), default="out/rt-session-reset", show_default=True, help="Backup directory for copied session files.")
@click.option("--journal", "journal_path", type=click.Path(dir_okay=False), default="out/rt-session-reset/session-reset-batch.jsonl", show_default=True, help="JSONL journal for resume/skip.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--rpc-timeout", type=int, default=20, show_default=True, help="Per-call XMLRPC timeout in seconds.")
@click.option("--verify-timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for reload verification.")
@click.option("--sleep-row", type=float, default=2.0, show_default=True, help="Seconds to sleep after each applied row.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit selected rows; 0 means no limit.")
@click.option("--include-missing-target", is_flag=True, help="Allow rows whose target path does not exist.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute resets. Default is dry-run.")
def rt_session_reset_batch_cmd(
    manifest_path,
    session_dir,
    backup_root,
    journal_path,
    rpc_url,
    rpc_timeout,
    verify_timeout,
    sleep_row,
    limit,
    include_missing_target,
    do_apply,
):
    """Apply session-reset rows from a manifest with journaling and pacing."""
    from hashall.rtorrent import rt_reset_torrent_session

    session_path = Path(session_dir).expanduser()
    backup_path = Path(backup_root).expanduser()
    journal = Path(journal_path).expanduser()
    rows = _load_rt_session_reset_manifest(Path(manifest_path).expanduser(), session_path)
    completed_hashes = _read_rt_session_reset_journal(journal)
    selected = []
    skipped_missing = 0
    skipped_completed = 0
    for row in rows:
        if row["hash"] in completed_hashes:
            skipped_completed += 1
            continue
        if not include_missing_target and not row["target_exists"]:
            skipped_missing += 1
            continue
        selected.append(row)
    if limit > 0:
        selected = selected[:limit]

    print("♻️  rt session reset batch")
    print(f"   manifest: {Path(manifest_path).expanduser()}")
    print(f"   session_dir: {session_path}")
    print(f"   backup_root: {backup_path}")
    print(f"   journal: {journal}")
    print(f"   rpc_url: {rpc_url}")
    print(f"   apply: {do_apply}")
    print(f"   manifest_rows: {len(rows)}")
    print(f"   journal_completed: {len(completed_hashes)}")
    print(f"   skipped_completed: {skipped_completed}")
    print(f"   skipped_missing_target: {skipped_missing}")
    print(f"   selected: {len(selected)}")
    for row in selected:
        print(f"   hash: {row['hash']} target={row['target_directory']}")
        if not do_apply:
            continue
        _append_rt_session_reset_journal(
            journal,
            {"event": "started", "hash": row["hash"], "target_directory": row["target_directory"]},
        )
        result = rt_reset_torrent_session(
            row["hash"],
            target_directory=row["target_directory"],
            session_dir=session_path,
            backup_root=backup_path,
            rpc_url=rpc_url,
            rpc_timeout=rpc_timeout,
            verify_timeout_s=verify_timeout,
        )
        _append_rt_session_reset_journal(journal, {"event": "finished", **result})
        print(f"      status: {result.get('status')}")
        if result.get("error"):
            print(f"      error: {result['error']}")
        if result.get("recovery_completed"):
            print(f"      recovery_completed: {result['recovery_completed']}")
        if result.get("status") not in {"verified", "verified_after_timeout"}:
            raise click.ClickException(
                f"rt session reset batch blocked hash={row['hash']} status={result.get('status')}"
            )
        if sleep_row > 0:
            time.sleep(sleep_row)


def _build_rt_repair_rows(report_path: str, session_dir: str, action_bucket: str | None) -> tuple[list[dict], list[dict]]:
    from hashall.rtorrent import (
        derive_rt_target_directory,
        load_rt_session_directories,
        load_rt_torrent_meta,
        normalize_rt_target_directory,
        rt_path_aligned,
    )

    report = json.loads(Path(report_path).expanduser().read_text(encoding="utf-8"))
    source_rows = list(report.get("rows") or [])
    session_path = Path(session_dir).expanduser()
    session_rows = load_rt_session_directories(session_path)
    bucket_filter = str(action_bucket or "").strip()
    rows = []
    for row in source_rows:
        if bucket_filter and row.get("action_bucket") != bucket_filter:
            continue
        torrent_hash = str(row.get("hash") or "").strip().lower()
        if not torrent_hash:
            continue
        session_entry = session_rows.get(torrent_hash)
        current_rt_directory = (
            session_entry.directory if session_entry else str(row.get("rt_directory") or "").strip()
        )
        current_rt_exists = session_entry.path_exists if session_entry else bool(
            current_rt_directory and Path(current_rt_directory).exists()
        )
        candidate_targets = []
        for raw in (row.get("qb_content_path"), row.get("qb_save_path")):
            text = str(raw or "").strip()
            if text and text not in candidate_targets:
                candidate_targets.append(text)
        preferred_target = ""
        preferred_target_exists = False
        for target in candidate_targets:
            if Path(target).exists():
                preferred_target = target
                preferred_target_exists = True
                break
        if not preferred_target and candidate_targets:
            preferred_target = candidate_targets[0]
        torrent_meta = load_rt_torrent_meta(session_path, torrent_hash)
        target_directory = derive_rt_target_directory(
            qb_save_path=row.get("qb_save_path"),
            qb_content_path=row.get("qb_content_path"),
            torrent_meta=torrent_meta,
        )
        target_directory = normalize_rt_target_directory(target_directory, torrent_meta)
        target_directory_exists = bool(target_directory and Path(target_directory).exists())
        aligned_now = rt_path_aligned(
            current_rt_directory,
            qb_save_path=row.get("qb_save_path"),
            qb_content_path=row.get("qb_content_path"),
        ) and current_rt_exists
        if aligned_now:
            repair_status = "aligned_now"
        elif preferred_target_exists and current_rt_exists:
            repair_status = "ready_repoint_drifted_rt_root"
        elif preferred_target_exists:
            repair_status = "ready_repoint_missing_rt_root"
        elif candidate_targets:
            repair_status = "blocked_missing_target"
        else:
            repair_status = "missing_target_info"
        rows.append(
            {
                "hash": torrent_hash,
                "name": row.get("name"),
                "action_bucket": row.get("action_bucket"),
                "repair_status": repair_status,
                "current_rt_directory": current_rt_directory,
                "current_rt_exists": current_rt_exists,
                "preferred_target": preferred_target,
                "preferred_target_exists": preferred_target_exists,
                "target_directory": target_directory,
                "target_directory_exists": target_directory_exists,
                "qb_save_path": row.get("qb_save_path"),
                "qb_content_path": row.get("qb_content_path"),
                "info_name": torrent_meta.info_name if torrent_meta else "",
                "is_multi_file": torrent_meta.is_multi_file if torrent_meta else None,
            }
        )
    rows.sort(
        key=lambda row: (
            row["repair_status"],
            row["action_bucket"] or "",
            str(row["name"] or "").lower(),
            row["hash"],
        )
    )
    return source_rows, rows


@rt.command("repair-report")
@click.option("--report", "report_path", type=click.Path(exists=True, dir_okay=False), required=True, help="Historical drift/repair action-plan JSON to reevaluate against the live rt session.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent .torrent.rtorrent session files.")
@click.option("--action-bucket", help="Only include rows from this action bucket.")
@click.option("--ready-only", is_flag=True, help="Only include rows that are immediately ready for direct repoint.")
@click.option("--unresolved-only", is_flag=True, help="Only include rows that are not already aligned now.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
@click.option("--markdown-output", is_flag=True, help="Emit a markdown checklist.")
def rt_repair_report_cmd(report_path, session_dir, action_bucket, ready_only, unresolved_only, limit, json_output, markdown_output):
    """Reevaluate historical rt repair rows against the live rt session and on-disk targets."""
    source_rows, rows = _build_rt_repair_rows(report_path, session_dir, action_bucket)
    filtered = []
    for row in rows:
        if ready_only and not row["repair_status"].startswith("ready_repoint_"):
            continue
        if unresolved_only and row["repair_status"] == "aligned_now":
            continue
        filtered.append(row)
    rows = filtered
    if limit > 0:
        rows = rows[:limit]

    summary = {
        "report_path": str(Path(report_path).expanduser()),
        "session_dir": str(Path(session_dir).expanduser()),
        "source_rows": len(source_rows),
        "rows": len(rows),
        "repair_status_counts": {},
        "action_bucket_counts": {},
    }
    for row in rows:
        summary["repair_status_counts"][row["repair_status"]] = (
            summary["repair_status_counts"].get(row["repair_status"], 0) + 1
        )
        summary["action_bucket_counts"][row["action_bucket"]] = (
            summary["action_bucket_counts"].get(row["action_bucket"], 0) + 1
        )

    if json_output:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
        return

    if markdown_output:
        print("# RT Repair Report")
        print()
        print(f"- report_path: `{summary['report_path']}`")
        print(f"- session_dir: `{summary['session_dir']}`")
        print(f"- source_rows: `{summary['source_rows']}`")
        print(f"- rows: `{summary['rows']}`")
        print(f"- repair_status_counts: `{summary['repair_status_counts']}`")
        print()
        current_bucket = None
        for idx, row in enumerate(rows, start=1):
            bucket = str(row.get("action_bucket") or "(none)")
            if bucket != current_bucket:
                current_bucket = bucket
                print(f"## {current_bucket}")
                print()
            print(f"### {idx}. {row.get('name')}")
            print()
            print(f"- hash: `{row['hash']}`")
            print(f"- repair_status: `{row['repair_status']}`")
            print(f"- current_rt_directory: `{row['current_rt_directory']}`")
            print(f"- current_rt_exists: `{row['current_rt_exists']}`")
            print(f"- preferred_target: `{row['preferred_target']}`")
            print(f"- preferred_target_exists: `{row['preferred_target_exists']}`")
            print(f"- target_directory: `{row['target_directory']}`")
            print(f"- target_directory_exists: `{row['target_directory_exists']}`")
            print()
        return

    print("🩺 rt repair report")
    print(f"   report_path: {summary['report_path']}")
    print(f"   session_dir: {summary['session_dir']}")
    print(f"   source_rows: {summary['source_rows']}")
    print(f"   rows: {summary['rows']}")
    print(f"   repair_status_counts: {summary['repair_status_counts']}")
    for row in rows:
        print(
            f"   {row['repair_status']:27s} {row['hash'][:16]} "
            f"{row['name']} :: rt={row['current_rt_directory']} -> target={row['target_directory'] or row['preferred_target']}"
        )


@rt.command("repair-apply")
@click.option("--report", "report_path", type=click.Path(exists=True, dir_okay=False), required=True, help="Historical drift/repair action-plan JSON to reevaluate and apply against the live rt session.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent .torrent.rtorrent session files.")
@click.option("--rpc-url", default=DEFAULT_RT_RPC_URL, show_default=True, help="rTorrent XMLRPC endpoint.")
@click.option("--action-bucket", help="Only include rows from this action bucket.")
@click.option("--hash", "hash_filters", multiple=True, help="Restrict apply to specific torrent hash(es).")
@click.option("--include-drifted-existing", is_flag=True, help="Also apply rows where the current rt root exists but should still be repointed.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows applied; 0 means no limit.")
@click.option("--apply", "do_apply", is_flag=True, help="Actually execute rt repoints. Default is dry-run.")
def rt_repair_apply_cmd(report_path, session_dir, rpc_url, action_bucket, hash_filters, include_drifted_existing, limit, do_apply):
    """Apply live rt repair-report rows that are ready for direct repoint."""
    from hashall.rtorrent import rt_apply_directory_repoint

    _, rows = _build_rt_repair_rows(report_path, session_dir, action_bucket)
    hash_set = {str(item).strip().lower() for item in hash_filters if str(item).strip()}
    selected = []
    for row in rows:
        if row["repair_status"] == "ready_repoint_missing_rt_root":
            pass
        elif include_drifted_existing and row["repair_status"] == "ready_repoint_drifted_rt_root":
            pass
        else:
            continue
        if hash_set and row["hash"] not in hash_set:
            continue
        if not row["target_directory"]:
            continue
        selected.append(row)
    if limit > 0:
        selected = selected[:limit]

    print("🛠️  rt repair apply")
    print(f"   report_path: {Path(report_path).expanduser()}")
    print(f"   session_dir: {Path(session_dir).expanduser()}")
    print(f"   rpc_url: {rpc_url}")
    print(f"   apply: {do_apply}")
    print(f"   candidates: {len(selected)}")
    if not selected:
        return

    applied = 0
    errors = 0
    for row in selected:
        print(
            f"   {row['repair_status']:27s} {row['hash'][:16]} "
            f"{row['name']} :: {row['current_rt_directory']} -> {row['target_directory']}"
        )
        if not do_apply:
            continue
        try:
            rt_apply_directory_repoint(row["hash"], row["target_directory"], rpc_url=rpc_url)
            applied += 1
            print("      result: OK")
        except Exception as exc:
            errors += 1
            print(f"      result: ERROR {exc}")
    print(f"   applied: {applied}")
    print(f"   errors: {errors}")


@rt.command("repair-worksheet")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent .torrent.rtorrent session files.")
@click.option("--hash", "hash_filters", multiple=True, help="Restrict worksheet to specific torrent hash(es).")
@click.option("--hash-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Read additional hash filters from a newline-delimited file.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
@click.option("--json-output", is_flag=True, help="Emit JSON.")
@click.option("--markdown-output", is_flag=True, help="Emit markdown.")
def rt_repair_worksheet_cmd(db, session_dir, hash_filters, hash_file, limit, json_output, markdown_output):
    """Build a repair worksheet for RT-linked residuals using current catalog evidence."""
    from hashall.model import connect_db

    requested = [str(item).strip().lower() for item in hash_filters if str(item).strip()]
    if hash_file:
        for raw in Path(hash_file).read_text(encoding="utf-8").splitlines():
            cleaned = raw.strip().lower()
            if cleaned and not cleaned.startswith("#"):
                requested.append(cleaned)

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    rows = _build_rt_repair_worksheet_rows(
        conn,
        session_dir=Path(session_dir).expanduser(),
        hash_filters=requested or None,
    )
    if limit > 0:
        rows = rows[:limit]
    summary = {
        "db": str(Path(db).expanduser()),
        "session_dir": str(Path(session_dir).expanduser()),
        "rows": len(rows),
        "requested_hashes": len(requested),
        "rows_with_candidates": sum(1 for row in rows if row["complete_candidates"]),
        "rows_with_nonzero_nfo": sum(
            1
            for row in rows
            if any(hit["size"] > 0 for hit in row["sidecar_hits"]["nfo"])
        ),
        "rows_with_nonzero_txt": sum(
            1
            for row in rows
            if any(hit["size"] > 0 for hit in row["sidecar_hits"]["txt"])
        ),
        "rows_with_nonzero_sample": sum(
            1
            for row in rows
            if any(hit["size"] > 0 for hit in row["sidecar_hits"]["sample_mkv"])
        ),
    }

    if json_output:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
        return

    if markdown_output:
        print("# RT Repair Worksheet")
        print()
        print(f"- db: `{summary['db']}`")
        print(f"- session_dir: `{summary['session_dir']}`")
        print(f"- rows: `{summary['rows']}`")
        print(f"- requested_hashes: `{summary['requested_hashes']}`")
        print(f"- rows_with_candidates: `{summary['rows_with_candidates']}`")
        print(f"- rows_with_nonzero_nfo: `{summary['rows_with_nonzero_nfo']}`")
        print(f"- rows_with_nonzero_txt: `{summary['rows_with_nonzero_txt']}`")
        print(f"- rows_with_nonzero_sample: `{summary['rows_with_nonzero_sample']}`")
        print()
        for idx, row in enumerate(rows, start=1):
            print(f"## {idx}. {row['root_name'] or row['torrent_hash']}")
            print()
            print(f"- hash: `{row['torrent_hash']}`")
            print(f"- rt_present: `{row['rt_present']}`")
            print(f"- rt_save_path: `{row['rt_save_path']}`")
            print(f"- rt_content_path: `{row['rt_content_path']}`")
            print(f"- expected_file_count: `{row['expected_file_count']}`")
            print(f"- expected_total_bytes: `{row['expected_total_bytes']}`")
            print(f"- catalog_payload_id: `{row['catalog_payload_id']}`")
            print(f"- catalog_payload_root: `{row['catalog_payload_root']}`")
            print(f"- catalog_payload_status: `{row['catalog_payload_status']}`")
            print(f"- complete_candidate_count: `{len(row['complete_candidates'])}`")
            if row["complete_candidates"]:
                print("- complete_candidates:")
                for candidate in row["complete_candidates"]:
                    print(
                        f"  - `{candidate['payload_id']}` `{candidate['file_count']}` files "
                        f"`{candidate['total_bytes']}` bytes `{candidate['root_path']}`"
                    )
            for label in ("nfo", "txt", "sample_mkv"):
                hits = row["sidecar_hits"][label]
                if not hits:
                    continue
                print(f"- {label}_hits:")
                for hit in hits[:5]:
                    print(f"  - `{hit['size']}` `{hit['status']}` `{hit['path']}`")
            print()
        return

    print("🧾 rt repair worksheet")
    print(f"   db: {summary['db']}")
    print(f"   session_dir: {summary['session_dir']}")
    print(f"   rows: {summary['rows']}")
    print(f"   rows_with_candidates: {summary['rows_with_candidates']}")
    print(f"   rows_with_nonzero_nfo: {summary['rows_with_nonzero_nfo']}")
    print(f"   rows_with_nonzero_txt: {summary['rows_with_nonzero_txt']}")
    print(f"   rows_with_nonzero_sample: {summary['rows_with_nonzero_sample']}")
    for row in rows:
        print(
            f"   {row['torrent_hash'][:16]} candidates={len(row['complete_candidates'])} "
            f"nfo={sum(1 for hit in row['sidecar_hits']['nfo'] if hit['size'] > 0)} "
            f"txt={sum(1 for hit in row['sidecar_hits']['txt'] if hit['size'] > 0)} "
            f"sample={sum(1 for hit in row['sidecar_hits']['sample_mkv'] if hit['size'] > 0)} "
            f"{row['root_name']}"
        )


@rt.command("repair-assistant")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--session-dir", type=click.Path(exists=True, file_okay=False), default=str(DEFAULT_RT_SESSION_DIR), show_default=True, help="Directory containing rtorrent .torrent.rtorrent session files.")
@click.option("--hash", "hash_filters", multiple=True, help="Restrict output to specific torrent hash(es).")
@click.option("--hash-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Read additional hash filters from a newline-delimited file.")
@click.option("--limit", type=int, default=0, show_default=True, help="Limit rows shown; 0 means no limit.")
def rt_repair_assistant_cmd(db, session_dir, hash_filters, hash_file, limit):
    """Emit strict read-only repair decisions for RT-linked rows."""
    from hashall.model import connect_db

    requested = [str(item).strip().lower() for item in hash_filters if str(item).strip()]
    if hash_file:
        for raw in Path(hash_file).read_text(encoding="utf-8").splitlines():
            cleaned = raw.strip().lower()
            if cleaned and not cleaned.startswith("#"):
                requested.append(cleaned)

    conn = connect_db(Path(db), read_only=True, apply_migrations=False)
    rows = _build_rt_repair_worksheet_rows(
        conn,
        session_dir=Path(session_dir).expanduser(),
        hash_filters=requested or None,
    )
    if limit > 0:
        rows = rows[:limit]
    print(json.dumps([_build_rt_repair_assistant_row(row) for row in rows], indent=2))


@payload.command("collisions")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--path-prefix",
    "path_prefixes",
    multiple=True,
    help="Only consider payload roots under this path (repeatable).",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    show_default=True,
    help="Limit number of payload roots analyzed. 0 means no limit.",
)
@click.option(
    "--top",
    type=int,
    default=10,
    show_default=True,
    help="Show top N collision groups by size.",
)
def payload_collisions_cmd(db, path_prefixes, limit, top):
    """
    Detect candidate duplicate payloads using a fast signature (quick_hash-based).

    This is a DB-only analysis pass. Use `payload upgrade-collisions` to backfill SHA256
    for the colliding payload roots and compute confirmed payload hashes.
    """
    from hashall.model import connect_db
    from hashall.payload import get_fast_files_for_path, compute_payload_fast_signature
    from hashall.pathing import canonicalize_path, is_under

    conn = connect_db(Path(db))

    prefix_paths = []
    for p in path_prefixes:
        try:
            prefix_paths.append(canonicalize_path(Path(p)))
        except Exception:
            prefix_paths.append(Path(p))

    rows = conn.execute(
        """
        SELECT payload_id, device_id, root_path, status, payload_hash
        FROM payloads
        ORDER BY payload_id
        """
    ).fetchall()

    analyzed = 0
    skipped_prefix = 0
    missing_in_catalog = 0
    missing_quick = 0
    by_fast = {}
    group_meta = {}

    for r in rows:
        if limit and analyzed >= limit:
            break

        payload_id = r["payload_id"]
        device_id = r["device_id"]
        root_path = r["root_path"]

        if prefix_paths:
            try:
                root_canon = canonicalize_path(Path(root_path))
            except Exception:
                root_canon = Path(root_path)
            if not any(is_under(root_canon, pref) for pref in prefix_paths):
                skipped_prefix += 1
                continue

        if device_id is None:
            # Without device_id we can't reliably query per-device tables.
            missing_in_catalog += 1
            analyzed += 1
            continue

        files = get_fast_files_for_path(conn, int(device_id), root_path)
        if not files:
            missing_in_catalog += 1
            analyzed += 1
            continue

        sig = compute_payload_fast_signature(files)
        if sig is None:
            missing_quick += 1
            analyzed += 1
            continue

        total_bytes = sum(f.size for f in files)
        by_fast.setdefault(sig, []).append((payload_id, int(device_id), root_path, total_bytes))
        # Keep one representative metadata record for display
        if sig not in group_meta:
            group_meta[sig] = {"file_count": len(files), "total_bytes": total_bytes}
        analyzed += 1

    collisions = {sig: roots for sig, roots in by_fast.items() if len(roots) > 1}
    colliding_roots = sum(len(v) for v in collisions.values())

    print("🔍 Payload collisions (fast signature)")
    print(f"   analyzed: {analyzed}")
    if prefix_strings:
        print(f"   skipped (path-prefix): {skipped_prefix}")
    print(f"   missing in catalog: {missing_in_catalog}")
    print(f"   missing quick_hash: {missing_quick}")
    print(f"   collision groups: {len(collisions)}")
    print(f"   colliding roots: {colliding_roots}")

    if not collisions:
        return

    ranked = []
    for sig, roots in collisions.items():
        group_bytes = sum(x[3] for x in roots)
        ranked.append((group_bytes, sig, roots))
    ranked.sort(reverse=True, key=lambda t: t[0])

    show = ranked[: max(0, int(top))]
    print(f"\nTop {len(show)} groups (by total bytes):")
    for i, (group_bytes, sig, roots) in enumerate(show, 1):
        print(f" {i}. roots={len(roots)} bytes={group_bytes:,} fast={sig[:16]}...")
        # Keep this short: show up to 3 roots.
        for payload_id, device_id, root_path, _ in roots[:3]:
            print(f"    - #{payload_id} dev={device_id} root={root_path}")
        if len(roots) > 3:
            print(f"    - ... and {len(roots) - 3} more")


@payload.command("upgrade-collisions")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option(
    "--path-prefix",
    "path_prefixes",
    multiple=True,
    help="Only consider payload roots under this path (repeatable).",
)
@click.option(
    "--order",
    type=click.Choice(["cheapest", "largest"], case_sensitive=False),
    default="cheapest",
    show_default=True,
    help="Processing order for collision groups (cheapest = fewest missing SHA256).",
)
@click.option(
    "--max-groups",
    type=int,
    default=0,
    show_default=True,
    help="Process at most N collision groups (after ordering). 0 means no limit.",
)
@click.option("--dry-run", is_flag=True, help="Report what would be upgraded (no hashing/DB writes).")
@click.option("--parallel", is_flag=True, help="Parallel SHA256 hashing for missing hashes.")
@click.option("--workers", type=int, default=None, help="Worker threads for --parallel (default: CPU count).")
@click.option(
    "--hash-progress",
    type=click.Choice(["auto", "minimal", "full"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Hash progress detail level during SHA256 upgrades.",
)
@click.option("--low-priority", is_flag=True, help="Lower CPU/IO priority (nice +15, ionice idle).")
def payload_upgrade_collisions_cmd(db, path_prefixes, order, max_groups, dry_run, parallel, workers, hash_progress, low_priority):
    """
    Upgrade candidate duplicate payloads by backfilling missing SHA256, then computing payload_hash.

    This is the payload-level analogue of "upgrade quick-hash collisions":
    - Find colliding payload roots using fast signatures (quick_hash-based)
    - For those roots only, hash missing SHA256 (inode-aware)
    - Rebuild/upsert payload rows so confirmed payload_hash can be used for sibling grouping
    """
    if low_priority:
        _apply_low_priority()

    from hashall.model import connect_db
    from hashall.payload import (
        get_fast_files_for_path,
        compute_payload_fast_signature,
        build_payload,
        upsert_payload,
        upgrade_payload_missing_sha256,
        count_missing_sha256_for_path,
    )
    from hashall.pathing import canonicalize_path, is_under

    conn = connect_db(Path(db))

    prefix_paths = []
    for p in path_prefixes:
        try:
            prefix_paths.append(canonicalize_path(Path(p)))
        except Exception:
            prefix_paths.append(Path(p))

    payload_rows = conn.execute(
        "SELECT payload_id, device_id, root_path FROM payloads ORDER BY payload_id"
    ).fetchall()

    by_fast = {}
    for r in payload_rows:
        device_id = r["device_id"]
        root_path = r["root_path"]
        payload_id = r["payload_id"]

        if prefix_paths:
            try:
                root_canon = canonicalize_path(Path(root_path))
            except Exception:
                root_canon = Path(root_path)
            if not any(is_under(root_canon, pref) for pref in prefix_paths):
                continue

        if device_id is None:
            continue

        files = get_fast_files_for_path(conn, int(device_id), root_path)
        if not files:
            continue
        sig = compute_payload_fast_signature(files)
        if sig is None:
            continue
        total_bytes = sum(f.size for f in files)
        by_fast.setdefault(sig, []).append((payload_id, int(device_id), root_path, total_bytes))

    collisions = []
    for sig, roots in by_fast.items():
        if len(roots) <= 1:
            continue
        group_bytes = sum(x[3] for x in roots)
        group_missing = sum(count_missing_sha256_for_path(conn, x[1], x[2]) for x in roots)
        collisions.append((group_missing, group_bytes, sig, roots))

    if order.lower() == "largest":
        collisions.sort(reverse=True, key=lambda t: t[1])
    else:
        collisions.sort(key=lambda t: (t[0], t[1]))

    if max_groups:
        collisions = collisions[: int(max_groups)]

    print("⚡ Payload upgrade-collisions")
    if dry_run:
        print("   mode: DRY-RUN (no hashing/DB writes)")
    if prefix_paths:
        print(f"   path-prefixes: {', '.join(str(p) for p in prefix_paths)}")
    print(f"   order: {order.lower()}")
    print(f"   collision groups: {len(collisions)}")

    if not collisions:
        return

    total_roots = sum(len(roots) for _, _, _, roots in collisions)
    print(f"   colliding roots: {total_roots}")

    inode_groups_hashed = 0
    completed = 0
    still_incomplete = 0
    confirmed = {}

    for idx, (group_missing, group_bytes, sig, roots) in enumerate(collisions, 1):
        print(
            f"\n--- group {idx}/{len(collisions)} fast={sig[:16]}... roots={len(roots)} "
            f"bytes={group_bytes:,} missing_sha256={group_missing} ---"
        )

        for payload_id, device_id, root_path, _ in roots:
            if dry_run:
                missing = count_missing_sha256_for_path(conn, device_id, root_path)
                print(f"   - #{payload_id} dev={device_id} missing_sha256={missing} root={root_path}")
                continue

            missing_before = count_missing_sha256_for_path(conn, device_id, root_path)
            print(f"   - #{payload_id} dev={device_id} missing_sha256={missing_before} root={root_path}")

            hash_state = {
                "last_done": 0,
                "last_total": 0,
                "last_bytes_done": 0,
                "last_bytes_total": 0,
                "done_event_seen": False,
            }
            root_reporter = HashProgressReporter(label=root_path, mode=hash_progress.lower())

            def _upgrade_progress(event, done, total, abs_path, **meta):
                hash_state["last_done"] = max(0, int(done or 0))
                hash_state["last_total"] = max(0, int(total or 0))
                hash_state["last_bytes_done"] = max(
                    0,
                    int(meta.get("hashed_bytes") or hash_state["last_bytes_done"]),
                )
                hash_state["last_bytes_total"] = max(
                    0,
                    int(meta.get("total_bytes") or hash_state["last_bytes_total"]),
                )
                if event == "done":
                    hash_state["done_event_seen"] = True
                if event == "start":
                    root_reporter.start(
                        total_groups=hash_state["last_total"],
                        total_bytes=hash_state["last_bytes_total"],
                    )
                    return
                root_reporter.update(
                    event=event,
                    done_groups=hash_state["last_done"],
                    total_groups=hash_state["last_total"],
                    path=abs_path,
                    file_bytes_done=meta.get("group_bytes_done"),
                    file_bytes_total=meta.get("group_bytes_total"),
                    batch_bytes_done=hash_state["last_bytes_done"],
                    batch_bytes_total=hash_state["last_bytes_total"],
                )

            upgraded = upgrade_payload_missing_sha256(
                conn,
                root_path,
                device_id=device_id,
                parallel=parallel,
                workers=workers,
                progress_cb=_upgrade_progress,
            )
            if hash_state["last_total"] > 0 and not hash_state["done_event_seen"]:
                root_reporter.finish(
                    done_groups=hash_state["last_done"],
                    total_groups=hash_state["last_total"],
                    batch_bytes_done=hash_state["last_bytes_done"],
                    batch_bytes_total=hash_state["last_bytes_total"],
                )
            inode_groups_hashed += upgraded

            payload = build_payload(conn, root_path, device_id=device_id)
            upsert_payload(conn, payload)

            if payload.status == "complete" and payload.payload_hash:
                confirmed.setdefault(payload.payload_hash, []).append((payload_id, root_path))
                completed += 1
                print(
                    f"     -> complete hash={payload.payload_hash[:16]}... "
                    f"files={payload.file_count} bytes={payload.total_bytes:,} upgraded_inodes={upgraded}"
                )
            else:
                still_incomplete += 1
                print(f"     -> incomplete upgraded_inodes={upgraded}")

    if dry_run:
        return

    print("\n✅ Upgrade complete")
    print(f"   inode-groups hashed: {inode_groups_hashed}")
    print(f"   payloads complete: {completed}")
    print(f"   payloads still incomplete: {still_incomplete}")

    confirmed_dupes = {h: roots for h, roots in confirmed.items() if len(roots) > 1}
    print(f"   confirmed duplicate payloads: {len(confirmed_dupes)}")
    if confirmed_dupes:
        print("\nTop confirmed dupes:")
        for h, roots in list(confirmed_dupes.items())[:10]:
            print(f" - hash={h[:16]}... roots={len(roots)}")
            for payload_id, root_path in roots[:3]:
                print(f"    - #{payload_id} {root_path}")
            if len(roots) > 3:
                print(f"    - ... and {len(roots) - 3} more")


@cli.command("stats")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--hash-coverage", is_flag=True, help="Show hash coverage statistics.")
@click.option("--show-roots", is_flag=True, help="Show recent scanned roots (noisy).")
@click.option("--roots-limit", type=int, default=10, show_default=True,
              help="Limit for recent roots list (requires --show-roots).")
def stats_cmd(db, hash_coverage, show_roots, roots_limit):
    """Display catalog statistics."""
    import os
    from hashall.model import connect_db

    db_path = Path(db)

    # Check if database exists
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run 'hashall scan <path>' to create a catalog.")
        return

    # Get database file size
    db_size_bytes = os.path.getsize(db_path)

    # Connect to database
    conn = connect_db(db_path)

    # Helper function to format bytes as human-readable
    def format_size(bytes_val):
        if bytes_val is None or bytes_val == 0:
            return "0 B"

        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_idx = 0
        size = float(bytes_val)

        while size >= 1024 and unit_idx < len(units) - 1:
            size /= 1024
            unit_idx += 1

        if unit_idx == 0:
            return f"{int(size)} {units[unit_idx]}"
        elif size >= 100:
            return f"{size:.0f} {units[unit_idx]}"
        elif size >= 10:
            return f"{size:.1f} {units[unit_idx]}"
        else:
            return f"{size:.2f} {units[unit_idx]}"

    # Print header
    print("Hashall Catalog Statistics")
    print(f"  Database: {db_path}")
    print(f"  Database Size: {format_size(db_size_bytes)}")
    print()

    # Get device statistics
    devices = conn.execute("""
        SELECT
            device_alias,
            device_id,
            fs_uuid,
            mount_point,
            preferred_mount_point,
            fs_type,
            zfs_pool_name,
            zfs_dataset_name,
            zfs_pool_guid,
            total_files,
            total_bytes,
            scan_count
        FROM devices
        ORDER BY device_alias
    """).fetchall()

    if devices:
        print(f"  Devices: {len(devices)}")

        total_active_files = 0
        total_bytes = 0

        for device in devices:
            alias = device['device_alias'] or '(unnamed)'
            device_id = device['device_id']
            files = device['total_files'] or 0
            bytes_val = device['total_bytes'] or 0
            scan_count = device['scan_count'] or 0

            total_active_files += files
            total_bytes += bytes_val

            print(f"    {alias:15} ({device_id}): {files:,} files, {format_size(bytes_val)}, scans: {scan_count}")
            print(f"      fs_uuid: {device['fs_uuid']}")
            preferred = device['preferred_mount_point'] or device['mount_point']
            print(f"      preferred: {preferred}")
            from hashall.fs_utils import get_mount_point
            detected_mount = get_mount_point(device['mount_point'] or preferred)
            if detected_mount and detected_mount != preferred:
                print(f"      mount_detected: {detected_mount}")
            if show_roots and device['mount_point'] and device['mount_point'] != preferred:
                print(f"      mount_recorded: {device['mount_point']}")
            if device['fs_type']:
                print(f"      fs_type: {device['fs_type']}")
            zfs_bits = []
            if device['zfs_pool_name']:
                zfs_bits.append(f"pool={device['zfs_pool_name']}")
            if device['zfs_dataset_name']:
                zfs_bits.append(f"dataset={device['zfs_dataset_name']}")
            if device['zfs_pool_guid']:
                zfs_bits.append(f"guid={device['zfs_pool_guid']}")
            if zfs_bits:
                print(f"      zfs: {', '.join(zfs_bits)}")

        print()

        # Count deleted files across all files_* tables
        total_deleted = 0
        for device in devices:
            device_id = device['device_id']
            table_name = get_files_table_name(conn.cursor(), device_id=device_id)
            if not table_name:
                continue
            table_ident = _quote_sql_identifier(table_name)

            # Check if table exists
            table_exists = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE name=?
            """, (table_name,)).fetchone()

            if table_exists:
                result = conn.execute(f"""
                    SELECT COUNT(*) as count
                    FROM {table_ident}
                    WHERE status='deleted'
                """).fetchone()
                total_deleted += result['count'] if result else 0

        print(f"  Total Files: {total_active_files:,} active, {total_deleted:,} deleted")
        print(f"  Total Size: {format_size(total_bytes)}")
    else:
        print("  Devices: 0")
        print("  (No devices scanned yet)")

    print()

    # Get scan history
    last_scan = conn.execute("""
        SELECT
            scan_id,
            fs_uuid,
            root_path,
            completed_at,
            status
        FROM scan_sessions
        WHERE status = 'completed'
        ORDER BY completed_at DESC
        LIMIT 1
    """).fetchone()

    total_scans = conn.execute("""
        SELECT COUNT(*) as count
        FROM scan_sessions
        WHERE status = 'completed'
    """).fetchone()

    def _shorten_path(path_value: str, max_len: int = 100) -> str:
        if len(path_value) <= max_len:
            return path_value
        head = path_value[:50]
        tail = path_value[-40:]
        return f"{head}...{tail}"

    print("  Scan History:")
    if last_scan:
        # Get device alias for the last scan
        device = conn.execute("""
            SELECT device_alias, preferred_mount_point, mount_point
            FROM devices
            WHERE fs_uuid = ?
        """, (last_scan['fs_uuid'],)).fetchone()

        device_name = device['device_alias'] if device else 'unknown'
        preferred_mount = (device['preferred_mount_point'] if device else None) or (device['mount_point'] if device else None)

        # Format timestamp (remove microseconds if present)
        timestamp = last_scan['completed_at']
        if timestamp and '.' in timestamp:
            timestamp = timestamp.split('.')[0]

        print(f"    Last Scan: {timestamp} ({device_name})")
        root_path = last_scan['root_path'] or ""
        if preferred_mount:
            try:
                rel = Path(root_path).relative_to(Path(preferred_mount))
                rel_str = "." if str(rel) == "." else str(rel)
                root_display = f"{preferred_mount} (rel: {rel_str})"
            except Exception:
                root_display = root_path
        else:
            root_display = root_path
        if root_display:
            print(f"      Root (canonical): {_shorten_path(root_display)}")
        print(f"      Status: {last_scan['status']}")
        print(f"    Scan Sessions (completed): {total_scans['count'] if total_scans else 0}")
    else:
        print("    (No completed scans yet)")

    # Scan roots summary
    if devices:
        roots_total = conn.execute("""
            SELECT COUNT(*) as count
            FROM scan_roots
        """).fetchone()
        total_roots = roots_total['count'] if roots_total else 0
        print(f"    Distinct Roots: {total_roots}")

        if show_roots and total_roots > 0:
            recent_roots = conn.execute("""
                SELECT r.root_path, r.last_scanned_at, r.scan_count, d.device_alias
                FROM scan_roots r
                LEFT JOIN devices d ON d.fs_uuid = r.fs_uuid
                ORDER BY r.last_scanned_at DESC
                LIMIT ?
            """, (roots_limit,)).fetchall()

            if recent_roots:
                print("    Recent Roots:")
                for row in recent_roots:
                    alias = row['device_alias'] or 'unknown'
                    ts = row['last_scanned_at']
                    if ts and '.' in ts:
                        ts = ts.split('.')[0]
                    print(f"      {row['root_path']} (last: {ts}, scans: {row['scan_count']}, device: {alias})")

    # Hash coverage statistics
    if hash_coverage and devices:
        print()
        print("  Hash Coverage:")

        total_with_quick = 0
        total_with_sha1 = 0
        total_with_sha256 = 0
        total_collision_groups = 0

        for device in devices:
            device_id = device['device_id']
            table_name = get_files_table_name(conn.cursor(), device_id=device_id)
            if not table_name:
                continue
            table_ident = _quote_sql_identifier(table_name)

            # Check if table exists
            table_exists = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE name=?
            """, (table_name,)).fetchone()

            if table_exists:
                # Detect available columns (sha256 may not exist yet)
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_ident})")}
                has_sha256_col = "sha256" in columns

                # Get hash coverage for this device
                if has_sha256_col:
                    result = conn.execute(f"""
                        SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN quick_hash IS NOT NULL THEN 1 ELSE 0 END) as has_quick,
                            SUM(CASE WHEN sha1 IS NOT NULL THEN 1 ELSE 0 END) as has_sha1,
                            SUM(CASE WHEN sha256 IS NOT NULL THEN 1 ELSE 0 END) as has_sha256
                        FROM {table_ident}
                        WHERE status = 'active'
                    """).fetchone()
                else:
                    result = conn.execute(f"""
                        SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN quick_hash IS NOT NULL THEN 1 ELSE 0 END) as has_quick,
                            SUM(CASE WHEN sha1 IS NOT NULL THEN 1 ELSE 0 END) as has_sha1
                        FROM {table_ident}
                        WHERE status = 'active'
                    """).fetchone()

                if result:
                    total = result['total'] or 0
                    has_quick = result['has_quick'] or 0
                    has_sha1 = result['has_sha1'] or 0

                    total_with_quick += has_quick
                    total_with_sha1 += has_sha1
                    if has_sha256_col:
                        total_with_sha256 += result["has_sha256"] or 0

                    # Count collision groups for this device
                    collision_result = conn.execute(f"""
                        SELECT COUNT(DISTINCT quick_hash) as collision_count
                        FROM (
                            SELECT quick_hash
                            FROM {table_ident}
                            WHERE status = 'active' AND quick_hash IS NOT NULL
                            GROUP BY quick_hash
                            HAVING COUNT(*) > 1
                        )
                    """).fetchone()

                    if collision_result:
                        total_collision_groups += collision_result['collision_count'] or 0

        if total_active_files > 0:
            quick_pct = (total_with_quick / total_active_files) * 100
            # Legacy SHA1 coverage (optional)
            pending_sha256 = total_active_files - total_with_sha256
            pending_sha1 = total_active_files - total_with_sha1

            print(f"    Quick hash: {total_with_quick:,} ({quick_pct:.1f}%)")
            if total_with_sha256:
                sha256_pct = (total_with_sha256 / total_active_files) * 100
                print(f"    SHA256:     {total_with_sha256:,} ({sha256_pct:.1f}%)")
                print(f"    Pending:    {pending_sha256:,} ({100-sha256_pct:.1f}%)")
            if total_with_sha1:
                sha1_pct = (total_with_sha1 / total_active_files) * 100
                print(f"    SHA1 (legacy): {total_with_sha1:,} ({sha1_pct:.1f}%)")
                if total_with_sha256 == 0:
                    print(f"    Pending:    {pending_sha1:,} ({100-sha1_pct:.1f}%)")

            if total_collision_groups > 0:
                print(f"    Collision groups: {total_collision_groups}")

    conn.close()


@cli.command("sha256-backfill")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", default=None, help="Device alias or device_id to backfill.")
@click.option("--batch-size", type=int, default=200, help="Batch size for updates.")
@click.option("--limit", type=int, default=None, help="Max files to process (for testing).")
@click.option("--dry-run", is_flag=True, help="Compute hashes but do not write.")
def sha256_backfill_cmd(db, device, batch_size, limit, dry_run):
    """Backfill SHA256 for files missing it (resumable)."""
    from hashall.sha256_migration import backfill_sha256

    backfill_sha256(
        db_path=Path(db),
        device=device,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
    )


@cli.command("sha256-verify")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", default=None, help="Device alias or device_id to verify.")
@click.option("--sample", type=int, default=50, help="Number of files to sample per device.")
def sha256_verify_cmd(db, device, sample):
    """Spot-check stored SHA256 values against disk contents."""
    from hashall.sha256_migration import verify_sha256

    verify_sha256(
        db_path=Path(db),
        device=device,
        sample=sample,
    )


@cli.command("dupes")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", required=True, help="Device alias or device_id to scan for duplicates.")
@click.option("--auto-upgrade/--no-auto-upgrade", default=True,
              help="Automatically upgrade collision groups to full SHA256 (default: enabled).")
@click.option("--show-paths", is_flag=True, help="Show full paths for duplicate files.")
def dupes_cmd(db, device, auto_upgrade, show_paths):
    """
    Find duplicate files within a device.

    Detects files with matching quick_hash (1MB samples), and optionally
    auto-upgrades collision groups to full SHA256 to identify true duplicates.

    Example:
        hashall dupes --device pool --auto-upgrade
        hashall dupes --device 49 --no-auto-upgrade --show-paths
    """
    from hashall.model import connect_db
    from hashall.scan import find_duplicates

    db_path = Path(db)

    # Check if database exists
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        print("Run 'hashall scan <path>' to create a catalog.")
        return

    conn = connect_db(db_path)
    cursor = conn.cursor()

    # Find device by alias or device_id
    device_row = None

    # Try lookup by alias
    cursor.execute("""
        SELECT device_id, device_alias, mount_point
        FROM devices WHERE device_alias = ?
    """, (device,))
    device_row = cursor.fetchone()

    # If not found, try by device_id
    if not device_row and device.isdigit():
        cursor.execute("""
            SELECT device_id, device_alias, mount_point
            FROM devices WHERE device_id = ?
        """, (int(device),))
        device_row = cursor.fetchone()

    if not device_row:
        print(f"❌ Device not found: {device}")
        print("Run 'hashall devices list' to see available devices.")
        conn.close()
        return

    device_id = device_row['device_id']
    device_alias = device_row['device_alias'] or f"device_{device_id}"

    conn.close()

    # Find duplicates
    print(f"🔍 Finding duplicates on {device_alias}...")
    duplicates = find_duplicates(device_id, db_path, auto_upgrade=auto_upgrade)

    if not duplicates:
        print("✅ No duplicates found!")
        return

    # Display results
    print()
    print(f"📊 Found {len(duplicates)} duplicate group(s):")
    print()

    total_files = 0
    total_wasted_space = 0

    for i, (sha256, files) in enumerate(duplicates.items(), 1):
        file_count = len(files)
        file_size = files[0]['size']  # All files have same size
        wasted = file_size * (file_count - 1)  # Space that could be saved

        total_files += file_count
        total_wasted_space += wasted

        print(f"  Group {i}: {file_count} files, {file_size:,} bytes each")
        print(f"    SHA256: {sha256[:16]}...")
        print(f"    Wasted space: {wasted:,} bytes")

        if show_paths:
            for f in files:
                print(f"      • {f['path']}")
        print()

    # Summary
    def format_size(bytes_val):
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_idx = 0
        size = float(bytes_val)
        while size >= 1024 and unit_idx < len(units) - 1:
            size /= 1024
            unit_idx += 1
        if unit_idx == 0:
            return f"{int(size)} {units[unit_idx]}"
        else:
            return f"{size:.1f} {units[unit_idx]}"

    print(f"📈 Summary:")
    print(f"   Total duplicate files: {total_files:,}")
    print(f"   Total wasted space: {format_size(total_wasted_space)} ({total_wasted_space:,} bytes)")
    print()
    print(f"💡 Tip: Run deduplication to hardlink duplicates and reclaim space")


# Link deduplication command group
@cli.group()
def link():
    """Link deduplication commands (analyze, plan, execute)."""
    pass


@link.command("analyze")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", required=False, help="Device alias or device_id to analyze.")
@click.option("--cross-device", is_flag=True, help="Analyze duplicates across devices.")
@click.option("--min-size", type=int, default=0, help="Minimum file size in bytes (default: 0).")
@click.option("--format", type=click.Choice(['text', 'json']), default='text', help="Output format.")
def link_analyze_cmd(db, device, cross_device, min_size, format):
    """
    Analyze catalog for deduplication opportunities.

    Identifies files with same content (SHA256) but different inodes on the same device.
    Reports potential space savings from hardlinking duplicates.

    Examples:
        hashall link analyze --device pool
        hashall link analyze --device stash --min-size 1048576  # 1MB+
        hashall link analyze --device 49 --format json
    """
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_analysis import (
        analyze_device,
        analyze_cross_device,
        format_analysis_text,
        format_analysis_json,
        format_cross_device_text,
        format_cross_device_json,
    )

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    if cross_device:
        try:
            result = analyze_cross_device(conn, min_size=min_size)
            if format == 'json':
                click.echo(format_cross_device_json(result))
            else:
                click.echo(format_cross_device_text(result))
            conn.close()
            return 0
        except Exception as e:
            click.echo(f"❌ Error: {e}", err=True)
            conn.close()
            return 1

    if not device:
        click.echo("❌ Must specify --device or --cross-device", err=True)
        conn.close()
        return 1

    # Resolve device (try alias first, then device_id if numeric)
    cursor.execute(
        "SELECT device_id FROM devices WHERE device_alias = ?",
        (device,)
    )
    result_row = cursor.fetchone()

    if not result_row and device.isdigit():
        cursor.execute(
            "SELECT device_id FROM devices WHERE device_id = ?",
            (int(device),)
        )
        result_row = cursor.fetchone()

    if not result_row:
        click.echo(f"❌ Device not found: {device}", err=True)
        click.echo(f"💡 Tip: Use 'hashall devices list' to see available devices", err=True)
        conn.close()
        return 1

    device_id = result_row[0]

    try:
        # Run analysis
        result = analyze_device(conn, device_id, min_size=min_size)

        # Format output
        if format == 'json':
            click.echo(format_analysis_json(result))
        else:
            click.echo(format_analysis_text(result))

        conn.close()
        return 0

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        conn.close()
        return 1
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        return 1


@link.command("plan")
@click.argument("name")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", required=True, help="Device alias or device_id to plan for.")
@click.option("--min-size", type=int, default=1, help="Minimum file size in bytes (default: 1).")
@click.option("--include-empty", is_flag=True, help="Include zero-length files (sets --min-size=0).")
@click.option("--dry-run", is_flag=True, help="Generate plan without saving to database.")
@click.option("--upgrade-collisions/--no-upgrade-collisions", default=True,
              help="Upgrade quick-hash collisions to SHA256 before planning.")
def link_plan_cmd(name, db, device, min_size, include_empty, dry_run, upgrade_collisions):
    """
    Create a deduplication plan.

    Analyzes device and generates a plan of hardlink actions to deduplicate files.
    Plan is saved to database and can be reviewed with 'link show-plan' command.

    Examples:
        hashall link plan "Monthly pool dedupe" --device pool
        hashall link plan "Stash cleanup" --device stash --min-size 1048576
        hashall link plan "Include empties" --device pool --include-empty
        hashall link plan "Test plan" --device 49 --dry-run
    """
    import threading
    import time
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_planner import create_plan, save_plan, format_plan_summary
    from hashall.scan import upgrade_quick_hash_collisions

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    # Resolve device (try alias first, then device_id if numeric)
    cursor.execute(
        "SELECT device_id FROM devices WHERE device_alias = ?",
        (device,)
    )
    result_row = cursor.fetchone()

    if not result_row and device.isdigit():
        cursor.execute(
            "SELECT device_id FROM devices WHERE device_id = ?",
            (int(device),)
        )
        result_row = cursor.fetchone()

    if not result_row:
        click.echo(f"❌ Device not found: {device}", err=True)
        click.echo(f"💡 Tip: Use 'hashall devices list' to see available devices", err=True)
        conn.close()
        return 1

    device_id = result_row[0]

    try:
        if include_empty:
            min_size = 0
        # Create plan
        click.echo(f"📋 Creating deduplication plan: \"{name}\"")
        click.echo(f"   Device: {device} ({device_id})")
        if upgrade_collisions:
            upgraded = upgrade_quick_hash_collisions(device_id, Path(db), quiet=False)
            if upgraded > 0:
                click.echo(f"   Upgraded collision groups: {upgraded}")
        click.echo(f"   Analyzing...")
        click.echo()

        progress_state = {
            "stage": "analysis_start",
            "groups_processed": 0,
            "groups_total": 0,
            "actions_generated": 0,
        }
        progress_lock = threading.Lock()
        heartbeat_stop = threading.Event()
        started = time.monotonic()

        def _update_progress(**kwargs):
            with progress_lock:
                progress_state.update(kwargs)

        def _heartbeat():
            while not heartbeat_stop.wait(20.0):
                with progress_lock:
                    stage = progress_state.get("stage", "analysis")
                    groups_processed = int(progress_state.get("groups_processed", 0) or 0)
                    groups_total = progress_state.get("groups_total", 0) or 0
                    actions_generated = int(progress_state.get("actions_generated", 0) or 0)
                elapsed = int(time.monotonic() - started)
                total_label = groups_total if groups_total else "?"
                click.echo(
                    f"   ⏳ still working ({elapsed}s) "
                    f"stage={stage} groups={groups_processed}/{total_label} "
                    f"actions={actions_generated}"
                )

        heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            plan = create_plan(
                conn,
                name,
                device_id,
                min_size=min_size,
                progress_callback=_update_progress,
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=0.2)

        if dry_run:
            # Dry-run mode: just show plan, don't save
            click.echo("🔍 DRY-RUN MODE (plan not saved)")
            click.echo()
            click.echo(format_plan_summary(plan))
            conn.close()
            return 0

        # Save plan to database
        plan_id = save_plan(conn, plan)

        # Show summary
        click.echo("✅ Plan created successfully!")
        click.echo()
        click.echo(format_plan_summary(plan, plan_id=plan_id))

        conn.close()
        return 0

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        conn.close()
        return 1


@link.command("verify-scope")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--plan-id", type=int, default=None, help="Plan ID to verify (default: latest matching plan).")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--max-examples", type=int, default=10, help="Max out-of-scope examples to show.")
@click.option("--update-plan/--no-update-plan", default=True, help="Store verification result in plan metadata.")
def link_verify_scope_cmd(path, plan_id, db, max_examples, update_plan):
    """
    Verify that link plan actions are scoped under a root path.
    """
    import json
    from datetime import datetime
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.pathing import canonicalize_path, is_under
    from hashall.fs_utils import get_mount_source, get_zfs_metadata
    from hashall.scan import _canonicalize_root

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    root_resolved = Path(path).resolve()
    root_canonical = canonicalize_path(root_resolved)
    device_id = os.stat(root_canonical).st_dev

    device_row = cursor.execute("""
        SELECT device_alias, mount_point, preferred_mount_point
        FROM devices WHERE device_id = ?
    """, (device_id,)).fetchone()
    if not device_row:
        click.echo(f"❌ Device not found for path: {root_canonical}", err=True)
        conn.close()
        return 1

    device_alias, current_mount, preferred_mount = device_row[0], Path(device_row[1]), Path(device_row[2] or device_row[1])
    mount_source = get_mount_source(str(root_canonical)) or ""
    canonical_root = _canonicalize_root(
        root_canonical, current_mount, preferred_mount, allow_remap=bool(mount_source)
    )
    effective_mount = preferred_mount if is_under(canonical_root, preferred_mount) else current_mount
    try:
        rel_root = canonical_root.relative_to(effective_mount)
    except ValueError:
        rel_root = Path(".")
    rel_root_str = str(rel_root)

    if plan_id is None:
        if rel_root_str == ".":
            plan_row = cursor.execute("""
                SELECT id, name, status, metadata, created_at
                FROM link_plans
                WHERE device_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (device_id,)).fetchone()
        else:
            pattern = f"{rel_root_str}/%"
            plan_row = cursor.execute("""
                SELECT lp.id, lp.name, lp.status, lp.metadata, lp.created_at
                FROM link_plans lp
                WHERE lp.device_id = ?
                  AND EXISTS (
                        SELECT 1 FROM link_actions la
                        WHERE la.plan_id = lp.id
                          AND (
                               la.canonical_path = ? OR la.canonical_path LIKE ?
                            OR la.duplicate_path = ? OR la.duplicate_path LIKE ?
                          )
                  )
                ORDER BY lp.created_at DESC
                LIMIT 1
            """, (device_id, rel_root_str, pattern, rel_root_str, pattern)).fetchone()
        if not plan_row:
            click.echo("❌ No matching plan found", err=True)
            conn.close()
            return 1
        plan_id, plan_name, plan_status, plan_metadata, plan_created = plan_row
    else:
        plan_row = cursor.execute("""
            SELECT id, name, status, metadata, created_at
            FROM link_plans WHERE id = ?
        """, (plan_id,)).fetchone()
        if not plan_row:
            click.echo(f"❌ Plan not found: {plan_id}", err=True)
            conn.close()
            return 1
        plan_id, plan_name, plan_status, plan_metadata, plan_created = plan_row

    total_actions = cursor.execute(
        "SELECT COUNT(*) FROM link_actions WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()[0]

    out_of_scope = 0
    examples = []
    if rel_root_str != ".":
        pattern = f"{rel_root_str}/%"
        out_of_scope = cursor.execute("""
            SELECT COUNT(*) FROM link_actions
            WHERE plan_id = ?
              AND (
                    NOT (canonical_path = ? OR canonical_path LIKE ?)
                 OR NOT (duplicate_path = ? OR duplicate_path LIKE ?)
              )
        """, (plan_id, rel_root_str, pattern, rel_root_str, pattern)).fetchone()[0]

        if out_of_scope > 0 and max_examples > 0:
            examples = cursor.execute("""
                SELECT canonical_path, duplicate_path
                FROM link_actions
                WHERE plan_id = ?
                  AND (
                        NOT (canonical_path = ? OR canonical_path LIKE ?)
                     OR NOT (duplicate_path = ? OR duplicate_path LIKE ?)
                  )
                LIMIT ?
            """, (plan_id, rel_root_str, pattern, rel_root_str, pattern, max_examples)).fetchall()

    click.echo(f"🔎 Plan #{plan_id}: {plan_name} ({plan_status})")
    click.echo(f"   Path: {canonical_root}")
    zfs_meta = get_zfs_metadata(str(canonical_root))
    zfs_dataset = zfs_meta.get("dataset_name") if zfs_meta else None
    if not zfs_dataset:
        source = get_mount_source(str(canonical_root))
        if source and not source.startswith("/"):
            zfs_dataset = source
    if zfs_dataset:
        click.echo(f"   ZFS dataset: {zfs_dataset}")
    else:
        click.echo("   ZFS dataset: (not detected)")
    click.echo(f"   Relative root: {rel_root_str}")
    click.echo(f"   Actions: {total_actions}")
    click.echo(f"   Out of scope: {out_of_scope}")
    if examples:
        click.echo("   Examples:")
        for canonical_path, duplicate_path in examples:
            click.echo(f"     keep={canonical_path} replace={duplicate_path}")

    if update_plan:
        metadata = {}
        if plan_metadata:
            try:
                metadata = json.loads(plan_metadata)
            except json.JSONDecodeError:
                metadata = {}
        metadata.update({
            "scope_verified_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
            "scope_root": str(canonical_root),
            "scope_rel_root": rel_root_str,
            "scope_out_of_scope": out_of_scope,
            "scope_status": "ok" if out_of_scope == 0 else "fail",
        })
        cursor.execute(
            "UPDATE link_plans SET metadata = ? WHERE id = ?",
            (json.dumps(metadata), plan_id),
        )
        conn.commit()

    conn.close()
    return 0 if out_of_scope == 0 else 2

@link.command("plan-payload-empty")
@click.argument("name")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--device", required=True, help="Device alias or device_id to plan for.")
@click.option("--dry-run", is_flag=True, help="Generate plan without saving to database.")
@click.option(
    "--require-existing-hardlinks/--no-require-existing-hardlinks",
    default=True,
    help="Require existing hardlink evidence across payload roots (default: enabled)."
)
def link_plan_payload_empty_cmd(name, db, device, dry_run, require_existing_hardlinks):
    """
    Create a deduplication plan for zero-length files within payload groups.
    """
    import json
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_planner import create_payload_empty_plan, save_plan, format_plan_summary

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    # Resolve device (try alias first, then device_id if numeric)
    cursor.execute(
        "SELECT device_id FROM devices WHERE device_alias = ?",
        (device,)
    )
    result_row = cursor.fetchone()

    if not result_row and device.isdigit():
        cursor.execute(
            "SELECT device_id FROM devices WHERE device_id = ?",
            (int(device),)
        )
        result_row = cursor.fetchone()

    if not result_row:
        click.echo(f"❌ Device not found: {device}", err=True)
        click.echo(f"💡 Tip: Use 'hashall devices list' to see available devices", err=True)
        conn.close()
        return 1

    device_id = result_row[0]

    try:
        click.echo(f"📋 Creating empty-file payload plan: \"{name}\"")
        click.echo(f"   Device: {device} ({device_id})")
        click.echo(f"   Require existing hardlinks: {'yes' if require_existing_hardlinks else 'no'}")
        click.echo()

        plan = create_payload_empty_plan(
            conn,
            name,
            device_id,
            require_existing_hardlinks=require_existing_hardlinks
        )

        if dry_run:
            click.echo("🔍 DRY-RUN MODE (plan not saved)")
            click.echo()
            click.echo(format_plan_summary(plan))
            conn.close()
            return 0

        plan_id = save_plan(conn, plan)
        metadata = json.dumps({
            "type": "payload_empty",
            "require_existing_hardlinks": require_existing_hardlinks
        })
        conn.execute(
            "UPDATE link_plans SET notes = ?, metadata = ? WHERE id = ?",
            ("payload_empty", metadata, plan_id),
        )
        conn.commit()

        click.echo("✅ Plan created successfully!")
        click.echo()
        click.echo(format_plan_summary(plan, plan_id=plan_id))

        conn.close()
        return 0

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        conn.close()
        return 1
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        return 1
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        return 1


@link.command("list-plans")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--status", type=click.Choice(['pending', 'in_progress', 'completed', 'failed', 'cancelled']), help="Filter by status.")
def link_list_plans_cmd(db, status):
    """
    List all deduplication plans.

    Shows all plans sorted by creation date (newest first).
    Optionally filter by status.

    Examples:
        hashall link list-plans
        hashall link list-plans --status pending
        hashall link list-plans --status completed
    """
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_query import list_plans

    conn = connect_db(Path(db))

    try:
        plans = list_plans(conn, status=status)

        if not plans:
            if status:
                click.echo(f"No plans found with status: {status}")
            else:
                click.echo("No plans found")
            click.echo("💡 Create a plan with: hashall link plan <name> --device <device>")
            conn.close()
            return 0

        # Header
        if status:
            click.echo(f"📋 Plans (status: {status}):\n")
        else:
            click.echo(f"📋 All Plans ({len(plans)} total):\n")

        # Display each plan
        for plan in plans:
            device_name = plan.device_alias or f"Device {plan.device_id}"
            savings_mb = plan.total_bytes_saveable / (1024**2)

            status_emoji = {
                'pending': '⏳',
                'in_progress': '⚡',
                'completed': '✅',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(plan.status, '❓')

            click.echo(f"  {status_emoji} Plan #{plan.id}: {plan.name}")
            click.echo(f"     Device: {device_name} | Actions: {plan.actions_total:,} | Savings: {savings_mb:.1f} MB")
            click.echo(f"     Created: {plan.created_at} | Status: {plan.status}")

            if plan.is_in_progress:
                click.echo(f"     Progress: {plan.progress_percentage:.1f}% ({plan.actions_executed}/{plan.actions_total} executed)")

            click.echo()

        click.echo(f"💡 View details: hashall link show-plan <plan_id>")

        conn.close()
        return 0

    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        return 1


@link.command("show-plan")
@click.argument("plan_id", type=int)
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--limit", type=int, default=10, help="Number of actions to show (0 for all).")
@click.option("--format", type=click.Choice(['text', 'json']), default='text', help="Output format.")
def link_show_plan_cmd(plan_id, db, limit, format):
    """
    Display details of a deduplication plan.

    Shows plan metadata, execution progress, and top actions sorted by space savings.
    Use --limit 0 to show all actions.

    Examples:
        hashall link show-plan 1
        hashall link show-plan 1 --limit 20
        hashall link show-plan 1 --limit 0  # Show all actions
        hashall link show-plan 1 --format json
    """
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_query import get_plan, get_plan_actions, format_plan_details, format_plan_details_json

    conn = connect_db(Path(db))

    try:
        # Get plan
        plan = get_plan(conn, plan_id)

        if not plan:
            click.echo(f"❌ Plan not found: {plan_id}", err=True)
            click.echo(f"💡 Tip: Use 'hashall link list-plans' to see available plans", err=True)
            conn.close()
            return 1

        # Get actions
        actions = get_plan_actions(conn, plan_id, limit=0)  # Get all, we'll limit in formatting

        # Format output
        if format == 'json':
            click.echo(format_plan_details_json(plan, actions, limit=limit))
        else:
            click.echo(format_plan_details(plan, actions, limit=limit))

        conn.close()
        return 0

    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        return 1


@link.command("execute")
@click.argument("plan_id", type=int)
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--dry-run", is_flag=True, help="Simulate execution without making changes.")
@click.option("--verify", type=click.Choice(['fast', 'paranoid', 'none']), default='fast',
              help="Verification mode: fast=size/mtime+sampling (default), paranoid=full hash (slow), none=skip")
@click.option("--no-backup", is_flag=True, help="Skip creating .bak backup files (faster but less safe).")
@click.option("--limit", type=int, default=0, help="Maximum number of actions to execute (0 for all).")
@click.option("--jdupes/--no-jdupes", default=True,
              help="Use jdupes for byte-for-byte verification + hardlinking (recommended).")
@click.option("--jdupes-log-dir", type=click.Path(), default=str(DEFAULT_JDUPES_LOG_DIR),
              help="Write per-group jdupes logs to this directory.")
@click.option("--snapshot/--no-snapshot", default=True,
              help="Use a ZFS snapshot for rollback when available (recommended).")
@click.option("--snapshot-prefix", default="hashall-link",
              help="Prefix for ZFS snapshot names.")
@click.option("--low-priority/--normal-priority", default=False,
              help="Lower CPU/IO priority for this run (nice + ionice).")
@click.option("--fix-perms/--no-fix-perms", default=True,
              help="Fix ownership/group/perms on targets before linking (recommended).")
@click.option("--fix-acl/--no-fix-acl", default=False,
              help="Set default ACL on dirs when fixing perms (optional).")
@click.option("--fix-perms-log", type=click.Path(), default=None,
              help="Write JSON log of permission fixes (default: ~/.logs/hashall/perms/plan-<id>-<ts>.json).")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def link_execute_cmd(plan_id, db, dry_run, verify, no_backup, limit, jdupes, jdupes_log_dir,
                     snapshot, snapshot_prefix, low_priority, fix_perms, fix_acl, fix_perms_log, yes):
    """
    Execute a deduplication plan.

    Replaces duplicate files with hardlinks to save space. This operation
    modifies the filesystem, so use --dry-run first to preview.

    SAFETY FEATURES:
    - jdupes byte-for-byte verification + linking (when enabled)
    - Fast verification: size/mtime + hash sampling (default, recommended)
    - Paranoid verification: full file hash (--verify paranoid, slow)
    - Backup file creation (use --no-backup to skip)
    - Atomic operations with rollback on error
    - Progress tracking in database

    VERIFICATION MODES:
    - fast: Size/mtime checks + first/middle/last 1MB hash sampling
            (3MB read for 100GB file = 33,000x faster than full hash)
    - paranoid: Full SHA256 hash of entire files (slow for large files)
    - none: Skip verification, trust planning phase (fastest)

    Examples:
        # Dry-run first (safe, no changes)
        hashall link execute 1 --dry-run

        # Execute with fast verification (default, recommended)
        hashall link execute 1

        # Execute limited batch (test on 10 files first)
        hashall link execute 1 --limit 10

        # Low priority (nice + ionice)
        hashall link execute 1 --low-priority

        # Paranoid mode (full hash, slow but 100% certain)
        hashall link execute 1 --verify paranoid

        # Maximum speed (no verification, no backups)
        hashall link execute 1 --verify none --no-backup --yes
    """
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.link_query import get_plan
    from hashall.link_executor import execute_plan
    from hashall.link_query import get_plan_actions
    from hashall.permfix import fix_permissions, resolve_plan_paths_for_permfix
    from hashall.fs_utils import get_zfs_metadata, get_mount_source
    import subprocess
    import datetime as dt

    conn = connect_db(Path(db))

    try:
        # Get plan
        plan = get_plan(conn, plan_id)

        if not plan:
            click.echo(f"❌ Plan not found: {plan_id}", err=True)
            click.echo(f"💡 Tip: Use 'hashall link list-plans' to see available plans", err=True)
            conn.close()
            return 1

        if plan.status == 'completed':
            click.echo(f"✅ Plan #{plan_id} is already completed", err=True)
            click.echo(f"💡 View results: hashall link show-plan {plan_id}", err=True)
            conn.close()
            return 0

        # Show plan summary
        device_name = plan.device_alias or f"Device {plan.device_id}"
        savings_mb = plan.total_bytes_saveable / (1024**2)

        click.echo(f"🔗 Executing Plan #{plan_id}: {plan.name}")
        click.echo(f"   Device: {device_name} ({plan.device_id})")
        click.echo(f"   Actions: {plan.actions_total:,} hardlinks")
        click.echo(f"   Potential savings: {savings_mb:.2f} MB")
        click.echo()

        # Snapshot discovery (read-only)
        snapshot_dataset = None
        snapshot_existing = None
        if snapshot and plan.mount_point:
            meta = get_zfs_metadata(plan.mount_point)
            snapshot_dataset = meta.get("dataset_name") if meta else None
            if not snapshot_dataset:
                source = get_mount_source(plan.mount_point)
                if source and not source.startswith("/"):
                    snapshot_dataset = source
            if snapshot_dataset:
                try:
                    result = subprocess.run(
                        ["zfs", "list", "-H", "-o", "name", "-t", "snapshot", "-r", snapshot_dataset],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=10,
                    )
                    snaps = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                    matches = [
                        s for s in snaps
                        if s.startswith(f"{snapshot_dataset}@{snapshot_prefix}")
                        and s.split("@")[0] == snapshot_dataset
                    ]
                    if matches:
                        snapshot_existing = matches[-1]
                except Exception:
                    snapshot_existing = None

        if dry_run:
            click.echo("🔍 DRY-RUN MODE (no changes will be made)")
            if snapshot and snapshot_dataset:
                snap_label = snapshot_existing or f"{snapshot_dataset}@{snapshot_prefix}-<timestamp>"
                click.echo(f"🔎 ZFS snapshot (planned): {snap_label}")
            elif snapshot:
                click.echo("⚠️  ZFS snapshot not available")
            click.echo()
        else:
            # Safety confirmation
            if not yes:
                click.echo("⚠️  WARNING: This will modify files on disk!")
                click.echo()
                click.echo("Safety features enabled:")

                verify_desc = {
                    'fast': '✅ Fast verification (size/mtime + hash sampling)',
                    'paranoid': '✅ Paranoid verification (full file hash - SLOW)',
                    'none': '❌ No verification (trust planning phase)'
                }
                click.echo(f"   {'✅' if jdupes else '❌'} jdupes byte-for-byte verification + linking")
                click.echo(f"   {verify_desc.get(verify, verify)}")
                if snapshot and snapshot_dataset:
                    snap_label = snapshot_existing or f"{snapshot_dataset}@{snapshot_prefix}-<timestamp>"
                    click.echo(f"   ✅ ZFS snapshot (dataset: {snapshot_dataset})")
                    click.echo(f"      {snap_label}")
                else:
                    if snapshot:
                        click.echo("   ⚠️  ZFS snapshot (not available)")
                    else:
                        click.echo("   ❌ ZFS snapshot (disabled)")
                click.echo(f"   {'✅' if not no_backup else '❌'} Backup file creation (.bak)")
                click.echo(f"   ✅ Atomic operations with rollback")
                click.echo()

                if limit > 0:
                    click.echo(f"Limiting to first {limit} actions")
                    click.echo()

                if not click.confirm("Do you want to continue?"):
                    click.echo("Aborted.")
                    conn.close()
                    return 0

        if low_priority:
            _apply_low_priority()

        if fix_perms:
            # Build list of pending action paths (respect limit)
            order_clause = "bytes_to_save DESC"
            query = f"""
                SELECT canonical_path, duplicate_path
                FROM link_actions
                WHERE plan_id = ? AND status = 'pending'
                ORDER BY {order_clause}
            """
            params: list[object] = [plan_id]
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            mount_point = Path(plan.mount_point) if plan.mount_point else None
            path_set = resolve_plan_paths_for_permfix(rows, mount_point)

            if plan.mount_point:
                root_path = Path(plan.mount_point)
            elif path_set:
                root_path = next(iter(path_set)).parent
            else:
                root_path = Path("/")
            root_gid = os.stat(root_path).st_gid
            root_group = grp.getgrgid(root_gid).gr_name if root_gid is not None else str(root_gid)
            root_uid = os.getuid()

            if fix_perms_log:
                log_path = Path(fix_perms_log).expanduser()
            else:
                log_path = DEFAULT_PERMS_LOG_DIR / f"plan-{plan_id}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

            apply_perms = not dry_run
            click.echo(f"🧰 Perm fix ({'apply' if apply_perms else 'check-only'}): group={root_group} ({root_gid})")
            summary, written = fix_permissions(
                sorted(path_set, key=lambda p: str(p)),
                root_gid,
                root_uid,
                apply=apply_perms,
                fix_owner_root=True,
                fix_acl=fix_acl,
                use_sudo=apply_perms,
                log_path=log_path,
                root_label=str(root_path),
            )
            if apply_perms:
                click.echo(f"   Checked: {summary.checked:,} Changed: {summary.changed:,} Failed: {summary.failed:,}")
            else:
                click.echo(f"   Checked: {summary.checked:,} Would change: {summary.changed:,} Failed: {summary.failed:,}")
            if written:
                click.echo(f"   Log: {written}")
            if summary.failed:
                click.echo("⚠️  Some permission fixes failed; linking may still fail.")

        # Progress callback
        def progress_callback(action_num, total_actions, action, status=None, error=None):
            pct = (action_num / total_actions) * 100
            size_mb = (action.file_size or 0) / (1024**2)
            sha = (action.sha256 or "")[:12]
            status_label = (status or "processing").upper()
            if dry_run or status:
                msg = (
                    f"   [{action_num}/{total_actions}] ({pct:.0f}%) {status_label} "
                    f"{size_mb:.2f} MB sha={sha} "
                    f"keep={action.canonical_path} "
                    f"replace={action.duplicate_path}"
                )
                if error:
                    if status_label == "SKIPPED":
                        msg += f" reason={error}"
                    else:
                        msg += f" err={error}"
                click.echo(msg)
            else:
                click.echo(f"   [{action_num}/{total_actions}] ({pct:.0f}%) Processing: {Path(action.duplicate_path).name[:50]}")

        # Execute plan
        click.echo("⚡ Executing plan...")
        click.echo()

        # Snapshot (only when executing)
        snapshot_used = None
        create_backup = not no_backup
        if snapshot and not dry_run and snapshot_dataset:
            if snapshot_existing:
                snapshot_used = snapshot_existing
            else:
                snap_name = f"{snapshot_prefix}-plan{plan_id}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
                snapshot_used = f"{snapshot_dataset}@{snap_name}"
                try:
                    subprocess.run(
                        ["zfs", "snapshot", snapshot_used],
                        check=True,
                        timeout=15,
                    )
                except Exception as e:
                    snapshot_used = None
                    click.echo(f"⚠️  Snapshot failed: {e}. Falling back to .bak backups.")

            if snapshot_used:
                click.echo(f"✅ Snapshot ready: {snapshot_used}")
                if not no_backup:
                    create_backup = False
                    click.echo("ℹ️  Snapshot active; skipping per-file .bak backups")

        result = execute_plan(
            conn,
            plan_id,
            dry_run=dry_run,
            verify_mode=verify,
            create_backup=create_backup,
            limit=limit,
            progress_callback=progress_callback,
            use_jdupes=jdupes,
            jdupes_log_dir=Path(jdupes_log_dir).expanduser() if jdupes_log_dir else None,
            low_priority=low_priority
        )

        # Show results
        click.echo()
        click.echo("=" * 60)

        if dry_run:
            click.echo("🔍 DRY-RUN RESULTS:")
        else:
            click.echo("✅ EXECUTION COMPLETE:")

        click.echo(f"   Actions executed: {result.actions_executed:,}")
        click.echo(f"   Actions failed: {result.actions_failed:,}")
        click.echo(f"   Actions skipped: {result.actions_skipped:,}")

        saved_mb = result.bytes_saved / (1024**2)
        saved_gb = result.bytes_saved / (1024**3)
        if saved_gb >= 1.0:
            click.echo(f"   Space saved: {saved_gb:.2f} GB")
        else:
            click.echo(f"   Space saved: {saved_mb:.2f} MB")

        if result.errors:
            click.echo()
            click.echo(f"❌ Errors ({len(result.errors)}):")
            for error in result.errors[:10]:  # Show first 10 errors
                click.echo(f"   {error}")
            if len(result.errors) > 10:
                click.echo(f"   ... and {len(result.errors) - 10} more errors")

        if jdupes and jdupes_log_dir:
            click.echo()
            click.echo(f"🧾 jdupes logs: {Path(jdupes_log_dir).expanduser()}/plan-{plan_id}_sha256-*.log")

        if result.actions_failed > 0:
            failed_actions = [
                action for action in get_plan_actions(conn, plan_id, limit=0)
                if str(action.status or "") == "failed"
            ]
            if failed_actions:
                click.echo()
                click.echo(f"🧪 Failed actions ({min(5, len(failed_actions))} shown):")
                for action in failed_actions[:5]:
                    click.echo(
                        f"   action={action.id} keep={action.canonical_path} "
                        f"replace={action.duplicate_path}"
                    )
                    if action.error_message:
                        click.echo(f"      error={action.error_message}")

        click.echo("=" * 60)
        click.echo()

        if dry_run:
            click.echo(f"💡 Looks good? Execute with: hashall link execute {plan_id}")
        elif result.actions_failed == 0:
            click.echo(f"✅ Plan completed successfully!")
            click.echo(f"💡 View results: hashall link show-plan {plan_id}")
        else:
            click.echo(f"⚠️  Plan completed with {result.actions_failed} errors")
            click.echo(f"💡 Review errors: hashall link show-plan {plan_id}")

        conn.close()
        if result.actions_failed == 0:
            return 0
        raise click.exceptions.Exit(1)

    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
        conn.close()
        raise click.exceptions.Exit(1)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        import traceback
        traceback.print_exc()
        conn.close()
        raise click.exceptions.Exit(1)


# Devices command group
@cli.group()
def devices():
    """Device registry and filesystem management commands."""
    pass


@devices.command("list")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def devices_list(db):
    """
    List all registered devices and their statistics.

    Shows device alias, UUID, device ID, mount point, filesystem type,
    file count, and total size for all registered devices.
    """
    from hashall.model import connect_db

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    # Query all devices, sorted by device_alias (or device_id if no alias)
    cursor.execute("""
        SELECT
            device_alias,
            fs_uuid,
            device_id,
            mount_point,
            preferred_mount_point,
            fs_type,
            total_files,
            total_bytes
        FROM devices
        ORDER BY
            CASE WHEN device_alias IS NULL THEN 1 ELSE 0 END,
            device_alias,
            device_id
    """)

    devices = cursor.fetchall()

    if not devices:
        click.echo("No devices registered")
        return

    # Helper function to format bytes as human-readable size
    def format_size(bytes_val):
        """Format bytes as human-readable size (TB, GB, MB)."""
        if bytes_val is None:
            return "0 B"

        tb = bytes_val / (1024 ** 4)
        if tb >= 1.0:
            return f"{tb:.1f} TB"

        gb = bytes_val / (1024 ** 3)
        if gb >= 1.0:
            return f"{gb:.1f} GB"

        mb = bytes_val / (1024 ** 2)
        if mb >= 1.0:
            return f"{mb:.1f} MB"

        kb = bytes_val / 1024
        if kb >= 1.0:
            return f"{kb:.1f} KB"

        return f"{bytes_val} B"

    # Helper function to format file count with commas
    def format_count(count):
        """Format count with thousand separators."""
        if count is None:
            return "0"
        return f"{count:,}"

    # Format data for table
    rows = []
    for device in devices:
        alias = device[0] or "(none)"
        uuid_short = device[1][:8] if device[1] else "(none)"
        device_id = str(device[2])
        preferred_mount = device[4] or device[3] or "(none)"
        fs_type = device[5] or "(none)"
        files = format_count(device[6])
        size = format_size(device[7])

        rows.append([alias, uuid_short, device_id, preferred_mount, fs_type, files, size])

    # Calculate column widths
    headers = ["Alias", "UUID (first 8)", "Device ID", "Preferred Mount", "Type", "Files", "Size"]
    col_widths = [len(h) for h in headers]

    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # Print header
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)

    # Print rows
    for row in rows:
        row_line = "  ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
        click.echo(row_line)


@devices.command("repair-indexes")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--quiet", is_flag=True, help="Reduce per-index repair output.")
def devices_repair_indexes(db, quiet):
    """
    Repair files_* index ownership and naming drift after device-id table renames.
    """
    from hashall.model import connect_db
    from hashall.device import repair_all_files_table_indexes

    conn = connect_db(Path(db))
    cursor = conn.cursor()
    summary = repair_all_files_table_indexes(cursor, verbose=not quiet)
    conn.commit()
    conn.close()

    click.echo(
        "index_repair "
        f"tables={summary['tables']} "
        f"dropped_stale={summary['dropped_stale']} "
        f"dropped_conflicts={summary['dropped_conflicts']} "
        f"recreated={summary['recreated']}"
    )


@devices.command("migrate-files-tables")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--apply", is_flag=True, help="Execute changes. Default is dry-run.")
@click.option(
    "--device",
    "device_filters",
    multiple=True,
    help="Limit to a device alias, device_id, or fs_uuid. Repeatable.",
)
@click.option("--limit", type=int, default=0, show_default=True, help="Maximum devices to process after filtering (0 = all).")
@click.option("--report-json", type=click.Path(), help="Write JSON report to this path.")
@click.option("--snapshot-db", type=click.Path(), help="Write a DB snapshot here before apply.")
def devices_migrate_files_tables(db, apply, device_filters, limit, report_json, snapshot_db):
    """Plan or apply fs_uuid-backed files-table bindings with compatibility views."""
    import sqlite3
    from collections import Counter
    from datetime import datetime

    from hashall.model import connect_db
    from hashall.device import ensure_files_table, files_table_name_for_fs_uuid, resolve_device_id
    from hashall.fs_utils import filesystem_uuid_is_stable

    conn = connect_db(Path(db))
    cursor = conn.cursor()
    rows = list(cursor.execute(
        """
        SELECT device_id, device_alias, fs_uuid, files_table
        FROM devices
        WHERE fs_uuid IS NOT NULL AND trim(fs_uuid) <> ''
        ORDER BY device_alias, fs_uuid
        """
    ).fetchall())

    def _relation_type(name: str | None) -> str | None:
        if not name:
            return None
        row = cursor.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            (str(name),),
        ).fetchone()
        return str(row[0]) if row else None

    if device_filters:
        wanted_ids: set[int] = set()
        for raw in device_filters:
            try:
                wanted_ids.add(resolve_device_id(conn, raw))
                continue
            except ValueError:
                row = cursor.execute(
                    "SELECT device_id FROM devices WHERE fs_uuid = ?",
                    (str(raw),),
                ).fetchone()
                if row is None:
                    conn.close()
                    raise click.ClickException(
                        f"No device found for filter {raw!r} (expected alias, device_id, or fs_uuid)"
                    )
                wanted_ids.add(int(row[0]))
        rows = [row for row in rows if int(row[0]) in wanted_ids]

    if limit > 0:
        rows = rows[:limit]

    report = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "apply" if apply else "dry-run",
        "db": str(Path(db)),
        "device_filters": list(device_filters or ()),
        "limit": int(limit),
        "devices": [],
    }

    for row in rows:
        device_id = int(row[0])
        device_alias = str(row[1] or "")
        fs_uuid = str(row[2] or "").strip()
        current_binding = str(row[3] or "").strip() or None
        target_table = files_table_name_for_fs_uuid(fs_uuid)
        legacy_name = f"files_{device_id}"
        target_relation = _relation_type(target_table)
        legacy_relation = _relation_type(legacy_name)

        if not filesystem_uuid_is_stable(fs_uuid):
            action = "blocked_unstable_fs_uuid"
        elif current_binding == target_table and target_relation == "table" and legacy_relation in {"table", "view"}:
            action = "noop_already_bound"
        elif target_relation == "table" and not current_binding:
            action = "backfill_binding_only"
        elif legacy_relation == "table" and target_relation != "table":
            action = "rename_legacy_table"
        elif target_relation != "table" and legacy_relation is None:
            action = "create_target_table"
        elif target_relation == "table" and legacy_relation is None:
            action = "create_compat_view"
        else:
            action = "reconcile_binding"

        report["devices"].append(
            {
                "device_id": device_id,
                "device_alias": device_alias,
                "fs_uuid": fs_uuid,
                "current_binding": current_binding,
                "target_table": target_table,
                "target_relation": target_relation,
                "legacy_relation": legacy_relation,
                "planned_action": action,
            }
        )

    snapshot_path = None
    if apply:
        blocked = [item for item in report["devices"] if item["planned_action"] == "blocked_unstable_fs_uuid"]
        if blocked:
            conn.close()
            blocked_csv = ",".join(str(item["device_id"]) for item in blocked)
            raise click.ClickException(
                "refusing apply for devices with volatile dev-* fs_uuid fallback: "
                f"{blocked_csv}"
            )
        snapshot_path = Path(snapshot_db) if snapshot_db else (
            Path(db).with_name(
                f"{Path(db).stem}-pre-files-table-migrate-{datetime.now().strftime('%Y%m%d-%H%M%S')}{Path(db).suffix}"
            )
        )
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        backup_conn = sqlite3.connect(str(snapshot_path))
        conn.backup(backup_conn)
        backup_conn.close()
        click.echo(f"snapshot_db={snapshot_path}")
        report["snapshot_db"] = str(snapshot_path)

        for item in report["devices"]:
            table_name = ensure_files_table(cursor, item["device_id"], fs_uuid=item["fs_uuid"])
            conn.commit()
            item["applied_table"] = table_name
            item["post_binding"] = cursor.execute(
                "SELECT files_table FROM devices WHERE device_id = ?",
                (item["device_id"],),
            ).fetchone()[0]
            item["post_target_relation"] = _relation_type(table_name)
            item["post_legacy_relation"] = _relation_type(f"files_{item['device_id']}")

    counter = Counter(item["planned_action"] for item in report["devices"])
    report["summary"] = {
        "devices": len(report["devices"]),
        "actions": dict(counter),
    }

    click.echo(
        f"mode={report['mode']} devices={report['summary']['devices']} "
        f"actions={json.dumps(report['summary']['actions'], sort_keys=True)}"
    )
    for item in report["devices"]:
        click.echo(
            f"device_id={item['device_id']} alias={item['device_alias'] or '-'} "
            f"fs_uuid={item['fs_uuid']} target={item['target_table']} "
            f"planned={item['planned_action']}"
        )

    if report_json:
        out_path = Path(report_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        click.echo(f"report_json={out_path}")

    conn.close()


@devices.command('alias')
@click.argument('current_name')
@click.argument('new_alias')
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def alias_device(current_name, new_alias, db):
    """
    Update device alias.

    CURRENT_NAME can be either a device alias or a device_id.
    NEW_ALIAS is the new alias to assign to the device.

    Examples:
        hashall devices alias pool main_pool
        hashall devices alias 49 main_pool
    """
    from hashall.model import connect_db

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    # Step 1: Find device by current_name (try alias first, then device_id)
    device = None

    # Try to find by alias first
    cursor.execute("""
        SELECT fs_uuid, device_id, device_alias, mount_point
        FROM devices WHERE device_alias = ?
    """, (current_name,))
    device = cursor.fetchone()

    # If not found, try as device_id (if it's numeric)
    if not device and current_name.isdigit():
        cursor.execute("""
            SELECT fs_uuid, device_id, device_alias, mount_point
            FROM devices WHERE device_id = ?
        """, (int(current_name),))
        device = cursor.fetchone()

    if not device:
        click.echo(f"Device '{current_name}' not found")
        conn.close()
        return

    fs_uuid, device_id, old_alias, mount_point = device

    # Step 2: Check if new_alias is already taken
    cursor.execute("""
        SELECT device_id, device_alias
        FROM devices WHERE device_alias = ?
    """, (new_alias,))
    existing = cursor.fetchone()

    if existing:
        existing_device_id, existing_alias = existing
        click.echo(f"Alias '{new_alias}' already taken by device {existing_device_id}")
        conn.close()
        return

    # Step 3: Update device_alias
    cursor.execute("""
        UPDATE devices SET device_alias = ?, updated_at = datetime('now')
        WHERE fs_uuid = ?
    """, (new_alias, fs_uuid))
    conn.commit()

    # Step 4: Print confirmation
    old_display = old_alias if old_alias else str(device_id)
    click.echo(f"Updated alias: {old_display} -> {new_alias}")

    conn.close()


@devices.command("show")
@click.argument("device")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def devices_show(device, db):
    """
    Display detailed information for a device.

    DEVICE can be either a device alias (e.g., "pool") or a device_id (e.g., "49").

    Examples:
        hashall devices show pool
        hashall devices show 49
    """
    from hashall.model import connect_db
    import json
    import datetime

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    # Try to find device by alias first, then by device_id
    device_row = None

    # Try lookup by alias
    cursor.execute("""
        SELECT fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, fs_type,
               zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
               first_scanned_at, last_scanned_at, scan_count,
               total_files, total_bytes, device_id_history
        FROM devices WHERE device_alias = ?
    """, (device,))
    device_row = cursor.fetchone()

    # If not found, try lookup by device_id
    if not device_row:
        try:
            device_id_int = int(device)
            cursor.execute("""
                SELECT fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, fs_type,
                       zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
                       first_scanned_at, last_scanned_at, scan_count,
                       total_files, total_bytes, device_id_history
                FROM devices WHERE device_id = ?
            """, (device_id_int,))
            device_row = cursor.fetchone()
        except ValueError:
            pass  # Not a valid integer, skip device_id lookup

    if not device_row:
        print(f"❌ Device not found: {device}")
        conn.close()
        return

    # Unpack device data
    (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, fs_type,
     zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
     first_scanned_at, last_scanned_at, scan_count,
     total_files, total_bytes, device_id_history_json) = device_row

    # Get deleted files count
    table_name = get_files_table_name(cursor, device_id=device_id)
    if not table_name:
        table_name = f"files_{device_id}"
    table_ident = _quote_sql_identifier(table_name)
    deleted_count = 0
    try:
        cursor.execute(f"""
            SELECT COUNT(*) FROM {table_ident} WHERE status = 'deleted'
        """)
        result = cursor.fetchone()
        if result:
            deleted_count = result[0]
    except Exception:
        # Table might not exist yet or other error
        pass

    # Display device information
    display_name = device_alias if device_alias else f"Device {device_id}"
    print(f"Device: {display_name}")
    print(f"  Filesystem UUID: {fs_uuid}")
    print(f"  Current Device ID: {device_id}")
    preferred_mount = preferred_mount_point or mount_point
    print(f"  Preferred Mount: {preferred_mount}")
    if mount_point and mount_point != preferred_mount:
        print(f"  Mount (recorded): {mount_point}")
    from hashall.fs_utils import get_mount_point
    detected_mount = get_mount_point(mount_point or preferred_mount)
    if detected_mount and detected_mount != preferred_mount:
        print(f"  Mount (detected): {detected_mount}")
    print(f"  Filesystem Type: {fs_type or 'unknown'}")

    # ZFS metadata section (only if ZFS)
    if zfs_pool_name:
        print()
        print("  ZFS Metadata:")
        print(f"    Pool Name: {zfs_pool_name}")
        if zfs_dataset_name:
            print(f"    Dataset Name: {zfs_dataset_name}")
        if zfs_pool_guid:
            print(f"    Pool GUID: {zfs_pool_guid}")

    # Statistics section
    print()
    print("  Statistics:")
    active_files = total_files or 0
    print(f"    Total Files: {active_files:,} active, {deleted_count:,} deleted")

    if total_bytes:
        # Format bytes in human-readable format
        if total_bytes >= 1_000_000_000_000:  # TB
            size_str = f"{total_bytes / 1_000_000_000_000:.1f} TB"
        elif total_bytes >= 1_000_000_000:  # GB
            size_str = f"{total_bytes / 1_000_000_000:.1f} GB"
        elif total_bytes >= 1_000_000:  # MB
            size_str = f"{total_bytes / 1_000_000:.1f} MB"
        else:
            size_str = f"{total_bytes:,} bytes"
        print(f"    Total Size: {size_str}")

    if first_scanned_at:
        print(f"    First Scanned: {first_scanned_at}")
    if last_scanned_at:
        print(f"    Last Scanned: {last_scanned_at}")
    if scan_count:
        print(f"    Scan Count: {scan_count}")

    # Device ID history section
    if device_id_history_json:
        try:
            history = json.loads(device_id_history_json)
            if history:
                print()
                print("  Device ID History:")
                for entry in history:
                    device_id_old = entry.get('device_id')
                    changed_at = entry.get('changed_at', 'unknown')
                    # Try to parse and format the timestamp
                    try:
                        dt = datetime.datetime.fromisoformat(changed_at)
                        changed_at_str = dt.strftime('%Y-%m-%d')
                    except (ValueError, AttributeError):
                        changed_at_str = changed_at
                    print(f"    {changed_at_str}: device_id {device_id_old} (initial)")
                # Show current device_id as the latest entry
                if last_scanned_at:
                    try:
                        # Handle SQLite datetime format
                        last_scanned_at_clean = last_scanned_at.replace(' ', 'T') if ' ' in last_scanned_at else last_scanned_at
                        dt = datetime.datetime.fromisoformat(last_scanned_at_clean)
                        current_date = dt.strftime('%Y-%m-%d')
                    except (ValueError, AttributeError):
                        current_date = last_scanned_at.split()[0] if ' ' in last_scanned_at else last_scanned_at
                    print(f"    {current_date}: device_id {device_id} (changed after reboot)")
        except json.JSONDecodeError:
            pass  # Invalid JSON, skip history section

    conn.close()


@devices.command("preferred-mount")
@click.argument("device")
@click.argument("mount_point", required=False)
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
def devices_preferred_mount(device, mount_point, db):
    """
    Show or set the preferred mount point for a device.

    DEVICE can be either a device alias (e.g., "pool") or a device_id (e.g., "49").
    If MOUNT_POINT is provided, updates preferred mount point.

    Examples:
        hashall devices preferred-mount pool
        hashall devices preferred-mount 49 /mnt/pool
    """
    from hashall.model import connect_db

    conn = connect_db(Path(db))
    cursor = conn.cursor()

    device_columns = {row[1] for row in cursor.execute("PRAGMA table_info(devices)").fetchall()}
    if "preferred_mount_point" not in device_columns:
        click.echo("❌ preferred_mount_point not supported in this database")
        conn.close()
        return

    device_row = cursor.execute(
        """
        SELECT fs_uuid, device_id, device_alias, mount_point, preferred_mount_point
        FROM devices WHERE device_alias = ?
        """,
        (device,),
    ).fetchone()

    if not device_row and device.isdigit():
        device_row = cursor.execute(
            """
            SELECT fs_uuid, device_id, device_alias, mount_point, preferred_mount_point
            FROM devices WHERE device_id = ?
            """,
            (int(device),),
        ).fetchone()

    if not device_row:
        click.echo(f"❌ Device not found: {device}")
        conn.close()
        return

    fs_uuid, device_id, device_alias, current_mount, preferred_mount = device_row
    display_name = device_alias or f"Device {device_id}"
    effective_preferred = preferred_mount or current_mount

    if mount_point is None:
        click.echo(f"Device: {display_name}")
        click.echo(f"  Mount Point: {current_mount}")
        click.echo(f"  Preferred Mount Point: {effective_preferred}")
        conn.close()
        return

    if not Path(mount_point).is_absolute():
        click.echo("❌ Preferred mount point must be an absolute path")
        conn.close()
        return

    if mount_point == effective_preferred:
        click.echo(f"Preferred mount point already set to {effective_preferred}")
        conn.close()
        return

    cursor.execute(
        """
        UPDATE devices
        SET preferred_mount_point = ?, updated_at = datetime('now')
        WHERE fs_uuid = ?
        """,
        (mount_point, fs_uuid),
    )
    conn.commit()

    click.echo(f"Updated preferred mount point: {display_name} -> {mount_point}")
    conn.close()


# Canonical CLI surface:
# - `hashall rehome ...` exposes the full rehome command tree
# - `hashall refresh` is a direct top-level alias for the rehome refresh flow
# - `hashall refresh-dashboard` exposes the refresh task status view directly
from rehome.cli import (
    cli as rehome_cli,
    refresh_cmd as rehome_refresh_cmd,
    refresh_dashboard_cmd as rehome_refresh_dashboard_cmd,
    refresh_status_cmd as rehome_refresh_status_cmd,
)

cli.add_command(rehome_cli, name="rehome")
cli.add_command(rehome_refresh_cmd, name="refresh")
cli.add_command(rehome_refresh_dashboard_cmd, name="refresh-dashboard")
cli.add_command(rehome_refresh_status_cmd, name="refresh-status")


if __name__ == "__main__":
    cli()
