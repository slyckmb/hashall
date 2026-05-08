"""
Hitchhiker split: for each N→1 group, create per-hash hardlink trees under
_rehome-unique/<hash16>/ and repoint qB + RT to the new per-hash locations.

Only the primary hash (hashes[0]) stays at the original root_path.
All secondary hashes get their own hardlinked copy so each can be verified
and managed independently.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .hitchhiker import HitchhikerGroup, HitchhikerStatus
from .qbittorrent import QBittorrentClient, get_torrents_from_cache, DEFAULT_QB_CACHE_FILE
from .rtorrent import rt_apply_directory_repoint, DEFAULT_RT_RPC_URL

# Seeding root aliases: (fs_path_on_host, api_path_for_qb_and_rt)
# The catalog may store /stash/... paths (ZFS alt mount) while qB/RT use /data/media/...
_SEEDING_ROOT_ALIASES: list[tuple[str, str]] = [
    ("/stash/media/torrents/seeding", "/data/media/torrents/seeding"),
    ("/data/media/torrents/seeding", "/data/media/torrents/seeding"),
    ("/pool/media/torrents/seeding", "/pool/media/torrents/seeding"),
]


@dataclass
class SplitAction:
    """Planned/executed split for one secondary hash."""
    hash_val: str
    source_root_path: str       # original shared root (file or dir on disk)
    target_parent_fs: str       # filesystem path: <seeding_root_fs>/_rehome-unique/<hash16>/
    target_parent_api: str      # qB/RT API path: <seeding_root_api>/_rehome-unique/<hash16>/
    is_dir: bool                # True = multi-file torrent (source is directory)
    target_content_fs: str = ""
    source_exists: bool = False
    target_parent_exists: bool = False
    target_content_exists: bool = False
    target_parent_entries: int = 0
    same_device: Optional[bool] = None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    files_linked: int = 0
    completed: bool = False
    error: Optional[str] = None


@dataclass
class SplitGroupResult:
    """Result of splitting one hitchhiker group."""
    payload_id: int
    primary_hash: str
    root_path: str
    actions: list[SplitAction] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _seeding_roots_for_path(root_path: str) -> tuple[str, str]:
    """
    Return (fs_root, api_root) for a root_path under any known seeding root.
    fs_root: path to use for filesystem hardlink operations.
    api_root: path to pass to qB and RT APIs.
    Raises ValueError if root_path is not under a known seeding root.
    """
    for fs_root, api_root in _SEEDING_ROOT_ALIASES:
        if root_path == fs_root or root_path.startswith(fs_root + "/"):
            return fs_root, api_root
    raise ValueError(f"root_path not under any known seeding root: {root_path!r}")


def _api_path(path_on_fs: str, fs_root: str, api_root: str) -> str:
    """Convert a filesystem path to the corresponding qB/RT API path."""
    if fs_root == api_root:
        return path_on_fs
    rel = path_on_fs[len(fs_root):]
    return api_root + rel


def _hardlink_tree(src: Path, dst_parent: Path, *, dry_run: bool) -> int:
    """
    Hardlink src (file or directory tree) into dst_parent.
    For a file: creates dst_parent/<src.name> as a hardlink.
    For a dir:  creates dst_parent/<src.name>/<...> mirroring the tree.
    Returns number of files linked (or counted in dry-run).
    """
    count = 0
    if src.is_file():
        dst = dst_parent / src.name
        if dst.exists():
            raise FileExistsError(f"target already exists: {dst}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(str(src), str(dst))
        count = 1
    elif src.is_dir():
        for item in sorted(src.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(src.parent)  # relative to src's parent, keeps src.name
            dst_file = dst_parent / rel
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                if dst_file.exists():
                    raise FileExistsError(f"target already exists: {dst_file}")
                os.link(str(item), str(dst_file))
            count += 1
    else:
        raise FileNotFoundError(f"source root not found or unsupported: {src}")
    return count


def _inspect_split_target(src: Path, dst_parent: Path) -> tuple[str, bool, bool, bool, int, Optional[bool], list[str], list[str]]:
    target_content = dst_parent / src.name
    source_exists = src.is_file() or src.is_dir()
    target_parent_exists = dst_parent.exists()
    target_content_exists = target_content.exists()
    entries = 0
    warnings: list[str] = []
    blockers: list[str] = []
    same_device: Optional[bool] = None

    if not source_exists:
        blockers.append("source_root_missing_or_not_file_or_dir")
    if target_parent_exists:
        if dst_parent.is_dir():
            try:
                entries = sum(1 for _ in dst_parent.iterdir())
            except OSError:
                blockers.append("target_parent_unreadable")
        else:
            blockers.append("target_parent_exists_not_directory")
        if entries == 0:
            warnings.append("target_parent_exists_empty")
        elif entries > 0:
            blockers.append("target_parent_exists_non_empty")
    if target_content_exists:
        blockers.append("target_content_exists")

    try:
        base = dst_parent.parent
        if source_exists and base.exists():
            same_device = os.stat(src).st_dev == os.stat(base).st_dev
            if not same_device:
                blockers.append("source_and_target_on_different_devices")
    except OSError:
        same_device = None
        blockers.append("unable_to_verify_source_target_device")

    return (
        str(target_content),
        source_exists,
        target_parent_exists,
        target_content_exists,
        entries,
        same_device,
        warnings,
        blockers,
    )


def plan_split_actions(group: HitchhikerGroup) -> list[SplitAction]:
    """Build the list of split actions for secondary hashes in a group."""
    root_path = group.root_path
    try:
        fs_root, api_root = _seeding_roots_for_path(root_path)
    except ValueError:
        return []

    src = Path(root_path)
    is_dir = src.is_dir()
    actions = []

    # hashes[0] = primary, stays in place. hashes[1:] = secondaries to split.
    for secondary_hash in group.hashes[1:]:
        slug = secondary_hash[:16]
        target_parent_fs = f"{fs_root}/_rehome-unique/{slug}"
        target_parent_api = f"{api_root}/_rehome-unique/{slug}"
        (
            target_content_fs,
            source_exists,
            target_parent_exists,
            target_content_exists,
            target_parent_entries,
            same_device,
            warnings,
            blockers,
        ) = _inspect_split_target(src, Path(target_parent_fs))
        actions.append(
            SplitAction(
                hash_val=secondary_hash,
                source_root_path=root_path,
                target_parent_fs=target_parent_fs,
                target_parent_api=target_parent_api,
                is_dir=is_dir,
                target_content_fs=target_content_fs,
                source_exists=source_exists,
                target_parent_exists=target_parent_exists,
                target_content_exists=target_content_exists,
                target_parent_entries=target_parent_entries,
                same_device=same_device,
                warnings=warnings,
                blockers=blockers,
            )
        )
    return actions


def execute_split_group(
    group: HitchhikerGroup,
    *,
    dry_run: bool = True,
    qb_client: Optional[QBittorrentClient] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> SplitGroupResult:
    """
    Split one hitchhiker group: hardlink secondary hashes to _rehome-unique/<hash16>/,
    then repoint qB and RT for each secondary.
    """
    result = SplitGroupResult(
        payload_id=group.payload_id,
        primary_hash=group.hashes[0],
        root_path=group.root_path,
    )

    if group.status != HitchhikerStatus.SAFE_TO_SPLIT:
        result.error = f"group not safe to split: status={group.status.value}"
        return result

    actions = plan_split_actions(group)
    if not actions:
        result.error = f"no split actions (root_path not under known seeding root: {group.root_path!r})"
        return result

    if qb_client is None and not dry_run:
        qb_client = QBittorrentClient()

    result.actions = actions
    all_ok = True

    for action in actions:
        try:
            if action.blockers:
                raise RuntimeError(f"split action blocked: {','.join(action.blockers)}")
            # 1. Hardlink the content tree
            src = Path(action.source_root_path)
            dst_parent = Path(action.target_parent_fs)
            action.files_linked = _hardlink_tree(src, dst_parent, dry_run=dry_run)

            # 2. Repoint qB save location
            if not dry_run and qb_client:
                ok = qb_client.set_location(action.hash_val, action.target_parent_api)
                if not ok:
                    raise RuntimeError("qb set_location returned False")

            # 3. Repoint RT directory
            if not dry_run:
                rt_apply_directory_repoint(
                    action.hash_val,
                    action.target_parent_api,
                    rpc_url=rpc_url,
                    restart=True,
                )

            action.completed = True

        except Exception as exc:
            action.error = str(exc)
            action.completed = False
            all_ok = False
            result.notes.append(f"  {action.hash_val[:16]}: FAILED — {exc}")

    result.success = all_ok
    if dry_run:
        result.notes.append("dry-run: no files written, no qB/RT changes made")
    return result


def split_hitchhiker_groups(
    groups: list[HitchhikerGroup],
    *,
    dry_run: bool = True,
    limit: Optional[int] = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    include_unsafe: bool = False,
) -> list[SplitGroupResult]:
    """
    Split a list of hitchhiker groups (SAFE_TO_SPLIT only), smallest-first.
    """
    # Broad mode only processes safe groups; selected dry-runs include unsafe
    # groups so the operator sees why a requested target is blocked.
    safe = list(groups) if include_unsafe else [g for g in groups if g.status == HitchhikerStatus.SAFE_TO_SPLIT]
    safe.sort(key=lambda g: (g.file_count, g.total_bytes))
    if limit:
        safe = safe[:limit]

    # Load qB client once (uses cache)
    qb_client: Optional[QBittorrentClient] = None
    if not dry_run:
        qb_client = QBittorrentClient()

    results = []
    for group in safe:
        result = execute_split_group(group, dry_run=dry_run, qb_client=qb_client, rpc_url=rpc_url)
        results.append(result)

    return results


def format_split_report(
    results: list[SplitGroupResult],
    *,
    dry_run: bool,
    json_output: bool = False,
) -> str:
    """Format split results for output."""
    if json_output:
        import json
        return json.dumps(
            [
                {
                    "payload_id": r.payload_id,
                    "primary_hash": r.primary_hash[:16],
                    "root_path": r.root_path,
                    "success": r.success,
                    "error": r.error,
                    "dry_run": dry_run,
                    "actions": [
                        {
                            "hash": a.hash_val[:16],
                            "target_parent": a.target_parent_api,
                            "target_content_fs": a.target_content_fs,
                            "source_exists": a.source_exists,
                            "target_parent_exists": a.target_parent_exists,
                            "target_content_exists": a.target_content_exists,
                            "target_parent_entries": a.target_parent_entries,
                            "same_device": a.same_device,
                            "warnings": a.warnings,
                            "blockers": a.blockers,
                            "files": a.files_linked,
                            "completed": a.completed,
                            "error": a.error,
                        }
                        for a in r.actions
                    ],
                    "notes": r.notes,
                }
                for r in results
            ],
            indent=2,
        )

    lines = []
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success and r.error)
    total_files = sum(a.files_linked for r in results for a in r.actions)

    lines.append(f"Hitchhiker Split [{mode}]: {len(results)} groups processed")
    lines.append(f"  Succeeded: {succeeded}  Failed: {failed}  Files linked: {total_files}")
    lines.append("")

    for r in results:
        status = "OK" if r.success else ("ERR" if r.error else "SKIP")
        lines.append(f"  [{status}] payload_id={r.payload_id}  primary={r.primary_hash[:16]}")
        lines.append(f"        root: {r.root_path}")
        for a in r.actions:
            a_status = "OK" if a.completed else ("ERR" if a.error else "PLAN")
            lines.append(
                f"        [{a_status}] {a.hash_val[:16]} → {a.target_parent_api}  files={a.files_linked}"
            )
            if a.warnings:
                lines.append(f"               warnings: {', '.join(a.warnings)}")
            if a.blockers:
                lines.append(f"               blockers: {', '.join(a.blockers)}")
            if a.error:
                lines.append(f"               error: {a.error}")
        if r.error:
            lines.append(f"        error: {r.error}")
        for note in r.notes:
            lines.append(f"        note: {note}")

    return "\n".join(lines)
