"""
Link deduplication query module.

This module provides functionality to query and display saved deduplication plans.
"""

from dataclasses import dataclass
from typing import List, Optional
import sqlite3
import json


@dataclass
class PlanInfo:
    """Plan metadata from database.

    Attributes:
        id: Plan ID
        name: Plan name
        status: Plan status (pending, in_progress, completed, failed, cancelled)
        created_at: Creation timestamp
        device_id: Device ID
        device_alias: Device alias
        mount_point: Device mount point
        total_opportunities: Number of duplicate groups
        total_bytes_saveable: Potential bytes to save
        total_bytes_saved: Actual bytes saved (after execution)
        actions_total: Total number of actions
        actions_executed: Number of executed actions
        actions_failed: Number of failed actions
        actions_skipped: Number of skipped actions
        started_at: Execution start time
        completed_at: Execution completion time
    """
    id: int
    name: str
    status: str
    created_at: str
    device_id: int
    device_alias: Optional[str]
    mount_point: Optional[str]
    total_opportunities: int
    total_bytes_saveable: int
    total_bytes_saved: int
    actions_total: int
    actions_executed: int
    actions_failed: int
    actions_skipped: int
    started_at: Optional[str]
    completed_at: Optional[str]

    @property
    def actions_pending(self) -> int:
        """Number of pending actions."""
        return self.actions_total - self.actions_executed - self.actions_failed - self.actions_skipped

    @property
    def is_completed(self) -> bool:
        """Whether plan execution is completed."""
        return self.status == 'completed'

    @property
    def is_in_progress(self) -> bool:
        """Whether plan execution is in progress."""
        return self.status == 'in_progress'

    @property
    def progress_percentage(self) -> float:
        """Execution progress as percentage (0-100)."""
        if self.actions_total == 0:
            return 100.0
        return (self.actions_executed / self.actions_total) * 100


@dataclass
class ActionInfo:
    """Action details from database.

    Attributes:
        id: Action ID
        plan_id: Parent plan ID
        action_type: Type of action (HARDLINK, SKIP, NOOP)
        status: Action status (pending, in_progress, completed, failed, skipped)
        canonical_path: Path to canonical file
        duplicate_path: Path to duplicate file
        canonical_inode: Canonical file inode
        duplicate_inode: Duplicate file inode
        device_id: Device ID
        file_size: File size in bytes
        sha256: SHA256 hash (optional)
        bytes_to_save: Expected bytes to save
        bytes_saved: Actual bytes saved
        executed_at: Execution timestamp
        error_message: Error message (if failed)
    """
    id: int
    plan_id: int
    action_type: str
    status: str
    canonical_path: str
    duplicate_path: str
    canonical_inode: Optional[int]
    duplicate_inode: Optional[int]
    device_id: int
    file_size: int
    sha256: Optional[str]
    bytes_to_save: int
    bytes_saved: int
    executed_at: Optional[str]
    error_message: Optional[str]


def get_plan(conn: sqlite3.Connection, plan_id: int) -> Optional[PlanInfo]:
    """
    Fetch plan by ID.

    Args:
        conn: Database connection
        plan_id: Plan ID to fetch

    Returns:
        PlanInfo object if found, None otherwise
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id, name, status, created_at,
            device_id, device_alias, mount_point,
            total_opportunities, total_bytes_saveable, total_bytes_saved,
            actions_total, actions_executed, actions_failed, actions_skipped,
            started_at, completed_at
        FROM link_plans
        WHERE id = ?
    """, (plan_id,))

    row = cursor.fetchone()
    if not row:
        return None

    return PlanInfo(
        id=row[0],
        name=row[1],
        status=row[2],
        created_at=row[3],
        device_id=row[4],
        device_alias=row[5],
        mount_point=row[6],
        total_opportunities=row[7],
        total_bytes_saveable=row[8],
        total_bytes_saved=row[9],
        actions_total=row[10],
        actions_executed=row[11],
        actions_failed=row[12],
        actions_skipped=row[13],
        started_at=row[14],
        completed_at=row[15]
    )


def get_plan_actions(
    conn: sqlite3.Connection,
    plan_id: int,
    limit: int = 0,
    order_by: str = 'bytes_to_save'
) -> List[ActionInfo]:
    """
    Fetch actions for a plan.

    Args:
        conn: Database connection
        plan_id: Plan ID
        limit: Maximum number of actions to return (0 = all)
        order_by: Sort field ('bytes_to_save', 'id', 'status')

    Returns:
        List of ActionInfo objects
    """
    cursor = conn.cursor()

    # Build query
    valid_order_fields = {
        'bytes_to_save': 'bytes_to_save DESC',
        'id': 'id ASC',
        'status': 'status, bytes_to_save DESC'
    }

    order_clause = valid_order_fields.get(order_by, 'bytes_to_save DESC')

    query = f"""
        SELECT
            id, plan_id, action_type, status,
            canonical_path, duplicate_path,
            canonical_inode, duplicate_inode,
            device_id, file_size, sha256,
            bytes_to_save, bytes_saved,
            executed_at, error_message
        FROM link_actions
        WHERE plan_id = ?
        ORDER BY {order_clause}
    """

    if limit > 0:
        query += f" LIMIT {limit}"

    cursor.execute(query, (plan_id,))

    actions = []
    for row in cursor.fetchall():
        actions.append(ActionInfo(
            id=row[0],
            plan_id=row[1],
            action_type=row[2],
            status=row[3],
            canonical_path=row[4],
            duplicate_path=row[5],
            canonical_inode=row[6],
            duplicate_inode=row[7],
            device_id=row[8],
            file_size=row[9],
            sha256=row[10],
            bytes_to_save=row[11],
            bytes_saved=row[12],
            executed_at=row[13],
            error_message=row[14]
        ))

    return actions


def list_plans(conn: sqlite3.Connection, status: Optional[str] = None) -> List[PlanInfo]:
    """
    List all plans, optionally filtered by status.

    Args:
        conn: Database connection
        status: Filter by status (None = all plans)

    Returns:
        List of PlanInfo objects, sorted by creation date (newest first)
    """
    cursor = conn.cursor()

    if status:
        query = """
            SELECT
                id, name, status, created_at,
                device_id, device_alias, mount_point,
                total_opportunities, total_bytes_saveable, total_bytes_saved,
                actions_total, actions_executed, actions_failed, actions_skipped,
                started_at, completed_at
            FROM link_plans
            WHERE status = ?
            ORDER BY created_at DESC
        """
        cursor.execute(query, (status,))
    else:
        query = """
            SELECT
                id, name, status, created_at,
                device_id, device_alias, mount_point,
                total_opportunities, total_bytes_saveable, total_bytes_saved,
                actions_total, actions_executed, actions_failed, actions_skipped,
                started_at, completed_at
            FROM link_plans
            ORDER BY created_at DESC
        """
        cursor.execute(query)

    plans = []
    for row in cursor.fetchall():
        plans.append(PlanInfo(
            id=row[0],
            name=row[1],
            status=row[2],
            created_at=row[3],
            device_id=row[4],
            device_alias=row[5],
            mount_point=row[6],
            total_opportunities=row[7],
            total_bytes_saveable=row[8],
            total_bytes_saved=row[9],
            actions_total=row[10],
            actions_executed=row[11],
            actions_failed=row[12],
            actions_skipped=row[13],
            started_at=row[14],
            completed_at=row[15]
        ))

    return plans


def format_plan_details(plan: PlanInfo, actions: List[ActionInfo], limit: int = 10) -> str:
    """
    Format plan and actions as human-readable text.

    Args:
        plan: PlanInfo object
        actions: List of ActionInfo objects
        limit: Number of actions to display

    Returns:
        Formatted text output
    """
    output = []

    # Header
    output.append(f"📋 Plan #{plan.id}: {plan.name}")
    output.append(f"   Status: {plan.status}")
    output.append(f"   Created: {plan.created_at}")

    if plan.started_at:
        output.append(f"   Started: {plan.started_at}")
    if plan.completed_at:
        output.append(f"   Completed: {plan.completed_at}")

    output.append("")

    # Device info
    device_name = plan.device_alias or f"Device {plan.device_id}"
    output.append(f"   Device: {device_name} ({plan.device_id})")
    if plan.mount_point:
        output.append(f"   Mount point: {plan.mount_point}")
    output.append("")

    # Summary stats
    output.append("📊 Plan Summary:")
    output.append(f"   Total opportunities: {plan.total_opportunities:,} duplicate groups")
    output.append(f"   Total actions: {plan.actions_total:,}")

    savings_gb = plan.total_bytes_saveable / (1024**3)
    savings_mb = plan.total_bytes_saveable / (1024**2)
    if savings_gb >= 1.0:
        output.append(f"   Potential savings: {savings_gb:.2f} GB")
    else:
        output.append(f"   Potential savings: {savings_mb:.2f} MB")

    # Execution progress
    if plan.is_in_progress or plan.is_completed:
        output.append("")
        output.append("⚡ Execution Progress:")
        output.append(f"   Executed: {plan.actions_executed:,}")
        output.append(f"   Failed: {plan.actions_failed:,}")
        output.append(f"   Skipped: {plan.actions_skipped:,}")
        output.append(f"   Pending: {plan.actions_pending:,}")
        output.append(f"   Progress: {plan.progress_percentage:.1f}%")

        if plan.total_bytes_saved > 0:
            saved_gb = plan.total_bytes_saved / (1024**3)
            saved_mb = plan.total_bytes_saved / (1024**2)
            if saved_gb >= 1.0:
                output.append(f"   Actual savings: {saved_gb:.2f} GB")
            else:
                output.append(f"   Actual savings: {saved_mb:.2f} MB")

    # Actions list
    if actions:
        output.append("")
        action_count = min(limit, len(actions)) if limit > 0 else len(actions)
        if limit > 0 and len(actions) > limit:
            output.append(f"   Top {action_count} actions (by space savings):")
        else:
            output.append(f"   Actions ({action_count} total):")

        for i, action in enumerate(actions[:action_count], 1):
            size_mb = action.file_size / (1024**2)
            size_kb = action.file_size / 1024

            if size_mb >= 1.0:
                size_str = f"{size_mb:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            # Get filename from canonical path
            canonical_name = action.canonical_path.split('/')[-1]
            if len(canonical_name) > 50:
                canonical_name = canonical_name[:47] + "..."

            status_emoji = {
                'pending': '⏳',
                'in_progress': '⚡',
                'completed': '✅',
                'failed': '❌',
                'skipped': '⏭️'
            }.get(action.status, '❓')

            output.append(f"   {i:2d}. {status_emoji} {action.action_type} {size_str}")
            output.append(f"       Keep:    {action.canonical_path}")
            output.append(f"       Replace: {action.duplicate_path}")

            if action.error_message:
                output.append(f"       Error: {action.error_message}")

    output.append("")

    # Next steps
    if plan.status == 'pending':
        output.append(f"✅ Execute with: hashall link execute {plan.id} --dry-run")
    elif plan.status == 'in_progress':
        output.append(f"⚡ Resume with: hashall link execute {plan.id}")
    elif plan.status == 'completed':
        output.append(f"✅ Plan completed successfully")
    elif plan.status == 'failed':
        output.append(f"❌ Plan failed - review error messages above")

    return "\n".join(output)


def format_plan_details_json(plan: PlanInfo, actions: List[ActionInfo], limit: int = 0) -> str:
    """
    Format plan and actions as JSON.

    Args:
        plan: PlanInfo object
        actions: List of ActionInfo objects
        limit: Number of actions to include (0 = all)

    Returns:
        JSON string
    """
    action_list = actions[:limit] if limit > 0 else actions

    data = {
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "status": plan.status,
            "created_at": plan.created_at,
            "started_at": plan.started_at,
            "completed_at": plan.completed_at,
            "device": {
                "id": plan.device_id,
                "alias": plan.device_alias,
                "mount_point": plan.mount_point
            },
            "summary": {
                "total_opportunities": plan.total_opportunities,
                "total_bytes_saveable": plan.total_bytes_saveable,
                "total_bytes_saved": plan.total_bytes_saved,
                "actions_total": plan.actions_total,
                "actions_executed": plan.actions_executed,
                "actions_failed": plan.actions_failed,
                "actions_skipped": plan.actions_skipped,
                "actions_pending": plan.actions_pending,
                "progress_percentage": plan.progress_percentage
            }
        },
        "actions": [
            {
                "id": a.id,
                "type": a.action_type,
                "status": a.status,
                "canonical_path": a.canonical_path,
                "duplicate_path": a.duplicate_path,
                "canonical_inode": a.canonical_inode,
                "duplicate_inode": a.duplicate_inode,
                "file_size": a.file_size,
                "bytes_to_save": a.bytes_to_save,
                "bytes_saved": a.bytes_saved,
                "executed_at": a.executed_at,
                "error_message": a.error_message
            }
            for a in action_list
        ]
    }

    return json.dumps(data, indent=2)
