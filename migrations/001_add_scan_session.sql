-- Migration: Add scan_session table

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

-- Add columns to files table if not present
ALTER TABLE files ADD COLUMN scan_id TEXT;
ALTER TABLE files ADD COLUMN rel_path TEXT;
ALTER TABLE files ADD COLUMN sha1 TEXT;  -- ✅ Required for JSON export
