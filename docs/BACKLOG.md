# Backlog (Ranked Priorities)

Last updated: 2026-05-19
Status: canonical

Extracted from PLAN.md. For current-sprint work see `docs/SPRINT.md`.

## P0 — Shared Migration Constructor

Refactor migration around two phases: donor acquisition + shared attach/repoint.
- `REUSE`: donor already exists at target.
- `MOVE`: donor is transferred externally first, then handed to shared attach path.
- Both lanes must: build/verify target payload layout → offline fastresume patch qB → restart qB if needed → recheck → verify seed-ready → sync catalog → track cleanup provenance.
- `qB setLocation` must not be used in the mainline path.
- **Status:** implemented in code for REUSE and MOVE; MOVE unproven live.

## P1 — Finish Pool REUSE

Continue remaining REUSE groups in small batches with the offline constructor.
Gates before each apply:
- no `MV`/`moving` reviews
- no download-like flips
- final qB states in `stoppedup`/`stalledup`
- `catalog OK` results
- cleanup provenance cites `/pool/data/media/torrents/seeding/...` not legacy `/pool/data/seeds/...`

Note: planner reports `0 MOVE groups available` at current safety level, but raw inventory
still shows old-path payloads.

## P2 — Make MOVE Safe

MOVE code path is refactored but unproven live. Next gate: controlled live MOVE pilot.
Scale only after: no `MV/moving`, no download-like flip, cleanup messaging correct, planner agrees.

## P3 — Refresh / Identity Stability

- Keep `hashall refresh --verbose` healthy across stash, pool-media, pool-data, spare.
- Preserve stable `fs_uuid`; keep `device_id` limited to runtime metadata.
- Update catalog rows immediately for known migration changes (not waiting on next full refresh).
- Recommended refresh command (after merging fast-refresh branch):
  ```bash
  make db-refresh-fast-gated-parallel
  ```

## P4 — qB Repair / Guard Hardening

- Keep `qb-start-seeding-gradual.sh` focused on resuming `stoppedUP` torrents.
- Guard: halt on newly flipped downloading-like torrents; not on preexisting ones.
- Continue post-apply verification and cache tooling coverage.

## P5 — ~noHL Readiness

After pool migration solid, move `~noHL` payloads from `/data/media/torrents/seeding`
→ `/pool/media/torrents/seeding`.
- First proving group: `Alien Romulus` (14 siblings, 7 marked `~noHL`)
- Reuse donor-acquisition + shared attach architecture.

## Canonical Tree Normalization (deferred)

- `cross-seed-link` → `cross-seed`
- `orphaned_data` → `orphans`
- Do path normalization first, then compare/rebuild inventory, then drain `/pool/data`.
- Treat `*/media/torrents/orphans` as canonical orphan location.
- Do not rename until both clients agree on policy-correct path.

## Deferred Follow-Up

- `V for Vendetta` refresh-upgrade anomaly: refresh ended OK but root logged `files=0 bytes=0`.
  Investigate when active migration lane is idle.
- Orphan GC redesign: current code deletes DB entries only; needs redesign to RELOCATE
  files to `/stash/media/orphaned_data/` holding area before any deletion.
  Use: `HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT=3000 HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION=0.5`

## Active Risks

- `MOVE` is refactored but unproven live; pilot validation is the stop gate.
- Cleanup source path/provenance can drift to legacy `/pool/data/seeds/...` aliases.
- Large batch operations can hide qB/API transient failures; inspect after every run.
