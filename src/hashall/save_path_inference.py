"""
Save-path inference: derive canonical seeding paths from qBittorrent category/tags.

Ported from ~/dev/sys/docker/gluetun_qbit/qbittorrent_vpn/bin/qb-to-rt-migrate.py
(preserve logic, adapt to hashall context).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml


# Canonical seeding roots (device-aware)
APPROVED_SAVE_ROOTS = (
    "/data/media/torrents/seeding",  # /stash (hardlinked library content)
    "/pool/media/torrents/seeding",  # /pool (seed-only, no hardlinks)
)

# ARR category → post-import category mapping (sonarr → tv, etc.)
ARR_CATEGORY_FINAL_MAP = {
    "sonarr": "tv",
    "radarr": "movies",
    "lidarr": "music",
    "readarr": "books",
    "speakarr": "books",
}

# Category aliases (e.g., MaM → myanonamouse)
CATEGORY_DIR_ALIASES = {
    "myanonamouse": ("myanonamouse", "MaM"),
}

# RT container → host path mappings (for qb-to-rt-migrate compat)
RT_CONTAINER_HOST_PATH_PREFIXES = (
    ("/downloads", "/dump/docker/gluetun_qbit/rtorrent_vpn/downloads"),
    ("/config", "/dump/docker/gluetun_qbit/rtorrent_vpn"),
    ("/data/media", "/data/media"),
    ("/pool/data", "/pool/data"),
    ("/pool/media", "/pool/media"),
)

# System tags that are not tracker identifiers
SYSTEM_TAGS = {"private", "cross-seed", "~noHL", "needs_rehome"}


@dataclass
class InferredSavePath:
    """Result of canonical save-path inference."""
    canonical_save_path: str  # the derived correct path
    device: Literal["stash", "pool"]  # /data/media (stash) or /pool/media (pool)
    category: str  # original category name
    subdir: str  # leaf directory name (e.g., "tv", "cross-seed/myanonamouse")
    reliability: Literal["reliable", "transient", "ambiguous"]
    notes: list[str] = field(default_factory=list)


def rt_container_path_to_host(path_str: str) -> str | None:
    """Convert RT container path (/data/media) to host path (/stash/media)."""
    if not path_str:
        return None
    normalized = str(path_str).rstrip("/") or "/"
    for container_prefix, host_prefix in RT_CONTAINER_HOST_PATH_PREFIXES:
        if normalized == container_prefix or normalized.startswith(container_prefix + "/"):
            suffix = normalized[len(container_prefix):].lstrip("/")
            base = Path(host_prefix)
            return str(base / suffix) if suffix else str(base)
    return None


def normalize_cleanup_save_path(save_path: str) -> tuple[str | None, str | None]:
    """
    Validate qB's save_path before using it as the authoritative RT target.
    For cleanup-live, we only trust canonical seeding roots.
    """
    if not save_path:
        return None, "empty_save_path"

    normalized = save_path.rstrip("/") or "/"
    for root in APPROVED_SAVE_ROOTS:
        if normalized == root or normalized.startswith(root + "/"):
            return normalized, None

    return None, f"blocked_invalid_save_path:{normalized}"


def normalize_cross_seed_refactor_path(path_str: str, category: str) -> str:
    """Normalize cross-seed-link (legacy) → cross-seed (canonical)."""
    if not path_str:
        return path_str
    normalized = str(path_str).rstrip("/") or "/"
    for root in APPROVED_SAVE_ROOTS:
        legacy_root = f"{root}/cross-seed-link"
        canonical_root = f"{root}/cross-seed"
        if normalized == legacy_root:
            return canonical_root
        if normalized.startswith(legacy_root + "/"):
            return canonical_root + normalized[len(legacy_root):]
    if (category or "").strip().lower() != "cross-seed":
        return normalized
    return normalized


def choose_preferred_save_root(*paths: str) -> str:
    """Infer which device root (stash vs pool) from candidate paths."""
    for candidate in paths:
        normalized = str(candidate or "").rstrip("/") or ""
        if not normalized:
            continue
        for root in APPROVED_SAVE_ROOTS:
            if normalized == root or normalized.startswith(root + "/"):
                return root
    return APPROVED_SAVE_ROOTS[0]  # default to stash


def choose_category_leaf_name(category: str, *paths: str) -> str:
    """Choose the correct leaf directory name for a category, using aliases when present."""
    category_norm = str(category or "").strip()
    if not category_norm:
        return category_norm

    aliases = CATEGORY_DIR_ALIASES.get(category_norm.lower())
    if not aliases:
        return category_norm

    # If any path contains an alias variant, use it
    for candidate in paths:
        normalized = str(candidate or "").rstrip("/") or ""
        if not normalized:
            continue
        for root in APPROVED_SAVE_ROOTS:
            prefix = root + "/"
            if not normalized.startswith(prefix):
                continue
            rel = normalized[len(prefix):]
            if not rel:
                continue
            leaf = rel.split("/", 1)[0]
            if leaf in aliases:
                return leaf

    return aliases[0]  # default to first alias


def extract_cross_seed_provider_name(*paths: str) -> str | None:
    """Extract tracker slug from cross-seed path."""
    for candidate in paths:
        normalized = normalize_cross_seed_refactor_path(candidate, "cross-seed")
        if not normalized:
            continue
        for root in APPROVED_SAVE_ROOTS:
            prefix = f"{root}/cross-seed/"
            if not normalized.startswith(prefix):
                continue
            rel = Path(normalized[len(prefix):])
            if rel.parts:
                return rel.parts[0]
    return None


def derive_policy_base_save_path(
    category: str,
    *,
    save_path: str = "",
    content_path: str = "",
    rt_directory: str = "",
) -> tuple[str | None, str | None, str]:
    """
    Derive canonical save path from category and contextual paths.
    Returns (path, error, strategy).
    """
    category_norm = str(category or "").strip()
    rt_host_directory = rt_container_path_to_host(rt_directory) if rt_directory else ""
    primary_root = choose_preferred_save_root(save_path, content_path, rt_host_directory)

    if category_norm:
        if category_norm.lower() == "cross-seed":
            provider = extract_cross_seed_provider_name(
                save_path,
                content_path,
                rt_host_directory,
            )
            base = f"{primary_root}/cross-seed"
            if provider:
                return f"{base}/{provider}", None, "cross_seed_provider"
            return base, None, "cross_seed_root"
        leaf = choose_category_leaf_name(category_norm, save_path, content_path, rt_host_directory)
        return f"{primary_root}/{leaf}", None, "category_root"

    normalized = normalize_cross_seed_refactor_path(save_path, category_norm)
    fallback, err = normalize_cleanup_save_path(normalized)
    if err:
        return None, err, "save_path_fallback"
    return fallback, None, "save_path_fallback"


def derive_policy_target_save_path(
    category: str,
    *,
    save_path: str = "",
    content_path: str = "",
    rt_directory: str = "",
) -> tuple[str | None, str | None, str]:
    """
    Derive target save path, preserving sub-paths when already canonical.
    Returns (path, error, strategy).
    """
    base_save_path, err, strategy = derive_policy_base_save_path(
        category,
        save_path=save_path,
        content_path=content_path,
        rt_directory=rt_directory,
    )
    if err:
        return None, err, strategy

    normalized = normalize_cross_seed_refactor_path(save_path, category)
    preserved, preserve_err = (
        normalize_cleanup_save_path(normalized) if normalized else (None, "empty_save_path")
    )
    if not preserve_err and (preserved == base_save_path or preserved.startswith(base_save_path + "/")):
        return preserved, None, strategy
    return base_save_path, None, strategy


def load_qbm_config(config_path: str = "/home/michael/dev/sys/docker/qbit_manage/config.yml") -> dict[str, str]:
    """
    Load qbit_manage config.yml and extract category → save_path mapping.
    Returns {category: leaf_dir_name}.
    """
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        # Fallback if config not found or parsing fails
        return {}

    if not config or "cat" not in config:
        return {}

    # Extract leaf directory names from absolute paths
    cat_map = {}
    for category, abs_path in config["cat"].items():
        if not abs_path or not isinstance(abs_path, str):
            continue
        # Extract leaf from path: /data/media/torrents/seeding/tv → tv
        # Special case: root path /data/media/torrents/seeding → ""
        for root in APPROVED_SAVE_ROOTS:
            if abs_path == root:
                cat_map[category] = ""
                break
            if abs_path.startswith(root + "/"):
                rel = abs_path[len(root) + 1:]
                leaf = rel.split("/", 1)[0]  # first component
                cat_map[category] = leaf
                break

    return cat_map


def infer_canonical_save_path(
    category: str,
    tags: str = "",
    current_save_path: str = "",
    current_content_path: str = "",
    current_rt_directory: str = "",
    *,
    qbm_config_path: str = "/home/michael/dev/sys/docker/qbit_manage/config.yml",
) -> InferredSavePath:
    """
    Infer the canonical save path for a torrent based on qBittorrent metadata.

    Args:
        category: qB category name
        tags: comma-separated tags string
        current_save_path: current qB save_path
        current_content_path: current qB content_path
        current_rt_directory: current RT d.directory
        qbm_config_path: path to qbit_manage config.yml

    Returns:
        InferredSavePath with canonical path and reliability classification
    """
    category_norm = str(category or "").strip()
    tags_set = {t.strip() for t in (tags or "").split(",") if t.strip()}

    # Determine device root based on ~noHL tag
    has_no_hardlinks = "~noHL" in tags_set
    if has_no_hardlinks:
        device_root = "/pool/media/torrents/seeding"
        device = "pool"
    else:
        device_root = "/data/media/torrents/seeding"
        device = "stash"

    notes = []

    # Determine subdirectory
    subdir = ""
    reliability = "ambiguous"

    if not category_norm or category_norm == "Uncategorized":
        # Uncategorized → root, no subdir
        subdir = ""
        reliability = "ambiguous"
    elif category_norm.lower() == "cross-seed":
        # Extract tracker slug from tags or paths
        tracker_tags = tags_set - SYSTEM_TAGS
        if tracker_tags:
            tracker_slug = sorted(tracker_tags)[0]  # first remaining tag
            subdir = f"cross-seed/{tracker_slug}"
        else:
            # Try to extract from current paths
            provider = extract_cross_seed_provider_name(current_save_path, current_content_path)
            if provider:
                subdir = f"cross-seed/{provider}"
                notes.append(f"cross-seed provider extracted from path: {provider}")
            else:
                subdir = "cross-seed"
                notes.append("cross-seed category, but no provider found in paths or tags")
        reliability = "reliable"
    elif category_norm in ARR_CATEGORY_FINAL_MAP:
        # Pre-import ARR category → transient
        subdir = category_norm
        reliability = "transient"
        final_cat = ARR_CATEGORY_FINAL_MAP[category_norm]
        notes.append(f"Pre-import ARR category; should become '{final_cat}' after import")
    else:
        # Check qbm config for uncommon categories
        qbm_config = load_qbm_config(qbm_config_path)
        if category_norm in qbm_config:
            subdir = qbm_config[category_norm]
            reliability = "reliable"
        else:
            # Default: use category name as subdir
            subdir = category_norm
            reliability = "reliable"

    canonical_save_path = f"{device_root}/{subdir}" if subdir else device_root

    return InferredSavePath(
        canonical_save_path=canonical_save_path,
        device=device,
        category=category_norm,
        subdir=subdir,
        reliability=reliability,
        notes=notes,
    )


@dataclass
class DriftReport:
    """Drift detection result for a single torrent hash."""
    torrent_hash: str
    category: str
    qb_current_save_path: str
    rt_current_directory: str
    canonical_save_path: str  # inferred canonical path
    is_drifted: bool
    drift_reason: Optional[str] = None  # why it drifted
    notes: list[str] = field(default_factory=list)


def check_path_alignment(
    current_path: str,
    canonical_path: str,
    tolerance_depth: int = 1,
) -> bool:
    """
    Check if current path is aligned with canonical path.
    Allows for single-level directory name variations (e.g., /tv/Show vs /tv for single-file torrents).
    """
    if not current_path or not canonical_path:
        return False

    current_norm = Path(current_path).as_posix().rstrip("/")
    canonical_norm = Path(canonical_path).as_posix().rstrip("/")

    if current_norm == canonical_norm:
        return True

    # Allow single subdirectory mismatch (single-file torrent case)
    if tolerance_depth > 0:
        current_parent = str(Path(current_norm).parent)
        canonical_parent = str(Path(canonical_norm).parent)
        if current_parent == canonical_parent:
            return True

    return False


def detect_drift(
    torrent_hash: str,
    category: str,
    tags: str = "",
    current_save_path: str = "",
    current_content_path: str = "",
    current_rt_directory: str = "",
    current_qb_state: str = "unknown",
) -> DriftReport:
    """
    Detect save-path drift for a single torrent.
    Returns DriftReport with canonical path and drift classification.
    """
    # Infer canonical path
    inferred = infer_canonical_save_path(
        category=category,
        tags=tags,
        current_save_path=current_save_path,
        current_content_path=current_content_path,
        current_rt_directory=current_rt_directory,
    )

    # Skip transient categories (they may be in transit due to ARR imports)
    if inferred.reliability == "transient":
        return DriftReport(
            torrent_hash=torrent_hash,
            category=category,
            qb_current_save_path=current_save_path,
            rt_current_directory=current_rt_directory,
            canonical_save_path=inferred.canonical_save_path,
            is_drifted=False,
            drift_reason="transient_category_skipped",
            notes=[f"Skipping transient {category} category (may be in ARR import transit)"],
        )

    # Check alignment
    qb_aligned = check_path_alignment(current_save_path, inferred.canonical_save_path)
    rt_aligned = check_path_alignment(current_rt_directory, inferred.canonical_save_path)

    notes = []
    drift_reasons = []

    # Detect device mismatch
    if inferred.device == "pool" and "pool" not in current_save_path.lower():
        drift_reasons.append("wrong_device_should_be_pool")
        notes.append("Item tagged ~noHL (no hardlinks) but save_path not on /pool")
    elif inferred.device == "stash" and "pool" in current_save_path.lower():
        drift_reasons.append("wrong_device_should_be_stash")
        notes.append("Item should have hardlinks on /stash but save_path is on /pool")

    # Detect category dir mismatch
    if category in ARR_CATEGORY_FINAL_MAP:
        final_cat = ARR_CATEGORY_FINAL_MAP[category]
        if final_cat not in current_save_path and final_cat not in current_rt_directory:
            if category in current_save_path or category in current_rt_directory:
                drift_reasons.append("wrong_category_dir_pre_import")
                notes.append(f"Still in pre-import {category}; should be {final_cat} after import")

    # Detect legacy paths
    legacy_markers = ["_qb-repair", "_qb-finish", "cross-seed-link", "/downloads/"]
    for marker in legacy_markers:
        if marker in current_save_path or marker in current_rt_directory:
            drift_reasons.append("legacy_path")
            notes.append(f"Legacy path marker found: {marker}")
            break

    # Detect general path mismatch
    if not qb_aligned or not rt_aligned:
        if not drift_reasons:
            drift_reasons.append("path_mismatch")
        notes.append(f"qB/RT mismatch: qb={qb_aligned}, rt={rt_aligned}")

    is_drifted = len(drift_reasons) > 0
    drift_reason = " + ".join(drift_reasons) if drift_reasons else None

    return DriftReport(
        torrent_hash=torrent_hash,
        category=category,
        qb_current_save_path=current_save_path,
        rt_current_directory=current_rt_directory,
        canonical_save_path=inferred.canonical_save_path,
        is_drifted=is_drifted,
        drift_reason=drift_reason,
        notes=notes,
    )
