"""Helpers for resolving library roots from external configs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


_DATA_DIRS_RE = re.compile(r"dataDirs\s*:\s*\[(.*?)\]\s*,", re.S)
_STRING_RE = re.compile(r"""['"]([^'"]+)['"]""")


def _dedupe_roots(roots: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for root in roots:
        if not root:
            continue
        normalized = os.path.expanduser(root).strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def parse_cross_seed_data_dirs(config_path: Path) -> List[str]:
    """Parse cross-seed config.js dataDirs into a list of paths."""
    if not config_path.exists():
        return []

    text = config_path.read_text(encoding="utf-8", errors="ignore")
    match = _DATA_DIRS_RE.search(text)
    if not match:
        return []

    block = match.group(1)
    roots: List[str] = []

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        # Drop inline comments
        if "//" in line:
            line = line.split("//", 1)[0]
        for m in _STRING_RE.finditer(line):
            value = m.group(1).strip()
            if value:
                roots.append(value)

    return _dedupe_roots(roots)


def parse_tracker_registry_save_paths(registry_path: Path) -> List[str]:
    """
    Parse tracker-registry.yml for qbittorrent.save_path values.

    Note: minimal YAML parsing tailored to current schema; ignores comments.
    """
    if not registry_path.exists():
        return []

    roots: List[str] = []
    lines = registry_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    in_trackers = False
    trackers_indent: Optional[int] = None
    in_qbit = False
    qbit_indent: Optional[int] = None

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if stripped == "trackers:":
            in_trackers = True
            trackers_indent = indent
            in_qbit = False
            qbit_indent = None
            continue

        if not in_trackers:
            continue

        if trackers_indent is not None and indent <= trackers_indent:
            in_trackers = False
            in_qbit = False
            qbit_indent = None
            continue

        if stripped.startswith("qbittorrent:"):
            in_qbit = True
            qbit_indent = indent
            continue

        if in_qbit and qbit_indent is not None:
            if indent <= qbit_indent:
                in_qbit = False
                qbit_indent = None
                continue
            if stripped.startswith("save_path:"):
                value = stripped.split(":", 1)[1].strip().strip("'\"")
                if value and value != "null":
                    roots.append(value)

    return _dedupe_roots(roots)


def _first_existing(paths: Iterable[Optional[str]]) -> Optional[Path]:
    for candidate in paths:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def find_cross_seed_config(explicit: Optional[str] = None) -> Tuple[Optional[Path], bool]:
    """Return (path, explicit_flag)."""
    if explicit:
        return Path(explicit), True

    env_candidates = (
        os.environ.get("HASHALL_CROSS_SEED_CONFIG"),
        os.environ.get("CROSSSEED_CONFIG"),
        os.environ.get("CROSS_SEED_CONFIG"),
    )

    auto_candidates = [
        "/home/michael/dev/work/glider/glider-docker/cross-seed/config.js",
        "/mnt/config/docker/cross-seed/config.js",
    ]

    return _first_existing(env_candidates) or _first_existing(auto_candidates), False


def find_tracker_registry(explicit: Optional[str] = None) -> Tuple[Optional[Path], bool]:
    """Return (path, explicit_flag)."""
    if explicit:
        return Path(explicit), True

    env_candidates = (
        os.environ.get("HASHALL_TRACKER_REGISTRY"),
        os.environ.get("TRACKER_REGISTRY"),
    )

    auto_candidates = [
        "/home/michael/dev/work/glider/glider-docker/tracker-ctl/config/tracker-registry.yml",
        "/mnt/config/docker/tracker-ctl/config/tracker-registry.yml",
    ]

    return _first_existing(env_candidates) or _first_existing(auto_candidates), False


def collect_library_roots(
    explicit_roots: Iterable[str],
    cross_seed_config: Optional[str],
    tracker_registry: Optional[str],
) -> Tuple[List[str], List[str]]:
    """
    Collect library roots and describe their sources.

    Returns:
        (roots, sources)
    """
    roots: List[str] = []
    sources: List[str] = []

    if explicit_roots:
        roots.extend(explicit_roots)
        sources.append("explicit")

    cross_seed_path, cross_seed_explicit = find_cross_seed_config(cross_seed_config)
    if cross_seed_path:
        if cross_seed_explicit and not cross_seed_path.exists():
            raise FileNotFoundError(f"Cross-seed config not found: {cross_seed_path}")
        dirs = parse_cross_seed_data_dirs(cross_seed_path)
        if dirs:
            roots.extend(dirs)
            sources.append(f"cross-seed:{cross_seed_path}")

    registry_path, registry_explicit = find_tracker_registry(tracker_registry)
    if registry_path:
        if registry_explicit and not registry_path.exists():
            raise FileNotFoundError(f"Tracker registry not found: {registry_path}")
        save_paths = parse_tracker_registry_save_paths(registry_path)
        if save_paths:
            roots.extend(save_paths)
            sources.append(f"tracker-registry:{registry_path}")

    return _dedupe_roots(roots), _dedupe_roots(sources)
