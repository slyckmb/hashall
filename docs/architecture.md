# Hashall Architecture
**Model:** Unified Catalog (as of v0.5.0)
**Last Updated:** 2026-01-31

---

## Overview

Hashall uses a **unified catalog model**: one database catalogs all files across all storage, with device-aware tables for natural hardlink boundaries.

**Key principles:**
- Single source of truth (`~/.hashall/catalog.db`)
- One table per device/filesystem
- Incremental updates (not snapshots)
- Link-ready for deduplication

---

## Core Concept

### The Unified Catalog

```
~/.hashall/catalog.db
  ├─ devices                    (registry of filesystems)
  ├─ files_49                   (files on device 49: /pool)
  ├─ files_50                   (files on device 50: /stash)
  ├─ hardlink_groups            (inodes with multiple paths)
  ├─ duplicate_groups           (same content across devices)
  └─ link_plans                 (deduplication plans)
```

**Why device-based tables?**
- Hardlinks only work within a device
- Natural boundary for operations
- Faster queries (no device_id filter needed)
- Clear data isolation

---

## Data Flow

### 1. Scan Phase

```
User: hashall scan /pool
       ↓
┌──────────────────────────────────────┐
│ Walk filesystem                       │
│ - Resolve symlinks to canonical paths │
│ - Check (device_id, inode, path)      │
│ - Skip if already seen in this scan   │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ For each file:                        │
│ - Compute SHA1 hash                   │
│ - Get inode, device_id, size, mtime   │
│ - Check if exists in catalog          │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ Incremental update:                   │
│ - NEW files      → INSERT             │
│ - CHANGED files  → UPDATE             │
│ - MISSING files  → UPDATE status      │
│ - MOVED files    → DETECT and mark    │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ Update metadata:                      │
│ - hardlink_groups (inodes w/ >1 path) │
│ - duplicate_groups (cross-device)     │
│ - scan_history (stats)                │
└──────────────────────────────────────┘
```

**Output:** Updated catalog with latest filesystem state

### 2. Analysis Phase

```
User: hashall link analyze
       ↓
┌──────────────────────────────────────┐
│ Query catalog:                        │
│ - Group files by SHA1                 │
│ - Count unique (device_id, inode)     │
│ - Identify duplicates vs hardlinks    │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ Categorize opportunities:             │
│ - Same device, different inodes       │
│   → Can hardlink                      │
│ - Cross device, same content          │
│   → Informational only                │
│ - Same inode, multiple paths          │
│   → Already optimized (NOOP)          │
└──────────────────────────────────────┘
```

**Output:** Deduplication opportunities report

### 3. Planning Phase

```
User: hashall link plan "dedupe"
       ↓
┌──────────────────────────────────────┐
│ Generate plan:                        │
│ - For each duplicate group            │
│ - Pick canonical path                 │
│ - Create HARDLINK actions             │
│ - Calculate space savings             │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ Store plan:                           │
│ - link_plans (summary)                │
│ - link_actions (individual ops)       │
└──────────────────────────────────────┘
```

**Output:** Actionable plan with safety checks

### 4. Execution Phase

```
User: hashall link execute <plan_id>
       ↓
┌──────────────────────────────────────┐
│ For each action:                      │
│ 1. Verify source exists               │
│ 2. Verify same device                 │
│ 3. Backup target → target.bak         │
│ 4. Create hardlink                    │
│ 5. Verify inode matches               │
│ 6. Remove backup                      │
└──────────────────────────────────────┘
       ↓
┌──────────────────────────────────────┐
│ On failure:                           │
│ - Restore from backup                 │
│ - Mark action as failed               │
│ - Continue with next action           │
└──────────────────────────────────────┘
```

**Output:** Executed plan with success/failure stats

---

## Key Modules

### `src/hashall/scan.py`
Filesystem walk + incremental update logic.

**Key functions:**
- `scan_path()` - Main entry point
- `incremental_scan()` - Add/remove/modify/move detection
- `_ensure_device_table()` - Create device-specific tables
- `_detect_moves()` - Same inode, different path detection

### `src/hashall/catalog.py`
Unified catalog management.

**Key classes:**
- `UnifiedCatalog` - Main catalog interface
- `Device` - Device registry
- `FileRecord` - File metadata

### `src/hashall/link.py`
Deduplication planning and execution.

**Key classes:**
- `Link` - Main link interface
- `Plan` - Deduplication plan
- `Action` - Individual hardlink operation

### `src/hashall/export.py` (Optional)
JSON export for archival/sharing.

**Note:** Link works directly with DB now, export is optional.

---

## Schema Overview

See `docs/schema.md` for complete details.

### Core Tables

```sql
-- Device registry
devices (device_id, mount_point, total_files, total_size, ...)

-- Per-device file tables (created dynamically)
files_<device_id> (path, inode, size, mtime, sha1, ...)

-- Hardlink tracking (within device)
hardlink_groups (device_id, inode, path_count, sha1, ...)

-- Duplicate tracking (across devices)
duplicate_groups (sha1, instance_count, device_count, ...)

-- Link plans
link_plans (id, name, status, total_opportunities, ...)
link_actions (id, plan_id, action_type, source_path, ...)

-- Audit trail
scan_history (device_id, started_at, files_added, files_removed, ...)
```

---

## Incremental Scan Algorithm

### Step 1: Get Current State

```python
# Query existing files from catalog
existing_files = query(f"SELECT path, inode, size, mtime, sha1 FROM files_{device_id}")

# Build lookup maps
existing_by_path = {f.path: f for f in existing_files}
existing_by_inode = {f.inode: f for f in existing_files}
```

### Step 2: Walk Filesystem

```python
for file_path in walk(root):
    # Resolve symlinks
    canonical = file_path.resolve()

    # Get metadata
    stat = file_path.stat()
    device_id, inode = stat.st_dev, stat.st_ino

    # Check if already seen in THIS scan
    if (device_id, inode, canonical) in seen_in_scan:
        continue  # Skip bind mount/symlink duplicate

    # Mark as seen
    seen_in_scan.add((device_id, inode, canonical))

    # Process file...
```

### Step 3: Detect Changes

```python
if path in existing_by_path:
    old = existing_by_path[path]

    if old.size != stat.st_size or old.mtime != stat.st_mtime:
        # File was modified
        UPDATE files SET size=?, mtime=?, sha1=?, last_seen=?
        stats['modified'] += 1
    else:
        # File unchanged
        UPDATE files SET last_seen=?, scan_count=scan_count+1
        stats['unchanged'] += 1
else:
    # New file
    INSERT INTO files (path, inode, size, mtime, sha1, first_seen, last_seen)
    stats['added'] += 1
```

### Step 4: Detect Deletions

```python
for old_path in existing_by_path:
    if old_path not in seen_in_scan:
        # File was deleted
        UPDATE files SET status='deleted', last_seen=?
        stats['removed'] += 1
```

### Step 5: Detect Moves

```python
# Find inodes that appear in both 'deleted' and 'active' with different paths
moved = query("""
    SELECT d.path as old_path, a.path as new_path, d.inode
    FROM files d
    JOIN files a ON d.inode = a.inode
    WHERE d.status = 'deleted'
      AND a.status = 'active'
      AND d.path != a.path
      AND a.last_seen = ?
""", (scan_time,))

for move in moved:
    UPDATE files SET status='moved' WHERE path=move.old_path
    stats['moved'] += 1
```

---

## Symlink and Bind Mount Handling

See `docs/symlinks-and-bind-mounts.md` for complete details.

**Key strategy:** Canonical path resolution + deduplication tracking

```python
# During scan, track what we've seen
seen_in_scan = set()  # (device_id, inode, canonical_path)

for file_path in walk(root):
    # Skip symlinked files
    if file_path.is_symlink():
        continue

    # Resolve to canonical path
    canonical = file_path.resolve()

    # Get device and inode
    stat = file_path.stat()
    key = (stat.st_dev, stat.st_ino, str(canonical))

    # Skip if already scanned (bind mount or symlink duplicate)
    if key in seen_in_scan:
        continue

    # Process file...
    seen_in_scan.add(key)
```

**Result:**
- Symlinks → Resolved to same canonical path, scanned once
- Bind mounts → Same device+inode, skipped
- Hardlinks → Different canonical paths, all recorded

---

## Comparison with Session-Based Model

### Session-Based (Old)

```
scan_sessions (scan_id, root_path, started_at, treehash)
files (path, scan_session_id, size, mtime, sha1, inode, device_id)
```

**Problems:**
- Database grows forever (3 scans = 3× data)
- Complex queries (need session filtering)
- No automatic change detection
- Need manual session cleanup

### Unified Catalog (New)

```
devices (device_id, mount_point, ...)
files_<device_id> (path, size, mtime, sha1, inode, ...)
```

**Benefits:**
- Database stays lean (one record per file)
- Simple queries (always current state)
- Automatic change tracking (compare last_seen)
- Natural CRUD operations

---

## Performance Characteristics

### Scan Performance

| Dataset | Files | Time | Rate |
|---------|-------|------|------|
| Music library | 3,804 | 6m48s | 9.3 files/s |
| Ebook library | 57,156 | 43m13s | 22.0 files/s |

**Bottleneck:** SHA1 computation (CPU-bound)

**Future:** Parallel mode will use ThreadPoolExecutor for hashing

### Catalog Size

| Files | Database Size | Export Size (JSON) |
|-------|---------------|-------------------|
| 3,804 | ~500 KB | 1.1 MB |
| 57,156 | ~7 MB | 17 MB |

**Growth:** ~120 bytes per file record (SQLite)

### Query Performance

Direct DB queries (no JSON parsing):
- Find duplicates: <100ms (indexed on sha1)
- Find hardlinks: <50ms (indexed on inode)
- Generate plan: <500ms (50k files)

---

## Future Enhancements

### Planned Features

1. **Parallel scanning** - Multi-threaded hashing for faster scans
2. **Incremental hashing** - Skip unchanged files based on mtime
3. **Subtree treehash** - Fast subtree comparison
4. **Web UI** - Browse catalog via web interface
5. **Remote sync** - Sync catalog across machines
6. **Advanced filters** - Size, date, path patterns

### Under Consideration

1. **Content-based move detection** - Not just inode-based
2. **Automatic execution** - Scheduled deduplication
3. **Undo/rollback** - Revert conductor actions
4. **Cloud integration** - S3, Backblaze support

---

## Migration from Session-Based

If you have an existing session-based database:

```bash
# Export latest session per root
hashall export old.db --root /pool --out /tmp/pool.json

# Import into unified catalog
hashall import /tmp/pool.json --device /pool

# Verify
hashall link status
```

See `docs/unified-catalog-architecture.md` for complete migration guide.

---

## See Also

- `docs/unified-catalog-architecture.md` - Comprehensive design document
- `docs/schema.md` - Complete database schema
- `docs/link-guide.md` - Deduplication workflow
- `docs/symlinks-and-bind-mounts.md` - Canonical path handling
- `docs/cli.md` - Command reference

---

**Architecture questions?** File an issue on GitHub.
