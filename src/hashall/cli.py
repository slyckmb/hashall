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


if __name__ == "__main__":
    cli()
