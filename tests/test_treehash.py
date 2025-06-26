# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import sqlite3
import tempfile
from src.hashall.treehash import compute_treehash

def test_compute_treehash_basic():
    # Setup in-memory DB copied to disk to allow re-open
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Create minimal schema
    cur.executescript("""
    CREATE TABLE scan_session (
        scan_id TEXT PRIMARY KEY,
        root_path TEXT,
        treehash TEXT
    );
    CREATE TABLE files (
        id INTEGER PRIMARY KEY,
        scan_id TEXT,
        rel_path TEXT,
        sha1 TEXT,
        size INTEGER,
        mtime REAL
    );
    """)

    # Insert mock data
    cur.execute("INSERT INTO scan_session (scan_id, root_path) VALUES (?, ?)", ("test123", "/mock/path"))
    cur.executemany("INSERT INTO files (scan_id, rel_path, sha1, size, mtime) VALUES (?, ?, ?, ?, ?)", [
        ("test123", "a.txt", "111aaa", 100, 1680000000),
        ("test123", "b.txt", "222bbb", 200, 1680000001),
    ])
    conn.commit()
    conn.close()

    # Run treehash
    result = compute_treehash("test123", db_path)
    print("Treehash:", result)
    assert isinstance(result, str)
    assert len(result) == 40  # SHA1

    # Test commit=True
    compute_treehash("test123", db_path, commit=True)
    conn = sqlite3.connect(db_path)
    treehash_in_db = conn.execute("SELECT treehash FROM scan_session WHERE scan_id = 'test123'").fetchone()[0]
    conn.close()

    assert result == treehash_in_db
    os.unlink(db_path)  # Cleanup
