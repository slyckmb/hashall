#!/usr/bin/env python3
"""Pause any qB mirror-tagged items in non-acceptable states (upload or download)."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.hashall.qbittorrent import get_qbittorrent_client, get_torrents_from_cache

ACCEPTABLE_PAUSED_STATES = {"stoppedUP", "pausedUP"}
UPLOAD_STATES = {"stalledUP", "uploading", "forcedUP", "queuedUP"}
DOWNLOAD_STATES = {"downloading", "forcedDL", "stalledDL"}
ALL_NON_ACCEPTABLE = UPLOAD_STATES | DOWNLOAD_STATES
MIRROR_TAGS = {"hashall-client-drift", "hashall-rt-qb-mirror"}


def parse_states(text: str) -> set:
    out = set()
    for part in str(text or "").replace("|", ",").split(","):
        s = part.strip()
        if s:
            out.add(s)
    return out


def is_mirror_item(torrent: dict) -> bool:
    return any(tag in (torrent.get("tags") or "") for tag in MIRROR_TAGS)


def is_non_acceptable_state(state: str, selected_states: set) -> bool:
    state = str(state or "").strip()
    return state in selected_states and state not in ACCEPTABLE_PAUSED_STATES


def live_state(qb, torrent_hash: str) -> str:
    try:
        info = qb.get_torrent_info(torrent_hash)
    except Exception:
        return ""
    return str(getattr(info, "state", "") or "") if info is not None else ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pause qB mirror-tagged items in non-acceptable states."
    )
    p.add_argument("--dry-run", action="store_true", help="Preview actions without mutating qB")
    p.add_argument(
        "--states",
        default="",
        help="Comma-separated states to quiesce (default: all non-acceptable states)",
    )
    p.add_argument(
        "--report-json",
        default="",
        help="Write structured JSON report to this path",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    states = parse_states(args.states) if args.states else ALL_NON_ACCEPTABLE

    cache = get_torrents_from_cache(max_age_s=300)
    if cache is None:
        print("No fresh qB cache available.", file=sys.stderr)
        return 1

    targets = [
        t for t in cache
        if is_non_acceptable_state(t.get("state", ""), states)
        and is_mirror_item(t)
    ]

    if not targets:
        print("No mirror items in selected states found.")
        if args.report_json:
            now = datetime.now().isoformat(timespec="seconds")
            report = {
                "script": "pause_mirror_seeders",
                "generated_at": now,
                "dry_run": args.dry_run,
                "summary": {
                    "total_mirror_items": 0,
                    "upload_paused": 0,
                    "download_paused": 0,
                    "failed": 0,
                },
                "actions": [],
            }
            Path(args.report_json).write_text(json.dumps(report, indent=2) + "\n")
        return 0

    qb = get_qbittorrent_client()
    upload_ok = download_ok = err = 0
    actions = []

    for t in targets:
        h = t["hash"]
        name = t["name"]
        state = t.get("state", "")
        tags = t.get("tags", "")
        is_download = state in DOWNLOAD_STATES

        if args.dry_run:
            print(f"DRY-RUN would pause {h[:16]}: {name} state={state}")
            action = "dry_run"
        else:
            if qb.pause_torrent(h):
                verified_state = live_state(qb, h)
                if is_download:
                    print(f"  WARNING {h[:16]}: {name} state={state} tags={tags}")
                    download_ok += 1
                else:
                    suffix = f" -> {verified_state}" if verified_state else ""
                    print(f"  paused  {h[:16]}: {name[:55]}{suffix}")
                    upload_ok += 1
                action = "paused"
            else:
                verified_state = ""
                print(f"  FAILED  {h[:16]}: {name}")
                err += 1
                action = "failed"

        entry = {
            "hash": h,
            "name": name,
            "state": state,
            "verified_state": verified_state if not args.dry_run else "",
            "action": action,
        }
        if is_download and action in ("paused", "dry_run"):
            entry["warning"] = "download_state"
        actions.append(entry)

    if args.dry_run:
        paused_count = len(targets)
        upload_count = sum(1 for t in targets if t.get("state") in UPLOAD_STATES)
        download_count = sum(1 for t in targets if t.get("state") in DOWNLOAD_STATES)
        print(f"Dry-run: would pause {paused_count} mirror item(s) ({upload_count} upload, {download_count} download).")
    else:
        print(f"Done: {upload_ok} upload paused, {download_ok} download paused, {err} failed.")

    if args.report_json:
        now = datetime.now().isoformat(timespec="seconds")
        report = {
            "script": "pause_mirror_seeders",
            "generated_at": now,
            "dry_run": args.dry_run,
            "summary": {
                "total_mirror_items": len(targets),
                "upload_paused": upload_ok,
                "download_paused": download_ok,
                "failed": err,
            },
            "actions": actions,
        }
        Path(args.report_json).write_text(json.dumps(report, indent=2) + "\n")

    return 0 if args.dry_run or err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
