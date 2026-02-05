"""
Unit tests for link_query module.
"""

import sqlite3
import pytest

from hashall.link_query import (
    PlanInfo,
    ActionInfo,
    get_plan,
    get_plan_actions,
    list_plans,
    format_plan_details,
    format_plan_details_json
)


@pytest.fixture
def test_db_with_plans():
    """Create a test database with sample plans and actions."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

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

    # Insert test plans
    cursor.execute("""
        INSERT INTO link_plans (
            id, name, status, created_at, device_id, device_alias, mount_point,
            total_opportunities, total_bytes_saveable, actions_total
        ) VALUES (1, 'Test Plan 1', 'pending', '2026-02-02 10:00:00', 99, 'test_device', '/tmp/test', 5, 5000, 10)
    """)

    cursor.execute("""
        INSERT INTO link_plans (
            id, name, status, created_at, device_id, device_alias, mount_point,
            total_opportunities, total_bytes_saveable, total_bytes_saved,
            actions_total, actions_executed, actions_failed, actions_skipped,
            started_at, completed_at
        ) VALUES (
            2, 'Completed Plan', 'completed', '2026-02-02 09:00:00', 99, 'test_device', '/tmp/test',
            3, 3000, 2500, 5, 4, 1, 0,
            '2026-02-02 11:00:00', '2026-02-02 12:00:00'
        )
    """)

    # Insert test actions for plan 1
    for i in range(3):
        cursor.execute("""
            INSERT INTO link_actions (
                plan_id, action_type, status, canonical_path, duplicate_path,
                canonical_inode, duplicate_inode, device_id, file_size, bytes_to_save
            ) VALUES (?, 'HARDLINK', 'pending', ?, ?, ?, ?, 99, ?, ?)
        """, (
            1,
            f'/test/canonical{i}.txt',
            f'/test/duplicate{i}.txt',
            100 + i,
            200 + i,
            1000 * (3 - i),  # Varying sizes for sorting
            1000 * (3 - i)
        ))

    conn.commit()
    yield conn
    conn.close()


def test_plan_info_properties():
    """Test PlanInfo computed properties."""
    plan = PlanInfo(
        id=1,
        name='Test',
        status='in_progress',
        created_at='2026-02-02',
        device_id=99,
        device_alias='test',
        mount_point='/test',
        total_opportunities=5,
        total_bytes_saveable=5000,
        total_bytes_saved=3000,
        actions_total=10,
        actions_executed=6,
        actions_failed=1,
        actions_skipped=1,
        started_at='2026-02-02 10:00',
        completed_at=None
    )

    assert plan.actions_pending == 2  # 10 - 6 - 1 - 1
    assert plan.is_in_progress == True
    assert plan.is_completed == False
    assert plan.progress_percentage == 60.0  # 6/10 * 100


def test_get_plan_found(test_db_with_plans):
    """Test retrieving an existing plan."""
    plan = get_plan(test_db_with_plans, plan_id=1)

    assert plan is not None
    assert plan.id == 1
    assert plan.name == 'Test Plan 1'
    assert plan.status == 'pending'
    assert plan.device_id == 99
    assert plan.device_alias == 'test_device'
    assert plan.mount_point == '/tmp/test'
    assert plan.total_opportunities == 5
    assert plan.total_bytes_saveable == 5000
    assert plan.actions_total == 10


def test_get_plan_not_found(test_db_with_plans):
    """Test retrieving a non-existent plan."""
    plan = get_plan(test_db_with_plans, plan_id=999)

    assert plan is None


def test_get_plan_actions_all(test_db_with_plans):
    """Test retrieving all actions for a plan."""
    actions = get_plan_actions(test_db_with_plans, plan_id=1, limit=0)

    assert len(actions) == 3
    assert all(isinstance(a, ActionInfo) for a in actions)
    assert all(a.plan_id == 1 for a in actions)

    # Should be sorted by bytes_to_save descending
    assert actions[0].bytes_to_save == 3000
    assert actions[1].bytes_to_save == 2000
    assert actions[2].bytes_to_save == 1000


def test_get_plan_actions_limited(test_db_with_plans):
    """Test retrieving limited actions."""
    actions = get_plan_actions(test_db_with_plans, plan_id=1, limit=2)

    assert len(actions) == 2
    # Should get top 2 by bytes_to_save
    assert actions[0].bytes_to_save == 3000
    assert actions[1].bytes_to_save == 2000


def test_get_plan_actions_empty(test_db_with_plans):
    """Test retrieving actions for plan with no actions."""
    actions = get_plan_actions(test_db_with_plans, plan_id=2, limit=0)

    assert len(actions) == 0


def test_list_plans_all(test_db_with_plans):
    """Test listing all plans."""
    plans = list_plans(test_db_with_plans)

    assert len(plans) == 2
    # Should be sorted by created_at DESC (newest first)
    assert plans[0].id == 1  # Created at 10:00
    assert plans[1].id == 2  # Created at 09:00


def test_list_plans_filtered_by_status(test_db_with_plans):
    """Test listing plans filtered by status."""
    # Get pending plans
    pending_plans = list_plans(test_db_with_plans, status='pending')
    assert len(pending_plans) == 1
    assert pending_plans[0].status == 'pending'

    # Get completed plans
    completed_plans = list_plans(test_db_with_plans, status='completed')
    assert len(completed_plans) == 1
    assert completed_plans[0].status == 'completed'

    # Get in_progress plans (none)
    in_progress_plans = list_plans(test_db_with_plans, status='in_progress')
    assert len(in_progress_plans) == 0


def test_format_plan_details_pending(test_db_with_plans):
    """Test formatting plan details for pending plan."""
    plan = get_plan(test_db_with_plans, plan_id=1)
    actions = get_plan_actions(test_db_with_plans, plan_id=1, limit=0)

    text = format_plan_details(plan, actions, limit=10)

    assert "Plan #1: Test Plan 1" in text
    assert "Status: pending" in text
    assert "test_device (99)" in text
    assert "/tmp/test" in text
    assert "5 duplicate groups" in text
    assert "10" in text  # actions_total
    assert "hashall link execute 1" in text

    # Should show actions
    assert "canonical0.txt" in text
    assert "duplicate0.txt" in text


def test_format_plan_details_completed(test_db_with_plans):
    """Test formatting plan details for completed plan."""
    plan = get_plan(test_db_with_plans, plan_id=2)
    actions = get_plan_actions(test_db_with_plans, plan_id=2, limit=0)

    text = format_plan_details(plan, actions, limit=10)

    assert "Plan #2: Completed Plan" in text
    assert "Status: completed" in text
    assert "Started: 2026-02-02 11:00:00" in text
    assert "Completed: 2026-02-02 12:00:00" in text

    # Should show execution progress
    assert "Execution Progress:" in text
    assert "Executed: 4" in text
    assert "Failed: 1" in text
    assert "Progress: 80.0%" in text  # 4/5 * 100

    # Should show actual savings
    assert "Actual savings:" in text

    assert "Plan completed successfully" in text


def test_format_plan_details_limit(test_db_with_plans):
    """Test formatting plan details with action limit."""
    plan = get_plan(test_db_with_plans, plan_id=1)
    actions = get_plan_actions(test_db_with_plans, plan_id=1, limit=0)

    text = format_plan_details(plan, actions, limit=2)

    assert "Top 2 actions" in text
    # Should only show first 2 actions
    assert text.count("HARDLINK") == 2


def test_format_plan_details_json(test_db_with_plans):
    """Test formatting plan details as JSON."""
    import json

    plan = get_plan(test_db_with_plans, plan_id=1)
    actions = get_plan_actions(test_db_with_plans, plan_id=1, limit=0)

    json_str = format_plan_details_json(plan, actions, limit=2)

    # Parse JSON to verify it's valid
    data = json.loads(json_str)

    assert data['plan']['id'] == 1
    assert data['plan']['name'] == 'Test Plan 1'
    assert data['plan']['status'] == 'pending'
    assert data['plan']['device']['id'] == 99
    assert data['plan']['device']['alias'] == 'test_device'
    assert data['plan']['summary']['total_opportunities'] == 5
    assert data['plan']['summary']['actions_total'] == 10
    assert data['plan']['summary']['progress_percentage'] == 0.0

    # Should have 2 actions (limit=2)
    assert len(data['actions']) == 2
    assert data['actions'][0]['type'] == 'HARDLINK'
    assert data['actions'][0]['status'] == 'pending'
