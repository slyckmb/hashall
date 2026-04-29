from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import json
import time
from typing import Any, Iterable

from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE
from hashall.rt_cache import DEFAULT_RT_SHARED_CACHE_FILE
from hashall.rtorrent import DEFAULT_RT_SESSION_DIR, load_rt_torrent_meta, resolve_rt_session_files


HEALTHY_QB_STATES = {"uploading", "stalledUP", "stoppedUP", "pausedUP"}
HEALTHY_RT_STATES = {"uploading", "stalledUP", "stoppedUP"}

DEFAULT_MIRROR_ROOTS = (
    "/data/media/torrents/seeding",
    "/pool/media/torrents/seeding",
    "/stash/media/torrents/seeding",
)


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
    if _category_in(row.category, policy.ignore_rt_only_categories) or _under_any_prefix(row.save_path, policy.ignore_rt_only_path_prefixes):
        reasons.append("explicit_rt_only_ignore_policy")
        return "ignore_intentional_rt_only", "high", reasons, blockers
    if _category_in(row.category, policy.remove_from_rt_categories) or _under_any_prefix(row.save_path, policy.remove_from_rt_path_prefixes):
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
    mirrorable_by_root = _under_any_prefix(row.target_qb_save_path or row.save_path, policy.mirror_roots)
    mirrorable_by_category = _category_in(row.category, policy.mirror_rt_to_qb_categories)
    if mirrorable_by_root:
        reasons.append("under_mirror_root")
    if mirrorable_by_category:
        reasons.append("category_mirror_rt_to_qb_policy")
    if (mirrorable_by_root or mirrorable_by_category) and not blockers:
        return "mirror_rt_to_qb", "high", reasons, blockers
    if blockers:
        return "manual_review", "low", reasons, blockers
    blockers.append("no_policy_says_rt_only_should_be_mirrored_or_removed")
    return "manual_review", "medium", reasons, blockers


def _classify_qb_only(row: ClientTorrentRow, policy: ClientDriftPolicy, now: float) -> tuple[str, str, list[str], list[str]]:
    reasons: list[str] = ["present_in_qb_missing_in_rt"]
    blockers: list[str] = []
    if _category_in(row.category, policy.ignore_qb_only_categories) or _under_any_prefix(row.save_path, policy.ignore_qb_only_path_prefixes):
        reasons.append("explicit_qb_only_ignore_policy")
        return "ignore_intentional_qb_only", "high", reasons, blockers
    if _category_in(row.category, policy.remove_from_qb_categories) or _under_any_prefix(row.save_path, policy.remove_from_qb_path_prefixes):
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
    mirrorable_by_root = _under_any_prefix(row.save_path or row.content_path, policy.mirror_roots)
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


def build_client_drift_report(
    *,
    qb_cache_file: Path = DEFAULT_QB_CACHE_FILE,
    rt_cache_file: Path = DEFAULT_RT_SHARED_CACHE_FILE,
    rt_session_dir: Path = DEFAULT_RT_SESSION_DIR,
    policy: ClientDriftPolicy | None = None,
) -> dict[str, Any]:
    active_policy = policy or default_policy()
    qb_rows = load_qb_cache_rows(qb_cache_file)
    rt_rows = load_rt_cache_rows(rt_cache_file, session_dir=rt_session_dir, policy=active_policy)
    qb_hashes = set(qb_rows)
    rt_hashes = set(rt_rows)
    common = qb_hashes & rt_hashes
    now = time.time()
    drift_rows: list[dict[str, Any]] = []

    for torrent_hash in sorted(rt_hashes - qb_hashes):
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
        "qb_total": len(qb_rows),
        "rt_total": len(rt_rows),
        "common": len(common),
        "qb_only": len(qb_hashes - rt_hashes),
        "rt_only": len(rt_hashes - qb_hashes),
        "drift_total": len(drift_rows),
        "side_counts": dict(side_counts),
        "action_counts": dict(action_counts),
    }
    return {"summary": summary, "rows": drift_rows}
