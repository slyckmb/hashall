-- Migration 0008: Add Link Deduplication Tables
-- Created: 2026-02-02
-- Purpose: Support link deduplication workflow (analyze, plan, execute)
--
-- Tables:
--   - link_plans: Deduplication plan metadata
--   - link_actions: Individual hardlink actions within a plan
--
-- Usage:
--   Plans are created by 'hashall link plan' command
--   Actions are executed by 'hashall link execute' command
--   Status tracking enables resume and audit trail

-- ============================================================================
-- Link Plans Table
-- ============================================================================
-- Stores deduplication plan metadata and execution statistics
--
-- Status flow: pending → in_progress → completed/failed/cancelled

CREATE TABLE IF NOT EXISTS link_plans (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Plan identification
    name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending' CHECK(
        status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')
    ),

    -- Device context
    device_id INTEGER NOT NULL,
    device_alias TEXT,
    mount_point TEXT,

    -- Opportunity metrics (set at plan creation)
    total_opportunities INTEGER NOT NULL DEFAULT 0,  -- Number of duplicate groups

    -- Space metrics (bytes)
    total_bytes_saveable INTEGER NOT NULL DEFAULT 0,  -- Potential savings
    total_bytes_saved INTEGER DEFAULT 0,              -- Actual savings (after execution)

    -- Action counts (set at plan creation)
    actions_total INTEGER NOT NULL DEFAULT 0,

    -- Execution metrics (updated during execution)
    actions_executed INTEGER DEFAULT 0,
    actions_failed INTEGER DEFAULT 0,
    actions_skipped INTEGER DEFAULT 0,

    -- Timing
    started_at TEXT,     -- When execution started
    completed_at TEXT,   -- When execution finished

    -- Notes and extensibility
    notes TEXT,          -- Human-readable notes
    metadata TEXT,       -- JSON blob for future extensibility

    -- Foreign key to devices table
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

-- ============================================================================
-- Link Actions Table
-- ============================================================================
-- Stores individual hardlink actions for a plan
--
-- Action types:
--   - HARDLINK: Replace duplicate with hardlink to canonical
--   - SKIP: Duplicate cannot be linked (e.g., already same inode)
--   - NOOP: No action needed (informational)
--
-- Status flow: pending → in_progress → completed/failed/skipped

CREATE TABLE IF NOT EXISTS link_actions (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Plan association
    plan_id INTEGER NOT NULL,

    -- Action details
    action_type TEXT NOT NULL CHECK(
        action_type IN ('HARDLINK', 'SKIP', 'NOOP')
    ),
    status TEXT DEFAULT 'pending' CHECK(
        status IN ('pending', 'in_progress', 'completed', 'failed', 'skipped')
    ),

    -- File paths
    canonical_path TEXT NOT NULL,  -- The file to keep (source of truth)
    duplicate_path TEXT NOT NULL,  -- The file to replace with hardlink

    -- File metadata (for verification and auditing)
    canonical_inode INTEGER,       -- Inode of canonical file (before linking)
    duplicate_inode INTEGER,       -- Inode of duplicate file (before linking)
    device_id INTEGER NOT NULL,
    file_size INTEGER,             -- Size in bytes
    sha256 TEXT,                   -- Future-proof: SHA256 hash for verification

    -- Space savings
    bytes_to_save INTEGER NOT NULL DEFAULT 0,  -- Expected savings (file_size)
    bytes_saved INTEGER DEFAULT 0,             -- Actual savings (after execution)

    -- Execution details
    executed_at TEXT,              -- When action was executed
    error_message TEXT,            -- If failed, why?
    backup_path TEXT,              -- Path to .bak file if created

    -- Foreign keys
    FOREIGN KEY (plan_id) REFERENCES link_plans(id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(device_id)
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Link Plans Indexes
CREATE INDEX IF NOT EXISTS idx_link_plans_status
    ON link_plans(status);

CREATE INDEX IF NOT EXISTS idx_link_plans_device
    ON link_plans(device_id);

CREATE INDEX IF NOT EXISTS idx_link_plans_created
    ON link_plans(created_at DESC);

-- Link Actions Indexes
CREATE INDEX IF NOT EXISTS idx_link_actions_plan
    ON link_actions(plan_id);

CREATE INDEX IF NOT EXISTS idx_link_actions_status
    ON link_actions(status);

CREATE INDEX IF NOT EXISTS idx_link_actions_device
    ON link_actions(device_id);

CREATE INDEX IF NOT EXISTS idx_link_actions_type
    ON link_actions(action_type);

-- Composite index for common query: actions by plan and status
CREATE INDEX IF NOT EXISTS idx_link_actions_plan_status
    ON link_actions(plan_id, status);

-- ============================================================================
-- Notes on Design Decisions
-- ============================================================================
--
-- 1. Why separate link_plans and link_actions tables?
--    - Plans are long-lived metadata (can be reviewed later)
--    - Actions are many-to-one with plans (1 plan = 1000+ actions)
--    - Separation enables efficient queries and updates
--
-- 2. Why track both "to_save" and "saved"?
--    - to_save: Expected savings (set at plan creation)
--    - saved: Actual savings (set at execution)
--    - Allows validation and detection of unexpected changes
--
-- 3. Why include device_id in both tables?
--    - Plans are device-scoped (dedup only works within device)
--    - Actions inherit device from plan (denormalized for query speed)
--    - Foreign key to devices table ensures referential integrity
--
-- 4. Why sha256 instead of sha1?
--    - Future-proofing for SHA256 migration (Sprint 2)
--    - Can be NULL during SHA1-only period
--    - Enables verification after migration
--
-- 5. Why CHECK constraints?
--    - Enforces valid status values at database level
--    - Prevents application bugs from creating invalid data
--    - Self-documenting (schema shows valid values)
--
-- 6. Why ON DELETE CASCADE for link_actions?
--    - If plan is deleted, actions should be deleted too
--    - Actions have no meaning without their plan
--    - Prevents orphaned actions in database
--
-- 7. Why metadata TEXT (JSON blob)?
--    - Extensibility for future features without schema changes
--    - Can store custom attributes per plan
--    - Examples: filters, options, user preferences
--
-- ============================================================================
-- Migration Testing
-- ============================================================================
--
-- After applying this migration, verify:
--
-- 1. Tables exist:
--    sqlite3 catalog.db ".tables"
--    (should show link_plans and link_actions)
--
-- 2. Schema is correct:
--    sqlite3 catalog.db ".schema link_plans"
--    sqlite3 catalog.db ".schema link_actions"
--
-- 3. Indexes created:
--    sqlite3 catalog.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name LIKE 'link_%';"
--
-- 4. Can insert test data:
--    INSERT INTO link_plans (name, device_id, total_opportunities, actions_total)
--    VALUES ('Test Plan', 49, 1, 1);
--
--    INSERT INTO link_actions (plan_id, action_type, canonical_path, duplicate_path, device_id, file_size)
--    VALUES (1, 'HARDLINK', '/pool/file1.txt', '/pool/file2.txt', 49, 1024);
--
-- 5. Foreign keys work:
--    Try inserting action with invalid plan_id (should fail)
--    Try deleting plan (actions should cascade delete)
--
-- ============================================================================
