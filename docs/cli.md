# Hashall CLI Reference
**Version:** 0.5.0 (Unified Catalog)
**Last Updated:** 2026-01-31

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

Scan a directory and update the unified catalog.

```bash
hashall scan ROOT_PATH [OPTIONS]
```

**Arguments:**
- `ROOT_PATH` - Directory to scan (e.g., `/pool`, `/stash`)

**Options:**
- `--db PATH` - Database path (default: `~/.hashall/catalog.db`)
- `--parallel` - Enable parallel hashing (future feature)

**Behavior:**
- First scan: Creates device table, adds all files
- Subsequent scans: Incremental update (add/remove/modify/move detection)
- Resolves symlinks to canonical paths
- Skips duplicate paths from bind mounts

**Example:**
```bash
# Initial scan
hashall scan /pool

# Rescan (incremental update)
hashall scan /pool

# Scan multiple devices
hashall scan /pool
hashall scan /stash
hashall scan /backup
```

**Output:**
```
✅ Scan session started: <device_id> — /pool
📦 Scanning: 100%|███████████| 50000/50000 [10:25<00:00, 79.92it/s]
📦 Scan complete.

✅ Scan Summary:
   Added:     1,234
   Removed:   567
   Modified:  89
   Moved:     45
   Unchanged: 48,234
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

**Note:** JSON export is now optional. Conductor works directly with the database.

---

### `conductor analyze`

Analyze catalog for deduplication opportunities.

```bash
hashall conductor analyze [OPTIONS]
```

**Options:**
- `--device PATH` - Analyze specific device only
- `--cross-device` - Include cross-device duplicates
- `--min-size BYTES` - Minimum file size (future)
- `--limit N` - Show top N opportunities

**Example:**
```bash
# Analyze single device
hashall conductor analyze --device /pool

# Analyze all devices
hashall conductor analyze --cross-device

# Quick summary
hashall conductor analyze --limit 10
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

### `conductor plan`

Create a deduplication plan.

```bash
hashall conductor plan NAME [OPTIONS]
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
hashall conductor plan "Monthly /pool dedupe" --device /pool

# Cross-device audit (informational)
hashall conductor plan "Cross-device audit" --cross-device --same-device=false
```

**Output:**
```
✅ Plan created: Monthly /pool dedupe
   ID: 1
   Opportunities: 250
   Potential savings: 45.2 GB
```

---

### `conductor show-plan`

Display plan details.

```bash
hashall conductor show-plan PLAN_ID [OPTIONS]
```

**Arguments:**
- `PLAN_ID` - Plan to display

**Options:**
- `--limit N` - Show top N actions (default: 20)
- `--format {text|json}` - Output format (future)

**Example:**
```bash
hashall conductor show-plan 1
hashall conductor show-plan 1 --limit 50
```

**Output:**
```
╔══════════════════════════════════════════════════════════════
║ CONDUCTOR PLAN #1: Monthly /pool dedupe
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

### `conductor execute`

Execute a deduplication plan.

```bash
hashall conductor execute PLAN_ID [OPTIONS]
```

**Arguments:**
- `PLAN_ID` - Plan to execute

**Options:**
- `--dry-run` - Preview without making changes (default)
- `--force` - Actually execute (DANGEROUS - review first!)

**Example:**
```bash
# Always dry-run first!
hashall conductor execute 1 --dry-run

# Execute for real
hashall conductor execute 1 --force
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

### `conductor status`

Show catalog and device status.

```bash
hashall conductor status [OPTIONS]
```

**Options:**
- `--device PATH` - Show specific device only
- `--verbose` - Show detailed statistics

**Example:**
```bash
hashall conductor status
hashall conductor status --device /pool
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

**Note:** This command uses the legacy session-based model. For unified catalog workflows, use `conductor analyze` instead.

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
hashall conductor analyze --device /pool

# 3. Create plan
hashall conductor plan "Monthly dedupe" --device /pool

# 4. Review
hashall conductor show-plan <plan_id>

# 5. Execute
hashall conductor execute <plan_id> --dry-run
hashall conductor execute <plan_id> --force
```

### Initial Setup

```bash
# Scan all your storage
hashall scan /pool
hashall scan /stash
hashall scan /backup

# Check status
hashall conductor status
```

### Cross-Device Audit

```bash
# Find duplicates across devices
hashall conductor analyze --cross-device

# Create informational report
hashall conductor plan "Audit 2026-01" --cross-device
hashall conductor show-plan <plan_id>
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

- `docs/conductor-guide.md` - Complete conductor workflow
- `docs/architecture.md` - How hashall works
- `docs/schema.md` - Database schema
- `docs/quick-reference.md` - Cheat sheet

---

**CLI questions?** File an issue on GitHub.
