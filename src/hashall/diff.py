# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/diff.py
# Based on working version from: 2025-06-25 16:10
# ✅ Corrected import of DiffReport

from hashall.model import DiffReport, DiffReportEntry
from pathlib import Path


def diff_sessions(src_files, dest_files):
    """
    Diff two in-memory file maps.

    Input format:
        {path: {"hash": str, "inode": int, "device_id": int}}

    Returns:
        {"added": [...], "removed": [...], "changed": [...]}
    """
    src_paths = set(src_files.keys())
    dest_paths = set(dest_files.keys())

    src_inode_keys = {
        (meta.get("device_id"), meta.get("inode"))
        for meta in src_files.values()
        if meta.get("device_id") is not None and meta.get("inode") is not None
    }
    dest_inode_keys = {
        (meta.get("device_id"), meta.get("inode"))
        for meta in dest_files.values()
        if meta.get("device_id") is not None and meta.get("inode") is not None
    }

    added = []
    for path in sorted(dest_paths - src_paths):
        meta = dest_files.get(path, {})
        inode_key = (meta.get("device_id"), meta.get("inode"))
        if inode_key in src_inode_keys:
            continue  # hardlink equivalence
        added.append(path)

    removed = []
    for path in sorted(src_paths - dest_paths):
        meta = src_files.get(path, {})
        inode_key = (meta.get("device_id"), meta.get("inode"))
        if inode_key in dest_inode_keys:
            continue  # hardlink equivalence
        removed.append(path)

    changed = []
    for path in sorted(src_paths & dest_paths):
        src = src_files.get(path, {})
        dest = dest_files.get(path, {})
        if src.get("hash") != dest.get("hash"):
            changed.append(path)
            continue
        if src.get("device_id") != dest.get("device_id"):
            changed.append(path)

    return {"added": added, "removed": removed, "changed": changed}

def diff_scan_sessions(conn, src_session_id, dst_session_id):
    """Diffs two scan sessions and returns report object."""
    cursor = conn.cursor()

    def table_exists(name: str) -> bool:
        row = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def load_from_legacy_files(session_id: int):
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(files)").fetchall()}
        has_inode = "inode" in columns
        has_device_id = "device_id" in columns

        select_cols = ["path"]
        if "sha256" in columns:
            select_cols.append("sha256")
            select_cols.append("sha1")
        else:
            select_cols.append("sha1")
        if has_inode:
            select_cols.append("inode")
        if has_device_id:
            select_cols.append("device_id")

        rows = cursor.execute(
            f"SELECT {', '.join(select_cols)} FROM files WHERE scan_session_id = ?",
            (session_id,),
        ).fetchall()

        files = {}
        for row in rows:
            path = row[0]
            if "sha256" in columns:
                file_hash = row[1] or row[2]
                inode_idx = 3
            else:
                file_hash = row[1]
                inode_idx = 2
            inode = row[inode_idx] if has_inode else None
            if has_inode and has_device_id:
                device_id = row[inode_idx + 1]
            else:
                device_id = row[inode_idx] if has_device_id else None
            files[path] = {"hash": file_hash, "inode": inode, "device_id": device_id}
        return files

    def load_from_device_table(session_id: int):
        session = cursor.execute(
            "SELECT device_id, root_path FROM scan_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            return {}

        device_id = session[0]
        root_path = Path(session[1])

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
            return {}
        try:
            rel_root = root_path.relative_to(mount_point)
        except ValueError:
            return {}

        rel_root_str = str(rel_root)
        table_name = f"files_{device_id}"
        if not table_exists(table_name):
            return {}

        if rel_root_str == ".":
            rows = cursor.execute(
                f"""
                SELECT path, sha256, sha1, inode
                FROM {table_name}
                WHERE status = 'active'
                """
            ).fetchall()
        else:
            rows = cursor.execute(
                f"""
                SELECT path, sha256, sha1, inode
                FROM {table_name}
                WHERE status = 'active' AND (path = ? OR path LIKE ?)
                """,
                (rel_root_str, f"{rel_root_str}/%"),
            ).fetchall()

        files = {}
        for row in rows:
            path = row[0]
            if path == rel_root_str:
                rel_path = Path(path).name
            elif path.startswith(rel_root_str + "/"):
                rel_path = path[len(rel_root_str) + 1:]
            else:
                rel_path = path
            display_path = "/" + rel_path.lstrip("/")
            file_hash = row[1] or row[2]
            files[display_path] = {"hash": file_hash, "inode": row[3], "device_id": device_id}
        return files

    if table_exists("files"):
        src_files = load_from_legacy_files(src_session_id)
        dest_files = load_from_legacy_files(dst_session_id)
    else:
        src_files = load_from_device_table(src_session_id)
        dest_files = load_from_device_table(dst_session_id)

    diff = diff_sessions(src_files, dest_files)
    entries = []
    for path in diff["added"]:
        entries.append(DiffReportEntry(path=path, status="added"))
    for path in diff["removed"]:
        entries.append(DiffReportEntry(path=path, status="removed"))
    for path in diff["changed"]:
        entries.append(DiffReportEntry(path=path, status="changed"))

    return DiffReport(entries=entries)
