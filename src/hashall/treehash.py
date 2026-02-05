# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
from hashlib import sha256

def compute_treehash(scan_id: str, db_path: str, commit: bool = False) -> str:
    """
    Computes a SHA256-based treehash representing the file structure of a scan session.

    Args:
        scan_id (str): The scan session UUID.
        db_path (str): Path to the SQLite database.
        commit (bool): If True, updates the scan_sessions.treehash field.

    Returns:
        str: Computed treehash value.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
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
