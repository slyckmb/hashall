# Hashall CLI Reference
**Version:** 0.5.0 (Unified Catalog with Incremental Scanning)
**Last Updated:** 2026-02-01

---

## Entry Point

Use the module entry point (preferred for dev):

```bash
python -m hashall --help
```

Installed console script (if installed via `pip`):

```bash
hashall --help
```

---

## Global Options

```bash
--db PATH     Path to catalog database (default: ~/.hashall/catalog.db)
--help        Show help message
--version     Show version
```

---

## Commands

### `scan`

Scan a directory and update the unified catalog. **Now incremental by default.**

```bash
hashall scan ROOT_PATH [OPTIONS]
```

**Arguments:**
- `ROOT_PATH` - Directory to scan (e.g., `/pool`, `/stash`)

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/hashall.sqlite3`)
- `--parallel` - Enable parallel hashing with thread pool
- `--workers N` - Number of worker threads (default: CPU count)
- `--batch-size N` - Batch size for parallel writes (default: 500)

**Behavior:**
- **First scan:** Detects filesystem UUID, registers device, creates `files_<device_id>` table, hashes all files
- **Subsequent scans:** Incremental update - skips unchanged files (same size+mtime), only rehashes modified files
- Automatically detects: additions, deletions, modifications
- Tracks scan roots for scoped deletion detection
- Resolves symlinks to canonical paths
- Skips duplicate paths from bind mounts
- Handles device_id changes across reboots (renames tables automatically)

**Performance:**
- Sequential: ~20-30 files/s (initial), ~500-1000 files/s (incremental)
- Parallel (8 workers): ~100-150 files/s (initial), ~2000-5000 files/s (incremental)
- **10-100x faster on rescans** due to unchanged file skipping

**Example:**
```bash
# Initial scan (hashes all files)
hashall scan /pool

# Incremental rescan (skips unchanged files)
hashall scan /pool
# Much faster - only rehashes modified files

# Parallel scan (faster on large datasets)
hashall scan /pool --parallel --workers 8

# Scan multiple devices
hashall scan /pool
hashall scan /stash
hashall scan /backup

# Scan a subset (scoped deletion)
hashall scan /pool/torrents
# Only files under /pool/torrents are considered for deletion
```

**Output:**
```
📍 Scanning: /pool
   Device ID: 49
   Filesystem UUID: zfs-12345678
✅ Registered new device: pool (fs_uuid=zfs-12345678, device_id=49)
✅ Scan session: a1b2c3d4-...
📊 Existing files in catalog: 0
📁 Files on filesystem: 50,000
📦 Scanning: 100%|███████████| 50000/50000 [8:20<00:00, 100.0it/s]

📦 Scan complete!
   Duration: 500.0s
   Scanned: 50,000 files
   Added: 50,000
   Updated: 0
   Unchanged: 0
   Deleted: 0
   Hashed: 500.0 GB

# Rescan output (mostly unchanged):
📦 Scanning: 100%|███████████| 50000/50000 [0:25<00:00, 2000.0it/s]

📦 Scan complete!
   Duration: 25.0s
   Scanned: 50,000 files
   Added: 10
   Updated: 50
   Unchanged: 49,940
   Deleted: 5
   Hashed: 0.5 GB
```

---

### `export`

Export scan data to JSON (optional, for archival/sharing).

```bash
hashall export DB_PATH [OPTIONS]
```

**Arguments:**
- `DB_PATH` - Database to export from

**Options:**
- `--root ROOT_PATH` - Filter to specific root
- `--out OUTPUT_PATH` - Output file path
- `--device DEVICE_ID` - Filter to specific device

**Example:**
```bash
# Export device 49 to JSON
hashall export ~/.hashall/catalog.db --device 49 --out /tmp/pool.json

# Export all devices
hashall export ~/.hashall/catalog.db --out /tmp/catalog.json
```

**Note:** JSON export is now optional. Link works directly with the database.

---

### `devices list`

List all registered devices and their statistics.

```bash
hashall devices list [OPTIONS]
```

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/hashall.sqlite3`)

**Example:**
```bash
hashall devices list
```

**Output:**
```
Alias  UUID (first 8)  Device ID  Mount Point  Type  Files     Size
pool   zfs-1234        49         /pool        zfs   50,000    500.0 GB
stash  zfs-5678        50         /stash       zfs   30,000    300.0 GB
```

---

### `devices show`

Display detailed information for a specific device.

```bash
hashall devices show DEVICE [OPTIONS]
```

**Arguments:**
- `DEVICE` - Device alias (e.g., "pool") or device_id (e.g., "49")

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/hashall.sqlite3`)

**Example:**
```bash
hashall devices show pool
hashall devices show 49
```

**Output:**
```
Device: pool
  Filesystem UUID: zfs-12345678
  Current Device ID: 49
  Mount Point: /pool
  Filesystem Type: zfs

  ZFS Metadata:
    Pool Name: pool
    Dataset Name: pool
    Pool GUID: 12345678901234567890

  Statistics:
    Total Files: 50,000 active, 123 deleted
    Total Size: 500.0 GB
    First Scanned: 2026-01-15 10:00:00
    Last Scanned: 2026-02-01 14:30:00
    Scan Count: 25

  Device ID History:
    2026-01-15: device_id 48 (initial)
    2026-02-01: device_id 49 (changed after reboot)
```

---

### `devices alias`

Update device alias for easier identification.

```bash
hashall devices alias CURRENT_NAME NEW_ALIAS [OPTIONS]
```

**Arguments:**
- `CURRENT_NAME` - Current alias or device_id
- `NEW_ALIAS` - New alias to assign

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/hashall.sqlite3`)

**Example:**
```bash
# Rename by alias
hashall devices alias pool main_pool

# Rename by device_id
hashall devices alias 49 primary_storage
```

**Output:**
```
Updated alias: pool -> main_pool
```

---

### `stats`

Display overall catalog statistics.

```bash
hashall stats [OPTIONS]
```

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/hashall.sqlite3`)

**Example:**
```bash
hashall stats
```

**Output:**
```
Hashall Catalog Statistics
  Database: /home/user/.hashall/hashall.sqlite3
  Database Size: 12.5 MB

  Devices: 2
    pool            (49): 50,000 files, 500.0 GB
    stash           (50): 30,000 files, 300.0 GB

  Total Files: 80,000 active, 245 deleted
  Total Size: 800.0 GB

  Scan History:
    Last Scan: 2026-02-01 14:30:00 (pool)
    Total Scans: 47
```

---

### `link analyze`

Analyze catalog for deduplication opportunities.

```bash
hashall link analyze [OPTIONS]
```

**Options:**
- `--device PATH` - Analyze specific device only
- `--cross-device` - Include cross-device duplicates
- `--min-size BYTES` - Minimum file size (future)
- `--limit N` - Show top N opportunities

**Example:**
```bash
# Analyze single device
hashall link analyze --device /pool

# Analyze all devices
hashall link analyze --cross-device

# Quick summary
hashall link analyze --limit 10
```

**Output:**
```
📊 Registered Devices:
  /pool   (device 49) - 50,000 files, 500 GB
  /stash  (device 50) - 30,000 files, 300 GB

🔍 Same-device deduplication opportunities:
  /pool:
    abc123... - 3 inodes, 5 paths, save 10 GB
    def456... - 2 inodes, 3 paths, save 5 GB

🌐 Cross-device duplicates:
  xyz789... - 2.5 GB × 3 copies across 2 devices
```

---

### `link plan`

Create a deduplication plan.

```bash
hashall link plan NAME [OPTIONS]
```

**Arguments:**
- `NAME` - Human-readable plan name

**Options:**
- `--device PATH` - Target specific device
- `--cross-device` - Include cross-device analysis
- `--same-device` - Include same-device opportunities (default: true)
- `--min-savings BYTES` - Minimum savings threshold (future)

**Example:**
```bash
# Plan for single device
hashall link plan "Monthly /pool dedupe" --device /pool

# Cross-device audit (informational)
hashall link plan "Cross-device audit" --cross-device --same-device=false
```

**Output:**
```
✅ Plan created: Monthly /pool dedupe
   ID: 1
   Opportunities: 250
   Potential savings: 45.2 GB
```

---

### `link show-plan`

Display plan details.

```bash
hashall link show-plan PLAN_ID [OPTIONS]
```

**Arguments:**
- `PLAN_ID` - Plan to display

**Options:**
- `--limit N` - Show top N actions (default: 20)
- `--format {text|json}` - Output format (future)

**Example:**
```bash
hashall link show-plan 1
hashall link show-plan 1 --limit 50
```

**Output:**
```
╔══════════════════════════════════════════════════════════════
║ LINK PLAN #1: Monthly /pool dedupe
╚══════════════════════════════════════════════════════════════

Status: pending
Opportunities: 250
Potential Savings: 45.2 GB

Top 20 Actions:
────────────────────────────────────────────────────────────────
 1. HARDLINK           5,000,000,000 bytes
    abc123def456...
    Source: /pool/movies/film.mkv
    Target: /pool/backup/movies/film.mkv
...
```

---

### `link execute`

Execute a deduplication plan.

```bash
hashall link execute PLAN_ID [OPTIONS]
```

**Arguments:**
- `PLAN_ID` - Plan to execute

**Options:**
- `--dry-run` - Preview without making changes (default)
- `--force` - Actually execute (DANGEROUS - review first!)

**Example:**
```bash
# Always dry-run first!
hashall link execute 1 --dry-run

# Execute for real
hashall link execute 1 --force
```

**Output (dry-run):**
```
🔍 DRY RUN: Plan #1
Actions: 250
═══════════════════════════════════════════════════

HARDLINK: /pool/backup/movies/film.mkv
  → /pool/movies/film.mkv
  Saves: 5,000,000,000 bytes

...

🔍 DRY RUN complete - no changes made
```

**Output (execute):**
```
⚡ EXECUTING Plan #1
═══════════════════════════════════════════════════

HARDLINK: /pool/backup/movies/film.mkv
  → /pool/movies/film.mkv
  ✅ Success (saved 5 GB)

...

✅ Executed: 248
❌ Failed: 2
```

---

### `link status`

Show catalog and device status.

```bash
hashall link status [OPTIONS]
```

**Options:**
- `--device PATH` - Show specific device only
- `--verbose` - Show detailed statistics

**Example:**
```bash
hashall link status
hashall link status --device /pool
```

**Output:**
```
📊 Hashall Catalog Status

Devices:
  /pool   (device 49)
    Files: 50,000
    Size: 500 GB
    Hardlink groups: 1,200 (saving 25 GB)
    Last scan: 2026-01-31 10:30:00

  /stash  (device 50)
    Files: 30,000
    Size: 300 GB
    Hardlink groups: 800 (saving 15 GB)
    Last scan: 2026-01-31 09:15:00

Deduplication Opportunities:
  Same-device: 45.2 GB saveable
  Cross-device: 12.3 GB duplicate content
```

---

### `verify-trees` (Legacy)

Compare two directory trees (session-based workflow - may be deprecated).

```bash
hashall verify-trees SRC_ROOT DST_ROOT [OPTIONS]
```

**Note:** This command uses the legacy session-based model. For unified catalog workflows, use `link analyze` instead.

**Arguments:**
- `SRC_ROOT` - Source directory
- `DST_ROOT` - Destination directory

**Options:**
- `--db PATH` - Database path
- `--repair` - Generate repair manifest
- `--force` - Force rescan
- `--no-export` - Skip JSON export

**Example:**
```bash
hashall verify-trees /src /dst
```

---

## Environment Variables

```bash
HASHALL_DB      Default database path (overrides default)
HASHALL_JOBS    Number of parallel hash workers (future)
```

---

## Common Workflows

### Monthly Deduplication

```bash
# 1. Update catalog
hashall scan /pool

# 2. Analyze
hashall link analyze --device /pool

# 3. Create plan
hashall link plan "Monthly dedupe" --device /pool

# 4. Review
hashall link show-plan <plan_id>

# 5. Execute
hashall link execute <plan_id> --dry-run
hashall link execute <plan_id> --force
```

### Initial Setup

```bash
# Scan all your storage
hashall scan /pool
hashall scan /stash
hashall scan /backup

# Check status
hashall link status
```

### Cross-Device Audit

```bash
# Find duplicates across devices
hashall link analyze --cross-device

# Create informational report
hashall link plan "Audit 2026-01" --cross-device
hashall link show-plan <plan_id>
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Database error |
| 4 | Permission denied |
| 5 | Plan execution failed |

---

## Shell Completion

Generate shell completion scripts (future feature):

```bash
hashall --completion bash > ~/.hashall-completion.bash
source ~/.hashall-completion.bash
```

---

## See Also

- `docs/link-guide.md` - Complete link workflow
- `docs/architecture.md` - How hashall works
- `docs/schema.md` - Database schema
- `docs/quick-reference.md` - Cheat sheet

---

**CLI questions?** File an issue on GitHub.
