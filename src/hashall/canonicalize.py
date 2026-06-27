"""
Unified placement + path canonicalization orchestrator.

Wires DemotionPlanner (device placement) with save_path_inference (path structure)
to produce a single authoritative verdict per torrent.

Pipeline:
  1. Resolve catalog identity (torrent -> payload -> root_path, payload_hash)
  2. Determine canonical device via external consumer detection
  3. Determine canonical subdir via path inference
  4. Build canonical path (seeding_root / subdir / item_name)
  5. Cross-validate: drift dimensions + reuse + move_required
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from hashall.client_drift import ClientDriftPolicy, _placement_kind
from hashall.payload import get_torrent_instance, get_payload_by_id, get_payloads_by_hash
from hashall.pathing import canonicalize_path
from hashall.save_path_inference import (
    _STAGING_DIRS,
    infer_canonical_save_path,
    InferredSavePath,
)
from rehome.planner import DemotionPlanner


@dataclass
class CanonicalizeRequest:
    """All inputs needed to canonicalize a torrent's placement and path."""
    torrent_hash: str
    category: str
    tags: str
    save_path: str
    content_path: str
    rt_directory: str
    state: str


@dataclass
class ExternalConsumer:
    """External hardlink consumer for evidence in canonicalize verdict."""
    path: str
    inode: int
    domain: str


@dataclass
class CanonicalizeVerdict:
    """Structured drift report for a single torrent."""
    torrent_hash: str
    canonical_device: str
    canonical_seeding_root: str
    canonical_subdir: str
    canonical_path: str
    placement_drift: bool
    path_structure_drift: bool
    full_path_drift: bool
    reuse_possible: bool
    move_required: bool
    blocked: bool
    external_consumers: List[ExternalConsumer]
    inference_notes: List[str]
    reliability: str


@dataclass
class RepairPlan:
    """Actionable repair plan derived from a canonicalize verdict."""
    torrent_hash: str
    plan_type: str
    source_path: str
    target_path: str
    move_required: bool
    reuse_possible: bool
    notes: List[str]


@dataclass
class CanonicalizeConfig:
    """Shared context for canonicalization pipeline."""
    planner: DemotionPlanner
    policy: ClientDriftPolicy
    qbm_config_path: str = "/home/michael/dev/sys/docker/qbit_manage/config.yml"


_STASH_SEEDING_ROOT = "/stash/media/torrents/seeding"
_POOL_SEEDING_ROOT = "/pool/media/torrents/seeding"


def _path_under_staging_dir(path: str) -> bool:
    """Check if any path component matches a staging directory name."""
    if not path:
        return False
    parts = Path(path.rstrip("/")).parts
    return any(part in _STAGING_DIRS for part in parts)


def _convert_rehome_consumers(
    rehome_consumers: list,
    policy: ClientDriftPolicy,
) -> List[ExternalConsumer]:
    """Convert rehome.planner.ExternalConsumer list to local ExternalConsumer."""
    result: List[ExternalConsumer] = []
    for ec in rehome_consumers:
        link = ec.external_link_paths[0] if ec.external_link_paths else ec.file_path
        domain = "library"
        if policy.arr_library_roots:
            is_under_library = any(
                link.startswith(root) for root in policy.arr_library_roots
            )
            if not is_under_library:
                domain = "other"
        result.append(ExternalConsumer(
            path=link,
            inode=0,
            domain=domain,
        ))
    return result


def _extract_current_subdir(path: str, policy: ClientDriftPolicy) -> str:
    """Extract the subdir portion of a path relative to any known seeding root."""
    if not path:
        return ""
    for root in getattr(policy, "stash_roots", ()):
        if path.startswith(root):
            return path[len(root):].strip("/")
    for root in getattr(policy, "pool_roots", ()):
        if path.startswith(root):
            return path[len(root):].strip("/")
    return ""


def canonicalize_torrent(
    request: CanonicalizeRequest,
    db_session: sqlite3.Connection,
    config: CanonicalizeConfig,
) -> CanonicalizeVerdict:
    """
    Run the 5-step canonicalization pipeline for a single torrent.

    Steps:
      1. Resolve catalog identity
      2. Determine canonical device (placement)
      3. Determine canonical subdir (path structure)
      4. Build canonical path
      5. Cross-validate and finalize verdict

    Args:
        request: All qB/RT metadata for the torrent
        db_session: Open catalog database connection
        config: Shared context (planner, policy, qbm_config_path)

    Returns:
        CanonicalizeVerdict with all drift dimensions and evidence
    """
    planner = config.planner
    policy = config.policy
    notes: List[str] = []

    # --- Step 1: Resolve catalog identity ---
    torrent = get_torrent_instance(db_session, request.torrent_hash)
    if torrent is None:
        notes.append("torrent not found in catalog")
        return CanonicalizeVerdict(
            torrent_hash=request.torrent_hash,
            canonical_device="",
            canonical_seeding_root="",
            canonical_subdir="",
            canonical_path="",
            placement_drift=False,
            path_structure_drift=False,
            full_path_drift=False,
            reuse_possible=False,
            move_required=False,
            blocked=False,
            external_consumers=[],
            inference_notes=notes,
            reliability="transient",
        )

    payload = (
        get_payload_by_id(db_session, torrent.payload_id)
        if torrent.payload_id is not None
        else None
    )
    if payload is None:
        notes.append("payload not found for torrent instance")
        return CanonicalizeVerdict(
            torrent_hash=request.torrent_hash,
            canonical_device="",
            canonical_seeding_root="",
            canonical_subdir="",
            canonical_path="",
            placement_drift=False,
            path_structure_drift=False,
            full_path_drift=False,
            reuse_possible=False,
            move_required=False,
            blocked=False,
            external_consumers=[],
            inference_notes=notes,
            reliability="transient",
        )

    payload_hash = payload.payload_hash
    root_path = payload.root_path
    notes.append(f"catalog resolved: payload_hash={payload_hash}, root_path={root_path}")

    # --- Step 2: Determine canonical device ---
    planner._refresh_identity_cache(db_session)

    external_consumers_raw: list = []
    try:
        external_consumers_raw = planner._detect_external_consumers(
            db_session, root_path
        )
    except ValueError as e:
        notes.append(f"external consumer detection failed: {e}")

    has_external_consumers = len(external_consumers_raw) > 0
    external_consumers = _convert_rehome_consumers(external_consumers_raw, policy)
    ec_domains = {ec.domain for ec in external_consumers}

    if has_external_consumers:
        canonical_device = "stash"
        notes.append(
            f"external consumers found: {len(external_consumers)} consumer(s)"
        )
        if "library" in ec_domains:
            notes.append("library external consumers detected — device locked to stash")
    else:
        canonical_device = "pool"
        notes.append("no external consumers found — device is pool")

    current_device = _placement_kind(request.save_path, policy)
    if current_device == "other":
        current_device = _placement_kind(request.content_path, policy)
    if current_device == "other":
        stash_id = planner.stash_device
        pool_id = planner.pool_device
        if payload.device_id is not None:
            current_device = "stash" if payload.device_id == stash_id else "pool"
        else:
            current_device = canonical_device

    placement_drift = current_device != canonical_device
    blocked = has_external_consumers and placement_drift

    notes.append(
        f"current_device={current_device}, canonical_device={canonical_device}, "
        f"placement_drift={placement_drift}, blocked={blocked}"
    )

    # --- Step 3: Determine canonical subdir ---
    canonical_seeding_root = ""
    canonical_subdir = ""
    path_structure_drift = False
    inference_reliability: Optional[str] = None

    save_path_under_staging = _path_under_staging_dir(request.save_path)
    content_path_under_staging = _path_under_staging_dir(request.content_path)

    if save_path_under_staging or content_path_under_staging:
        notes.append("path under staging directory — transient, no path drift flagged")
        inference_reliability = "transient"

    try:
        inferred = infer_canonical_save_path(
            category=request.category,
            tags=request.tags,
            current_save_path=request.save_path,
            current_content_path=request.content_path,
            current_rt_directory=request.rt_directory,
            qbm_config_path=config.qbm_config_path,
        )

        inferred_path = Path(inferred.canonical_save_path.rstrip("/"))
        canonical_seeding_root = str(inferred_path.parent)
        canonical_subdir = inferred.subdir

        if inference_reliability is None:
            inference_reliability = inferred.reliability
        notes.extend(inferred.notes)

        if inference_reliability != "transient":
            current_path = request.save_path or request.content_path
            current_subdir = _extract_current_subdir(current_path, policy)
            if current_subdir and canonical_subdir:
                path_structure_drift = current_subdir != canonical_subdir
                notes.append(
                    f"current_subdir={current_subdir}, canonical_subdir={canonical_subdir}, "
                    f"path_structure_drift={path_structure_drift}"
                )

    except Exception as e:
        notes.append(f"path inference failed: {e}")
        if inference_reliability is None:
            inference_reliability = "ambiguous"

    if not canonical_seeding_root:
        canonical_seeding_root = (
            _STASH_SEEDING_ROOT if canonical_device == "stash" else _POOL_SEEDING_ROOT
        )

    # --- Step 4: Build canonical path ---
    item_name = (
        Path(request.content_path.rstrip("/")).name
        if request.content_path
        else Path(request.save_path.rstrip("/")).name
    )

    canonical_path = (
        f"{canonical_seeding_root}/{canonical_subdir}/{item_name}".rstrip("/")
    )
    canonical_path = str(canonicalize_path(Path(canonical_path)))

    # --- Step 5: Cross-validate and finalize ---
    full_path_drift = False
    if request.save_path:
        normalized_save = str(canonicalize_path(Path(request.save_path.rstrip("/"))))
        normalized_canon = str(canonicalize_path(Path(canonical_path.rstrip("/"))))
        full_path_drift = normalized_save != normalized_canon

    if not full_path_drift and request.rt_directory:
        normalized_rt = str(
            canonicalize_path(Path(request.rt_directory.rstrip("/")))
        )
        full_path_drift = normalized_rt != normalized_canon

    reuse_possible = False
    if payload_hash:
        if canonical_device == "pool":
            existing = planner._payload_exists_on_pool(db_session, payload_hash)
            if existing:
                reuse_possible = True
                notes.append(f"payload exists on pool at {existing}")
        elif canonical_device == "stash":
            stash_payloads = get_payloads_by_hash(
                db_session, payload_hash,
                device_id=planner.stash_device,
            )
            for p in stash_payloads:
                if p.root_path and p.root_path.rstrip("/") == canonical_path.rstrip("/"):
                    reuse_possible = True
                    notes.append(f"payload exists on stash at {canonical_path}")
                    break

    move_required = placement_drift and not reuse_possible

    reliability: str = inference_reliability if inference_reliability is not None else "reliable"

    return CanonicalizeVerdict(
        torrent_hash=request.torrent_hash,
        canonical_device=canonical_device,
        canonical_seeding_root=canonical_seeding_root,
        canonical_subdir=canonical_subdir,
        canonical_path=canonical_path,
        placement_drift=placement_drift,
        path_structure_drift=path_structure_drift,
        full_path_drift=full_path_drift,
        reuse_possible=reuse_possible,
        move_required=move_required,
        blocked=blocked,
        external_consumers=external_consumers,
        inference_notes=notes,
        reliability=reliability,
    )


def generate_repair_plan(verdict: CanonicalizeVerdict) -> RepairPlan:
    """Generate a repair plan from a canonicalize verdict."""
    if verdict.blocked:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="blocked",
            source_path=verdict.canonical_path,
            target_path="",
            move_required=False,
            reuse_possible=False,
            notes=verdict.inference_notes
            + ["blocked: external consumers prevent repair"],
        )

    if not verdict.placement_drift and not verdict.path_structure_drift:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="ok",
            source_path=verdict.canonical_path,
            target_path=verdict.canonical_path,
            move_required=False,
            reuse_possible=True,
            notes=verdict.inference_notes + ["already canonical"],
        )

    move_required = verdict.move_required
    reuse_possible = verdict.reuse_possible

    if verdict.placement_drift and verdict.path_structure_drift:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="fix_both",
            source_path=verdict.canonical_path,
            target_path=verdict.canonical_path,
            move_required=move_required,
            reuse_possible=reuse_possible,
            notes=verdict.inference_notes
            + ["placement and path both need fixing"],
        )

    if verdict.placement_drift:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="fix_placement_only",
            source_path=verdict.canonical_path,
            target_path=verdict.canonical_path,
            move_required=move_required,
            reuse_possible=reuse_possible,
            notes=verdict.inference_notes + ["placement drift only"],
        )

    return RepairPlan(
        torrent_hash=verdict.torrent_hash,
        plan_type="fix_path_only",
        source_path=verdict.canonical_path,
        target_path=verdict.canonical_path,
        move_required=False,
        reuse_possible=True,
        notes=verdict.inference_notes + ["path structure drift only"],
    )
