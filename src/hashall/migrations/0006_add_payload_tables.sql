-- Add payload identity tables for Stage 2
-- Supports many-torrent-to-one-payload mapping
-- Compatible with existing session-based model, designed for future unified catalog migration

-- Payloads: unique content instances on disk
CREATE TABLE IF NOT EXISTS payloads (
    payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload_hash TEXT,                      -- SHA256 of sorted (path, size, sha256) tuples; NULL if incomplete
    device_id INTEGER,                      -- Physical device/filesystem ID
    root_path TEXT NOT NULL,                -- Canonical path relative to device mount (or absolute for now)
    file_count INTEGER NOT NULL DEFAULT 0,  -- Number of files in this payload
    total_bytes INTEGER NOT NULL DEFAULT 0, -- Total size of all files
    status TEXT NOT NULL DEFAULT 'incomplete',  -- 'complete' | 'incomplete'
    last_built_at REAL,                     -- Unix timestamp when payload_hash was last computed
    created_at REAL DEFAULT (julianday('now')),
    updated_at REAL DEFAULT (julianday('now'))
);

-- Index for lookups by payload_hash
CREATE INDEX IF NOT EXISTS idx_payloads_hash ON payloads(payload_hash);

-- Index for lookups by device and root_path
CREATE INDEX IF NOT EXISTS idx_payloads_device_root ON payloads(device_id, root_path);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_payloads_status ON payloads(status);

-- Torrent instances: maps torrent hashes to payloads
CREATE TABLE IF NOT EXISTS torrent_instances (
    torrent_hash TEXT PRIMARY KEY,          -- Infohash (v1 or v2)
    payload_id INTEGER NOT NULL,            -- Foreign key to payloads
    device_id INTEGER,                      -- Device where torrent is located
    save_path TEXT,                         -- qBittorrent save_path
    root_name TEXT,                         -- Root directory name for multi-file torrents
    category TEXT,                          -- qBittorrent category
    tags TEXT,                              -- Comma-separated tags
    last_seen_at REAL,                      -- Unix timestamp when last observed in qBittorrent
    created_at REAL DEFAULT (julianday('now')),
    updated_at REAL DEFAULT (julianday('now')),
    FOREIGN KEY (payload_id) REFERENCES payloads(payload_id) ON DELETE CASCADE
);

-- Index for lookups by payload_id (to find siblings)
CREATE INDEX IF NOT EXISTS idx_torrent_instances_payload ON torrent_instances(payload_id);

-- Index for lookups by device
CREATE INDEX IF NOT EXISTS idx_torrent_instances_device ON torrent_instances(device_id);

-- Index for category/tag filtering
CREATE INDEX IF NOT EXISTS idx_torrent_instances_category ON torrent_instances(category);
