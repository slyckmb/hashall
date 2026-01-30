#!/usr/bin/env python3

# verify_full_hashes.py
import os
import sqlite3
import hashlib
from pathlib import Path
from time import time

def compute_full_sha1(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()
    except Exception:
        return None

def verify_duplicates(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Find partial duplicates that don't yet have full hashes
    cur.execute("""
        SELECT partial_sha1 FROM file_hashes
        WHERE full_sha1 IS NULL
        GROUP BY partial_sha1 HAVING COUNT(*) > 1
    """)
    partial_dupes = [row[0] for row in cur.fetchall()]

    for partial in partial_dupes:
        cur.execute("""
            SELECT id, path FROM file_hashes
            WHERE partial_sha1 = ? AND full_sha1 IS NULL
        """, (partial,))
        rows = cur.fetchall()

        for file_id, path in rows:
            full_sha = compute_full_sha1(path)
            if full_sha:
                cur.execute("""
                    UPDATE file_hashes SET full_sha1 = ?, scanned_at = ?
                    WHERE id = ?
                """, (full_sha, int(time()), file_id))

        conn.commit()

    conn.close()

if __name__ == "__main__":
    db_path = str(Path.home() / ".filehash.db")
    verify_duplicates(db_path)
