from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import os
from pathlib import Path
import json
import stat
import sqlite3
import time
from typing import Any, Iterable

from hashall.fs_utils import get_mount_point
from hashall.pathing import canonicalize_path, remap_to_mount_alias
from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE
from hashall.rt_cache import DEFAULT_RT_SHARED_CACHE_FILE
from hashall.rtorrent import DEFAULT_RT_SESSION_DIR, load_rt_torrent_meta, normalize_rt_target_directory, resolve_rt_session_files, rt_path_aligned
from hashall.save_path_inference import ARR_CATEGORY_FINAL_MAP


HEALTHY_QB_STATES = {"uploading", "stalledUP", "stoppedUP", "pausedUP"}
HEALTHY_RT_STATES = {"uploading", "stalledUP", "stoppedUP"}

DEFAULT_MIRROR_ROOTS = (
    "/data/media/torrents/seeding",
    "/pool/media/torrents/seeding",
    "/stash/media/torrents/seeding",
)

DEFAULT_POOL_PLACEMENT_ROOTS = (
    "/pool/media/torrents/seeding",
)

DEFAULT_STASH_PLACEMENT_ROOTS = (
    "/data/media/torrents/seeding",
    "/stash/media/torrents/seeding",
)

DEFAULT_ARR_LIBRARY_ROOTS = (
    "/data/media/books",
    "/data/media/downloads",
    "/data/media/movies",
    "/data/media/music",
    "/data/media/shows",
    "/data/media/tv",
    "/stash/media/books",
    "/stash/media/downloads",
    "/stash/media/movies",
    "/stash/media/music",
    "/stash/media/shows",
    "/stash/media/tv",
)

DEFAULT_ANCHOR_SCAN_MAX_FILES = 0
DEFAULT_CATALOG_PATH = Path("~/.hashall/catalog.db")


RT_MIRROR_TAG = "~rt-mirrored"   # qB tag: item was added via RT→qB mirror
QB_MIRROR_TAG = "~qb-mirrored"   # RT d.custom2 tag: item has a qB mirror
NO_HARDLINK_TAG = "~noHL"        # qB tag: qbit_manage did not find ARR hardlinks


@dataclass(frozen=True)
class ClientDriftPolicy:
    mirror_roots: tuple[str, ...] = ()
    mirror_rt_to_qb_categories: tuple[str, ...] = ()
    mirror_qb_to_rt_categories: tuple[str, ...] = ()
    ignore_rt_only_categories: tuple[str, ...] = ()
    ignore_qb_only_categories: tuple[str, ...] = ()
    ignore_rt_only_path_prefixes: tuple[str, ...] = ()
    ignore_qb_only_path_prefixes: tuple[str, ...] = ()
    remove_from_rt_categories: tuple[str, ...] = ()
    remove_from_qb_categories: tuple[str, ...] = ()
    remove_from_rt_path_prefixes: tuple[str, ...] = ()
    remove_from_qb_path_prefixes: tuple[str, ...] = ()
    pool_roots: tuple[str, ...] = DEFAULT_POOL_PLACEMENT_ROOTS
    stash_roots: tuple[str, ...] = DEFAULT_STASH_PLACEMENT_ROOTS
    arr_library_roots: tuple[str, ...] = DEFAULT_ARR_LIBRARY_ROOTS
    anchor_scan_max_files: int = DEFAULT_ANCHOR_SCAN_MAX_FILES
    recent_seconds: int = 0
    mode: str = "conservative"


@dataclass
class ClientTorrentRow:
    client: str
    torrent_hash: str
    name: str = ""
    save_path: str = ""
    content_path: str = ""
    category: str = ""
    tags: str = ""
    state: str = ""
    progress: float = 0.0
    size: int = 0
    tracker: str = ""
    added_on: int = 0
    added_display: str = ""
    path_exists: bool = False
    torrent_file: str = ""
    torrent_file_exists: bool = False
    target_qb_save_path: str = ""
    meta_loaded: bool = False
    is_multi_file: bool | None = None
    expected_file_count: int = 0
    expected_total_bytes: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "hash": self.torrent_hash,
            "name": self.name,
            "save_path": self.save_path,
            "content_path": self.content_path,
            "category": self.category,
            "tags": self.tags,
            "state": self.state,
            "progress": self.progress,
            "size": self.size,
            "tracker": self.tracker,
            "added_on": self.added_on,
            "added_display": self.added_display,
            "path_exists": self.path_exists,
            "torrent_file": self.torrent_file,
            "torrent_file_exists": self.torrent_file_exists,
            "target_qb_save_path": self.target_qb_save_path,
            "meta_loaded": self.meta_loaded,
            "is_multi_file": self.is_multi_file,
            "expected_file_count": self.expected_file_count,
            "expected_total_bytes": self.expected_total_bytes,
        }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Iterable):
        out = []
        for item in value:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return tuple(out)
    return ()


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _norm_hash(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text))
    except Exception:
        return text


def _path_exists(path: str) -> bool:
    return bool(path and Path(path).exists())


def _policy_mount_points(policy: ClientDriftPolicy) -> tuple[Path, ...]:
    roots = (
        *policy.mirror_roots,
        *policy.pool_roots,
        *policy.stash_roots,
        *policy.arr_library_roots,
    )
    out: list[Path] = []
    seen: set[str] = set()
    for raw_root in roots:
        root = str(raw_root or "").strip()
        if not root:
            continue
        try:
            mount = get_mount_point(root) or ""
        except Exception:
            mount = ""
        if not mount:
            continue
        mount_text = str(Path(mount))
        if mount_text not in seen:
            seen.add(mount_text)
            out.append(Path(mount_text))
    return tuple(out)


def _path_variants(path: str, policy: ClientDriftPolicy) -> tuple[str, ...]:
    text = _norm_path(path).rstrip("/")
    if not text:
        return ()

    out: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | Path | None) -> None:
        value = str(candidate or "").rstrip("/")
        if value and value not in seen:
            seen.add(value)
            out.append(value)

    add(text)
    try:
        add(canonicalize_path(Path(text)))
    except Exception:
        pass

    for mount_point in _policy_mount_points(policy):
        for candidate in tuple(out):
            try:
                remapped = remap_to_mount_alias(Path(candidate), mount_point)
            except Exception:
                remapped = None
            if remapped is None:
                continue
            add(remapped)
            try:
                add(canonicalize_path(remapped))
            except Exception:
                pass

    return tuple(out)


def _path_variants_many(paths: Iterable[str], policy: ClientDriftPolicy) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for variant in _path_variants(path, policy):
            if variant not in seen:
                seen.add(variant)
                out.append(variant)
    return tuple(out)


def _under_any_policy_prefix(path: str, prefixes: Iterable[str], policy: ClientDriftPolicy) -> bool:
    return any(_under_any_prefix(variant, prefixes) for variant in _path_variants(path, policy))


def _under_any_prefix(path: str, prefixes: Iterable[str]) -> bool:
    candidate = str(path or "").rstrip("/")
    if not candidate:
        return False
    for raw_prefix in prefixes:
        prefix = str(raw_prefix or "").rstrip("/")
        if prefix and (candidate == prefix or candidate.startswith(prefix + "/")):
            return True
    return False


def _category_in(category: str, categories: Iterable[str]) -> bool:
    wanted = {str(item or "").strip().lower() for item in categories if str(item or "").strip()}
    return bool(wanted and str(category or "").strip().lower() in wanted)


def _has_tag(tags_str: str, tag: str) -> bool:
    """Exact-match tag check; tags_str is comma-separated."""
    needle = tag.strip().lower()
    return any(t.strip().lower() == needle for t in str(tags_str or "").split(",") if t.strip())


def _infer_category_from_path(path: str, mirror_roots: Iterable[str]) -> str:
    candidate = Path(path) if path else None
    if candidate is None:
        return ""
    for raw_root in mirror_roots:
        root = Path(str(raw_root or ""))
        try:
            rel = candidate.relative_to(root)
        except ValueError:
            continue
        return rel.parts[0] if rel.parts else ""
    return ""


def _rt_path_aligned_with_policy(
    rt_directory: str | None,
    *,
    qb_save_path: str | None,
    qb_content_path: str | None,
    policy: ClientDriftPolicy,
) -> bool:
    if rt_path_aligned(rt_directory, qb_save_path=qb_save_path, qb_content_path=qb_content_path):
        return True

    rt_variants = set(_path_variants(str(rt_directory or ""), policy))
    if not rt_variants:
        return False

    candidates: list[str] = []
    for raw in (qb_save_path, qb_content_path):
        text = str(raw or "").strip()
        if not text:
            continue
        candidates.append(text)
        try:
            parent = str(Path(text).parent)
        except Exception:
            parent = ""
        if parent:
            candidates.append(parent)

    for candidate in candidates:
        if rt_variants.intersection(_path_variants(candidate, policy)):
            return True
    return False


def default_policy(mode: str = "conservative") -> ClientDriftPolicy:
    policy_mode = str(mode or "conservative").strip().lower()
    if policy_mode == "rt-authoritative-mirror":
        return ClientDriftPolicy(
            mirror_roots=DEFAULT_MIRROR_ROOTS,
            mode=policy_mode,
        )
    return ClientDriftPolicy(mode="conservative")


def load_policy(path: Path | None = None, *, mode: str = "conservative") -> ClientDriftPolicy:
    base = default_policy(mode)
    if path is None:
        return base
    payload = _read_json(path.expanduser())
    if not isinstance(payload, dict):
        raise ValueError(f"policy file is not a JSON object: {path}")

    data = {
        "mirror_roots": _as_tuple(payload.get("mirror_roots", base.mirror_roots)),
        "mirror_rt_to_qb_categories": _as_tuple(payload.get("mirror_rt_to_qb_categories", base.mirror_rt_to_qb_categories)),
        "mirror_qb_to_rt_categories": _as_tuple(payload.get("mirror_qb_to_rt_categories", base.mirror_qb_to_rt_categories)),
        "ignore_rt_only_categories": _as_tuple(payload.get("ignore_rt_only_categories", base.ignore_rt_only_categories)),
        "ignore_qb_only_categories": _as_tuple(payload.get("ignore_qb_only_categories", base.ignore_qb_only_categories)),
        "ignore_rt_only_path_prefixes": _as_tuple(payload.get("ignore_rt_only_path_prefixes", base.ignore_rt_only_path_prefixes)),
        "ignore_qb_only_path_prefixes": _as_tuple(payload.get("ignore_qb_only_path_prefixes", base.ignore_qb_only_path_prefixes)),
        "remove_from_rt_categories": _as_tuple(payload.get("remove_from_rt_categories", base.remove_from_rt_categories)),
        "remove_from_qb_categories": _as_tuple(payload.get("remove_from_qb_categories", base.remove_from_qb_categories)),
        "remove_from_rt_path_prefixes": _as_tuple(payload.get("remove_from_rt_path_prefixes", base.remove_from_rt_path_prefixes)),
        "remove_from_qb_path_prefixes": _as_tuple(payload.get("remove_from_qb_path_prefixes", base.remove_from_qb_path_prefixes)),
        "pool_roots": _as_tuple(payload.get("pool_roots", base.pool_roots)),
        "stash_roots": _as_tuple(payload.get("stash_roots", base.stash_roots)),
        "arr_library_roots": _as_tuple(payload.get("arr_library_roots", base.arr_library_roots)),
        "anchor_scan_max_files": _to_int(payload.get("anchor_scan_max_files", base.anchor_scan_max_files)),
        "recent_seconds": _to_int(payload.get("recent_seconds", base.recent_seconds)),
        "mode": str(payload.get("mode") or base.mode),
    }
    return ClientDriftPolicy(**data)


def load_qb_cache_rows(cache_file: Path = DEFAULT_QB_CACHE_FILE) -> dict[str, ClientTorrentRow]:
    payload = _read_json(cache_file.expanduser())
    if not isinstance(payload, list):
        return {}
    rows: dict[str, ClientTorrentRow] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        torrent_hash = _norm_hash(raw.get("hash"))
        if not torrent_hash:
            continue
        name = str(raw.get("name") or "").strip()
        save_path = _norm_path(raw.get("save_path"))
        content_path = _norm_path(raw.get("content_path")) or str(Path(save_path) / name if save_path and name else "")
        rows[torrent_hash] = ClientTorrentRow(
            client="qb",
            torrent_hash=torrent_hash,
            name=name,
            save_path=save_path,
            content_path=content_path,
            category=str(raw.get("category") or "").strip(),
            tags=str(raw.get("tags") or "").strip(),
            state=str(raw.get("state") or "").strip(),
            progress=_to_float(raw.get("progress")),
            size=_to_int(raw.get("size")),
            tracker=str(raw.get("tracker") or raw.get("primary_tracker") or "").strip(),
            added_on=_to_int(raw.get("added_on")),
            path_exists=_path_exists(content_path),
            raw=dict(raw),
        )
    return rows


def load_rt_cache_rows(
    cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    *,
    session_dir: Path = DEFAULT_RT_SESSION_DIR,
    policy: ClientDriftPolicy | None = None,
) -> dict[str, ClientTorrentRow]:
    payload = _read_json(cache_file.expanduser())
    if not isinstance(payload, list):
        return {}
    active_policy = policy or default_policy()
    rows: dict[str, ClientTorrentRow] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        torrent_hash = _norm_hash(raw.get("hash"))
        if not torrent_hash:
            continue
        directory = _norm_path(raw.get("directory") or raw.get("save_path"))
        name = str(raw.get("name") or "").strip()
        meta = load_rt_torrent_meta(session_dir.expanduser(), torrent_hash)
        meta_name = str(meta.info_name if meta else "").strip()
        content_path = directory
        target_qb_save_path = directory
        if meta and meta.is_multi_file:
            if meta_name and Path(directory).name == meta_name:
                target_qb_save_path = str(Path(directory).parent)
            content_path = directory
        elif meta and meta_name:
            content_path = str(Path(directory) / meta_name)
        session_files = resolve_rt_session_files(session_dir.expanduser(), torrent_hash)
        category = str(
            raw.get("category")
            or raw.get("label")
            or raw.get("custom1")
            or ""
        ).strip()
        if not category:
            category = _infer_category_from_path(target_qb_save_path or directory, active_policy.mirror_roots)
        rows[torrent_hash] = ClientTorrentRow(
            client="rt",
            torrent_hash=torrent_hash,
            name=name or meta_name,
            save_path=directory,
            content_path=content_path,
            category=category,
            tags=str(raw.get("tags") or "").strip(),
            state=str(raw.get("state") or "unknown").strip() or "unknown",
            progress=1.0 if _to_int(raw.get("complete")) == 1 or str(raw.get("state")) in HEALTHY_RT_STATES else 0.0,
            size=_to_int(raw.get("size") or raw.get("total_size") or (meta.total_bytes if meta else 0)),
            tracker=str(raw.get("tracker") or "").strip(),
            added_on=_to_int(raw.get("added_on")),
            added_display=str(raw.get("added") or raw.get("added_short") or "").strip(),
            path_exists=_path_exists(content_path),
            torrent_file=str(session_files.torrent_file),
            torrent_file_exists=session_files.torrent_file.exists(),
            target_qb_save_path=target_qb_save_path,
            meta_loaded=meta is not None,
            is_multi_file=meta.is_multi_file if meta else None,
            expected_file_count=int(meta.file_count if meta else 0),
            expected_total_bytes=int(meta.total_bytes if meta else 0),
            raw=dict(raw),
        )
    return rows


def _is_recent(row: ClientTorrentRow, policy: ClientDriftPolicy, now: float) -> bool:
    return bool(policy.recent_seconds > 0 and row.added_on > 0 and now - row.added_on < policy.recent_seconds)


def _classify_rt_only(row: ClientTorrentRow, policy: ClientDriftPolicy, now: float) -> tuple[str, str, list[str], list[str]]:
    reasons: list[str] = ["present_in_rt_missing_in_qb"]
    blockers: list[str] = []
    if _category_in(row.category, policy.ignore_rt_only_categories) or _under_any_policy_prefix(row.save_path, policy.ignore_rt_only_path_prefixes, policy):
        reasons.append("explicit_rt_only_ignore_policy")
        return "ignore_intentional_rt_only", "high", reasons, blockers
    if _category_in(row.category, policy.remove_from_rt_categories) or _under_any_policy_prefix(row.save_path, policy.remove_from_rt_path_prefixes, policy):
        reasons.append("explicit_remove_from_rt_policy")
        return "remove_from_rt", "high", reasons, blockers
    if _is_recent(row, policy, now):
        blockers.append("recent_item_wait_for_peer_client_sync")
    if row.state not in HEALTHY_RT_STATES:
        blockers.append(f"rt_state_not_healthy:{row.state or 'unknown'}")
    if not row.path_exists:
        blockers.append("rt_content_path_missing")
    if not row.torrent_file_exists:
        blockers.append("rt_torrent_file_missing")
    if not row.meta_loaded:
        blockers.append("rt_torrent_meta_missing")
    mirrorable_by_root = _under_any_policy_prefix(row.target_qb_save_path or row.save_path, policy.mirror_roots, policy)
    mirrorable_by_category = _category_in(row.category, policy.mirror_rt_to_qb_categories)
    if mirrorable_by_root:
        reasons.append("under_mirror_root")
    if mirrorable_by_category:
        reasons.append("category_mirror_rt_to_qb_policy")
    if (mirrorable_by_root or mirrorable_by_category) and not blockers:
        custom2_val = row.raw.get("custom2", "")
        if _has_tag(custom2_val, QB_MIRROR_TAG):
            reasons.append("qb_lost_mirrored_item")
            return "re_mirror_rt_to_qb", "high", reasons, blockers
        return "mirror_rt_to_qb", "high", reasons, blockers
    if blockers:
        return "manual_review", "low", reasons, blockers
    blockers.append("no_policy_says_rt_only_should_be_mirrored_or_removed")
    return "manual_review", "medium", reasons, blockers


def _classify_qb_only(row: ClientTorrentRow, policy: ClientDriftPolicy, now: float) -> tuple[str, str, list[str], list[str]]:
    reasons: list[str] = ["present_in_qb_missing_in_rt"]
    blockers: list[str] = []
    if _has_tag(row.tags, RT_MIRROR_TAG):
        reasons.append("orphaned_rt_mirror")
        return "remove_from_qb", "high", reasons, blockers
    if _category_in(row.category, policy.ignore_qb_only_categories) or _under_any_policy_prefix(row.save_path, policy.ignore_qb_only_path_prefixes, policy):
        reasons.append("explicit_qb_only_ignore_policy")
        return "ignore_intentional_qb_only", "high", reasons, blockers
    if _category_in(row.category, policy.remove_from_qb_categories) or _under_any_policy_prefix(row.save_path, policy.remove_from_qb_path_prefixes, policy):
        reasons.append("explicit_remove_from_qb_policy")
        return "remove_from_qb", "high", reasons, blockers
    if _is_recent(row, policy, now):
        blockers.append("recent_item_wait_for_peer_client_sync")
    if row.state not in HEALTHY_QB_STATES:
        blockers.append(f"qb_state_not_healthy:{row.state or 'unknown'}")
    if row.progress < 0.999:
        blockers.append(f"qb_progress_not_complete:{row.progress:.3f}")
    if not row.path_exists:
        blockers.append("qb_content_path_missing")
    mirrorable_by_root = _under_any_policy_prefix(row.save_path or row.content_path, policy.mirror_roots, policy)
    mirrorable_by_category = _category_in(row.category, policy.mirror_qb_to_rt_categories)
    if mirrorable_by_root:
        reasons.append("under_mirror_root")
    if mirrorable_by_category:
        reasons.append("category_mirror_qb_to_rt_policy")
    if (mirrorable_by_root or mirrorable_by_category) and not blockers and policy.mode != "rt-authoritative-mirror":
        return "mirror_qb_to_rt", "medium", reasons, blockers
    if policy.mode == "rt-authoritative-mirror":
        blockers.append("rt_authoritative_mode_does_not_import_from_qb_by_default")
    if blockers:
        return "manual_review", "low", reasons, blockers
    blockers.append("no_policy_says_qb_only_should_be_mirrored_or_removed")
    return "manual_review", "medium", reasons, blockers


@dataclass
class _AnchorScanResult:
    has_arr_anchor: bool | None
    source: str = ""
    anchor_paths: list[str] = field(default_factory=list)
    payload_files_checked: int = 0
    library_files_checked: int = 0
    payload_scan_truncated: bool = False
    library_scan_truncated: bool = False
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_arr_anchor": self.has_arr_anchor,
            "source": self.source,
            "anchor_paths": self.anchor_paths[:20],
            "payload_files_checked": self.payload_files_checked,
            "library_files_checked": self.library_files_checked,
            "payload_scan_truncated": self.payload_scan_truncated,
            "library_scan_truncated": self.library_scan_truncated,
            "blockers": self.blockers,
        }


class _PlacementAnchorScanner:
    def __init__(self, policy: ClientDriftPolicy, *, catalog_path: Path | None = None) -> None:
        self.policy = policy
        self.catalog_path = catalog_path
        self._library_index: dict[tuple[int, int], list[str]] | None = None
        self._library_files_checked = 0
        self._library_scan_truncated = False
        self._library_blockers: list[str] = []

    def scan_paths(self, paths: Iterable[str]) -> _AnchorScanResult:
        raw_paths = tuple(str(path or "").strip() for path in paths if str(path or "").strip())
        path_tuple = _path_variants_many(raw_paths, self.policy)
        catalog_result = self._scan_catalog(path_tuple)
        if catalog_result.has_arr_anchor is not None:
            return catalog_result
        catalog_blockers = [
            blocker
            for blocker in catalog_result.blockers
            if blocker != "catalog_anchor_lookup_not_configured"
        ]
        max_files = max(0, int(self.policy.anchor_scan_max_files))
        if (
            max_files <= 0
            and "catalog_negative_anchor_requires_filesystem_confirmation" in catalog_blockers
        ):
            return _AnchorScanResult(
                has_arr_anchor=None,
                source="catalog",
                payload_files_checked=catalog_result.payload_files_checked,
                blockers=[*catalog_blockers, "arr_anchor_scan_disabled"],
            )

        library_index = self._load_library_index()
        fs_blockers = [*self._library_blockers]
        if max_files <= 0:
            return _AnchorScanResult(
                has_arr_anchor=None,
                source="filesystem",
                library_files_checked=self._library_files_checked,
                library_scan_truncated=self._library_scan_truncated,
                blockers=[*catalog_blockers, *fs_blockers, "arr_anchor_scan_disabled"],
            )
        if not self.policy.arr_library_roots:
            return _AnchorScanResult(
                has_arr_anchor=None,
                source="filesystem",
                library_files_checked=self._library_files_checked,
                library_scan_truncated=self._library_scan_truncated,
                blockers=[*catalog_blockers, *fs_blockers, "arr_library_roots_not_configured"],
            )

        anchor_paths: list[str] = []
        payload_files_checked = 0
        payload_scan_truncated = False
        for payload_file in self._iter_files(path_tuple):
            payload_files_checked += 1
            if payload_files_checked > max_files:
                payload_scan_truncated = True
                break
            try:
                st = payload_file.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_nlink <= 1:
                continue
            for library_path in library_index.get((int(st.st_dev), int(st.st_ino)), []):
                if str(payload_file) != library_path and library_path not in anchor_paths:
                    anchor_paths.append(library_path)

        if anchor_paths:
            return _AnchorScanResult(
                has_arr_anchor=True,
                source="filesystem",
                anchor_paths=anchor_paths,
                payload_files_checked=payload_files_checked,
                library_files_checked=self._library_files_checked,
                payload_scan_truncated=payload_scan_truncated,
                library_scan_truncated=self._library_scan_truncated,
                blockers=fs_blockers,
            )
        if payload_scan_truncated or self._library_scan_truncated:
            blockers = [*catalog_blockers, *fs_blockers, "arr_anchor_scan_incomplete"]
            return _AnchorScanResult(
                has_arr_anchor=None,
                source="filesystem",
                payload_files_checked=payload_files_checked,
                library_files_checked=self._library_files_checked,
                payload_scan_truncated=payload_scan_truncated,
                library_scan_truncated=self._library_scan_truncated,
                blockers=blockers,
            )
        return _AnchorScanResult(
            has_arr_anchor=False,
            source="filesystem",
            payload_files_checked=payload_files_checked,
            library_files_checked=self._library_files_checked,
            blockers=fs_blockers,
        )

    def _scan_catalog(self, paths: Iterable[str]) -> _AnchorScanResult:
        if self.catalog_path is None:
            return _AnchorScanResult(has_arr_anchor=None, source="catalog", blockers=["catalog_anchor_lookup_not_configured"])
        catalog_path = self.catalog_path.expanduser()
        if not catalog_path.exists():
            return _AnchorScanResult(has_arr_anchor=None, source="catalog", blockers=["catalog_not_found"])
        if not self.policy.arr_library_roots:
            return _AnchorScanResult(has_arr_anchor=None, source="catalog", blockers=["arr_library_roots_not_configured"])

        try:
            conn = sqlite3.connect(f"file:{catalog_path.resolve()}?mode=ro", uri=True)
            try:
                tables = self._catalog_files_tables(conn)
                if not tables:
                    return _AnchorScanResult(has_arr_anchor=None, source="catalog", blockers=["catalog_files_tables_missing"])
                anchor_paths: list[str] = []
                payload_files_checked = 0
                blockers: list[str] = []
                for table in tables:
                    if not self._catalog_table_has_column(conn, table, "path") or not self._catalog_table_has_column(conn, table, "inode"):
                        continue
                    identity_column = self._catalog_identity_column(conn, table)
                    table_scoped_identity = self._catalog_table_scopes_inode_identity(table)
                    if identity_column is None and not table_scoped_identity:
                        blockers.append(f"catalog_table_lacks_filesystem_identity:{table}")
                        continue
                    has_status = self._catalog_table_has_column(conn, table, "status")
                    payload_rows = self._catalog_payload_rows(
                        conn,
                        table,
                        paths,
                        has_status=has_status,
                        identity_column=identity_column,
                        table_scoped_identity=table_scoped_identity,
                    )
                    payload_files_checked += len(payload_rows)
                    if not payload_rows:
                        continue
                    identity_groups: dict[str, list[int]] = {}
                    for _path, inode, identity in payload_rows:
                        identity_groups.setdefault(identity, []).append(int(inode))
                    for identity, inode_values_raw in sorted(identity_groups.items()):
                        inode_values = sorted(set(inode_values_raw))
                        for inode_chunk in self._chunks(inode_values, 500):
                            placeholders = ",".join("?" for _ in inode_chunk)
                            status_clause = "status = 'active' AND " if has_status else ""
                            params: list[Any] = []
                            identity_clause = ""
                            if identity_column is not None:
                                identity_clause = f"{identity_column} = ? AND "
                                params.append(identity)
                            rows = conn.execute(
                                f"SELECT path, inode FROM {table} WHERE {status_clause}{identity_clause}inode IN ({placeholders})",
                                [*params, *inode_chunk],
                            ).fetchall()
                            for link_path, _inode in rows:
                                link_text = str(link_path or "")
                                if self._under_library_root(link_text) and link_text not in anchor_paths:
                                    anchor_paths.append(link_text)
                if anchor_paths:
                    return _AnchorScanResult(
                        has_arr_anchor=True,
                        source="catalog",
                        anchor_paths=sorted(anchor_paths),
                        payload_files_checked=payload_files_checked,
                        blockers=blockers,
                    )
                if payload_files_checked > 0:
                    return _AnchorScanResult(
                        has_arr_anchor=None,
                        source="catalog",
                        payload_files_checked=payload_files_checked,
                        blockers=[*blockers, "catalog_negative_anchor_requires_filesystem_confirmation"],
                    )
                if blockers:
                    return _AnchorScanResult(
                        has_arr_anchor=None,
                        source="catalog",
                        blockers=blockers,
                    )
                return _AnchorScanResult(
                    has_arr_anchor=None,
                    source="catalog",
                    blockers=["catalog_payload_paths_missing"],
                )
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return _AnchorScanResult(
                has_arr_anchor=None,
                source="catalog",
                blockers=[f"catalog_error:{exc}"],
            )

    @staticmethod
    def _catalog_table_scopes_inode_identity(table: str) -> bool:
        return str(table or "").startswith("files_")

    @staticmethod
    def _catalog_identity_column(conn: sqlite3.Connection, table: str) -> str | None:
        for column in ("fs_uuid", "device_id"):
            if _PlacementAnchorScanner._catalog_table_has_column(conn, table, column):
                return column
        return None

    @staticmethod
    def _catalog_identity_value(
        *,
        table: str,
        identity_column: str | None,
        table_scoped_identity: bool,
        row_identity: Any,
    ) -> str:
        if identity_column is not None:
            if row_identity is None:
                return ""
            return str(row_identity).strip()
        if table_scoped_identity:
            return f"table:{table}"
        return ""

    @staticmethod
    def _catalog_files_tables(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        out = []
        for (name,) in rows:
            text = str(name or "")
            if text == "files" or text.startswith("files_"):
                out.append(text)
        return out

    @staticmethod
    def _catalog_table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(str(row[1]) == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())

    @staticmethod
    def _catalog_payload_rows(
        conn: sqlite3.Connection,
        table: str,
        paths: Iterable[str],
        *,
        has_status: bool,
        identity_column: str | None,
        table_scoped_identity: bool,
    ) -> list[tuple[str, int, str]]:
        out: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int, str]] = set()
        status_clause = "status = 'active' AND " if has_status else ""
        identity_select = f", {identity_column}" if identity_column is not None else ""
        for raw_path in paths:
            path = str(raw_path or "").rstrip("/")
            if not path:
                continue
            rows = conn.execute(
                f"SELECT path, inode{identity_select} FROM {table} WHERE {status_clause}(path = ? OR path LIKE ?)",
                (path, f"{path}/%"),
            ).fetchall()
            for row in rows:
                file_path, inode, *identity_values = row
                row_identity = identity_values[0] if identity_values else None
                identity = _PlacementAnchorScanner._catalog_identity_value(
                    table=table,
                    identity_column=identity_column,
                    table_scoped_identity=table_scoped_identity,
                    row_identity=row_identity,
                )
                if not identity:
                    continue
                try:
                    key = (str(file_path), int(inode), identity)
                except Exception:
                    continue
                if key not in seen:
                    seen.add(key)
                    out.append(key)
        return out

    def _under_library_root(self, path: str) -> bool:
        return _under_any_policy_prefix(path, self.policy.arr_library_roots, self.policy)

    @staticmethod
    def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
        for index in range(0, len(values), size):
            yield values[index:index + size]

    def _load_library_index(self) -> dict[tuple[int, int], list[str]]:
        if self._library_index is not None:
            return self._library_index
        self._library_index = {}
        max_files = max(0, int(self.policy.anchor_scan_max_files))
        if max_files <= 0:
            return self._library_index
        existing_roots = [Path(root) for root in self.policy.arr_library_roots if root and Path(root).exists()]
        if not existing_roots:
            self._library_blockers.append("arr_library_roots_missing")
            return self._library_index
        for library_file in self._iter_files(str(root) for root in existing_roots):
            self._library_files_checked += 1
            if self._library_files_checked > max_files:
                self._library_scan_truncated = True
                break
            try:
                st = library_file.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                self._library_index.setdefault((int(st.st_dev), int(st.st_ino)), []).append(str(library_file))
        return self._library_index

    @staticmethod
    def _iter_files(paths: Iterable[str]) -> Iterable[Path]:
        seen: set[str] = set()
        seen_inodes: set[tuple[int, int]] = set()
        for raw_path in paths:
            path_text = str(raw_path or "").strip()
            if not path_text or path_text in seen:
                continue
            seen.add(path_text)
            path = Path(path_text)
            if path.is_file():
                try:
                    st = path.stat(follow_symlinks=False)
                    inode_key = (int(st.st_dev), int(st.st_ino))
                except OSError:
                    inode_key = None
                if inode_key is not None:
                    if inode_key in seen_inodes:
                        continue
                    seen_inodes.add(inode_key)
                yield path
                continue
            if not path.is_dir():
                continue
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs.sort()
                for name in sorted(files):
                    file_path = Path(root) / name
                    try:
                        st = file_path.stat(follow_symlinks=False)
                        inode_key = (int(st.st_dev), int(st.st_ino))
                    except OSError:
                        inode_key = None
                    if inode_key is not None:
                        if inode_key in seen_inodes:
                            continue
                        seen_inodes.add(inode_key)
                    yield file_path


def _placement_kind(path: str, policy: ClientDriftPolicy) -> str:
    if _under_any_policy_prefix(path, policy.pool_roots, policy):
        return "pool"
    if _under_any_policy_prefix(path, policy.stash_roots, policy):
        return "stash"
    return "other"


# Seeding subdirs that ARR sets after import (radarr→movies, sonarr→tv, etc.)
_ARR_SEEDING_DIRS: frozenset[str] = frozenset(ARR_CATEGORY_FINAL_MAP.values())


def _is_arr_seeding_path(path: str) -> bool:
    """Return True if path's immediate seeding subdir is an ARR post-import category."""
    if not path:
        return False
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part == "seeding" and i + 1 < len(parts):
            return parts[i + 1] in _ARR_SEEDING_DIRS
    return False


_TRACKER_REGISTRY_SEARCH_PATHS: tuple[str, ...] = (
    os.environ.get("HASHALL_TRACKER_REGISTRY", ""),
    os.environ.get("TRACKER_REGISTRY", ""),
    "/home/michael/dev/tools/traktor/config/tracker-registry.yml",
    "/home/michael/dev/work/glider/glider-docker/tracker-ctl/config/tracker-registry.yml",
    "/mnt/config/docker/tracker-ctl/config/tracker-registry.yml",
)


def _load_tracker_registry() -> dict[str, dict]:
    """
    Load tracker-registry.yml and return {tracker_key: {display_name, prowlarr_name, base_url, url_pattern}}.
    Returns empty dict if registry not found or unreadable.
    """
    for raw_path in _TRACKER_REGISTRY_SEARCH_PATHS:
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.exists():
            continue
        try:
            import yaml  # PyYAML — available as transitive dep; lazy import to avoid hard coupling
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            result: dict[str, dict] = {}
            for key, entry in (raw.get("trackers") or {}).items():
                if not isinstance(entry, dict):
                    continue
                prowlarr = entry.get("prowlarr") or {}
                qbitmanage = entry.get("qbitmanage") or {}
                result[str(key)] = {
                    "display_name": str(entry.get("display_name") or ""),
                    "prowlarr_name": str(prowlarr.get("indexer_name") or ""),
                    "base_url": str(prowlarr.get("base_url") or ""),
                    "url_pattern": str(qbitmanage.get("tracker_url_pattern") or ""),
                }
            return result
        except Exception:
            return {}
    return {}


def _resolve_tracker(tracker_url: str, registry: dict[str, dict]) -> dict[str, str]:
    """
    Resolve a tracker announce URL to registry identity.
    Returns {url, key, display_name, prowlarr_name}.
    Matches against prowlarr.base_url hostname first, then qbitmanage.tracker_url_pattern.
    Falls back to heuristic hostname extraction when registry has no match.
    """
    url_clean = str(tracker_url or "").strip()
    result = {"url": url_clean, "key": "", "display_name": "", "prowlarr_name": ""}
    if not url_clean:
        return result

    if registry:
        url_lower = url_clean.lower()
        for tracker_key, info in registry.items():
            matched = False
            base_url = info.get("base_url", "").lower().rstrip("/")
            if base_url:
                try:
                    from urllib.parse import urlparse as _up
                    base_host = _up(base_url).hostname or ""
                    if base_host and base_host in url_lower:
                        matched = True
                except Exception:
                    pass
            if not matched:
                pattern = info.get("url_pattern", "").lower()
                if pattern and pattern in url_lower:
                    matched = True
            if matched:
                result.update({
                    "key": tracker_key,
                    "display_name": info.get("display_name", ""),
                    "prowlarr_name": info.get("prowlarr_name", ""),
                })
                return result

    # Fallback: heuristic hostname extraction
    try:
        from urllib.parse import urlparse as _up
        host = _up(url_clean).hostname or url_clean.lower()
        parts = host.split(".")
        _SKIP = {"tracker", "announce", "t", "bt", "www", "torrent"}
        while len(parts) > 1 and parts[0] in _SKIP:
            parts = parts[1:]
        if len(parts) > 1:
            parts = parts[:-1]
        result["key"] = parts[0].lower() if parts else host.lower()
    except Exception:
        pass
    return result


def _rt_repoint_target_for_content_path(content_path: str, rt_row: ClientTorrentRow) -> str:
    if not content_path:
        return ""
    p = Path(content_path)
    if rt_row.is_multi_file is False:
        return str(p.parent)
    if rt_row.is_multi_file and rt_row.name:
        if p.name == rt_row.name:
            return str(p.parent)
        # content_path is a file inside the torrent folder.
        # Find the first (outermost) path component matching the torrent name and
        # return its parent — that is where RT should set its save directory.
        parts = list(p.parts)
        for i, part in enumerate(parts):
            if part == rt_row.name:
                return str(Path(*parts[:i])) if i > 0 else str(Path(parts[0]))
    return normalize_rt_target_directory(content_path, None)


def _classify_common_path_drift(
    qb_row: ClientTorrentRow,
    rt_row: ClientTorrentRow,
    policy: ClientDriftPolicy,
    anchor_scanner: _PlacementAnchorScanner,
) -> tuple[str, str, list[str], list[str], dict[str, Any]]:
    reasons = ["present_in_both_clients", "same_hash_path_drift", "rt_qb_path_not_aligned"]
    blockers: list[str] = []
    if qb_row.state not in HEALTHY_QB_STATES:
        blockers.append(f"qb_state_not_healthy:{qb_row.state or 'unknown'}")
    if qb_row.progress < 0.999:
        blockers.append(f"qb_progress_not_complete:{qb_row.progress:.3f}")
    if rt_row.state not in HEALTHY_RT_STATES:
        blockers.append(f"rt_state_not_healthy:{rt_row.state or 'unknown'}")
    if not qb_row.path_exists:
        blockers.append("qb_content_path_missing")
    if not rt_row.path_exists:
        blockers.append("rt_content_path_missing")

    anchor = anchor_scanner.scan_paths(
        path for path in (qb_row.content_path, rt_row.content_path) if path
    )
    qb_has_nohl_tag = _has_tag(qb_row.tags, NO_HARDLINK_TAG)
    if qb_has_nohl_tag:
        reasons.append("qb_nohl_tag_present_advisory")
    desired_placement = ""
    if anchor.has_arr_anchor is True:
        desired_placement = "stash"
        reasons.append("arr_library_hardlink_anchor_present")
        blockers.extend(anchor.blockers)
    elif anchor.has_arr_anchor is False:
        desired_placement = "pool"
        reasons.append("no_arr_library_hardlink_anchor_found")
        blockers.extend(anchor.blockers)
    else:
        # Anchor scan inconclusive — infer stash placement from ARR seeding dir if unambiguous.
        # Only propagate anchor blockers when we cannot resolve placement by other means.
        rt_in_arr_dir = _is_arr_seeding_path(rt_row.content_path or rt_row.save_path)
        qb_in_arr_dir = _is_arr_seeding_path(qb_row.content_path or qb_row.save_path)
        if rt_in_arr_dir != qb_in_arr_dir:
            desired_placement = "stash"
            reasons.append("arr_seeding_dir_implies_stash_placement")
        else:
            blockers.extend(anchor.blockers)
            blockers.append("hardlink_anchor_evidence_required_for_placement")

    qb_kind = _placement_kind(qb_row.save_path or qb_row.content_path, policy)
    rt_kind = _placement_kind(rt_row.target_qb_save_path or rt_row.save_path or rt_row.content_path, policy)
    placement = {
        "desired": desired_placement,
        "qb_kind": qb_kind,
        "rt_kind": rt_kind,
        "qb_save_path": qb_row.save_path,
        "qb_content_path": qb_row.content_path,
        "rt_save_path": rt_row.save_path,
        "rt_target_qb_save_path": rt_row.target_qb_save_path,
        "rt_content_path": rt_row.content_path,
        "qb_has_nohl_tag": qb_has_nohl_tag,
        "qb_tracker_url": "",
        "qb_tracker_key": "",
        "qb_tracker_display": "",
        "qb_prowlarr_name": "",
        "rt_tracker_url": "",
        "rt_tracker_key": "",
        "rt_tracker_display": "",
        "rt_prowlarr_name": "",
        "proposed_qb_save_path": "",
        "proposed_rt_directory": "",
        "proposed_rt_content_path": "",
        "proposed_rt_repoint_target": "",
        "proposed_source_client": "",
        "anchor_scan": anchor.to_dict(),
    }

    action = "manual_review"
    if desired_placement:
        qb_matches = qb_kind == desired_placement
        rt_matches = rt_kind == desired_placement
        if qb_matches and not rt_matches:
            action = "repoint_rt_to_qb_path"
            reasons.append(f"qb_on_required_{desired_placement}_placement")
            placement["proposed_source_client"] = "qb"
            placement["proposed_rt_directory"] = qb_row.content_path
            placement["proposed_rt_content_path"] = qb_row.content_path
            placement["proposed_rt_repoint_target"] = _rt_repoint_target_for_content_path(qb_row.content_path, rt_row)
            if not qb_row.path_exists:
                blockers.append("selected_qb_target_missing")
        elif rt_matches and not qb_matches:
            action = "repoint_qb_to_rt_path"
            reasons.append(f"rt_on_required_{desired_placement}_placement")
            placement["proposed_source_client"] = "rt"
            placement["proposed_qb_save_path"] = rt_row.target_qb_save_path or rt_row.save_path
            if not rt_row.path_exists:
                blockers.append("selected_rt_target_missing")
        elif qb_matches and rt_matches:
            # Both sides are on the correct storage class but at different paths.
            # Use inode comparison against the ARR anchor to pick canonical side.
            anchor_inodes: set[int] = set()
            for ap in anchor.anchor_paths:
                try:
                    anchor_inodes.add(os.stat(ap).st_ino)
                except OSError:
                    pass
            qb_inode: int | None = None
            rt_inode: int | None = None
            if qb_row.content_path:
                try:
                    qb_inode = os.stat(qb_row.content_path).st_ino
                except OSError:
                    pass
            if rt_row.content_path:
                try:
                    rt_inode = os.stat(rt_row.content_path).st_ino
                except OSError:
                    pass
            rt_is_anchor = bool(anchor_inodes and rt_inode and rt_inode in anchor_inodes)
            qb_is_anchor = bool(anchor_inodes and qb_inode and qb_inode in anchor_inodes)
            if rt_is_anchor and not qb_is_anchor:
                action = "repoint_qb_to_rt_path"
                reasons.append(f"rt_on_required_{desired_placement}_placement")
                reasons.append("rt_inode_matches_arr_anchor")
                placement["proposed_source_client"] = "rt"
                placement["proposed_qb_save_path"] = rt_row.target_qb_save_path or rt_row.save_path
                if not rt_row.path_exists:
                    blockers.append("selected_rt_target_missing")
            elif qb_is_anchor and not rt_is_anchor:
                action = "repoint_rt_to_qb_path"
                reasons.append(f"qb_on_required_{desired_placement}_placement")
                reasons.append("qb_inode_matches_arr_anchor")
                placement["proposed_source_client"] = "qb"
                placement["proposed_rt_directory"] = qb_row.content_path
                placement["proposed_rt_content_path"] = qb_row.content_path
                placement["proposed_rt_repoint_target"] = _rt_repoint_target_for_content_path(qb_row.content_path, rt_row)
                if not qb_row.path_exists:
                    blockers.append("selected_qb_target_missing")
            else:
                # Both share the same inode as the ARR anchor (same physical file,
                # different directory names). Use ARR post-import seeding dir as
                # the tiebreaker: the path whose immediate seeding subdir is an ARR
                # category (movies/, tv/, music/, ebooks/, audiobooks/) is canonical —
                # that's where ATM placed it after import.
                rt_in_arr_dir = _is_arr_seeding_path(rt_row.content_path or rt_row.save_path)
                qb_in_arr_dir = _is_arr_seeding_path(qb_row.content_path or qb_row.save_path)
                if rt_in_arr_dir and not qb_in_arr_dir:
                    action = "repoint_qb_to_rt_path"
                    reasons.append(f"rt_on_required_{desired_placement}_placement")
                    reasons.append("rt_path_in_arr_seeding_dir")
                    placement["proposed_source_client"] = "rt"
                    placement["proposed_qb_save_path"] = rt_row.target_qb_save_path or rt_row.save_path
                    if not rt_row.path_exists:
                        blockers.append("selected_rt_target_missing")
                elif qb_in_arr_dir and not rt_in_arr_dir:
                    action = "repoint_rt_to_qb_path"
                    reasons.append(f"qb_on_required_{desired_placement}_placement")
                    reasons.append("qb_path_in_arr_seeding_dir")
                    placement["proposed_source_client"] = "qb"
                    placement["proposed_rt_directory"] = qb_row.content_path
                    placement["proposed_rt_content_path"] = qb_row.content_path
                    placement["proposed_rt_repoint_target"] = _rt_repoint_target_for_content_path(qb_row.content_path, rt_row)
                    if not qb_row.path_exists:
                        blockers.append("selected_qb_target_missing")
                else:
                    blockers.append("both_clients_on_required_placement_but_paths_differ")
        else:
            blockers.append(f"no_client_on_required_{desired_placement}_placement")

    if blockers:
        return "manual_review", "low", reasons, blockers, placement
    if action != "manual_review":
        return action, "high", reasons, blockers, placement
    blockers.append("unable_to_select_repoint_source")
    return "manual_review", "medium", reasons, blockers, placement


def build_client_drift_report(
    *,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    rt_session_dir: Path = DEFAULT_RT_SESSION_DIR,
    policy: ClientDriftPolicy | None = None,
    hash_filters: Iterable[str] = (),
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    active_policy = policy or default_policy()
    qb_rows = load_qb_cache_rows(qb_cache_file)
    rt_rows = load_rt_cache_rows(rt_cache_file, session_dir=rt_session_dir, policy=active_policy)
    qb_hashes = set(qb_rows)
    rt_hashes = set(rt_rows)
    common = qb_hashes & rt_hashes
    hash_prefixes = tuple(_norm_hash(item) for item in hash_filters if _norm_hash(item))

    def _selected_hash(torrent_hash: str) -> bool:
        return not hash_prefixes or any(torrent_hash.startswith(prefix) for prefix in hash_prefixes)

    now = time.time()
    drift_rows: list[dict[str, Any]] = []
    anchor_scanner = _PlacementAnchorScanner(active_policy, catalog_path=catalog_path)
    tracker_registry = _load_tracker_registry()

    for torrent_hash in sorted(common):
        if not _selected_hash(torrent_hash):
            continue
        qb_row = qb_rows[torrent_hash]
        rt_row = rt_rows[torrent_hash]
        aligned = _rt_path_aligned_with_policy(
            rt_row.save_path,
            qb_save_path=qb_row.save_path,
            qb_content_path=qb_row.content_path,
            policy=active_policy,
        )
        if aligned:
            continue
        action, confidence, reasons, blockers, placement = _classify_common_path_drift(
            qb_row,
            rt_row,
            active_policy,
            anchor_scanner,
        )
        qb_ti = _resolve_tracker(qb_row.tracker, tracker_registry)
        rt_ti = _resolve_tracker(rt_row.tracker, tracker_registry)
        placement.update({
            "qb_tracker_url": qb_ti["url"],
            "qb_tracker_key": qb_ti["key"],
            "qb_tracker_display": qb_ti["display_name"],
            "qb_prowlarr_name": qb_ti["prowlarr_name"],
            "rt_tracker_url": rt_ti["url"],
            "rt_tracker_key": rt_ti["key"],
            "rt_tracker_display": rt_ti["display_name"],
            "rt_prowlarr_name": rt_ti["prowlarr_name"],
        })
        drift_rows.append(
            {
                "hash": torrent_hash,
                "side": "path_drift",
                "action": action,
                "confidence": confidence,
                "reasons": reasons,
                "blockers": blockers,
                "name": qb_row.name or rt_row.name,
                "placement": placement,
                "rt": rt_row.to_dict(),
                "qb": qb_row.to_dict(),
            }
        )

    for torrent_hash in sorted(rt_hashes - qb_hashes):
        if not _selected_hash(torrent_hash):
            continue
        row = rt_rows[torrent_hash]
        action, confidence, reasons, blockers = _classify_rt_only(row, active_policy, now)
        drift_rows.append(
            {
                "hash": torrent_hash,
                "side": "rt_only",
                "action": action,
                "confidence": confidence,
                "reasons": reasons,
                "blockers": blockers,
                "name": row.name,
                "rt": row.to_dict(),
                "qb": None,
            }
        )

    for torrent_hash in sorted(qb_hashes - rt_hashes):
        if not _selected_hash(torrent_hash):
            continue
        row = qb_rows[torrent_hash]
        action, confidence, reasons, blockers = _classify_qb_only(row, active_policy, now)
        drift_rows.append(
            {
                "hash": torrent_hash,
                "side": "qb_only",
                "action": action,
                "confidence": confidence,
                "reasons": reasons,
                "blockers": blockers,
                "name": row.name,
                "rt": None,
                "qb": row.to_dict(),
            }
        )

    action_counts = Counter(str(row["action"]) for row in drift_rows)
    side_counts = Counter(str(row["side"]) for row in drift_rows)
    summary = {
        "qb_cache_file": str(qb_cache_file.expanduser()),
        "rt_cache_file": str(rt_cache_file.expanduser()),
        "rt_session_dir": str(rt_session_dir.expanduser()),
        "policy_mode": active_policy.mode,
        "mirror_roots": list(active_policy.mirror_roots),
        "pool_roots": list(active_policy.pool_roots),
        "stash_roots": list(active_policy.stash_roots),
        "arr_library_roots": list(active_policy.arr_library_roots),
        "anchor_scan_max_files": active_policy.anchor_scan_max_files,
        "hash_filters": list(hash_prefixes),
        "catalog_path": str(catalog_path.expanduser()) if catalog_path is not None else "",
        "qb_total": len(qb_rows),
        "rt_total": len(rt_rows),
        "common": len(common),
        "qb_only": len(qb_hashes - rt_hashes),
        "rt_only": len(rt_hashes - qb_hashes),
        "path_drift": side_counts.get("path_drift", 0),
        "drift_total": len(drift_rows),
        "side_counts": dict(side_counts),
        "action_counts": dict(action_counts),
    }
    return {"summary": summary, "rows": drift_rows}


def _catalog_context_for_hashes(catalog_path: Path | None, torrent_hashes: Iterable[str]) -> dict[str, dict[str, Any]]:
    if catalog_path is None:
        return {}
    path = Path(catalog_path).expanduser()
    if not path.exists():
        return {}
    wanted = sorted({_norm_hash(value) for value in torrent_hashes if _norm_hash(value)})
    if not wanted:
        return {}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        payload_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(payloads)").fetchall()
        }
        torrent_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(torrent_instances)").fetchall()
        }
        payload_hash_expr = "p.payload_hash" if "payload_hash" in payload_columns else "''"
        payload_status_expr = "p.status" if "status" in payload_columns else "''"
        payload_file_count_expr = "p.file_count" if "file_count" in payload_columns else "0"
        payload_total_bytes_expr = "p.total_bytes" if "total_bytes" in payload_columns else "0"
        payload_device_expr = "p.device_id" if "device_id" in payload_columns else "0"
        ti_save_path_expr = "ti.save_path" if "save_path" in torrent_columns else "''"
        placeholders = ",".join("?" for _ in wanted)
        rows = conn.execute(
            f"""
            SELECT lower(ti.torrent_hash) AS torrent_hash,
                   ti.payload_id,
                   {ti_save_path_expr} AS torrent_save_path,
                   {payload_hash_expr} AS payload_hash,
                   p.root_path,
                   {payload_status_expr} AS payload_status,
                   {payload_file_count_expr} AS file_count,
                   {payload_total_bytes_expr} AS total_bytes,
                   {payload_device_expr} AS device_id
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) IN ({placeholders})
            ORDER BY ti.torrent_hash
            """,
            wanted,
        ).fetchall()
        context: dict[str, dict[str, Any]] = {}
        by_payload_hash: dict[str, list[sqlite3.Row]] = {}
        payload_ids = sorted({int(row["payload_id"] or 0) for row in rows if row["payload_id"]})
        payload_hashes = sorted({str(row["payload_hash"] or "") for row in rows if row["payload_hash"]})
        if payload_hashes and "payload_hash" in payload_columns:
            hash_placeholders = ",".join("?" for _ in payload_hashes)
            family_rows = conn.execute(
                f"""
                SELECT p.payload_id, p.payload_hash, p.root_path,
                       {payload_status_expr} AS payload_status,
                       {payload_file_count_expr} AS file_count,
                       {payload_total_bytes_expr} AS total_bytes,
                       COUNT(ti.torrent_hash) AS torrent_count
                FROM payloads p
                LEFT JOIN torrent_instances ti ON ti.payload_id = p.payload_id
                WHERE p.payload_hash IN ({hash_placeholders})
                GROUP BY p.payload_id
                ORDER BY p.payload_hash, p.payload_id
                """,
                payload_hashes,
            ).fetchall()
            for row in family_rows:
                by_payload_hash.setdefault(str(row["payload_hash"] or ""), []).append(row)
        torrent_counts: dict[int, int] = {}
        if payload_ids:
            id_placeholders = ",".join("?" for _ in payload_ids)
            count_rows = conn.execute(
                f"""
                SELECT payload_id, COUNT(*) AS torrent_count
                FROM torrent_instances
                WHERE payload_id IN ({id_placeholders})
                GROUP BY payload_id
                """,
                payload_ids,
            ).fetchall()
            torrent_counts = {int(row["payload_id"] or 0): int(row["torrent_count"] or 0) for row in count_rows}
        for row in rows:
            payload_hash = str(row["payload_hash"] or "")
            sibling_payloads = [
                {
                    "payload_id": int(sib["payload_id"] or 0),
                    "payload_hash": str(sib["payload_hash"] or ""),
                    "root_path": str(sib["root_path"] or ""),
                    "status": str(sib["payload_status"] or ""),
                    "file_count": int(sib["file_count"] or 0),
                    "total_bytes": int(sib["total_bytes"] or 0),
                    "torrent_count": int(sib["torrent_count"] or 0),
                }
                for sib in by_payload_hash.get(payload_hash, [])
            ]
            payload_id = int(row["payload_id"] or 0)
            context[str(row["torrent_hash"])] = {
                "payload_id": payload_id,
                "payload_hash": payload_hash,
                "root_path": str(row["root_path"] or ""),
                "save_path": str(row["torrent_save_path"] or ""),
                "status": str(row["payload_status"] or ""),
                "file_count": int(row["file_count"] or 0),
                "total_bytes": int(row["total_bytes"] or 0),
                "device_id": int(row["device_id"] or 0),
                "payload_torrent_count": int(torrent_counts.get(payload_id, 0)),
                "sibling_payloads": sibling_payloads,
                "sibling_payload_count": len([sib for sib in sibling_payloads if int(sib["payload_id"]) != payload_id]),
            }
        return context
    finally:
        conn.close()


def _arr_status_from_anchor(anchor: dict[str, Any]) -> str:
    value = anchor.get("has_arr_anchor")
    if value is True:
        return "linked_to_arr"
    if value is False:
        return "not_linked_to_arr"
    return "unknown"


def _difficulty_for_path_drift(row: dict[str, Any], catalog: dict[str, Any]) -> tuple[str, list[str]]:
    placement = row.get("placement") or {}
    blockers = list(row.get("blockers") or [])
    reasons: list[str] = []
    action = str(row.get("action") or "")
    desired = str(placement.get("desired") or "")
    qb_kind = str(placement.get("qb_kind") or "")
    rt_kind = str(placement.get("rt_kind") or "")
    file_count = int((row.get("rt") or {}).get("expected_file_count") or catalog.get("file_count") or 0)
    payload_torrent_count = int(catalog.get("payload_torrent_count") or 0)
    sibling_payload_count = int(catalog.get("sibling_payload_count") or 0)

    if action in {"repoint_rt_to_qb_path", "repoint_qb_to_rt_path"}:
        reasons.append(f"tool_selected:{action}")
        level = "easy"
    elif desired and qb_kind == desired and rt_kind == desired:
        reasons.append("both_clients_on_desired_root_class")
        level = "easy"
    elif desired and (qb_kind == desired or rt_kind == desired):
        reasons.append("one_client_on_desired_root_class")
        level = "medium"
    elif desired:
        reasons.append("no_client_on_desired_root_class")
        level = "hard"
    else:
        reasons.append("placement_unknown")
        level = "hard"

    if "both_clients_on_required_placement_but_paths_differ" in blockers:
        reasons.append("same_root_class_path_choice_needed")
    if "no_client_on_required_pool_placement" in blockers or "no_client_on_required_stash_placement" in blockers:
        reasons.append("needs_rehome_or_missing_target_discovery")
        level = "hard"
    if payload_torrent_count > 1:
        reasons.append(f"n_to_1_payload:{payload_torrent_count}_hashes")
        level = "hard"
    if sibling_payload_count > 0:
        reasons.append(f"sibling_payloads:{sibling_payload_count}")
        if level == "easy":
            level = "medium"
    if file_count > 1 and level == "easy":
        reasons.append(f"multi_file:{file_count}")
        level = "medium"
    if placement.get("qb_has_nohl_tag"):
        reasons.append("qb_nohl_advisory")
    if "rehome_verify_pending" in str((row.get("qb") or {}).get("tags") or "") and level == "easy":
        reasons.append("rehome_verify_pending")
        level = "medium"
    return level, reasons


def build_path_drift_rank_report(
    *,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    rt_session_dir: Path = DEFAULT_RT_SESSION_DIR,
    policy: ClientDriftPolicy | None = None,
    hash_filters: Iterable[str] = (),
    catalog_path: Path | None = DEFAULT_CATALOG_PATH,
) -> dict[str, Any]:
    active_policy = policy or default_policy()
    report = build_client_drift_report(
        qb_cache_file=qb_cache_file,
        rt_cache_file=rt_cache_file,
        rt_session_dir=rt_session_dir,
        policy=active_policy,
        hash_filters=hash_filters,
        catalog_path=catalog_path,
    )
    rows = [row for row in report.get("rows") or [] if row.get("side") == "path_drift"]
    catalog_by_hash = _catalog_context_for_hashes(catalog_path, (row.get("hash") for row in rows))
    items: list[dict[str, Any]] = []
    for row in rows:
        torrent_hash = str(row.get("hash") or "").strip().lower()
        placement = row.get("placement") or {}
        anchor = placement.get("anchor_scan") or {}
        catalog = catalog_by_hash.get(torrent_hash, {})
        difficulty, difficulty_reasons = _difficulty_for_path_drift(row, catalog)
        items.append(
            {
                "hash": torrent_hash,
                "name": row.get("name") or "",
                "difficulty": difficulty,
                "difficulty_reasons": difficulty_reasons,
                "action": row.get("action") or "",
                "desired_root": placement.get("desired") or "",
                "arr_status": _arr_status_from_anchor(anchor),
                "arr_anchor_source": anchor.get("source") or "",
                "arr_anchor_paths": anchor.get("anchor_paths") or [],
                "qb_nohl": bool(placement.get("qb_has_nohl_tag")),
                "qb_root_kind": placement.get("qb_kind") or "",
                "rt_root_kind": placement.get("rt_kind") or "",
                "qb_save_path": placement.get("qb_save_path") or "",
                "qb_content_path": placement.get("qb_content_path") or "",
                "rt_save_path": placement.get("rt_save_path") or "",
                "rt_target_qb_save_path": placement.get("rt_target_qb_save_path") or "",
                "rt_content_path": placement.get("rt_content_path") or "",
                "file_count": int((row.get("rt") or {}).get("expected_file_count") or catalog.get("file_count") or 0),
                "blockers": row.get("blockers") or [],
                "tags": (row.get("qb") or {}).get("tags") or "",
                "qb_tracker_url": placement.get("qb_tracker_url") or "",
                "qb_tracker_key": placement.get("qb_tracker_key") or "",
                "qb_tracker_display": placement.get("qb_tracker_display") or "",
                "qb_prowlarr_name": placement.get("qb_prowlarr_name") or "",
                "rt_tracker_url": placement.get("rt_tracker_url") or "",
                "rt_tracker_key": placement.get("rt_tracker_key") or "",
                "rt_tracker_display": placement.get("rt_tracker_display") or "",
                "rt_prowlarr_name": placement.get("rt_prowlarr_name") or "",
                "catalog": catalog,
            }
        )

    order = {"easy": 0, "medium": 1, "hard": 2}
    items.sort(
        key=lambda item: (
            order.get(str(item["difficulty"]), 99),
            int(item.get("file_count") or 0),
            str(item.get("name") or "").lower(),
        )
    )
    groups = {
        level: [item for item in items if item["difficulty"] == level]
        for level in ("easy", "medium", "hard")
    }
    return {
        "summary": {
            "path_drift": len(items),
            "easy": len(groups["easy"]),
            "medium": len(groups["medium"]),
            "hard": len(groups["hard"]),
            "anchor_scan_max_files": active_policy.anchor_scan_max_files,
            "catalog_path": str(catalog_path.expanduser()) if catalog_path is not None else "",
        },
        "groups": groups,
        "items": items,
        "source_summary": report.get("summary") or {},
    }


def format_path_drift_rank_report(report: dict[str, Any], *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(report, indent=2)

    import sys
    from rich.console import Console
    from rich.text import Text
    from rich.rule import Rule
    from io import StringIO

    use_color = sys.stdout.isatty()
    buf = StringIO()
    console = Console(file=buf, highlight=False, markup=False, force_terminal=use_color, width=220)

    # Color palette
    LEVEL_STYLE = {"easy": "bold green", "medium": "bold yellow", "hard": "bold red"}
    ACTION_STYLE = {
        "repoint_qb_to_rt_path": "green",
        "repoint_rt_to_qb_path": "cyan",
        "mirror_rt_to_qb": "cyan",
        "manual_review": "yellow",
    }
    ARR_STYLE = {"linked_to_arr": "green", "not_linked_to_arr": "dim", None: "dim"}

    summary = report.get("summary") or {}
    n_easy = summary.get("easy", 0)
    n_med = summary.get("medium", 0)
    n_hard = summary.get("hard", 0)
    n_total = summary.get("path_drift", 0)

    console.print(Rule("Path Drift Repair Ranking", style="bold"))
    console.print(
        Text.assemble(
            ("  total=", "dim"), (str(n_total), "bold"),
            ("  easy=", "dim"), (str(n_easy), "bold green"),
            ("  medium=", "dim"), (str(n_med), "bold yellow"),
            ("  hard=", "dim"), (str(n_hard), "bold red"),
        )
    )
    console.print()

    for level in ("easy", "medium", "hard"):
        items = (report.get("groups") or {}).get(level) or []
        level_style = LEVEL_STYLE[level]
        console.print(Text(f"{level.upper()}: {len(items)}", style=level_style))
        console.print()

        for item in items:
            catalog = item.get("catalog") or {}
            sibling_payloads = catalog.get("sibling_payloads") or []
            sibling_roots = [
                str(sib.get("root_path") or "")
                for sib in sibling_payloads
                if int(sib.get("payload_id") or 0) != int(catalog.get("payload_id") or 0)
            ]
            h = str(item.get("hash") or "")[:16]
            name = str(item.get("name") or "")
            action = str(item.get("action") or "manual_review")
            blockers = item.get("blockers") or []
            arr_status = item.get("arr_status")
            nohl = item.get("qb_nohl")
            desired = item.get("desired_root") or "-"
            qb_path = item.get("qb_save_path") or "-"
            rt_path = item.get("rt_target_qb_save_path") or item.get("rt_save_path") or "-"
            file_count = item.get("file_count") or 0
            qb_tracker_key = item.get("qb_tracker_key") or ""
            qb_prowlarr = item.get("qb_prowlarr_name") or item.get("qb_tracker_display") or ""
            rt_tracker_key = item.get("rt_tracker_key") or ""
            rt_prowlarr = item.get("rt_prowlarr_name") or item.get("rt_tracker_display") or ""

            # ── Title line
            console.print(Text.assemble(
                ("  ", ""),
                (h, "dim"),
                ("  ", ""),
                (name, "bold"),
            ))

            # ── Action / status line
            action_label = action.replace("_", " ")
            action_s = ACTION_STYLE.get(action, "yellow")
            arr_s = ARR_STYLE.get(arr_status, "dim")
            nohl_text = Text.assemble(("~noHL", "yellow bold")) if nohl else Text("", style="")
            console.print(Text.assemble(
                ("    action=", "dim"),
                (action_label, action_s),
                ("  desired=", "dim"), (desired, ""),
                ("  arr=", "dim"), (str(arr_status or "-"), arr_s),
                ("  files=", "dim"), (str(file_count), ""),
                ("  ", ""), nohl_text,
            ))

            # ── Tracker: key + Prowlarr name
            if qb_tracker_key or rt_tracker_key:
                def _tracker_cell(key: str, prowlarr: str) -> list[tuple[str, str]]:
                    if not key:
                        return []
                    parts: list[tuple[str, str]] = [(key, "magenta")]
                    if prowlarr and prowlarr.lower() != key.lower():
                        parts += [(" (", "dim"), (prowlarr, "dim magenta"), (")", "dim")]
                    return parts

                tracker_parts: list[tuple[str, str]] = [("    tracker  ", "dim bold")]
                qb_cell = _tracker_cell(qb_tracker_key, qb_prowlarr)
                rt_cell = _tracker_cell(rt_tracker_key, rt_prowlarr)
                if qb_cell:
                    tracker_parts += [("qb=", "dim")] + qb_cell
                if rt_cell:
                    if qb_cell:
                        tracker_parts.append(("  ", ""))
                    tracker_parts += [("rt=", "dim")] + rt_cell
                console.print(Text.assemble(*tracker_parts))

            # ── Paths
            console.print(Text.assemble(
                ("    qb  ", "dim bold"), (qb_path, "cyan"),
            ))
            console.print(Text.assemble(
                ("    rt  ", "dim bold"), (rt_path, "cyan"),
            ))

            # ── Sibling payload roots
            if sibling_roots:
                console.print(Text.assemble(
                    ("    siblings=", "dim"), (str(len(sibling_roots)), "yellow"),
                ))
                for root in sibling_roots[:3]:
                    console.print(Text("      • " + root, style="dim"))

            # ── Blockers (red, prominent)
            if blockers:
                for b in blockers:
                    console.print(Text("    ✖ " + b, style="bold red"))
            else:
                difficulty_reasons = item.get("difficulty_reasons") or []
                auto_reasons = [r for r in difficulty_reasons if r.startswith("tool_selected")]
                if auto_reasons:
                    console.print(Text("    ✔ " + auto_reasons[0], style="green"))

            console.print()

        if not items:
            console.print(Text("  (none)", style="dim"))
            console.print()

    return buf.getvalue().rstrip()
