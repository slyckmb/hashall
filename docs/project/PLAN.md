# Project Plan (Canonical)

Last updated: 2026-03-07
Status: active

## Purpose

Unified roadmap + active backlog for development and operations.

## Current Objectives

1. Finish `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`.
2. Keep qB out of the byte-move path.
3. Use one shared attach/repoint constructor for both `REUSE` and `MOVE`.
4. Keep `hashall refresh` healthy and catalog identity stable.
5. Resume `~noHL` only after pool migration is operationally solid.

## Ranked Priorities

### P0 Shared Migration Constructor

- Refactor migration around two phases:
  - donor acquisition
  - shared attach/repoint
- `REUSE`:
  - donor already exists at target
- `MOVE`:
  - donor is transferred externally first
- After donor acquisition, both lanes must use the same constructor:
  - build/verify target payload
  - offline fastresume patch
  - qB restart if needed
  - recheck
  - verify seed-ready
  - catalog sync
  - cleanup tracking
- qB `setLocation` must not be used in the mainline path.
- Status:
  - implemented in code for both `REUSE` and `MOVE`
  - current transfer implementation is the existing external `rsync` helper behind donor acquisition

### P1 Finish Pool `REUSE`

- Continue the remaining `REUSE` groups from `pool-data` to `pool-media` in small batches.
- Gate every apply batch on:
  - no `MV/moving`
  - no download-like flips
  - final state `stoppedup` or `stalledup`
  - `catalog OK`
  - `cleanup pending` if source retained
- Track and fix cleanup provenance drift when cleanup paths resolve to legacy `/pool/data/seeds/...` instead of `/pool/data/media/torrents/seeding/...`.
- Current planner state:
  - `hashall rehome auto --from pool-data --to pool-media --limit 10`
  - reports `0 MOVE groups available`
  - pool-data phase is effectively exhausted at planner level

### P2 Make `MOVE` Safe

- `MOVE` now uses the same offline fastresume attach constructor as `REUSE` after donor acquisition.
- Keep external transfer separate and dumb:
  - `rsync` / sink / filesystem copy only
  - verify donor at target
  - then attach torrents
- Do not allow qB to perform payload moves.
- Next gate:
  - one live `MOVE` pilot
  - then small-batch scaling only if there is no `MV/moving`, no download-like flip, and clean source cleanup semantics

### P3 Refresh / Identity Stability

- Keep `hashall refresh --verbose` healthy across:
  - `stash`
  - `pool-media`
  - `pool-data`
  - `spare`
- Preserve stable `fs_uuid` identity.
- Keep `device_id` limited to runtime/current-mount concerns only.
- Ensure immediate catalog sync for known migration changes instead of relying on later full refresh for basic state correction.

### P4 qB Repair / Guard Hardening

- Keep `qb-start-seeding-gradual.sh` focused on resuming `stoppedUP`.
- Maintain guard behavior:
  - halt on newly flipped downloading-like torrents
  - do not halt on preexisting downloading-like states
- Continue hardening:
  - stoppedDL drain/apply
  - cache-backed watch tooling
  - post-apply verification

### P5 `~noHL` Readiness

- After pool migration is solid, reassess `~noHL` from `/data/media/torrents/seeding -> /pool/media/torrents/seeding`.
- Reuse the same donor-acquisition + shared attach architecture.
- Current next gate:
  - live `stash -> pool-media` `REUSE` pilot is running
  - do not scale `~noHL` until that pilot completes cleanly

## Immediate Execution Plan

1. Close the remaining cleanup-source provenance drift on completed pool-data `REUSE` runs.
2. Confirm the active `stash -> pool-media` `REUSE` pilot completes cleanly.
3. If clean, scale `stash -> pool-media` in small batches.
4. Run a live `MOVE` pilot only if/when the planner surfaces a real donor-acquisition case again.
5. Then finish `~noHL`.

## Current Operating Rules

- Canonical CLI is `hashall`.
- Use:
  - `hashall refresh --verbose`
  - `hashall rehome auto ...`
  - `hashall rehome config ...`
- Do not use the removed `rehome` console script.
- One mutating qB workflow at a time.
- No large batch apply until the preceding smaller batch is clean.

## Active Risks

- `MOVE` has been refactored off qB relocation semantics, but it is still unproven live.
- Cleanup source path/provenance can still drift to old aliases.
- Large batch operations can still hide qB/API transient failures if not inspected after each batch.

## Source Of Truth Docs

- `docs/project/PLAN.md`
- `docs/operations/RUN-STATE.md`
- `docs/handoff.md`
