"""Filesystem-backed payload identity helpers for rehome planning/execution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from hashall.pathing import canonicalize_path
from hashall.payload import PayloadFile, compute_payload_hash
from hashall.scan import compute_sha256


@dataclass(frozen=True)
class RootContentSnapshot:
    root: Path
    file_count: int
    total_bytes: int
    payload_hash: Optional[str]
    entries: Tuple[Tuple[str, int, Optional[str]], ...]


@dataclass(frozen=True)
class RootContentComparison:
    matches: bool
    reason: str
    left_payload_hash: Optional[str]
    right_payload_hash: Optional[str]


def _canonical_root(path: Path | str) -> Path:
    return canonicalize_path(Path(path).resolve())


def _iter_root_files(root: Path) -> Sequence[Tuple[str, Path]]:
    if root.is_file():
        return ((root.name, root),)

    pairs = []
    for candidate in root.rglob("*"):
        if candidate.is_file():
            rel = str(candidate.relative_to(root))
            pairs.append((rel, candidate))
    pairs.sort(key=lambda item: item[0])
    return tuple(pairs)


def build_root_content_snapshot(
    root_path: Path | str,
    *,
    root_cache: Optional[Dict[str, RootContentSnapshot]] = None,
    path_sha_cache: Optional[Dict[Tuple[str, int, int], Optional[str]]] = None,
    inode_sha_cache: Optional[Dict[Tuple[int, int, int, int], Optional[str]]] = None,
) -> RootContentSnapshot:
    root = _canonical_root(root_path)
    cache_key = str(root)
    if root_cache is not None and cache_key in root_cache:
        return root_cache[cache_key]

    if not root.exists():
        snapshot = RootContentSnapshot(
            root=root,
            file_count=0,
            total_bytes=0,
            payload_hash=None,
            entries=tuple(),
        )
        if root_cache is not None:
            root_cache[cache_key] = snapshot
        return snapshot

    resolved_path_cache = path_sha_cache if path_sha_cache is not None else {}
    resolved_inode_cache = inode_sha_cache if inode_sha_cache is not None else {}
    payload_files = []
    entry_rows = []
    total_bytes = 0

    for rel_path, abs_path in _iter_root_files(root):
        stat_result = abs_path.stat()
        size = int(stat_result.st_size)
        mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
        inode_key = (int(stat_result.st_dev), int(stat_result.st_ino), size, mtime_ns)
        path_key = (str(abs_path.resolve()), size, mtime_ns)

        sha256 = resolved_inode_cache.get(inode_key)
        if sha256 is None and path_key in resolved_path_cache:
            sha256 = resolved_path_cache[path_key]
        if sha256 is None:
            sha256 = compute_sha256(abs_path)
            resolved_path_cache[path_key] = sha256
            resolved_inode_cache[inode_key] = sha256

        payload_files.append(
            PayloadFile(
                relative_path=rel_path,
                size=size,
                sha256=sha256,
            )
        )
        entry_rows.append((rel_path, size, sha256))
        total_bytes += size

    snapshot = RootContentSnapshot(
        root=root,
        file_count=len(entry_rows),
        total_bytes=total_bytes,
        payload_hash=compute_payload_hash(payload_files),
        entries=tuple(sorted(entry_rows, key=lambda row: row[0])),
    )
    if root_cache is not None:
        root_cache[cache_key] = snapshot
    return snapshot


def compare_root_content(
    left_root: Path | str,
    right_root: Path | str,
    *,
    root_cache: Optional[Dict[str, RootContentSnapshot]] = None,
    path_sha_cache: Optional[Dict[Tuple[str, int, int], Optional[str]]] = None,
    inode_sha_cache: Optional[Dict[Tuple[int, int, int, int], Optional[str]]] = None,
) -> RootContentComparison:
    left = build_root_content_snapshot(
        left_root,
        root_cache=root_cache,
        path_sha_cache=path_sha_cache,
        inode_sha_cache=inode_sha_cache,
    )
    right = build_root_content_snapshot(
        right_root,
        root_cache=root_cache,
        path_sha_cache=path_sha_cache,
        inode_sha_cache=inode_sha_cache,
    )

    if left.file_count != right.file_count:
        return RootContentComparison(
            matches=False,
            reason=f"file_count_mismatch left={left.file_count} right={right.file_count}",
            left_payload_hash=left.payload_hash,
            right_payload_hash=right.payload_hash,
        )
    if left.total_bytes != right.total_bytes:
        return RootContentComparison(
            matches=False,
            reason=f"total_bytes_mismatch left={left.total_bytes} right={right.total_bytes}",
            left_payload_hash=left.payload_hash,
            right_payload_hash=right.payload_hash,
        )

    left_entries = {rel: (size, sha) for rel, size, sha in left.entries}
    right_entries = {rel: (size, sha) for rel, size, sha in right.entries}
    if left_entries.keys() != right_entries.keys():
        missing_left = sorted(set(right_entries) - set(left_entries))
        missing_right = sorted(set(left_entries) - set(right_entries))
        detail = []
        if missing_left:
            detail.append(f"missing_from_left={missing_left[0]}")
        if missing_right:
            detail.append(f"missing_from_right={missing_right[0]}")
        return RootContentComparison(
            matches=False,
            reason="path_mismatch " + " ".join(detail),
            left_payload_hash=left.payload_hash,
            right_payload_hash=right.payload_hash,
        )

    for rel_path in sorted(left_entries):
        left_size, left_sha = left_entries[rel_path]
        right_size, right_sha = right_entries[rel_path]
        if left_size != right_size:
            return RootContentComparison(
                matches=False,
                reason=(
                    f"size_mismatch rel={rel_path} "
                    f"left={left_size} right={right_size}"
                ),
                left_payload_hash=left.payload_hash,
                right_payload_hash=right.payload_hash,
            )
        if left_sha != right_sha:
            return RootContentComparison(
                matches=False,
                reason=(
                    f"sha256_mismatch rel={rel_path} "
                    f"left={left_sha or '<missing>'} right={right_sha or '<missing>'}"
                ),
                left_payload_hash=left.payload_hash,
                right_payload_hash=right.payload_hash,
            )

    if left.payload_hash and right.payload_hash and left.payload_hash == right.payload_hash:
        return RootContentComparison(
            matches=True,
            reason=f"payload_hash={left.payload_hash}",
            left_payload_hash=left.payload_hash,
            right_payload_hash=right.payload_hash,
        )

    return RootContentComparison(
        matches=False,
        reason=(
            f"payload_hash_mismatch left={left.payload_hash or '<missing>'} "
            f"right={right.payload_hash or '<missing>'}"
        ),
        left_payload_hash=left.payload_hash,
        right_payload_hash=right.payload_hash,
    )
