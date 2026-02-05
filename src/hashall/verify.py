# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
from rich.console import Console

console = Console()

def verify_paths(
    conn,
    src_root,
    dst_root,
    repair=False,
    dry_run=True,
    rsync_source=None,
    src_session_id=None,
    dst_session_id=None
):
    console.rule("[🔍] Diffing Files")

    cursor = conn.cursor()
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(files)").fetchall()}
    if "sha256" in columns:
        select_cols = "path, size, mtime, sha256, sha1"
    else:
        select_cols = "path, size, mtime, sha1"

    src_rows = cursor.execute(
        f"SELECT {select_cols} FROM files WHERE scan_session_id = ?",
        (src_session_id,)
    ).fetchall()
    dst_rows = cursor.execute(
        f"SELECT {select_cols} FROM files WHERE scan_session_id = ?",
        (dst_session_id,)
    ).fetchall()

    def extract_hash(row):
        if "sha256" in columns:
            return row["sha256"] or row["sha1"]
        return row["sha1"]

    src_map = {r["path"]: {**r, "file_hash": extract_hash(r)} for r in src_rows}
    dst_map = {r["path"]: {**r, "file_hash": extract_hash(r)} for r in dst_rows}

    all_paths = sorted(set(src_map) | set(dst_map))
    mismatches = []

    for path in all_paths:
        src = src_map.get(path)
        dst = dst_map.get(path)

        if src and not dst:
            mismatches.append((path, "missing"))
        elif dst and not src:
            mismatches.append((path, "unexpected"))
        elif src and dst:
            if src["file_hash"] != dst["file_hash"] or src["size"] != dst["size"] or int(src["mtime"]) != int(dst["mtime"]):
                mismatches.append((path, "changed"))

    for path, status in mismatches:
        console.print(f"❌ {status.upper()}: {path}")

    if not mismatches:
        console.print("✅ All files match.")
