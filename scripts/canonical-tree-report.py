#!/usr/bin/env python3
"""Canonical tree normalization report — lists non-canonical save_path patterns by class."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hashall.model import connect_db

VERSION = "1.0.0"
SCRIPT_NAME = "canonical-tree-report"

# ---------------------------------------------------------------------------
# Class definitions: (label, description, SQL WHERE clause)
# ---------------------------------------------------------------------------

CLASSES = [
    (
        "Class 1",
        "cross-seed/<40-hex-hash>/  (hash-named cross-seed dir)",
        # 40-char hex = GLOB with 40 [0-9a-f] wildcards is unwieldy; use LIKE + length check
        (
            "save_path LIKE '%/cross-seed/%'"
            " AND length(replace(save_path, rtrim(save_path, replace(save_path, '/', '')), '')) = 40"
            " AND (save_path GLOB '*/cross-seed/[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*')"
        ),
    ),
    (
        "Class 2",
        "cross-seed/other/  (unresolved tracker bucket)",
        (
            "save_path LIKE '%/cross-seed/other%'"
            " AND NOT (save_path GLOB '*/cross-seed/[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*')"
        ),
    ),
    (
        "Class 3",
        "cross-seed-link/<tracker>/  (legacy cross-seed-link symlink pattern)",
        "save_path LIKE '%/cross-seed-link/%'",
    ),
    (
        "Class 4",
        "_rehome-unique/<hash>/  (pure-repoint needed)",
        (
            "save_path GLOB '*/_rehome-unique/*'"
            " AND save_path NOT GLOB '*/cross-seed/_rehome-unique/*'"
        ),
    ),
    (
        "Class 5",
        "_qb-unique-repair/ | _qb-repair-v2/ | _qb-finish/  (qB repair staging)",
        (
            "save_path GLOB '*/_qb-unique-repair/*'"
            " OR save_path GLOB '*/_qb-repair-v2/*'"
            " OR save_path GLOB '*/_qb-finish/*'"
        ),
    ),
]


def _report(db_path: Path, full: bool, color: bool) -> None:
    def c(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    conn = connect_db(db_path)
    seen_hashes: set[str] = set()

    print(f"{c('=== Canonical Tree Normalization Report ===', '1')} (v{VERSION})")
    print()

    for label, desc, where in CLASSES:
        rows = conn.execute(
            f"SELECT torrent_hash, save_path, root_name FROM torrent_instances WHERE {where} ORDER BY save_path, root_name"
        ).fetchall()

        count = len(rows)
        seen_hashes.update(row[0].lower() for row in rows)

        status = c(f"({count} items)", "33" if count else "32")
        print(f"{c(label, '1;36')}: {desc}  {status}")

        if count == 0:
            print()
            continue

        # Always show up to 3 samples
        samples = rows[:3]
        print(f"  {'Samples' if count > 3 else 'Items'}:")
        for h, sp, rn in samples:
            display = f"{sp}/{rn}" if rn else sp
            print(f"    {h[:12]}…  {display}")
        if count > 3 and not full:
            print(f"    … and {count - 3} more (use --full to list all)")

        if full and count > 3:
            print(f"  All {count} items:")
            for h, sp, rn in rows:
                display = f"{sp}/{rn}" if rn else sp
                print(f"    {h[:12]}…  {display}")

        print()

    conn.close()
    print(f"{c('Total non-canonical:', '1')} {len(seen_hashes)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="List all items, not just 3 samples per class")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI color")
    ap.add_argument("--db", default=Path.home() / ".hashall" / "catalog.db", type=Path)
    args = ap.parse_args()

    color = sys.stdout.isatty() and not args.no_color
    _report(args.db, args.full, color)


if __name__ == "__main__":
    main()
