#!/usr/bin/env python3

# clean_missing_paths.py
import os
import sqlite3
from pathlib import Path

def clean_missing(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id, path FROM file_hashes")
    all_rows = cur.fetchall()

    removed = 0
    for file_id, path in all_rows:
        if not os.path.exists(path):
            cur.execute("DELETE FROM file_hashes WHERE id = ?", (file_id,))
            removed += 1

    conn.commit()
    conn.close()
    print(f"✅ Removed {removed} missing entries from the DB.")

if __name__ == "__main__":
    db_path = str(Path.home() / ".filehash.db")
    clean_missing(db_path)
