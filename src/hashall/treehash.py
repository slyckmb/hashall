# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
from hashlib import sha256
from pathlib import Path

def compute_treehash(scan_id: str, db_path: str, commit: bool = False) -> str:
    """
    Computes a SHA256-based treehash representing the file structure of a scan session.
    Supports both legacy (files) and unified (files_<device_id>) catalogs.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    def _table_exists(name: str) -> bool:
        return cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None

    rows = []

    if _table_exists("files"):
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(files)").fetchall()}
        if "sha256" in columns:
            hash_col = "COALESCE(f.sha256, f.sha1)"
        else:
            hash_col = "f.sha1"

        cursor.execute(f"""
            SELECT f.path, {hash_col}, f.size, f.mtime
            FROM files f
            JOIN scan_sessions s ON f.scan_session_id = s.id
            WHERE s.scan_id = ?
            ORDER BY f.path
        """, (scan_id,))
        rows = cursor.fetchall()

    else:
        session = cursor.execute(
            "SELECT id, device_id, root_path FROM scan_sessions WHERE scan_id = ?",
            (scan_id,),
        ).fetchone()
        if not session:
            conn.close()
            raise ValueError(f"Scan session not found: {scan_id}")

        device_id = session[1]
        root_path = Path(session[2])
        table_name = f"files_{device_id}"
        if not _table_exists(table_name):
            conn.close()
            raise ValueError(f"Missing device table: {table_name}")

        device_columns = {row[1] for row in cursor.execute("PRAGMA table_info(devices)").fetchall()}
        if "preferred_mount_point" in device_columns:
            device = cursor.execute(
                "SELECT mount_point, preferred_mount_point FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            mount_point = Path(device[1] or device[0]) if device else None
        else:
            device = cursor.execute(
                "SELECT mount_point FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            mount_point = Path(device[0]) if device else None

        if not mount_point:
            conn.close()
            raise ValueError("Device mount point not found for treehash")

        try:
            rel_root = root_path.relative_to(mount_point)
        except ValueError:
            rel_root = Path(".")

        rel_root_str = str(rel_root)
        columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if "sha256" in columns:
            select_cols = "path, COALESCE(sha256, sha1), size, mtime"
        else:
            select_cols = "path, sha1, size, mtime"

        if rel_root_str == ".":
            rows = cursor.execute(
                f"""
                SELECT {select_cols}
                FROM {table_name}
                WHERE status = 'active'
                ORDER BY path
                """
            ).fetchall()
        else:
            rows = cursor.execute(
                f"""
                SELECT {select_cols}
                FROM {table_name}
                WHERE status = 'active' AND (path = ? OR path LIKE ?)
                ORDER BY path
                """,
                (rel_root_str, f"{rel_root_str}/%"),
            ).fetchall()

            normalized_rows = []
            for row in rows:
                path = row[0]
                if path == rel_root_str:
                    rel_path = Path(path).name
                elif path.startswith(rel_root_str + "/"):
                    rel_path = path[len(rel_root_str) + 1:]
                else:
                    rel_path = path
                normalized_rows.append((rel_path, row[1], row[2], row[3]))
            rows = normalized_rows

    conn.close()

    treehash_input = "\n".join(
        f"{row[0]}|{row[1]}|{row[2]}|{row[3]}" for row in rows
    )
    treehash = sha256(treehash_input.encode()).hexdigest()

    if commit:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scan_sessions SET treehash = ? WHERE scan_id = ?",
            (treehash, scan_id)
        )
        conn.commit()
        conn.close()

    return treehash
