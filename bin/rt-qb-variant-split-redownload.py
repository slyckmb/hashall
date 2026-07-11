#!/usr/bin/env python3
"""Split a failed 99.* RT payload away from shared sibling inodes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.bencode import bencode_decode
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    load_rt_session_directories,
    load_rt_torrent_meta,
    normalize_rt_target_directory,
    rt_get_torrent_directory,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)


SCRIPT_NAME = "rt-qb-variant-split-redownload.py"
SEMVER = "0.2.1"
INDEXER_TRACKER_HOST_HINTS = {
    "digitalcore": ("digitalcore",),
    "speedcd": ("speed", "speedcd", "connecting.center"),
    "torrentday": ("torrentday", "td-peers", "jumbohostpro"),
    "torrentleech": ("torrentleech", "tleech"),
}
DEFAULT_PLACEMENT_SCAN_ROOTS = (
    "/data/media/torrents/seeding",
    "/stash/media/torrents/seeding",
    "/data/media/movies",
    "/stash/media/movies",
    "/data/media/shows",
    "/stash/media/shows",
    "/data/media/books",
    "/stash/media/books",
    "/data/media/music",
    "/stash/media/music",
    "/data/media/audiobooks",
    "/stash/media/audiobooks",
)
DEFAULT_MEDIA_LIBRARY_PREFIXES = (
    "/data/media/movies",
    "/stash/media/movies",
    "/data/media/shows",
    "/stash/media/shows",
    "/data/media/books",
    "/stash/media/books",
    "/data/media/music",
    "/stash/media/music",
    "/data/media/audiobooks",
    "/stash/media/audiobooks",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "For explicit failed-completion RT hashes, quarantine the failed torrent's "
            "expected payload path so RT can redownload into a unique path."
        )
    )
    parser.add_argument("--hash", required=True, help="One explicit torrent hash")
    parser.add_argument("--target", default="", help="Override RT save path; default is live d.directory")
    parser.add_argument("--session-dir", default=str(DEFAULT_RT_SESSION_DIR))
    parser.add_argument("--rpc-url", default=DEFAULT_RT_RPC_URL)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--poll-secs", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--apply", action="store_true", help="Apply filesystem and RT mutations")
    parser.add_argument(
        "--start-existing-split",
        action="store_true",
        help="Start an already-split item after proving its payload path is not shared.",
    )
    parser.add_argument(
        "--placement-audit",
        action="store_true",
        help=(
            "Read-only: enumerate same-inode paths for this payload and classify "
            "the payload-group home as stash-required or pool-eligible."
        ),
    )
    parser.add_argument(
        "--placement-scan-root",
        action="append",
        default=[],
        help="Root to scan for hardlink group members during --placement-audit; repeatable.",
    )
    parser.add_argument(
        "--media-library-prefix",
        action="append",
        default=[],
        help="Prefix that counts as a media-library consumer during --placement-audit; repeatable.",
    )
    parser.add_argument(
        "--placement-member-path",
        action="append",
        default=[],
        help=(
            "Existing or proposed compatible member path to include in placement "
            "audit before hardlinking it into the repaired variant group; repeatable."
        ),
    )
    parser.add_argument(
        "--placement-max-files",
        type=int,
        default=200000,
        help="Maximum files to inspect during --placement-audit before returning manual-review status; -1 means unlimited.",
    )
    parser.add_argument(
        "--allow-start-download",
        action="store_true",
        help="After quarantine and hash-check, call d.start so RT can fetch fresh bytes",
    )
    parser.add_argument(
        "--operator-download-approval",
        action="store_true",
        help="Confirm the operator approved this tracker/download choice.",
    )
    parser.add_argument(
        "--freeleech-proof",
        default="",
        help="Path to a JSON proof report with freeleech_proven=true.",
    )
    parser.add_argument("--quarantine-suffix", default="", help="Override quarantine suffix")
    parser.add_argument("--report-json", default="", help="Write JSON report to this path")
    return parser


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rt_scalar(method: str, torrent_hash: str, *, rpc_url: str, timeout: int) -> str:
    try:
        return _xmlrpc_scalar_text(rt_xmlrpc_call(method, torrent_hash, rpc_url=rpc_url, timeout=timeout))
    except Exception as exc:
        return f"ERROR:{exc}"


def resolve_hash(session_dir: Path, raw_hash: str) -> str:
    key = str(raw_hash).strip().lower()
    if len(key) == 40:
        return key
    matches: set[str] = set()
    for path in session_dir.glob("*.torrent"):
        stem = path.name.split(".", 1)[0].lower()
        if stem.startswith(key):
            matches.add(stem)
    if len(matches) != 1:
        raise ValueError(f"hash prefix {key!r} matched {len(matches)} RT session torrents")
    return next(iter(matches))


def torrent_file_for(session_dir: Path, torrent_hash: str) -> Path:
    key = str(torrent_hash).strip()
    for candidate in (session_dir / f"{key.upper()}.torrent", session_dir / f"{key.lower()}.torrent"):
        if candidate.exists():
            return candidate
    return session_dir / f"{key.upper()}.torrent"


def load_torrent_payload(torrent_file: Path) -> dict[bytes, Any]:
    payload = bencode_decode(torrent_file.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get(b"info"), dict):
        raise ValueError(f"invalid torrent metadata: {torrent_file}")
    return payload


def load_torrent_info(torrent_file: Path) -> dict[bytes, Any]:
    payload = load_torrent_payload(torrent_file)
    return payload[b"info"]


def torrent_shape(info: dict[bytes, Any]) -> dict[str, Any]:
    raw_name = info.get(b"name", b"")
    name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
    files = info.get(b"files")
    if isinstance(files, list):
        rows: list[dict[str, Any]] = []
        total = 0
        for item in files:
            parts = [
                p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p)
                for p in (item.get(b"path") or [])
            ]
            length = int(item.get(b"length", 0) or 0)
            total += length
            rows.append({"relative_path": str(Path(*parts)), "size": length})
        return {"name": name, "is_multi_file": True, "files": rows, "size": total}
    size = int(info.get(b"length", 0) or 0)
    return {"name": name, "is_multi_file": False, "files": [{"relative_path": name, "size": size}], "size": size}


def _flatten_tracker_urls(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
        if text:
            out.append(text)
    elif isinstance(value, str):
        if value:
            out.append(value)
    elif isinstance(value, list):
        for item in value:
            out.extend(_flatten_tracker_urls(item))
    return out


def torrent_tracker_urls(torrent_file: Path) -> list[str]:
    payload = load_torrent_payload(torrent_file)
    urls = _flatten_tracker_urls(payload.get(b"announce"))
    urls.extend(_flatten_tracker_urls(payload.get(b"announce-list")))
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _proof_indexer_key(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _tracker_hosts(urls: list[str]) -> list[str]:
    hosts: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host:
            hosts.append(host.lower())
    return hosts


def _freeleech_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("freeleech")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    items = payload.get("all_hits")
    if isinstance(items, list):
        return [
            item
            for item in items
            if isinstance(item, dict)
            and bool((item.get("freeleech") or {}).get("is_freeleech"))
            and bool((item.get("proof_match") or {}).get("is_match"))
        ]
    return []


def validate_freeleech_proof_matches_trackers(
    path_text: str,
    tracker_urls: list[str],
) -> tuple[bool, str, dict[str, Any]]:
    path = Path(path_text).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    hosts = _tracker_hosts(tracker_urls)
    proof_indexers = sorted(
        {
            str(item.get("indexer") or "")
            for item in _freeleech_items(payload)
            if item.get("indexer")
        }
    )
    diagnostics = {
        "proof_path": str(path),
        "proof_indexers": proof_indexers,
        "tracker_urls": tracker_urls,
        "tracker_hosts": hosts,
    }
    unmapped: list[str] = []
    saw_mapped = False
    for indexer in proof_indexers:
        key = _proof_indexer_key(indexer)
        hints = INDEXER_TRACKER_HOST_HINTS.get(key)
        if not hints:
            unmapped.append(indexer)
            continue
        saw_mapped = True
        if any(any(hint in host for hint in hints) for host in hosts):
            diagnostics["matched_indexer"] = indexer
            diagnostics["matched_hints"] = list(hints)
            return True, "ok", diagnostics
    if unmapped:
        diagnostics["unmapped_indexers"] = unmapped
    if not saw_mapped and unmapped:
        return False, f"freeleech_indexer_unmapped:{unmapped[0]}", diagnostics
    return False, "freeleech_proof_tracker_mismatch", diagnostics


def expected_payload_path(save_path: Path, shape: dict[str, Any]) -> Path:
    name = str(shape["name"])
    if bool(shape["is_multi_file"]):
        return save_path / name
    return save_path / name


def stat_or_missing(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return out
    st = path.stat()
    out.update(
        {
            "is_file": path.is_file(),
            "is_dir": path.is_dir(),
            "size": int(st.st_size),
            "dev": int(st.st_dev),
            "inode": int(st.st_ino),
            "nlink": int(st.st_nlink),
        }
    )
    return out


def inode_keys_from_stats(stats: list[dict[str, Any]]) -> set[tuple[int, int]]:
    return {
        (int(row["dev"]), int(row["inode"]))
        for row in stats
        if row.get("exists") and row.get("dev") is not None and row.get("inode") is not None
    }


def child_stats(payload_path: Path, shape: dict[str, Any]) -> list[dict[str, Any]]:
    if not bool(shape["is_multi_file"]):
        return [stat_or_missing(payload_path)]
    rows: list[dict[str, Any]] = []
    for item in shape["files"]:
        rows.append(stat_or_missing(payload_path / str(item["relative_path"])))
    return rows


def has_shared_inode(stats: list[dict[str, Any]]) -> bool:
    return any(int(row.get("nlink") or 0) > 1 for row in stats if row.get("exists"))


def _is_relative_to(path: Path, prefix: Path) -> bool:
    try:
        path.resolve().relative_to(prefix.resolve())
        return True
    except (OSError, ValueError):
        return False


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return Path(left) == Path(right)


def path_under_any(path_text: str, prefixes: list[str]) -> bool:
    path = Path(path_text)
    return any(_is_relative_to(path, Path(prefix)) for prefix in prefixes)


def same_inode_paths(wanted: set[tuple[int, int]], roots: list[Path], *, max_files: int) -> tuple[list[str], bool, int]:
    matches: set[str] = set()
    checked = 0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in {".git", ".zfs"}]
            for name in filenames:
                checked += 1
                if max_files >= 0 and checked > max_files:
                    return sorted(matches), True, checked
                path = Path(dirpath) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                if (int(st.st_dev), int(st.st_ino)) in wanted:
                    matches.add(str(path))
    return sorted(matches), False, checked


def placement_audit(
    report: dict[str, Any],
    *,
    scan_roots: list[str],
    media_prefixes: list[str],
    member_paths: list[str],
    max_files: int,
) -> dict[str, Any]:
    roots = [Path(item).expanduser() for item in (scan_roots or list(DEFAULT_PLACEMENT_SCAN_ROOTS))]
    prefixes = media_prefixes or list(DEFAULT_MEDIA_LIBRARY_PREFIXES)
    member_stats = [stat_or_missing(Path(item).expanduser()) for item in member_paths]
    expected_existing_paths = [
        str(row["path"])
        for row in [*report.get("file_stats", []), *member_stats]
        if row.get("exists") and row.get("path")
    ]
    missing_member_paths = [str(row["path"]) for row in member_stats if not row.get("exists")]
    wanted = inode_keys_from_stats(report.get("file_stats", [])) | inode_keys_from_stats(member_stats)
    members, truncated, checked = same_inode_paths(wanted, roots, max_files=max_files) if wanted else ([], False, 0)
    media_members = [path for path in members if path_under_any(path, prefixes)]
    found_existing_paths = [
        path for path in expected_existing_paths if any(_same_path(path, member) for member in members)
    ]
    missing_expected_paths = sorted(set(expected_existing_paths) - set(found_existing_paths))
    if media_members:
        group_home = "stash_required"
        reason = "media_library_member_present"
    elif not wanted:
        group_home = "unknown_requires_manual_review"
        reason = "no_existing_payload_files_to_audit"
    elif missing_member_paths:
        group_home = "unknown_requires_manual_review"
        reason = "placement_member_path_missing"
    elif truncated:
        group_home = "unknown_requires_manual_review"
        reason = "placement_scan_file_limit_reached"
    elif missing_expected_paths:
        group_home = "unknown_requires_manual_review"
        reason = "payload_files_not_found_in_scan_roots"
    else:
        group_home = "pool_eligible"
        reason = "no_media_library_members_found"
    report["placement_audit"] = {
        "rule": (
            "placement is decided for the whole same-inode payload group; "
            "any media-library member requires stash home for the group"
        ),
        "scan_roots": [str(root) for root in roots],
        "files_checked": checked,
        "scan_truncated": truncated,
        "max_files": max_files,
        "media_library_prefixes": prefixes,
        "placement_member_paths": member_paths,
        "placement_member_stats": member_stats,
        "missing_placement_member_paths": missing_member_paths,
        "same_inode_member_paths": members,
        "media_library_member_paths": media_members,
        "expected_existing_payload_paths": expected_existing_paths,
        "missing_expected_payload_paths": missing_expected_paths,
        "group_home": group_home,
        "reason": reason,
    }
    return report


def nested_session_dirs(
    session_dir: Path,
    payload_path: Path,
    torrent_hash: str,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not payload_path.is_dir():
        return out
    try:
        payload_resolved = payload_path.resolve()
    except OSError:
        payload_resolved = payload_path
    for h, entry in load_rt_session_directories(session_dir).items():
        if h == torrent_hash:
            continue
        directory = Path(entry.directory)
        try:
            resolved = directory.resolve()
        except OSError:
            resolved = directory
        try:
            resolved.relative_to(payload_resolved)
        except ValueError:
            continue
        out.append({"hash": h, "directory": entry.directory})
    return out


def choose_quarantine_path(payload_path: Path, torrent_hash: str, suffix: str) -> Path:
    base_suffix = suffix or f".invalid-for-{torrent_hash[:12]}-{time.strftime('%Y%m%d-%H%M%S')}"
    candidate = payload_path.with_name(payload_path.name + base_suffix)
    idx = 1
    while candidate.exists():
        candidate = payload_path.with_name(payload_path.name + f"{base_suffix}.{idx}")
        idx += 1
    return candidate


def wait_short_state(torrent_hash: str, *, rpc_url: str, timeout: int, poll_secs: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, poll_secs)
    history: list[dict[str, str]] = []
    while True:
        row = {
            "state": rt_scalar("d.state", torrent_hash, rpc_url=rpc_url, timeout=timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=rpc_url, timeout=timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=rpc_url, timeout=timeout),
            "left_bytes": rt_scalar("d.left_bytes", torrent_hash, rpc_url=rpc_url, timeout=timeout),
            "down_rate": rt_scalar("d.down.rate", torrent_hash, rpc_url=rpc_url, timeout=timeout),
            "message": rt_scalar("d.message", torrent_hash, rpc_url=rpc_url, timeout=timeout),
        }
        history.append(row)
        if time.monotonic() >= deadline:
            return {"history": history}
        time.sleep(1)


def validate_freeleech_proof(path_text: str) -> tuple[bool, str]:
    path = Path(path_text).expanduser()
    if not path.is_file():
        return False, "freeleech_proof_file_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"freeleech_proof_json_error:{exc}"
    if not bool(payload.get("freeleech_proven")):
        return False, "freeleech_not_proven"
    if int(payload.get("freeleech_hits") or 0) <= 0:
        return False, "freeleech_hits_zero"
    return True, "ok"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).expanduser()
    torrent_hash = resolve_hash(session_dir, args.hash)
    torrent_file = torrent_file_for(session_dir, torrent_hash)
    info = load_torrent_info(torrent_file)
    shape = torrent_shape(info)
    tracker_urls = torrent_tracker_urls(torrent_file)
    live_dir = rt_get_torrent_directory(torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
    target_raw = args.target or live_dir
    meta = load_rt_torrent_meta(session_dir, torrent_hash)
    normalized_save = normalize_rt_target_directory(target_raw, meta) if meta else target_raw
    save_path = Path(normalized_save)
    payload_path = expected_payload_path(save_path, shape)
    file_stats = child_stats(payload_path, shape)
    quarantine_path = choose_quarantine_path(payload_path, torrent_hash, args.quarantine_suffix)
    return {
        "tool": "rt-qb-variant-split-redownload",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "timestamp": ts(),
        "hash": torrent_hash,
        "dry_run": bool(args.dry_run or not args.apply),
        "apply": bool(args.apply),
        "allow_start_download": bool(args.allow_start_download),
        "torrent": {
            "torrent_file": str(torrent_file),
            "tracker_urls": tracker_urls,
            **shape,
        },
        "pre_rt": {
            "directory": live_dir,
            "state": rt_scalar("d.state", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "left_bytes": rt_scalar("d.left_bytes", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "message": rt_scalar("d.message", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
        },
        "save_path": str(save_path),
        "payload_path": str(payload_path),
        "payload_stat": stat_or_missing(payload_path),
        "file_stats": file_stats,
        "shared_inode_detected": has_shared_inode(file_stats),
        "nested_session_dirs": nested_session_dirs(session_dir, payload_path, torrent_hash),
        "quarantine_path": str(quarantine_path),
        "actions": [],
        "status": "planned",
    }


def apply_report(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    torrent_hash = report["hash"]
    payload_path = Path(report["payload_path"])
    quarantine_path = Path(report["quarantine_path"])
    if not payload_path.exists():
        report["status"] = "blocked"
        report["blocked_reason"] = "payload_path_missing"
        return report
    if quarantine_path.exists():
        report["status"] = "blocked"
        report["blocked_reason"] = "quarantine_path_exists"
        return report
    if report.get("nested_session_dirs"):
        report["status"] = "blocked"
        report["blocked_reason"] = "nested_rt_session_dir_under_payload"
        return report
    if not report.get("shared_inode_detected"):
        report["status"] = "blocked"
        report["blocked_reason"] = "no_shared_inode_detected"
        return report

    rt_xmlrpc_call("d.stop", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
    report["actions"].append("d.stop")
    os.rename(payload_path, quarantine_path)
    report["actions"].append("rename_payload_to_quarantine")
    report["post_rename_payload_stat"] = stat_or_missing(payload_path)
    report["quarantine_stat"] = stat_or_missing(quarantine_path)
    rt_xmlrpc_call("d.check_hash", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
    report["actions"].append("d.check_hash")
    if args.allow_start_download:
        rt_xmlrpc_call("d.start", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
        report["actions"].append("d.start")
    report["post_rt"] = wait_short_state(
        torrent_hash,
        rpc_url=args.rpc_url,
        timeout=args.timeout,
        poll_secs=args.poll_secs,
    )
    report["status"] = "applied"
    return report


def start_existing_split(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    torrent_hash = report["hash"]
    if args.allow_start_download and args.freeleech_proof:
        ok, reason, diagnostics = validate_freeleech_proof_matches_trackers(
            args.freeleech_proof,
            list(report.get("torrent", {}).get("tracker_urls") or []),
        )
        report["freeleech_tracker_match"] = diagnostics
        if not ok:
            report["status"] = "blocked"
            report["blocked_reason"] = reason
            return report
    if not report["payload_stat"].get("exists"):
        report["status"] = "blocked"
        report["blocked_reason"] = "payload_path_missing"
        return report
    if report.get("shared_inode_detected"):
        report["status"] = "blocked"
        report["blocked_reason"] = "payload_still_shared_inode"
        return report
    if report.get("nested_session_dirs"):
        report["status"] = "blocked"
        report["blocked_reason"] = "nested_rt_session_dir_under_payload"
        return report
    if str(report.get("pre_rt", {}).get("complete")) == "1":
        report["status"] = "blocked"
        report["blocked_reason"] = "already_complete"
        return report
    if not args.apply:
        report["status"] = "dry_run_ok"
        report["actions"] = ["d.start"]
        return report
    rt_xmlrpc_call("d.start", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
    report["actions"].append("d.start")
    report["post_rt"] = wait_short_state(
        torrent_hash,
        rpc_url=args.rpc_url,
        timeout=args.timeout,
        poll_secs=args.poll_secs,
    )
    report["status"] = "applied"
    return report


def main() -> int:
    args = build_parser().parse_args()
    if args.apply and args.dry_run:
        print("ERROR choose --apply or --dry-run, not both", file=sys.stderr)
        return 2
    if args.placement_audit and (args.apply or args.start_existing_split or args.allow_start_download):
        print(
            "ERROR --placement-audit is read-only and cannot be combined with mutation/start flags",
            file=sys.stderr,
        )
        return 2
    if args.allow_start_download and not (args.operator_download_approval or args.freeleech_proof):
        print(
            "ERROR --allow-start-download requires --operator-download-approval or --freeleech-proof",
            file=sys.stderr,
        )
        return 2
    if args.allow_start_download and args.freeleech_proof:
        ok, reason = validate_freeleech_proof(args.freeleech_proof)
        if not ok:
            print(f"ERROR invalid --freeleech-proof: {reason}", file=sys.stderr)
            return 2
    report = build_report(args)
    if args.placement_audit:
        report = placement_audit(
            report,
            scan_roots=list(args.placement_scan_root or []),
            media_prefixes=list(args.media_library_prefix or []),
            member_paths=list(args.placement_member_path or []),
            max_files=int(args.placement_max_files),
        )
    if args.start_existing_split:
        report = start_existing_split(args, report)
    elif args.apply:
        report = apply_report(args, report)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report_json:
        path = Path(args.report_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
