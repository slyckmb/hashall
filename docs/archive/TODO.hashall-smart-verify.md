# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# ✅ TODO.md — Hashall: Smart Verify, Treehash, Hardlink

## Phase 1: Core Verify Command
- ✅ `verify-trees` CLI subcommand
- ✅ Load `.hashall/hashall.json` from both trees
- ✅ Import `scan_session` if not in DB
- ✅ Reuse existing `scan()` machinery (DRY)
- ✅ Write back updated scan JSON after scan
- ✅ DB-level compare: file relpath, sha1, inode
- ✅ Save result report to file
- ✅ Print terminal summary (pass/fail stats)
- 🔹✅ Add `verify.py`, `verify_trees.py`, `verify_session.py` to support functionality

## Phase 2: Treehash Tracking
- ✅ Add `treehash` column to `scan_session`
- ✅ Implement `compute_treehash()` utility
- ✅ Track deterministic relpath/sha1 summary per scan
- ✅ Use to skip redundant scans if tree unchanged
- 🔹OBE Optional: add `tree_hashes` table (subtree) — deferred

## Phase 3: Inode + Hardlink Tracking
- ✅ Add `inode`, `device_id`, `is_hardlink` to `files`
- ✅ Populate inode/device on scan
- ✅ Detect and mark hardlinked files

## Phase 4: Rsync Repair Integration
- ✅ Add `--repair` and `--rsync-source` options
- ✅ Use DB diff to create rsync manifest
- ✅ Run safe, checksum-based `rsync`
- ✅ Save manifest + logs to verify session folder

## Phase 5: CLI UX Polish
- ✅ Add dry-run / verbose modes
- ✅ Pretty print verification report
- 🔹✅ Add progress and console logging steps
- ✅ Export diff report to JSON/CSV

## Phase 6: Treehash Utilities (Future)
- ☐ CLI: `hashall trees --dupes`
- ☐ CLI: `hashall trees --treehash-report`
- ☐ Use to find dedup targets or fast-compare trees
