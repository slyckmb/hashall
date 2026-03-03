# Hashall Handoff (Living)

Last updated: 2026-02-28

## Scope

This handoff covers the stoppedDL recovery campaign using the bucket/drain/apply pipeline.

## Status

- Active toolchain is now:
  - `qb-stoppeddl-bucket.py` (sync + `.torrent` export)
  - `qb-stoppeddl-drain.py` (candidate ranking + libtorrent verify + grading, `0.1.12`)
  - `qb-stoppeddl-apply.py` (setLocation/recheck + optional fastresume batch patch)
  - `qb-stoppeddl-apply-watch.sh` (daemon/loop apply on completed drains)
  - `qb-stoppeddl-roundloop.sh` (bucket -> drain -> apply -> wait-checking loop, `0.1.5`)
- qB API helper now supports `.torrent` export via `QBitTorrent.export_torrent_file()`.
- Gradual seeding watchdog was patched to avoid false halts from `checkingDL`.
- Hash ignore whitelist support was added across bucket/drain/apply/roundloop and gradual seeding watchdog.
- Payload-group repair script now falls back from qB `/torrents/resume` to `/torrents/start` for compatibility.

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
  - roundloop propagates stop-file to drain for mid-pass interruption
  - default apply mode: if any hash needs fastresume patch, do one offline batch for entire selection
- Stop handling improvements:
  - drain checks stop-file before each hash and candidate
  - drain can terminate in-flight verifier subprocess on stop request
  - drain writes `progress_reason=stop_file_exists` when interrupted
- Ignore whitelist behavior:
  - hash exact/prefix matching (e.g. `102b7bf38155`)
  - default ignore file for stoppedDL flow: `/tmp/qb-stoppeddl-bucket-live/download-whitelist-hashes.txt`
  - ignored hashes are excluded from remediation selection and skipped in summary counters

## Remaining Work

- Continue draining current stoppedDL bucket and applying only `a/b/c` rows.
- Investigate persistent `d/e` rows for content absence, naming variance, or wrong-root candidates.
- Build unique payload reconstruction path for confirmed cross-seed reuse cases where class `c` is acceptable but unique root is required.

## Next Ordered Steps

1. Keep `roundloop` running with `--max-candidates 1` for conservative first-pass yield.
2. Review each completed drain summary (`a/b/c/d/e`) and apply completion report.
3. Re-sync bucket periodically with `--prune-absent`.
4. Maintain ignore whitelist for known intentional downloaders before loop runs.
5. For hashes still `d/e`, inspect candidate notes and run targeted reconstruction.
6. Re-run until stoppedDL converges, then finalize unresolved categories for phase-3.
