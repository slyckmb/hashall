# Hashall Database Schema
**Model:** Unified Catalog with Incremental Scanning
**Version:** 0.5.0
**Last Updated:** 2026-02-01

Source of truth for current implementation: Check `src/hashall/migrations/0007_incremental_scanning.sql` for actual schema.

---

## Overview

The unified catalog uses a device-aware schema where files are stored in separate tables per device/filesystem. This reflects the natural boundary for hardlink operations and enables faster queries.

**Key principle:** One table per device = natural hardlink domain

---

## Core Tables

### `devices`

Registry of filesystems/mount points with persistent filesystem UUID tracking.

```sql
CREATE TABLE devices (
    -- Identity (persistent)
    fs_uuid TEXT PRIMARY KEY,                   -- Persistent filesystem UUID
                                                 -- Examples: "zfs-12345678", "a1b2c3d4-..."

    -- Identity (transient - can change across reboots)
    device_id INTEGER NOT NULL UNIQUE,          -- Current st_dev from stat()

    -- User-friendly naming
    device_alias TEXT UNIQUE,                   -- User-friendly name (e.g., "pool", "stash")

    -- Mount information
    mount_point TEXT NOT NULL,                  -- Current mount point (can change)
    fs_type TEXT,                               -- Filesystem type (zfs, ext4, btrfs, etc.)

    -- ZFS-specific metadata (if applicable)
    zfs_pool_name TEXT,                         -- ZFS pool name (e.g., "pool", "stash")
    zfs_dataset_name TEXT,                      -- ZFS dataset name (e.g., "pool/torrents")
    zfs_pool_guid TEXT,                         -- ZFS pool GUID

    -- Statistics
    first_scanned_at TEXT,                      -- Timestamp of first scan
    last_scanned_at TEXT,                       -- Timestamp of most recent scan
    scan_count INTEGER DEFAULT 0,               -- Number of times scanned
    total_files INTEGER DEFAULT 0,              -- Total active files
    total_bytes INTEGER DEFAULT 0,              -- Total bytes of active files

    -- Tracking device_id changes (for debugging)
    device_id_history TEXT,                     -- JSON array of historical device_ids

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_devices_device_id ON devices(device_id);
CREATE UNIQUE INDEX idx_devices_alias ON devices(device_alias);
CREATE INDEX idx_devices_mount ON devices(mount_point);
```

**Purpose:** Track which filesystems are cataloged with persistent identity

**Updated by:** `scan` command on each run

**Key features:**
- `fs_uuid` is the primary key (persistent across reboots)
- `device_id` can change after reboot (tracked in `device_id_history`)
- Auto-suggests `device_alias` based on path (e.g., "/pool" → "pool")
- ZFS metadata automatically extracted if available

---

### `scan_roots`

Tracks which specific root paths have been scanned on each device.

```sql
CREATE TABLE scan_roots (
    fs_uuid TEXT NOT NULL,                      -- Which filesystem
    root_path TEXT NOT NULL,                    -- Canonical path that was scanned
    last_scanned_at TEXT,                       -- When this root was last scanned
    scan_count INTEGER DEFAULT 0,               -- Number of times scanned

    PRIMARY KEY (fs_uuid, root_path),
    FOREIGN KEY (fs_uuid) REFERENCES devices(fs_uuid)
);

CREATE INDEX idx_scan_roots_fs_uuid ON scan_roots(fs_uuid);
```

**Purpose:** Track scanned root paths for scoped deletion detection

**Updated by:** `scan` command on each run

**Why this matters:**
- Prevents false deletions when scanning a subset of a filesystem
- Example: If you scan `/pool/torrents`, files under `/pool/media` won't be marked deleted
- Critical for safe partial rescans

**Query example:**
```sql
-- Show all scanned roots for a filesystem
SELECT root_path, last_scanned_at, scan_count
FROM scan_roots
WHERE fs_uuid = 'zfs-12345678'
ORDER BY last_scanned_at DESC;
```

---

## Per-Device File Tables

### `files_<device_id>`

One table per device. Created dynamically during first scan of each device.

**Example:** `files_49`, `files_50`, etc.

```sql
CREATE TABLE files_<device_id> (
    path TEXT PRIMARY KEY,                      -- Relative to mount_point
    size INTEGER NOT NULL,                      -- st_size (bytes)
    mtime REAL NOT NULL,                        -- st_mtime (modification time)
    sha1 TEXT NOT NULL,                         -- Hex digest (40 chars)
    inode INTEGER NOT NULL,                     -- st_ino

    -- Tracking
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,      -- When first discovered
    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,       -- When last seen in scan
    last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,   -- When metadata changed

    -- Status
    status TEXT DEFAULT 'active',               -- 'active', 'deleted', 'moved'

    -- Optional: track which scan root discovered this file
    discovered_under TEXT                       -- e.g., '/pool/torrents', '/stash/media'
);

CREATE INDEX idx_files_<device_id>_sha1 ON files_<device_id>(sha1);
CREATE INDEX idx_files_<device_id>_inode ON files_<device_id>(inode);
CREATE INDEX idx_files_<device_id>_status ON files_<device_id>(status);
```

**Purpose:** Store file metadata for incremental scanning

**Key fields:**
- `path` - Relative to mount point (not absolute)
- `size`, `mtime` - Used for change detection (if unchanged, skip rehashing)
- `sha1` - For content-based deduplication
- `inode` - For hardlink detection
- `first_seen_at` - When file was first discovered
- `last_seen_at` - Updated every scan (for staleness detection)
- `last_modified_at` - Updated when size/mtime changes
- `status` - Lifecycle: 'active' → 'deleted' (scoped to scan_roots)
- `discovered_under` - Tracks which scan root found this file first

**Updated by:** `scan` command (incremental updates)

**Incremental scan logic:**
1. Load existing files from DB
2. For each file on filesystem:
   - If size+mtime unchanged → UPDATE last_seen_at (skip hashing)
   - If size/mtime changed → REHASH and UPDATE
   - If new → INSERT
3. For each file in DB not seen → UPDATE status='deleted'

---

## Aggregated Metadata Tables

### `hardlink_groups`

Tracks inodes with multiple paths (hardlinked files within a device).

```sql
CREATE TABLE hardlink_groups (
    device_id INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    path_count INTEGER NOT NULL,                -- How many paths share this inode
    sha1 TEXT,                                   -- Content hash
    size INTEGER NOT NULL,                       -- File size
    canonical_path TEXT,                         -- "Primary" path (lexically first)
    last_updated REAL NOT NULL,                  -- Unix timestamp
    PRIMARY KEY (device_id, inode),
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX idx_hardlink_sha1 ON hardlink_groups(sha1);
CREATE INDEX idx_hardlink_size ON hardlink_groups(size);
```

**Purpose:** Quick lookup of existing hardlinks

**Updated by:** `scan` command after processing files

**Query example:**
```sql
-- Find all hardlink groups on device 49
SELECT * FROM hardlink_groups WHERE device_id = 49 AND path_count > 1;
```

---

### `duplicate_groups`

Tracks files with same SHA1 across devices (potential deduplication targets).

```sql
CREATE TABLE duplicate_groups (
    sha1 TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    instance_count INTEGER NOT NULL,             -- Total copies across all devices
    total_wasted_bytes INTEGER NOT NULL,         -- (instance_count - 1) * size
    device_count INTEGER NOT NULL,               -- How many devices have this file
    first_seen REAL NOT NULL,
    last_updated REAL NOT NULL
);

CREATE INDEX idx_duplicates_wasted ON duplicate_groups(total_wasted_bytes DESC);
CREATE INDEX idx_duplicates_size ON duplicate_groups(size DESC);
```

**Purpose:** Identify deduplication opportunities

**Updated by:** `scan` command after updating hardlink_groups

**Query example:**
```sql
-- Find biggest deduplication opportunities
SELECT * FROM duplicate_groups
ORDER BY total_wasted_bytes DESC
LIMIT 20;
```

---

## Link Tables

### `link_plans`

Deduplication plans created by link.

```sql
CREATE TABLE link_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    name TEXT,                                   -- User-friendly name
    description TEXT,
    source_devices TEXT NOT NULL,                -- JSON array of device_ids
    target_device INTEGER,                       -- NULL = across all devices
    total_opportunities INTEGER,
    total_bytes_saveable INTEGER,
    status TEXT DEFAULT 'pending',               -- 'pending', 'approved', 'executed', 'cancelled'
    executed_at REAL
);
```

**Purpose:** Store deduplication plans for review/execution

**Created by:** `hashall link plan` command

---

### `link_actions`

Individual actions within a plan.

```sql
CREATE TABLE link_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,                   -- 'HARDLINK', 'DELETE', 'MOVE', 'COPY_THEN_HARDLINK'
    sha1 TEXT NOT NULL,
    source_device INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    target_device INTEGER NOT NULL,
    target_path TEXT NOT NULL,
    bytes_to_save INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',               -- 'pending', 'executed', 'failed', 'skipped'
    executed_at REAL,
    error_message TEXT,
    FOREIGN KEY (plan_id) REFERENCES link_plans(id),
    FOREIGN KEY (source_device) REFERENCES devices(device_id),
    FOREIGN KEY (target_device) REFERENCES devices(device_id)
);

CREATE INDEX idx_actions_plan ON link_actions(plan_id);
CREATE INDEX idx_actions_status ON link_actions(status);
CREATE INDEX idx_actions_sha1 ON link_actions(sha1);
```

**Purpose:** Track execution of individual operations

**Created by:** `hashall link plan` command

**Updated by:** `hashall link execute` command

---

## Audit Trail

### `scan_sessions`

Audit trail of scan operations with incremental metrics.

```sql
CREATE TABLE scan_sessions (
    id INTEGER PRIMARY KEY,
    scan_id TEXT UNIQUE NOT NULL,               -- UUID for this scan

    -- Device identification
    fs_uuid TEXT NOT NULL,                      -- Which filesystem was scanned
    device_id INTEGER NOT NULL,                 -- Device ID at time of scan
    root_path TEXT NOT NULL,                    -- Specific path that was scanned

    -- Timing
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    duration_seconds REAL,

    -- Status
    status TEXT DEFAULT 'running',              -- 'running', 'completed', 'failed', 'interrupted'

    -- Statistics (incremental scan metrics)
    files_scanned INTEGER DEFAULT 0,            -- Total files processed
    files_added INTEGER DEFAULT 0,              -- New files added to catalog
    files_updated INTEGER DEFAULT 0,            -- Existing files updated (mtime changed)
    files_unchanged INTEGER DEFAULT 0,          -- Existing files skipped (no change)
    files_deleted INTEGER DEFAULT 0,            -- Files marked as deleted
    bytes_hashed INTEGER DEFAULT 0,             -- Total bytes hashed (new + updated)

    -- Settings
    parallel BOOLEAN DEFAULT 0,                 -- Whether parallel mode was used
    workers INTEGER,                            -- Number of worker processes

    FOREIGN KEY (fs_uuid) REFERENCES devices(fs_uuid)
);

CREATE INDEX idx_scan_sessions_fs_uuid ON scan_sessions(fs_uuid);
CREATE INDEX idx_scan_sessions_completed ON scan_sessions(completed_at);
CREATE INDEX idx_scan_sessions_status ON scan_sessions(status);
```

**Purpose:** Track scan activity for auditing and performance analysis

**Created by:** `scan` command (one record per scan)

**Key metrics:**
- `files_scanned` - Total files walked on filesystem
- `files_added` - New files inserted into catalog
- `files_updated` - Files rehashed due to size/mtime change
- `files_unchanged` - Files skipped (no rehashing needed)
- `files_deleted` - Files marked deleted (scoped to root_path)
- `bytes_hashed` - Only counts rehashed bytes (excludes unchanged)
- `parallel`, `workers` - Performance tuning settings used

**Query example:**
```sql
-- Show recent scan activity with incremental metrics
SELECT
    d.device_alias,
    s.root_path,
    datetime(s.started_at) as scan_time,
    s.files_added,
    s.files_updated,
    s.files_unchanged,
    s.files_deleted,
    s.duration_seconds,
    CASE WHEN s.parallel THEN s.workers || ' workers' ELSE 'sequential' END as mode
FROM scan_sessions s
JOIN devices d ON s.fs_uuid = d.fs_uuid
ORDER BY s.started_at DESC
LIMIT 10;
```

---

## Materialized Views

### `device_summary`

Quick summary statistics per device.

```sql
CREATE VIEW device_summary AS
SELECT
    d.device_id,
    d.mount_point,
    d.filesystem_type,
    d.total_files,
    d.total_size,
    d.last_scan_completed,
    COUNT(DISTINCT hg.inode) as hardlink_groups,
    SUM(CASE WHEN hg.path_count > 1 THEN hg.size * (hg.path_count - 1) ELSE 0 END) as space_saved_by_hardlinks
FROM devices d
LEFT JOIN hardlink_groups hg ON d.device_id = hg.device_id
GROUP BY d.device_id;
```

**Purpose:** Dashboard statistics

**Used by:** `hashall link status` command

---

## Design Rationale

### Why Device-Based Tables?

**Problem:** Hardlinks only work within a single filesystem/device.

**Solution:** One table per device naturally enforces this boundary.

**Benefits:**
1. **Faster queries** - No need to filter by device_id
2. **Clear isolation** - Can't accidentally hardlink across devices
3. **Natural scaling** - Each device table grows independently
4. **Easier reasoning** - All files in `files_49` are on same device

### Why Incremental Updates?

**Problem:** Session-based model accumulates data (3 scans = 3× data).

**Solution:** UPDATE existing records instead of INSERT new ones.

**Benefits:**
1. **Lean database** - One record per file (not per scan)
2. **Simple queries** - Always current state, no session filtering
3. **Change tracking** - `last_seen`, `first_seen` timestamps
4. **Natural CRUD** - Standard database operations

### Why Separate Hardlink and Duplicate Tables?

**Problem:** Querying for hardlinks vs duplicates requires complex joins.

**Solution:** Pre-compute and cache in separate tables.

**Benefits:**
1. **Fast lookups** - No complex GROUP BY queries needed
2. **Clear semantics** - hardlink_groups = within device, duplicate_groups = across devices
3. **Indexed properly** - Different access patterns, different indexes

---

## Schema Evolution

### Migration Strategy

Migrations are stored in `src/hashall/migrations/` and applied automatically.

**Naming convention:** `NNNN_description.sql`

**Example:**
```
0001_init_schema.sql
0002_add_treehash_fields.sql
0003_add_scan_session.sql
0004_backfill_scan_session.sql
0005_add_hardlink_fields.sql
0006_add_unified_catalog.sql  ← Future migration
```

**Application:** Migrations run automatically on first `scan` command.

### Backward Compatibility

For users migrating from session-based model:

1. Old tables (`scan_sessions`, `files`) remain untouched
2. New tables created alongside
3. Migration tool (future) copies data from old → new
4. Old tables can be dropped after verification

---

## Common Queries

### Find Deduplication Opportunities (Same Device)

```sql
-- Find files with same SHA1 but different inodes on device 49
SELECT
    sha1,
    COUNT(DISTINCT inode) as inode_count,
    COUNT(*) as path_count,
    (COUNT(DISTINCT inode) - 1) * MAX(size) as bytes_saveable
FROM files_49
WHERE status = 'active' AND sha1 IS NOT NULL
GROUP BY sha1, size
HAVING inode_count > 1
ORDER BY bytes_saveable DESC;
```

### Show All Hardlinks

```sql
-- Get all paths that share an inode
SELECT
    device_id,
    inode,
    GROUP_CONCAT(path, ', ') as paths,
    path_count,
    size
FROM (
    SELECT f.*, hg.path_count
    FROM files_49 f
    JOIN hardlink_groups hg ON hg.device_id = 49 AND hg.inode = f.inode
    WHERE f.status = 'active'
)
GROUP BY inode;
```

### Find Cross-Device Duplicates

```sql
-- Files that exist on multiple devices
SELECT
    dg.sha1,
    dg.size,
    dg.device_count,
    dg.instance_count,
    GROUP_CONCAT(DISTINCT d.mount_point) as devices
FROM duplicate_groups dg
JOIN hardlink_groups hg ON dg.sha1 = hg.sha1
JOIN devices d ON hg.device_id = d.device_id
WHERE dg.device_count > 1
GROUP BY dg.sha1;
```

### Show Recent Scan Activity

```sql
-- Scan history with incremental metrics
SELECT
    d.device_alias,
    s.root_path,
    datetime(s.started_at) as scan_time,
    s.files_added,
    s.files_updated,
    s.files_unchanged,
    s.files_deleted,
    round(s.duration_seconds, 1) || 's' as duration,
    round(s.files_scanned / s.duration_seconds, 1) || '/s' as rate
FROM scan_sessions s
JOIN devices d ON s.fs_uuid = d.fs_uuid
WHERE s.status = 'completed'
ORDER BY s.started_at DESC
LIMIT 10;
```

### List All Registered Devices

```sql
-- Show all devices with stats
SELECT
    device_alias,
    fs_type,
    mount_point,
    total_files,
    round(total_bytes / 1024.0 / 1024 / 1024, 2) || ' GB' as total_size,
    scan_count,
    datetime(last_scanned_at) as last_scan
FROM devices
ORDER BY last_scanned_at DESC;
```

### Check for Stale Files

```sql
-- Files not seen in recent scans (potential deletions)
SELECT
    path,
    round(size / 1024.0 / 1024, 2) || ' MB' as size,
    datetime(last_seen_at) as last_seen,
    discovered_under
FROM files_49
WHERE status = 'active'
  AND last_seen_at < datetime('now', '-30 days')
ORDER BY last_seen_at
LIMIT 20;
```

### Analyze Scan Performance

```sql
-- Compare sequential vs parallel scan performance
SELECT
    CASE WHEN parallel THEN 'parallel' ELSE 'sequential' END as mode,
    COUNT(*) as scans,
    round(AVG(files_scanned / duration_seconds), 1) as avg_rate,
    round(AVG(duration_seconds), 1) as avg_duration,
    round(AVG(CAST(files_unchanged AS REAL) / files_scanned * 100), 1) as pct_unchanged
FROM scan_sessions
WHERE status = 'completed' AND duration_seconds > 0
GROUP BY parallel;
```

---

## Database Size Estimates

| Files | Devices | DB Size | Notes |
|-------|---------|---------|-------|
| 10,000 | 1 | ~1.5 MB | Small music library |
| 50,000 | 2 | ~7 MB | Medium collection |
| 100,000 | 3 | ~15 MB | Large multi-device setup |
| 1,000,000 | 5 | ~150 MB | Very large catalog |

**Growth rate:** ~120 bytes per file record (includes indexes)

**Compression:** SQLite databases compress well with `VACUUM`

---

## Performance Considerations

### Indexes

All tables have indexes on:
- Primary keys (automatic)
- Foreign keys (for joins)
- Query columns (sha1, inode, size, status)

### Query Optimization

**Fast queries:**
- Lookup by path: O(log n) - indexed primary key
- Lookup by inode: O(log n) - indexed
- Lookup by SHA1: O(log n) - indexed

**Slow queries:**
- Full table scans without WHERE clauses
- Complex JOINs across many device tables

**Recommendation:** Use device-specific tables when possible instead of scanning all `files_*` tables.

---

## See Also

- `docs/architecture.md` - How the schema is used
- `docs/unified-catalog-architecture.md` - Complete design rationale
- `src/hashall/migrations/` - Actual migration SQL files
- `schema.sql` - Legacy schema (session-based model)

---

**Schema questions?** File an issue on GitHub.
