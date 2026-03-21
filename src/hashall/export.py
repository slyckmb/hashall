# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
from pathlib import Path
import orjson
import sqlite3

from hashall.device import get_files_table_name, resolve_current_device_row

def export_json(db_path: Path, root_path: Path = None, out_path: Path = None):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    def _table_exists(name: str) -> bool:
        return conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None

    def _scan_session_columns():
        return {row["name"] for row in conn.execute("PRAGMA table_info(scan_sessions)")}

    if root_path:
        fs_uuid_expr = "fs_uuid" if "fs_uuid" in _scan_session_columns() else "NULL AS fs_uuid"
        cursor = conn.execute(
            f"SELECT id, scan_id, root_path, device_id, {fs_uuid_expr} FROM scan_sessions WHERE root_path = ? ORDER BY started_at DESC LIMIT 1",
            (str(root_path),),
        )
        row = cursor.fetchone()
        if not row:
            print(f"❌ No scan session found for: {root_path}")
            return
        scan_session_id = row["id"]
        scan_id = row["scan_id"]
        session_root = Path(row["root_path"])
        session_device_id = row["device_id"] if "device_id" in row.keys() else None
        session_fs_uuid = row["fs_uuid"] if "fs_uuid" in row.keys() else None
    else:
        fs_uuid_expr = "fs_uuid" if "fs_uuid" in _scan_session_columns() else "NULL AS fs_uuid"
        cursor = conn.execute(
            f"SELECT id, scan_id, root_path, device_id, {fs_uuid_expr} FROM scan_sessions ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        scan_session_id = row["id"]
        scan_id = row["scan_id"]
        session_root = Path(row["root_path"])
        session_device_id = row["device_id"] if "device_id" in row.keys() else None
        session_fs_uuid = row["fs_uuid"] if "fs_uuid" in row.keys() else None

    files_data = []

    # Prefer per-device tables when available
    table_name = None
    device_row = None
    if session_fs_uuid is not None or session_device_id is not None:
        device_row = resolve_current_device_row(
            conn.cursor(),
            fs_uuid=session_fs_uuid,
            device_id=int(session_device_id) if session_device_id is not None else None,
        )
    current_device_id = None
    if device_row is not None:
        current_device_id = int(device_row[0])
        table_name = get_files_table_name(
            conn.cursor(),
            fs_uuid=device_row[1],
            device_id=current_device_id,
        )
    elif session_device_id is not None:
        table_name = get_files_table_name(conn.cursor(), device_id=int(session_device_id))

    if table_name is not None and _table_exists(table_name):

        mount_point = None
        if device_row is not None:
            mount_point = Path(str(device_row[4] or device_row[3]))
        elif _table_exists("devices") and session_device_id is not None:
            legacy_device_row = conn.execute(
                "SELECT mount_point FROM devices WHERE device_id = ?",
                (session_device_id,),
            ).fetchone()
            if legacy_device_row:
                mount_point = Path(legacy_device_row["mount_point"])

        if mount_point is None:
            mount_point = session_root

        try:
            rel_root = session_root.resolve().relative_to(mount_point)
        except ValueError:
            rel_root = Path(".")

        rel_root_str = str(rel_root)
        if rel_root_str == ".":
            rows = conn.execute(
                f"SELECT path, size, mtime, sha1, sha256, inode FROM {table_name} WHERE status = 'active'"
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT path, size, mtime, sha1, sha256, inode
                FROM {table_name}
                WHERE status = 'active' AND (path = ? OR path LIKE ?)
                """,
                (rel_root_str, f"{rel_root_str}/%"),
            ).fetchall()

        for row in rows:
            path = row["path"]
            if rel_root_str == ".":
                export_path = path
            elif path.startswith(rel_root_str + "/"):
                export_path = path[len(rel_root_str) + 1:]
            elif path == rel_root_str:
                export_path = Path(path).name
            else:
                export_path = path

            files_data.append({
                "path": export_path,
                "size": row["size"],
                "mtime": row["mtime"],
                "sha1": row["sha1"],
                "sha256": row["sha256"],
                "inode": row["inode"],
                "device_id": current_device_id if current_device_id is not None else session_device_id,
            })

    elif _table_exists("files"):
        # Legacy session-based table
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(files)")}
        select_cols = ["path", "size", "mtime", "sha1"]
        if "inode" in columns:
            select_cols.append("inode")
        if "device_id" in columns:
            select_cols.append("device_id")
        if "sha256" in columns:
            select_cols.append("sha256")

        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM files WHERE scan_session_id = ?",
            (scan_session_id,),
        ).fetchall()

        for row in rows:
            row_dict = dict(row)
            if "inode" not in row_dict:
                row_dict["inode"] = None
            if "device_id" not in row_dict:
                row_dict["device_id"] = None
            if "sha256" not in row_dict:
                row_dict["sha256"] = None
            files_data.append(row_dict)

    data = {
        "scan_id": scan_id,
        "root_path": str(root_path) if root_path else None,
        "files": files_data,
    }

    # Default export location: <root>/.hashall/hashall.json if root_path provided,
    # otherwise ~/.hashall/hashall.json for backward compatibility
    if out_path:
        out = Path(out_path)
    elif root_path:
        out = Path(root_path) / ".hashall" / "hashall.json"
    else:
        out = Path.home() / ".hashall" / "hashall.json"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
    print(f"✅ Exported {len(data['files'])} records to: {out}")
