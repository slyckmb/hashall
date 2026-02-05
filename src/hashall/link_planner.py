"""
Link deduplication planner module.

This module provides functionality to create deduplication plans by analyzing
duplicate files and generating hardlink actions.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import sqlite3
from pathlib import Path

from hashall.link_analysis import analyze_device, DuplicateGroup


@dataclass
class LinkAction:
    """Single hardlink action within a plan.

    Attributes:
        action_type: Type of action (HARDLINK, SKIP, NOOP)
        canonical_path: Path to canonical file (to keep)
        duplicate_path: Path to duplicate file (to replace with hardlink)
        canonical_inode: Inode of canonical file
        duplicate_inode: Inode of duplicate file
        device_id: Device ID
        file_size: Size of file in bytes
        sha1: SHA1 hash (for verification)
        bytes_to_save: Bytes saved by this action
    """
    action_type: str
    canonical_path: str
    duplicate_path: str
    canonical_inode: int
    duplicate_inode: int
    device_id: int
    file_size: int
    sha1: str
    bytes_to_save: int


@dataclass
class LinkPlan:
    """Deduplication plan containing metadata and actions.

    Attributes:
        id: Plan ID (None before persistence)
        name: Human-readable plan name
        device_id: Device ID
        device_alias: Device alias
        mount_point: Device mount point
        total_opportunities: Number of duplicate groups
        total_bytes_saveable: Total bytes that could be saved
        actions_total: Total number of actions
        actions: List of link actions
    """
    id: Optional[int]
    name: str
    device_id: int
    device_alias: Optional[str]
    mount_point: str
    total_opportunities: int
    total_bytes_saveable: int
    actions_total: int
    actions: List[LinkAction] = field(default_factory=list)


def pick_canonical_file(
    files: List[str],
    inodes: List[int],
    conn: sqlite3.Connection,
    device_id: int
) -> Tuple[str, int]:
    """
    Choose which file to keep as the canonical copy.

    Strategy:
    1. Prefer lowest inode (oldest file, likely original)
    2. If inodes are equal (already hardlinked), choose shortest path
    3. If paths equal length, choose alphabetically first

    Args:
        files: List of file paths with same content
        inodes: List of inodes corresponding to files
        conn: Database connection (for future inode lookup if needed)
        device_id: Device ID

    Returns:
        Tuple of (canonical_path, canonical_inode)
    """
    if not files or not inodes:
        raise ValueError("Cannot pick canonical file from empty list")

    # Build list of (path, inode) tuples
    file_inode_pairs = list(zip(files, inodes))

    # Sort by:
    # 1. Lowest inode (oldest file)
    # 2. Shortest path (simpler path)
    # 3. Alphabetical (deterministic)
    sorted_pairs = sorted(
        file_inode_pairs,
        key=lambda x: (x[1], len(x[0]), x[0])
    )

    canonical_path, canonical_inode = sorted_pairs[0]
    return canonical_path, canonical_inode


def create_plan(
    conn: sqlite3.Connection,
    name: str,
    device_id: int,
    min_size: int = 0
) -> LinkPlan:
    """
    Generate a deduplication plan.

    Steps:
    1. Run analysis to find duplicate groups
    2. For each duplicate group:
       - Pick canonical file (to keep)
       - Generate HARDLINK actions for other files
    3. Build LinkPlan object with all actions

    Args:
        conn: Database connection
        name: Human-readable plan name
        device_id: Device ID to analyze
        min_size: Minimum file size in bytes (default: 0)

    Returns:
        LinkPlan object (not yet persisted to database)

    Raises:
        ValueError: If device not found or invalid parameters
    """
    # Run analysis
    analysis_result = analyze_device(conn, device_id, min_size=min_size)

    if not analysis_result.duplicate_groups:
        # No duplicates found, return empty plan
        return LinkPlan(
            id=None,
            name=name,
            device_id=device_id,
            device_alias=analysis_result.device_alias,
            mount_point=analysis_result.mount_point,
            total_opportunities=0,
            total_bytes_saveable=0,
            actions_total=0,
            actions=[]
        )

    # Generate actions for each duplicate group
    all_actions = []

    for group in analysis_result.duplicate_groups:
        # Pick canonical file
        canonical_path, canonical_inode = pick_canonical_file(
            group.files,
            group.inodes,
            conn,
            device_id
        )

        # Generate HARDLINK actions for all non-canonical files
        for file_path in group.files:
            if file_path == canonical_path:
                continue  # Skip canonical file

            # Get inode for this file
            cursor = conn.cursor()
            table_name = f"files_{device_id}"
            cursor.execute(
                f"SELECT inode FROM {table_name} WHERE path = ? AND status = 'active'",
                (file_path,)
            )
            row = cursor.fetchone()
            if not row:
                # File not found or inactive, skip
                continue

            duplicate_inode = row[0]

            # Create action
            action = LinkAction(
                action_type='HARDLINK',
                canonical_path=canonical_path,
                duplicate_path=file_path,
                canonical_inode=canonical_inode,
                duplicate_inode=duplicate_inode,
                device_id=device_id,
                file_size=group.file_size,
                sha1=group.hash,
                bytes_to_save=group.file_size  # Each duplicate saves file_size bytes
            )
            all_actions.append(action)

    # Build plan
    plan = LinkPlan(
        id=None,
        name=name,
        device_id=device_id,
        device_alias=analysis_result.device_alias,
        mount_point=analysis_result.mount_point,
        total_opportunities=len(analysis_result.duplicate_groups),
        total_bytes_saveable=analysis_result.potential_bytes_saveable,
        actions_total=len(all_actions),
        actions=all_actions
    )

    return plan


def save_plan(conn: sqlite3.Connection, plan: LinkPlan) -> int:
    """
    Persist plan to database.

    Transactions:
    1. INSERT into link_plans
    2. INSERT into link_actions (batch)
    3. Commit transaction

    Args:
        conn: Database connection
        plan: LinkPlan object to persist

    Returns:
        plan_id: ID of created plan

    Raises:
        sqlite3.Error: If database operations fail
    """
    cursor = conn.cursor()

    try:
        # Insert plan
        cursor.execute("""
            INSERT INTO link_plans (
                name, device_id, device_alias, mount_point,
                total_opportunities, total_bytes_saveable, actions_total,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
        """, (
            plan.name,
            plan.device_id,
            plan.device_alias,
            plan.mount_point,
            plan.total_opportunities,
            plan.total_bytes_saveable,
            plan.actions_total
        ))

        plan_id = cursor.lastrowid

        # Insert actions (batch)
        if plan.actions:
            action_values = [
                (
                    plan_id,
                    action.action_type,
                    action.canonical_path,
                    action.duplicate_path,
                    action.canonical_inode,
                    action.duplicate_inode,
                    action.device_id,
                    action.file_size,
                    action.sha1,  # sha256 column can be NULL for now
                    action.bytes_to_save,
                    'pending'  # status
                )
                for action in plan.actions
            ]

            cursor.executemany("""
                INSERT INTO link_actions (
                    plan_id, action_type, canonical_path, duplicate_path,
                    canonical_inode, duplicate_inode, device_id, file_size,
                    sha256, bytes_to_save, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, action_values)

        # Commit transaction
        conn.commit()

        return plan_id

    except Exception as e:
        # Rollback on error
        conn.rollback()
        raise


def format_plan_summary(plan: LinkPlan, plan_id: Optional[int] = None) -> str:
    """
    Format plan summary as human-readable text.

    Args:
        plan: LinkPlan object
        plan_id: Plan ID (if saved to database)

    Returns:
        Formatted text output
    """
    output = []

    # Header
    if plan_id is not None:
        output.append(f"📋 Plan #{plan_id}: {plan.name}")
    else:
        output.append(f"📋 Plan: {plan.name}")

    device_name = plan.device_alias or f"Device {plan.device_id}"
    output.append(f"   Device: {device_name} ({plan.device_id}) at {plan.mount_point}")
    output.append("")

    # Summary
    if plan.total_opportunities == 0:
        output.append("✅ No deduplication opportunities found")
        output.append("   All files are already unique or hardlinked")
        return "\n".join(output)

    output.append(f"   Total opportunities: {plan.total_opportunities:,} duplicate groups")
    output.append(f"   Actions generated: {plan.actions_total:,} hardlinks")

    savings_gb = plan.total_bytes_saveable / (1024**3)
    savings_mb = plan.total_bytes_saveable / (1024**2)
    if savings_gb >= 1.0:
        output.append(f"   Potential savings: {savings_gb:.2f} GB")
    else:
        output.append(f"   Potential savings: {savings_mb:.2f} MB")

    # Next steps
    if plan_id is not None:
        output.append("")
        output.append(f"   Review with: hashall link show-plan {plan_id}")
        output.append(f"   Execute with: hashall link execute {plan_id} --dry-run")

    return "\n".join(output)
