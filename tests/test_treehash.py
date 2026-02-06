# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import sqlite3
import tempfile
from hashall.treehash import compute_treehash

def test_compute_treehash_basic():
    # Setup in-memory DB copied to disk to allow re-open
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Create minimal schema
    cur.executescript("""
    CREATE TABLE scan_sessions (
        id INTEGER PRIMARY KEY,
        scan_id TEXT UNIQUE,
        root_path TEXT,
        treehash TEXT
    );
    CREATE TABLE files (
        path TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        sha1 TEXT,
        sha256 TEXT,
        scan_session_id INTEGER
    );
    """)

    # Insert mock data
    cur.execute("INSERT INTO scan_sessions (scan_id, root_path) VALUES (?, ?)", ("test123", "/mock/path"))
    scan_session_id = cur.execute("SELECT id FROM scan_sessions WHERE scan_id = 'test123'").fetchone()[0]
    cur.executemany("INSERT INTO files (path, size, mtime, sha256, sha1, scan_session_id) VALUES (?, ?, ?, ?, ?, ?)", [
        ("/mock/path/a.txt", 100, 1680000000, "111aaa256", "111aaa", scan_session_id),
        ("/mock/path/b.txt", 200, 1680000001, "222bbb256", "222bbb", scan_session_id),
    ])
    conn.commit()
    conn.close()

    # Run treehash
    result = compute_treehash("test123", db_path)
    print("Treehash:", result)
    assert isinstance(result, str)
    assert len(result) == 64  # SHA256

    # Test commit=True
    compute_treehash("test123", db_path, commit=True)
    conn = sqlite3.connect(db_path)
    treehash_in_db = conn.execute("SELECT treehash FROM scan_sessions WHERE scan_id = 'test123'").fetchone()[0]
    conn.close()

    assert result == treehash_in_db
    os.unlink(db_path)  # Cleanup


def test_compute_treehash_unified_catalog():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE devices (
        device_id INTEGER PRIMARY KEY,
        mount_point TEXT NOT NULL,
        preferred_mount_point TEXT
    );
    CREATE TABLE scan_sessions (
        id INTEGER PRIMARY KEY,
        scan_id TEXT UNIQUE,
        root_path TEXT,
        device_id INTEGER,
        treehash TEXT
    );
    CREATE TABLE files_49 (
        path TEXT PRIMARY KEY,
        size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        sha1 TEXT,
        sha256 TEXT,
        status TEXT DEFAULT 'active'
    );
    """)

    cur.execute("INSERT INTO devices (device_id, mount_point, preferred_mount_point) VALUES (49, '/pool', '/pool')")
    cur.execute("INSERT INTO scan_sessions (scan_id, root_path, device_id) VALUES (?, ?, ?)", ("unified123", "/pool/data", 49))
    cur.executemany(
        "INSERT INTO files_49 (path, size, mtime, sha256, sha1, status) VALUES (?, ?, ?, ?, ?, 'active')",
        [
            ("data/a.txt", 100, 1680000000, "aaa256", "aaa1"),
            ("data/b.txt", 200, 1680000001, "bbb256", "bbb1"),
        ],
    )

    conn.commit()
    conn.close()

    result = compute_treehash("unified123", db_path)
    assert isinstance(result, str)
    assert len(result) == 64

    compute_treehash("unified123", db_path, commit=True)
    conn = sqlite3.connect(db_path)
    treehash_in_db = conn.execute("SELECT treehash FROM scan_sessions WHERE scan_id = 'unified123'").fetchone()[0]
    conn.close()
    assert result == treehash_in_db
    os.unlink(db_path)
