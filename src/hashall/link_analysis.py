"""
Link deduplication analysis module.

This module provides functionality to analyze a device catalog for deduplication
opportunities by finding files with identical content but different inodes.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import sqlite3
import json


@dataclass
class DuplicateGroup:
    """Group of files with same content but different inodes.

    Attributes:
        hash: SHA256 hash of file content
        file_size: Size of each file in bytes
        file_count: Total number of files with this hash
        unique_inodes: Number of distinct inodes (files not yet deduplicated)
        files: List of file paths
        inodes: List of unique inode numbers
        potential_savings: Bytes that could be saved by deduplication
    """
    hash: str
    file_size: int
    file_count: int
    unique_inodes: int
    files: List[str]
    inodes: List[int]
    potential_savings: int


@dataclass
class AnalysisResult:
    """Result of deduplication analysis for a device.

    Attributes:
        device_id: Device ID analyzed
        device_alias: Device alias (if set)
        mount_point: Device mount point
        total_files: Total number of active files on device
        duplicate_groups: List of duplicate groups found
    """
    device_id: int
    device_alias: Optional[str]
    mount_point: str
    total_files: int
    duplicate_groups: List[DuplicateGroup] = field(default_factory=list)

    @property
    def total_duplicates(self) -> int:
        """Total number of duplicate files across all groups."""
        return sum(g.file_count for g in self.duplicate_groups)

    @property
    def potential_bytes_saveable(self) -> int:
        """Total bytes that could be saved by deduplication."""
        return sum(g.potential_savings for g in self.duplicate_groups)


def analyze_device(
    conn: sqlite3.Connection,
    device_id: int,
    min_size: int = 0
) -> AnalysisResult:
    """
    Analyze a device for deduplication opportunities.

    Finds groups of files that have the same SHA256 hash but different inodes,
    indicating they are duplicates that could be hardlinked together.

    Args:
        conn: Database connection
        device_id: Device ID to analyze
        min_size: Minimum file size in bytes (default: 0, analyze all files)

    Returns:
        AnalysisResult containing duplicate groups and statistics

    Raises:
        ValueError: If device_id is invalid or device table doesn't exist
    """
    cursor = conn.cursor()

    # Get device info
    cursor.execute(
        "SELECT device_id, device_alias, mount_point FROM devices WHERE device_id = ?",
        (device_id,)
    )
    dev_row = cursor.fetchone()

    if not dev_row:
        raise ValueError(f"Device {device_id} not found in catalog")

    device_alias, mount_point = dev_row[1], dev_row[2]

    # Check if device table exists
    table_name = f"files_{device_id}"
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    if not cursor.fetchone():
        raise ValueError(f"Table {table_name} does not exist in catalog")

    # Count total active files
    cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE status = 'active'")
    total_files = cursor.fetchone()[0]

    # Find duplicate groups (same hash, different inodes)
    query = f"""
    SELECT
        sha256,
        size,
        COUNT(*) as file_count,
        COUNT(DISTINCT inode) as unique_inodes,
        GROUP_CONCAT(path, '|||') as paths,
        (COUNT(DISTINCT inode) - 1) * size as potential_savings
    FROM {table_name}
    WHERE status = 'active'
      AND sha256 IS NOT NULL
      AND size >= ?
    GROUP BY sha256, size
    HAVING COUNT(DISTINCT inode) > 1
    ORDER BY potential_savings DESC
    """

    cursor.execute(query, (min_size,))

    duplicate_groups = []
    for row in cursor.fetchall():
        (
            hash_val,
            file_size,
            file_count,
            unique_inodes,
            paths_str,
            potential_savings
        ) = row

        files = paths_str.split('|||') if paths_str else []

        # Get distinct inodes for this hash
        cursor.execute(
            f"SELECT DISTINCT inode FROM {table_name} WHERE sha256 = ? AND status = 'active'",
            (hash_val,)
        )
        inodes = [row[0] for row in cursor.fetchall()]

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
    """
    Format analysis result as human-readable text.

    Args:
        result: AnalysisResult to format

    Returns:
        Formatted text output
    """
    output = []

    # Header
    device_name = result.device_alias or f"Device {result.device_id}"
    output.append(f"🔍 Analyzing device: {device_name}")
    output.append(f"   Mount point: {result.mount_point}")
    output.append(f"   Total files: {result.total_files:,}")
    output.append("")

    # Summary statistics
    output.append("📊 Deduplication Analysis:")
    output.append(f"   Duplicate groups found: {len(result.duplicate_groups):,}")
    output.append(f"   Total duplicates: {result.total_duplicates:,} files")

    savings_gb = result.potential_bytes_saveable / (1024**3)
    output.append(f"   Potential space savings: {savings_gb:.2f} GB")

    # Top duplicate groups
    if result.duplicate_groups:
        output.append("")
        output.append("   Top 10 duplicate groups:")
        for i, group in enumerate(result.duplicate_groups[:10], 1):
            size_mb = group.file_size / (1024**2)
            savings_mb = group.potential_savings / (1024**2)

            # Get filename from first path
            filename = group.files[0].split('/')[-1] if group.files else "unknown"
            if len(filename) > 50:
                filename = filename[:47] + "..."

            output.append(
                f"   {i:2d}. {group.file_count} copies × {size_mb:.1f} MB = "
                f"{savings_mb:.1f} MB savings - {filename}"
            )

    output.append("")

    # Next steps
    if result.duplicate_groups:
        output.append("✅ Use 'hashall link plan' to create a deduplication plan")
    else:
        output.append("✅ No deduplication opportunities found (all files already linked)")

    return "\n".join(output)


def format_analysis_json(result: AnalysisResult) -> str:
    """
    Format analysis result as JSON.

    Args:
        result: AnalysisResult to format

    Returns:
        JSON string
    """
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
