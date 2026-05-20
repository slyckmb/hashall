#!/usr/bin/env python3
"""
rt-execute-recovery.py v1.0.0

Recovers RT items damaged by a save-path-repair --execute run.

For each hash in the input file:
  1. Read qB current state (save_path, content_path, state, progress)
  2. Trigger qB recheck → poll until not checking → verify stoppedUP 100%
     (never-downloads guard: immediately pause if <100% after recheck)
  3. Repoint RT d.directory to qB's verified path
  4. Trigger RT recheck → poll d.is_hash_checking → verify d.complete==1
"""

VERSION = "1.0.2"
SCRIPT_NAME = "rt-execute-recovery"

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hashall.qbittorrent import get_qbittorrent_client
from hashall.rtorrent import (
    rt_apply_directory_repoint,
    rt_recheck_torrent,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
    load_rt_torrent_meta,
    normalize_rt_target_directory,
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
)

RT_RPC_URL = DEFAULT_RT_RPC_URL
RT_SESSION_DIR = DEFAULT_RT_SESSION_DIR

QB_CHECK_POLL_S = 5.0
QB_CHECK_TIMEOUT_S = 900.0  # 15 min for large files

RT_CHECK_POLL_S = 5.0
RT_CHECK_TIMEOUT_S = 900.0  # 15 min

RT_XMLRPC_TIMEOUT = 60  # seconds per individual XMLRPC call (d.stop/d.directory.set can be slow)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def is_checking_state(state: str) -> bool:
    return str(state or "").lower().startswith("checking")


def qb_poll_until_done(qb, torrent_hash: str) -> object | None:
    """Poll qB until torrent leaves checking states. Returns final QBitTorrent or None on timeout."""
    deadline = time.monotonic() + QB_CHECK_TIMEOUT_S
    while time.monotonic() < deadline:
        info = qb.get_torrent_info(torrent_hash)
        if info is not None and not is_checking_state(info.state):
            return info
        time.sleep(QB_CHECK_POLL_S)
    return None


def rt_poll_until_hash_done(torrent_hash: str) -> bool:
    """Poll RT until d.is_hash_checking == '0'. Returns True when done, False on timeout."""
    deadline = time.monotonic() + RT_CHECK_TIMEOUT_S
    hash_lc = torrent_hash.lower()
    while time.monotonic() < deadline:
        try:
            xml = rt_xmlrpc_call("d.is_hash_checking", hash_lc, rpc_url=RT_RPC_URL)
            if _xmlrpc_scalar_text(xml).strip() == "0":
                return True
        except Exception:
            pass
        time.sleep(RT_CHECK_POLL_S)
    return False


def _rt_dir_matches_target(rt_dir: str, rt_target: str, torrent_hash: str) -> bool:
    """True if RT's live d.directory is consistent with rt_target having been applied.

    After d.open for a multi-file torrent, RT materializes d.directory as
    rt_target/info_name — so both forms count as "already at target".
    """
    if not rt_dir or not rt_target:
        return False
    if rt_dir == rt_target:
        return True
    meta = load_rt_torrent_meta(RT_SESSION_DIR, torrent_hash.lower())
    if meta and meta.is_multi_file and meta.info_name:
        return rt_dir == rt_target.rstrip("/") + "/" + meta.info_name
    return False


def derive_rt_target(qb_info, torrent_hash: str) -> str:
    """Return the correct value to pass to RT d.directory.set.

    rTorrent's d.directory.set expects the PARENT of info_name for multi-file
    torrents (= qb.save_path). rTorrent then materializes d.directory as
    save_path/info_name after d.open.  For single-file, save_path is the
    containing directory — also correct.

    normalize_rt_target_directory handles /stash→/data alias mapping.
    """
    meta = load_rt_torrent_meta(RT_SESSION_DIR, torrent_hash.lower())
    save_path = str(qb_info.save_path or "").rstrip("/")
    return normalize_rt_target_directory(save_path, meta)


def process_hash(qb, torrent_hash: str, dry_run: bool, idx: int, total: int) -> str:
    short = torrent_hash[:16]
    log(f"[{idx}/{total}] {short}…")

    # Read current qB state
    qb_info = qb.get_torrent_info(torrent_hash)
    if qb_info is None:
        log(f"  ERROR: qB has no info for {short} — skipping")
        return "skip_not_found"

    # Read current RT directory
    try:
        xml = rt_xmlrpc_call("d.directory", torrent_hash.lower(), rpc_url=RT_RPC_URL)
        rt_dir = _xmlrpc_scalar_text(xml).strip()
    except Exception as exc:
        rt_dir = f"<error: {exc}>"

    rt_target = derive_rt_target(qb_info, torrent_hash)

    log(f"  qB  state={qb_info.state}  progress={qb_info.progress:.1%}")
    log(f"  qB  save_path={qb_info.save_path}")
    log(f"  qB  content_path={qb_info.content_path}")
    log(f"  RT  current_dir={rt_dir}")
    log(f"  RT  planned_target={rt_target}")

    # Skip check: if RT is already at the target and d.complete==1, nothing to do
    if rt_dir == rt_target or _rt_dir_matches_target(rt_dir, rt_target, torrent_hash):
        try:
            xml = rt_xmlrpc_call("d.complete", torrent_hash.lower(), rpc_url=RT_RPC_URL)
            already_complete = _xmlrpc_scalar_text(xml).strip() == "1"
        except Exception:
            already_complete = False
        if already_complete:
            log(f"  SKIP: RT already at target and d.complete=1 — already recovered")
            return "already_recovered"

    if dry_run:
        log(f"  DRY-RUN: would recheck qB → verify 100% → repoint RT → recheck RT")
        return "dry_run"

    # ── Step 1: qB recheck ──────────────────────────────────────────────────
    log(f"  Step 1/3: qB recheck…")
    ok = qb.recheck_torrent(torrent_hash)
    if not ok:
        log(f"  ERROR: qB recheck_torrent call failed for {short}")
        return "fail_qb_recheck_trigger"

    # Give qB a moment to flip to checking state before polling
    time.sleep(3.0)

    final_info = qb_poll_until_done(qb, torrent_hash)
    if final_info is None:
        log(f"  ERROR: qB recheck timed out after {QB_CHECK_TIMEOUT_S:.0f}s — pausing torrent immediately")
        qb.pause_torrent(torrent_hash)
        return "fail_qb_recheck_timeout"

    log(f"  qB recheck result: state={final_info.state} progress={final_info.progress:.1%}")

    # Never-downloads guard
    if final_info.state != "stoppedUP" or final_info.progress < 1.0:
        log(f"  GUARD: qB not stoppedUP at 100% — pausing torrent immediately to prevent downloads")
        qb.pause_torrent(torrent_hash)
        return "fail_qb_not_complete"

    log(f"  qB verified: 100% stoppedUP ✅")

    # Refresh rt_target from the post-recheck info (same values, but be consistent)
    rt_target = derive_rt_target(final_info, torrent_hash)

    # ── Step 2: RT repoint ──────────────────────────────────────────────────
    log(f"  Step 2/3: RT repoint → {rt_target}")
    try:
        rt_apply_directory_repoint(
            torrent_hash.lower(), rt_target, rpc_url=RT_RPC_URL, restart=True, timeout=RT_XMLRPC_TIMEOUT
        )
    except Exception as exc:
        log(f"  ERROR: RT repoint failed: {exc}")
        return "fail_rt_repoint"

    # ── Step 3: RT recheck ──────────────────────────────────────────────────
    log(f"  Step 3/3: RT recheck…")
    try:
        rt_recheck_torrent(torrent_hash.lower(), rpc_url=RT_RPC_URL)
    except Exception as exc:
        log(f"  ERROR: RT recheck trigger failed: {exc}")
        return "fail_rt_recheck_trigger"

    # Give RT a moment to start checking
    time.sleep(3.0)

    rt_done = rt_poll_until_hash_done(torrent_hash)
    if not rt_done:
        log(f"  ERROR: RT recheck timed out after {RT_CHECK_TIMEOUT_S:.0f}s")
        return "fail_rt_recheck_timeout"

    # Verify RT complete
    try:
        xml = rt_xmlrpc_call("d.complete", torrent_hash.lower(), rpc_url=RT_RPC_URL)
        rt_complete = _xmlrpc_scalar_text(xml).strip()
    except Exception as exc:
        log(f"  ERROR: RT d.complete query failed: {exc}")
        return "fail_rt_complete_query"

    if rt_complete != "1":
        log(f"  ERROR: RT recheck done but d.complete={rt_complete} — data not found at {rt_target}")
        return "fail_rt_not_complete"

    log(f"  RT recheck: d.complete=1 ✅")
    log(f"  RESULT: RECOVERED ✅")
    return "recovered"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=f"{SCRIPT_NAME} v{VERSION}: recover RT items from save-path-repair --execute damage"
    )
    ap.add_argument(
        "--hashes-file",
        default="/tmp/hashall-20260508-043305-claude-execute-hashes.txt",
        help="File with one 40-char info_hash per line (default: %(default)s)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Process at most N hashes from the file (default: 1)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute mutations (default: dry-run only)",
    )
    args = ap.parse_args()

    dry_run = not args.apply
    mode = "dry-run" if dry_run else "apply"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"[{SCRIPT_NAME} v{VERSION}] phase={mode} ts={ts}")
    log(f"  hashes_file={args.hashes_file}  limit={args.limit}")

    hashes_path = Path(args.hashes_file)
    if not hashes_path.exists():
        log(f"ERROR: hashes file not found: {hashes_path}")
        sys.exit(1)

    all_hashes = [
        line.strip().lower()
        for line in hashes_path.read_text().splitlines()
        if line.strip() and len(line.strip()) == 40
    ]
    log(f"  total valid hashes in file: {len(all_hashes)}")

    batch = all_hashes[: args.limit]
    log(f"  batch size: {len(batch)}")

    qb = get_qbittorrent_client()

    counts: dict[str, int] = {"recovered": 0, "already_recovered": 0, "dry_run": 0, "skip_not_found": 0, "failed": 0}
    for idx, h in enumerate(batch, 1):
        outcome = process_hash(qb, h, dry_run, idx, len(batch))
        if outcome in counts:
            counts[outcome] += 1
        else:
            counts["failed"] += 1

    log("---")
    log(
        f"Processed: {len(batch)}"
        f"  Recovered: {counts['recovered']}"
        f"  AlreadyOK: {counts['already_recovered']}"
        f"  Failed: {counts['failed']}"
        f"  DryRun: {counts['dry_run']}"
        f"  Skipped: {counts['skip_not_found']}"
    )
    log(f"[{SCRIPT_NAME} v{VERSION}] phase={mode} done ts={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
