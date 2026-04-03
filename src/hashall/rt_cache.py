from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import time
from typing import Any


DEFAULT_RT_SHARED_CACHE_DIR = Path.home() / ".cache" / "silo-rt"
DEFAULT_RT_SHARED_CACHE_FILE = DEFAULT_RT_SHARED_CACHE_DIR / "torrents.json"
DEFAULT_RT_SHARED_CACHE_META_FILE = DEFAULT_RT_SHARED_CACHE_DIR / "torrents.meta.json"


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _normalize_cache_rows(rows_payload: Any) -> list[dict]:
    if not isinstance(rows_payload, list):
        return []
    rows: list[dict] = []
    for row in rows_payload:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "hash": str(row.get("hash") or "").strip().lower(),
                "name": str(row.get("name") or "").strip(),
                "directory": str(row.get("directory") or row.get("save_path") or "").strip(),
                "state": str(row.get("state") or "unknown").strip() or "unknown",
                "message": str(row.get("message") or "").strip(),
                "tracker": str(row.get("tracker") or "").strip(),
                "peers": _to_int(row.get("peers")),
                "dlspeed": _to_int(row.get("dlspeed")),
                "upspeed": _to_int(row.get("upspeed")),
            }
        )
    return rows


def load_rt_cache_snapshot(
    *,
    cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    meta_file: Path = DEFAULT_RT_SHARED_CACHE_META_FILE,
    max_age_s: float = 60.0,
) -> dict[str, Any]:
    cache_path = Path(cache_file).expanduser()
    meta_path = Path(meta_file).expanduser()
    rows = _normalize_cache_rows(_read_json_file(cache_path))
    meta = _read_json_file(meta_path)
    if not isinstance(meta, dict):
        meta = {}

    now = time.time()
    cache_age_s: float | None = None
    fetched_at = meta.get("fetched_at")
    if fetched_at is not None:
        try:
            cache_age_s = max(0.0, now - float(fetched_at))
        except Exception:
            cache_age_s = None
    if cache_age_s is None and cache_path.exists():
        try:
            cache_age_s = max(0.0, now - cache_path.stat().st_mtime)
        except OSError:
            cache_age_s = None

    cache_source = str(meta.get("source") or "").strip()
    if rows:
        freshness = "fresh"
        if cache_age_s is not None and cache_age_s > float(max_age_s):
            freshness = "stale"
        if cache_source == "daemon_error":
            freshness = "stale_error"
    else:
        freshness = "error" if cache_source == "daemon_error" else "missing"

    states = Counter(row["state"] for row in rows)
    return {
        "read_mode": "shared_cache",
        "cache_file": str(cache_path),
        "meta_file": str(meta_path),
        "rows": rows,
        "rows_total": len(rows),
        "cache_source": cache_source,
        "cache_age_s": cache_age_s,
        "max_age_s": float(max_age_s),
        "freshness": freshness,
        "last_error": str(meta.get("last_error") or "").strip(),
        "xmlrpc_url": str(meta.get("xmlrpc_url") or "").strip(),
        "consecutive_failures": _to_int(meta.get("consecutive_failures")),
        "state_counts": dict(states),
    }
