# hashall schema

Source of truth: `schema.sql`.

## Tables

### scan_sessions

- `id` INTEGER PRIMARY KEY
- `scan_id` TEXT UNIQUE NOT NULL
- `root_path` TEXT NOT NULL
- `started_at` TEXT DEFAULT CURRENT_TIMESTAMP
- `treehash` TEXT

### files

- `path` TEXT NOT NULL
- `size` INTEGER NOT NULL
- `mtime` REAL NOT NULL
- `sha1` TEXT
- `scan_session_id` INTEGER

Primary key: `(path, scan_session_id)`

Foreign key: `scan_session_id -> scan_sessions(id)`

## Indexes

- `idx_files_scan_session` on `files(scan_session_id)`

