"""Helpers for restarting noHL payload-group rehome workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

DEFAULT_NOHL_TAG = "~noHL"
DEFAULT_STASH_PREFIXES = ("/stash/media", "/data/media")
DEFAULT_POOL_SEEDS_ROOT = "/pool/data/seeds"


def _norm(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return text.rstrip("/")


def split_tags(raw: str) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part and part.strip()}


def path_is_under(path: str, root: str) -> bool:
    p = _norm(path)
    r = _norm(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r + "/")


def is_stash_alias_path(path: str, stash_prefixes: Sequence[str] = DEFAULT_STASH_PREFIXES) -> bool:
    return any(path_is_under(path, prefix) for prefix in stash_prefixes)


def is_pool_seeds_path(path: str, pool_seeds_root: str = DEFAULT_POOL_SEEDS_ROOT) -> bool:
    return path_is_under(path, pool_seeds_root)


@dataclass(frozen=True)
class NoHLCandidate:
    torrent_hash: str
    save_path: str
    tags: str


def filter_nohl_candidates(
    torrents: Iterable[Mapping[str, object]],
    *,
    tag: str = DEFAULT_NOHL_TAG,
    stash_prefixes: Sequence[str] = DEFAULT_STASH_PREFIXES,
    pool_seeds_root: str = DEFAULT_POOL_SEEDS_ROOT,
) -> list[NoHLCandidate]:
    selected: list[NoHLCandidate] = []
    for row in torrents:
        torrent_hash = str(row.get("hash") or "").strip().lower()
        save_path = str(row.get("save_path") or "").strip()
        tags = str(row.get("tags") or "")
        if not torrent_hash or not save_path:
            continue
        tag_set = split_tags(tags)
        if tag not in tag_set:
            continue
        if not is_stash_alias_path(save_path, stash_prefixes):
            continue
        if is_pool_seeds_path(save_path, pool_seeds_root):
            continue
        selected.append(
            NoHLCandidate(
                torrent_hash=torrent_hash,
                save_path=save_path,
                tags=tags,
            )
        )
    return selected


def sort_payload_groups(rows: Iterable[Mapping[str, object]]) -> list[dict]:
    out = [
        {
            "payload_hash": str(item.get("payload_hash") or "").strip(),
            "group_items": int(item.get("group_items") or 0),
            "payload_bytes": int(item.get("payload_bytes") or 0),
            **{k: v for k, v in dict(item).items() if k not in {"payload_hash", "group_items", "payload_bytes"}},
        }
        for item in rows
        if str(item.get("payload_hash") or "").strip()
    ]
    out.sort(key=lambda item: (-item["group_items"], -item["payload_bytes"], item["payload_hash"]))
    return out
