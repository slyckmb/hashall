-- Migration 0007: Incremental Scanning with Filesystem UUIDs
-- Date: 2026-02-01
-- Description: Clean break migration from session-based to incremental scanning
--              Introduces per-device tables, filesystem UUID tracking, and scoped deletion detection
--              See: /home/michael/dev/work/hashall/out/priority-0-revised-with-filesystem-uuids.md

-- DESTRUCTIVE MIGRATION WARNING:
-- This migration drops the old 'files' and 'scan_sessions' tables.
-- All existing scan data will be lost. Payload tables are preserved.
-- A backup is recommended before running this migration.

-- ============================================================================
-- Step 1: Drop old tables and indexes
-- ============================================================================

-- Drop old scan_sessions table (session-based model)
DROP TABLE IF EXISTS scan_sessions;

-- Drop old files table (single table for all devices)
DROP TABLE IF EXISTS files;

-- Drop old indexes if they exist
DROP INDEX IF EXISTS idx_files_scan_session;
DROP INDEX IF EXISTS idx_files_sha1;
DROP INDEX IF EXISTS idx_files_mtime;

-- ============================================================================
-- Step 2: Create devices table (Device Registry)
-- ============================================================================

-- Tracks all filesystems/devices that have been scanned
-- Uses filesystem UUID for persistent identity across reboots
-- Tracks current device_id for hardlink detection
CREATE TABLE devices (
    -- Identity (persistent)
    fs_uuid TEXT PRIMARY KEY,              -- Persistent filesystem UUID (from findmnt, ZFS GUID, etc.)

    -- Identity (transient - can change across reboots)
    device_id INTEGER NOT NULL UNIQUE,     -- Current st_dev value from os.stat()

    -- User-friendly naming
    device_alias TEXT UNIQUE,              -- User-friendly name (e.g., "pool", "stash")

    -- Mount information
    mount_point TEXT NOT NULL,             -- Current mount point (can change)
    fs_type TEXT,                          -- Filesystem type (zfs, ext4, btrfs, etc.)

    -- ZFS-specific metadata (if applicable)
    zfs_pool_name TEXT,                    -- ZFS pool name (e.g., "pool", "stash")
    zfs_dataset_name TEXT,                 -- ZFS dataset name (e.g., "pool/torrents")
    zfs_pool_guid TEXT,                    -- ZFS pool GUID

    -- Statistics
    first_scanned_at TEXT,                 -- Timestamp of first scan
    last_scanned_at TEXT,                  -- Timestamp of most recent scan
    scan_count INTEGER DEFAULT 0,          -- Number of times this device has been scanned
    total_files INTEGER DEFAULT 0,         -- Total active files on this device
    total_bytes INTEGER DEFAULT 0,         -- Total bytes of active files

    -- Tracking device_id changes
    device_id_history TEXT,                -- JSON array of historical device_ids with timestamps

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for device lookup
CREATE UNIQUE INDEX idx_devices_device_id ON devices(device_id);
CREATE UNIQUE INDEX idx_devices_alias ON devices(device_alias);
CREATE INDEX idx_devices_mount ON devices(mount_point);

-- ============================================================================
-- Step 3: Create new scan_sessions table (Audit Trail)
-- ============================================================================

-- Tracks each individual scan operation
-- Links to devices via fs_uuid for persistence
CREATE TABLE scan_sessions (
    id INTEGER PRIMARY KEY,
    scan_id TEXT UNIQUE NOT NULL,          -- UUID for this scan

    -- Device identification
    fs_uuid TEXT NOT NULL,                 -- Which filesystem was scanned
    device_id INTEGER NOT NULL,            -- Device ID at time of scan (for reference)
    root_path TEXT NOT NULL,               -- Specific path that was scanned

    -- Timing
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    duration_seconds REAL,

    -- Status
    status TEXT DEFAULT 'running',         -- 'running', 'completed', 'failed', 'interrupted'

    -- Statistics (incremental scan metrics)
    files_scanned INTEGER DEFAULT 0,       -- Total files processed
    files_added INTEGER DEFAULT 0,         -- New files added to catalog
    files_updated INTEGER DEFAULT 0,       -- Existing files that were updated (mtime changed)
    files_unchanged INTEGER DEFAULT 0,     -- Existing files that were skipped (no change)
    files_deleted INTEGER DEFAULT 0,       -- Files marked as deleted
    bytes_hashed INTEGER DEFAULT 0,        -- Total bytes that were hashed (new + updated)

    -- Settings
    parallel BOOLEAN DEFAULT 0,            -- Whether parallel mode was used
    workers INTEGER,                       -- Number of worker processes (if parallel)

    FOREIGN KEY (fs_uuid) REFERENCES devices(fs_uuid)
);

-- Indexes for scan session queries
CREATE INDEX idx_scan_sessions_fs_uuid ON scan_sessions(fs_uuid);
CREATE INDEX idx_scan_sessions_completed ON scan_sessions(completed_at);
CREATE INDEX idx_scan_sessions_status ON scan_sessions(status);

-- ============================================================================
-- Step 4: Create scan_roots table (Track Scanned Root Paths)
-- ============================================================================

-- Tracks which specific root paths have been scanned on each device
-- Critical for scoped deletion detection:
--   - Only mark files as deleted if they're under a previously scanned root
--   - Prevents false deletions for areas that haven't been scanned yet
CREATE TABLE scan_roots (
    fs_uuid TEXT NOT NULL,                 -- Which filesystem
    root_path TEXT NOT NULL,               -- Canonical path that was scanned
    last_scanned_at TEXT,                  -- When this root was last scanned
    scan_count INTEGER DEFAULT 0,          -- Number of times this root has been scanned

    PRIMARY KEY (fs_uuid, root_path),
    FOREIGN KEY (fs_uuid) REFERENCES devices(fs_uuid)
);

-- Index for lookup by filesystem
CREATE INDEX idx_scan_roots_fs_uuid ON scan_roots(fs_uuid);

-- ============================================================================
-- Step 5: Files tables (Per-Device)
-- ============================================================================

-- NOTE: files_{device_id} tables are created DYNAMICALLY during scan operations.
-- They are NOT created by this migration script.
--
-- Each device gets its own table named: files_{device_id}
-- Examples: files_49, files_50, files_51
--
-- This design allows:
--   1. Efficient per-device queries
--   2. Natural isolation of different filesystems
--   3. Matches kernel's (device_id, inode) tuple for hardlink detection
--   4. Automatic handling when device_id changes (table rename)
--
-- Template schema for reference (created by scan logic):
--
-- CREATE TABLE files_{device_id} (
--     path TEXT PRIMARY KEY,                 -- Relative to device mount_point
--     size INTEGER NOT NULL,
--     mtime REAL NOT NULL,
--     sha1 TEXT NOT NULL,
--     inode INTEGER NOT NULL,
--
--     -- Tracking
--     first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
--     last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
--     last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
--
--     -- Status
--     status TEXT DEFAULT 'active',          -- 'active', 'deleted', 'moved'
--
--     -- Optional: track which scan root discovered this file
--     discovered_under TEXT                  -- e.g., '/pool/torrents', '/stash/media'
-- );
--
-- CREATE INDEX idx_files_{device_id}_sha1 ON files_{device_id}(sha1);
-- CREATE INDEX idx_files_{device_id}_inode ON files_{device_id}(inode);
-- CREATE INDEX idx_files_{device_id}_mtime ON files_{device_id}(mtime);
-- CREATE INDEX idx_files_{device_id}_status ON files_{device_id}(status);

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- The database is now ready for incremental scanning with filesystem UUID tracking.
-- Next steps:
--   1. Run: hashall scan /pool (or your first scan path)
--   2. The scan logic will:
--      - Detect the filesystem UUID
--      - Register the device in the 'devices' table
--      - Create the files_{device_id} table dynamically
--      - Perform the initial scan
--   3. Subsequent scans will be incremental (skip unchanged files)
--   4. Use: hashall devices list (to view registered devices)
--   5. Use: hashall stats (to view overall statistics)
