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

DEFAULTS: dict[str, str] = {
    "stash_device": "stash",
    "pool_device": "pool",
    "pool_payload_root": "/pool/data/seeds",
    "seeding_root": "/stash/media",
    "library_root": "/stash/media",
    "catalog": "~/.hashall/catalog.db",
}


def load_config() -> dict[str, str]:
    """Load config from disk, merged over hard defaults."""
    cfg: dict[str, str] = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            user_cfg = tomllib.load(f)
        cfg.update({k: str(v) for k, v in user_cfg.items()})
    return cfg


def save_config_key(key: str, value: str) -> None:
    """Write a single key to the config file."""
    cfg: dict[str, str] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = {k: str(v) for k, v in tomllib.load(f).items()}
    cfg[key] = value
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k} = {_toml_str(v)}\n" for k, v in sorted(cfg.items())]
    CONFIG_PATH.write_text("".join(lines))


def _toml_str(v: str) -> str:
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
