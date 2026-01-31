-- Unified Hashall Schema

CREATE TABLE IF NOT EXISTS scan_sessions (
    id INTEGER PRIMARY KEY,
    scan_id TEXT UNIQUE NOT NULL,
    root_path TEXT NOT NULL,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    treehash TEXT
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha1 TEXT,
    scan_session_id INTEGER,
    inode INTEGER,
    device_id INTEGER,
    PRIMARY KEY (path, scan_session_id),
    FOREIGN KEY (scan_session_id) REFERENCES scan_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_files_scan_session ON files(scan_session_id);
CREATE INDEX IF NOT EXISTS idx_files_inode_device ON files(inode, device_id);
