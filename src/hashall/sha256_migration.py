"""
SHA256 migration utilities.

Backfills per-device file tables with full SHA256 hashes and provides
spot-check verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from hashall.model import connect_db
from hashall.device import ensure_files_table
from hashall.scan import compute_full_hashes, compute_sha256


@dataclass
class BackfillSummary:
    device_id: int
    device_alias: str | None
    total_missing: int
    processed: int
    updated: int
    mismatches: int
    errors: int
    duration_seconds: float


def _resolve_devices(conn, device: str | None):
    cursor = conn.cursor()
    if device is None:
        rows = cursor.execute(
            "SELECT device_id, device_alias, mount_point FROM devices ORDER BY device_alias"
        ).fetchall()
        return rows

    # Try alias first
    row = cursor.execute(
        "SELECT device_id, device_alias, mount_point FROM devices WHERE device_alias = ?",
        (device,),
    ).fetchone()
    if row:
        return [row]

    # Then device_id
    if device.isdigit():
        row = cursor.execute(
            "SELECT device_id, device_alias, mount_point FROM devices WHERE device_id = ?",
            (int(device),),
        ).fetchone()
        if row:
            return [row]

    return []


def backfill_sha256(
    db_path: Path,
    device: str | None = None,
    batch_size: int = 200,
    limit: int | None = None,
    dry_run: bool = False,
):
    """
    Backfill SHA256 for active files missing it. Resumable and safe to re-run.

    Args:
        db_path: Path to catalog DB
        device: Optional device alias or ID to scope
        batch_size: Number of rows per batch
        limit: Optional cap on files processed
        dry_run: If True, compute but do not write
    """
    conn = connect_db(db_path)
    cursor = conn.cursor()

    devices = _resolve_devices(conn, device)
    if not devices:
        print("No matching devices found.")
        conn.close()
        return

    summaries: list[BackfillSummary] = []

    for row in devices:
        device_id = row["device_id"]
        device_alias = row["device_alias"]
        mount_point = Path(row["mount_point"])
        table_name = f"files_{device_id}"

        ensure_files_table(cursor, device_id)
        conn.commit()

        total_missing = cursor.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE status = 'active' AND sha256 IS NULL"
        ).fetchone()[0]

        label = device_alias or str(device_id)
        print(f"\n🔧 Backfilling SHA256 for device {label} (id={device_id})")
        print(f"   Missing SHA256: {total_missing:,}")

        processed = 0
        updated = 0
        mismatches = 0
        errors = 0
        last_path = None
        started = time.time()

        try:
            while True:
                if limit is not None and processed >= limit:
                    break

                params = []
                query = (
                    f"SELECT path, sha1, inode, size FROM {table_name} "
                    "WHERE status = 'active' AND sha256 IS NULL"
                )
                if last_path is not None:
                    query += " AND path > ?"
                    params.append(last_path)

                query += " ORDER BY path LIMIT ?"
                params.append(batch_size if limit is None else min(batch_size, limit - processed))

                rows = cursor.execute(query, params).fetchall()
                if not rows:
                    break

                # Group files by (inode, size) for hardlink deduplication
                inode_groups = {}  # {(inode, size): [(path, sha1), ...]}
                files_without_inode = []

                for file_row in rows:
                    rel_path = file_row["path"]
                    existing_sha1 = file_row["sha1"]
                    inode = file_row["inode"]
                    size = file_row["size"]
                    last_path = rel_path

                    if inode is not None and inode != 0:
                        key = (inode, size)
                        inode_groups.setdefault(key, []).append((rel_path, existing_sha1))
                    else:
                        files_without_inode.append((rel_path, existing_sha1))

                # Hash once per inode group
                for (inode, size), group_files in inode_groups.items():
                    # Pick first file as representative
                    repr_path, repr_sha1 = group_files[0]
                    abs_path = mount_point / repr_path
                    processed += len(group_files)

                    if not abs_path.exists():
                        errors += len(group_files)
                        print(f"⚠️  Missing: {abs_path} (affects {len(group_files)} hardlinks)")
                        continue

                    try:
                        full_sha1, full_sha256 = compute_full_hashes(abs_path)
                    except Exception as exc:
                        errors += len(group_files)
                        print(f"⚠️  Error hashing {abs_path}: {exc} (affects {len(group_files)} hardlinks)")
                        continue

                    if repr_sha1 and repr_sha1 != full_sha1:
                        mismatches += 1
                        print(f"❌ SHA1 mismatch: {repr_path}")

                    if dry_run:
                        updated += len(group_files)
                        continue

                    # Update ALL files with this inode
                    cursor.execute(
                        f"UPDATE {table_name} "
                        "SET sha256 = ?, sha1 = COALESCE(sha1, ?), last_modified_at = datetime('now') "
                        "WHERE inode = ? AND size = ? AND status = 'active'",
                        (full_sha256, full_sha1, inode, size),
                    )
                    updated += len(group_files)

                # Handle files without inodes individually
                for rel_path, existing_sha1 in files_without_inode:
                    abs_path = mount_point / rel_path
                    processed += 1

                    if not abs_path.exists():
                        errors += 1
                        print(f"⚠️  Missing: {abs_path}")
                        continue

                    try:
                        full_sha1, full_sha256 = compute_full_hashes(abs_path)
                    except Exception as exc:
                        errors += 1
                        print(f"⚠️  Error hashing {abs_path}: {exc}")
                        continue

                    if existing_sha1 and existing_sha1 != full_sha1:
                        mismatches += 1
                        print(f"❌ SHA1 mismatch: {rel_path}")

                    if dry_run:
                        updated += 1
                        continue

                    cursor.execute(
                        f"UPDATE {table_name} "
                        "SET sha256 = ?, sha1 = COALESCE(sha1, ?), last_modified_at = datetime('now') "
                        "WHERE path = ?",
                        (full_sha256, full_sha1, rel_path),
                    )
                    updated += 1

                if not dry_run:
                    conn.commit()
        except KeyboardInterrupt:
            if not dry_run:
                conn.commit()
            print("⚠️  Backfill interrupted by user.")

        duration = time.time() - started
        summaries.append(
            BackfillSummary(
                device_id=device_id,
                device_alias=device_alias,
                total_missing=total_missing,
                processed=processed,
                updated=updated,
                mismatches=mismatches,
                errors=errors,
                duration_seconds=duration,
            )
        )

        print(
            f"   Done: {updated:,} updated, {mismatches} mismatches, {errors} errors "
            f"({duration:.1f}s)"
        )

    conn.close()
    return summaries


def verify_sha256(
    db_path: Path,
    device: str | None = None,
    sample: int = 50,
):
    """Spot-check SHA256 values against on-disk content."""
    conn = connect_db(db_path)
    cursor = conn.cursor()

    devices = _resolve_devices(conn, device)
    if not devices:
        print("No matching devices found.")
        conn.close()
        return

    for row in devices:
        device_id = row["device_id"]
        device_alias = row["device_alias"]
        mount_point = Path(row["mount_point"])
        table_name = f"files_{device_id}"

        ensure_files_table(cursor, device_id)
        conn.commit()

        total = cursor.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE status = 'active' AND sha256 IS NOT NULL"
        ).fetchone()[0]

        label = device_alias or str(device_id)
        if total == 0:
            print(f"\n🔍 SHA256 verify for {label}: no SHA256 hashes to verify")
            continue

        count = min(sample, total)
        print(f"\n🔍 SHA256 verify for {label}: sampling {count} of {total}")

        rows = cursor.execute(
            f"SELECT path, sha256 FROM {table_name} "
            "WHERE status = 'active' AND sha256 IS NOT NULL "
            "ORDER BY RANDOM() LIMIT ?",
            (count,),
        ).fetchall()

        mismatches = 0
        errors = 0

        for file_row in rows:
            rel_path = file_row["path"]
            expected = file_row["sha256"]
            abs_path = mount_point / rel_path

            if not abs_path.exists():
                errors += 1
                print(f"⚠️  Missing: {abs_path}")
                continue

            try:
                actual = compute_sha256(abs_path)
            except Exception as exc:
                errors += 1
                print(f"⚠️  Error hashing {abs_path}: {exc}")
                continue

            if actual != expected:
                mismatches += 1
                print(f"❌ SHA256 mismatch: {rel_path}")

        if mismatches == 0 and errors == 0:
            print("✅ All sampled hashes match")
        else:
            print(f"⚠️  Mismatches: {mismatches}, Errors: {errors}")

    conn.close()
