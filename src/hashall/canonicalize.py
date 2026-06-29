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

from __future__ import annotations

import os
import shutil
import subprocess
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hashall.qbittorrent import QBittorrentClient

from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)

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
class ApplyResult:
    """Result of applying a repair plan."""
    torrent_hash: str
    plan_type: str
    dry_run: bool
    success: bool
    pre_state: dict
    post_state: dict | None
    error: str | None
    notes: list[str]


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

    # Seeding root is determined by canonical device (Step 2), not path inference.
    # infer_canonical_save_path uses the RT container-view stash prefix (/data/media/);
    # we always use real paths (/stash/media/, /pool/media/) in verdicts and repair plans.
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


def generate_repair_plan(
    verdict: CanonicalizeVerdict,
    current_path: str = "",
) -> RepairPlan:
    """Generate a repair plan from a canonicalize verdict.

    Args:
        verdict: The canonicalize verdict from canonicalize_torrent().
        current_path: The actual current path of the torrent data (source).
            If empty, falls back to canonical_path for both source and target
            (backward compat with tests that don't assert paths).
    """
    src = current_path if current_path else verdict.canonical_path
    tgt = verdict.canonical_path

    if verdict.blocked:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="blocked",
            source_path=src,
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
            source_path=src,
            target_path=tgt,
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
            source_path=src,
            target_path=tgt,
            move_required=move_required,
            reuse_possible=reuse_possible,
            notes=verdict.inference_notes
            + ["placement and path both need fixing"],
        )

    if verdict.placement_drift:
        return RepairPlan(
            torrent_hash=verdict.torrent_hash,
            plan_type="fix_placement_only",
            source_path=src,
            target_path=tgt,
            move_required=move_required,
            reuse_possible=reuse_possible,
            notes=verdict.inference_notes + ["placement drift only"],
        )

    return RepairPlan(
        torrent_hash=verdict.torrent_hash,
        plan_type="fix_path_only",
        source_path=src,
        target_path=tgt,
        move_required=False,
        reuse_possible=True,
        notes=verdict.inference_notes + ["path structure drift only"],
    )


def _capture_rt_state(torrent_hash: str, rt_rpc_url: str) -> dict:
    """Read-only RT state snapshot."""
    result: dict = {"rt_directory": "", "rt_complete": -1}
    try:
        dir_xml = rt_xmlrpc_call("d.directory", torrent_hash, rpc_url=rt_rpc_url)
        result["rt_directory"] = _xmlrpc_scalar_text(dir_xml).rstrip("/")
    except Exception as e:
        result["rt_directory"] = f"<error: {e}>"
    try:
        comp_xml = rt_xmlrpc_call("d.complete", torrent_hash, rpc_url=rt_rpc_url)
        result["rt_complete"] = int(_xmlrpc_scalar_text(comp_xml).strip())
    except Exception as e:
        result["rt_complete"] = -1
    try:
        down_xml = rt_xmlrpc_call("d.down.rate", torrent_hash, rpc_url=rt_rpc_url)
        result["rt_down_rate"] = int(_xmlrpc_scalar_text(down_xml).strip())
    except Exception as e:
        result["rt_down_rate"] = -1
    return result


def _capture_qb_state(torrent_hash: str, qb_client: Optional[QBittorrentClient]) -> dict:
    """Read-only qB state snapshot. Returns empty dict if no client or lookup fails."""
    result: dict = {"qb_save_path": "", "qb_state": ""}
    if qb_client is None:
        result["qb_save_path"] = "<no-client>"
        result["qb_state"] = "<no-client>"
        return result
    try:
        info = qb_client.get_torrent_info(torrent_hash)
        if info:
            result["qb_save_path"] = info.save_path
            result["qb_state"] = info.state
        else:
            result["qb_save_path"] = "<not-found>"
            result["qb_state"] = "<not-found>"
    except Exception as e:
        result["qb_save_path"] = f"<error: {e}>"
        result["qb_state"] = f"<error: {e}>"
    return result


def _capture_pre_state(
    torrent_hash: str,
    qb_client: Optional[QBittorrentClient],
    rt_rpc_url: str,
) -> dict:
    """Capture combined pre-mutation state from RT and qB."""
    state = {}
    state.update(_capture_rt_state(torrent_hash, rt_rpc_url))
    state.update(_capture_qb_state(torrent_hash, qb_client))
    return state


def _get_payload_size_bytes(db_session: sqlite3.Connection, torrent_hash: str) -> int:
    """Look up total payload bytes for a torrent from catalog."""
    from hashall.payload import get_torrent_instance, get_payload_by_id
    try:
        torrent = get_torrent_instance(db_session, torrent_hash)
        if torrent and torrent.payload_id is not None:
            payload = get_payload_by_id(db_session, torrent.payload_id)
            if payload:
                return payload.total_bytes or 0
        return 0
    except Exception:
        return 0


def _execute_fix_path_only(
    plan: RepairPlan,
    db_session: sqlite3.Connection,
    config: CanonicalizeConfig,
    qb_client: Optional[QBittorrentClient],
    rt_rpc_url: str,
    pre_state: dict,
) -> ApplyResult:
    """Rename source dir to canonical path + repoint both clients."""
    from hashall.rtorrent import rt_apply_directory_repoint

    notes = list(plan.notes)
    src = plan.source_path.rstrip("/")
    tgt = plan.target_path.rstrip("/")

    if not src:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="source_path is empty", notes=notes,
        )
    if not tgt:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="target_path is empty", notes=notes,
        )

    if not os.path.exists(src):
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=f"source path does not exist: {src}",
            notes=notes,
        )

    if os.path.exists(tgt):
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=f"target path already exists: {tgt}",
            notes=notes,
        )

    # --- Rename ---
    try:
        parent = os.path.dirname(tgt)
        os.makedirs(parent, exist_ok=True)
        os.rename(src, tgt)
        renamed_ok = True
        notes.append(f"rename: {src} -> {tgt}")
    except OSError as e:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=f"rename failed: {e}", notes=notes,
        )

    # --- Repoint RT ---
    # RT appends info_name internally for multi-file torrents (d.directory.set semantics),
    # so we must pass the PARENT of the content path, not the content path itself.
    rt_target = os.path.dirname(tgt)
    rt_ok = False
    try:
        rt_apply_directory_repoint(
            plan.torrent_hash, rt_target,
            rpc_url=rt_rpc_url, restart=True, check_before_start=True,
            validate_target_exists=True,
        )
        rt_ok = True
        notes.append(f"RT repointed to {rt_target}")
    except Exception as e:
        notes.append(f"RT repoint failed: {e}")

    # --- Repoint qB ---
    qb_ok = False
    if qb_client:
        try:
            success = qb_client.set_location(plan.torrent_hash, tgt, resume_after=False)
            if success:
                qb_ok = True
                notes.append(f"qB set_location -> {tgt}")
            else:
                notes.append(f"qB set_location returned False")
        except Exception as e:
            notes.append(f"qB repoint error: {e}")
    else:
        notes.append("no qB client available — qB not repointed")

    # --- Rollback if either repoint failed ---
    if not rt_ok or (qb_client and not qb_ok):
        try:
            os.rename(tgt, src)
            notes.append(f"rollback rename: {tgt} -> {src}")
        except OSError as e:
            notes.append(f"rollback rename failed: {e}")

        error_parts = []
        if not rt_ok:
            error_parts.append("RT repoint failed")
        if qb_client and not qb_ok:
            error_parts.append("qB repoint failed")
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="; ".join(error_parts), notes=notes,
        )

    post_state = _capture_pre_state(plan.torrent_hash, qb_client, rt_rpc_url)
    return ApplyResult(
        torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
        dry_run=False, success=True, pre_state=pre_state,
        post_state=post_state, error=None, notes=notes,
    )


def _execute_fix_placement(
    plan: RepairPlan,
    db_session: sqlite3.Connection,
    config: CanonicalizeConfig,
    qb_client: Optional[QBittorrentClient],
    rt_rpc_url: str,
    pre_state: dict,
) -> ApplyResult:
    """Rsync source to canonical device+path + repoint both clients + stage source."""
    from hashall.rtorrent import rt_apply_directory_repoint

    notes = list(plan.notes)
    src = plan.source_path.rstrip("/")
    tgt = plan.target_path.rstrip("/")

    if not src:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="source_path is empty", notes=notes,
        )
    if not tgt:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="target_path is empty", notes=notes,
        )

    if not os.path.exists(src):
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=f"source path does not exist: {src}",
            notes=notes,
        )

    # --- Validate pool free space ---
    payload_size = _get_payload_size_bytes(db_session, plan.torrent_hash)
    target_parent = os.path.dirname(tgt)
    if payload_size > 0:
        try:
            usage = shutil.disk_usage(target_parent)
            if usage.free < payload_size:
                return ApplyResult(
                    torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
                    dry_run=False, success=False, pre_state=pre_state,
                    post_state=None,
                    error=f"insufficient space on target device: free={usage.free} < "
                          f"required={payload_size}",
                    notes=notes,
                )
            notes.append(f"space ok: free={usage.free} >= required={payload_size}")
        except OSError as e:
            notes.append(f"could not check disk space for {target_parent}: {e}")

    # --- Rsync ---
    src_is_file = os.path.isfile(src)
    if src_is_file:
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        rsync_args = [src, tgt]
    else:
        os.makedirs(tgt, exist_ok=True)
        rsync_args = [f"{src}/", f"{tgt}/"]
    try:
        rsync_cmd = ["rsync", "-a", "--hard-links"] + rsync_args
        notes.append(f"rsync: {' '.join(rsync_cmd)}")
        result = subprocess.run(
            rsync_cmd, capture_output=True, text=True, timeout=86400,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unknown rsync error"
            return ApplyResult(
                torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
                dry_run=False, success=False, pre_state=pre_state,
                post_state=None, error=f"rsync failed (exit={result.returncode}): {stderr}",
                notes=notes,
            )
        notes.append(f"rsync completed: {src} -> {tgt}")
    except subprocess.TimeoutExpired:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="rsync timed out after 24h", notes=notes,
        )
    except FileNotFoundError:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="rsync not found on PATH", notes=notes,
        )
    except OSError as e:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=f"rsync exec error: {e}", notes=notes,
        )

    # --- Repoint RT ---
    # RT appends info_name internally for multi-file torrents (d.directory.set semantics),
    # so we must pass the PARENT of the content path, not the content path itself.
    rt_target = os.path.dirname(tgt)
    rt_ok = False
    try:
        rt_apply_directory_repoint(
            plan.torrent_hash, rt_target,
            rpc_url=rt_rpc_url, restart=True, check_before_start=True,
            validate_target_exists=True,
        )
        rt_ok = True
        notes.append(f"RT repointed to {rt_target}")
    except Exception as e:
        notes.append(f"RT repoint failed: {e}")

    # --- Repoint qB ---
    qb_ok = False
    if qb_client:
        try:
            success = qb_client.set_location(plan.torrent_hash, tgt, resume_after=False)
            if success:
                qb_ok = True
                notes.append(f"qB set_location -> {tgt}")
                # Trigger recheck so qB verifies the file at new location and returns to stoppedUP.
                # Without recheck, qB may remain stoppedDL after cross-device set_location.
                try:
                    qb_client.recheck_torrent(plan.torrent_hash)
                    time.sleep(5)
                    notes.append("qB recheck triggered post-set_location")
                except Exception as e:
                    notes.append(f"qB recheck failed (non-fatal): {e}")
            else:
                notes.append("qB set_location returned False")
        except Exception as e:
            notes.append(f"qB repoint error: {e}")
    else:
        notes.append("no qB client available — qB not repointed")

    # --- Verify RT seeding state ---
    rt_seeding_ok = False
    if rt_ok:
        try:
            time.sleep(1)
            health = _capture_rt_state(plan.torrent_hash, rt_rpc_url)
            rt_complete = health.get("rt_complete", -1)
            rt_down = health.get("rt_down_rate", -1)
            if rt_complete == 1 and rt_down == 0:
                rt_seeding_ok = True
                notes.append(f"RT seeding ok: complete={rt_complete} down_rate={rt_down}")
            else:
                notes.append(f"RT state post-repoint: complete={rt_complete} down_rate={rt_down}")
        except Exception as e:
            notes.append(f"RT state check error: {e}")

    # --- Stage source for deferred cleanup ---
    try:
        stage_base = os.path.join(
            os.path.dirname(src),
            ".rehome-cleanup-stage",
            plan.torrent_hash,
        )
        os.makedirs(stage_base, exist_ok=True)
        staged_path = os.path.join(stage_base, os.path.basename(src))
        os.rename(src, staged_path)
        notes.append(f"staged source: {src} -> {staged_path}")
    except OSError as e:
        notes.append(f"staging source failed (non-fatal): {e}")

    if not rt_ok:
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="RT repoint failed", notes=notes,
        )

    # qB update is best-effort: cross-device set_location is blocked (qB would physically copy).
    # RT is the authority; qB debt tracked in notes for follow-up via rehome/fastresume.
    if qb_client and not qb_ok:
        notes.append("qB debt: update qB path via rehome after Gate 4")

    post_state = _capture_pre_state(plan.torrent_hash, qb_client, rt_rpc_url)
    return ApplyResult(
        torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
        dry_run=False, success=True, pre_state=pre_state,
        post_state=post_state, error=None, notes=notes,
    )


def apply_repair_plan(
    plan: RepairPlan,
    db_session: sqlite3.Connection,
    config: CanonicalizeConfig,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rt_rpc_url: str = DEFAULT_RT_RPC_URL,
) -> ApplyResult:
    """
    Apply a repair plan. Default is dry-run (no mutations).

    Args:
        plan: The repair plan to execute.
        db_session: Open catalog database connection.
        config: Shared canonicalize context.
        dry_run: If True, simulate all actions without mutation.
        qb_client: Optional qB client for live operations.
            Required when dry_run=False.
        rt_rpc_url: rTorrent XMLRPC endpoint.

    Returns:
        ApplyResult with pre/post state, success flag, and notes.
    """
    notes = list(plan.notes)

    # --- Capture pre-state (read-only, safe in dry-run) ---
    pre_state = _capture_pre_state(plan.torrent_hash, qb_client, rt_rpc_url)

    if dry_run:
        notes.append("dry-run: no mutations performed")
        if plan.plan_type == "blocked":
            return ApplyResult(
                torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
                dry_run=True, success=False, pre_state=pre_state,
                post_state=None, error="blocked by external consumer", notes=notes,
            )
        if plan.plan_type == "ok":
            return ApplyResult(
                torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
                dry_run=True, success=True, pre_state=pre_state,
                post_state=None, error=None, notes=notes,
            )

        src = plan.source_path.rstrip("/")
        tgt = plan.target_path.rstrip("/")
        notes.append(f"would rename: {src} -> {tgt}") if plan.plan_type == "fix_path_only" else None
        notes.append(f"would rsync: {src}/ -> {tgt}/") if plan.plan_type in ("fix_placement_only", "fix_both") else None
        notes.append(f"would repoint RT to {tgt}")
        notes.append(f"would set qB location to {tgt}")

        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=True, success=True, pre_state=pre_state,
            post_state=None, error=None, notes=notes,
        )

    # --- Live execution ---
    if plan.plan_type == "blocked":
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error="blocked by external consumer", notes=notes,
        )

    if plan.plan_type == "ok":
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=True, pre_state=pre_state,
            post_state=None, error=None, notes=notes,
        )

    if qb_client is None:
        notes.append("No qB client provided — qB will not be repointed")

    try:
        if plan.plan_type == "fix_path_only":
            return _execute_fix_path_only(
                plan, db_session, config, qb_client, rt_rpc_url, pre_state,
            )
        elif plan.plan_type in ("fix_placement_only", "fix_both"):
            return _execute_fix_placement(
                plan, db_session, config, qb_client, rt_rpc_url, pre_state,
            )
        else:
            return ApplyResult(
                torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
                dry_run=False, success=False, pre_state=pre_state,
                post_state=None,
                error=f"unknown plan_type: {plan.plan_type}", notes=notes,
            )
    except Exception as e:
        notes.append(f"unexpected error: {e}")
        return ApplyResult(
            torrent_hash=plan.torrent_hash, plan_type=plan.plan_type,
            dry_run=False, success=False, pre_state=pre_state,
            post_state=None, error=str(e), notes=notes,
        )
