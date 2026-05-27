#!/usr/bin/env python3
"""
rt-crossseed-legacy-repair.py v1.0.0

Slice 12b — Remove legacy `cross-seed/` prefix from torrent save paths.

Many qBittorrent torrents have save_path like:
  /data/media/torrents/seeding/cross-seed/<tracker>/<item>
when the canonical path (§4.4) is:
  /data/media/torrents/seeding/<tracker>/<item>

The `cross-seed/` subdirectory is a legacy prefix from an older scheme.
This script scans qB for all such items, renames the filesystem
directories, patches fastresume files, and repoints rTorrent.

Strategy:
  - For unique `cross-seed/<tracker>` dirs whose canonical target
    does NOT exist: rename the whole tracker dir (one mv per tracker).
  - For dirs whose canonical target DOES exist: move items individually.
  - Always dry-run first (default). Pass --apply to execute.

Safety:
  - Stops qB before patching fastresumes, starts after.
  - Creates .bak-repair backups of every modified fastresume.
  - Validates target path is a known seeding root.
"""

VERSION = "1.0.0"
SCRIPT_NAME = "rt-crossseed-legacy-repair"

import argparse
import re
import sys
import time
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hashall.qbittorrent import QBittorrentClient
from hashall.rtorrent import (
    rt_apply_directory_repoint,
    rt_recheck_torrent,
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
)
from hashall.fastresume import patch_fastresume_file, validate_qb_target_save_path

# --- Constants ---

SEEDING_ROOTS = frozenset({
    "/data/media/torrents/seeding",
    "/pool/media/torrents/seeding",
})

QB_CONTAINER = "qbittorrent_vpn"
BT_BACKUP_DIR = Path("/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup")

TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --- Helpers ---

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def log_run_marker(phase: str) -> None:
    print(f"[{TIMESTAMP}] [{SCRIPT_NAME} v{VERSION}] phase={phase}")


def run_qb_command(container: str, *args: str) -> None:
    import subprocess
    subprocess.run(
        ["docker", "exec", container] + list(args),
        check=True, capture_output=True, text=True,
    )


def docker_stop_qb(container: str = QB_CONTAINER) -> None:
    import subprocess
    log(f"Stopping {container} (docker stop)...")
    subprocess.run(["docker", "stop", container], check=True, capture_output=True)
    log(f"{container} stopped.")
    time.sleep(3)


def docker_start_qb(container: str = QB_CONTAINER) -> None:
    import subprocess
    log(f"Starting {container} (docker start)...")
    subprocess.run(["docker", "start", container], check=True, capture_output=True)
    log(f"{container} started.")
    time.sleep(5)


HEX40_RE = re.compile(r"^[0-9a-f]{40}$")


def is_legacy_path(save_path: str) -> bool:
    """True if save_path is under a cross-seed/ prefix that should be removed."""
    sp = save_path.rstrip("/")
    for root in SEEDING_ROOTS:
        prefix = f"{root}/cross-seed/"
        if sp.startswith(prefix):
            # Ignore staging dirs that happen to be under cross-seed/
            remainder = sp[len(prefix):]
            # _rehome-unique and _qb-* are staging, not legacy
            if remainder.startswith("_rehome-unique/") or remainder.startswith("_qb-"):
                return False
            # Skip 40-char hash-named directories (Class 1 — needs tracker resolution, not prefix strip)
            tracker_name = remainder.split("/")[0].lower()
            if HEX40_RE.fullmatch(tracker_name):
                return False
            return True
    return False


def canonical_target(save_path: str) -> str:
    """Remove the /cross-seed/ segment to produce the canonical save path."""
    return save_path.replace("/cross-seed/", "/", 1)


def grouping_key(sp: str) -> tuple:
    """Return (root, tracker_dir) tuple for grouping."""
    sp_norm = sp.rstrip("/")
    for root in SEEDING_ROOTS:
        prefix = f"{root}/cross-seed/"
        if sp_norm.startswith(prefix):
            tracker = sp_norm[len(prefix):].split("/")[0]
            return (root, tracker)
    return ("", "")


# --- Scan ---

def scan_legacy_items() -> list[dict]:
    """Return list of dicts with hash, save_path, content_path for legacy items."""
    qb = QBittorrentClient()
    qb.login()
    torrents = qb.get_torrents()

    items = []
    for t in torrents:
        sp = (t.save_path or "").rstrip("/")
        if not is_legacy_path(sp):
            continue
        items.append({
            "hash": t.hash.lower(),
            "save_path": sp,
            "content_path": (t.content_path or "").rstrip("/"),
            "state": t.state,
            "root": sp.split("/cross-seed/")[0],
        })
    return items


def group_by_tracker_dir(items: list[dict]) -> dict:
    """Group items by (root, tracker_dir) for directory-level rename decisions."""
    groups = defaultdict(lambda: {
        "hashes": [], "save_paths": set(), "item_count": 0,
    })
    for item in items:
        key = grouping_key(item["save_path"])
        groups[key]["hashes"].append(item["hash"])
        groups[key]["save_paths"].add(item["save_path"])
        groups[key]["item_count"] += 1
    return dict(groups)


def classify_groups(items: list[dict]) -> tuple[list, list]:
    """Classify tracker dirs as safe (can mv) or blocked (target exists)."""
    groups = group_by_tracker_dir(items)

    safe = []
    blocked = []

    for key, info in groups.items():
        root, tracker = key
        legacy_dir = f"{root}/cross-seed/{tracker}"
        target_dir = f"{root}/{tracker}"
        target_path = Path(target_dir)

        item = {
            "key": key,
            "root": root,
            "tracker": tracker,
            "legacy_dir": legacy_dir,
            "target_dir": target_dir,
            "target_exists": target_path.exists(),
            "item_count": info["item_count"],
            "hashes": info["hashes"],
        }

        if item["target_exists"]:
            blocked.append(item)
        else:
            safe.append(item)

    safe.sort(key=lambda x: -x["item_count"])
    blocked.sort(key=lambda x: -x["item_count"])
    return safe, blocked


# --- Execute ---

def rename_tracker_dir(legacy_dir: str, target_dir: str, dry_run: bool = True) -> bool:
    """Rename cross-seed/<tracker> to <tracker> (safe rename, target doesn't exist)."""
    src = Path(legacy_dir)
    dst = Path(target_dir)

    if not src.is_dir():
        log(f"  SKIP: source dir does not exist: {legacy_dir}")
        return False

    if dst.exists():
        log(f"  SKIP: target already exists: {target_dir}")
        return False

    if dry_run:
        log(f"  WOULD RENAME: {legacy_dir} → {target_dir}")
        return True

    log(f"  RENAMING: {legacy_dir} → {target_dir}")
    src.rename(dst)
    log(f"  OK: renamed")
    return True


def move_item_dir(legacy_path: str, target_path: str, dry_run: bool = True) -> bool:
    """Move a single item folder from legacy to canonical position.

    For blocked dirs where `cross-seed/<tracker>/` and `<tracker>/` both exist,
    each item subdir must be moved individually.
    """
    src = Path(legacy_path)
    dst = Path(target_path)

    if not src.is_dir():
        log(f"  SKIP: source item dir does not exist: {legacy_path}")
        return False

    if dst.exists():
        log(f"  SKIP: target item path already exists: {target_path}")
        return True  # Already in place — not an error

    if dry_run:
        log(f"  WOULD MOVE: {legacy_path} → {target_path}")
        return True

    # Ensure parent exists
    dst.parent.mkdir(parents=True, exist_ok=True)
    log(f"  MOVING: {legacy_path} → {target_path}")
    shutil.move(str(src), str(dst))
    log(f"  OK: moved")
    return True


def patch_item_fastresume(hash_val: str, new_save_path: str, dry_run: bool = True) -> bool:
    """Patch qB fastresume for one hash to point to new canonical path.

    Returns True on success (or would-succeed in dry-run).
    """
    fastresume = BT_BACKUP_DIR / f"{hash_val}.fastresume"
    if not fastresume.exists():
        log(f"  SKIP fastresume: {fastresume.name} not found")
        return False

    try:
        validate_qb_target_save_path(new_save_path, approved_roots=SEEDING_ROOTS)
    except Exception as e:
        log(f"  ERROR fastresume validation: {e}")
        return False

    if dry_run:
        log(f"  WOULD PATCH fastresume: {fastresume.name} → save_path={new_save_path}")
        return True

    try:
        patch_fastresume_file(fastresume, new_save_path, "bak-repair")
        # Validate the patched path
        validate_qb_target_save_path(new_save_path, approved_roots=SEEDING_ROOTS)
        log(f"  PATCHED+VERIFIED: {fastresume.name} → {new_save_path}")
        return True
    except Exception as e:
        log(f"  ERROR patching fastresume: {e}")
        return False


def repoint_rt(hash_val: str, new_save_path: str, dry_run: bool = True) -> bool:
    """Repoint RT d.directory to the new canonical parent.

    new_save_path should be the PARENT directory (RT appends info_name).
    For cross-seed items: canonical_save_path is the tracker dir.
    """
    if dry_run:
        log(f"  WOULD REPOINT RT: {hash_val[:16]} → {new_save_path}")
        return True

    try:
        # RT repoint: first arg = torrent_hash, second = target_directory (parent save_path)
        result = rt_apply_directory_repoint(hash_val, new_save_path)
        if result:
            log(f"  REPOINTED RT: {hash_val[:16]} → {new_save_path}")
            # Trigger RT recheck
            rt_recheck_torrent(hash_val)
            log(f"  RECHECK triggered RT: {hash_val[:16]}")
            return True
        else:
            log(f"  ERROR repointing RT: {hash_val[:16]}")
            return False
    except Exception as e:
        log(f"  ERROR RT repoint: {e}")
        return False


# --- Main ---

def process_items(
    items: list[dict],
    dry_run: bool = True,
    skip_fastresume: bool = False,
    skip_rt: bool = False,
    limit: int = 0,
) -> dict:
    """Main processing loop. Returns summary dict."""
    safe, blocked = classify_groups(items)

    log(f"  Safe tracker dirs (rename entire dir): {len(safe)}")
    log(f"  Blocked tracker dirs (per-item move): {len(blocked)}")

    total_items = len(items)
    processed_limit = limit if limit > 0 else total_items

    counts = {
        "dir_renamed": 0,
        "dir_skipped": 0,
        "items_moved": 0,
        "items_skipped": 0,
        "fastresume_patched": 0,
        "fastresume_skipped": 0,
        "rt_repointed": 0,
        "rt_skipped": 0,
        "errors": [],
    }

    qb_stopped = False

    # Phase 1: Rename safe tracker directories
    log(f"\n--- Phase 1: Rename safe tracker dirs (no target conflict) ---")
    for g in safe:
        if counts["items_moved"] >= processed_limit:
            break
        ok = rename_tracker_dir(g["legacy_dir"], g["target_dir"], dry_run)
        if ok:
            counts["dir_renamed"] += 1
            counts["items_moved"] += g["item_count"]
        else:
            counts["dir_skipped"] += 1

    # Phase 2: Per-item moves for blocked dirs
    log(f"\n--- Phase 2: Per-item moves (target conflict) ---")
    for g in blocked:
        if counts["items_moved"] >= processed_limit:
            break
        root, tracker = g["key"]
        prefix = f"{root}/cross-seed/{tracker}/"
        target_prefix = f"{root}/{tracker}/"

        for h in g["hashes"]:
            if counts["items_moved"] >= processed_limit:
                break
            # Find item's content dir name
            item_info = [i for i in items if i["hash"] == h]
            if not item_info:
                continue
            cp = item_info[0].get("content_path", "")
            sp = item_info[0].get("save_path", "")

            # Content path gives us the item dir name
            if cp.startswith(prefix):
                item_name = cp[len(prefix):].split("/")[0]
            else:
                # Fallback: extract from save_path vs content_path
                item_name = Path(cp).name if cp else Path(sp).name

            legacy_item_path = f"{prefix}{item_name}"
            target_item_path = f"{target_prefix}{item_name}"

            ok = move_item_dir(legacy_item_path, target_item_path, dry_run)
            if ok:
                counts["items_moved"] += 1
            else:
                counts["items_skipped"] += 1

    if dry_run:
        log(f"\n--- DRY-RUN completed ---")
        return counts

    # Phase 3: Stop qB, patch fastresumes
    log(f"\n--- Phase 3: Stop qB + patch fastresumes ---")
    if not skip_fastresume:
        docker_stop_qb()
        qb_stopped = True
        time.sleep(3)

        for g in safe + blocked:
            if counts["fastresume_patched"] >= processed_limit:
                break
            for h in g["hashes"]:
                if counts["fastresume_patched"] >= processed_limit:
                    break
                old_sp = ""
                for item in items:
                    if item["hash"] == h:
                        old_sp = item["save_path"]
                        break
                new_sp = canonical_target(old_sp) if old_sp else ""
                if not new_sp:
                    continue
                ok = patch_item_fastresume(h, new_sp, dry_run=False)
                if ok:
                    counts["fastresume_patched"] += 1
                else:
                    counts["fastresume_skipped"] += 1

        if qb_stopped:
            docker_start_qb()
            qb_stopped = False
            time.sleep(10)  # Let qB fully init

    # Phase 4: Repoint RT
    log(f"\n--- Phase 4: Repoint RT ---")
    if not skip_rt:
        for g in safe + blocked:
            if counts["rt_repointed"] >= processed_limit:
                break
            for h in g["hashes"]:
                if counts["rt_repointed"] >= processed_limit:
                    break
                old_sp = ""
                for item in items:
                    if item["hash"] == h:
                        old_sp = item["save_path"]
                        break
                new_sp = canonical_target(old_sp) if old_sp else ""
                if not new_sp:
                    continue
                ok = repoint_rt(h, new_sp, dry_run=False)
                if ok:
                    counts["rt_repointed"] += 1
                else:
                    counts["rt_skipped"] += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{SCRIPT_NAME} v{VERSION} — Remove legacy cross-seed/ prefix from torrent save paths",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply repairs (default is dry-run-only)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max items to process (0 = all)",
    )
    parser.add_argument(
        "--skip-fastresume", action="store_true",
        help="Skip fastresume patching phase (for testing)",
    )
    parser.add_argument(
        "--skip-rt", action="store_true",
        help="Skip RT repoint phase (for testing)",
    )
    parser.add_argument(
        "--summary-only", action="store_true",
        help="Only print the summary scan (no processing)",
    )

    args = parser.parse_args()
    dry_run = not args.apply

    log_run_marker("dry-run" if dry_run else "apply")

    log("Scanning qB for legacy cross-seed/ save_path items...")
    items = scan_legacy_items()
    log(f"Found {len(items)} legacy items.")

    if not items:
        log("No legacy items found. Nothing to do.")
        log_run_marker("done")
        return

    safe, blocked = classify_groups(items)
    log(f"Tracker dirs: {len(safe)} safe (target absent), {len(blocked)} blocked (target exists)")
    log(f"Total items: {len(items)}")

    # Print breakdown
    log("\nSafe tracker dirs (will rename entire dir):")
    for g in sorted(safe, key=lambda x: -x["item_count"]):
        log(f"  {g['item_count']:5d}  {g['key'][1]:40s}  {g['root']}")

    log("\nBlocked tracker dirs (per-item move needed):")
    for g in sorted(blocked, key=lambda x: -x["item_count"]):
        log(f"  {g['item_count']:5d}  {g['key'][1]:40s}  {g['root']}")

    if args.summary_only:
        log_run_marker("done")
        return

    limit = args.limit if args.limit > 0 else len(items)
    log(f"\nProcessing up to {limit} items (dry_run={dry_run})...")
    counts = process_items(
        items,
        dry_run=dry_run,
        skip_fastresume=args.skip_fastresume,
        skip_rt=args.skip_rt,
        limit=limit,
    )

    log("\n" + "=" * 60)
    log(f"RESULTS [{SCRIPT_NAME} v{VERSION}]")
    log(f"  Dir renames:        {counts['dir_renamed']}")
    log(f"  Dirs skipped:       {counts['dir_skipped']}")
    log(f"  Items moved:        {counts['items_moved']}")
    log(f"  Items skipped:      {counts['items_skipped']}")
    log(f"  Fastresume patched: {counts['fastresume_patched']}")
    log(f"  Fastresume skipped: {counts['fastresume_skipped']}")
    log(f"  RT repointed:       {counts['rt_repointed']}")
    log(f"  RT skipped:         {counts['rt_skipped']}")
    log(f"  Errors:             {len(counts['errors'])}")
    for err in counts["errors"][:5]:
        log(f"    - {err}")
    log("=" * 60)

    log_run_marker("done")


if __name__ == "__main__":
    main()
