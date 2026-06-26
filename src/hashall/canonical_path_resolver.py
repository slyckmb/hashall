"""
Canonical path resolver — Steps 0-5 decision tree from CANONICAL-PATH-SPEC.md.

Determines where each torrent should live (seeding root + category subdirectory)
and diffs both qB and RT current paths against the canonical target.
No execute/mutation logic — this module is pure decision.
"""

import enum
import os
from dataclasses import dataclass, field
from typing import Optional

from hashall.client_drift import ClientTorrentRow
from hashall.save_path_inference import (
    SYSTEM_TAGS,
    extract_cross_seed_provider_name,
    load_qbm_config,
    normalize_cross_seed_refactor_path,
    rt_container_path_to_host,
)

# Seeding roots — container paths used by both RT and qB
STASH_ROOT = "/data/media/torrents/seeding"
POOL_ROOT = "/pool/media/torrents/seeding"

# ARR pre-import category → final category after import
ARR_CATEGORY_FINAL_MAP = {
    "sonarr": "tv",
    "radarr": "movies",
    "lidarr": "music",
    "readarr": "books",
    "speakarr": "audiobooks",
}

# Post-import ARR categories — final ATM-managed form
ARR_POST_IMPORT_CATEGORIES = frozenset({
    "tv", "movies", "books", "ebooks", "audiobooks", "music",
})

# Staging dirs — path segments that classify an item as NEEDS_REPAIR
STAGING_PATTERNS = frozenset({
    "_rehome-unique",
    "_qb-finish",
    "_qb-unique-repair",
    "_qb-repair-v2",
})

LEGACY_CROSS_SEED_LINK = "cross-seed-link"


class ItemType(enum.Enum):
    CROSS_SEED = "cross_seed"
    ARR_PRE_IMPORT = "arr_pre_import"
    ARR_POST_IMPORT = "arr_post_import"
    QBM_TRACKER_TAGGED = "qbm_tracker_tagged"
    OTHER_EXPLICIT = "other_explicit"
    UNCATEGORIZED = "uncategorized"
    UNKNOWN = "unknown"


class SeedingDevice(enum.Enum):
    STASH = "stash"
    POOL = "pool"


class DriftType(enum.Enum):
    CANONICAL = "canonical"
    ROOT_DRIFT = "root_drift"
    CATEGORY_DRIFT = "category_drift"
    NAME_DRIFT = "name_drift"
    STAGING_NEEDS_REPAIR = "staging_needs_repair"
    PATH_MISSING = "path_missing"
    UNKNOWN = "unknown"


@dataclass
class CanonicalPathResult:
    canonical_path: str            # save path: <root>/<category_subdir>
    canonical_content_path: str    # full path: <root>/<category_subdir>/<payload_name>
    item_type: ItemType
    seeding_device: SeedingDevice
    category_subdir: str
    payload_name: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ClientDiffResult:
    client: str
    drift_type: DriftType
    actual_path: Optional[str]
    canonical_path: str


@dataclass
class ItemResolution:
    torrent_hash: str
    canonical: CanonicalPathResult
    qb_diff: ClientDiffResult
    rt_diff: ClientDiffResult
    action: str
    needs_human_review: bool


# ═══════════════════════════════════════════════════════
# Step 0: Pre-screen
# ═══════════════════════════════════════════════════════


def _is_staging_path(path: str) -> bool:
    """Return True if path contains a known staging directory pattern."""
    for pattern in STAGING_PATTERNS:
        if f"/{pattern}/" in path or path.endswith(f"/{pattern}"):
            return True
    return False


# ═══════════════════════════════════════════════════════
# Step 1: Classify item type
# ═══════════════════════════════════════════════════════


def _filter_tracker_tags(tags: set[str]) -> list[str]:
    """Filter SYSTEM_TAGS, ~-prefixed, and rehome_* tags from a tag set."""
    filtered = [
        t for t in tags
        if t not in SYSTEM_TAGS
        and not t.startswith("~")
        and not t.startswith("rehome_")
    ]
    return filtered


def classify_item_type(
    category: str,
    tags: str,
    *,
    qbm_config_path: Optional[str] = None,
) -> tuple[ItemType, str]:
    """
    Returns (ItemType, resolved_subdir_hint).

    resolved_subdir_hint is:
      - tracker name for CROSS_SEED and QBM_TRACKER_TAGGED
      - final category for ARR items (e.g. "tv" for sonarr)
      - empty string otherwise
    """
    category_norm = str(category or "").strip()
    tags_set = {t.strip() for t in (tags or "").split(",") if t.strip()}

    if not category_norm or category_norm == "Uncategorized":
        # Step 1b: tag-based fallback
        tracker_tags = _filter_tracker_tags(tags_set)
        if "cross-seed" in tags_set:
            return (ItemType.CROSS_SEED, "")
        if tracker_tags:
            if qbm_config_path:
                qbm = load_qbm_config(qbm_config_path)
                qbm_matches = [t for t in tracker_tags if t in qbm]
                if qbm_matches:
                    return (ItemType.QBM_TRACKER_TAGGED, sorted(qbm_matches)[0])
            return (ItemType.QBM_TRACKER_TAGGED, sorted(tracker_tags)[0])
        return (ItemType.UNKNOWN, "")

    category_lower = category_norm.lower()

    if category_lower == "cross-seed":
        return (ItemType.CROSS_SEED, "")

    if category_norm in ARR_CATEGORY_FINAL_MAP:
        return (ItemType.ARR_PRE_IMPORT, ARR_CATEGORY_FINAL_MAP[category_norm])

    if category_norm in ARR_POST_IMPORT_CATEGORIES:
        return (ItemType.ARR_POST_IMPORT, category_norm)

    # Check qbit_manage config for tracker-name categories
    if qbm_config_path:
        qbm = load_qbm_config(qbm_config_path)
        if category_norm in qbm:
            return (ItemType.QBM_TRACKER_TAGGED, category_norm)

    # Anything else is either QBM_TRACKER_TAGGED (via tracker-registry) or OTHER_EXPLICIT
    return (ItemType.OTHER_EXPLICIT, category_norm)


# ═══════════════════════════════════════════════════════
# Step 2: Determine seeding device (WHERE)
# ═══════════════════════════════════════════════════════


def _has_no_hardlinks_tag(tags: str) -> bool:
    return "~noHL" in {t.strip() for t in (tags or "").split(",") if t.strip()}


def classify_seeding_device(
    item_type: ItemType,
    tags: str,
    *,
    catalog_nlinks: Optional[int] = None,
    full_scan: bool = False,
    payload_paths: Optional[list[str]] = None,
) -> SeedingDevice:
    """
    Default mode: use ~noHL tag + catalog_nlinks as proxy.
    full_scan mode: not implemented — raises NotImplementedError.
    CROSS_SEED defaults to POOL.
    """
    if full_scan:
        raise NotImplementedError(
            "full_scan mode is not implemented in this module. "
            "Use the default scan mode or extend the execution tool."
        )

    has_nohl = _has_no_hardlinks_tag(tags)

    if item_type == ItemType.CROSS_SEED:
        if has_nohl:
            return SeedingDevice.POOL
        if catalog_nlinks is not None and catalog_nlinks > 1:
            return SeedingDevice.STASH
        return SeedingDevice.POOL

    if has_nohl:
        return SeedingDevice.POOL

    if catalog_nlinks is not None and catalog_nlinks > 1:
        return SeedingDevice.STASH

    return SeedingDevice.STASH


# ═══════════════════════════════════════════════════════
# Step 3: Resolve category subdirectory (WHAT PATH)
# ═══════════════════════════════════════════════════════


def _resolve_tracker_from_tags(tags: str, *, qbm_config_path: Optional[str] = None) -> Optional[str]:
    """Extract a tracker name from qB tags, filtering out system and control tags."""
    tags_set = {t.strip() for t in (tags or "").split(",") if t.strip()}
    tracker_tags = _filter_tracker_tags(tags_set)
    if not tracker_tags:
        return None
    if qbm_config_path:
        qbm = load_qbm_config(qbm_config_path)
        qbm_matches = [t for t in tracker_tags if t in qbm]
        if qbm_matches:
            return sorted(qbm_matches)[0]
    return sorted(tracker_tags)[0]


def resolve_category_subdir(
    item_type: ItemType,
    category: str,
    tags: str,
    save_path: str = "",
    content_path: str = "",
    *,
    qbm_config_path: Optional[str] = None,
) -> tuple[str, list[str]]:
    """
    Returns (category_subdir, notes).

    For CROSS_SEED: "cross-seed/<tracker>" — tracker resolved from path then tags.
    For ARR_PRE_IMPORT: uses ARR_CATEGORY_FINAL_MAP.
    For ARR_POST_IMPORT / QBM_TRACKER_TAGGED / OTHER_EXPLICIT: category verbatim.
    For UNCATEGORIZED / UNKNOWN: empty string.
    """
    notes: list[str] = []

    if item_type == ItemType.CROSS_SEED:
        # Step 3a: resolve tracker from path, then tags
        provider = extract_cross_seed_provider_name(save_path, content_path)
        if provider:
            subdir = f"cross-seed/{provider}"
            notes.append(f"cross-seed provider from path: {provider}")
            return (subdir, notes)
        tracker_slug = _resolve_tracker_from_tags(tags, qbm_config_path=qbm_config_path)
        if tracker_slug:
            subdir = f"cross-seed/{tracker_slug}"
            notes.append(f"cross-seed provider from tags: {tracker_slug}")
            return (subdir, notes)
        notes.append("cross-seed category, but no provider found in paths or tags")
        return ("cross-seed", notes)

    if item_type == ItemType.ARR_PRE_IMPORT:
        final_cat = ARR_CATEGORY_FINAL_MAP.get(category, category)
        notes.append(f"Pre-import ARR category; should become '{final_cat}' after import")
        return (final_cat, notes)

    if item_type == ItemType.ARR_POST_IMPORT:
        return (category, notes)

    if item_type == ItemType.QBM_TRACKER_TAGGED:
        return (category, notes)

    if item_type == ItemType.OTHER_EXPLICIT:
        return (category, notes)

    # UNCATEGORIZED or UNKNOWN
    return ("", notes)


# ═══════════════════════════════════════════════════════
# Step 4: Assemble canonical path
# ═══════════════════════════════════════════════════════


def assemble_canonical_path(
    seeding_device: SeedingDevice,
    category_subdir: str,
) -> str:
    """
    Returns canonical SAVE PATH: <root>/<category_subdir> (no payload name).

    This is the parent directory that qB save_path and RT directory represent.
    Use canonical_content_path for the full path including the payload name.
    """
    root = STASH_ROOT if seeding_device == SeedingDevice.STASH else POOL_ROOT
    if category_subdir:
        return f"{root}/{category_subdir}"
    return root


# ═══════════════════════════════════════════════════════
# Step 5: Diff client path
# ═══════════════════════════════════════════════════════


def _normalize_path(path: str) -> str:
    """Normalize /data/media ↔ /stash/media for comparison."""
    if path.startswith("/stash/media/"):
        path = "/data/media/" + path[len("/stash/media/"):]
    return path.rstrip("/")


def _path_relative_to_root(path: str, root: str) -> Optional[str]:
    """Return the root-relative portion of path, or None if not under root."""
    p = _normalize_path(path)
    r = _normalize_path(root)
    if p == r:
        return ""
    if p.startswith(r + "/"):
        return p[len(r) + 1:]
    return None


def _get_root_and_rel(norm_path: str) -> tuple[Optional[str], Optional[str]]:
    """Return (root, relative_path) if path is under a known seeding root."""
    for root in (STASH_ROOT, POOL_ROOT):
        rel = _path_relative_to_root(norm_path, root)
        if rel is not None:
            return root, rel
    return None, None


def _normalize_rt_path(rt_path: str, canonical_path: str) -> str:
    """
    Truncate RT path to canonical save-path depth when RT directory is
    exactly one level deeper (multi-file torrent content folder appended).

    RT's ``directory`` field includes the content folder for multi-file
    torrents. The canonical save path is always the parent (category level).
    If the RT path has exactly one extra component beyond the canonical depth,
    strip it so the comparison is at the same level.
    """
    if not rt_path or not canonical_path:
        return rt_path

    norm_rt = _normalize_path(rt_path)
    norm_canon = _normalize_path(canonical_path)

    canon_parts = norm_canon.rstrip("/").split("/")
    rt_parts = norm_rt.rstrip("/").split("/")

    if len(rt_parts) == len(canon_parts) + 1:
        return "/".join(rt_parts[: len(canon_parts)])

    return rt_path


def diff_client_path(
    actual_path: Optional[str],
    canonical_path: str,
) -> DriftType:
    """
    Compare actual_path to canonical_path.

    - None → PATH_MISSING
    - Staging pattern → STAGING_NEEDS_REPAIR
    - Exact match → CANONICAL
    - Same relative path, different root → ROOT_DRIFT
    - Different relative path → CATEGORY_DRIFT
    Normalizes /data/media ↔ /stash/media before comparing.
    """
    if actual_path is None:
        return DriftType.PATH_MISSING

    norm_actual = _normalize_path(actual_path)
    norm_canonical = _normalize_path(canonical_path)

    if _is_staging_path(norm_actual):
        return DriftType.STAGING_NEEDS_REPAIR

    if norm_actual == norm_canonical:
        return DriftType.CANONICAL

    # Different paths — determine if same relative under different root
    actual_root, actual_rel = _get_root_and_rel(norm_actual)
    canon_root, canon_rel = _get_root_and_rel(norm_canonical)

    if actual_rel is not None and canon_rel is not None:
        if actual_root != canon_root and actual_rel == canon_rel:
            return DriftType.ROOT_DRIFT

    return DriftType.CATEGORY_DRIFT


# ═══════════════════════════════════════════════════════
# Action table
# ═══════════════════════════════════════════════════════


def _derive_action(rt_drift: DriftType, qb_drift: DriftType) -> str:
    """Map (RT status, qB status) to human-readable action per §4 action table."""
    table = {
        (DriftType.CANONICAL, DriftType.CANONICAL): "None. Item is correctly placed.",
        (DriftType.CANONICAL, DriftType.ROOT_DRIFT): "Repoint qB to canonical (RT's current path).",
        (DriftType.CANONICAL, DriftType.CATEGORY_DRIFT): "Repoint qB to canonical (RT's current path).",
        (DriftType.CANONICAL, DriftType.PATH_MISSING): "Add qB mirror at RT path.",
        (DriftType.ROOT_DRIFT, DriftType.ROOT_DRIFT): "Rehome both to canonical root.",
        (DriftType.ROOT_DRIFT, DriftType.CANONICAL): "Rare: qB at canonical, RT not. Rehome RT to canonical.",
        (DriftType.ROOT_DRIFT, DriftType.CATEGORY_DRIFT): "Rehome RT to canonical root; repoint qB to canonical path.",
        (DriftType.CATEGORY_DRIFT, DriftType.CATEGORY_DRIFT): "Rename directory and/or repoint both to canonical path.",
        (DriftType.CATEGORY_DRIFT, DriftType.CANONICAL): "Rename RT directory (or repoint RT) to match canonical.",
    }

    # Needs repair / missing / unknown — RT side takes priority
    if rt_drift in (DriftType.STAGING_NEEDS_REPAIR,):
        return "Run repair tool (save-path-repair, qb-fastresume-patch, etc.) before re-evaluating."
    if rt_drift == DriftType.PATH_MISSING:
        return "Investigate: data missing on disk. Escalate."
    if rt_drift == DriftType.UNKNOWN or qb_drift == DriftType.UNKNOWN:
        return "Escalate for human review."
    if qb_drift == DriftType.PATH_MISSING:
        return "Add qB mirror at RT path."
    if qb_drift == DriftType.STAGING_NEEDS_REPAIR:
        return "Run repair tool on qB before re-evaluating."

    pair = (rt_drift, qb_drift)
    if pair in table:
        return table[pair]

    return f"Investigate: unexpected state combination (RT={rt_drift.value}, qB={qb_drift.value})."


# ═══════════════════════════════════════════════════════
# Top-level resolver
# ═══════════════════════════════════════════════════════


def resolve_canonical_path(
    qb_row: ClientTorrentRow,
    rt_path: Optional[str],
    *,
    catalog_nlinks: Optional[int] = None,
    qbm_config_path: Optional[str] = None,
    full_scan: bool = False,
) -> ItemResolution:
    """
    Run Steps 0-5 for one item. Returns ItemResolution.

    Args:
        qb_row: ClientTorrentRow from qB cache (category, tags, save_path, etc.)
        rt_path: RT's current save_path (None if RT doesn't have the item)
        catalog_nlinks: hardlink count from catalog DB (default scan mode)
        qbm_config_path: path to qbit_manage config.yml for tracker resolution
        full_scan: if True, raises NotImplementedError (see classify_seeding_device)
    """
    # Step 0: Pre-screen
    staging_found = False
    if qb_row.save_path and _is_staging_path(qb_row.save_path):
        staging_found = True
    if rt_path and _is_staging_path(rt_path):
        staging_found = True

    # Step 1: Classify item type
    item_type, _ = classify_item_type(
        qb_row.category, qb_row.tags, qbm_config_path=qbm_config_path,
    )

    # Step 2: Seeding device
    seeding_device = classify_seeding_device(
        item_type, qb_row.tags,
        catalog_nlinks=catalog_nlinks,
        full_scan=full_scan,
    )

    # Step 3: Category subdirectory
    category_subdir, notes = resolve_category_subdir(
        item_type,
        qb_row.category,
        qb_row.tags,
        save_path=qb_row.save_path,
        content_path=qb_row.content_path,
        qbm_config_path=qbm_config_path,
    )

    # Step 4: Assemble canonical path
    payload_name = qb_row.name
    canonical_path = assemble_canonical_path(seeding_device, category_subdir)
    canonical_content_path = f"{canonical_path}/{payload_name}" if payload_name else canonical_path

    canonical_result = CanonicalPathResult(
        canonical_path=canonical_path,
        canonical_content_path=canonical_content_path,
        item_type=item_type,
        seeding_device=seeding_device,
        category_subdir=category_subdir,
        payload_name=payload_name,
        notes=notes,
    )

    # Step 5: Diff
    if staging_found:
        qb_drift = DriftType.STAGING_NEEDS_REPAIR
    else:
        qb_drift = diff_client_path(qb_row.save_path, canonical_path)

    # Normalize RT path to save-path depth (strips multi-file content folder)
    rt_path_normalized = _normalize_rt_path(rt_path, canonical_path) if rt_path else rt_path
    rt_drift = diff_client_path(rt_path_normalized, canonical_path)

    qb_diff = ClientDiffResult(
        client="qb",
        drift_type=qb_drift,
        actual_path=qb_row.save_path,
        canonical_path=canonical_path,
    )
    rt_diff = ClientDiffResult(
        client="rt",
        drift_type=rt_drift,
        actual_path=rt_path,
        canonical_path=canonical_path,
    )

    action = _derive_action(rt_drift, qb_drift)
    needs_human_review = (
        item_type == ItemType.UNKNOWN
        or DriftType.PATH_MISSING in (rt_drift, qb_drift)
    )

    return ItemResolution(
        torrent_hash=qb_row.torrent_hash,
        canonical=canonical_result,
        qb_diff=qb_diff,
        rt_diff=rt_diff,
        action=action,
        needs_human_review=needs_human_review,
    )
