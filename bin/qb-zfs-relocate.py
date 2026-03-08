#!/usr/bin/env python3
"""qb-zfs-relocate v0.1.4. Last updated: 2026-03-08."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qb_zfs_relocate import main


if __name__ == "__main__":
    raise SystemExit(main())
