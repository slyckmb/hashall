#!/usr/bin/env python3
"""Audit and prune recovered non-seeding payload content."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List


def _files_table(device_id: int) -> str:
    if device_id <= 0:
        raise ValueError(f"invalid device id: {device_id}")
    return f"files_{device_id}"


def _norm_relpath(value: str) -> str:
    return str(PurePosixPath(value).as_posix()).strip("/")


def _device_mounts(conn: sqlite3.Connection, device_id: int) -> List[Path]:
    row = conn.execute(
        """
        SELECT mount_point, preferred_mount_point
        FROM devices
        WHERE device_id = ?
        """,
        (device_id,),
    ).fetchone()
    if not row:
        raise RuntimeError(f"device not found: {device_id}")

    mounts: List[Path] = []
    for item in row:
        if not item:
            continue
        p = Path(str(item)).expanduser()
        mounts.append(p)
        try:
            mounts.append(p.resolve())
        except OSError:
            pass

    deduped: List[Path] = []
    seen = set()
    for m in mounts:
        key = str(m)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    return deduped


def _resolve_recovery_rel_and_abs(
    conn: sqlite3.Connection, *, device_id: int, recovery_prefix: str
) -> tuple[str, Path]:
    mounts = _device_mounts(conn, device_id)
    raw = Path(recovery_prefix).expanduser()
    candidates: List[Path] = [raw]
    try:
        candidates.append(raw.resolve())
    except OSError:
        pass

    for candidate in candidates:
        for mount in mounts:
            try:
                rel = candidate.relative_to(mount)
                return _norm_relpath(str(rel)), candidate
            except ValueError:
                continue

    # Alias fallback: /data/media -> device mount ending in /media (e.g. /stash/media).
    raw_str = str(raw)
    if raw_str == "/data/media" or raw_str.startswith("/data/media/"):
        suffix = raw_str[len("/data/media/") :] if raw_str.startswith("/data/media/") else ""
        for mount in mounts:
            if mount.name != "media":
                continue
            remapped = mount if not suffix else mount / suffix
            rel = remapped.relative_to(mount)
            return _norm_relpath(str(rel)), remapped

    # Already a DB-relative path.
    if not str(raw).startswith("/"):
        return _norm_relpath(str(raw)), mounts[0] / raw

    raise RuntimeError(
        f"recovery prefix is not under device {device_id} mounts: {recovery_prefix}"
    )


def _derive_canonical_base(recovery_rel: str) -> str:
    parts = list(PurePosixPath(recovery_rel).parts)
    for i, token in enumerate(parts):
        if not token.startswith("recovery_"):
            continue
        j = i + 1
        if j < len(parts) and (
            parts[j].startswith("recycle_snapshot_")
            or parts[j].startswith("snapshot_")
        ):
            j += 1
        return _norm_relpath("/".join(parts[:i]))
    parent = PurePosixPath(recovery_rel).parent
    if str(parent) in ("", "."):
        return ""
    return _norm_relpath(str(parent))


def _unit_key_from_suffix(suffix_path: str) -> str:
    parts = list(PurePosixPath(suffix_path).parts)
    if not parts:
        return ""
    depth = 3 if parts[0] == "cross-seed" else 2
    return "/".join(parts[: min(len(parts), depth)])


@dataclass
class UnitAgg:
    unit_key: str
    files: int = 0
    bytes: int = 0
    exact_files: int = 0
    exact_bytes: int = 0
    stash_support_files: int = 0
    stash_support_bytes: int = 0
    pool_support_files: int = 0
    pool_support_bytes: int = 0
    unique_files: int = 0
    unique_bytes: int = 0
    missing_sha_files: int = 0
    missing_sha_bytes: int = 0
    sample_paths: List[str] = field(default_factory=list)
    block_reasons: Dict[str, int] = field(default_factory=dict)
    live_refs: int = 0
    action: str = "REVIEW_PARTIAL"
    action_reason: str = ""

    def add_reason(self, reason: str) -> None:
        self.block_reasons[reason] = int(self.block_reasons.get(reason, 0)) + 1


def _fetch_rows(
    conn: sqlite3.Connection,
    *,
    stash_device: int,
    pool_device: int,
    recovery_rel: str,
    canonical_base: str,
) -> list[dict]:
    stash_table = _files_table(stash_device)
    pool_table = _files_table(pool_device)
    rr = _norm_relpath(recovery_rel)
    rr_glob = rr + "/%"
    canon = canonical_base
    prefix_len = len(rr)
    tmp = "tmp_recovery_src"
    conn.execute("PRAGMA temp_store = MEMORY")

    conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    conn.execute(
        f"""
        CREATE TEMP TABLE {tmp} (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            sha256 TEXT,
            canonical_path TEXT NOT NULL,
            has_sha INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO {tmp} (path, size, sha256, canonical_path, has_sha)
        SELECT
            s.path,
            s.size,
            s.sha256,
            CASE WHEN ? = ''
                 THEN substr(s.path, ? + 2)
                 ELSE ? || '/' || substr(s.path, ? + 2)
            END AS canonical_path,
            CASE WHEN COALESCE(s.sha256, '') = '' THEN 0 ELSE 1 END AS has_sha
        FROM {stash_table} s
        WHERE s.status = 'active' AND (s.path = ? OR s.path LIKE ?)
        """,
        (canon, prefix_len, canon, prefix_len, rr, rr_glob),
    )
    conn.execute(f"CREATE INDEX idx_{tmp}_canonical ON {tmp}(canonical_path)")
    conn.execute(f"CREATE INDEX idx_{tmp}_sha_size ON {tmp}(sha256, size)")

    exact_paths = set(
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT t.path
            FROM {tmp} t
            JOIN {stash_table} x
              ON x.status = 'active'
             AND x.path = t.canonical_path
             AND x.size = t.size
             AND COALESCE(x.sha256, '') = COALESCE(t.sha256, '')
            UNION
            SELECT DISTINCT t.path
            FROM {tmp} t
            JOIN {pool_table} y
              ON y.status = 'active'
             AND y.path = t.canonical_path
             AND y.size = t.size
             AND COALESCE(y.sha256, '') = COALESCE(t.sha256, '')
            """
        ).fetchall()
    )
    stash_support_paths = set(
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT t.path
            FROM {tmp} t
            JOIN {stash_table} x
              ON t.has_sha = 1
             AND x.status = 'active'
             AND x.path NOT LIKE ?
             AND x.path != ?
             AND x.size = t.size
             AND x.sha256 = t.sha256
            """,
            (rr_glob, rr),
        ).fetchall()
    )
    pool_support_paths = set(
        row[0]
        for row in conn.execute(
            f"""
            SELECT DISTINCT t.path
            FROM {tmp} t
            JOIN {pool_table} y
              ON t.has_sha = 1
             AND y.status = 'active'
             AND y.size = t.size
             AND y.sha256 = t.sha256
            """
        ).fetchall()
    )

    src_rows = conn.execute(
        f"SELECT path, size, sha256, canonical_path FROM {tmp} ORDER BY path"
    ).fetchall()
    conn.execute(f"DROP TABLE IF EXISTS {tmp}")

    rows = []
    for path, size, sha256, canonical_path in src_rows:
        rows.append(
            {
                "path": path,
                "size": size,
                "sha256": sha256,
                "canonical_path": canonical_path,
                "exact": path in exact_paths,
                "stash_support": path in stash_support_paths,
                "pool_support": path in pool_support_paths,
            }
        )
    return rows


def _count_live_refs(conn: sqlite3.Connection, unit_abs_path: Path) -> int:
    path_str = str(unit_abs_path)
    like = path_str.rstrip("/") + "/%"
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM payloads p
        JOIN torrent_instances ti ON ti.payload_id = p.payload_id
        WHERE p.root_path = ? OR p.root_path LIKE ?
        """,
        (path_str, like),
    ).fetchone()
    return int(row[0] or 0)


def build_report(
    conn: sqlite3.Connection,
    *,
    stash_device: int,
    pool_device: int,
    recovery_prefix: str,
) -> dict:
    recovery_rel, recovery_abs = _resolve_recovery_rel_and_abs(
        conn, device_id=stash_device, recovery_prefix=recovery_prefix
    )
    canonical_base = _derive_canonical_base(recovery_rel)
    rows = _fetch_rows(
        conn,
        stash_device=stash_device,
        pool_device=pool_device,
        recovery_rel=recovery_rel,
        canonical_base=canonical_base,
    )

    units: Dict[str, UnitAgg] = {}
    for row in rows:
        rel = str(row["path"])
        if rel == recovery_rel:
            suffix = PurePosixPath(rel).name
        else:
            suffix = rel[len(recovery_rel) + 1 :]
        unit_key = _unit_key_from_suffix(suffix)
        unit = units.setdefault(unit_key, UnitAgg(unit_key=unit_key))

        size = int(row["size"] or 0)
        unit.files += 1
        unit.bytes += size
        if len(unit.sample_paths) < 3:
            unit.sample_paths.append(rel)

        sha = str(row["sha256"] or "")
        exact = bool(row["exact"])
        stash_support = bool(row["stash_support"])
        pool_support = bool(row["pool_support"])

        if not sha:
            unit.missing_sha_files += 1
            unit.missing_sha_bytes += size
            unit.add_reason("missing_sha256")
            continue

        if exact:
            unit.exact_files += 1
            unit.exact_bytes += size
        if stash_support:
            unit.stash_support_files += 1
            unit.stash_support_bytes += size
        if pool_support:
            unit.pool_support_files += 1
            unit.pool_support_bytes += size
        if not exact and not stash_support and not pool_support:
            unit.unique_files += 1
            unit.unique_bytes += size
            unit.add_reason("unique_content")

    for unit in units.values():
        unit_path = recovery_abs / unit.unit_key
        unit.live_refs = _count_live_refs(conn, unit_path)
        if unit.live_refs > 0:
            unit.action = "HOLD_ACTIVE_REFS"
            unit.action_reason = "unit has live torrent refs"
            unit.add_reason("live_torrent_refs")
        elif unit.missing_sha_files > 0:
            unit.action = "NEEDS_FULL_HASH"
            unit.action_reason = "some files missing sha256"
        elif unit.files > 0 and unit.exact_files == unit.files:
            unit.action = "DELETE_EXACT_DUPLICATE"
            unit.action_reason = "all files matched exact canonical path+hash elsewhere"
        elif unit.files > 0 and unit.unique_files == 0 and unit.pool_support_files == unit.files:
            unit.action = "POOL_SUPPORTED_NO_GROWTH"
            unit.action_reason = "all files already exist on pool by sha256"
        elif unit.files > 0 and unit.unique_files == 0 and unit.stash_support_files == unit.files:
            unit.action = "STASH_SUPPORTED_BY_HARDLINKS"
            unit.action_reason = "all files already exist on stash by sha256"
        else:
            unit.action = "REVIEW_PARTIAL"
            unit.action_reason = "mixed/partial support"

    sorted_units = sorted(
        units.values(),
        key=lambda u: (u.bytes, u.files),
        reverse=True,
    )

    summary = {
        "unit_count": len(sorted_units),
        "file_count": sum(u.files for u in sorted_units),
        "bytes": sum(u.bytes for u in sorted_units),
        "delete_exact_units": sum(1 for u in sorted_units if u.action == "DELETE_EXACT_DUPLICATE"),
        "delete_exact_bytes": sum(u.bytes for u in sorted_units if u.action == "DELETE_EXACT_DUPLICATE"),
        "pool_supported_units": sum(1 for u in sorted_units if u.action == "POOL_SUPPORTED_NO_GROWTH"),
        "pool_supported_bytes": sum(u.bytes for u in sorted_units if u.action == "POOL_SUPPORTED_NO_GROWTH"),
        "stash_supported_units": sum(1 for u in sorted_units if u.action == "STASH_SUPPORTED_BY_HARDLINKS"),
        "stash_supported_bytes": sum(u.bytes for u in sorted_units if u.action == "STASH_SUPPORTED_BY_HARDLINKS"),
        "review_units": sum(1 for u in sorted_units if u.action == "REVIEW_PARTIAL"),
        "review_bytes": sum(u.bytes for u in sorted_units if u.action == "REVIEW_PARTIAL"),
        "hold_ref_units": sum(1 for u in sorted_units if u.action == "HOLD_ACTIVE_REFS"),
        "needs_hash_units": sum(1 for u in sorted_units if u.action == "NEEDS_FULL_HASH"),
    }

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "recovery_prefix": str(recovery_prefix),
        "recovery_rel": recovery_rel,
        "recovery_abs": str(recovery_abs),
        "canonical_base_rel": canonical_base,
        "stash_device_id": stash_device,
        "pool_device_id": pool_device,
        "summary": summary,
        "units": [
            {
                "unit_key": u.unit_key,
                "unit_abs_path": str(recovery_abs / u.unit_key),
                "files": u.files,
                "bytes": u.bytes,
                "exact_files": u.exact_files,
                "exact_bytes": u.exact_bytes,
                "stash_support_files": u.stash_support_files,
                "stash_support_bytes": u.stash_support_bytes,
                "pool_support_files": u.pool_support_files,
                "pool_support_bytes": u.pool_support_bytes,
                "unique_files": u.unique_files,
                "unique_bytes": u.unique_bytes,
                "missing_sha_files": u.missing_sha_files,
                "missing_sha_bytes": u.missing_sha_bytes,
                "live_refs": u.live_refs,
                "action": u.action,
                "action_reason": u.action_reason,
                "block_reason_counts": u.block_reasons,
                "sample_paths": u.sample_paths,
            }
            for u in sorted_units
        ],
    }


def apply_exact_prune(
    conn: sqlite3.Connection,
    *,
    report: dict,
    stash_device: int,
    limit: int,
) -> dict:
    table = _files_table(stash_device)
    recovery_rel = _norm_relpath(str(report["recovery_rel"]))
    recovery_abs = Path(str(report["recovery_abs"]))
    candidates = [
        u for u in report.get("units", []) if u.get("action") == "DELETE_EXACT_DUPLICATE"
    ]
    if limit > 0:
        candidates = candidates[:limit]

    deleted_units = 0
    deleted_files = 0
    deleted_bytes = 0
    skipped = []
    deleted_items = []
    for unit in candidates:
        unit_key = str(unit.get("unit_key") or "")
        unit_abs = Path(str(unit.get("unit_abs_path") or ""))
        if not unit_abs:
            skipped.append({"unit_key": unit_key, "reason": "missing_unit_path"})
            continue
        try:
            unit_abs.relative_to(recovery_abs)
        except ValueError:
            skipped.append({"unit_key": unit_key, "reason": "outside_recovery_root"})
            continue
        if not unit_abs.exists():
            skipped.append({"unit_key": unit_key, "reason": "missing_on_disk"})
            continue
        if int(unit.get("live_refs") or 0) > 0:
            skipped.append({"unit_key": unit_key, "reason": "live_torrent_refs"})
            continue

        if unit_abs.is_dir():
            shutil.rmtree(unit_abs)
        else:
            unit_abs.unlink()

        unit_rel = recovery_rel if not unit_key else f"{recovery_rel}/{unit_key}"
        like = unit_rel.rstrip("/") + "/%"
        conn.execute(
            f"""
            UPDATE {table}
            SET status = 'deleted',
                last_seen_at = CURRENT_TIMESTAMP,
                last_modified_at = CURRENT_TIMESTAMP
            WHERE status = 'active' AND (path = ? OR path LIKE ?)
            """,
            (unit_rel, like),
        )
        deleted_units += 1
        deleted_files += int(unit.get("files") or 0)
        deleted_bytes += int(unit.get("bytes") or 0)
        deleted_items.append({"unit_key": unit_key, "unit_path": str(unit_abs)})

    conn.commit()
    return {
        "deleted_units": deleted_units,
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "deleted_items": deleted_items,
        "skipped": skipped,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Recovery workflow: classify and optionally prune exact duplicate recovered units"
    )
    p.add_argument("--db", required=True, help="Catalog DB path")
    p.add_argument("--recovery-prefix", required=True, help="Recovery prefix path (absolute or DB-relative)")
    p.add_argument("--stash-device", type=int, default=49, help="Stash device id (files table source)")
    p.add_argument("--pool-device", type=int, default=44, help="Pool device id (files table compare target)")
    p.add_argument("--output-dir", default="out/reports/recovery-workflow")
    p.add_argument("--output", default="", help="Optional explicit report JSON path")
    p.add_argument("--limit", type=int, default=20, help="Apply limit for prune actions (0 = unlimited)")
    p.add_argument("--apply", action="store_true", help="Delete exact duplicate units and mark files deleted")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    if args.apply:
        conn = sqlite3.connect(db_path)
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        report = build_report(
            conn,
            stash_device=int(args.stash_device),
            pool_device=int(args.pool_device),
            recovery_prefix=str(args.recovery_prefix),
        )
        apply_result = None
        if args.apply:
            apply_result = apply_exact_prune(
                conn,
                report=report,
                stash_device=int(args.stash_device),
                limit=int(args.limit),
            )
            report["apply"] = apply_result
    finally:
        conn.close()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.output:
        output_path = Path(args.output)
    else:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"recovery-workflow-{stamp}.json"
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(f"report={output_path}")
    print(
        "summary="
        f"units:{summary['unit_count']} files:{summary['file_count']} bytes:{summary['bytes']} "
        f"delete_exact_units:{summary['delete_exact_units']} delete_exact_bytes:{summary['delete_exact_bytes']} "
        f"pool_supported_units:{summary['pool_supported_units']} review_units:{summary['review_units']}"
    )
    if args.apply:
        apply = report.get("apply") or {}
        print(
            "apply="
            f"deleted_units:{apply.get('deleted_units', 0)} "
            f"deleted_files:{apply.get('deleted_files', 0)} "
            f"deleted_bytes:{apply.get('deleted_bytes', 0)} "
            f"skipped:{len(apply.get('skipped', []))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
