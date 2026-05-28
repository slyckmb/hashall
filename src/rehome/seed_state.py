"""Published seed-root coordination state for external consumers.

Ownership contract:
- hashall is the sole writer of this artifact
- external tools (for example traktor) are read-only consumers
- the artifact must be machine-readable, versioned, and safe to reject
  fail-closed when required fields are missing or invalid
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable, Optional

from rehome.config import load_config, parse_managed_roots


SEED_ROOT_STATE_PATH = Path.home() / ".hashall" / "seed-root-state.json"
SCHEMA_VERSION = 1
CONTRACT_OWNER = "hashall"
REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "updated_at",
    "generation",
    "writer",
    "active",
    "target",
    "cross_seed",
    "migration",
    "aliases",
    "mirror_roots",
)


def validate_seed_root_state(state: dict) -> None:
    """Raise ValueError when a published contract is missing required fields."""
    missing = [field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in state]
    if missing:
        raise ValueError(f"seed-root-state missing required field(s): {', '.join(missing)}")
    if int(state.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        raise ValueError(
            f"seed-root-state schema_version={state.get('schema_version')} expected={SCHEMA_VERSION}"
        )
    if str(state.get("writer") or "").strip() != CONTRACT_OWNER:
        raise ValueError(
            f"seed-root-state writer={state.get('writer')!r} expected={CONTRACT_OWNER!r}"
        )
    for section_name, key_name in (
        ("active", "seeding_root"),
        ("target", "seeding_root"),
        ("cross_seed", "link_root"),
        ("migration", "state"),
    ):
        section = state.get(section_name)
        if not isinstance(section, dict):
            raise ValueError(f"seed-root-state section {section_name!r} must be an object")
        if not str(section.get(key_name) or "").strip():
            raise ValueError(f"seed-root-state {section_name}.{key_name} is required")
    if not isinstance(state.get("aliases"), list):
        raise ValueError("seed-root-state aliases must be a list")
    if not isinstance(state.get("mirror_roots"), list):
        raise ValueError("seed-root-state mirror_roots must be a list")


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _looks_like_seeding_root(path: str) -> bool:
    return "/torrents/seeding" in path or path.endswith("/seeds")


def _legacy_seed_roots_for_managed_path(path: str) -> list[str]:
    path = str(path).rstrip("/")
    roots: list[str] = []
    if path == "/pool/data":
        roots.append("/pool/data/media/torrents/seeding")
    elif path == "/pool/media":
        roots.append("/pool/media/torrents/seeding")
    elif _looks_like_seeding_root(path):
        roots.append(path)
    return roots


def _stash_alias_roots(root: str) -> list[str]:
    root = str(root).rstrip("/")
    if root == "/stash/media":
        return [
            "/stash/media/torrents/seeding",
            "/data/media/torrents/seeding",
        ]
    if root == "/data/media":
        return [
            "/data/media/torrents/seeding",
            "/stash/media/torrents/seeding",
        ]
    if root.startswith("/stash/media/"):
        suffix = root[len("/stash/media") :]
        return [root, f"/data/media{suffix}"]
    if root.startswith("/data/media/"):
        suffix = root[len("/data/media") :]
        return [root, f"/stash/media{suffix}"]
    return [root] if _looks_like_seeding_root(root) else []


def _infer_active_seed_root(cfg: dict) -> str:
    explicit = str(cfg.get("seed_root_active") or "").strip()
    if explicit:
        return explicit

    dest_root = str(cfg.get("default_dest_root") or "").strip()
    if dest_root:
        return dest_root

    active_root = str(cfg.get("active_root") or "").strip()
    candidates = _stash_alias_roots(active_root)
    return candidates[0] if candidates else active_root


def _infer_target_seed_root(cfg: dict, active_root: str) -> str:
    explicit = str(cfg.get("seed_root_target") or "").strip()
    if explicit:
        return explicit
    dest_root = str(cfg.get("default_dest_root") or "").strip()
    return dest_root or active_root


def _build_aliases(active_root: str, target_root: str) -> list[dict]:
    aliases: list[dict] = []
    for root in {active_root, target_root}:
        if root.startswith("/stash/media/") or root == "/stash/media/torrents/seeding":
            aliases.append(
                {
                    "path": root.replace("/stash/media", "/data/media", 1),
                    "canonical_root": root,
                    "kind": "bind_alias",
                }
            )
        elif root.startswith("/data/media/") or root == "/data/media/torrents/seeding":
            aliases.append(
                {
                    "path": root.replace("/data/media", "/stash/media", 1),
                    "canonical_root": root,
                    "kind": "bind_alias",
                }
            )
    return aliases


def _existing_generation(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    generation = data.get("generation", 0)
    return int(generation) if isinstance(generation, int) or str(generation).isdigit() else 0


def build_seed_root_state(
    cfg: Optional[dict] = None,
    *,
    now: Optional[datetime] = None,
    previous_generation: int = 0,
) -> dict:
    cfg = cfg or load_config()
    now = now or datetime.now().astimezone()

    active_root = _infer_active_seed_root(cfg)
    target_root = _infer_target_seed_root(cfg, active_root)
    active_alias = str(cfg.get("seed_root_active_device") or cfg.get("default_dest_device") or "").strip()
    target_alias = str(cfg.get("seed_root_target_device") or cfg.get("default_dest_device") or active_alias).strip()

    cross_seed_link_root = str(cfg.get("cross_seed_link_root") or "").strip()
    if not cross_seed_link_root:
        cross_seed_link_root = str(Path(target_root) / "cross-seed")

    mirror_roots = [active_root, target_root]
    mirror_roots.extend(_stash_alias_roots(str(cfg.get("active_root") or "").strip()))
    for managed_path, _managed_alias in parse_managed_roots(cfg.get("managed_roots") or []):
        mirror_roots.extend(_legacy_seed_roots_for_managed_path(managed_path))
    mirror_roots = _dedupe(mirror_roots)

    source_roots = [root for root in mirror_roots if root != target_root]
    migration_state = str(cfg.get("migration_state") or "").strip() or (
        "in_progress" if source_roots else "steady"
    )

    state = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now.isoformat(timespec="seconds"),
        "generation": previous_generation + 1,
        "writer": CONTRACT_OWNER,
        "active": {
            "seeding_root": active_root,
            "device_alias": active_alias,
        },
        "target": {
            "seeding_root": target_root,
            "device_alias": target_alias,
        },
        "cross_seed": {
            "link_root": cross_seed_link_root,
            "category": "cross-seed",
        },
        "migration": {
            "state": migration_state,
            "source_roots": source_roots,
            "target_root": target_root,
        },
        "aliases": _build_aliases(active_root, target_root),
        "mirror_roots": mirror_roots,
    }
    validate_seed_root_state(state)
    return state


def publish_seed_root_state(path: Optional[Path] = None, cfg: Optional[dict] = None) -> tuple[Path, dict]:
    output_path = Path(path or SEED_ROOT_STATE_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    state = build_seed_root_state(cfg, previous_generation=_existing_generation(output_path))

    with NamedTemporaryFile("w", encoding="utf-8", dir=str(output_path.parent), delete=False) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        temp_path = Path(handle.name)

    temp_path.replace(output_path)
    return output_path, state
