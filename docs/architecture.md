# hashall architecture

## Data flow

1) `scan` walks a root directory and records file metadata in SQLite.
2) `export` reads a scan session and writes JSON to `.hashall/hashall.json`.
3) `verify-trees` loads JSON if present or scans on demand, then compares two trees.

## Key modules

- `src/hashall/scan.py`: filesystem walk + hashing
- `src/hashall/export.py`: JSON export
- `src/hashall/verify_trees.py`: orchestration for tree comparison
- `src/hashall/verify.py`: diff logic

## Intended future capabilities

- Treehash support for fast subtree identity checks
- Inode/hardlink awareness for dedupe planning
- Rsync repair manifests and automation

