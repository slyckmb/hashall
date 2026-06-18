#!/usr/bin/env python3
"""
Controlled experiment: does qB recheck_torrent() cause RT to enter checking?

Procedure:
  1. Find a candidate: stalledUP in RT, stoppedUP/pausedUP in qB, cross-seed
  2. Snapshot RT hashing/state for that hash
  3. Issue qB recheck
  4. Poll RT every 0.5s for 60s, log every transition
  5. Report verdict

Run from repo root with venv active:
  python3 scripts/experiment_qb_rt_interaction.py [--hash <hash>]
"""

import sys
import time
import argparse

sys.path.insert(0, "src")

from hashall.rtorrent import (
    fetch_rt_status_rows,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
    DEFAULT_RT_RPC_URL,
)
from hashall.qbittorrent import QBittorrentClient

QB_URL = "http://localhost:9003"
QB_USER = "admin"
QB_PASS = "adminadmin"
RT_RPC = DEFAULT_RT_RPC_URL
POLL_SECS = 90
POLL_INTERVAL = 0.5


def rt_snapshot(h: str) -> dict:
    try:
        return {
            "hashing": int(_xmlrpc_scalar_text(rt_xmlrpc_call("d.hashing", h, rpc_url=RT_RPC)).strip()),
            "state":   int(_xmlrpc_scalar_text(rt_xmlrpc_call("d.state",   h, rpc_url=RT_RPC)).strip()),
            "complete":int(_xmlrpc_scalar_text(rt_xmlrpc_call("d.complete",h, rpc_url=RT_RPC)).strip()),
            "down_rate":int(_xmlrpc_scalar_text(rt_xmlrpc_call("d.down.rate",h,rpc_url=RT_RPC)).strip()),
        }
    except Exception as e:
        return {"error": str(e)}


def pick_candidate(qb: QBittorrentClient) -> tuple[str, str]:
    """Return (hash, name) of a small cross-seed torrent stable in both clients."""
    rows = fetch_rt_status_rows(rpc_url=RT_RPC)
    rt_seeding = {r["hash"].lower() for r in rows if r.get("state") == "stalledUP"
                  and "cross-seed" in r.get("directory", "")}

    qb_torrents = qb.get_torrents()
    candidates = []
    for t in qb_torrents:
        h = t.hash.lower()
        if h not in rt_seeding:
            continue
        if t.state not in ("stoppedUP", "pausedUP", "stalledUP"):
            continue
        candidates.append((h, t.name, getattr(t, "size", 0)))

    if not candidates:
        raise RuntimeError("No suitable candidate found")

    # Pick smallest to minimise check duration
    candidates.sort(key=lambda x: x[2])
    h, name, size = candidates[0]
    return h, name


def run(candidate_hash: str | None = None):
    qb = QBittorrentClient(QB_URL, username=QB_USER, password=QB_PASS)

    if candidate_hash:
        h = candidate_hash.lower()
        info = qb.get_torrent_info(h)
        name = info.name if info else h
    else:
        print("Selecting candidate...")
        h, name = pick_candidate(qb)

    print(f"\nCandidate: {h[:16]}  {name[:60]}")

    # Pre-snapshot RT
    pre = rt_snapshot(h)
    print(f"RT pre-snapshot: {pre}")
    if pre.get("hashing", 0) != 0 or pre.get("state", 0) == 0:
        print("ABORT: RT torrent is not in stable seeding state. Pick another.")
        sys.exit(1)

    # Trigger qB recheck
    print("\nIssuing qB recheck_torrent()...")
    t0 = time.monotonic()
    qb.recheck_torrent(h)

    # Poll RT
    transitions = []
    prev_hashing = pre.get("hashing", 0)
    print(f"Polling RT every {POLL_INTERVAL}s for {POLL_SECS}s...\n")

    polls = int(POLL_SECS / POLL_INTERVAL)
    for i in range(polls):
        time.sleep(POLL_INTERVAL)
        snap = rt_snapshot(h)
        elapsed = time.monotonic() - t0
        hashing = snap.get("hashing", -1)
        state   = snap.get("state",   -1)
        dr      = snap.get("down_rate", 0)

        if hashing != prev_hashing:
            msg = f"  t={elapsed:.1f}s  RT hashing changed: {prev_hashing} → {hashing}  state={state} down_rate={dr}"
            print(msg)
            transitions.append({"t": elapsed, "from_hashing": prev_hashing, "to_hashing": hashing,
                                 "state": state, "down_rate": dr})
            prev_hashing = hashing

        if dr > 0:
            print(f"  ⚠  t={elapsed:.1f}s  RT down_rate={dr} — RT IS DOWNLOADING")
            transitions.append({"t": elapsed, "event": "DOWNLOADING", "down_rate": dr})

    # Final snapshot
    post = rt_snapshot(h)
    elapsed_total = time.monotonic() - t0
    print(f"\nRT post-snapshot (t={elapsed_total:.1f}s): {post}")

    print("\n=== VERDICT ===")
    if any(tr.get("to_hashing", 0) != 0 or tr.get("event") == "DOWNLOADING" for tr in transitions):
        print("HYPOTHESIS CONFIRMED: qB recheck triggered RT state change.")
        print(f"Transitions observed: {len(transitions)}")
    else:
        print("HYPOTHESIS NOT CONFIRMED: RT showed no reaction to qB recheck.")
        print("RT remained stable throughout.")
    print(f"Transitions log: {transitions or 'none'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash", default=None, help="Specific torrent hash to test")
    args = parser.parse_args()
    run(args.hash)
