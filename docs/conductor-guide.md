# Hashall Conductor Guide
**Version:** 0.5.0 (Unified Catalog Model)
**Last Updated:** 2026-01-31

---

## What is the Conductor?

The **conductor** is hashall's deduplication planning and execution system. It analyzes your file catalog to find:
- Duplicate files that can be hardlinked
- Existing hardlinks (already optimized)
- Cross-device duplicates (informational)
- Space-saving opportunities

**Key principle:** The conductor never modifies files without explicit approval. All operations go through a plan→review→execute workflow.

---

## Use Cases

### 1. Within-Device Deduplication
**Scenario:** You have duplicate files on the same filesystem/device that aren't hardlinked.

**Example:**
```
/pool/media/movies/film.mkv        (5GB, device 49, inode 100)
/pool/backup/movies/film.mkv       (5GB, device 49, inode 101) ← duplicate!
```

**Result:** Conductor can hardlink these to save 5GB.

### 2. Cross-Device Analysis
**Scenario:** You want to know what files exist on multiple devices.

**Example:**
```
/pool/archive/file.mp4   (device 49)
/stash/archive/file.mp4  (device 50) ← same content, different device
```

**Result:** Conductor identifies the duplicate but flags it as cross-device (can't hardlink, but you can delete one copy).

### 3. Hardlink Verification
**Scenario:** You want to verify existing hardlinks are intact.

**Example:**
```
/data/torrents/movie.mkv  (inode 12345)
/data/seeding/movie.mkv   (inode 12345) ← already hardlinked
```

**Result:** Conductor reports "NOOP" (already optimal, no action needed).

---

## Workflow

### Step 1: Scan Your Storage

```bash
# Scan each root you want to analyze
hashall scan /pool
hashall scan /stash
hashall scan /backup
```

This builds the unified catalog at `~/.hashall/catalog.db`.

### Step 2: Analyze Opportunities

```bash
# Analyze a single device for deduplication
hashall conductor analyze --device /pool

# Analyze across multiple devices
hashall conductor analyze --cross-device
```

**Output example:**
```
📊 Registered Devices:
  /pool           (device 49) - 50,000 files, 500 GB
  /stash          (device 50) - 30,000 files, 300 GB

🔍 Same-device deduplication opportunities:
  /pool:
    abc123... - 3 inodes, 5 paths, save 10 GB

🌐 Cross-device duplicate files:
  def456... - 2.5 GB × 3 copies across 2 devices
```

### Step 3: Create a Plan

```bash
# Generate plan for single device
hashall conductor plan "Monthly /pool dedupe" --device /pool

# Generate plan across devices
hashall conductor plan "Cross-device analysis" --cross-device
```

**Output:**
```
✅ Plan created: Monthly /pool dedupe
   ID: 1
   Opportunities: 250
   Potential savings: 45.2 GB
```

### Step 4: Review the Plan

```bash
hashall conductor show-plan 1
```

**Output example:**
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

 2. HARDLINK           3,500,000,000 bytes
    ...
```

### Step 5: Execute (Dry Run First)

```bash
# Always dry-run first!
hashall conductor execute 1 --dry-run

# If it looks good, execute for real
hashall conductor execute 1
```

**Execution output:**
```
⚡ EXECUTING Plan #1: Monthly /pool dedupe
Actions to perform: 250
═══════════════════════════════════════════════════

HARDLINK: /pool/backup/movies/film.mkv
  → /pool/movies/film.mkv
  Saves: 5,000,000,000 bytes
  ✅ Success

...

═══════════════════════════════════════════════════
✅ Executed: 248
❌ Failed: 2

See /tmp/conductor_plan_1_execution.log for details
```

---

## Safety Guarantees

### 1. Device Boundary Enforcement
**Guarantee:** Conductor will NEVER attempt to hardlink files across different devices.

**Why:** Hardlinks only work within a single filesystem.

**What it does:** Cross-device duplicates are flagged for manual review or deletion, never auto-hardlinked.

### 2. SHA1 Collision Detection
**Guarantee:** Before hardlinking, conductor verifies SHA1 + size match.

**Why:** Protect against hash collisions (extremely rare but theoretically possible).

**What it does:** Rejects any mismatches as potential collisions.

### 3. Existing Hardlink Preservation
**Guarantee:** Never attempts to hardlink files that are already hardlinked.

**Why:** Avoid unnecessary operations and potential errors.

**What it does:** Detects `(device_id, inode)` matches and marks as "NOOP".

### 4. Backup Before Modify
**Guarantee:** Target files are backed up before being replaced.

**Why:** Allow rollback if something goes wrong.

**What it does:**
```bash
mv target.mkv target.mkv.bak
ln source.mkv target.mkv
# If success: rm target.mkv.bak
# If failure: mv target.mkv.bak target.mkv
```

### 5. Dry-Run by Default
**Guarantee:** All operations preview changes before execution.

**Why:** Let users review and approve before making changes.

**What it does:** Generates plan file, requires `--force` or explicit execute command.

---

## Command Reference

### `hashall conductor analyze`
Find deduplication opportunities.

```bash
hashall conductor analyze [--device PATH] [--cross-device]
```

**Options:**
- `--device PATH` - Analyze single device
- `--cross-device` - Include cross-device duplicates

### `hashall conductor plan`
Create a deduplication plan.

```bash
hashall conductor plan NAME [--device PATH] [--cross-device] [--same-device]
```

**Options:**
- `NAME` - Human-readable plan name
- `--device PATH` - Target single device (default: all)
- `--same-device` - Include same-device hardlink opportunities (default: true)
- `--cross-device` - Include cross-device analysis (default: false)

**Returns:** Plan ID for later reference

### `hashall conductor show-plan`
Display plan details.

```bash
hashall conductor show-plan PLAN_ID [--limit N]
```

**Options:**
- `PLAN_ID` - Plan to display
- `--limit N` - Show top N actions (default: 20)

### `hashall conductor execute`
Execute a plan.

```bash
hashall conductor execute PLAN_ID [--dry-run] [--force]
```

**Options:**
- `PLAN_ID` - Plan to execute
- `--dry-run` - Preview without making changes (default)
- `--force` - Actually execute (DANGEROUS - review plan first!)

### `hashall conductor status`
Show catalog status.

```bash
hashall conductor status [--device PATH]
```

Displays:
- Registered devices
- File counts
- Total space
- Hardlink statistics
- Potential savings

---

## Example Workflows

### Workflow 1: Monthly /pool Deduplication

```bash
# 1. Rescan to update catalog
hashall scan /pool

# 2. Find opportunities
hashall conductor analyze --device /pool

# 3. Create plan
hashall conductor plan "Monthly /pool dedupe" --device /pool

# 4. Review plan
hashall conductor show-plan 1

# 5. Execute (dry-run)
hashall conductor execute 1 --dry-run

# 6. Execute for real
hashall conductor execute 1
```

### Workflow 2: Cross-Device Audit

```bash
# 1. Scan all devices
hashall scan /pool
hashall scan /stash
hashall scan /backup

# 2. Find cross-device duplicates
hashall conductor analyze --cross-device

# 3. Export report
hashall conductor plan "Cross-device audit" --cross-device --same-device=false

# 4. Review (won't hardlink, just informs)
hashall conductor show-plan 2
```

### Workflow 3: Verify Existing Hardlinks

```bash
# 1. Scan
hashall scan /data

# 2. Analyze
hashall conductor analyze --device /data

# 3. Check for NOOP items (already optimal)
hashall conductor plan "Verify hardlinks" --device /data
hashall conductor show-plan 3 | grep "NOOP"
```

---

## Troubleshooting

### "Cross-device hardlink attempt detected"
**Cause:** Plan tried to hardlink across devices (should never happen - safety check).

**Solution:** This is a bug. Report it. Conductor should flag cross-device as informational only.

### "SHA1 mismatch despite matching hash"
**Cause:** Possible hash collision or file corruption.

**Solution:** Do NOT proceed. Investigate the files manually. This is extremely rare.

### "Target file missing during execution"
**Cause:** File was deleted between plan creation and execution.

**Solution:** Re-scan and create a new plan. Don't execute stale plans.

### "Permission denied"
**Cause:** Conductor doesn't have write access to target directory.

**Solution:** Run with appropriate permissions or fix directory ownership/permissions.

---

## Best Practices

### 1. Scan Regularly
- Rescan before creating new plans
- Stale data = bad plans

### 2. Always Dry-Run First
- Review what will happen
- Check for unexpected actions
- Verify space savings estimates

### 3. Start Small
- Test on a single directory first
- Expand to full devices once confident
- Build trust incrementally

### 4. Review NOOP Items
- They show what's already optimal
- Verify your dedup strategy is working
- No action needed = good!

### 5. Monitor Cross-Device Duplicates
- They can't be auto-deduplicated
- Manual decision required (delete? consolidate?)
- Track to avoid unnecessary copies

### 6. Keep Catalog Updated
- Scan after major file operations
- Incremental updates are fast
- Accurate data = better plans

---

## Advanced Topics

### Custom Filters (Future)
Future versions will support:
```bash
hashall conductor plan "Large files only" --min-size 1GB
hashall conductor plan "Recent files" --mtime-since "2026-01"
hashall conductor plan "Specific paths" --include "*/media/*"
```

### Automated Execution (Future)
Future versions will support:
```bash
hashall conductor auto-execute --weekly --device /pool --min-savings 10GB
```

### Reporting (Future)
Future versions will support:
```bash
hashall conductor report --format json --out report.json
hashall conductor report --format html --out report.html
```

---

## Technical Details

### How Deduplication Works

**Step 1: Group by SHA1**
```sql
SELECT sha1, COUNT(DISTINCT inode) as inode_count
FROM files_49
GROUP BY sha1
HAVING inode_count > 1;
```

**Step 2: For Each Group**
- Pick "canonical" file (lexically first path)
- Plan `ln` operations for all other inodes
- Calculate space savings

**Step 3: Execute Plan**
```bash
for action in plan:
    backup(action.target)
    ln(action.source, action.target)
    verify(action.target)
    cleanup(backup)
```

### Data Model

Plans are stored in `conductor_plans` and `conductor_actions` tables:

```sql
CREATE TABLE conductor_plans (
    id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT,  -- pending, approved, executed
    total_opportunities INTEGER,
    total_bytes_saveable INTEGER
);

CREATE TABLE conductor_actions (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER,
    action_type TEXT,  -- HARDLINK, DELETE, SKIP, NOOP
    source_path TEXT,
    target_path TEXT,
    bytes_to_save INTEGER,
    status TEXT  -- pending, executed, failed
);
```

---

## Migration from JSON-Based Conductor

If you used conductor with JSON exports (session-based model):

**Old way:**
```bash
hashall export db.sqlite3 --out /tmp/export.json
python conductor_plan.py /tmp/export.json
```

**New way:**
```bash
hashall scan /pool  # Updates unified catalog
hashall conductor plan "Dedupe" --device /pool
hashall conductor execute 1
```

**Benefits:**
- No intermediate JSON files
- Direct DB queries (faster)
- Incremental updates (not full rescans)
- Device-aware (natural hardlink boundaries)

---

## See Also

- `docs/unified-catalog-architecture.md` - How the catalog works
- `docs/schema.md` - Database schema details
- `docs/symlinks-and-bind-mounts.md` - How symlinks are handled
- `docs/cli.md` - Complete CLI reference

---

**Questions or issues?** File a bug report or feature request on GitHub.
