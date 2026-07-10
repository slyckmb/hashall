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

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.bencode import bencode_decode
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    load_rt_torrent_meta,
    normalize_rt_target_directory,
    rt_get_torrent_directory,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)


SCRIPT_NAME = "rt-qb-variant-split-redownload.py"
SEMVER = "0.1.0"


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
        "--allow-start-download",
        action="store_true",
        help="After quarantine and hash-check, call d.start so RT can fetch fresh bytes",
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


def load_torrent_info(torrent_file: Path) -> dict[bytes, Any]:
    payload = bencode_decode(torrent_file.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get(b"info"), dict):
        raise ValueError(f"invalid torrent metadata: {torrent_file}")
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


def child_stats(payload_path: Path, shape: dict[str, Any]) -> list[dict[str, Any]]:
    if not bool(shape["is_multi_file"]):
        return [stat_or_missing(payload_path)]
    rows: list[dict[str, Any]] = []
    for item in shape["files"]:
        rows.append(stat_or_missing(payload_path / str(item["relative_path"])))
    return rows


def has_shared_inode(stats: list[dict[str, Any]]) -> bool:
    return any(int(row.get("nlink") or 0) > 1 for row in stats if row.get("exists"))


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


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    session_dir = Path(args.session_dir).expanduser()
    torrent_hash = resolve_hash(session_dir, args.hash)
    torrent_file = torrent_file_for(session_dir, torrent_hash)
    info = load_torrent_info(torrent_file)
    shape = torrent_shape(info)
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


def main() -> int:
    args = build_parser().parse_args()
    if args.apply and args.dry_run:
        print("ERROR choose --apply or --dry-run, not both", file=sys.stderr)
        return 2
    if args.apply and not args.allow_start_download:
        print("ERROR live apply requires --allow-start-download", file=sys.stderr)
        return 2
    report = build_report(args)
    if args.apply:
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
