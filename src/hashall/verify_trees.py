# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/verify_trees.py
# ✅ Calls updated verify_paths with correct signature

from pathlib import Path
from rich.console import Console
from hashall.model import connect_db, load_json_scan_into_db
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify import verify_paths

console = Console()

def verify_trees(
    src_root: Path,
    dst_root: Path,
    db_path: Path,
    repair: bool = False,
    dry_run: bool = True,
    rsync_source: Path = None,
    auto_export: bool = True,
):
    """Verify that destination matches source using SHA1 & smart scan fallback."""
    console.rule("🌲 Hashall Tree Verification")
    console.print(f"📂 Source: {src_root}")
    console.print(f"📁 Destination: {dst_root}")
    console.print(f"📄 DB: {db_path}")
    console.print(f"🔧 Mode: {'dry-run' if dry_run else 'force'} — Repair: {'on' if repair else 'off'}")

    conn = connect_db(db_path)

    src_json = src_root / ".hashall" / "hashall.json"
    dst_json = dst_root / ".hashall" / "hashall.json"

    if src_json.exists():
        console.print(f"ℹ️   Loading scan JSON from source: {src_json}")
        src_session = load_json_scan_into_db(conn, str(src_json))
    else:
        console.print(f"⚠️   No source export found, scanning `{src_root}`")
        scan_path(db_path=db_path, root_path=src_root)
        if auto_export:
            export_json(db_path=db_path, root_path=src_root)
        src_session = None

    if dst_json.exists():
        console.print(f"ℹ️   Loading scan JSON from destination: {dst_json}")
        dst_session = load_json_scan_into_db(conn, str(dst_json))
    else:
        console.print(f"⚠️   No dest export found, scanning `{dst_root}`")
        scan_path(db_path=db_path, root_path=dst_root)
        if auto_export:
            export_json(db_path=db_path, root_path=dst_root)
        dst_session = None

    verify_paths(
        conn=conn,
        src_root=src_root,
        dst_root=dst_root,
        repair=repair,
        dry_run=dry_run,
        rsync_source=rsync_source,
        src_session_id=src_session,
        dst_session_id=dst_session,
    )
