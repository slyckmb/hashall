"""
Orphan repoint: scan RT and qB for torrents referencing paths under the orphan
directory and repoint each to its canonical seeding path.

Orphan dir: /pool/media/torrents/orphans/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hashall.qbittorrent import (
    DEFAULT_QB_CACHE_FILE,
    QBittorrentClient,
    get_torrents_from_cache,
)
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    RTSessionEntry,
    load_rt_session_directories,
    rt_apply_directory_repoint,
)
from hashall.save_path_inference import infer_canonical_save_path
from hashall.scan import scan_path

ORPHAN_DIR_PREFIX = "/pool/media/torrents/orphans/"
ORPHAN_DIR_PREFIX_ALT = "/data/media/torrents/orphans/"

ORPHAN_PATH_PREFIXES = (ORPHAN_DIR_PREFIX, ORPHAN_DIR_PREFIX_ALT)


@dataclass
class OrphanRef:
    """A torrent reference pointing into the orphan directory."""
    torrent_hash: str
    name: str
    source: str  # "RT" or "qB"
    current_path: str
    canonical_path: str | None


def scan_rt(session_dir: Path = DEFAULT_RT_SESSION_DIR) -> list[OrphanRef]:
    """Scan RT session files for torrents whose d.directory is under the orphan dir."""
    entries = load_rt_session_directories(session_dir)
    hits: list[OrphanRef] = []
    for th, entry in entries.items():
        if _is_orphan_path(entry.directory):
            hits.append(OrphanRef(
                torrent_hash=th,
                name=_torrent_name_from_hash(th),
                source="RT",
                current_path=entry.directory,
                canonical_path=None,
            ))
    return hits


def scan_qb(*, cache_path: Path | None = None) -> list[OrphanRef]:
    """Scan qB cache (or live API) for torrents whose save_path is under the orphan dir.

    Tries cache first; falls back to live API if cache is stale or absent.
    """
    cached = get_torrents_from_cache(max_age_s=120.0, cache_path=cache_path)
    if cached is not None:
        return _scan_qb_dicts(cached)

    client = QBittorrentClient()
    live = client.get_torrents()
    return _scan_qb_objects(live)


def _scan_qb_dicts(entries: list[dict]) -> list[OrphanRef]:
    hits: list[OrphanRef] = []
    for t in entries:
        save_path = str(t.get("save_path") or t.get("savePath") or "")
        if _is_orphan_path(save_path):
            hits.append(OrphanRef(
                torrent_hash=str(t.get("hash", "")),
                name=str(t.get("name", "")),
                source="qB",
                current_path=save_path,
                canonical_path=None,
            ))
    return hits


def _scan_qb_objects(entries: list) -> list[OrphanRef]:
    hits: list[OrphanRef] = []
    for t in entries:
        sp = str(getattr(t, "save_path", "") or "")
        if _is_orphan_path(sp):
            hits.append(OrphanRef(
                torrent_hash=str(getattr(t, "hash", "")),
                name=str(getattr(t, "name", "")),
                source="qB",
                current_path=sp,
                canonical_path=None,
            ))
    return hits


def build_qb_lookup(*, cache_path: Path | None = None) -> dict[str, dict]:
    """Build a dict[hash_lower -> qb_entry] from cache or live API."""
    cached = get_torrents_from_cache(max_age_s=120.0, cache_path=cache_path)
    if cached is not None:
        return {str(e.get("hash", "")).lower(): e for e in cached if e.get("hash")}

    client = QBittorrentClient()
    live = client.get_torrents()
    out: dict[str, dict] = {}
    for t in live:
        h = str(getattr(t, "hash", "")).lower()
        if h:
            out[h] = {
                "hash": getattr(t, "hash", ""),
                "name": getattr(t, "name", ""),
                "save_path": getattr(t, "save_path", ""),
                "content_path": getattr(t, "content_path", ""),
                "category": getattr(t, "category", ""),
                "tags": getattr(t, "tags", ""),
            }
    return out


def resolve_canonical_path(
    ref: OrphanRef,
    qb_lookup: dict[str, dict] | None = None,
) -> str | None:
    """Resolve the canonical seeding path for an orphan reference.

    For qB items, infers directly from qB metadata.
    For RT items, tries qB mirror lookup first, then falls back to inference
    with whatever metadata is available.
    """
    if ref.source == "qB":
        qb_entry = qb_lookup.get(ref.torrent_hash.lower()) if qb_lookup else None
        if qb_entry:
            inferred = infer_canonical_save_path(
                category=str(qb_entry.get("category", "")),
                tags=str(qb_entry.get("tags", "")),
                current_save_path=str(qb_entry.get("save_path", "")),
                current_content_path=str(qb_entry.get("content_path", "")),
            )
            if inferred.reliability != "ambiguous":
                return inferred.canonical_save_path
        return None

    if qb_lookup:
        qb_entry = qb_lookup.get(ref.torrent_hash.lower())
        if qb_entry:
            inferred = infer_canonical_save_path(
                category=str(qb_entry.get("category", "")),
                tags=str(qb_entry.get("tags", "")),
                current_save_path=str(qb_entry.get("save_path", "")),
                current_content_path=str(qb_entry.get("content_path", "")),
                current_rt_directory=ref.current_path,
            )
            if inferred.reliability != "ambiguous":
                return inferred.canonical_save_path

    inferred = infer_canonical_save_path(
        category="",
        tags="",
        current_save_path=ref.current_path,
        current_content_path=ref.current_path,
        current_rt_directory=ref.current_path,
    )
    if inferred.reliability != "ambiguous":
        return inferred.canonical_save_path
    return None


def repoint_rt(ref: OrphanRef, rpc_url: str = DEFAULT_RT_RPC_URL) -> bool:
    """Repoint an RT torrent to its canonical path."""
    if not ref.canonical_path:
        return False
    try:
        rt_apply_directory_repoint(
            torrent_hash=ref.torrent_hash,
            target_directory=ref.canonical_path,
            rpc_url=rpc_url,
            restart=True,
            check_before_start=True,
        )
        return True
    except Exception:
        return False


def repoint_qb(ref: OrphanRef) -> bool:
    """Repoint a qB torrent to its canonical path."""
    if not ref.canonical_path:
        return False
    try:
        client = QBittorrentClient()
        return client.set_location(ref.torrent_hash, ref.canonical_path)
    except Exception:
        return False


def _is_orphan_path(path: str) -> bool:
    if not path:
        return False
    norm = str(path).rstrip("/")
    for prefix in ORPHAN_PATH_PREFIXES:
        if norm == prefix.rstrip("/") or norm.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _torrent_name_from_hash(torrent_hash: str) -> str:
    return f"<{torrent_hash[:8]}>"


def run_orphan_repoint(
    *,
    dry_run: bool = True,
    rt_session_dir: Path = DEFAULT_RT_SESSION_DIR,
    qb_cache_path: Path | None = None,
    rt_rpc_url: str = DEFAULT_RT_RPC_URL,
    auto_scan: bool = True,
) -> dict:
    """Orchestrate orphan repoint scan + resolution + optional execution.

    Returns a summary dict with scan results and per-item outcomes.

    If auto_scan=True (default), triggers a hashall scan of the orphan directory
    tree after all repoints to sync the catalog with disk state (detect deletions
    from rm/mv operations, update metadata). Pass auto_scan=False when
    sequencing multiple ops where a single final sync suffices.
    """
    qb_lookup = build_qb_lookup(cache_path=qb_cache_path)

    rt_hits = scan_rt(session_dir=rt_session_dir)
    qb_hits = scan_qb(cache_path=qb_cache_path)

    all_hits: list[OrphanRef] = rt_hits + qb_hits
    seen: set[str] = set()
    deduped: list[OrphanRef] = []
    for h in all_hits:
        key = f"{h.torrent_hash}:{h.source}"
        if key not in seen:
            seen.add(key)
            deduped.append(h)
    all_hits = deduped

    for ref in all_hits:
        ref.canonical_path = resolve_canonical_path(ref, qb_lookup=qb_lookup)

    results: list[dict] = []
    rt_repointed = 0
    qb_repointed = 0
    failed = 0

    for ref in all_hits:
        entry = {
            "torrent_hash": ref.torrent_hash,
            "name": ref.name,
            "source": ref.source,
            "current_path": ref.current_path,
            "canonical_path": ref.canonical_path,
            "action": "skipped",
        }
        if not ref.canonical_path:
            entry["action"] = "no_canonical_path"
            results.append(entry)
            failed += 1
            continue

        if dry_run:
            entry["action"] = "dry_run"
            results.append(entry)
            continue

        if ref.source == "RT":
            ok = repoint_rt(ref, rpc_url=rt_rpc_url)
            if ok:
                entry["action"] = "repointed_rt"
                rt_repointed += 1
            else:
                entry["action"] = "failed"
                failed += 1
        elif ref.source == "qB":
            ok = repoint_qb(ref)
            if ok:
                entry["action"] = "repointed_qb"
                qb_repointed += 1
            else:
                entry["action"] = "failed"
                failed += 1

        results.append(entry)

    if auto_scan and not dry_run:
        try:
            from pathlib import Path as _P
            _db = _P.home() / ".hashall" / "catalog.db"
            scan_path(_db, Path(ORPHAN_DIR_PREFIX), hash_mode="fast", parallel=True)
            print("  DB sync: orphan dir scanned (fast mode)")
        except Exception as e:
            print(f"  DB sync failed: {e}")

    return {
        "dry_run": dry_run,
        "rt_scanned": len(rt_hits),
        "qb_scanned": len(qb_hits),
        "total_orphan_refs": len(all_hits),
        "rt_repointed": rt_repointed,
        "qb_repointed": qb_repointed,
        "failed": failed,
        "results": results,
    }
