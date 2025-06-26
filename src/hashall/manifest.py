# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
"""
manifest.py — Write rsync-compatible file lists from diff results
"""

from pathlib import Path
import sqlite3

def write_rsync_manifest(db_path: Path, scan_id_src: int, scan_id_dst: int, manifest_path: Path):
    """
    Generate a --files-from manifest for rsync based on differences between two scan sessions.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
    SELECT f1.relpath
    FROM files f1
    LEFT JOIN files f2
        ON f1.relpath = f2.relpath AND f2.scan_id = ?
    WHERE f1.scan_id = ?
      AND (f2.sha1 IS NULL OR f1.sha1 != f2.sha1)
    ORDER BY f1.relpath;
    """

    rows = cursor.execute(query, (scan_id_dst, scan_id_src)).fetchall()

    if not rows:
        print("✅ No mismatches found — no manifest needed.")
        return

    with open(manifest_path, "w") as f:
        for row in rows:
            f.write(f"{row[0]}\n")

    print(f"📄 Wrote rsync manifest: {manifest_path} ({len(rows)} files)")

    conn.close()
