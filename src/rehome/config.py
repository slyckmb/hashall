"""
Persistent configuration for rehome (~/.hashall/rehome.toml).
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    try:
        import tomllib  # type: ignore
    except ImportError:
        import tomli as tomllib  # type: ignore

CONFIG_PATH = Path.home() / ".hashall" / "rehome.toml"

DEFAULTS: dict = {
    "active_device": "stash",
    "active_root": "/stash/media",
    "content_root": "/stash/media",
    "default_dest_device": "pool",
    "default_dest_root": "/pool/data/seeds",
    "catalog": "~/.hashall/catalog.db",
    "managed_roots": [],
}

# Old key → new canonical key (backwards compatibility)
_KEY_RENAMES: dict[str, str] = {
    "stash_device": "active_device",
    "seeding_root": "active_root",
    "library_root": "content_root",
    "pool_device": "default_dest_device",
    "pool_payload_root": "default_dest_root",
    "extra_scan_roots": "managed_roots",
}


def load_config() -> dict:
    """Load config from disk, merged over hard defaults. Old keys are normalized."""
    cfg: dict = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user_cfg = tomllib.load(f)
        for k, v in user_cfg.items():
            canonical_k = _KEY_RENAMES.get(k, k)
            if isinstance(v, list):
                cfg[canonical_k] = [str(x) for x in v]
            else:
                cfg[canonical_k] = str(v)
    return cfg


def _load_raw() -> dict:
    """Load only what's persisted on disk (no defaults merged, no key normalization)."""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        raw = tomllib.load(f)
    return {k: ([str(x) for x in v] if isinstance(v, list) else str(v)) for k, v in raw.items()}


def _write_config(cfg: dict) -> None:
    """Write cfg to disk as TOML (handles both scalar strings and string lists)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for k in sorted(cfg.keys()):
        v = cfg[k]
        if isinstance(v, list):
            if v:
                items = ", ".join(_toml_str(x) for x in v)
                lines.append(f"{k} = [{items}]\n")
            else:
                lines.append(f"{k} = []\n")
        else:
            lines.append(f"{k} = {_toml_str(str(v))}\n")
    CONFIG_PATH.write_text("".join(lines))


def save_config_key(key: str, value: str) -> None:
    """Write a single scalar key to the config file. Normalizes old key names."""
    canonical = _KEY_RENAMES.get(key, key)
    cfg = _load_raw()
    # Remove any lingering old key before writing canonical
    for old_k, new_k in _KEY_RENAMES.items():
        if new_k == canonical and old_k in cfg:
            del cfg[old_k]
    cfg[canonical] = value
    _write_config(cfg)


def _toml_str(v: str) -> str:
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Managed roots helpers
# ---------------------------------------------------------------------------

def parse_managed_roots(roots: list) -> list[tuple[str, str]]:
    """
    Parse a list of "path:alias" strings into [(path, alias), ...] tuples.

    If an entry has no colon, the alias falls back to the path's basename.
    """
    result: list[tuple[str, str]] = []
    for entry in roots:
        s = str(entry).strip()
        if not s:
            continue
        if ":" in s:
            path, alias = s.rsplit(":", 1)
            result.append((path.strip(), alias.strip()))
        else:
            result.append((s, Path(s).name))
    return result


# Backwards compatibility alias
parse_extra_scan_roots = parse_managed_roots


def add_scan_root(path: str, alias: str) -> None:
    """
    Upsert a path:alias entry in managed_roots.

    If an entry with the same path already exists it is replaced (alias updated).
    """
    cfg = _load_raw()
    # Read from either key name for compatibility
    existing: list[str] = list(cfg.get("managed_roots") or cfg.get("extra_scan_roots") or [])
    # Remove any existing entry for this path
    existing = [e for e in existing if not _root_path_matches(e, path)]
    existing.append(f"{path}:{alias}")
    # Always write under canonical key; remove old key if present
    if "extra_scan_roots" in cfg:
        del cfg["extra_scan_roots"]
    cfg["managed_roots"] = existing
    _write_config(cfg)


def remove_scan_root(path: str) -> bool:
    """
    Remove the entry matching *path* from managed_roots.

    Returns True if an entry was removed, False if nothing matched.
    """
    cfg = _load_raw()
    existing: list[str] = list(cfg.get("managed_roots") or cfg.get("extra_scan_roots") or [])
    filtered = [e for e in existing if not _root_path_matches(e, path)]
    removed = len(filtered) < len(existing)
    if "extra_scan_roots" in cfg:
        del cfg["extra_scan_roots"]
    cfg["managed_roots"] = filtered
    _write_config(cfg)
    return removed


def _root_path_matches(entry: str, path: str) -> bool:
    """Return True if *entry* (a "path:alias" string) refers to *path*."""
    if ":" in entry:
        entry_path = entry.rsplit(":", 1)[0].strip()
    else:
        entry_path = entry.strip()
    return entry_path == path.strip()
