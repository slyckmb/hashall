# Project Plan (Canonical)

Last updated: 2026-04-18
Status: active

## Purpose

Unified roadmap + active backlog for development and operations.

## Current Objectives

1. Canonicalize the stash/pool torrent trees:
   - `cross-seed-link -> cross-seed`
   - `orphaned_data -> orphans`
2. Keep RT authoritative and qB mirrored for any affected live torrent metadata.
3. Drain `/pool/data` into canonical stash/pool torrent homes.
4. Apply the stash-vs-pool sibling-group placement rule:
   - hardlink-anchored into `/stash/media` libraries stays on stash
   - otherwise rehome the whole sibling group to pool
5. Audit `~/dev` for path-sensitive code/docs before any rename batches.
6. Keep qB out of the byte-move path.
7. Use one shared attach/repoint constructor for both `REUSE` and `MOVE`.
8. Keep `hashall refresh` healthy and catalog identity stable.
9. Resume `~noHL` only after the pool migration path is operationally proven.
10. Use the `Alien Romulus` sibling group as the next targeted proving lane for:
   - `~noHL` sibling expansion,
   - guarded repair vs rehome decisioning,
   - and de-hitchhiked per-item target-tree construction on `pool-media`.
11. Investigate the incomplete `V for Vendetta` refresh-upgrade root when the active migration/cleanup lane is idle:
   - refresh `20260313-172217` ended `OK`, but root `99/99` for `/pool/media/torrents/seeding/cross-seed/hawke-uno/V.for.Vendetta...` logged `files=0 bytes=0`
   - treat this as a follow-up refresh/catalog/upgrade anomaly, not as proof that refresh itself failed

## 2026-04-18 Canonical Torrent Tree Normalization

Canonical planning doc:
- `docs/operations/TORRENT-TREE-NORMALIZATION-PLAN-2026-04-18.md`

Immediate planning rules:
- do path normalization first, then compare/rebuild inventory, then drain `/pool/data`
- treat `*/media/torrents/orphans` as the canonical orphan location
- keep local dataset orphan moves atomic first; rehome stash orphans outward later
- stop for manual review on conflicting verified copies, mixed hardlink-anchor evidence, incomplete sibling groups, or any unexpected state
- every mutating phase must use:
  - sim code walk
  - dry-run
  - tiny pilot
  - code/fix/code/fix loops before widening

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
- First explicit proving group:
  - `Alien Romulus`
  - current observed scope:
    - `14` sibling candidates
    - `7` marked `~noHL`
    - mixed healthy siblings on `/data/...`, one incomplete `PD` row on `/pool/data/...`
  - expected engineering use:
    - audit whether current rehome/repair code can lift the `~noHL` siblings to `pool-media`
    - prove that each qB item gets its own correct payload tree there
    - keep those trees hardlink-backed where the filesystem allows it

## Migration Resumption Tasking (2026-03-19)

Live state as of 2026-03-19: 41 pool-data torrents remain (was 34 in Mar-13 docs).
Two blockers must be cleared before running a new plan.

Confirmed live split of the 41 qB rows:
- `8` under `/pool/data/media/torrents/seeding`
- `28` under `/pool/data/cross-seed-link`
- `5` under `/pool/data/cross-seed`

Important operator note:
- `bin/migrate-pool-data-to-media.sh` only auto-selects the exact
  `/pool/data/media/torrents/seeding` subset, so a dry-run there currently sees only `8` rows.
- That wrapper also includes `Alien Romulus`, which should stay out of the plain migration lane.
- Therefore it is not the correct "resume the whole remaining 41" command as currently wired.

### Phase 0 — Blocker investigation (operator, read-only)
- [ ] Verify and remove stale `~/.hashall/rehome.lock` (5 days old, pid likely dead)
- [ ] Investigate 640 consecutive qB API failures in cache meta (check `last_error`, confirm live API responds)
- [ ] Run `hashall refresh --verbose` to confirm catalog freshness

### Phase 1 — Fresh plan generation
- [ ] Generate new relocate plan for the full live remainder: `hashall rehome relocate-plan --source-root /pool/data --target-root /pool/media/torrents/seeding --output out/rehome-plan-pool-data-to-media-2026-03-19.json`
- [ ] Audit plan coverage vs. live qB pool-data list (41 hashes expected)
- [ ] Investigate any pool-data torrents not in plan (likely: missing catalog entry, stale reuse, or repair-lane items)
- [ ] Note: 2026-03-18/19 audit fixes (unique-view, bind-mount) may reclassify some previously-BLOCKED candidates

### Phase 2 — Execution
- [ ] Execute migration in conservative batches; gate each on absence of download-like flips, clean qB states, and catalog OK
- [ ] Keep `Alien Romulus` out of the plain migration batches (repair/proving lane, not plain MOVE)
- [ ] Keep the bad `Shining.Girls...` reuse family out of plain migration batches until it is explicitly re-audited
- [ ] Run `hashall rehome followup --cleanup` after each green apply batch

See `docs/operations/RUN-STATE.md` "2026-03-19 Migration Analysis" for shell commands.

---

## Immediate Execution Plan

1. **Phase 0 first** (see Migration Resumption Tasking above): clear stale lock, verify qB, confirm catalog.
2. **Phase 1**: generate fresh relocate plan for the remaining 41 pool-data torrents and audit coverage.
3. **Phase 2**: execute migration in small curated batches.
4. Use the `Alien Romulus` group as the first deliberate `~noHL` rehome/repair proving task once the current cleanup + planner hardening slice is stable.
5. Afterwards, continue the wider `~noHL` lane.
6. When the live migration lane is stable, investigate the incomplete `V for Vendetta` refresh-upgrade root from refresh `20260313-172217`.

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
