# Hashall Handoff (Living)

Last updated: 2026-02-28

## Scope

This handoff covers the stoppedDL recovery campaign using the bucket/drain/apply pipeline.

## Status

- Active toolchain is now:
  - `qb-stoppeddl-bucket.py` (sync + `.torrent` export)
  - `qb-stoppeddl-drain.py` (candidate ranking + libtorrent verify + grading)
  - `qb-stoppeddl-apply.py` (setLocation/recheck + optional fastresume batch patch)
  - `qb-stoppeddl-apply-watch.sh` (daemon/loop apply on completed drains)
  - `qb-stoppeddl-roundloop.sh` (bucket -> drain -> apply -> wait-checking loop)
- qB API helper now supports `.torrent` export via `QBitTorrent.export_torrent_file()`.
- Gradual seeding watchdog was patched to avoid false halts from `checkingDL`.

## Safety Constraints

- One mutating qB workflow at a time.
- Preserve no-download policy during repairs.
- Treat `/data/media` and `/stash/media` as equivalent aliases.
- Keep payload roots unique per hash.
- If a root is exclusive to a hash and bad, quarantine as `<root>.bad.<timestamp>.<hash>`.

## What Changed in This Iteration

- Drain precision and efficiency improvements:
  - stronger global DB pre-verify narrowing (noise token filtering + overlap gating)
  - quick prefilter drops weak candidates before full verify
  - stop candidate testing for a hash after class `a` hit
  - persisted caches for tried/bad candidates during long runs
  - stale live-state skip support for hashes already safe in qB
- Apply/loop orchestration improvements:
  - apply completion marker output
  - apply-watch and roundloop use completion freshness checks
  - roundloop startup handling for stale stop file
  - default apply mode: if any hash needs fastresume patch, do one offline batch for entire selection

## Remaining Work

- Continue draining current stoppedDL bucket and applying only `a/b/c` rows.
- Investigate persistent `d/e` rows for content absence, naming variance, or wrong-root candidates.
- Build unique payload reconstruction path for confirmed cross-seed reuse cases where class `c` is acceptable but unique root is required.

## Next Ordered Steps

1. Keep `roundloop` running with `--max-candidates 1` for conservative first-pass yield.
2. Review each completed drain summary (`a/b/c/d/e`) and apply completion report.
3. Re-sync bucket periodically with `--prune-absent`.
4. For hashes still `d/e`, inspect candidate notes and run targeted reconstruction.
5. Re-run until stoppedDL converges, then finalize unresolved categories for phase-3.
