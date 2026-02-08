# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/cli.py
# ✅ Minimal fix: Added --no-export, fixed missing arg to verify_trees

import click
import time
import os
import sys
import shutil
import subprocess
import grp
from pathlib import Path
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify_trees import verify_trees
from hashall import __version__

DEFAULT_DB_PATH = Path.home() / ".hashall" / "catalog.db"
DEFAULT_JDUPES_LOG_DIR = Path.home() / ".logs" / "hashall" / "jdupes"
DEFAULT_PERMS_LOG_DIR = Path.home() / ".logs" / "hashall" / "perms"

_LOG_SETUP = False
_LOG_FILE = None
_LOG_PATH = None
_RUN_HEADER_EMITTED = False
_PIPE_BROKEN = False


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
            self._secondary.write(text)
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
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    script = Path(sys.argv[0]).name or "hashall"
    print(f"🧾 {script} v{__version__} @ {timestamp}")
    if _LOG_PATH:
        print(f"🧾 log: {_LOG_PATH}")
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
@click.option("--scan-nested-datasets", is_flag=True,
              help="Detect nested mountpoints/datasets and scan them separately.")
def scan_cmd(path, db, parallel, workers, batch_size, hash_mode, hash_mode_flag, show_path, scan_nested_datasets):
    """Scan a directory and store file metadata in SQLite."""
    # Use flag if provided, otherwise use hash_mode
    mode = hash_mode_flag if hash_mode_flag else hash_mode
    scan_path(db_path=Path(db), root_path=Path(path), parallel=parallel,
              workers=workers, batch_size=batch_size, hash_mode=mode,
              show_current_path=show_path, scan_nested_datasets=scan_nested_datasets)

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

# Payload command group
@cli.group()
def payload():
    """Payload identity and torrent mapping commands."""
    pass


@payload.command("sync")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--qbit-url", default=None, help="qBittorrent URL (default: http://localhost:9003)")
@click.option("--qbit-user", default=None, help="qBittorrent username (default: admin)")
@click.option("--qbit-pass", default=None, help="qBittorrent password")
@click.option("--category", default=None, help="Filter torrents by category")
@click.option("--tag", default=None, help="Filter torrents by tag")
@click.option("--upgrade-missing", is_flag=True,
              help="Hash missing SHA256s for payload files (inode-aware).")
def payload_sync(db, qbit_url, qbit_user, qbit_pass, category, tag, upgrade_missing):
    """
    Sync torrent instances from qBittorrent and map to payloads.

    Connects to qBittorrent (read-only), retrieves torrent list, maps torrents
    to on-disk payload roots, computes payload hashes, and updates the database.

    This command is idempotent and can be run multiple times.
    """
    from hashall.model import connect_db
    from hashall.qbittorrent import get_qbittorrent_client
    from hashall.payload import (
        build_payload, upsert_payload, upsert_torrent_instance, TorrentInstance,
        upgrade_payload_missing_sha256
    )

    # Connect to database
    conn = connect_db(Path(db))

    # Connect to qBittorrent
    print("🔌 Connecting to qBittorrent...")
    qbit = get_qbittorrent_client(qbit_url, qbit_user, qbit_pass)

    if not qbit.test_connection():
        print("❌ Failed to connect to qBittorrent. Check URL and credentials.")
        print(f"   URL: {qbit.base_url}")
        print("   Hint: uses QBITTORRENT_API_URL and /mnt/config/secrets/qbittorrent/api.env")
        return

    if not qbit.login():
        print("❌ Failed to authenticate with qBittorrent.")
        return

    print("✅ Connected to qBittorrent")

    # Get torrents
    print("📥 Fetching torrents...")
    torrents = qbit.get_torrents(category=category, tag=tag)
    print(f"   Found {len(torrents)} torrents")

    # Process each torrent
    synced_count = 0
    incomplete_count = 0

    for torrent in torrents:
        print(f"\n🔄 Processing: {torrent.name[:50]}...")
        print(f"   Hash: {torrent.hash}")

        # Get torrent root path
        root_path = qbit.get_torrent_root_path(torrent)
        print(f"   Path: {root_path}")

        # Build payload from database
        payload = build_payload(conn, root_path, device_id=None)
        if payload.status != 'complete' and upgrade_missing:
            upgraded = upgrade_payload_missing_sha256(conn, root_path, device_id=payload.device_id)
            if upgraded > 0:
                payload = build_payload(conn, root_path, device_id=payload.device_id)

        # Insert/update payload
        payload_id = upsert_payload(conn, payload)

        # Insert/update torrent instance
        torrent_instance = TorrentInstance(
            torrent_hash=torrent.hash,
            payload_id=payload_id,
            device_id=None,  # Could be extracted from stat() if needed
            save_path=torrent.save_path,
            root_name=torrent.name,
            category=torrent.category,
            tags=torrent.tags,
            last_seen_at=time.time()
        )
        upsert_torrent_instance(conn, torrent_instance)

        if payload.status == 'complete':
            print(f"   ✅ Payload complete (hash: {payload.payload_hash[:16]}...)")
            print(f"      {payload.file_count} files, {payload.total_bytes:,} bytes")
            synced_count += 1
        else:
            print(f"   ⚠️  Payload incomplete (missing SHA256s)")
            incomplete_count += 1

    print(f"\n✅ Sync complete!")
    print(f"   {synced_count} complete payloads")
    print(f"   {incomplete_count} incomplete payloads")


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

    conn = connect_db(Path(db))

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

    conn = connect_db(Path(db))

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
            table_name = f"files_{device_id}"

            # Check if table exists
            table_exists = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """, (table_name,)).fetchone()

            if table_exists:
                result = conn.execute(f"""
                    SELECT COUNT(*) as count
                    FROM {table_name}
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
            table_name = f"files_{device_id}"

            # Check if table exists
            table_exists = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """, (table_name,)).fetchone()

            if table_exists:
                # Detect available columns (sha256 may not exist yet)
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
                has_sha256_col = "sha256" in columns

                # Get hash coverage for this device
                if has_sha256_col:
                    result = conn.execute(f"""
                        SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN quick_hash IS NOT NULL THEN 1 ELSE 0 END) as has_quick,
                            SUM(CASE WHEN sha1 IS NOT NULL THEN 1 ELSE 0 END) as has_sha1,
                            SUM(CASE WHEN sha256 IS NOT NULL THEN 1 ELSE 0 END) as has_sha256
                        FROM {table_name}
                        WHERE status = 'active'
                    """).fetchone()
                else:
                    result = conn.execute(f"""
                        SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN quick_hash IS NOT NULL THEN 1 ELSE 0 END) as has_quick,
                            SUM(CASE WHEN sha1 IS NOT NULL THEN 1 ELSE 0 END) as has_sha1
                        FROM {table_name}
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
                            FROM {table_name}
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

        plan = create_plan(conn, name, device_id, min_size=min_size)

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

            click.echo(f"🧰 Perm fix: group={root_group} ({root_gid})")
            summary, written = fix_permissions(
                sorted(path_set, key=lambda p: str(p)),
                root_gid,
                root_uid,
                fix_owner_root=True,
                fix_acl=fix_acl,
                use_sudo=True,
                log_path=log_path,
                root_label=str(root_path),
            )
            click.echo(f"   Checked: {summary.checked:,} Changed: {summary.changed:,} Failed: {summary.failed:,}")
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
        return 0 if result.actions_failed == 0 else 1

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
    table_name = f"files_{device_id}"
    deleted_count = 0
    try:
        cursor.execute(f"""
            SELECT COUNT(*) FROM {table_name} WHERE status = 'deleted'
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


if __name__ == "__main__":
    cli()
