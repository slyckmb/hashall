#!/usr/bin/env python3
"""Post-mutation guard that polls for stoppedDL emergence and auto-repairs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import (
    QBittorrentClient,
    get_qbittorrent_client,
    get_torrents_from_cache,
)

SEMVER = "0.1.0"
SCRIPT_NAME = Path(__file__).name

STOPPEDDL_STATES = {"stoppeddl", "pauseddl"}


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit_start_banner() -> str:
    now = ts_iso()
    print(f"start ts={now} script={SCRIPT_NAME} semver={SEMVER}")
    return now


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Watch for stoppedDL emergence and auto-repair."
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        help="Seconds between polls (default: 30)",
    )
    p.add_argument(
        "--max-runtime",
        type=float,
        default=0.0,
        help="Max runtime in seconds (0 = unlimited, default: 0)",
    )
    p.add_argument(
        "--exit-on-zero",
        action="store_true",
        default=False,
        help="Exit when stoppedDL count reaches 0",
    )
    p.add_argument(
        "--stop-file",
        default="",
        help="Graceful stop when this file exists",
    )
    p.add_argument(
        "--journal",
        default="",
        help="JSONL journal path (default: <bucket>/watchdog-journal.jsonl)",
    )
    p.add_argument(
        "--bucket-dir",
        default="/tmp/qb-stoppeddl-bucket-live",
        help="Bucket dir for auto-repair (default: /tmp/qb-stoppeddl-bucket-live)",
    )
    p.add_argument(
        "--auto-repair",
        action="store_true",
        default=False,
        help="Enable auto drain+apply for new stoppedDL (OFF by default)",
    )
    p.add_argument(
        "--cache-max-age",
        type=float,
        default=30.0,
        help="Max cache age seconds (default: 30)",
    )
    p.add_argument(
        "--report-json",
        default="",
        help="Final report path (default: <bucket>/reports/watchdog-<ts>.json)",
    )
    return p


def is_stoppeddl(state: str) -> bool:
    return str(state or "").strip().lower() in STOPPEDDL_STATES


def take_snapshot(
    torrents: List[dict],
) -> Dict[str, str]:
    return {
        str(t.get("hash", "")).lower().strip(): str(t.get("state", "") or "")
        for t in torrents
        if str(t.get("hash", "")).strip()
    }


def log_journal(journal_path: Path, entry: dict) -> None:
    try:
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:
        print(f"ERROR journal_write_failed path={journal_path} error={e}", file=sys.stderr)


def run_auto_repair(hash: str, name: str, bucket_dir: str) -> dict:
    drain_cmd = [
        sys.executable,
        str(REPO_ROOT / "bin" / "qb-stoppeddl-drain.py"),
        "--bucket-dir",
        bucket_dir,
        "--hashes",
        hash,
        "--limit",
        "1",
        "--max-candidates",
        "1",
    ]
    try:
        drain_result = subprocess.run(
            drain_cmd,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        return {"auto_repair_result": "failed", "drain_report": "", "error": "drain_timeout"}
    except Exception as e:
        return {"auto_repair_result": "failed", "drain_report": "", "error": str(e)}

    if drain_result.returncode != 0:
        return {"auto_repair_result": "failed", "drain_report": "", "error": drain_result.stderr[:200]}

    drain_report_path = Path(bucket_dir) / "reports" / "drain-latest.json"
    if not drain_report_path.exists():
        return {"auto_repair_result": "failed", "drain_report": "", "error": "no_drain_latest"}

    try:
        report = json.loads(drain_report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"auto_repair_result": "failed", "drain_report": str(drain_report_path), "error": str(e)}

    classified = "no_candidates"
    best_result = None
    for entry in report.get("entries", []):
        c = str(entry.get("classification", "") or "").lower().strip()
        br = entry.get("best_result", {})
        if c == "a" and br.get("verified") is True:
            classified = c
            best_result = br
            break

    if classified != "a":
        return {
            "auto_repair_result": "no_candidates",
            "drain_report": str(drain_report_path),
            "classification": classified,
        }

    apply_cmd = [
        sys.executable,
        str(REPO_ROOT / "bin" / "qb-stoppeddl-apply.py"),
        "--bucket-dir",
        bucket_dir,
        "--hashes",
        hash,
        "--allow-class",
        "a",
        "--apply",
        "--wait-recheck",
    ]
    try:
        apply_result = subprocess.run(
            apply_cmd,
            capture_output=True,
            text=True,
            timeout=7200,
        )
    except subprocess.TimeoutExpired:
        return {"auto_repair_result": "failed", "drain_report": str(drain_report_path), "error": "apply_timeout"}
    except Exception as e:
        return {"auto_repair_result": "failed", "drain_report": str(drain_report_path), "error": str(e)}

    if apply_result.returncode == 0:
        return {"auto_repair_result": "ok", "drain_report": str(drain_report_path)}
    else:
        return {
            "auto_repair_result": "failed",
            "drain_report": str(drain_report_path),
            "error": apply_result.stderr[:200] if apply_result.stderr else "apply_exit_nonzero",
        }


def write_final_report(
    report_path: Path,
    start_time: float,
    exit_reason: str,
    polls: int,
    cache_misses: int,
    baseline_stoppeddl: int,
    new_stoppeddl_detected: int,
    paused: int,
    auto_repaired: int,
    auto_repair_failed: int,
    final_stoppeddl: int,
) -> None:
    runtime = time.time() - start_time
    report = {
        "tool": "qb-stoppeddl-watchdog",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": ts_iso(),
        "runtime_seconds": round(runtime, 1),
        "exit_reason": exit_reason,
        "summary": {
            "polls": polls,
            "cache_misses": cache_misses,
            "baseline_stoppeddl_count": baseline_stoppeddl,
            "new_stoppeddl_detected": new_stoppeddl_detected,
            "paused": paused,
            "auto_repaired": auto_repaired,
            "auto_repair_failed": auto_repair_failed,
            "final_stoppeddl_count": final_stoppeddl,
        },
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report_json={report_path}")
    except OSError as e:
        print(f"ERROR report_write_failed path={report_path} error={e}", file=sys.stderr)
    # Print summary line for log
    print(
        "summary "
        f"exit_reason={exit_reason} runtime_s={round(runtime, 1)} "
        f"polls={polls} cache_misses={cache_misses} "
        f"baseline_stoppeddl={baseline_stoppeddl} "
        f"new_stoppeddl={new_stoppeddl_detected} "
        f"paused={paused} auto_repaired={auto_repaired} "
        f"auto_repair_failed={auto_repair_failed} "
        f"final_stoppeddl={final_stoppeddl}"
    )


def main() -> int:
    args = build_parser().parse_args()
    start_ts = emit_start_banner()
    start_time = time.time()

    bucket_dir = Path(args.bucket_dir).expanduser()
    reports_dir = bucket_dir / "reports"
    journal_path = (
        Path(args.journal).expanduser()
        if str(args.journal or "").strip()
        else bucket_dir / "watchdog-journal.jsonl"
    )
    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else reports_dir / f"watchdog-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    stop_file = str(args.stop_file or "").strip()

    polls = 0
    cache_misses = 0
    new_stoppeddl_detected = 0
    paused = 0
    auto_repaired = 0
    auto_repair_failed = 0
    exit_reason = "unknown"

    print(f"config poll_interval={args.poll_interval}s max_runtime={args.max_runtime}s "
          f"exit_on_zero={args.exit_on_zero} auto_repair={args.auto_repair} "
          f"cache_max_age={args.cache_max_age}s "
          f"stop_file={stop_file or '<none>'}")
    print(f"paths journal={journal_path} report={report_path} bucket_dir={bucket_dir}")

    # Step 1: Take baseline snapshot
    cache = get_torrents_from_cache(max_age_s=args.cache_max_age)
    if cache is None:
        print("ERROR baseline_cache_miss cannot_start", file=sys.stderr)
        exit_reason = "baseline_cache_miss"
        write_final_report(
            report_path, start_time, exit_reason,
            polls, cache_misses, 0, 0, 0, 0, 0, 0,
        )
        return 1

    baseline = take_snapshot(cache)
    current_hash_set: Set[str] = set(baseline.keys())
    baseline_stoppeddl = sum(1 for s in baseline.values() if is_stoppeddl(s))
    print(f"baseline ts={ts_iso()} total={len(baseline)} stoppeddl={baseline_stoppeddl}")

    qb: Optional[QBittorrentClient] = None

    # Signal handling for graceful interrupt
    interrupted = False

    def handle_sigterm(*_args):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        while not interrupted:
            # 2a: Check stop-file
            if stop_file and Path(stop_file).exists():
                print(f"status ts={ts_iso()} action=stop reason=stop_file_exists stop_file={stop_file}")
                exit_reason = "stop_file"
                break

            # 2b: Poll via cache
            cache = get_torrents_from_cache(max_age_s=args.cache_max_age)
            if cache is None:
                cache_misses += 1
                print(f"cache_miss ts={ts_iso()} skip_reason=stale_cache will_retry_in={args.poll_interval}s")
                polls += 1
                if args.max_runtime > 0 and (time.time() - start_time) >= args.max_runtime:
                    exit_reason = "timeout"
                    break
                time.sleep(args.poll_interval)
                continue

            current = take_snapshot(cache)
            current_hash_set = set(current.keys())

            # 2c: Detect NEW stoppedDL
            new_stoppeddl: List[tuple] = []
            for h, state in current.items():
                prior_state = baseline.get(h)
                if is_stoppeddl(state) and (prior_state is None or not is_stoppeddl(prior_state)):
                    # Find name
                    name = ""
                    for t in cache:
                        if str(t.get("hash", "")).lower().strip() == h:
                            name = str(t.get("name", "") or "")
                            break
                    new_stoppeddl.append((h, name, state, prior_state or ""))

            # 2d: Act on each new stoppedDL
            for h, name, current_state, prior_state in new_stoppeddl:
                new_stoppeddl_detected += 1
                print(f"detected ts={ts_iso()} hash={h[:16]} name={name[:60]} "
                      f"state={current_state} prior_state={prior_state}")

                # Pause the torrent
                if qb is None:
                    qb = get_qbittorrent_client()
                if qb.pause_torrent(h):
                    paused += 1
                    action = "paused"
                else:
                    action = "pause_failed"
                    print(f"ERROR pause_failed hash={h[:16]} name={name[:60]} error={qb.last_error}", file=sys.stderr)

                journal_entry = {
                    "ts": ts_iso(),
                    "hash": h,
                    "name": name,
                    "action": action,
                    "prior_state": prior_state,
                    "auto_repaired": False,
                }

                # Auto-repair
                if args.auto_repair and action == "paused":
                    repair_result = run_auto_repair(h, name, str(bucket_dir))
                    ar_result = repair_result.get("auto_repair_result", "")
                    if ar_result == "ok":
                        auto_repaired += 1
                        journal_entry["auto_repaired"] = True
                        journal_entry["action"] = "auto_repaired"
                        journal_entry["auto_repair_result"] = "ok"
                    elif ar_result == "no_candidates":
                        journal_entry["auto_repaired"] = False
                        journal_entry["auto_repair_result"] = "no_candidates"
                    else:
                        auto_repair_failed += 1
                        journal_entry["auto_repaired"] = False
                        journal_entry["auto_repair_result"] = "failed"
                    journal_entry["drain_report"] = repair_result.get("drain_report", "")

                log_journal(journal_path, journal_entry)

            # 2e: Update baseline
            baseline = current

            # Check exit-on-zero
            current_stoppeddl = sum(1 for s in current.values() if is_stoppeddl(s))
            if args.exit_on_zero and current_stoppeddl == 0:
                print(f"status ts={ts_iso()} action=stop reason=zero_stoppeddl")
                exit_reason = "zero_stoppeddl"
                break

            polls += 1

            # Check max runtime
            if args.max_runtime > 0 and (time.time() - start_time) >= args.max_runtime:
                exit_reason = "timeout"
                print(f"status ts={ts_iso()} action=stop reason=timeout "
                      f"max_runtime={args.max_runtime}s")
                break

            time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        exit_reason = "interrupted"
        print(f"status ts={ts_iso()} action=stop reason=interrupted")

    if interrupted:
        exit_reason = "interrupted"
        print(f"status ts={ts_iso()} action=stop reason=interrupted")

    # Final snapshot for final_stoppeddl_count
    final_stoppeddl = 0
    cache = get_torrents_from_cache(max_age_s=args.cache_max_age)
    if cache is not None:
        final_snap = take_snapshot(cache)
        final_stoppeddl = sum(1 for s in final_snap.values() if is_stoppeddl(s))

    write_final_report(
        report_path, start_time, exit_reason,
        polls, cache_misses, baseline_stoppeddl,
        new_stoppeddl_detected, paused, auto_repaired,
        auto_repair_failed, final_stoppeddl,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
