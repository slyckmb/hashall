# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/verify_trees.py
# ✅ Calls updated verify_paths with correct signature

from pathlib import Path
from rich.console import Console
from hashall.model import connect_db, load_json_scan_into_db
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify import verify_paths
from hashall.diff import diff_sessions

console = Console()

def _ensure_session_id(conn, scan_id: str, root_path: Path) -> int | None:
    if not scan_id:
        return None
    row = conn.execute(
        "SELECT id FROM scan_sessions WHERE scan_id = ?",
        (scan_id,),
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO scan_sessions (scan_id, root_path) VALUES (?, ?)",
        (scan_id, str(root_path)),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM scan_sessions WHERE scan_id = ?",
        (scan_id,),
    ).fetchone()["id"]

def _latest_session_id(conn, root_path: Path) -> int | None:
    row = conn.execute(
        "SELECT id FROM scan_sessions WHERE root_path = ? ORDER BY id DESC LIMIT 1",
        (str(root_path),),
    ).fetchone()
    return row["id"] if row else None

def verify_trees(
    src_root: Path,
    dst_root: Path,
    db_path: Path,
    repair: bool = False,
    dry_run: bool = True,
    rsync_source: Path = None,
    auto_export: bool = True,
):
    """Verify that destination matches source using SHA256 & smart scan fallback."""
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
        src_scan_id = load_json_scan_into_db(conn, str(src_json))
        src_session = _ensure_session_id(conn, src_scan_id, src_root)
    else:
        console.print(f"⚠️   No source export found, scanning `{src_root}`")
        scan_path(db_path=db_path, root_path=src_root)
        if auto_export:
            export_json(db_path=db_path, root_path=src_root)
        src_session = _latest_session_id(conn, src_root)

    if dst_json.exists():
        console.print(f"ℹ️   Loading scan JSON from destination: {dst_json}")
        dst_scan_id = load_json_scan_into_db(conn, str(dst_json))
        dst_session = _ensure_session_id(conn, dst_scan_id, dst_root)
    else:
        console.print(f"⚠️   No dest export found, scanning `{dst_root}`")
        scan_path(db_path=db_path, root_path=dst_root)
        if auto_export:
            export_json(db_path=db_path, root_path=dst_root)
        dst_session = _latest_session_id(conn, dst_root)

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


def compare_sessions(src_session, dest_session):
    """
    Compare two in-memory session objects with .files maps.

    Expected format:
        session.files = {path: {"hash": str, "inode": int, "device_id": int | None}}
    """
    return diff_sessions(src_session.files, dest_session.files)
