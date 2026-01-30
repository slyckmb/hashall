-- Legacy migration for adding scan_sessions and scan_session_id fields
-- Safe to skip if already exists

ALTER TABLE files ADD COLUMN scan_session_id INTEGER;

CREATE TABLE IF NOT EXISTS scan_sessions (
    id INTEGER PRIMARY KEY,
    scan_id TEXT UNIQUE NOT NULL,
    root_path TEXT NOT NULL,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    treehash TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_scan_session ON files(scan_session_id);
