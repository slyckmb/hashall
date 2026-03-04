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
    "stash_device": "stash",
    "pool_device": "pool",
    "pool_payload_root": "/pool/data/seeds",
    "seeding_root": "/stash/media",
    "library_root": "/stash/media",
    "catalog": "~/.hashall/catalog.db",
    "extra_scan_roots": [],
}


def load_config() -> dict:
    """Load config from disk, merged over hard defaults."""
    cfg: dict = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user_cfg = tomllib.load(f)
        for k, v in user_cfg.items():
            if isinstance(v, list):
                cfg[k] = [str(x) for x in v]
            else:
                cfg[k] = str(v)
    return cfg


def _load_raw() -> dict:
    """Load only what's persisted on disk (no defaults merged)."""
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
    """Write a single scalar key to the config file."""
    cfg = _load_raw()
    cfg[key] = value
    _write_config(cfg)


def _toml_str(v: str) -> str:
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Extra scan roots helpers
# ---------------------------------------------------------------------------

def parse_extra_scan_roots(roots: list) -> list[tuple[str, str]]:
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


def add_scan_root(path: str, alias: str) -> None:
    """
    Upsert a path:alias entry in extra_scan_roots.

    If an entry with the same path already exists it is replaced (alias updated).
    """
    cfg = _load_raw()
    existing: list[str] = list(cfg.get("extra_scan_roots") or [])
    # Remove any existing entry for this path
    existing = [e for e in existing if not _root_path_matches(e, path)]
    existing.append(f"{path}:{alias}")
    cfg["extra_scan_roots"] = existing
    _write_config(cfg)


def remove_scan_root(path: str) -> bool:
    """
    Remove the entry matching *path* from extra_scan_roots.

    Returns True if an entry was removed, False if nothing matched.
    """
    cfg = _load_raw()
    existing: list[str] = list(cfg.get("extra_scan_roots") or [])
    filtered = [e for e in existing if not _root_path_matches(e, path)]
    removed = len(filtered) < len(existing)
    cfg["extra_scan_roots"] = filtered
    _write_config(cfg)
    return removed


def _root_path_matches(entry: str, path: str) -> bool:
    """Return True if *entry* (a "path:alias" string) refers to *path*."""
    if ":" in entry:
        entry_path = entry.rsplit(":", 1)[0].strip()
    else:
        entry_path = entry.strip()
    return entry_path == path.strip()
