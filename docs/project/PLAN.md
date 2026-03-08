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
5. Resume `~noHL` only after the pool migration path is operationally proven.

## Ranked Priorities

### P0 Shared Migration Constructor

- Refactor migration around two phases: donor acquisition + shared attach/repoint.
- `REUSE`: donor already exists at target.
- `MOVE`: donor is transferred externally first.
- After donor acquisition, both lanes must:
  - build/verify the target payload layout,
  - offline fastresume patch qB metadata,
  - restart qB if needed,
  - recheck and verify seed-ready state,
  - sync catalog state,
  - track cleanup provenance.
- qB `setLocation` must not be used in the mainline path.
- Status:
  - implemented in code for both `REUSE` and `MOVE`.
  - donor transfer still reuses the existing external `rsync` helper before acquisition.

### P1 Finish Pool `REUSE`

- Continue remaining `REUSE` groups in small batches with the offline constructor.
- Gate every apply on:
  - absence of `MV`/`moving` reviews,
  - no download-like flips,
  - final qB states in `stoppedup`/`stalledup`,
  - `catalog OK` results,
  - `cleanup pending` only if the source is intentionally retained.
- Track and fix cleanup provenance so cleanup notices cite `/pool/data/media/torrents/seeding/...` instead of legacy `/pool/data/seeds/...` roots.
- Current planner snapshot:
  - `hashall rehome auto --from pool-data --to pool-media --limit 10` reports `0 MOVE groups available`.
  - At this safety level, the planner considers the `pool-data` phase exhausted, but the raw inventory still shows lots of old-path payloads.

### P2 Make `MOVE` Safe

- `MOVE` now calls the same offline fastresume attach constructor after donor acquisition.
- The code path itself is refactored, but it remains unproven live.
- Next gate: a controlled live `MOVE` pilot.
- Only scale above pilot size once there is no `MV/moving`, no download-like flip, cleanup messaging is correct, and the planner continues to agree.
- Keep the external transfer dumb (`rsync` / sink / filesystem copy) and verify the donor before handing it to the shared attach path.

### P3 Refresh / Identity Stability

- Keep `hashall refresh --verbose` healthy across `stash`, `pool-media`, `pool-data`, and `spare`.
- Preserve stable `fs_uuid` identities and keep `device_id` limited to runtime metadata.
- Ensure catalog rows are updated immediately for known migration changes instead of waiting for another full refresh.

### P4 qB Repair / Guard Hardening

- Keep `qb-start-seeding-gradual.sh` focused on resuming `stoppedUP` torrents.
- Guard strategy: halt on newly flipped downloading-like torrents, not on preexisting ones, and continue monitoring stoppedDL drains and cache-backed watchers.
- Continue post-apply verification and cache tooling coverage.

### P5 `~noHL` Readiness

- After pool migration is solid, reassess moving `~noHL` payloads from `/data/media/torrents/seeding -> /pool/media/torrents/seeding`.
- Reuse the donor-acquisition + shared attach architecture for those runs.

## Immediate Execution Plan

1. Close cleanup-source provenance drift on completed pool-data `REUSE` runs.
2. Confirm the active `stash -> pool-media` `REUSE` pilot (`rehome_runs.id=338`) completes cleanly.
3. If clean, scale `stash -> pool-media` in small `REUSE` batches.
4. Run a live `MOVE` pilot only when the planner surfaces a real donor-acquisition case again.
5. Afterwards, finish `~noHL`.

## Current Operating Rules

- Canonical CLI is `hashall`; use `hashall refresh`, `hashall rehome auto ...`, `hashall rehome config ...`.
- Do not use the removed `rehome` console script.
- Keep one mutating qB workflow at a time.
- Do not start a large batch until the previous smaller batch is fully inspected and clean.

## Active Risks

- `MOVE` has been refactored off qB relocation semantics but remains unproven live; pilot validation is the new stop gate.
- Cleanup source path/provenance can still drift to legacy `/pool/data/seeds/...` aliases.
- Large batch operations can hide qB/API transient failures unless inspected after every run.

## Source Of Truth Docs

- `docs/project/PLAN.md`
- `docs/operations/RUN-STATE.md`
- `docs/handoff.md`
