-- schema.sql – baseline schema for hashall (v0.3.8-dev)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    abs_path TEXT NOT NULL,
    rel_path TEXT,
    size INTEGER,
    mtime REAL,
    inode INTEGER,
    uid INTEGER,
    gid INTEGER,
    partial_sha1 TEXT,
    sha1 TEXT,
    scan_id TEXT,
    FOREIGN KEY(scan_id) REFERENCES scan_session(scan_id)
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
