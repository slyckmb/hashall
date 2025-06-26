# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import sqlite3
from hashlib import sha1

def compute_treehash(scan_id: str, db_path: str, commit: bool = False) -> str:
    """
    Computes a SHA1-based treehash representing the file structure of a scan session.
    
    Args:
        scan_id (str): The scan session ID.
        db_path (str): Path to the SQLite database.
        commit (bool): If True, updates the scan_session.treehash field.

    Returns:
        str: Computed treehash value.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rel_path, sha1, size, mtime
        FROM files
        WHERE scan_id = ?
        ORDER BY rel_path
    """, (scan_id,))
    rows = cursor.fetchall()
    conn.close()

    treehash_input = "\n".join(
        f"{row[0]}|{row[1]}|{row[2]}|{row[3]}" for row in rows
    )
    treehash = sha1(treehash_input.encode()).hexdigest()

    if commit:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE scan_session SET treehash = ? WHERE scan_id = ?",
            (treehash, scan_id)
        )
        conn.commit()
        conn.close()

    return treehash
