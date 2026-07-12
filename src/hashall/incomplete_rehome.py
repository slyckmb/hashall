"""Read-only planning helpers for incomplete payload rehome repairs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import time
from typing import Any, Iterable


MEDIA_ALIAS_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/data/media", "/stash/media"),
    ("/stash/media", "/data/media"),
)

DEFAULT_LIBRARY_ROOTS: tuple[str, ...] = (
    "/data/media/movies",
    "/data/media/tv",
    "/data/media/music",
    "/data/media/ebooks",
    "/data/media/audiobooks",
    "/stash/media/movies",
    "/stash/media/tv",
    "/stash/media/music",
    "/stash/media/ebooks",
    "/stash/media/audiobooks",
    "/pool/media/movies",
    "/pool/media/tv",
    "/pool/media/music",
    "/pool/media/ebooks",
    "/pool/media/audiobooks",
)

CATALOG_RELATIVE_ROOTS: tuple[str, ...] = (
    "/data/media",
    "/stash/media",
    "/pool/media",
)

REPAIR_PATH_MARKERS: tuple[str, ...] = (
    "/.rehome-cleanup-stage/",
    "/_qb-repair",
    "/_qb-finish/",
    "/_qb-unique-repair/",
    "/_rehome-unique/",
    "/RecycleBin/",
)


@dataclass(frozen=True)
class SourceFile:
    path: str
    rel_path: str
    dev: int
    inode: int
    size: int


@dataclass(frozen=True)
class PathSummary:
    path: str
    exists: bool
    is_file: bool
    file_count: int
    total_bytes: int
    zero_byte_files: int
    nonzero_files: int


def alias_variants(path: str) -> set[str]:
    text = str(path or "").rstrip("/")
    if not text:
        return set()
    variants = {text}
    for old, new in MEDIA_ALIAS_PREFIXES:
        if text == old:
            variants.add(new)
        elif text.startswith(old + "/"):
            variants.add(new + text[len(old) :])
    return variants


def catalog_path_variants(path: str) -> set[str]:
    variants = set(alias_variants(path))
    for candidate in list(variants):
        for prefix in ("/data/media/", "/stash/media/", "/pool/media/"):
            if candidate.startswith(prefix):
                variants.add(candidate[len(prefix) :])
    return {item.strip("/") for item in variants if item}


def path_aliases(path: str) -> set[str]:
    """Return absolute/relative aliases for a catalog path."""
    text = str(path or "").strip().rstrip("/")
    if not text:
        return set()
    aliases = set(alias_variants(text))
    if not text.startswith("/"):
        rel = text.strip("/")
        for root in CATALOG_RELATIVE_ROOTS:
            aliases.update(alias_variants(f"{root}/{rel}"))
    return {item.rstrip("/") for item in aliases if item}


def existing_path_aliases(path: str) -> list[str]:
    return sorted(alias for alias in path_aliases(path) if Path(alias).exists())


def _preferred_delete_path(paths: Iterable[str]) -> str:
    ordered = sorted(set(str(path) for path in paths if str(path)))
    if not ordered:
        return ""
    for prefix in ("/data/media/", "/stash/media/", "/pool/media/"):
        for path in ordered:
            if path.startswith(prefix):
                return path
    return ordered[0]


def _alias_collapse_key(path: str) -> str:
    text = str(path or "").rstrip("/")
    for root in CATALOG_RELATIVE_ROOTS:
        prefix = str(root).rstrip("/") + "/"
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def cleanup_path_groups(paths: Iterable[str]) -> list[dict[str, Any]]:
    inode_groups: dict[tuple[int, int] | tuple[str, str], set[str]] = {}
    for path_text in paths:
        path = Path(path_text)
        try:
            st = path.stat(follow_symlinks=False)
            key: tuple[int, int] | tuple[str, str] = (int(st.st_dev), int(st.st_ino))
        except OSError:
            key = ("missing", str(path))
        inode_groups.setdefault(key, set()).add(str(path))

    out: list[dict[str, Any]] = []
    for key, grouped_paths in inode_groups.items():
        alias_groups: dict[str, set[str]] = {}
        for grouped_path in grouped_paths:
            alias_groups.setdefault(_alias_collapse_key(grouped_path), set()).add(grouped_path)
        delete_paths = [
            _preferred_delete_path(alias_paths)
            for _suffix, alias_paths in sorted(alias_groups.items())
        ]
        if isinstance(key[0], int):
            dev = int(key[0])
            inode = int(key[1])
        else:
            dev = 0
            inode = 0
        out.append(
            {
                "dev": dev,
                "inode": inode,
                "paths": sorted(grouped_paths),
                "delete_paths_after_verify": [path for path in delete_paths if path],
            }
        )
    return sorted(out, key=lambda item: item["delete_paths_after_verify"][0] if item["delete_paths_after_verify"] else "")


def under_any(path: str, prefixes: Iterable[str]) -> bool:
    path_variants = path_aliases(path)
    for prefix in prefixes:
        base = str(prefix or "").rstrip("/")
        if not base:
            continue
        for variant in alias_variants(base):
            for text in path_variants:
                if text == variant or text.startswith(variant + "/"):
                    return True
    return False


def is_repair_path(path: str) -> bool:
    text = "/" + str(path or "").strip("/")
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in REPAIR_PATH_MARKERS)


def iter_source_files(source_root: Path) -> list[SourceFile]:
    root = Path(source_root)
    if not root.exists():
        raise FileNotFoundError(str(root))

    files: list[Path]
    if root.is_file():
        files = [root]
    else:
        files = sorted(path for path in root.rglob("*") if path.is_file())

    out: list[SourceFile] = []
    for path in files:
        st = path.stat(follow_symlinks=False)
        rel = path.name if root.is_file() else str(path.relative_to(root))
        out.append(
            SourceFile(
                path=str(path),
                rel_path=rel,
                dev=int(st.st_dev),
                inode=int(st.st_ino),
                size=int(st.st_size),
            )
        )
    return out


def summarize_path(path: Path) -> PathSummary:
    target = Path(path)
    if not target.exists():
        return PathSummary(str(target), False, False, 0, 0, 0, 0)
    files = [target] if target.is_file() else sorted(item for item in target.rglob("*") if item.is_file())
    total_bytes = 0
    zero_byte_files = 0
    nonzero_files = 0
    for item in files:
        size = int(item.stat(follow_symlinks=False).st_size)
        total_bytes += size
        if size == 0:
            zero_byte_files += 1
        else:
            nonzero_files += 1
    return PathSummary(
        path=str(target),
        exists=True,
        is_file=target.is_file(),
        file_count=len(files),
        total_bytes=total_bytes,
        zero_byte_files=zero_byte_files,
        nonzero_files=nonzero_files,
    )


def classify_target_readiness(summary: PathSummary) -> tuple[str, list[str]]:
    if not summary.exists:
        return "missing", []
    if summary.file_count == 0:
        return "empty", []
    if summary.nonzero_files == 0:
        return "zero_placeholder_tree", []
    return "nonzero_existing_tree", ["target_contains_nonzero_files"]


def _files_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    names: list[str] = []
    for (name,) in rows:
        text = str(name or "")
        if text == "files" or text.startswith("files_"):
            names.append(text)
    return names


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(str(row[1]) == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _catalog_rows_for_inodes(
    conn: sqlite3.Connection,
    *,
    inodes: set[int],
) -> list[dict[str, Any]]:
    if not inodes:
        return []
    out: list[dict[str, Any]] = []
    for table in _files_tables(conn):
        if not (_has_column(conn, table, "path") and _has_column(conn, table, "inode")):
            continue
        has_status = _has_column(conn, table, "status")
        has_size = _has_column(conn, table, "size")
        has_device_id = _has_column(conn, table, "device_id")
        has_fs_uuid = _has_column(conn, table, "fs_uuid")
        columns = ["path", "inode"]
        columns.append("size" if has_size else "0 AS size")
        columns.append("status" if has_status else "'' AS status")
        columns.append("device_id" if has_device_id else "NULL AS device_id")
        columns.append("fs_uuid" if has_fs_uuid else "'' AS fs_uuid")
        for chunk_start in range(0, len(inodes), 500):
            chunk = sorted(inodes)[chunk_start : chunk_start + 500]
            placeholders = ",".join("?" for _ in chunk)
            status_clause = "status = 'active' AND " if has_status else ""
            rows = conn.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {status_clause}inode IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                out.append(
                    {
                        "table": table,
                        "path": str(row[0] or ""),
                        "inode": int(row[1] or 0),
                        "size": int(row[2] or 0),
                        "status": str(row[3] or ""),
                        "device_id": row[4],
                        "fs_uuid": str(row[5] or ""),
                    }
                )
    return out


def _matching_source_catalog_tables(
    conn: sqlite3.Connection,
    source_files: list[SourceFile],
) -> set[str]:
    wanted = set()
    for source in source_files[:50]:
        wanted.update(catalog_path_variants(source.path))
    if not wanted:
        return set()

    tables: set[str] = set()
    for table in _files_tables(conn):
        if not (_has_column(conn, table, "path") and _has_column(conn, table, "inode")):
            continue
        has_status = _has_column(conn, table, "status")
        status_clause = "status = 'active' AND " if has_status else ""
        for path in wanted:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE {status_clause}path = ? LIMIT 1",
                (path,),
            ).fetchone()
            if row:
                tables.add(table)
                break
    return tables


def build_source_inode_manifest(
    *,
    source_roots: Iterable[Path],
    catalog_path: Path | None = None,
    target_roots: Iterable[Path] = (),
    library_roots: Iterable[str] = DEFAULT_LIBRARY_ROOTS,
) -> dict[str, Any]:
    """Build a read-only manifest for source inode cleanup decisions."""
    sources: list[dict[str, Any]] = []
    all_source_files: list[SourceFile] = []
    for root in source_roots:
        files = iter_source_files(Path(root))
        all_source_files.extend(files)
        sources.append(
            {
                "root": str(root),
                "exists": True,
                "file_count": len(files),
                "total_bytes": sum(item.size for item in files),
                "unique_inodes": len({(item.dev, item.inode) for item in files}),
            }
        )

    source_inodes = {item.inode for item in all_source_files}
    target_prefixes = [str(Path(root)) for root in target_roots]
    library_prefixes = [str(root) for root in library_roots]

    catalog_matches: list[dict[str, Any]] = []
    catalog_tables_used: set[str] = set()
    if catalog_path:
        conn = sqlite3.connect(f"file:{Path(catalog_path).expanduser().resolve()}?mode=ro", uri=True)
        try:
            catalog_tables_used = _matching_source_catalog_tables(conn, all_source_files)
            rows = _catalog_rows_for_inodes(conn, inodes=source_inodes)
        finally:
            conn.close()
        for row in rows:
            if catalog_tables_used and row["table"] not in catalog_tables_used:
                continue
            path = row["path"]
            aliases = sorted(path_aliases(path))
            existing_aliases = existing_path_aliases(path)
            protected = under_any(path, library_prefixes)
            target = under_any(path, target_prefixes)
            repair = is_repair_path(path)
            cleanup_candidate = bool(repair and not protected and not target)
            catalog_matches.append(
                {
                    **row,
                    "path_aliases": aliases,
                    "existing_path_aliases": existing_aliases,
                    "is_library_anchor": protected,
                    "is_target_path": target,
                    "is_repair_or_staging_path": repair,
                    "cleanup_candidate_after_verify": cleanup_candidate,
                    "existing_cleanup_paths_after_verify": existing_aliases if cleanup_candidate else [],
                    "cleanup_blockers": (
                        ["library_anchor"] if protected else []
                    ) + (["target_path"] if target else []),
                }
            )

    protected_paths = [
        row["path"]
        for row in catalog_matches
        if row.get("is_library_anchor") or (not row.get("is_repair_or_staging_path"))
    ]
    cleanup_candidates = [
        row["path"] for row in catalog_matches if row.get("cleanup_candidate_after_verify")
    ]
    existing_cleanup_paths = [
        path
        for row in catalog_matches
        if row.get("cleanup_candidate_after_verify")
        for path in row.get("existing_cleanup_paths_after_verify", [])
    ]
    cleanup_groups = cleanup_path_groups(existing_cleanup_paths)
    return {
        "schema": "hashall.incomplete_rehome.source_inode_manifest.v1",
        "mode": "read_only",
        "sources": sources,
        "target_roots": [str(root) for root in target_roots],
        "library_roots": sorted(library_prefixes),
        "catalog": str(catalog_path) if catalog_path else "",
        "catalog_tables_used": sorted(catalog_tables_used),
        "summary": {
            "source_files": len(all_source_files),
            "source_unique_inodes": len({(item.dev, item.inode) for item in all_source_files}),
            "catalog_matches": len(catalog_matches),
            "protected_or_live_paths": len(set(protected_paths)),
            "cleanup_candidates_after_verify": len(set(cleanup_candidates)),
            "existing_cleanup_paths_after_verify": len(set(existing_cleanup_paths)),
            "cleanup_path_groups_after_verify": len(cleanup_groups),
        },
        "source_files": [item.__dict__ for item in all_source_files],
        "catalog_inode_refs": sorted(catalog_matches, key=lambda row: (row["path"], row["table"])),
        "cleanup_candidates_after_verify": sorted(set(cleanup_candidates)),
        "existing_cleanup_paths_after_verify": sorted(set(existing_cleanup_paths)),
        "cleanup_path_groups_after_verify": cleanup_groups,
        "delete_paths_after_verify": [
            path
            for group in cleanup_groups
            for path in group.get("delete_paths_after_verify", [])
        ],
    }


def expected_incomplete_piece_gate(
    result: Any,
    *,
    allowed_failed_pieces: Iterable[int] = (0,),
    allowed_classifications: Iterable[str] = ("sidecar_media_boundary_piece",),
    allow_missing_pieces: bool = False,
) -> dict[str, Any]:
    """Return whether a piece-verify result matches an intentional incomplete wait state."""
    def _get(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    allowed_piece_set = {int(item) for item in allowed_failed_pieces}
    allowed_class_set = {str(item) for item in allowed_classifications}
    pieces_fail = int(_get(result, "pieces_fail", 0) or 0)
    pieces_missing = int(_get(result, "pieces_missing", 0) or 0)
    failed_pieces = list(_get(result, "failed_pieces", []) or [])

    reasons: list[str] = []
    if pieces_fail <= 0 and pieces_missing <= 0:
        reasons.append("verify_is_complete")
    if pieces_missing and not allow_missing_pieces:
        reasons.append("missing_pieces_not_allowed")
    if pieces_fail + pieces_missing != len(failed_pieces):
        reasons.append("failed_piece_details_incomplete")
    for piece in failed_pieces:
        index = int(_get(piece, "piece_index", -1))
        classification = str(_get(piece, "classification", "") or "")
        status = str(_get(piece, "status", "") or "")
        if index not in allowed_piece_set:
            reasons.append(f"unexpected_piece:{index}")
        if classification not in allowed_class_set:
            reasons.append(f"unexpected_classification:{classification or 'unknown'}")
        if status == "missing" and not allow_missing_pieces:
            reasons.append(f"unexpected_missing_piece:{index}")

    return {
        "ok": not reasons,
        "reasons": sorted(set(reasons)),
        "pieces_fail": pieces_fail,
        "pieces_missing": pieces_missing,
        "failed_piece_indexes": [
            int(_get(piece, "piece_index", -1)) for piece in failed_pieces
        ],
        "failed_piece_classifications": [
            str(_get(piece, "classification", "") or "") for piece in failed_pieces
        ],
    }


def _rsync_source_arg(path: Path) -> str:
    text = str(path)
    if path.is_dir():
        return text.rstrip("/") + "/"
    return text


def build_incomplete_rehome_plan(
    *,
    torrent_hash: str,
    source_roots: Iterable[Path],
    target_root: Path,
    catalog_path: Path | None = None,
    verify_result: Any | None = None,
    qb_save_path: str = "",
    qb_expected_state: str = "stoppedDL",
    rt_target_directory: str = "",
    rt_expected_state: str = "stalledDL",
    library_roots: Iterable[str] = DEFAULT_LIBRARY_ROOTS,
) -> dict[str, Any]:
    """Build a non-mutating surgical incomplete rehome plan."""
    source_list = [Path(item) for item in source_roots]
    if not source_list:
        raise ValueError("at least one source root is required")

    cleanup_manifest = build_source_inode_manifest(
        source_roots=source_list,
        catalog_path=catalog_path,
        target_roots=[target_root],
        library_roots=library_roots,
    )
    target_summary = summarize_path(Path(target_root))
    target_class, target_blockers = classify_target_readiness(target_summary)
    verify_gate = (
        expected_incomplete_piece_gate(verify_result)
        if verify_result is not None
        else {"ok": False, "reasons": ["verify_result_missing"]}
    )

    blockers: list[str] = []
    warnings: list[str] = []
    blockers.extend(target_blockers)
    if not verify_gate.get("ok"):
        blockers.extend(str(item) for item in verify_gate.get("reasons", []))
    for source in cleanup_manifest["sources"]:
        if int(source.get("file_count") or 0) <= 0:
            blockers.append(f"source_empty:{source.get('root')}")
        if int(source.get("total_bytes") or 0) <= 0:
            blockers.append(f"source_zero_bytes:{source.get('root')}")
    if qb_save_path and str(Path(qb_save_path)).rstrip("/") == str(Path(target_root)).rstrip("/"):
        warnings.append("qb_save_path_equals_payload_root_may_create_nested_content_path")

    primary_source = source_list[0]
    target_arg = str(Path(target_root)).rstrip("/") + "/"
    rsync_cmd = [
        "rsync",
        "-aHAX",
        "--partial",
        "--human-readable",
        "--info=progress2",
        _rsync_source_arg(primary_source),
        target_arg,
    ]

    return {
        "schema": "hashall.incomplete_rehome.plan.v1",
        "mode": "dry_run",
        "hash": str(torrent_hash).strip().lower(),
        "status": "blocked" if blockers else "ready_for_pilot",
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "source_roots": [str(item) for item in source_list],
        "primary_copy_source": str(primary_source),
        "target_root": str(target_root),
        "target": {
            **target_summary.__dict__,
            "class": target_class,
        },
        "expected_incomplete_gate": verify_gate,
        "copy_plan": {
            "tool": "rsync",
            "argv": rsync_cmd,
            "note": "dry-run plan only; run during pilot after stopping/pausing clients",
        },
        "client_plan": {
            "qb": {
                "save_path": qb_save_path,
                "expected_state_after_recheck": qb_expected_state,
                "operations": ["pause_or_stop", "set_location_or_fastresume_patch", "force_recheck", "leave_stopped"],
            },
            "rt": {
                "target_directory": rt_target_directory or str(target_root),
                "expected_state_after_recheck": rt_expected_state,
                "operations": ["stop", "repoint_directory", "force_recheck", "start_if_needed_to_wait_for_seeds"],
            },
        },
        "cleanup_gate": {
            "delete_before_verify": False,
            "requires_user_cleanup_approval": True,
            "manifest_summary": cleanup_manifest["summary"],
            "cleanup_candidates_after_verify": cleanup_manifest["cleanup_candidates_after_verify"],
            "existing_cleanup_paths_after_verify": cleanup_manifest["existing_cleanup_paths_after_verify"],
            "cleanup_path_groups_after_verify": cleanup_manifest["cleanup_path_groups_after_verify"],
            "delete_paths_after_verify": cleanup_manifest["delete_paths_after_verify"],
        },
        "source_inode_manifest": cleanup_manifest,
    }


def build_incomplete_rehome_pilot_dryrun(
    *,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Convert a ready Plan C artifact into a fresh non-mutating pilot manifest."""
    status = str(plan.get("status") or "")
    blockers = list(plan.get("blockers") or [])
    if status != "ready_for_pilot":
        blockers.append(f"plan_not_ready:{status or 'unknown'}")

    source_roots = [str(item) for item in plan.get("source_roots") or []]
    target_root = str(plan.get("target_root") or "")
    current_sources = [summarize_path(Path(path)).__dict__ for path in source_roots]
    current_target = summarize_path(Path(target_root)).__dict__ if target_root else {}
    target_class, target_blockers = classify_target_readiness(
        PathSummary(**current_target) if current_target else PathSummary("", False, False, 0, 0, 0, 0)
    )
    if target_class == "nonzero_existing_tree":
        blockers.extend(target_blockers)

    copy_argv = list(((plan.get("copy_plan") or {}).get("argv")) or [])
    qb_plan = dict((plan.get("client_plan") or {}).get("qb") or {})
    rt_plan = dict((plan.get("client_plan") or {}).get("rt") or {})
    torrent_hash = str(plan.get("hash") or "").strip().lower()

    operations = [
        {
            "phase": "preflight",
            "action": "confirm_plan_still_ready",
            "mutation": False,
        },
        {
            "phase": "copy",
            "action": "rsync_source_to_target",
            "mutation": True,
            "argv": copy_argv,
        },
        {
            "phase": "rt",
            "action": "repoint_recheck_start_waiting",
            "mutation": True,
            "hash": torrent_hash,
            "target_directory": rt_plan.get("target_directory", ""),
            "xmlrpc_sequence": [
                "d.stop",
                "d.close",
                "d.directory.set",
                "d.save_full_session",
                "session.save",
                "d.open",
                "d.check_hash",
                "d.start",
            ],
            "expected_state": rt_plan.get("expected_state_after_recheck", "stalledDL"),
        },
        {
            "phase": "qb",
            "action": "set_location_recheck_leave_stopped",
            "mutation": True,
            "hash": torrent_hash,
            "save_path": qb_plan.get("save_path", ""),
            "api_sequence": [
                "pause_torrent",
                "set_location(resume_after=False)",
                "recheck_torrent",
                "pause_torrent",
            ],
            "expected_state": qb_plan.get("expected_state_after_recheck", "stoppedDL"),
        },
        {
            "phase": "verify",
            "action": "verify_target_matches_expected_incomplete_gate",
            "mutation": False,
        },
        {
            "phase": "cleanup",
            "action": "request_separate_cleanup_approval",
            "mutation": False,
            "delete_paths_after_verify": (plan.get("cleanup_gate") or {}).get("delete_paths_after_verify", []),
        },
    ]

    return {
        "schema": "hashall.incomplete_rehome.pilot_dryrun.v1",
        "mode": "dry_run",
        "hash": torrent_hash,
        "status": "blocked" if blockers else "ready_for_live_approval",
        "blockers": sorted(set(str(item) for item in blockers)),
        "current_sources": current_sources,
        "current_target": {**current_target, "class": target_class},
        "operations": operations,
        "cleanup_gate": plan.get("cleanup_gate") or {},
    }


def _approval_matches(*, approval: str, torrent_hash: str) -> bool:
    text = str(approval or "").strip().lower()
    key = str(torrent_hash or "").strip().lower()
    return bool(key and key in text and "plan c" in text and "no cleanup" in text)


def execute_incomplete_rehome_pilot(
    *,
    pilot: dict[str, Any],
    apply: bool = False,
    approval: str = "",
    qbit_client: Any | None = None,
    rt_repoint_func: Any | None = None,
    rt_start_func: Any | None = None,
    run_func: Any = subprocess.run,
    rt_rpc_url: str = "http://127.0.0.1:18000/",
) -> dict[str, Any]:
    """Execute or preview a Plan C pilot. Live mode is gated by explicit approval."""
    torrent_hash = str(pilot.get("hash") or "").strip().lower()
    events: list[dict[str, Any]] = []
    blockers = list(pilot.get("blockers") or [])
    if str(pilot.get("status") or "") != "ready_for_live_approval":
        blockers.append(f"pilot_not_ready:{pilot.get('status') or 'unknown'}")
    if apply and not _approval_matches(approval=approval, torrent_hash=torrent_hash):
        blockers.append("approval_string_missing_plan_c_hash_no_cleanup")
    if blockers or not apply:
        return {
            "schema": "hashall.incomplete_rehome.pilot_execute.v1",
            "mode": "dry_run" if not apply else "blocked",
            "hash": torrent_hash,
            "status": "blocked" if blockers else "dry_run_ready",
            "blockers": sorted(set(str(item) for item in blockers)),
            "events": events,
            "pilot": pilot,
        }

    if qbit_client is None:
        from hashall.qbittorrent import get_qbittorrent_client

        qbit_client = get_qbittorrent_client()
    if rt_repoint_func is None or rt_start_func is None:
        from hashall.rtorrent import rt_apply_directory_repoint, rt_xmlrpc_call

        rt_repoint_func = rt_repoint_func or rt_apply_directory_repoint
        rt_start_func = rt_start_func or rt_xmlrpc_call

    operations = list(pilot.get("operations") or [])
    try:
        for operation in operations:
            phase = str(operation.get("phase") or "")
            if phase == "copy":
                argv = list(operation.get("argv") or [])
                if not argv:
                    raise RuntimeError("copy operation missing argv")
                run_func(argv, check=True)
                events.append({"phase": phase, "status": "ok", "argv": argv})
            elif phase == "rt":
                target_directory = str(operation.get("target_directory") or "")
                rt_repoint_func(
                    torrent_hash,
                    target_directory,
                    rpc_url=rt_rpc_url,
                    restart=False,
                    check_before_start=False,
                    validate_target_exists=True,
                )
                # Existing rt_recheck_torrent only starts when complete; Plan C must
                # explicitly start so the incomplete torrent can wait for seeds.
                rt_start_func("d.check_hash", torrent_hash, rpc_url=rt_rpc_url, timeout=60)
                rt_start_func("d.start", torrent_hash, rpc_url=rt_rpc_url, timeout=60)
                events.append({"phase": phase, "status": "ok", "target_directory": target_directory})
            elif phase == "qb":
                save_path = str(operation.get("save_path") or "")
                if not qbit_client.pause_torrent(torrent_hash):
                    raise RuntimeError("qb pause_torrent failed")
                if not qbit_client.set_location(torrent_hash, save_path, resume_after=False):
                    raise RuntimeError("qb set_location failed")
                if not qbit_client.recheck_torrent(torrent_hash):
                    raise RuntimeError("qb recheck_torrent failed")
                if not qbit_client.pause_torrent(torrent_hash):
                    raise RuntimeError("qb final pause_torrent failed")
                events.append({"phase": phase, "status": "ok", "save_path": save_path})
            else:
                events.append({"phase": phase, "status": "skipped_nonmutating"})
    except Exception as exc:
        return {
            "schema": "hashall.incomplete_rehome.pilot_execute.v1",
            "mode": "apply",
            "hash": torrent_hash,
            "status": "failed",
            "blockers": [],
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
            "pilot": pilot,
        }

    return {
        "schema": "hashall.incomplete_rehome.pilot_execute.v1",
        "mode": "apply",
        "hash": torrent_hash,
        "status": "applied_no_cleanup",
        "blockers": [],
        "events": events,
        "pilot": pilot,
    }


def _lower_state(value: Any) -> str:
    return str(value or "").strip().lower()


def _hash_matches(row_hash: Any, requested_hash: str) -> bool:
    row_text = str(row_hash or "").strip().lower()
    wanted = str(requested_hash or "").strip().lower()
    if not row_text or not wanted:
        return False
    return row_text == wanted or row_text.startswith(wanted) or wanted.startswith(row_text)


def _read_cache_rows(cache_file: Path) -> tuple[list[dict[str, Any]], float | None, str]:
    path = Path(cache_file).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], None, "missing"
    except Exception:
        return [], None, "unreadable"
    if not isinstance(payload, list):
        return [], None, "invalid"
    rows = [row for row in payload if isinstance(row, dict)]
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        age = None
    return rows, age, "loaded"


def _find_hash_row(rows: Iterable[dict[str, Any]], torrent_hash: str) -> tuple[dict[str, Any] | None, list[str]]:
    matches = [row for row in rows if _hash_matches(row.get("hash"), torrent_hash)]
    hashes = sorted({str(row.get("hash") or "").lower() for row in matches if row.get("hash")})
    if len(hashes) == 1:
        return matches[0], []
    if not hashes:
        return None, ["hash_not_found"]
    return None, [f"hash_ambiguous:{len(hashes)}"]


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value).strip().rstrip("%")))
    except Exception:
        return 0


def _to_float(value: Any) -> float:
    text = str(value or "").strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        return float(value)
    except Exception:
        return 0.0


def _progress_fraction(value: Any, *, is_percent: bool = False) -> float:
    progress = _to_float(value)
    if is_percent and progress > 1.0:
        return progress / 100.0
    return progress


def _row_subset(row: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if key in row}


def build_qb_snapshot_from_cache(
    *,
    torrent_hash: str,
    cache_file: Path,
) -> dict[str, Any]:
    """Build a read-only qB state snapshot for a single torrent hash."""
    rows, age, cache_status = _read_cache_rows(cache_file)
    row, blockers = _find_hash_row(rows, torrent_hash)
    found = row is not None
    payload: dict[str, Any] = {
        "schema": "hashall.incomplete_rehome.qb_snapshot.v1",
        "mode": "read_only",
        "side": "qb",
        "hash": str(torrent_hash).strip().lower(),
        "status": "found" if found else "blocked",
        "blockers": blockers,
        "cache_file": str(Path(cache_file).expanduser()),
        "cache_status": cache_status,
        "cache_age_s": age,
        "rows_total": len(rows),
    }
    if not found or row is None:
        if cache_status != "loaded":
            payload["blockers"] = sorted(set(blockers + [f"cache_{cache_status}"]))
        return payload

    payload.update(
        {
            "hash": str(row.get("hash") or torrent_hash).strip().lower(),
            "name": str(row.get("name") or ""),
            "state": str(row.get("state") or ""),
            "save_path": str(row.get("save_path") or ""),
            "content_path": str(row.get("content_path") or ""),
            "progress": _to_float(row.get("progress")),
            "amount_left": _to_int(row.get("amount_left")),
            "size": _to_int(row.get("size") or row.get("total_size")),
            "tracker": str(row.get("tracker") or ""),
            "num_seeds": _to_int(row.get("num_seeds") or row.get("num_complete")),
            "num_leechs": _to_int(row.get("num_leechs") or row.get("num_incomplete")),
            "dlspeed": _to_int(row.get("dlspeed")),
            "upspeed": _to_int(row.get("upspeed")),
            "row": _row_subset(
                row,
                (
                    "hash",
                    "name",
                    "state",
                    "save_path",
                    "content_path",
                    "progress",
                    "amount_left",
                    "size",
                    "total_size",
                    "category",
                    "tags",
                    "tracker",
                    "num_seeds",
                    "num_leechs",
                    "availability",
                ),
            ),
        }
    )
    return payload


def build_rt_snapshot_from_cache(
    *,
    torrent_hash: str,
    cache_file: Path,
) -> dict[str, Any]:
    """Build a read-only rTorrent state snapshot for a single torrent hash."""
    rows, age, cache_status = _read_cache_rows(cache_file)
    row, blockers = _find_hash_row(rows, torrent_hash)
    found = row is not None
    payload: dict[str, Any] = {
        "schema": "hashall.incomplete_rehome.rt_snapshot.v1",
        "mode": "read_only",
        "side": "rt",
        "hash": str(torrent_hash).strip().lower(),
        "status": "found" if found else "blocked",
        "blockers": blockers,
        "cache_file": str(Path(cache_file).expanduser()),
        "cache_status": cache_status,
        "cache_age_s": age,
        "rows_total": len(rows),
    }
    if not found or row is None:
        if cache_status != "loaded":
            payload["blockers"] = sorted(set(blockers + [f"cache_{cache_status}"]))
        return payload

    has_progress_pct = row.get("progress_pct") is not None
    progress = _progress_fraction(
        row.get("progress_pct") if has_progress_pct else row.get("progress"),
        is_percent=has_progress_pct,
    )
    size = _to_int(row.get("size"))
    left_bytes = _to_int(row.get("left_bytes"))
    if not left_bytes and size and progress:
        left_bytes = max(0, int(size * (1.0 - progress)))
    complete = bool(progress >= 1.0 or str(row.get("state") or "").lower() in {"seeding", "stoppedup"})
    directory = str(row.get("directory") or row.get("save_path") or "")
    payload.update(
        {
            "hash": str(row.get("hash") or torrent_hash).strip().lower(),
            "name": str(row.get("name") or ""),
            "state": str(row.get("state") or row.get("st") or ""),
            "directory": directory,
            "save_path": str(row.get("save_path") or directory),
            "progress": progress,
            "complete": complete,
            "left_bytes": left_bytes,
            "size": size,
            "tracker": str(row.get("tracker") or ""),
            "seeds": _to_int(row.get("seeds")),
            "peers": _to_int(row.get("peers")),
            "dlspeed": _to_int(row.get("dlspeed")),
            "upspeed": _to_int(row.get("upspeed")),
            "row": _row_subset(
                row,
                (
                    "hash",
                    "name",
                    "state",
                    "st",
                    "save_path",
                    "directory",
                    "progress",
                    "progress_pct",
                    "size",
                    "category",
                    "tags",
                    "tracker",
                    "seeds",
                    "peers",
                ),
            ),
        }
    )
    return payload


def validate_incomplete_rehome_post_pilot(
    *,
    execute_report: dict[str, Any],
    target_verify_result: Any,
    qb_snapshot: dict[str, Any] | None = None,
    rt_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only validation report after a Plan C live pilot."""
    pilot = dict(execute_report.get("pilot") or {})
    torrent_hash = str(execute_report.get("hash") or pilot.get("hash") or "").strip().lower()
    qb_plan = {}
    rt_plan = {}
    for operation in pilot.get("operations") or []:
        if operation.get("phase") == "qb":
            qb_plan = dict(operation)
        elif operation.get("phase") == "rt":
            rt_plan = dict(operation)

    blockers: list[str] = []
    warnings: list[str] = []
    if str(execute_report.get("status") or "") != "applied_no_cleanup":
        blockers.append(f"execute_not_applied:{execute_report.get('status') or 'unknown'}")

    verify_gate = expected_incomplete_piece_gate(target_verify_result)
    if not verify_gate.get("ok"):
        blockers.extend(f"target_verify:{reason}" for reason in verify_gate.get("reasons", []))

    qb_check: dict[str, Any] = {"provided": bool(qb_snapshot)}
    if qb_snapshot:
        expected_state = _lower_state(qb_plan.get("expected_state") or "stoppedDL")
        actual_state = _lower_state(qb_snapshot.get("state"))
        expected_save = str(qb_plan.get("save_path") or "").rstrip("/")
        actual_save = str(qb_snapshot.get("save_path") or "").rstrip("/")
        qb_check.update(
            {
                "state": qb_snapshot.get("state"),
                "save_path": qb_snapshot.get("save_path"),
                "progress": qb_snapshot.get("progress"),
                "amount_left": qb_snapshot.get("amount_left"),
                "expected_state": qb_plan.get("expected_state") or "stoppedDL",
                "expected_save_path": qb_plan.get("save_path") or "",
            }
        )
        if actual_state != expected_state:
            blockers.append(f"qb_state_mismatch:{actual_state or 'missing'}")
        if expected_save and actual_save != expected_save:
            blockers.append("qb_save_path_mismatch")
    else:
        warnings.append("qb_snapshot_missing")

    rt_check: dict[str, Any] = {"provided": bool(rt_snapshot)}
    if rt_snapshot:
        expected_state = _lower_state(rt_plan.get("expected_state") or "stalledDL")
        actual_state = _lower_state(rt_snapshot.get("state"))
        expected_dir = str(rt_plan.get("target_directory") or "").rstrip("/")
        actual_dir = str(rt_snapshot.get("directory") or "").rstrip("/")
        rt_check.update(
            {
                "state": rt_snapshot.get("state"),
                "complete": rt_snapshot.get("complete"),
                "left_bytes": rt_snapshot.get("left_bytes"),
                "directory": rt_snapshot.get("directory"),
                "expected_state": rt_plan.get("expected_state") or "stalledDL",
                "expected_directory": rt_plan.get("target_directory") or "",
            }
        )
        acceptable_rt_states = {expected_state, "stalleddl", "downloading"}
        if actual_state not in acceptable_rt_states:
            blockers.append(f"rt_state_mismatch:{actual_state or 'missing'}")
        if expected_dir and actual_dir != expected_dir:
            blockers.append("rt_directory_mismatch")
    else:
        warnings.append("rt_snapshot_missing")

    return {
        "schema": "hashall.incomplete_rehome.post_pilot_validation.v1",
        "mode": "read_only",
        "hash": torrent_hash,
        "status": "validated_ready_for_cleanup_approval" if not blockers else "blocked",
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "target_verify_gate": verify_gate,
        "qb_check": qb_check,
        "rt_check": rt_check,
        "cleanup_gate": pilot.get("cleanup_gate") or {},
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    import json

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + os.linesep, encoding="utf-8")
