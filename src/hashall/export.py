# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
from pathlib import Path
import orjson
import sqlite3

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
        cursor = conn.execute(
            "SELECT id, scan_id, root_path, device_id FROM scan_sessions WHERE root_path = ? ORDER BY started_at DESC LIMIT 1",
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
    else:
        cursor = conn.execute(
            "SELECT id, scan_id, root_path, device_id FROM scan_sessions ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        scan_session_id = row["id"]
        scan_id = row["scan_id"]
        session_root = Path(row["root_path"])
        session_device_id = row["device_id"] if "device_id" in row.keys() else None

    files_data = []

    # Prefer per-device tables when available
    if session_device_id is not None and _table_exists(f"files_{session_device_id}"):
        table_name = f"files_{session_device_id}"

        mount_point = None
        if _table_exists("devices"):
            device_row = conn.execute(
                "SELECT mount_point FROM devices WHERE device_id = ?",
                (session_device_id,),
            ).fetchone()
            if device_row:
                mount_point = Path(device_row["mount_point"])

        if mount_point is None:
            mount_point = session_root

        try:
            rel_root = session_root.resolve().relative_to(mount_point)
        except ValueError:
            rel_root = Path(".")

        rel_root_str = str(rel_root)
        if rel_root_str == ".":
            rows = conn.execute(
                f"SELECT path, size, mtime, sha1, inode FROM {table_name} WHERE status = 'active'"
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT path, size, mtime, sha1, inode
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
                "inode": row["inode"],
                "device_id": session_device_id,
            })

    elif _table_exists("files"):
        # Legacy session-based table
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(files)")}
        select_cols = ["path", "size", "mtime", "sha1"]
        if "inode" in columns:
            select_cols.append("inode")
        if "device_id" in columns:
            select_cols.append("device_id")

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
