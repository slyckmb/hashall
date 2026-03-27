# RT/qB Drift Cleanup Handoff

Last updated: 2026-03-27

## Purpose

This handoff covers the current rtorrent vs qBittorrent save-path drift cleanup and the
required operating rule change:

- treat seeded data as dual-client sensitive by default
- do not assume qB-only unless that has been explicitly proven
- future migration, repair, and reclaim code must account for both clients

## Current Sweep Result

Source report:
- `out/rt-qb-savepath-drift-refined-2026-03-27.json`

Action-plan report:
- `out/rt-qb-savepath-drift-action-plan-2026-03-27.json`

Current totals:
- `4522` hashes found in both clients
- `55` hashes with real path drift after normalizing common single-file wrapper differences

Normalization used for "aligned":
- `rt_directory == qb_save_path`
- or `rt_directory == qb_content_path`
- or `rt_directory == dirname(qb_content_path)`

Important migration conclusion:
- none of the still-remaining `/pool/data` migration items are currently drifted between rt and qB
- the remaining `pool/data -> pool/media` blocker is space / carve-out handling, not rt-vs-qB drift

## Default Rule Going Forward

Assume dual-client sensitivity by default.

That means:
- a seeded path may be owned by both qB and rt even if only one client is currently under review
- path changes are not complete until both clients agree on the active location
- reclaim logic must protect paths still needed by either client
- migration completion should not be inferred from qB state alone

## Drift Buckets

### 1. Fix Now: qB Already On `/pool/media`, rt Still Elsewhere

These are the highest-priority cleanup items because migration already moved qB, but rt still points
at an old location.

Representative items:
- `2fd37137...` `Subservience...`
- `323291dd...` `How.Its.Made.S25...`
- `3e82f6f7...` `UEFA...`
- `5c877f46...` `Hidden Figures...`
- `64b13ed5...` `Mighty Monsterwheelies...`
- `7654bd1c...` `Nobody Wants This...`
- `9e40638a...` `Black Mirror: Bandersnatch...`
- `e04e5247...` `Beetlejuice...`
- `e877206f...` `The Edge of Sleep...`
- `fad3310d...` `The Last Stop in Yuma County...`

Count:
- `19`

Required action:
- repoint rt to the qB `/pool/media` path
- verify rt sees the moved data cleanly
- only then consider the old `/pool/data` side fully retired

### 2. Repair Lane, Not Main Migration Blocker

These are mostly broken or incomplete qB rows that also still point rt at old download roots.
Let the repair lane own them unless they become directly relevant to a migration batch.

Representative items:
- `20555f70...` `Bottle Shock...`
- `5c86280a...` `Spider-Man...`
- `5feb771c...` `Spider-Man...`
- `c8f01321...` `The Matrix Reloaded...`
- `e2ae560a...` `River Monsters S06...`

Count:
- `11`

Required action:
- do not block broad `pool/data -> pool/media` migration on these
- repair or normalize them in the docker/repair lane

### 3. Normalize Old rt Download Paths

These are mostly healthy-enough items where qB is on a seeded path but rt still points to
`/downloads/complete/...`.

Representative items:
- `1309f4f2...` `One Day...`
- `15b92c2b...` `12 Monkeys...`
- `9a731a54...` `Dexter S01...`

Count:
- `6`

Required action:
- normalize rt paths after the urgent migration-adjacent drift is cleaned up

### 4. Normalize Generic rt Staging Paths

These items still point rt at generic staging under `/data/media/torrents/seeding/rtorrent/...`
while qB points at a more specific seeded root.

Representative items:
- `6d99af9f...` `Twin Peaks S03...`
- `c4acb67f...` `How.Its.Made.S32...`
- `51cc7074...` `Deadpool and Wolverine...`
- several books and audiobooks

Count:
- `17`

Required action:
- lower priority than the `qB on /pool/media, rt still elsewhere` bucket
- normalize when doing broader rt path cleanup

### 5. Investigate Shape-Specific Drift

These are path-shape mismatches that should be reviewed manually before bulk normalization.

Items:
- `1a066555...` `Top Gun 1986...`
- `29e2b889...` `Vigen Guroian`

Count:
- `2`

Required action:
- inspect actual file/tree layout in both clients
- do not fold them into an automatic repoint pass without review

## Cleanup Execution Plan

### Phase A: Fix The 19 Migration-Adjacent rt Drifts

Goal:
- make rt agree with qB for items already moved to `/pool/media`

Steps:
1. work from `out/rt-qb-savepath-drift-action-plan-2026-03-27.json`
2. take only rows where `action_bucket == fix_now_repoint_rt_to_pool_media`
3. for each row:
   - confirm qB content exists at the `/pool/media` target
   - confirm rt still points at the older non-`/pool/media` path
   - repoint rt to the qB path
   - verify rt now resolves the same content root
4. after the whole tranche:
   - re-run the drift sweep
   - expect this bucket to drop toward zero

Suggested completion criteria:
- rt and qB paths agree for all 19 rows
- no item in this bucket regresses to missing-content state

### Phase B: Keep Repair-Lane Rows Out Of Main Migration

Goal:
- do not let broken qB rows dominate the `pool/data -> pool/media` critical path

Steps:
1. leave `repair_lane_not_migration_blocker` rows to the docker/repair workflow
2. keep them excluded from plain migration batches
3. only pull one back into mainline work if a migration family directly depends on it

### Phase C: Normalize The Remaining rt Legacy Paths

Goal:
- clean up historical rt path drift once migration-adjacent items are stable

Order:
1. `normalize_rt_old_download_path`
2. `normalize_rt_generic_staging_path`
3. `investigate_shape_specific_drift`

## Code Changes Required Going Forward

This is the important design instruction.

### 1. Treat Both Clients As First-Class Path Owners

Future migration/repair code must not treat qB as the sole runtime authority.

Required behavior:
- path validation should consider both qB and rt
- migration completion should mean both clients agree on the active location
- cleanup safety checks should protect roots still used by rt even if qB has moved on

### 2. Repoint Planning Must Become Dual-Client Aware

When qB is already moved:
- planner should detect whether rt still points at the old root
- that should produce a follow-up action, not a false sense of completion

Recommended change:
- add an rt-aware audit/planner step after successful qB-side migration apply
- emit rows such as:
  - `qb_moved_rt_not_moved`
  - `qb_and_rt_aligned`
  - `rt_only_drift`

### 3. Reclaim Logic Must Protect rt-Owned Roots

Current reclaim protection already avoids exact live qB payload roots.
That is no longer enough.

Required behavior:
- treat paths still referenced by rt as protected by default
- do not classify them as purge candidates just because qB has moved away

Recommended change:
- extend reclaim-report protection to include live rt session roots

### 4. Reports And Runbooks Must Stop Assuming qB-Only

Required doc/UX change:
- operator-facing status should say whether a path is:
  - qB only
  - rt only
  - dual-client aligned
  - dual-client drifted

### 5. Verification Must Include Both Clients

Any future migration “success” check should verify:
- qB runtime path
- rt runtime/session path
- on-disk content exists at the intended keep location

## Immediate Recommended Next Move

1. execute Phase A for the `19` migration-adjacent drift rows
2. re-run the drift sweep
3. then return to the remaining `pool/data -> pool/media` carve-out work

The main point is:
- the remaining plain migration lane is not blocked by current rt/qB drift on the still-unmoved
  `/pool/data` items
- but completed migration work is not truly complete until rt is repointed too
