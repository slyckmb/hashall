# Sprint 1: Link Deduplication - Detailed Task Breakdown

**Sprint Goal:** Implement complete link deduplication workflow
**Duration:** 2-3 weeks
**Status:** 🚀 APPROVED - Implementation Starting

---

## Task 1.1: Database Schema (Priority: CRITICAL)

**Estimated Effort:** 2 days
**Status:** 🟢 READY TO START
**Owner:** TBD

### Task 1.1.1: Create Migration File

**File:** `src/hashall/migrations/0008_add_link_tables.sql`

**Requirements:**
- Create `link_plans` table for storing deduplication plans
- Create `link_actions` table for storing individual link operations
- Add indexes for performance
- Support idempotent execution (IF NOT EXISTS)
- Follow existing migration pattern from 0001-0007

**Schema Design:**

```sql
-- Link Plans Table
CREATE TABLE IF NOT EXISTS link_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, failed, cancelled
    device_id INTEGER NOT NULL,
    device_alias TEXT,
    mount_point TEXT,

    -- Opportunity counts
    total_opportunities INTEGER NOT NULL DEFAULT 0,

    -- Space metrics (bytes)
    total_bytes_saveable INTEGER NOT NULL DEFAULT 0,
    total_bytes_saved INTEGER DEFAULT 0,

    -- Execution metrics
    actions_total INTEGER NOT NULL DEFAULT 0,
    actions_executed INTEGER DEFAULT 0,
    actions_failed INTEGER DEFAULT 0,
    actions_skipped INTEGER DEFAULT 0,

    -- Timing
    started_at TEXT,
    completed_at TEXT,

    -- Notes and metadata
    notes TEXT,
    metadata TEXT,  -- JSON blob for extensibility

    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

-- Link Actions Table
CREATE TABLE IF NOT EXISTS link_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,

    -- Action details
    action_type TEXT NOT NULL,  -- HARDLINK, SKIP, NOOP
    status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, failed, skipped

    -- File paths
    canonical_path TEXT NOT NULL,  -- The file to keep (source of truth)
    duplicate_path TEXT NOT NULL,  -- The file to replace with hardlink

    -- File metadata (for verification)
    canonical_inode INTEGER,
    duplicate_inode INTEGER,
    device_id INTEGER NOT NULL,
    file_size INTEGER,
    sha256 TEXT,  -- Future-proof with SHA256

    -- Space savings
    bytes_to_save INTEGER NOT NULL DEFAULT 0,
    bytes_saved INTEGER DEFAULT 0,

    -- Execution details
    executed_at TEXT,
    error_message TEXT,
    backup_path TEXT,  -- Path to .bak file if created

    FOREIGN KEY (plan_id) REFERENCES link_plans(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_link_plans_status ON link_plans(status);
CREATE INDEX IF NOT EXISTS idx_link_plans_device ON link_plans(device_id);
CREATE INDEX IF NOT EXISTS idx_link_plans_created ON link_plans(created_at);

CREATE INDEX IF NOT EXISTS idx_link_actions_plan ON link_actions(plan_id);
CREATE INDEX IF NOT EXISTS idx_link_actions_status ON link_actions(status);
CREATE INDEX IF NOT EXISTS idx_link_actions_device ON link_actions(device_id);
CREATE INDEX IF NOT EXISTS idx_link_actions_type ON link_actions(action_type);
```

**Acceptance Criteria:**
- [ ] Migration file created at correct path
- [ ] Can be run multiple times without error (idempotent)
- [ ] All indexes created
- [ ] Foreign key constraints work
- [ ] Schema matches design spec

### Task 1.1.2: Apply Migration

**Steps:**
1. Backup current database: `cp ~/.hashall/catalog.db ~/.hashall/catalog.db.backup`
2. Apply migration using existing migration system
3. Verify tables exist: `sqlite3 ~/.hashall/catalog.db ".tables"`
4. Verify schema: `sqlite3 ~/.hashall/catalog.db ".schema link_plans"`

**Test Migration:**
```bash
# Test on clean database
cd /home/michael/dev/work/hashall
python3 -c "
from pathlib import Path
from hashall.model import connect_db
from hashall.migrate import apply_migrations
db_path = Path('/tmp/test_link_migration.db')
conn = connect_db(db_path)
apply_migrations(conn)
conn.close()
print('Migration successful!')
"
```

**Acceptance Criteria:**
- [ ] Migration applies without errors
- [ ] Tables exist in database
- [ ] Indexes created successfully
- [ ] Foreign keys enforced
- [ ] Can insert test data

### Task 1.1.3: Update Schema Documentation

**File:** `docs/architecture/schema.md`

**Changes:**
- Add section 5: Link Deduplication Tables
- Document `link_plans` table (all columns)
- Document `link_actions` table (all columns)
- Document indexes and foreign keys
- Add example queries

**Acceptance Criteria:**
- [ ] Documentation complete
- [ ] Examples work
- [ ] Reviewed and approved

---

## Task 1.2: Link Analyze Command (Priority: HIGH)

**Estimated Effort:** 3 days
**Depends On:** Task 1.1 (database schema)
**Status:** ⏳ BLOCKED

### Task 1.2.1: Design CLI Interface

**File:** `src/hashall/cli.py`

**Command Signature:**
```python
@cli.group()
def link():
    """Link deduplication commands."""
    pass

@link.command("analyze")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
@click.option("--device", required=True, help="Device alias or device_id")
@click.option("--cross-device", is_flag=True, help="Show cross-device duplicates (informational)")
@click.option("--min-size", type=int, default=0, help="Minimum file size in bytes")
@click.option("--format", type=click.Choice(['text', 'json']), default='text')
def link_analyze(db, device, cross_device, min_size, format):
    """
    Analyze catalog for deduplication opportunities.

    Identifies files with same content but different inodes on the same device.
    Reports space savings potential.
    """
    pass
```

**Output Format (Text):**
```
🔍 Analyzing device: pool (device_id: 49)
   Mount point: /pool
   Total files: 50,000

📊 Deduplication Analysis:
   Duplicate groups found: 250
   Total duplicates: 1,250 files
   Potential space savings: 45.2 GB

   Top 10 duplicate groups:
   1. 54315216817 bytes (51.8 GB) - 3 copies - Movie.2024.mkv
   2. 12345678912 bytes (11.5 GB) - 5 copies - Album.flac
   ...

✅ Use 'hashall link plan' to create a deduplication plan
```

**Output Format (JSON):**
```json
{
  "device_id": 49,
  "device_alias": "pool",
  "mount_point": "/pool",
  "total_files": 50000,
  "analysis": {
    "duplicate_groups": 250,
    "total_duplicates": 1250,
    "potential_bytes_saveable": 48557694976,
    "top_groups": [...]
  }
}
```

**Acceptance Criteria:**
- [ ] CLI command defined
- [ ] Help text clear
- [ ] Options validated
- [ ] Output formats implemented

### Task 1.2.2: Implement Analysis Logic

**New File:** `src/hashall/link_analysis.py`

**Core Functions:**
```python
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

@dataclass
class DuplicateGroup:
    """Group of files with same content."""
    hash: str  # SHA1 or SHA256
    file_size: int
    file_count: int
    files: List[str]  # Paths
    inodes: List[int]  # Unique inodes
    potential_savings: int  # bytes

@dataclass
class AnalysisResult:
    """Result of deduplication analysis."""
    device_id: int
    device_alias: Optional[str]
    mount_point: str
    total_files: int
    duplicate_groups: List[DuplicateGroup]
    total_duplicates: int
    potential_bytes_saveable: int

def analyze_device(db_path: Path, device_id: int, min_size: int = 0) -> AnalysisResult:
    """
    Analyze a device for deduplication opportunities.

    Query logic:
    1. Find all files with same hash but different inodes
    2. Count unique inodes per hash
    3. Calculate potential savings: (file_count - 1) * file_size
    4. Sort by potential savings (descending)
    """
    pass

def find_cross_device_duplicates(db_path: Path) -> List[DuplicateGroup]:
    """
    Find files duplicated across devices (informational only).
    Cannot be hardlinked, but useful to know.
    """
    pass
```

**SQL Query (Core Logic):**
```sql
-- Find duplicate groups on device
SELECT
    sha1,
    size,
    COUNT(*) as file_count,
    COUNT(DISTINCT inode) as unique_inodes,
    GROUP_CONCAT(path, '|') as paths,
    GROUP_CONCAT(DISTINCT inode, '|') as inodes,
    (COUNT(DISTINCT inode) - 1) * size as potential_savings
FROM files_{device_id}
WHERE status = 'active'
  AND sha1 IS NOT NULL
  AND size >= {min_size}
GROUP BY sha1, size
HAVING COUNT(DISTINCT inode) > 1
ORDER BY potential_savings DESC;
```

**Acceptance Criteria:**
- [ ] `link_analysis.py` module created
- [ ] Core functions implemented
- [ ] SQL queries optimized
- [ ] Unit tests written
- [ ] Edge cases handled (NULL hashes, 0-byte files)

### Task 1.2.3: Integration & Testing

**Unit Tests:** `tests/test_link_analysis.py`
**Integration Tests:** `tests/test_link_analyze_cli.py`

**Test Scenarios:**
1. Single device with duplicates
2. Device with no duplicates
3. Cross-device duplicates (informational)
4. Min-size filtering
5. JSON output format
6. Large dataset (performance)

**Acceptance Criteria:**
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Coverage >80%
- [ ] Command works end-to-end

---

## Task 1.3: Link Plan Command (Priority: HIGH)

**Estimated Effort:** 3 days
**Depends On:** Task 1.1 (schema), Task 1.2 (analyze)
**Status:** ⏳ BLOCKED

### Task 1.3.1: CLI Interface

**Command Signature:**
```python
@link.command("plan")
@click.argument("name")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
@click.option("--device", required=True)
@click.option("--min-size", type=int, default=0)
@click.option("--dry-run", is_flag=True, help="Generate plan without saving")
def link_plan(name, db, device, min_size, dry_run):
    """
    Create a deduplication plan.

    Analyzes device and generates a plan of actions to deduplicate files.
    Plan is saved to database and can be reviewed with 'link show-plan'.
    """
    pass
```

**Output:**
```
📋 Creating deduplication plan: "Monthly pool dedupe"
   Device: pool (49)
   Analyzing...

✅ Plan created successfully!
   Plan ID: 1
   Total opportunities: 250 groups
   Actions generated: 1,250 hardlinks
   Potential savings: 45.2 GB

   Review with: hashall link show-plan 1
   Execute with: hashall link execute 1 --dry-run
```

**Acceptance Criteria:**
- [ ] CLI command defined
- [ ] Plan name validated
- [ ] Device resolved (alias or ID)
- [ ] Output clear and actionable

### Task 1.3.2: Plan Generation Logic

**New File:** `src/hashall/link_planner.py`

**Core Functions:**
```python
from dataclasses import dataclass
from typing import List
from pathlib import Path
import sqlite3

@dataclass
class LinkPlan:
    """Deduplication plan."""
    id: Optional[int]
    name: str
    device_id: int
    opportunities: List[DuplicateGroup]
    actions: List[LinkAction]

@dataclass
class LinkAction:
    """Single hardlink action."""
    action_type: str  # HARDLINK, SKIP, NOOP
    canonical_path: str
    duplicate_path: str
    device_id: int
    file_size: int
    sha256: Optional[str]
    bytes_to_save: int

def create_plan(db_path: Path, name: str, device_id: int, min_size: int = 0) -> LinkPlan:
    """
    Generate a deduplication plan.

    Steps:
    1. Run analysis (reuse analyze_device())
    2. For each duplicate group:
       - Pick canonical file (lowest inode or first alphabetically)
       - Generate HARDLINK actions for other files
    3. Create LinkPlan object
    4. Return plan (not yet persisted)
    """
    pass

def save_plan(conn: sqlite3.Connection, plan: LinkPlan) -> int:
    """
    Persist plan to database.

    Transactions:
    1. INSERT into link_plans
    2. INSERT into link_actions (batch)
    3. Return plan_id
    """
    pass

def pick_canonical_file(files: List[str], inodes: List[int]) -> str:
    """
    Choose which file to keep as the canonical copy.

    Strategy:
    1. Prefer lowest inode (oldest file)
    2. If inodes equal, prefer shortest path
    3. If paths equal length, alphabetical
    """
    pass
```

**Acceptance Criteria:**
- [ ] `link_planner.py` created
- [ ] Plan generation works
- [ ] Actions correctly generated
- [ ] Canonical file selection is deterministic
- [ ] Plans persist to database

### Task 1.3.3: Database Persistence

**Insert Queries:**
```sql
-- Insert plan
INSERT INTO link_plans (
    name, device_id, device_alias, mount_point,
    total_opportunities, total_bytes_saveable, actions_total
) VALUES (?, ?, ?, ?, ?, ?, ?);

-- Insert actions (batch)
INSERT INTO link_actions (
    plan_id, action_type, canonical_path, duplicate_path,
    device_id, file_size, sha256, bytes_to_save
) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
```

**Acceptance Criteria:**
- [ ] Plans insert successfully
- [ ] Actions insert in batch (performance)
- [ ] Foreign keys maintained
- [ ] Transactions atomic (all or nothing)

### Task 1.3.4: Testing

**Unit Tests:** `tests/test_link_planner.py`
**Integration Tests:** `tests/test_link_plan_cli.py`

**Test Scenarios:**
1. Create plan with duplicates
2. Create plan with no duplicates (edge case)
3. Canonical file selection logic
4. Dry-run mode (no persistence)
5. Database persistence
6. Large plans (1000+ actions)

**Acceptance Criteria:**
- [ ] All tests pass
- [ ] Coverage >80%
- [ ] Performance acceptable

---

## Task 1.4: Link Show-Plan Command (Priority: MEDIUM)

**Estimated Effort:** 1 day
**Depends On:** Task 1.1 (schema), Task 1.3 (plan creation)
**Status:** ⏳ BLOCKED

### Task 1.4.1: CLI Interface

**Command Signature:**
```python
@link.command("show-plan")
@click.argument("plan_id", type=int)
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
@click.option("--limit", type=int, default=10, help="Actions to show (0 for all)")
@click.option("--format", type=click.Choice(['text', 'json']), default='text')
def link_show_plan(plan_id, db, limit, format):
    """Display details of a deduplication plan."""
    pass
```

**Output Format:**
```
📋 Plan #1: Monthly pool dedupe
   Status: pending
   Created: 2026-02-02 10:00:00

   Device: pool (49) at /pool
   Total opportunities: 250 groups
   Total actions: 1,250
   Potential savings: 45.2 GB

   Top 10 actions (by space savings):
   1. HARDLINK 51.8 GB
      Keep:    /pool/data/Movie.2024/video.mkv (inode: 12345)
      Replace: /pool/data/cross-seed/Movie.2024/video.mkv (inode: 67890)

   2. HARDLINK 11.5 GB
      Keep:    /pool/data/Album/track01.flac (inode: 11111)
      Replace: /pool/data/cross-seed/Album/track01.flac (inode: 22222)

   ...

✅ Execute with: hashall link execute 1 --dry-run
```

**Acceptance Criteria:**
- [ ] CLI command works
- [ ] Plan details displayed correctly
- [ ] Action list formatted clearly
- [ ] JSON output supported

### Task 1.4.2: Query Implementation

**New File:** `src/hashall/link_query.py`

**Functions:**
```python
def get_plan(conn: sqlite3.Connection, plan_id: int) -> Optional[LinkPlan]:
    """Fetch plan by ID."""
    pass

def get_plan_actions(conn: sqlite3.Connection, plan_id: int, limit: int = 0) -> List[LinkAction]:
    """Fetch actions for plan, optionally limited."""
    pass
```

**Acceptance Criteria:**
- [ ] Queries work
- [ ] Joins efficient
- [ ] Limit/pagination supported

### Task 1.4.3: Testing

**Tests:** `tests/test_link_show_plan.py`

**Test Scenarios:**
1. Show existing plan
2. Plan not found (error handling)
3. Large plan with limit
4. JSON output format

**Acceptance Criteria:**
- [ ] Tests pass
- [ ] Coverage >80%

---

## Task 1.5: Link Execute Command (Priority: CRITICAL)

**Estimated Effort:** 4 days
**Depends On:** All previous tasks
**Status:** ⏳ BLOCKED

### Task 1.5.1: CLI Interface

**Command Signature:**
```python
@link.command("execute")
@click.argument("plan_id", type=int)
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
@click.option("--dry-run", is_flag=True, help="Preview without making changes")
@click.option("--force", is_flag=True, help="Execute (cannot use with --dry-run)")
@click.option("--skip-backup", is_flag=True, help="Skip .bak file creation (faster but less safe)")
def link_execute(plan_id, db, dry_run, force, skip_backup):
    """
    Execute a deduplication plan.

    IMPORTANT: Review plan with 'show-plan' first!
    Use --dry-run to preview changes before executing.
    """
    if dry_run == force:
        raise click.UsageError("Must specify exactly one of --dry-run or --force")
    pass
```

**Acceptance Criteria:**
- [ ] Mutually exclusive flags enforced
- [ ] Confirmation prompt (unless --force)
- [ ] Clear warnings about data modification

### Task 1.5.2: Execution Engine

**New File:** `src/hashall/link_executor.py`

**Core Functions:**
```python
import os
import shutil
from pathlib import Path
from tqdm import tqdm

class LinkExecutor:
    """Execute hardlink deduplication plans."""

    def __init__(self, conn: sqlite3.Connection, dry_run: bool = False, skip_backup: bool = False):
        self.conn = conn
        self.dry_run = dry_run
        self.skip_backup = skip_backup
        self.stats = ExecutionStats()

    def execute_plan(self, plan_id: int) -> ExecutionStats:
        """
        Execute a plan.

        Process:
        1. Load plan and actions
        2. Validate plan (status = pending)
        3. Update plan status = in_progress
        4. For each action:
           a. Verify files exist
           b. Verify same device
           c. Backup target (unless --skip-backup)
           d. Create hardlink
           e. Verify inode matches
           f. Remove backup (or rollback)
           g. Update action status
        5. Update plan statistics
        6. Set plan status = completed
        """
        pass

    def execute_action(self, action: LinkAction) -> bool:
        """
        Execute a single hardlink action.

        Steps:
        1. Verify source exists
        2. Verify target exists
        3. Check same device
        4. Backup target → target.bak
        5. Remove target
        6. Create hardlink: ln source target
        7. Verify inodes match
        8. Remove backup
        9. Return success

        Error Handling:
        - If any step fails, rollback from backup
        - Log error
        - Continue with next action (don't abort entire plan)
        """
        pass

    def verify_action(self, canonical: Path, duplicate: Path) -> bool:
        """Verify inodes match after linking."""
        pass

    def rollback_action(self, action: LinkAction, backup_path: Path):
        """Restore from backup on failure."""
        pass

@dataclass
class ExecutionStats:
    """Execution statistics."""
    actions_total: int = 0
    actions_executed: int = 0
    actions_failed: int = 0
    actions_skipped: int = 0
    bytes_saved: int = 0
    errors: List[str] = field(default_factory=list)
```

**Safety Features:**
1. **Verify before link:**
   - Files exist
   - Same device (stat st_dev)
   - Not already hardlinked (same inode)

2. **Backup before modify:**
   - Copy target → target.bak
   - Only remove backup on success

3. **Verify after link:**
   - Check inodes match
   - If not, rollback

4. **Transaction-like:**
   - Each action independent
   - Failure in one doesn't abort plan
   - All successes/failures recorded

**Acceptance Criteria:**
- [ ] Executor class implemented
- [ ] All safety features work
- [ ] Rollback mechanism tested
- [ ] Progress bars (tqdm)
- [ ] Statistics accurate

### Task 1.5.3: Testing

**Unit Tests:** `tests/test_link_executor.py`
**Integration Tests:** `tests/test_link_execute_cli.py`

**Critical Test Scenarios:**
1. **Happy path:** All actions succeed
2. **Partial failure:** Some actions fail, plan continues
3. **Rollback:** Action fails, backup restored
4. **Already linked:** Skip actions where inodes already match (NOOP)
5. **Cross-device error:** Reject actions on different devices
6. **Missing files:** Handle gracefully
7. **Permission errors:** Handle gracefully
8. **Dry-run:** No actual modifications
9. **Large plan:** 1000+ actions with progress bar

**Acceptance Criteria:**
- [ ] All tests pass
- [ ] Coverage >90% (critical safety code)
- [ ] Failure scenarios tested thoroughly

---

## Task 1.6: Documentation & Integration (Priority: MEDIUM)

**Estimated Effort:** 1 day
**Depends On:** All implementation tasks
**Status:** ⏳ BLOCKED

### Task 1.6.1: Update CLI Documentation

**File:** `docs/tooling/cli.md`

Add complete reference for all 4 link commands:
- `link analyze` with examples
- `link plan` with examples
- `link show-plan` with examples
- `link execute` with safety warnings

**Acceptance Criteria:**
- [ ] All commands documented
- [ ] Examples work
- [ ] Warnings clear

### Task 1.6.2: Update Link Guide

**File:** `docs/tooling/link-guide.md`

Update with actual implementation:
- Remove "planned" language
- Add real command examples
- Add troubleshooting section
- Add best practices

**Acceptance Criteria:**
- [ ] Guide accurate
- [ ] Examples tested
- [ ] Beginner-friendly

### Task 1.6.3: Update Requirements

**File:** `docs/REQUIREMENTS.md`

Update Section 11 (Implementation Status):
- Mark link deduplication as ✅ Complete
- Update CLI command inventory
- Update implementation notes

**Acceptance Criteria:**
- [ ] Status accurate
- [ ] Matches reality

### Task 1.6.4: Update README

**File:** `README.md`

Add link deduplication to quick-start:
```bash
# 2. Find Deduplication Opportunities
hashall link analyze --device /pool

# 3. Create a Deduplication Plan
hashall link plan "Monthly dedupe" --device /pool

# 4. Review and Execute
hashall link show-plan 1
hashall link execute 1 --dry-run
hashall link execute 1 --force
```

**Acceptance Criteria:**
- [ ] Quick-start updated
- [ ] Examples tested
- [ ] Feature section added

---

## Sprint 1 Success Criteria (Final Checklist)

### Functionality
- [ ] All 4 link commands work end-to-end
- [ ] Database schema deployed
- [ ] Plans persist correctly
- [ ] Execution engine safe and reliable
- [ ] Dry-run mode accurate

### Quality
- [ ] Test coverage >80% overall
- [ ] Critical paths have >90% coverage
- [ ] All edge cases tested
- [ ] Performance acceptable (1000+ action plans)

### Documentation
- [ ] All commands documented
- [ ] User guide complete
- [ ] Implementation status updated
- [ ] Quick-start includes link workflow

### User Validation
- [ ] Beta tested by 1-2 users
- [ ] Feedback incorporated
- [ ] No critical bugs
- [ ] Workflow is intuitive

---

## Task Dependencies Graph

```
1.1 Database Schema
  ├─ BLOCKS → 1.2 Link Analyze
  ├─ BLOCKS → 1.3 Link Plan
  ├─ BLOCKS → 1.4 Show Plan
  └─ BLOCKS → 1.5 Execute

1.2 Link Analyze
  └─ BLOCKS → 1.3 Link Plan

1.3 Link Plan
  ├─ BLOCKS → 1.4 Show Plan
  └─ BLOCKS → 1.5 Execute

1.4 Show Plan
  └─ (independent, can work in parallel with 1.5)

1.5 Link Execute
  └─ BLOCKS → 1.6 Documentation

1.6 Documentation
  └─ (final task)
```

---

## Daily Stand-up Template

**What did you complete yesterday?**
**What will you work on today?**
**Any blockers?**

---

## Definition of Done (Per Task)

- [ ] Code written and works locally
- [ ] Unit tests written and passing
- [ ] Integration tests passing
- [ ] Code reviewed (if applicable)
- [ ] Documentation updated
- [ ] Merged to main branch
- [ ] Deployed/migrated (for schema changes)

---

**Sprint Start Date:** 2026-02-02
**Target Completion:** 2026-02-23 (3 weeks)
**Status:** 🚀 IN PROGRESS - Starting with Task 1.1
