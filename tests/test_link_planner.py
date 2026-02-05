"""
Unit tests for link_planner module.
"""

import sqlite3
import pytest

from hashall.link_planner import (
    LinkAction,
    LinkPlan,
    pick_canonical_file,
    create_plan,
    save_plan,
    format_plan_summary
)


@pytest.fixture
def test_db():
    """Create a test database with sample data."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Create devices table
    cursor.execute("""
        CREATE TABLE devices (
            device_id INTEGER PRIMARY KEY,
            device_alias TEXT,
            mount_point TEXT,
            fs_uuid TEXT,
            fs_type TEXT,
            total_files INTEGER,
            total_bytes INTEGER
        )
    """)

    # Create a test device
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (99, 'test_device', '/tmp/test', 'test-uuid-99')
    """)

    # Create files table
    cursor.execute("""
        CREATE TABLE files_99 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            quick_hash TEXT,
            sha1 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_modified_at TEXT DEFAULT CURRENT_TIMESTAMP,
            discovered_under TEXT
        )
    """)

    # Insert test data: duplicates for testing
    test_data = [
        # Group 1: 3 files with same hash, different inodes
        ('/test/group1/file1.txt', 1000, 'hash1', 101),
        ('/test/group1/file2.txt', 1000, 'hash1', 102),
        ('/test/file3_long_path.txt', 1000, 'hash1', 103),
        # Group 2: 2 files with same hash
        ('/test/dup1.txt', 500, 'hash2', 201),
        ('/test/dup2.txt', 500, 'hash2', 202),
        # Unique file (no duplicates)
        ('/test/unique.txt', 2000, 'hash3', 301),
    ]

    for path, size, sha1, inode in test_data:
        cursor.execute("""
            INSERT INTO files_99 (path, size, sha1, inode, mtime, status)
            VALUES (?, ?, ?, ?, 1234567890.0, 'active')
        """, (path, size, sha1, inode))

    # Create link_plans table
    cursor.execute("""
        CREATE TABLE link_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            device_id INTEGER NOT NULL,
            device_alias TEXT,
            mount_point TEXT,
            total_opportunities INTEGER NOT NULL DEFAULT 0,
            total_bytes_saveable INTEGER NOT NULL DEFAULT 0,
            total_bytes_saved INTEGER DEFAULT 0,
            actions_total INTEGER NOT NULL DEFAULT 0,
            actions_executed INTEGER DEFAULT 0,
            actions_failed INTEGER DEFAULT 0,
            actions_skipped INTEGER DEFAULT 0,
            started_at TEXT,
            completed_at TEXT,
            notes TEXT,
            metadata TEXT
        )
    """)

    # Create link_actions table
    cursor.execute("""
        CREATE TABLE link_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            canonical_path TEXT NOT NULL,
            duplicate_path TEXT NOT NULL,
            canonical_inode INTEGER,
            duplicate_inode INTEGER,
            device_id INTEGER NOT NULL,
            file_size INTEGER,
            sha256 TEXT,
            bytes_to_save INTEGER NOT NULL DEFAULT 0,
            bytes_saved INTEGER DEFAULT 0,
            executed_at TEXT,
            error_message TEXT,
            backup_path TEXT
        )
    """)

    conn.commit()
    yield conn
    conn.close()


def test_link_action_creation():
    """Test LinkAction dataclass creation."""
    action = LinkAction(
        action_type='HARDLINK',
        canonical_path='/keep/this.txt',
        duplicate_path='/replace/this.txt',
        canonical_inode=100,
        duplicate_inode=200,
        device_id=99,
        file_size=1000,
        sha1='testhash',
        bytes_to_save=1000
    )

    assert action.action_type == 'HARDLINK'
    assert action.canonical_path == '/keep/this.txt'
    assert action.duplicate_path == '/replace/this.txt'
    assert action.bytes_to_save == 1000


def test_link_plan_creation():
    """Test LinkPlan dataclass creation."""
    plan = LinkPlan(
        id=1,
        name='Test Plan',
        device_id=99,
        device_alias='test',
        mount_point='/test',
        total_opportunities=5,
        total_bytes_saveable=5000,
        actions_total=10,
        actions=[]
    )

    assert plan.name == 'Test Plan'
    assert plan.total_opportunities == 5
    assert plan.actions_total == 10


def test_pick_canonical_file_lowest_inode():
    """Test canonical file selection prefers lowest inode."""
    files = ['/b.txt', '/a.txt', '/c.txt']
    inodes = [200, 100, 300]  # Lowest inode is 100

    conn = sqlite3.connect(":memory:")
    canonical_path, canonical_inode = pick_canonical_file(files, inodes, conn, 99)

    assert canonical_inode == 100  # Lowest inode
    assert canonical_path == '/a.txt'  # Corresponding path

    conn.close()


def test_pick_canonical_file_shortest_path_on_tie():
    """Test canonical file selection prefers shortest path when inodes are equal."""
    files = ['/very/long/path.txt', '/short.txt', '/medium/path.txt']
    inodes = [100, 100, 100]  # All same inode

    conn = sqlite3.connect(":memory:")
    canonical_path, canonical_inode = pick_canonical_file(files, inodes, conn, 99)

    assert canonical_path == '/short.txt'  # Shortest path

    conn.close()


def test_pick_canonical_file_alphabetical_on_tie():
    """Test canonical file selection is alphabetical when inode and length are equal."""
    files = ['/c.txt', '/a.txt', '/b.txt']
    inodes = [100, 100, 100]  # All same inode

    conn = sqlite3.connect(":memory:")
    canonical_path, canonical_inode = pick_canonical_file(files, inodes, conn, 99)

    assert canonical_path == '/a.txt'  # Alphabetically first

    conn.close()


def test_pick_canonical_file_empty_list():
    """Test canonical file selection raises error on empty list."""
    conn = sqlite3.connect(":memory:")

    with pytest.raises(ValueError, match="empty list"):
        pick_canonical_file([], [], conn, 99)

    conn.close()


def test_create_plan_with_duplicates(test_db):
    """Test plan creation with duplicate files."""
    plan = create_plan(test_db, "Test Plan", device_id=99, min_size=0)

    assert plan.name == "Test Plan"
    assert plan.device_id == 99
    assert plan.device_alias == "test_device"
    assert plan.mount_point == "/tmp/test"

    # Should find 2 duplicate groups (hash1 and hash2)
    assert plan.total_opportunities == 2

    # Group 1: 3 files → 2 actions (keep 1, link 2)
    # Group 2: 2 files → 1 action (keep 1, link 1)
    # Total: 3 actions
    assert plan.actions_total == 3

    # Verify actions
    assert len(plan.actions) == 3
    assert all(action.action_type == 'HARDLINK' for action in plan.actions)

    # Check bytes_to_save
    # Group 1: 2 actions × 1000 bytes = 2000
    # Group 2: 1 action × 500 bytes = 500
    # Total: 2500 bytes
    assert plan.total_bytes_saveable == 2500


def test_create_plan_no_duplicates(test_db):
    """Test plan creation when no duplicates exist."""
    cursor = test_db.cursor()

    # Create new device with no duplicates
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (100, 'unique_device', '/tmp/unique', 'test-uuid-100')
    """)

    cursor.execute("""
        CREATE TABLE files_100 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    cursor.execute("""
        INSERT INTO files_100 (path, size, sha1, inode, mtime)
        VALUES ('/unique.txt', 1000, 'unique_hash', 1, 1234567890.0)
    """)

    test_db.commit()

    plan = create_plan(test_db, "Empty Plan", device_id=100)

    assert plan.total_opportunities == 0
    assert plan.actions_total == 0
    assert len(plan.actions) == 0
    assert plan.total_bytes_saveable == 0


def test_create_plan_min_size_filter(test_db):
    """Test plan creation with min_size filter."""
    # Only files >= 1000 bytes should be analyzed
    plan = create_plan(test_db, "Filtered Plan", device_id=99, min_size=1000)

    # Should only find hash1 group (1000 bytes)
    # hash2 group (500 bytes) should be filtered out
    assert plan.total_opportunities == 1
    assert plan.actions_total == 2  # 3 files in group → 2 actions


def test_save_plan(test_db):
    """Test saving plan to database."""
    plan = create_plan(test_db, "Save Test", device_id=99)

    # Save plan
    plan_id = save_plan(test_db, plan)

    assert plan_id > 0

    # Verify plan in database
    cursor = test_db.cursor()
    cursor.execute("SELECT name, device_id, total_opportunities, actions_total FROM link_plans WHERE id = ?", (plan_id,))
    row = cursor.fetchone()

    assert row[0] == "Save Test"
    assert row[1] == 99
    assert row[2] == 2  # 2 duplicate groups
    assert row[3] == 3  # 3 actions

    # Verify actions in database
    cursor.execute("SELECT COUNT(*) FROM link_actions WHERE plan_id = ?", (plan_id,))
    action_count = cursor.fetchone()[0]

    assert action_count == 3


def test_save_plan_empty(test_db):
    """Test saving empty plan (no duplicates)."""
    cursor = test_db.cursor()

    # Create device with no duplicates
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (100, 'unique_device', '/tmp/unique', 'test-uuid-100')
    """)

    cursor.execute("""
        CREATE TABLE files_100 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    cursor.execute("""
        INSERT INTO files_100 (path, size, sha1, inode, mtime)
        VALUES ('/unique.txt', 1000, 'unique_hash', 1, 1234567890.0)
    """)

    test_db.commit()

    plan = create_plan(test_db, "Empty Plan", device_id=100)
    plan_id = save_plan(test_db, plan)

    assert plan_id > 0

    # Verify plan saved with 0 actions
    cursor.execute("SELECT total_opportunities, actions_total FROM link_plans WHERE id = ?", (plan_id,))
    row = cursor.fetchone()
    assert row[0] == 0
    assert row[1] == 0


def test_format_plan_summary_with_duplicates(test_db):
    """Test plan summary formatting."""
    plan = create_plan(test_db, "Summary Test", device_id=99)
    text = format_plan_summary(plan, plan_id=1)

    assert "Plan #1: Summary Test" in text
    assert "test_device (99)" in text
    assert "/tmp/test" in text
    assert "2 duplicate groups" in text
    assert "3 hardlinks" in text
    assert "hashall link show-plan 1" in text
    assert "hashall link execute 1" in text


def test_format_plan_summary_no_duplicates(test_db):
    """Test plan summary formatting with no duplicates."""
    cursor = test_db.cursor()

    # Create device with no duplicates
    cursor.execute("""
        INSERT INTO devices (device_id, device_alias, mount_point, fs_uuid)
        VALUES (100, 'unique_device', '/tmp/unique', 'test-uuid-100')
    """)

    cursor.execute("""
        CREATE TABLE files_100 (
            path TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha1 TEXT,
            inode INTEGER NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    cursor.execute("""
        INSERT INTO files_100 (path, size, sha1, inode, mtime)
        VALUES ('/unique.txt', 1000, 'unique_hash', 1, 1234567890.0)
    """)

    test_db.commit()

    plan = create_plan(test_db, "Empty Plan", device_id=100)
    text = format_plan_summary(plan)

    assert "No deduplication opportunities found" in text
    assert "All files are already unique or hardlinked" in text
