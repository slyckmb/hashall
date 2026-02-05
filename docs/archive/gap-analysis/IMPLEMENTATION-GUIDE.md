# Implementation Guide - Sprint 1: Link Deduplication

**Sprint:** 1 of 3
**Feature:** Link Deduplication
**Start Date:** 2026-02-02
**Status:** 🚀 READY TO BEGIN

---

## Quick Start

### Step 1: Apply Database Migration (Task 1.1)

**File Created:** `src/hashall/migrations/0008_add_link_tables.sql`

**Apply Migration:**

```bash
cd /home/michael/dev/work/hashall

# Backup current database (IMPORTANT!)
cp ~/.hashall/catalog.db ~/.hashall/catalog.db.backup-$(date +%Y%m%d)

# Apply migration using existing migration system
python3 -c "
from pathlib import Path
from hashall.model import connect_db
from hashall.migrate import apply_migrations

db_path = Path.home() / '.hashall' / 'catalog.db'
conn = connect_db(db_path)
apply_migrations(conn)
conn.close()
print('✅ Migration 0008 applied successfully!')
"

# Verify tables exist
sqlite3 ~/.hashall/catalog.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'link_%';"

# Expected output:
# link_plans
# link_actions
```

**Verify Migration:**

```bash
# Check schema
sqlite3 ~/.hashall/catalog.db ".schema link_plans"
sqlite3 ~/.hashall/catalog.db ".schema link_actions"

# Check indexes
sqlite3 ~/.hashall/catalog.db "
SELECT name, tbl_name
FROM sqlite_master
WHERE type='index' AND tbl_name LIKE 'link_%'
ORDER BY tbl_name, name;
"

# Test insert (then delete)
sqlite3 ~/.hashall/catalog.db "
INSERT INTO link_plans (name, device_id, total_opportunities, actions_total)
VALUES ('Test Plan', 49, 1, 1);

SELECT * FROM link_plans;

DELETE FROM link_plans WHERE name = 'Test Plan';
"
```

**✅ Task 1.1 Complete When:**
- [ ] Migration applies without errors
- [ ] Tables exist in database
- [ ] Indexes created
- [ ] Test insert/delete works
- [ ] Schema documentation updated

---

### Step 2: Implement Link Analyze (Task 1.2)

**Files to Create:**
1. `src/hashall/link_analysis.py` (core logic)
2. `tests/test_link_analysis.py` (unit tests)
3. Update `src/hashall/cli.py` (add commands)

**Start with CLI Command Structure:**

```python
# In src/hashall/cli.py, after the payload group:

@cli.group()
def link():
    """Link deduplication commands."""
    pass

@link.command("analyze")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
@click.option("--device", required=True, help="Device alias or device_id")
@click.option("--cross-device", is_flag=True, help="Show cross-device duplicates")
@click.option("--min-size", type=int, default=0, help="Minimum file size in bytes")
@click.option("--format", type=click.Choice(['text', 'json']), default='text')
def link_analyze_cmd(db, device, cross_device, min_size, format):
    """
    Analyze catalog for deduplication opportunities.

    Identifies files with same content but different inodes on the same device.
    Reports potential space savings.

    Examples:
        hashall link analyze --device pool
        hashall link analyze --device /stash --min-size 1048576  # 1MB+
        hashall link analyze --device 49 --format json
    """
    from pathlib import Path
    from hashall.model import connect_db
    from hashall.device import get_device_by_alias_or_id
    from hashall.link_analysis import analyze_device, format_analysis_text, format_analysis_json

    conn = connect_db(Path(db))

    # Resolve device
    device_info = get_device_by_alias_or_id(conn, device)
    if not device_info:
        click.echo(f"❌ Device not found: {device}", err=True)
        return 1

    # Run analysis
    result = analyze_device(conn, device_info['device_id'], min_size=min_size)

    # Format output
    if format == 'json':
        click.echo(format_analysis_json(result))
    else:
        click.echo(format_analysis_text(result))

    conn.close()
    return 0
```

**Create Analysis Module:**

```python
# src/hashall/link_analysis.py
from dataclasses import dataclass, field
from typing import List, Optional
import sqlite3

@dataclass
class DuplicateGroup:
    """Group of files with same content."""
    hash: str
    file_size: int
    file_count: int
    unique_inodes: int
    files: List[str]
    inodes: List[int]
    potential_savings: int

@dataclass
class AnalysisResult:
    """Result of deduplication analysis."""
    device_id: int
    device_alias: Optional[str]
    mount_point: str
    total_files: int
    duplicate_groups: List[DuplicateGroup] = field(default_factory=list)

    @property
    def total_duplicates(self) -> int:
        return sum(g.file_count for g in self.duplicate_groups)

    @property
    def potential_bytes_saveable(self) -> int:
        return sum(g.potential_savings for g in self.duplicate_groups)

def analyze_device(conn: sqlite3.Connection, device_id: int, min_size: int = 0) -> AnalysisResult:
    """
    Analyze a device for deduplication opportunities.

    Returns groups where multiple files have same hash but different inodes.
    """
    cursor = conn.cursor()

    # Get device info
    cursor.execute("SELECT device_id, alias, mount_point FROM devices WHERE device_id = ?", (device_id,))
    dev_row = cursor.fetchone()
    device_alias, mount_point = dev_row[1], dev_row[2] if dev_row else (None, None)

    # Count total files
    table_name = f"files_{device_id}"
    cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE status = 'active'")
    total_files = cursor.fetchone()[0]

    # Find duplicate groups (same hash, different inodes)
    query = f"""
    SELECT
        sha1,
        size,
        COUNT(*) as file_count,
        COUNT(DISTINCT inode) as unique_inodes,
        GROUP_CONCAT(path, '|||') as paths,
        GROUP_CONCAT(DISTINCT inode, '|||') as inodes,
        (COUNT(DISTINCT inode) - 1) * size as potential_savings
    FROM {table_name}
    WHERE status = 'active'
      AND sha1 IS NOT NULL
      AND size >= ?
    GROUP BY sha1, size
    HAVING COUNT(DISTINCT inode) > 1
    ORDER BY potential_savings DESC
    """

    cursor.execute(query, (min_size,))

    duplicate_groups = []
    for row in cursor.fetchall():
        hash_val, file_size, file_count, unique_inodes, paths_str, inodes_str, potential_savings = row

        files = paths_str.split('|||') if paths_str else []
        inodes = [int(i) for i in inodes_str.split('|||')] if inodes_str else []

        duplicate_groups.append(DuplicateGroup(
            hash=hash_val,
            file_size=file_size,
            file_count=file_count,
            unique_inodes=unique_inodes,
            files=files,
            inodes=inodes,
            potential_savings=potential_savings
        ))

    return AnalysisResult(
        device_id=device_id,
        device_alias=device_alias,
        mount_point=mount_point,
        total_files=total_files,
        duplicate_groups=duplicate_groups
    )

def format_analysis_text(result: AnalysisResult) -> str:
    """Format analysis as human-readable text."""
    output = []
    output.append(f"🔍 Analyzing device: {result.device_alias or result.device_id}")
    output.append(f"   Mount point: {result.mount_point}")
    output.append(f"   Total files: {result.total_files:,}")
    output.append("")
    output.append("📊 Deduplication Analysis:")
    output.append(f"   Duplicate groups found: {len(result.duplicate_groups):,}")
    output.append(f"   Total duplicates: {result.total_duplicates:,} files")
    output.append(f"   Potential space savings: {result.potential_bytes_saveable / (1024**3):.1f} GB")

    if result.duplicate_groups:
        output.append("")
        output.append("   Top 10 duplicate groups:")
        for i, group in enumerate(result.duplicate_groups[:10], 1):
            size_gb = group.file_size / (1024**3)
            savings_gb = group.potential_savings / (1024**3)
            filename = group.files[0].split('/')[-1] if group.files else "unknown"
            output.append(f"   {i}. {group.file_size:,} bytes ({size_gb:.1f} GB) - {group.file_count} copies - saves {savings_gb:.1f} GB - {filename}")

    output.append("")
    output.append("✅ Use 'hashall link plan' to create a deduplication plan")

    return "\n".join(output)

def format_analysis_json(result: AnalysisResult) -> str:
    """Format analysis as JSON."""
    import json
    data = {
        "device_id": result.device_id,
        "device_alias": result.device_alias,
        "mount_point": result.mount_point,
        "total_files": result.total_files,
        "analysis": {
            "duplicate_groups": len(result.duplicate_groups),
            "total_duplicates": result.total_duplicates,
            "potential_bytes_saveable": result.potential_bytes_saveable,
            "top_groups": [
                {
                    "hash": g.hash,
                    "file_size": g.file_size,
                    "file_count": g.file_count,
                    "unique_inodes": g.unique_inodes,
                    "potential_savings": g.potential_savings,
                    "files": g.files[:5]  # Limit for brevity
                }
                for g in result.duplicate_groups[:20]
            ]
        }
    }
    return json.dumps(data, indent=2)
```

**Test the Command:**

```bash
# Test analyze command
python3 -m hashall link analyze --device pool

# Expected output:
# 🔍 Analyzing device: pool
#    Mount point: /pool
#    Total files: 50,000
#
# 📊 Deduplication Analysis:
#    Duplicate groups found: 250
#    Total duplicates: 1,250 files
#    Potential space savings: 45.2 GB
#    ...
```

**✅ Task 1.2 Complete When:**
- [ ] `link analyze` command works
- [ ] Duplicate detection accurate
- [ ] Output formats (text/json) work
- [ ] Unit tests pass
- [ ] Integration tests pass

---

### Step 3: Implement Remaining Commands

Follow the same pattern for:
- Task 1.3: `link plan`
- Task 1.4: `link show-plan`
- Task 1.5: `link execute`

Refer to `SPRINT-1-TASK-BREAKDOWN.md` for detailed specifications.

---

## Development Workflow

### Daily Checklist

```bash
# 1. Pull latest code
cd /home/michael/dev/work/hashall
git pull

# 2. Activate virtualenv
source ~/.venvs/hashall/bin/activate

# 3. Run tests before making changes
pytest tests/ -v

# 4. Make your changes
# ... write code ...

# 5. Run tests after changes
pytest tests/ -v

# 6. Check coverage
pytest --cov=src/hashall --cov-report=term-missing tests/

# 7. Commit changes
git add .
git commit -m "feat(link): implement link analyze command"

# 8. Push to repo
git push
```

### Testing Strategy

**Unit Tests (Fast, Isolated):**
```bash
# Test specific module
pytest tests/test_link_analysis.py -v

# Test specific function
pytest tests/test_link_analysis.py::test_analyze_device -v
```

**Integration Tests (Slower, End-to-End):**
```bash
# Test CLI commands
pytest tests/test_link_analyze_cli.py -v
```

**Manual Testing:**
```bash
# Create test database
python3 tests/test_link_manual.py

# Run command on test data
python3 -m hashall link analyze --device /tmp/test_pool --db /tmp/test.db
```

---

## Common Issues & Solutions

### Issue 1: Migration Already Applied

**Error:** `table link_plans already exists`

**Solution:** Migration is idempotent (IF NOT EXISTS). Safe to re-run.

### Issue 2: Device Not Found

**Error:** `Device not found: pool`

**Solution:**
```bash
# List devices
python3 -m hashall devices list

# Use correct alias or device_id
```

### Issue 3: No SHA1 Hashes

**Error:** `No duplicate groups found` (but you know duplicates exist)

**Cause:** Files scanned with `--hash-mode fast` (quick_hash only, no sha1)

**Solution:**
```bash
# Scan with full hash mode
python3 -m hashall scan /pool --hash-mode full

# Or upgrade existing quick_hash to full
python3 -m hashall scan /pool --hash-mode upgrade
```

### Issue 4: Permission Errors

**Error:** `Permission denied` when creating hardlinks

**Solution:**
- Ensure user has write permissions
- Check filesystem supports hardlinks (not FAT32, exFAT)
- ZFS requires same dataset (device_id)

---

## Code Style Guidelines

**Follow Existing Patterns:**

1. **Dataclasses for Data:** Use `@dataclass` for structured data
2. **Type Hints:** All functions should have type hints
3. **Docstrings:** Google-style docstrings for public functions
4. **Error Handling:** Explicit error messages with actionable guidance
5. **Logging:** Use `click.echo()` for CLI output
6. **Testing:** Aim for >80% coverage, >90% for critical safety code

**Example:**
```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class MyData:
    """Description of data structure."""
    field1: str
    field2: int
    optional_field: Optional[str] = None

def my_function(param1: str, param2: int) -> MyData:
    """
    Brief description of function.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        MyData object with results

    Raises:
        ValueError: If param2 is negative
    """
    if param2 < 0:
        raise ValueError(f"param2 must be non-negative, got {param2}")

    return MyData(field1=param1, field2=param2)
```

---

## Progress Tracking

**Update Task Status:**

Edit `SPRINT-1-TASK-BREAKDOWN.md` and check off completed items:

```markdown
### Task 1.1.1: Create Migration File
- [x] Migration file created
- [x] Can be run multiple times without error
- [x] All indexes created
- [x] Foreign key constraints work
- [x] Schema matches design spec
```

**Daily Stand-Up Format:**

```
Date: 2026-02-03

Yesterday:
- ✅ Created database migration (Task 1.1.1)
- ✅ Applied migration to test database
- ✅ Verified schema correctness

Today:
- 🎯 Implement link analyze CLI command (Task 1.2.1)
- 🎯 Create link_analysis.py module (Task 1.2.2)

Blockers:
- None
```

---

## Resources

**Documentation:**
- Requirements: `docs/REQUIREMENTS.md`
- Sprint Tasks: `docs/gap-analysis/SPRINT-1-TASK-BREAKDOWN.md`
- Roadmap: `docs/gap-analysis/DEVELOPMENT-ROADMAP.md`

**Code References:**
- Existing migrations: `src/hashall/migrations/0001-0007*.sql`
- Existing CLI: `src/hashall/cli.py`
- Existing tests: `tests/test_*.py`

**Tools:**
- sqlite3: Database inspection
- pytest: Test runner
- tqdm: Progress bars
- click: CLI framework

---

## Getting Help

**If stuck:**
1. Check existing code for similar patterns
2. Review test files for usage examples
3. Read docstrings in modules
4. Ask for help (user, Claude, etc.)

**Before asking:**
- What have you tried?
- What error message did you get?
- Can you reproduce with minimal example?

---

**Sprint Status:** 🚀 IN PROGRESS
**Current Task:** 1.1 Database Schema
**Next Task:** 1.2 Link Analyze Command

**Good luck! You've got this.** 🎉
