"""
Lane 1 dry-run plan generator.

Reads canonical path resolver output for all CATEGORY_DRIFT items and
produces a rename plan with pre-flight safety checks. No filesystem
mutations are performed.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from .canonical_path_resolver import DriftType, ItemResolution, STASH_ROOT, POOL_ROOT

SEEDING_ROOTS = (STASH_ROOT, POOL_ROOT)


@dataclass
class Lane1PlanItem:
    torrent_hash: str
    name: str
    item_type: str
    canonical_path: str
    canonical_content_path: str
    source_dir: Optional[str]
    target_dir: str
    source_exists: bool
    target_exists: bool
    same_device: bool
    safe: bool
    notes: list[str] = field(default_factory=list)


def _resolve_source_dir(resolution: ItemResolution) -> Optional[str]:
    """Pick best source path: prefer qB save_path, fall back to RT directory."""
    if resolution.qb_diff.actual_path:
        return resolution.qb_diff.actual_path
    if resolution.rt_diff.actual_path:
        return resolution.rt_diff.actual_path
    return None


def _check_same_device(source_dir: str, target_dir: str) -> tuple[bool, Optional[str]]:
    """Check if source_dir and target parent dir are on the same device.

    Returns (same_device, error_reason). Walks up from target parent until
    a directory that exists is found.
    """
    try:
        src_dev = os.stat(source_dir).st_dev
    except (OSError, FileNotFoundError) as e:
        return False, f"cannot stat source: {e}"

    # Walk up from target parent until we find a dir that exists
    parent = os.path.dirname(target_dir.rstrip("/"))
    while parent:
        if os.path.isdir(parent):
            try:
                tgt_dev = os.stat(parent).st_dev
                return src_dev == tgt_dev, None
            except OSError as e:
                return False, f"cannot stat target parent: {e}"
        parent = os.path.dirname(parent)

    return False, "no existing parent directory found for target"


def _seeding_root_of(path: Optional[str]) -> Optional[str]:
    """Return the seeding root prefix of path, or None if not under any known root."""
    if not path:
        return None
    norm = path.rstrip("/")
    for root in SEEDING_ROOTS:
        if norm == root or norm.startswith(root + "/"):
            return root
    return None


def _is_lane1_eligible(resolution: ItemResolution) -> bool:
    """
    Item qualifies for Lane 1 (same-root rename only):
    - Both clients CATEGORY_DRIFT, or one CATEGORY_DRIFT + one CANONICAL
    - Source path and canonical path are under the same seeding root

    Items with different seeding roots (compound drift) belong to Lane 2.
    """
    eligible_drifts = {DriftType.CATEGORY_DRIFT, DriftType.CANONICAL}
    if not (
        resolution.qb_diff.drift_type in eligible_drifts
        and resolution.rt_diff.drift_type in eligible_drifts
        and DriftType.CATEGORY_DRIFT in (
            resolution.qb_diff.drift_type, resolution.rt_diff.drift_type
        )
    ):
        return False

    # Compound drift check: source and canonical must share the same seeding root
    source_path = (
        resolution.qb_diff.actual_path
        or resolution.rt_diff.actual_path
    )
    canonical_path = resolution.canonical.canonical_path
    return _seeding_root_of(source_path) == _seeding_root_of(canonical_path)


def build_lane1_plan(resolutions: list[ItemResolution]) -> list[Lane1PlanItem]:
    """
    Given a list of ItemResolution objects, filter to Lane 1-eligible
    (CATEGORY_DRIFT) items and build a Lane1PlanItem for each with
    pre-flight safety checks.
    """
    plan: list[Lane1PlanItem] = []

    for res in resolutions:
        if not _is_lane1_eligible(res):
            continue

        source_dir = _resolve_source_dir(res)
        target_dir = res.canonical.canonical_content_path

        source_exists = False
        target_exists = False
        same_device = False
        notes: list[str] = []

        if source_dir:
            source_exists = os.path.isdir(source_dir) or os.path.isfile(source_dir)

        canonical_path = res.canonical.canonical_path
        category_dir_exists = bool(canonical_path and os.path.exists(canonical_path))

        if target_dir:
            target_exists = os.path.isdir(target_dir) or os.path.isfile(target_dir)

        if source_exists and source_dir:
            same_dev, err = _check_same_device(source_dir, target_dir)
            same_device = same_dev
            if err:
                notes.append(err)
        if category_dir_exists:
            notes.append(f"category dir already exists: {canonical_path}")

        safe = source_exists and not target_exists and same_device and not category_dir_exists

        plan.append(Lane1PlanItem(
            torrent_hash=res.torrent_hash,
            name=res.canonical.payload_name,
            item_type=res.canonical.item_type.value,
            canonical_path=res.canonical.canonical_path,
            canonical_content_path=target_dir,
            source_dir=source_dir,
            target_dir=target_dir,
            source_exists=source_exists,
            target_exists=target_exists,
            same_device=same_device,
            safe=safe,
            notes=notes,
        ))

    return plan
