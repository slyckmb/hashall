#!/usr/bin/env python3
"""Build per-torrent hardlink payload trees from verified sibling bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.bencode import bencode_decode
from hashall.qbittorrent import get_qbittorrent_client
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    load_rt_torrent_meta,
    normalize_rt_target_directory,
    rt_apply_directory_repoint,
    rt_check_and_conditionally_start,
    rt_get_torrent_directory,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)
from hashall.torrent_verify import verify_torrent_pieces


SCRIPT_NAME = "torrent-sibling-hardlink-repair.py"
SEMVER = "0.2.0"


@dataclass(frozen=True)
class ExpectedFile:
    rel_path: Path
    length: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "For explicit torrent hashes, create the exact payload tree each .torrent "
            "expects by hardlinking verified source bytes, then optionally repoint RT/qB."
        )
    )
    parser.add_argument("--hash", action="append", dest="hashes", default=[], help="Torrent hash; repeatable")
    parser.add_argument("--hashes-file", default="", help="File of hashes, one per line")
    parser.add_argument("--source-file", default="", help="Verified single source file to hardlink from")
    parser.add_argument(
        "--source-dir",
        default="",
        help=(
            "Verified source save path for single- or multi-file torrents. "
            "May be the directory above info_name or the info_name directory itself."
        ),
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Target save path. Use HASH=/path for multiple hashes, or /path for one hash.",
    )
    parser.add_argument("--session-dir", default=str(DEFAULT_RT_SESSION_DIR))
    parser.add_argument("--rpc-url", default=DEFAULT_RT_RPC_URL)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--poll-secs", type=float, default=180.0)
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--apply", action="store_true", help="Apply live filesystem and client mutations")
    parser.add_argument("--skip-rt", action="store_true", help="Do not mutate rTorrent")
    parser.add_argument("--skip-qb", action="store_true", help="Do not mutate qBittorrent")
    parser.add_argument(
        "--allow-start-if-complete",
        action="store_true",
        help="Start RT after recheck only if RT reports complete=1",
    )
    parser.add_argument("--report-json", default="", help="Write JSON report to this path")
    return parser


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_hashes(args: argparse.Namespace) -> list[str]:
    values = list(args.hashes or [])
    if args.hashes_file:
        for line in Path(args.hashes_file).read_text(encoding="utf-8").splitlines():
            text = line.split("#", 1)[0].strip()
            if text:
                values.append(text)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        h = str(value).strip().lower()
        if h and h not in seen:
            out.append(h)
            seen.add(h)
    return out


def parse_targets(values: list[str], hashes: list[str]) -> dict[str, str]:
    bare: list[str] = []
    mapped: dict[str, str] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if "=" in text:
            key, path = text.split("=", 1)
            key = key.strip().lower()
            path = path.strip()
            matches = [h for h in hashes if h.startswith(key)]
            if len(matches) != 1:
                raise SystemExit(f"target hash prefix {key!r} matched {len(matches)} hashes")
            mapped[matches[0]] = path
        else:
            bare.append(text)
    if bare:
        if len(hashes) != 1 or len(bare) != 1:
            raise SystemExit("bare --target is only allowed with exactly one --hash")
        mapped[hashes[0]] = bare[0]
    missing = [h for h in hashes if h not in mapped]
    if missing:
        raise SystemExit(f"missing --target for hash(es): {', '.join(h[:12] for h in missing)}")
    return mapped


def torrent_file_for(session_dir: Path, torrent_hash: str) -> Path:
    candidates = (
        session_dir / f"{torrent_hash.upper()}.torrent",
        session_dir / f"{torrent_hash.lower()}.torrent",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_torrent_info(torrent_file: Path) -> dict[bytes, Any]:
    payload = bencode_decode(torrent_file.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get(b"info"), dict):
        raise ValueError(f"invalid torrent metadata: {torrent_file}")
    return payload[b"info"]


def torrent_expected_files(info: dict[bytes, Any]) -> tuple[str, bool, int, int, list[bytes], list[ExpectedFile]]:
    raw_name = info.get(b"name", b"")
    name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
    piece_length = int(info.get(b"piece length", 0) or 0)
    raw_pieces = info.get(b"pieces", b"")
    if not name or piece_length <= 0 or not isinstance(raw_pieces, bytes) or len(raw_pieces) % 20:
        raise ValueError("invalid torrent metadata")
    pieces = [raw_pieces[i : i + 20] for i in range(0, len(raw_pieces), 20)]
    if isinstance(info.get(b"files"), list):
        entries: list[ExpectedFile] = []
        for file_info in info.get(b"files", []):
            parts = [
                p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p)
                for p in (file_info.get(b"path") or [])
            ]
            length = int(file_info.get(b"length", 0) or 0)
            if not parts or length < 0:
                raise ValueError("invalid multi-file torrent metadata")
            entries.append(ExpectedFile(Path(name).joinpath(*parts), length))
        if not entries:
            raise ValueError("multi-file torrent has no files")
        return name, True, sum(e.length for e in entries), piece_length, pieces, entries
    size = int(info.get(b"length", 0) or 0)
    if size <= 0:
        raise ValueError("invalid single-file torrent metadata")
    return name, False, size, piece_length, pieces, [ExpectedFile(Path(name), size)]


def source_base_for_dir(source_dir: Path, info_name: str, entries: list[ExpectedFile]) -> Path:
    if all((source_dir / entry.rel_path).is_file() for entry in entries):
        return source_dir
    stripped: list[Path] = []
    for entry in entries:
        try:
            stripped.append(entry.rel_path.relative_to(info_name))
        except ValueError:
            stripped.append(entry.rel_path)
    if all((source_dir / rel).is_file() for rel in stripped):
        return source_dir.parent
    raise ValueError(f"source_dir does not contain expected torrent tree for {info_name}: {source_dir}")


def verify_source_file(source_file: Path, expected_size: int, piece_length: int, pieces: list[bytes]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(source_file),
        "exists": source_file.is_file(),
        "expected_size": expected_size,
        "piece_count": len(pieces),
        "pieces_ok": 0,
        "pieces_fail": 0,
        "success": False,
    }
    if not source_file.is_file():
        result["error"] = "source_missing"
        return result
    stat = source_file.stat()
    result["size"] = int(stat.st_size)
    result["dev"] = int(stat.st_dev)
    result["inode"] = int(stat.st_ino)
    result["nlink"] = int(stat.st_nlink)
    if int(stat.st_size) != int(expected_size):
        result["error"] = "source_size_mismatch"
        return result
    with source_file.open("rb") as handle:
        for expected in pieces:
            actual = hashlib.sha1(handle.read(piece_length)).digest()
            if actual == expected:
                result["pieces_ok"] += 1
            else:
                result["pieces_fail"] += 1
    result["success"] = result["pieces_fail"] == 0 and result["pieces_ok"] == len(pieces)
    return result


def stat_dict(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"path": str(path), "size": int(st.st_size), "dev": int(st.st_dev), "inode": int(st.st_ino), "nlink": int(st.st_nlink)}


def hardlink_expected_file(
    source_file: Path,
    target_file: Path,
    expected_size: int,
    *,
    apply: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": str(source_file),
        "target": str(target_file),
        "expected_size": expected_size,
        "apply": apply,
        "action": "none",
        "ok": False,
    }
    source_stat = source_file.stat()
    if int(source_stat.st_size) != int(expected_size):
        out["error"] = "source_size_mismatch"
        return out
    if target_file.exists():
        target_stat = target_file.stat()
        out["pre_target"] = stat_dict(target_file)
        if (
            target_file.is_file()
            and int(target_stat.st_size) == int(expected_size)
            and int(target_stat.st_dev) == int(source_stat.st_dev)
            and int(target_stat.st_ino) == int(source_stat.st_ino)
        ):
            out["action"] = "already_hardlinked"
            out["ok"] = True
            return out
        out["error"] = "target_exists_not_same_inode"
        return out
    out["action"] = "create_hardlink"
    if not apply:
        out["ok"] = True
        return out
    target_file.parent.mkdir(parents=True, exist_ok=True)
    os.link(source_file, target_file)
    out["post_target"] = stat_dict(target_file)
    out["ok"] = True
    return out


def hardlink_expected_tree(
    source_base_dir: Path,
    target_base_dir: Path,
    entries: list[ExpectedFile],
    *,
    apply: bool,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    ok = True
    for entry in entries:
        result = hardlink_expected_file(
            source_base_dir / entry.rel_path,
            target_base_dir / entry.rel_path,
            entry.length,
            apply=apply,
        )
        files.append(result)
        ok = ok and bool(result.get("ok"))
    return {
        "source_base_dir": str(source_base_dir),
        "target_base_dir": str(target_base_dir),
        "file_count": len(entries),
        "apply": apply,
        "ok": ok,
        "files": files,
    }


def rt_scalar(method: str, torrent_hash: str, *, rpc_url: str, timeout: int) -> str:
    try:
        return _xmlrpc_scalar_text(rt_xmlrpc_call(method, torrent_hash, rpc_url=rpc_url, timeout=timeout))
    except Exception as exc:
        return f"ERROR:{exc}"


def wait_qb_recheck(qb: Any, torrent_hash: str, *, timeout_s: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    history: list[str] = []
    saw_checking = False
    while time.monotonic() < deadline:
        info = qb.get_torrent_info(torrent_hash)
        if info is None:
            return {"ok": False, "reason": "missing_qb_info", "history": history[-10:]}
        state = str(info.state or "")
        progress = float(info.progress or 0.0)
        amount_left = int(info.amount_left or 0)
        history.append(f"{state}:{progress:.6f}:{amount_left}")
        lowered = state.lower()
        is_checking = "check" in lowered or lowered in {"queuedcheck"}
        saw_checking = saw_checking or is_checking
        if is_checking:
            time.sleep(2)
            continue
        if progress >= 0.999999 and amount_left == 0:
            return {
                "ok": True,
                "state": state,
                "progress": progress,
                "amount_left": amount_left,
                "history": history[-10:],
            }
        if saw_checking:
            return {
                "ok": False,
                "state": state,
                "progress": progress,
                "amount_left": amount_left,
                "history": history[-10:],
            }
        time.sleep(2)
    return {"ok": False, "reason": "timeout", "history": history[-10:]}


def repair_one(args: argparse.Namespace, torrent_hash: str, target_save_path: str) -> dict[str, Any]:
    session_dir = Path(args.session_dir).expanduser()
    source_file = Path(args.source_file).expanduser() if args.source_file else None
    source_dir = Path(args.source_dir).expanduser() if args.source_dir else None
    torrent_file = torrent_file_for(session_dir, torrent_hash)
    target_dir = Path(target_save_path).expanduser()
    report: dict[str, Any] = {
        "hash": torrent_hash,
        "target_save_path": str(target_dir),
        "dry_run": bool(args.dry_run or not args.apply),
        "apply": bool(args.apply),
        "timestamp": ts(),
        "actions": [],
        "status": "unknown",
    }
    try:
        info = load_torrent_info(torrent_file)
        expected_name, is_multi_file, expected_size, piece_length, pieces, entries = torrent_expected_files(info)
        report["torrent"] = {
            "torrent_file": str(torrent_file),
            "name": expected_name,
            "is_multi_file": is_multi_file,
            "size": expected_size,
            "piece_length": piece_length,
            "piece_count": len(pieces),
            "file_count": len(entries),
        }
        report["pre_rt"] = {
            "directory": rt_get_torrent_directory(torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "state": rt_scalar("d.state", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "left_bytes": rt_scalar("d.left_bytes", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "message": rt_scalar("d.message", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
        }
        source_is_single_file = source_file is not None
        if source_file is not None:
            if is_multi_file:
                raise ValueError("--source-file is only valid for single-file torrents; use --source-dir")
            source_verify = verify_source_file(source_file, expected_size, piece_length, pieces)
            source_base_dir = source_file.parent
        elif source_dir is not None:
            source_base_dir = source_base_for_dir(source_dir, expected_name, entries)
            source_verify_raw = verify_torrent_pieces(torrent_file, source_base_dir)
            source_verify = {
                "path": str(source_dir),
                "source_base_dir": str(source_base_dir),
                "exists": source_dir.exists(),
                "expected_size": expected_size,
                "piece_count": source_verify_raw.piece_count,
                "pieces_ok": source_verify_raw.pieces_ok,
                "pieces_fail": source_verify_raw.pieces_fail,
                "pieces_missing": source_verify_raw.pieces_missing,
                "files_missing": source_verify_raw.files_missing,
                "success": source_verify_raw.success,
                "summary": source_verify_raw.summary,
            }
        else:
            raise ValueError("one of --source-file or --source-dir is required")
        report["source_verify"] = source_verify
        if not source_verify.get("success"):
            report["status"] = "blocked"
            report["blocked_reason"] = "source_failed_torrent_piece_verification"
            return report
        if source_is_single_file:
            link_result = hardlink_expected_file(
                source_file,
                target_dir / entries[0].rel_path,
                entries[0].length,
                apply=bool(args.apply),
            )
        else:
            link_result = hardlink_expected_tree(source_base_dir, target_dir, entries, apply=bool(args.apply))
        report["hardlink"] = link_result
        if not link_result.get("ok"):
            report["status"] = "blocked"
            report["blocked_reason"] = "hardlink_target_not_safe"
            return report
        if not args.apply:
            report["status"] = "dry_run_ok"
            report["actions"] = ["verify_source", "create_hardlink"]
            if not args.skip_rt:
                report["actions"].append("rt_repoint_recheck")
            if not args.skip_qb:
                report["actions"].append("qb_set_location_recheck")
            return report
        target_verify = verify_torrent_pieces(torrent_file, target_dir)
        report["target_verify"] = {
            "success": target_verify.success,
            "summary": target_verify.summary,
            "files_missing": target_verify.files_missing,
        }
        if not target_verify.success:
            report["status"] = "blocked"
            report["blocked_reason"] = "target_failed_torrent_piece_verification"
            return report
        meta = load_rt_torrent_meta(session_dir, torrent_hash)
        normalized_rt_target = normalize_rt_target_directory(str(target_dir), meta)
        if not args.skip_rt:
            rt_actions = rt_apply_directory_repoint(
                torrent_hash,
                normalized_rt_target,
                rpc_url=args.rpc_url,
                restart=False,
                check_before_start=False,
                validate_target_exists=True,
                timeout=args.timeout,
            )
            rt_actions.append("d.check_hash")
            rt_xmlrpc_call("d.check_hash", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
            if args.allow_start_if_complete:
                start_result = rt_check_and_conditionally_start(
                    torrent_hash,
                    rpc_url=args.rpc_url,
                    poll_secs=args.poll_secs,
                    timeout=args.timeout,
                )
                report["rt_start_result"] = start_result
            report["rt_actions"] = rt_actions
        if not args.skip_qb:
            qb = get_qbittorrent_client()
            ok = qb.login()
            if not ok:
                report["qb"] = {"ok": False, "error": qb.last_error or "login_failed"}
            else:
                before = qb.get_torrent_info(torrent_hash)
                report["pre_qb"] = before.__dict__ if before is not None else None
                set_ok = qb.set_location(torrent_hash, str(target_dir), resume_after=False)
                recheck_ok = qb.recheck_torrent(torrent_hash) if set_ok else False
                wait_result = wait_qb_recheck(qb, torrent_hash, timeout_s=args.poll_secs) if recheck_ok else {}
                after = qb.get_torrent_info(torrent_hash)
                report["qb"] = {
                    "set_location": bool(set_ok),
                    "recheck": bool(recheck_ok),
                    "wait": wait_result,
                    "post": after.__dict__ if after is not None else None,
                }
        report["post_rt"] = {
            "directory": rt_get_torrent_directory(torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "state": rt_scalar("d.state", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "left_bytes": rt_scalar("d.left_bytes", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "message": rt_scalar("d.message", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
        }
        report["status"] = "applied"
        return report
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report


def main() -> int:
    args = build_parser().parse_args()
    if bool(args.source_file) == bool(args.source_dir):
        print("ERROR specify exactly one of --source-file or --source-dir", file=sys.stderr)
        return 2
    hashes = read_hashes(args)
    if not hashes:
        print("ERROR no hashes supplied", file=sys.stderr)
        return 2
    if args.apply and args.dry_run:
        print("ERROR choose --apply or --dry-run, not both", file=sys.stderr)
        return 2
    targets = parse_targets(args.target, hashes)
    results = [repair_one(args, h, targets[h]) for h in hashes]
    report = {
        "tool": "torrent-sibling-hardlink-repair",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "timestamp": ts(),
        "results": results,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report_json:
        path = Path(args.report_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if any(r.get("status") in {"error", "blocked"} for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
