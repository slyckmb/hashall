#!/usr/bin/env python3
"""Run qB mutation actions through hashall's version-aware qB client."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import get_qbittorrent_client
from hashall.script_metadata import register as register_script_metadata

SCRIPT_NAME = Path(__file__).name
SEMVER = "0.1.0"
LAST_UPDATED = "2026-04-09T07:05:00-04:00"
register_script_metadata(SCRIPT_NAME, SEMVER, LAST_UPDATED, argv=" ".join(sys.argv[1:]))


def _split_hashes(value: str) -> list[str]:
    hashes = [part.strip().lower() for part in str(value or "").split("|")]
    return [part for part in hashes if part]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run qB mutation actions through the version-aware hashall client."
    )
    parser.add_argument("action", choices=("resume", "pause"))
    parser.add_argument("hashes", help="Pipe-delimited torrent hashes.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hashes = _split_hashes(args.hashes)
    if not hashes:
        print("No hashes provided.", file=sys.stderr)
        return 2

    client = get_qbittorrent_client(
        base_url=os.environ.get("QBIT_URL", "http://localhost:9003").strip(),
        username=(os.environ.get("QBIT_USER") or os.environ.get("QBITTORRENTAPI_USERNAME") or "admin").strip(),
        password=(os.environ.get("QBIT_PASS") or os.environ.get("QBITTORRENTAPI_PASSWORD") or "adminpass").strip(),
    )

    if args.action == "resume":
        ok = client.resume_torrents(hashes)
    else:
        ok = client.pause_torrents(hashes)

    if ok:
        print(f"{args.action} ok hashes={len(hashes)}")
        return 0

    last_error = getattr(client, "last_error", "") or "unknown_error"
    print(f"{args.action} failed hashes={len(hashes)} last_error={last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
