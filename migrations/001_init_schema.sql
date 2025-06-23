-- Migration 001: Initial schema and version table

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_path TEXT NOT NULL,
    rel_path TEXT,
    size INTEGER,
    mtime REAL,
    inode INTEGER,
    uid INTEGER,
    gid INTEGER,
    partial_sha1 TEXT,
    sha1 TEXT,
    scan_id TEXT
);

CREATE TABLE IF NOT EXISTS scan_session (
    scan_id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    mode TEXT NOT NULL,
    workers INTEGER,
    host TEXT,
    user TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version (version) VALUES (1);
