#!/usr/bin/env python3
"""Hash-scoped RT surgical repair wrapper with metadata verification."""

from __future__ import annotations

import argparse
import json
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
    rt_apply_directory_repoint,
    rt_get_torrent_directory,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)

SCRIPT_NAME = "rt-surgical-repair.py"
SEMVER = "0.1.0"


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verify and repair explicit RT hashes without bypassing surgical gate evidence."
    )
    p.add_argument("--hash", action="append", dest="hashes", default=[], help="Torrent hash; repeatable")
    p.add_argument("--hashes-file", default="", help="File of hashes, one per line")
    p.add_argument("--target", required=True, help="Candidate target directory or content root")
    p.add_argument("--session-dir", default=str(DEFAULT_RT_SESSION_DIR))
    p.add_argument("--rpc-url", default=DEFAULT_RT_RPC_URL)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--poll-secs", type=float, default=120.0)
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    p.add_argument("--apply", action="store_true", help="Apply live RT mutation")
    p.add_argument(
        "--allow-start-if-complete",
        action="store_true",
        help="Allow start after hash-check only if RT reports complete=1",
    )
    p.add_argument("--report-json", default="", help="Write JSON report to this path")
    return p


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


def load_torrent_info(session_dir: Path, torrent_hash: str) -> dict[str, Any]:
    candidates = [
        session_dir / f"{torrent_hash.upper()}.torrent",
        session_dir / f"{torrent_hash.lower()}.torrent",
    ]
    torrent_file = next((p for p in candidates if p.exists()), candidates[0])
    if not torrent_file.exists():
        raise FileNotFoundError(f"missing torrent file: {torrent_file}")
    payload = bencode_decode(torrent_file.read_bytes())
    if not isinstance(payload, dict) or not isinstance(payload.get(b"info"), dict):
        raise ValueError(f"invalid torrent metadata: {torrent_file}")
    return payload[b"info"]


def decode_path(parts: list[Any]) -> str:
    decoded: list[str] = []
    for part in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode("utf-8", "ignore"))
        else:
            decoded.append(str(part))
    return str(Path(*decoded)) if decoded else ""


def expected_files(info: dict[str, Any]) -> tuple[str, bool, list[dict[str, Any]]]:
    raw_name = info.get(b"name", b"")
    info_name = raw_name.decode("utf-8", "ignore") if isinstance(raw_name, bytes) else str(raw_name or "")
    files = info.get(b"files")
    if isinstance(files, list):
        rows: list[dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            rel = decode_path(item.get(b"path", []) or [])
            rows.append({"relative_path": rel, "size": int(item.get(b"length", 0) or 0)})
        return info_name, True, rows
    return info_name, False, [{"relative_path": info_name, "size": int(info.get(b"length", 0) or 0)}]


def verify_payload(session_dir: Path, torrent_hash: str, target: str) -> dict[str, Any]:
    meta = load_rt_torrent_meta(session_dir, torrent_hash)
    if meta is None:
        raise FileNotFoundError(f"missing RT torrent metadata for {torrent_hash}")
    info = load_torrent_info(session_dir, torrent_hash)
    info_name, is_multi, files = expected_files(info)
    normalized = normalize_rt_target_directory(target, meta)
    root = Path(normalized) / info_name if is_multi else Path(normalized)
    missing: list[dict[str, Any]] = []
    present = 0
    total_size = 0
    for row in files:
        rel = row["relative_path"]
        size = int(row["size"])
        total_size += size
        path = root / rel
        if not path.exists():
            missing.append({"relative_path": rel, "expected_size": size, "reason": "missing"})
            continue
        actual = path.stat().st_size
        if actual != size:
            missing.append(
                {
                    "relative_path": rel,
                    "expected_size": size,
                    "actual_size": actual,
                    "reason": "size_mismatch",
                }
            )
            continue
        present += 1
    return {
        "info_name": info_name,
        "is_multi_file": is_multi,
        "normalized_target": normalized,
        "content_root": str(root),
        "file_count": len(files),
        "present_count": present,
        "missing_count": len(missing),
        "total_bytes": total_size,
        "missing": missing,
        "verified": len(missing) == 0,
    }


def rt_scalar(method: str, torrent_hash: str, *, rpc_url: str, timeout: int) -> str:
    try:
        return _xmlrpc_scalar_text(rt_xmlrpc_call(method, torrent_hash, rpc_url=rpc_url, timeout=timeout))
    except Exception as exc:
        return f"ERROR:{exc}"


def repair_one(args: argparse.Namespace, torrent_hash: str) -> dict[str, Any]:
    session_dir = Path(args.session_dir).expanduser()
    report: dict[str, Any] = {
        "hash": torrent_hash,
        "target": args.target,
        "dry_run": bool(args.dry_run or not args.apply),
        "apply": bool(args.apply),
        "allow_start_if_complete": bool(args.allow_start_if_complete),
        "actions": [],
        "status": "unknown",
    }
    try:
        current_dir = rt_get_torrent_directory(torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
        report["pre_state"] = {
            "directory": current_dir,
            "state": rt_scalar("d.state", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
        }
        verification = verify_payload(session_dir, torrent_hash, args.target)
        report["verification"] = verification
        if not verification["verified"]:
            report["status"] = "blocked"
            report["blocked_reason"] = "payload_verification_failed"
            return report
        if not args.apply:
            report["status"] = "dry_run_ok"
            report["actions"] = [
                "d.stop",
                "d.close",
                "d.directory.set",
                "d.save_full_session",
                "session.save",
                "d.open",
                "d.check_hash",
            ]
            if args.allow_start_if_complete:
                report["actions"].append("d.start_if_complete")
            return report
        if args.allow_start_if_complete:
            result = rt_apply_directory_repoint(
                torrent_hash,
                verification["normalized_target"],
                rpc_url=args.rpc_url,
                restart=True,
                check_before_start=True,
                validate_target_exists=True,
                timeout=args.timeout,
            )
            report["actions"] = result
        else:
            result = rt_apply_directory_repoint(
                torrent_hash,
                verification["normalized_target"],
                rpc_url=args.rpc_url,
                restart=False,
                check_before_start=False,
                validate_target_exists=True,
                timeout=args.timeout,
            )
            rt_xmlrpc_call("d.check_hash", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout)
            result.append("d.check_hash")
            report["actions"] = result
        time.sleep(1)
        report["post_state"] = {
            "directory": rt_get_torrent_directory(torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "state": rt_scalar("d.state", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "complete": rt_scalar("d.complete", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
            "hashing": rt_scalar("d.hashing", torrent_hash, rpc_url=args.rpc_url, timeout=args.timeout),
        }
        report["status"] = "applied"
        return report
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report


def main() -> int:
    args = build_parser().parse_args()
    hashes = read_hashes(args)
    if not hashes:
        print("ERROR no hashes supplied", file=sys.stderr)
        return 2
    if args.apply and args.dry_run:
        print("ERROR choose --apply or --dry-run, not both", file=sys.stderr)
        return 2
    results = [repair_one(args, h) for h in hashes]
    report = {
        "tool": "rt-surgical-repair",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": ts(),
        "summary": {
            "total": len(results),
            "dry_run_ok": sum(1 for r in results if r["status"] == "dry_run_ok"),
            "applied": sum(1 for r in results if r["status"] == "applied"),
            "blocked": sum(1 for r in results if r["status"] == "blocked"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        },
        "results": results,
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.report_json:
        path = Path(args.report_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"report_json={path}")
    print(
        "summary "
        f"total={report['summary']['total']} "
        f"dry_run_ok={report['summary']['dry_run_ok']} "
        f"applied={report['summary']['applied']} "
        f"blocked={report['summary']['blocked']} "
        f"errors={report['summary']['errors']}"
    )
    return 1 if report["summary"]["blocked"] or report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
