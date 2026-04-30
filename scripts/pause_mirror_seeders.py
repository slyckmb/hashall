#!/usr/bin/env python3
"""Pause any qB mirror-tagged items currently in a seeding state."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
cache = json.loads(Path.home().joinpath(".cache/hashall-qb/torrents-info.json").read_text())

SEEDING_STATES = {"stalledUP", "uploading", "forcedUP", "queuedUP"}
MIRROR_TAGS = {"hashall-client-drift", "hashall-rt-qb-mirror"}

targets = [
    t for t in cache
    if t.get("state") in SEEDING_STATES
    and any(tag in (t.get("tags") or "") for tag in MIRROR_TAGS)
]

if not targets:
    print("No seeding mirror items found.")
    sys.exit(0)

print(f"Pausing {len(targets)} seeding mirror item(s)...")
ok = err = 0
for t in targets:
    h = t["hash"]
    if qb.pause_torrent(h):
        print(f"  paused  {h[:16]}: {t['name'][:55]}")
        ok += 1
    else:
        print(f"  FAILED  {h[:16]}: {t['name'][:55]}")
        err += 1
print(f"Done: {ok} paused, {err} failed.")
