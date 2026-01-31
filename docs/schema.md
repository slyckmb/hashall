# Hashall Database Schema
**Model:** Unified Catalog
**Version:** 0.5.0
**Last Updated:** 2026-01-31

Source of truth for current implementation: Check `src/hashall/migrations/` for actual schema.

---

## Overview

The unified catalog uses a device-aware schema where files are stored in separate tables per device/filesystem. This reflects the natural boundary for hardlink operations and enables faster queries.

**Key principle:** One table per device = natural hardlink domain

---

## Core Tables

### `devices`

Registry of filesystems/mount points.

```sql
CREATE TABLE devices (
    device_id INTEGER PRIMARY KEY,              -- st_dev from stat()
    mount_point TEXT NOT NULL,                  -- e.g., "/pool", "/stash"
    filesystem_type TEXT,                       -- e.g., "zfs", "ext4"
    last_scan_started REAL,                     -- Unix timestamp
    last_scan_completed REAL,                   -- Unix timestamp
    last_scan_status TEXT,                      -- "completed", "in_progress", "failed"
    total_files INTEGER DEFAULT 0,              -- Cached count
    total_size INTEGER DEFAULT 0,               -- Cached total bytes
    notes TEXT,                                 -- User notes
    UNIQUE(device_id)
);

CREATE INDEX idx_devices_mount ON devices(mount_point);
```

**Purpose:** Track which filesystems are cataloged

**Updated by:** `scan` command on each run

---

## Per-Device File Tables

### `files_<device_id>`

One table per device. Created dynamically during first scan of each device.

**Example:** `files_49`, `files_50`, etc.

```sql
CREATE TABLE files_<device_id> (
    path TEXT PRIMARY KEY,                      -- Relative to mount_point
    inode INTEGER NOT NULL,                     -- st_ino
    size INTEGER NOT NULL,                      -- st_size (bytes)
    mtime REAL NOT NULL,                        -- st_mtime (modification time)
    sha1 TEXT,                                  -- Hex digest (40 chars)
    last_seen REAL NOT NULL,                    -- Unix timestamp of last scan
    first_seen REAL NOT NULL,                   -- Unix timestamp when first discovered
    scan_count INTEGER DEFAULT 1,               -- How many times seen
    status TEXT DEFAULT 'active'                -- 'active', 'deleted', 'moved'
);

CREATE INDEX idx_files_<device_id>_inode ON files_<device_id>(inode);
CREATE INDEX idx_files_<device_id>_sha1 ON files_<device_id>(sha1);
CREATE INDEX idx_files_<device_id>_size ON files_<device_id>(size);
CREATE INDEX idx_files_<device_id>_status ON files_<device_id>(status);
```

**Purpose:** Store file metadata for incremental scanning

**Key fields:**
- `path` - Relative to mount point (not absolute)
- `inode` - For hardlink detection
- `sha1` - For content-based deduplication
- `last_seen` - Tracks when file was last verified
- `status` - Lifecycle: active → deleted/moved

**Updated by:** `scan` command (incremental updates)

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

### `scan_history`

Lightweight audit trail of scan operations.

```sql
CREATE TABLE scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    files_added INTEGER DEFAULT 0,
    files_removed INTEGER DEFAULT 0,
    files_modified INTEGER DEFAULT 0,
    files_unchanged INTEGER DEFAULT 0,
    status TEXT,                                 -- 'completed', 'failed', 'interrupted'
    error_message TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

CREATE INDEX idx_scan_history_device ON scan_history(device_id);
CREATE INDEX idx_scan_history_started ON scan_history(started_at DESC);
```

**Purpose:** Track scan activity for auditing

**Created by:** `scan` command (one record per scan)

**Query example:**
```sql
-- Show recent scan activity
SELECT d.mount_point, h.started_at, h.files_added, h.files_removed
FROM scan_history h
JOIN devices d ON h.device_id = d.device_id
ORDER BY h.started_at DESC
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
SELECT
    d.mount_point,
    datetime(h.started_at, 'unixepoch') as scan_time,
    h.files_added,
    h.files_removed,
    h.files_modified,
    h.status
FROM scan_history h
JOIN devices d ON h.device_id = d.device_id
ORDER BY h.started_at DESC
LIMIT 10;
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
