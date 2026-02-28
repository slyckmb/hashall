# Hashall Link Guide
**Version:** 0.5.0 (Unified Catalog Model)
**Last Updated:** 2026-02-04

---

## What is Link?

**Link** is hashall's same-device hardlink planning and execution system. It analyzes your file catalog to find:
- Duplicate files that can be hardlinked
- Existing hardlinks (already optimized)
- Space-saving opportunities

**Key principle:** Link never modifies files without explicit approval. All operations go through a plan→review→execute workflow.

---

## Use Cases

### 1. Within-Device Deduplication
**Scenario:** You have duplicate files on the same filesystem/device that aren't hardlinked.

**Example:**
```
/pool/media/movies/film.mkv        (5GB, device 49, inode 100)
/pool/backup/movies/film.mkv       (5GB, device 49, inode 101) ← duplicate!
```

**Result:** Link can hardlink these to save 5GB.

### 2. Hardlink Verification
**Scenario:** You want to verify existing hardlinks are intact.

**Example:**
```
/data/torrents/movie.mkv  (inode 12345)
/data/seeding/movie.mkv   (inode 12345) ← already hardlinked
```

**Result:** Link reports "NOOP" (already optimal, no action needed).

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
hashall link analyze --device /pool
```

**Output example:**
```
🔍 Analyzing device: pool
   Mount point: /pool
   Total files: 50,000

📊 Deduplication Analysis:
   Duplicate groups found: 250
   Total duplicates: 430 files
   Potential space savings: 45.2 GB
```

### Step 3: Create a Plan

```bash
# Generate plan for single device
hashall link plan "Monthly /pool dedupe" --device /pool
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
hashall link show-plan 1
```

**Output example:**
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

 2. HARDLINK           3,500,000,000 bytes
    ...
```

### Step 5: Execute (Dry Run First)

```bash
# Always dry-run first!
hashall link execute 1 --dry-run

# If it looks good, execute for real
hashall link execute 1
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
```

---

## Safety Guarantees

### 1. Device Boundary Enforcement
**Guarantee:** Link will NEVER attempt to hardlink files across different devices.

**Why:** Hardlinks only work within a single filesystem.

**What it does:** The executor blocks any cross-filesystem hardlink attempt.

### 2. Verification Modes
**Guarantee:** Link verifies file content before linking, unless you explicitly disable verification.

**Why:** Protect against files changing between plan and execution.

**What it does:**
- **fast** (default): size/mtime checks + sampled hash of first/middle/last 1MB
- **paranoid**: full SHA256 hash of the entire file
- **none**: skips verification for maximum speed (use with care)

### 3. Existing Hardlink Preservation
**Guarantee:** Never attempts to hardlink files that are already hardlinked.

**Why:** Avoid unnecessary operations and potential errors.

**What it does:** Detects `(device_id, inode)` matches and marks as "NOOP".

### 4. Backup Before Modify
**Guarantee:** Target files are backed up before being replaced.

**Why:** Allow rollback if something goes wrong.

**What it does:**
```bash
ln target.mkv target.mkv.bak
rm target.mkv
ln source.mkv target.mkv
# If success: rm target.mkv.bak
# If failure: ln target.mkv.bak target.mkv
```

### 5. Explicit Execution & Confirmation
**Guarantee:** No filesystem changes occur unless you run `link execute` and confirm.

**Why:** Let users review and approve before making changes.

**What it does:** Use `--dry-run` to preview, then run without `--dry-run` and confirm (or pass `--yes`).

---

## Command Reference

For full CLI options and flags, see `docs/tooling/cli.md`.

---

## Example Workflows

### Workflow 1: Monthly /pool Deduplication

```bash
# 1. Rescan to update catalog
hashall scan /pool

# 2. Find opportunities
hashall link analyze --device /pool

# 3. Create plan
hashall link plan "Monthly /pool dedupe" --device /pool

# 4. Review plan
hashall link show-plan 1

# 5. Execute (dry-run)
hashall link execute 1 --dry-run

# 6. Execute for real
hashall link execute 1
```

### Workflow 2: Verify Existing Hardlinks

```bash
# 1. Scan
hashall scan /data

# 2. Analyze
hashall link analyze --device /data

# 3. Check for NOOP items (already optimal)
hashall link plan "Verify hardlinks" --device /data
hashall link show-plan 3 | grep "NOOP"
```

---

## Troubleshooting

### "Cross-filesystem hardlink rejected"
**Cause:** The files are on different filesystems, so hardlinks are not possible.

**Solution:** Re-scan and re-plan for a single device. The executor will always block cross-filesystem links.

### "Verification mismatch"
**Cause:** File content or metadata changed between planning and execution.

**Solution:** Re-scan and re-create the plan. If you still see mismatches, run with `--verify paranoid` for certainty.

### "Target file missing during execution"
**Cause:** File was deleted between plan creation and execution.

**Solution:** Re-scan and create a new plan. Don't execute stale plans.

### "Permission denied"
**Cause:** Link doesn't have write access to target directory.

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

### 5. Cross-Device Duplicates (Not in Sprint 1)
Link only plans and executes within a single device in Sprint 1.

### 6. Keep Catalog Updated
- Scan after major file operations
- Incremental updates are fast
- Accurate data = better plans

---

## Advanced Topics

### Custom Filters
Currently supported:
```bash
hashall link plan "Large files only" --device /pool --min-size 1073741824
```

Planned for future versions:
```bash
hashall link plan "Recent files" --mtime-since "2026-01"
hashall link plan "Specific paths" --include "*/media/*"
```

### Automated Execution (Future)
Out of scope for now. Track in `docs/project/DEVELOPMENT-ROADMAP.md`.

### Reporting (Future)
Out of scope for now. Track in `docs/project/DEVELOPMENT-ROADMAP.md`.

---

## Technical Details

### How Deduplication Works

**Step 1: Group by SHA256**
```sql
SELECT sha256, COUNT(DISTINCT inode) as inode_count
FROM files_49
GROUP BY sha256
HAVING inode_count > 1;
```

**Step 2: For Each Group**
- Pick "canonical" file (lowest inode, then shortest path, then alphabetical)
- Plan `ln` operations for all other inodes
- Calculate space savings

**Step 3: Execute Plan**
```bash
for action in plan:
    verify(action.source, action.target)
    backup(action.target)  # .bak hardlink
    ln(action.source, action.target)
    cleanup(backup)
```

### Data Model

Plans are stored in `link_plans` and `link_actions` tables:

```sql
CREATE TABLE link_plans (
    id INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT,  -- pending, approved, executed
    total_opportunities INTEGER,
    total_bytes_saveable INTEGER
);

CREATE TABLE link_actions (
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

## Migration from JSON-Based Link

If you used link with JSON exports (session-based model):

**Old way:**
```bash
hashall export db.sqlite3 --out /tmp/export.json
python link_plan.py /tmp/export.json
```

**New way:**
```bash
hashall scan /pool  # Updates unified catalog
hashall link plan "Dedupe" --device /pool
hashall link execute 1
```

**Benefits:**
- No intermediate JSON files
- Direct DB queries (faster)
- Incremental updates (not full rescans)
- Device-aware (natural hardlink boundaries)

---

## See Also

- `docs/architecture/architecture.md` - How the catalog works
- `docs/architecture/schema.md` - Database schema details
- `docs/tooling/symlinks-and-bind-mounts.md` - How symlinks are handled
- `docs/tooling/cli.md` - Complete CLI reference

---

**Questions or issues?** File a bug report or feature request on GitHub.
