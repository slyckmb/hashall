# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/cli.py
# ✅ Minimal fix: Added --no-export, fixed missing arg to verify_trees

import click
import time
from pathlib import Path
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify_trees import verify_trees
from hashall import __version__

DEFAULT_DB_PATH = Path.home() / ".hashall" / "hashall.sqlite3"

@click.group()
@click.version_option(__version__)
def cli():
    """Hashall — file hashing, verification, and migration tools"""
    pass

@cli.command("scan")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--parallel", is_flag=True, help="Use thread pool to hash faster.")
@click.option("--workers", type=int, default=None, help="Worker count for parallel scan (default: cpu_count).")
@click.option("--batch-size", type=int, default=None, help="Batch size for parallel DB writes.")
def scan_cmd(path, db, parallel, workers, batch_size):
    """Scan a directory and store file metadata in SQLite."""
    scan_path(db_path=Path(db), root_path=Path(path), parallel=parallel,
              workers=workers, batch_size=batch_size)

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
    """Verify that DST matches SRC, using SHA1 & smart scanning"""
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
@click.option("--qbit-url", default=None, help="qBittorrent URL (default: http://localhost:8080)")
@click.option("--qbit-user", default=None, help="qBittorrent username (default: admin)")
@click.option("--qbit-pass", default=None, help="qBittorrent password")
@click.option("--category", default=None, help="Filter torrents by category")
@click.option("--tag", default=None, help="Filter torrents by tag")
def payload_sync(db, qbit_url, qbit_user, qbit_pass, category, tag):
    """
    Sync torrent instances from qBittorrent and map to payloads.

    Connects to qBittorrent (read-only), retrieves torrent list, maps torrents
    to on-disk payload roots, computes payload hashes, and updates the database.

    This command is idempotent and can be run multiple times.
    """
    from hashall.model import connect_db
    from hashall.qbittorrent import get_qbittorrent_client
    from hashall.payload import (
        build_payload, upsert_payload, upsert_torrent_instance, TorrentInstance
    )

    # Connect to database
    conn = connect_db(Path(db))

    # Connect to qBittorrent
    print("🔌 Connecting to qBittorrent...")
    qbit = get_qbittorrent_client(qbit_url, qbit_user, qbit_pass)

    if not qbit.test_connection():
        print("❌ Failed to connect to qBittorrent. Check URL and credentials.")
        print(f"   URL: {qbit.base_url}")
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
            print(f"   ⚠️  Payload incomplete (missing SHA1s)")
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
        print(f"   Hash: (incomplete - missing SHA1s)")

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
def stats_cmd(db):
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
            total_files,
            total_bytes
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

            total_active_files += files
            total_bytes += bytes_val

            print(f"    {alias:15} ({device_id}): {files:,} files, {format_size(bytes_val)}")

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

    print("  Scan History:")
    if last_scan:
        # Get device alias for the last scan
        device = conn.execute("""
            SELECT device_alias
            FROM devices
            WHERE fs_uuid = ?
        """, (last_scan['fs_uuid'],)).fetchone()

        device_name = device['device_alias'] if device else 'unknown'

        # Format timestamp (remove microseconds if present)
        timestamp = last_scan['completed_at']
        if timestamp and '.' in timestamp:
            timestamp = timestamp.split('.')[0]

        print(f"    Last Scan: {timestamp} ({device_name})")
        print(f"    Total Scans: {total_scans['count'] if total_scans else 0}")
    else:
        print("    (No completed scans yet)")

    conn.close()


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
        mount_point = device[3] or "(none)"
        fs_type = device[4] or "(none)"
        files = format_count(device[5])
        size = format_size(device[6])

        rows.append([alias, uuid_short, device_id, mount_point, fs_type, files, size])

    # Calculate column widths
    headers = ["Alias", "UUID (first 8)", "Device ID", "Mount Point", "Type", "Files", "Size"]
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
        SELECT fs_uuid, device_id, device_alias, mount_point, fs_type,
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
                SELECT fs_uuid, device_id, device_alias, mount_point, fs_type,
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
    (fs_uuid, device_id, device_alias, mount_point, fs_type,
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
    print(f"  Mount Point: {mount_point}")
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


if __name__ == "__main__":
    cli()
