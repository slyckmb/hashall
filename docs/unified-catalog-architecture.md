# Unified Catalog Architecture for hashall

## Core Philosophy

**One database to catalog everything you own.**

- Single SQLite database: `~/.hashall/catalog.db`
- One table per device/filesystem (natural hardlink boundaries)
- Incremental updates: rescans modify existing records, don't create new sessions
- Full paths relative to filesystem mount point
- Direct SQL queries for link operations (no JSON export needed)

---

## Answering Your Questions

### 1. **How should we use this tool?**

```bash
# Initial setup - scan all your storage
hashall scan /pool
hashall scan /stash
hashall scan /backup

# Later - just rescan, it updates in place
hashall scan /pool    # Adds new, removes deleted, tracks moves

# Find deduplication opportunities
hashall link plan --device /pool    # Within one filesystem
hashall link plan --cross-device    # Across filesystems

# Execute deduplication
hashall link execute <plan-id> --dry-run
hashall link execute <plan-id>      # Actually do it
```

**Workflow:**
1. **Scan phase**: Walk filesystem, compute hashes, update catalog
2. **Analysis phase**: Query catalog for duplicates, hardlink groups
3. **Planning phase**: Generate deduplication plan (what to hardlink, move, delete)
4. **Execution phase**: Safely execute plan with rollback capability

### 2. **Do we really need JSON?**

**No.** JSON export should be optional for:
- Portability (sharing scan with someone else)
- Archival (snapshot for historical comparison)
- External tool integration (if you want to process with jq)

**For link operations: work directly with SQLite.**

```python
# Instead of:
export_data = json.load(open('scan.json'))
for file in export_data['files']:
    # ... analyze ...

# Do this:
cursor = db.execute("""
    SELECT path, sha1, size, inode
    FROM files_49
    WHERE sha1 IN (SELECT sha1 FROM files_50)
""")
```

Much faster, simpler, and no intermediate file size concerns.

### 3. **Where is the DB kept currently?**

**Current default:** `~/.hashall/hashall.sqlite3` (single centralized DB)

**Proposed:** Same location is perfect for unified catalog model!

**Alternative locations to consider:**
- `~/.hashall/catalog.db` - Central catalog (recommended)
- `/pool/.hashall/catalog.db` - Per-filesystem catalog (if you want isolation)
- `~/.config/hashall/catalog.db` - XDG-compliant location

**Recommendation: Stick with `~/.hashall/catalog.db`** for a true unified view.

### 4. **What happens on rescans when things change?**

**Incremental Update Model:**

| Event | Current Behavior | New Behavior |
|-------|-----------------|--------------|
| **File added** | New record in new session | INSERT new record, set first_seen, last_seen |
| **File deleted** | Still in old session | UPDATE status='deleted', last_seen=now |
| **File modified** | New record in new session | UPDATE size, mtime, sha1, last_seen |
| **File moved** | Looks like delete+add | DETECT: same inode, mark old as 'moved' |
| **File unchanged** | Duplicate in new session | UPDATE last_seen, scan_count++ |

**Move Detection Logic:**
```python
# Scan finds inode 12345 at new_path
# But DB has inode 12345 at old_path (marked deleted)
# → This is a MOVE, not delete+add
UPDATE files SET status='moved' WHERE inode=12345 AND path=old_path
# new_path record already exists with status='active'
```

**Example Rescan Scenario:**

```
# Initial scan of /pool
/pool/music/song.mp3       (inode 100, sha1 abc123, size 5MB)
/pool/videos/movie.mp4     (inode 200, sha1 def456, size 1GB)

# Later: song moved, movie deleted, new file added
/pool/archive/song.mp3     (inode 100, sha1 abc123, size 5MB)  ← MOVED
/pool/downloads/show.mkv   (inode 300, sha1 789xyz, size 2GB)  ← NEW

# After rescan, DB shows:
files_49:
  path                    | inode | status  | sha1
  ----------------------- | ----- | ------- | ------
  music/song.mp3          | 100   | moved   | abc123  ← Detected move
  archive/song.mp3        | 100   | active  | abc123  ← New location
  videos/movie.mp4        | 200   | deleted | def456  ← Deleted
  downloads/show.mkv      | 300   | active  | 789xyz  ← New file
```

**Scan Stats Output:**
```
✅ Scan complete
   Added:     1,234
   Removed:   567
   Modified:  89
   Moved:     45
   Unchanged: 48,234
```

---

## Schema Overview

### **Core Tables**

```sql
devices                  -- Registry of filesystems/mount points
  ├─ device_id (primary key, from st_dev)
  ├─ mount_point (/pool, /stash)
  └─ total_files, total_size (cached stats)

files_<device_id>        -- One table per device (files_49, files_50...)
  ├─ path (primary key, relative to mount)
  ├─ inode, size, mtime, sha1
  ├─ first_seen, last_seen, scan_count
  └─ status (active, deleted, moved)

hardlink_groups          -- Inodes with multiple paths (within device)
  ├─ (device_id, inode) primary key
  ├─ path_count, sha1, size
  └─ canonical_path

duplicate_groups         -- Same content across devices
  ├─ sha1 (primary key)
  ├─ instance_count, device_count
  └─ total_wasted_bytes

link_plans               -- Deduplication plans
  └─ link_actions        -- Individual hardlink/move/delete operations

scan_history            -- Lightweight audit trail
  └─ devices, started_at, stats (added/removed/modified)
```

### **Dynamic Tables**

**One `files_*` table per device:**
- `files_49` for device 49 (/pool)
- `files_50` for device 50 (/stash)
- `files_51` for device 51 (/backup)

**Why?**
- Natural hardlink boundaries (can't hardlink across devices)
- Faster queries (don't need WHERE device_id = ?)
- Easier index management
- Clear data isolation

---

## Advantages Over Session Model

### **Current (Session-Based)**

```
Scan 1 at 10am → session abc123
Scan 2 at 11am → session def456
Scan 3 at 12pm → session ghi789

files table:
  path         | session_id | size | sha1
  ------------ | ---------- | ---- | ----
  foo.txt      | abc123     | 100  | aaa
  foo.txt      | def456     | 100  | aaa  ← Duplicate
  foo.txt      | ghi789     | 150  | bbb  ← Modified
  bar.txt      | abc123     | 200  | ccc
  bar.txt      | def456     | 200  | ccc  ← Duplicate
```

**Issues:**
- Database grows forever (3x sessions = 3x file records)
- Complex queries (need session filtering)
- No automatic change detection
- Need manual session cleanup

### **Proposed (Unified Catalog)**

```
Single state per device (updated in place)

files_49:
  path         | size | sha1 | last_seen | scan_count | status
  ------------ | ---- | ---- | --------- | ---------- | ------
  foo.txt      | 150  | bbb  | 12:00pm   | 3          | active
  bar.txt      | 200  | ccc  | 11:00am   | 2          | deleted
```

**Benefits:**
- Database stays lean (one record per file)
- Simple queries (no session filtering)
- Automatic change tracking (compare last_seen)
- Natural CRUD operations (INSERT/UPDATE/DELETE)

---

## Link Workflow

### **Phase 1: Discovery**

```bash
hashall scan /pool
hashall scan /stash
```

**Builds catalog:**
- `files_49`: 50,000 files in /pool
- `files_50`: 30,000 files in /stash
- `hardlink_groups`: 500 groups (already optimized)
- `duplicate_groups`: 200 SHA1s appearing on both devices

### **Phase 2: Analysis**

```bash
hashall link analyze
```

**Queries catalog:**
```sql
-- Same-device duplicates (can hardlink now)
SELECT sha1, COUNT(DISTINCT inode) as copies, size
FROM files_49
WHERE status = 'active' AND sha1 IS NOT NULL
GROUP BY sha1
HAVING copies > 1;

-- Cross-device duplicates (migration candidates)
SELECT f49.sha1, f49.path, f50.path
FROM files_49 f49
JOIN files_50 f50 ON f49.sha1 = f50.sha1
WHERE f49.device_id != f50.device_id;
```

### **Phase 3: Planning**

```bash
hashall link plan "Monthly dedupe" --device 49
```

**Creates plan record:**
- Scan `files_49` for SHA1s with multiple inodes
- For each group: pick canonical path, plan HARDLINK for others
- Store in `link_actions` table
- Show summary: X opportunities, Y GB saveable

### **Phase 4: Execution**

```bash
hashall link execute <plan-id> --dry-run  # Preview
hashall link execute <plan-id>             # Apply
```

**Safe execution:**
1. Backup target file: `mv target.mp3 target.mp3.bak`
2. Create hardlink: `ln source.mp3 target.mp3`
3. Verify: check inode matches
4. Remove backup: `rm target.mp3.bak`
5. Update DB: mark action as executed

**If anything fails:**
- Restore backup: `mv target.mp3.bak target.mp3`
- Mark action as failed
- Continue with next action

---

## Example Queries

### **Find biggest wasted space**

```sql
SELECT sha1, size, instance_count, total_wasted_bytes
FROM duplicate_groups
ORDER BY total_wasted_bytes DESC
LIMIT 20;
```

### **Show all copies of a file**

```sql
-- Find in device 49
SELECT path, inode, size FROM files_49 WHERE sha1 = 'abc123...';

-- Find in device 50
SELECT path, inode, size FROM files_50 WHERE sha1 = 'abc123...';
```

### **What changed since last scan?**

```sql
-- Files added in last scan
SELECT path, size FROM files_49
WHERE first_seen = last_seen
  AND last_seen > ?;

-- Files deleted
SELECT path, size FROM files_49
WHERE status = 'deleted'
  AND last_seen > ?;

-- Files modified
SELECT path, size FROM files_49
WHERE scan_count > 1
  AND last_seen > ?
  AND first_seen < ?;
```

### **Hardlink effectiveness per device**

```sql
SELECT
    d.mount_point,
    COUNT(*) as hardlink_groups,
    SUM(hg.path_count) as total_paths,
    SUM((hg.path_count - 1) * hg.size) as space_saved
FROM hardlink_groups hg
JOIN devices d ON hg.device_id = d.device_id
GROUP BY d.mount_point;
```

---

## Migration from Current Schema

**Current schema** uses session-based tracking:
```sql
scan_sessions (id, scan_id, root_path, started_at)
files (path, scan_session_id, size, sha1, inode, device_id)
```

**Migration strategy:**

```python
# 1. Take latest session per root
latest_sessions = {}
for session in scan_sessions:
    root = session.root_path
    if root not in latest_sessions or session.started_at > latest_sessions[root].started_at:
        latest_sessions[root] = session

# 2. Create unified catalog
unified_db = create_unified_catalog()

# 3. For each latest session
for root, session in latest_sessions.items():
    device_id = get_device_id(root)
    unified_db.register_device(root, device_id)

    # Copy files from session to device table
    for file in get_files(session.id):
        unified_db.add_file(device_id, file.path, file.inode,
                           file.size, file.sha1, session.started_at)

# 4. Build hardlink and duplicate groups
unified_db.rebuild_groups()
```

---

## Recommendations

### **Schema: ✅ Use unified catalog model**

- One DB for all storage
- One table per device
- Incremental updates
- Direct SQL access

### **JSON Export: ⚠️ Make it optional**

```bash
hashall scan /pool                    # Updates catalog
hashall export /pool --json out.json  # Optional export
```

### **DB Location: ✅ Keep `~/.hashall/catalog.db`**

Central location makes sense for unified view.

### **Rescans: ✅ Implement incremental update**

- Add new files
- Mark deleted files
- Detect moves
- Update modified files
- Track scan history for auditing

### **Link: ✅ Direct DB access**

No JSON parsing needed - query catalog directly for speed and simplicity.

---

## Implementation Priority

1. **High Priority:**
   - Implement unified schema (`devices`, `files_*` tables)
   - Incremental scan with add/delete/modify/move detection
   - Basic link: find same-device duplicates, generate plans

2. **Medium Priority:**
   - Cross-device duplicate detection
   - Plan execution with dry-run
   - Migration tool from session-based to unified model

3. **Low Priority:**
   - JSON export (for archival/sharing)
   - Web UI for browsing catalog
   - Advanced move detection (content-based, not just inode)

---

## Next Steps

Would you like me to:

1. **Implement the unified schema** in hashall?
2. **Port the scan.py to incremental model**?
3. **Build the link module** for real?
4. **Create migration tool** from current DB format?

The architecture is solid. Implementation is straightforward SQLite + filesystem operations.
