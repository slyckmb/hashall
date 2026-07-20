#!/usr/bin/env python3
"""Baseline/check/watch guard for RT/qB state drift."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import get_torrents_from_cache
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    fetch_rt_status_rows,
    load_rt_session_directories,
)

SCRIPT_NAME = "rt-qb-state-guard.py"
SEMVER = "0.1.0"
QB_ACTIVE_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "pausedUP", "downloading", "forcedDL", "stalledDL"}
QB_STOPPEDDL_STATES = {"stoppedDL", "pausedDL"}
RT_NON_IDEAL_STATES = {"stoppedDL", "stoppedUP", "stalledDL", "checking", "error"}


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Capture and compare RT/qB state guard baselines.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("baseline", "check"):
        sp = sub.add_parser(name)
        add_common(sp)
        if name == "baseline":
            sp.add_argument("--output", required=True, help="Baseline JSON output path")
        else:
            sp.add_argument("--baseline", required=True, help="Baseline JSON path")
            sp.add_argument("--report-json", required=True, help="Check report JSON output path")
    sp = sub.add_parser("watch")
    add_common(sp)
    sp.add_argument("--baseline", required=True, help="Baseline JSON path")
    sp.add_argument("--report-json", required=True, help="Final report JSON output path")
    sp.add_argument("--journal", default="", help="Optional JSONL journal")
    sp.add_argument("--poll-interval", type=float, default=30.0)
    sp.add_argument("--max-runtime", type=float, default=300.0)
    return p


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rt-rpc-url", default=DEFAULT_RT_RPC_URL)
    p.add_argument("--rt-session-dir", default=str(DEFAULT_RT_SESSION_DIR))
    p.add_argument("--qb-cache-max-age", type=float, default=300.0)
    p.add_argument("--allowed-rt-hash", action="append", default=[], help="Allowed changed RT hash")
    p.add_argument("--allowed-qb-hash", action="append", default=[], help="Allowed changed qB hash")
    p.add_argument("--max-checking", type=int, default=-1, help="Fail if qB checking count exceeds N")


def norm_hashes(values: list[str]) -> set[str]:
    return {str(v).strip().lower() for v in values if str(v).strip()}


def qb_snapshot(max_age: float) -> dict[str, Any]:
    rows = get_torrents_from_cache(max_age_s=max_age) or []
    counts = Counter(str(r.get("state") or "") for r in rows)
    active = [
        item(r)
        for r in rows
        if str(r.get("state") or "") in QB_ACTIVE_STATES
    ]
    stoppeddl = [
        item(r)
        for r in rows
        if str(r.get("state") or "") in QB_STOPPEDDL_STATES
    ]
    checking = [
        item(r)
        for r in rows
        if str(r.get("state") or "").lower().startswith("checking")
    ]
    return {
        "source": "cache",
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        "active": active,
        "stoppeddl": stoppeddl,
        "checking": checking,
    }


def item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "hash": str(row.get("hash") or "").lower(),
        "name": str(row.get("name") or ""),
        "state": str(row.get("state") or ""),
        "save_path": str(row.get("save_path") or ""),
        "tags": str(row.get("tags") or ""),
    }


def rt_snapshot(rpc_url: str, session_dir: str) -> dict[str, Any]:
    rows = fetch_rt_status_rows(rpc_url=rpc_url)
    session = load_rt_session_directories(Path(session_dir).expanduser())
    counts = Counter(str(r.get("state") or "") for r in rows)
    non_ideal = []
    missing_dirs = []
    for row in rows:
        h = str(row.get("hash") or "").lower()
        entry = {
            "hash": h,
            "name": str(row.get("name") or ""),
            "state": str(row.get("state") or ""),
            "directory": str(row.get("directory") or ""),
            "message": str(row.get("message") or ""),
        }
        if entry["state"] in RT_NON_IDEAL_STATES:
            non_ideal.append(entry)
        sess = session.get(h)
        if sess and not sess.path_exists:
            missing_dirs.append({**entry, "session_directory": sess.directory})
    return {
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        "non_ideal": non_ideal,
        "missing_dirs": missing_dirs,
    }


def capture(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "tool": "rt-qb-state-guard",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": ts(),
        "rt": rt_snapshot(args.rt_rpc_url, args.rt_session_dir),
        "qb": qb_snapshot(args.qb_cache_max_age),
    }


def by_hash(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r.get("hash") or "").lower(): r for r in rows if str(r.get("hash") or "").strip()}


def compare(base: dict[str, Any], current: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    allowed_rt = norm_hashes(args.allowed_rt_hash)
    allowed_qb = norm_hashes(args.allowed_qb_hash)
    issues: list[dict[str, Any]] = []

    base_qb_active = set(by_hash(base["qb"].get("active", [])).keys())
    cur_qb_active = by_hash(current["qb"].get("active", []))
    for h, row in cur_qb_active.items():
        if h not in base_qb_active and h not in allowed_qb:
            issues.append({"type": "new_qb_active", "hash": h, "row": row})

    base_qb_stoppeddl = set(by_hash(base["qb"].get("stoppeddl", [])).keys())
    cur_qb_stoppeddl = by_hash(current["qb"].get("stoppeddl", []))
    for h, row in cur_qb_stoppeddl.items():
        if h not in base_qb_stoppeddl and h not in allowed_qb:
            issues.append({"type": "new_qb_stoppeddl", "hash": h, "row": row})

    if args.max_checking >= 0 and len(current["qb"].get("checking", [])) > args.max_checking:
        issues.append(
            {
                "type": "qb_checking_above_limit",
                "count": len(current["qb"].get("checking", [])),
                "limit": args.max_checking,
            }
        )

    base_rt_non_ideal = set(by_hash(base["rt"].get("non_ideal", [])).keys())
    cur_rt_non_ideal = by_hash(current["rt"].get("non_ideal", []))
    for h, row in cur_rt_non_ideal.items():
        if h not in base_rt_non_ideal and h not in allowed_rt:
            issues.append({"type": "new_rt_non_ideal", "hash": h, "row": row})

    base_rt_missing = set(by_hash(base["rt"].get("missing_dirs", [])).keys())
    cur_rt_missing = by_hash(current["rt"].get("missing_dirs", []))
    for h, row in cur_rt_missing.items():
        if h not in base_rt_missing and h not in allowed_rt:
            issues.append({"type": "new_rt_missing_dir", "hash": h, "row": row})

    return {
        "tool": "rt-qb-state-guard",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": ts(),
        "status": "fail" if issues else "pass",
        "summary": {
            "issues": len(issues),
            "qb_active": len(current["qb"].get("active", [])),
            "qb_stoppeddl": len(current["qb"].get("stoppeddl", [])),
            "qb_checking": len(current["qb"].get("checking", [])),
            "rt_non_ideal": len(current["rt"].get("non_ideal", [])),
            "rt_missing_dirs": len(current["rt"].get("missing_dirs", [])),
        },
        "issues": issues,
        "current": current,
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "baseline":
        payload = capture(args)
        write_json(args.output, payload)
        print(f"baseline_json={args.output}")
        return 0
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    if args.cmd == "check":
        report = compare(base, capture(args), args)
        write_json(args.report_json, report)
        print(f"report_json={args.report_json} status={report['status']} issues={report['summary']['issues']}")
        return 0 if report["status"] == "pass" else 1
    deadline = time.monotonic() + max(0.0, args.max_runtime)
    final = None
    while time.monotonic() <= deadline:
        final = compare(base, capture(args), args)
        if args.journal:
            with Path(args.journal).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": ts(), "status": final["status"], "summary": final["summary"]}) + "\n")
        if final["status"] != "pass":
            break
        time.sleep(args.poll_interval)
    if final is None:
        final = compare(base, capture(args), args)
    write_json(args.report_json, final)
    print(f"report_json={args.report_json} status={final['status']} issues={final['summary']['issues']}")
    return 0 if final["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
