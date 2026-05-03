"""
rt_torrent_replace — Replace a corrupted or compromised RT torrent with a clean one.

Two operation modes:
  same_hash: replacement .torrent has the same infohash (info dict unchanged; only
             the announce list differs). Overwrites the session .torrent file and
             calls rt_reset_torrent_session() which stops/erases/reloads/rechecks.
  new_hash:  replacement has a different infohash. Loads new torrent pointing at
             existing data, waits for RT to register it, rechecks, erases old entry.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from hashall.bencode import bencode_decode, bencode_encode
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    rt_build_load_cmd,
    rt_recheck_torrent,
    rt_reset_torrent_session,
    rt_wait_for_hash_present,
    rt_xmlrpc_call,
    fetch_rt_status_rows,
)


DEFAULT_PROWLARR_URL = "http://localhost:9696"
DEFAULT_PROWLARR_KEY_FILES = [
    "/mnt/config/secrets/prowlarr/prowlarr-api-key.env",
    "/mnt/config/secrets/lazylibrarian/api-key.env",
    "/mnt/config/secrets/bash/bash_prowlarr-api-key.env",
]

# Keyword fragments that identify known public trackers
_PUBLIC_TRACKER_FRAGMENTS = frozenset({
    "opentrackr", "bt4g", "tracker.bz", "tracker.qu.ax", "p4p.arenabg",
    "seeders-paradise", "tracker.dler.org", "tracker.moeking", "1337.abcvg",
    "tracker.waaa", "tracker.skyts", "bt1.xxxxbt", "buny.uk", "bvarf.tracker",
    "tracker.opentrackr", "tracker.openbittorrent", "shubt.net", "tracker.dler",
    "tracker.sbsub", "jvavav.com", "bittorrent-tracker.e-n-c-r-y-p-t",
})


@dataclass
class TorrentMeta:
    infohash: str
    name: str
    total_bytes: int
    file_count: int
    is_private: bool
    trackers: list[str] = field(default_factory=list)
    has_public_trackers: bool = False

    @property
    def tracker_count(self) -> int:
        return len(self.trackers)


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    same_hash: bool = False
    replacement_meta: TorrentMeta | None = None


def compute_torrent_infohash(torrent_bytes: bytes) -> str:
    """Return the SHA1 infohash (hex) for the given raw .torrent bytes."""
    data = bencode_decode(torrent_bytes)
    if not isinstance(data, dict):
        raise ValueError("not a valid torrent file")
    info = data.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("torrent missing info dict")
    return hashlib.sha1(bencode_encode(info)).hexdigest()


def parse_torrent_metadata(torrent_bytes: bytes) -> TorrentMeta:
    """Parse .torrent bytes into TorrentMeta."""
    data = bencode_decode(torrent_bytes)
    if not isinstance(data, dict):
        raise ValueError("not a valid torrent file")
    info = data.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("torrent missing info dict")

    infohash = hashlib.sha1(bencode_encode(info)).hexdigest()
    name = (info.get(b"name") or b"").decode("utf-8", "ignore")
    is_private = bool(info.get(b"private"))

    files = info.get(b"files")
    if isinstance(files, list):
        total_bytes = sum(int(f.get(b"length", 0) or 0) for f in files if isinstance(f, dict))
        file_count = len(files)
    else:
        total_bytes = int(info.get(b"length", 0) or 0)
        file_count = 1 if total_bytes > 0 else 0

    trackers: list[str] = []
    if b"announce" in data:
        url = (data[b"announce"] or b"").decode("utf-8", "ignore").strip()
        if url:
            trackers.append(url)
    for tier in (data.get(b"announce-list") or []):
        for t in tier:
            url = (t or b"").decode("utf-8", "ignore").strip()
            if url and url not in trackers:
                trackers.append(url)

    has_public = any(
        any(frag in u.lower() for frag in _PUBLIC_TRACKER_FRAGMENTS)
        for u in trackers
    )

    return TorrentMeta(
        infohash=infohash,
        name=name,
        total_bytes=total_bytes,
        file_count=file_count,
        is_private=is_private,
        trackers=trackers,
        has_public_trackers=has_public,
    )


def validate_replacement(
    current_hash: str,
    current_name: str,
    current_size: int,
    replacement_bytes: bytes,
    *,
    size_tolerance: float = 0.01,
) -> ValidationResult:
    """
    Validate that replacement_bytes is a suitable replacement for the current torrent.
    Returns a ValidationResult with ok=True and same_hash flag if acceptable.
    """
    try:
        meta = parse_torrent_metadata(replacement_bytes)
    except Exception as exc:
        return ValidationResult(ok=False, reason=f"parse_error: {exc}")

    def _norm(s: str) -> str:
        return s.lower().replace(".", " ").replace("_", " ").strip()

    curr_norm = _norm(current_name)
    repl_norm = _norm(meta.name)
    if curr_norm != repl_norm and curr_norm not in repl_norm and repl_norm not in curr_norm:
        return ValidationResult(
            ok=False,
            reason=f"name_mismatch: current={current_name!r} replacement={meta.name!r}",
            replacement_meta=meta,
        )

    if current_size > 0:
        diff = abs(meta.total_bytes - current_size) / current_size
        if diff > size_tolerance:
            return ValidationResult(
                ok=False,
                reason=f"size_mismatch: current={current_size} replacement={meta.total_bytes} diff={diff:.1%}",
                replacement_meta=meta,
            )

    same_hash = meta.infohash.lower() == current_hash.strip().lower()
    return ValidationResult(ok=True, reason="ok", same_hash=same_hash, replacement_meta=meta)


# ---------------------------------------------------------------------------
# Prowlarr helpers
# ---------------------------------------------------------------------------

def load_prowlarr_api_key(api_key_file: str = "") -> str:
    candidates = [api_key_file] if api_key_file else []
    if not api_key_file or api_key_file == DEFAULT_PROWLARR_KEY_FILES[0]:
        candidates = list(DEFAULT_PROWLARR_KEY_FILES)
    else:
        candidates.extend(f for f in DEFAULT_PROWLARR_KEY_FILES if f != api_key_file)
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        for line in path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError(f"Prowlarr API key not found; tried: {candidates}")


def fetch_prowlarr_replacement(
    name: str,
    tracker_host: str,
    *,
    prowlarr_url: str = DEFAULT_PROWLARR_URL,
    api_key_file: str = "",
    timeout: float = 30.0,
) -> tuple[bytes | None, str]:
    """
    Search Prowlarr for a replacement torrent matching name on tracker_host.
    Returns (torrent_bytes, download_url) or (None, error_reason).
    """
    api_key = load_prowlarr_api_key(api_key_file)
    session = requests.Session()
    session.headers["X-Api-Key"] = api_key

    # Find matching indexer by tracker hostname
    try:
        resp = session.get(f"{prowlarr_url.rstrip('/')}/api/v1/indexer", timeout=timeout)
        resp.raise_for_status()
        indexers: list[dict] = resp.json() if isinstance(resp.json(), list) else []
    except Exception as exc:
        return None, f"prowlarr_indexer_error: {exc}"

    host_lower = tracker_host.lower()
    host_parts = [p for p in host_lower.split(".") if len(p) > 3]

    indexer_id: int | None = None
    indexer_name: str = ""
    for idx in indexers:
        fields_text = " ".join(str(f.get("value", "")) for f in (idx.get("fields") or []))
        combined = f"{idx.get('name', '')} {fields_text}".lower()
        if host_lower in combined or any(p in combined for p in host_parts):
            indexer_id = int(idx["id"]) if idx.get("id") is not None else None
            indexer_name = str(idx.get("name") or "")
            break

    # Search
    # Normalize for Prowlarr: strip extension, punctuation, and parenthetical
    # qualifiers like "(2nd ed)" that reduce match rate.
    import os
    search_name = os.path.splitext(name)[0]
    search_name = re.sub(r"\([^)]*\)", " ", search_name)  # drop parentheticals
    search_name = re.sub(r"[.\-_]", " ", search_name)
    search_name = re.sub(r"\s+", " ", search_name).strip()

    params: dict[str, Any] = {"query": search_name, "type": "search", "limit": "10"}
    if indexer_id is not None:
        params["indexerIds"] = indexer_id
    try:
        resp = session.get(f"{prowlarr_url.rstrip('/')}/api/v1/search", params=params, timeout=timeout)
        resp.raise_for_status()
        hits: list[dict] = resp.json() if isinstance(resp.json(), list) else []
    except Exception as exc:
        return None, f"prowlarr_search_error: {exc}"

    if not hits:
        return None, f"no_hits (query={search_name!r})"

    def _score(h: dict) -> tuple:
        same = int((h.get("indexer") or "").lower() == indexer_name.lower())
        return (same, int(h.get("seeders") or 0))

    best = max(hits, key=_score)
    download_url = str(best.get("downloadUrl") or "").strip()
    if not download_url:
        return None, "no_download_url"

    try:
        resp = session.get(download_url, timeout=timeout)
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:
        return None, f"download_error: {exc}"

    if not content or content[:1] not in {b"d", b"e"}:
        return None, "not_a_torrent_file"

    return content, download_url


# ---------------------------------------------------------------------------
# RT lookup helper
# ---------------------------------------------------------------------------

def rt_get_torrent_info_live(
    torrent_hash: str,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> dict[str, Any] | None:
    """
    Return {name, directory, label, trackers, size} from live RT for the given hash.
    Returns None if the hash is not currently loaded in RT.
    """
    target = torrent_hash.strip().lower()
    rows = fetch_rt_status_rows(rpc_url=rpc_url)
    row = next((r for r in rows if r["hash"] == target), None)
    if row is None:
        return None

    # Get label (d.custom1)
    label = ""
    try:
        xml = rt_xmlrpc_call("d.custom1", target, rpc_url=rpc_url)
        m = re.search(r"<string>(.*?)</string>", xml, re.DOTALL)
        if m:
            label = m.group(1).strip()
    except Exception:
        pass

    # Get trackers via t.multicall
    trackers: list[str] = []
    try:
        xml = rt_xmlrpc_call("t.multicall", target, "", "t.url=", rpc_url=rpc_url)
        for m in re.finditer(r"<string>([^<]+)</string>", xml):
            url = m.group(1).strip()
            if url.startswith("http") and url not in trackers:
                trackers.append(url)
    except Exception:
        pass

    # Get size from session .torrent
    size = 0
    try:
        from hashall.rtorrent import load_rt_torrent_meta
        meta = load_rt_torrent_meta(DEFAULT_RT_SESSION_DIR, target)
        if meta:
            size = meta.total_bytes
    except Exception:
        pass

    return {
        "name": row["name"],
        "directory": row["directory"],
        "label": label,
        "trackers": trackers,
        "size": size,
    }


# ---------------------------------------------------------------------------
# Core replacement execution
# ---------------------------------------------------------------------------

def _inject_announce_list(torrent_bytes: bytes, trackers: list[str]) -> bytes:
    """
    Return torrent_bytes with the given trackers injected as announce / announce-list.
    The info dict is not touched, so the infohash is unchanged.
    Each tracker gets its own tier so all are tried independently.
    """
    data = bencode_decode(torrent_bytes)
    data[b"announce"] = trackers[0].encode()
    data[b"announce-list"] = [[u.encode()] for u in trackers]
    return bencode_encode(data)


def replace_torrent(
    torrent_hash: str,
    replacement_bytes: bytes,
    *,
    directory: str,
    label: str,
    inject_trackers: list[str] | None = None,
    session_dir: Path = DEFAULT_RT_SESSION_DIR,
    backup_root: Path = Path("out/rt-torrent-replace"),
    rpc_url: str = DEFAULT_RT_RPC_URL,
    rpc_timeout: int = 20,
    verify_timeout_s: float = 30.0,
    same_hash: bool,
) -> dict[str, Any]:
    """
    Install replacement_bytes into RT for an existing torrent, reusing its on-disk data.

    inject_trackers: if the replacement has no announce-list and this list is non-empty,
                     inject the given tracker URLs into the bytes before loading so they
                     persist in the session .torrent after d.save_full_session.

    same_hash=True  — overwrite session .torrent + call rt_reset_torrent_session().
    same_hash=False — load.raw_start new hash, recheck, erase old hash.
    """
    torrent_hash = torrent_hash.strip().lower()

    # Inject private trackers into the replacement bytes if it has none.
    meta = parse_torrent_metadata(replacement_bytes)
    if inject_trackers and meta.tracker_count == 0:
        replacement_bytes = _inject_announce_list(replacement_bytes, inject_trackers)

    result: dict[str, Any] = {
        "old_hash": torrent_hash,
        "new_hash": None,
        "status": "unknown",
        "completed": [],
        "error": "",
        "backup_dir": "",
    }

    if same_hash:
        # Overwrite the .torrent file in the session directory before reset.
        # rt_reset_torrent_session reads it from there.
        session_torrent = session_dir / f"{torrent_hash.upper()}.torrent"
        if not session_torrent.exists():
            # some sessions use lowercase
            session_torrent = session_dir / f"{torrent_hash}.torrent"
        session_torrent.write_bytes(replacement_bytes)
        result["completed"].append("session.torrent.overwritten")

        reset = rt_reset_torrent_session(
            torrent_hash,
            target_directory=directory,
            session_dir=session_dir,
            backup_root=backup_root,
            rpc_url=rpc_url,
            rpc_timeout=rpc_timeout,
            verify_timeout_s=verify_timeout_s,
        )
        result["status"] = reset["status"]
        result["completed"].extend(reset["completed"])
        result["error"] = reset.get("error", "")
        result["backup_dir"] = reset.get("backup_dir", "")
        result["new_hash"] = torrent_hash

    else:
        # New hash path: load new torrent, wait, recheck, erase old.
        new_meta = parse_torrent_metadata(replacement_bytes)
        new_hash = new_meta.infohash

        # Write .torrent to session dir so RT can persist the session.
        new_session_torrent = session_dir / f"{new_hash.upper()}.torrent"
        new_session_torrent.write_bytes(replacement_bytes)
        result["completed"].append(f"session.torrent.written:{new_hash[:10]}")

        dir_cmd = rt_build_load_cmd("d.directory.set", directory)
        label_cmd = rt_build_load_cmd("d.custom1.set", label)
        try:
            rt_xmlrpc_call(
                "load.raw_start", "", replacement_bytes, dir_cmd, label_cmd,
                rpc_url=rpc_url, timeout=rpc_timeout,
            )
            result["completed"].append("load.raw_start")
        except Exception as exc:
            result["status"] = "blocked_load"
            result["error"] = str(exc)
            return result

        appeared = rt_wait_for_hash_present(new_hash, rpc_url=rpc_url, timeout_s=verify_timeout_s)
        if not appeared:
            result["status"] = "blocked_new_hash_not_found"
            result["error"] = f"new hash {new_hash[:10]} did not appear in RT within {verify_timeout_s}s"
            return result
        result["completed"].append("new_hash_present")

        try:
            recheck_steps = rt_recheck_torrent(new_hash, rpc_url=rpc_url, timeout=rpc_timeout)
            result["completed"].extend(recheck_steps)
        except Exception as exc:
            result["error"] = f"recheck_warning: {exc}"

        # Erase old hash
        for method in ("d.stop", "d.close", "d.erase"):
            try:
                rt_xmlrpc_call(method, torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout)
                result["completed"].append(f"old.{method}")
            except Exception:
                result["completed"].append(f"old.{method}:skip")

        try:
            rt_xmlrpc_call("session.save", rpc_url=rpc_url, timeout=rpc_timeout)
            result["completed"].append("session.save")
        except Exception:
            result["completed"].append("session.save:skip")

        result["new_hash"] = new_hash
        result["status"] = "verified"

    return result
