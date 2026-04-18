# Torrent Tree Normalization Plan

Last updated: 2026-04-18
Status: planning active

## Purpose

This doc is the canonical plan for standardizing the stash/pool torrent trees, draining `/pool/data`, and keeping RT/qB path metadata aligned while the tree layout changes.

Source operator answers captured in:
- `docs/hashall-answers-0418-1121.md`
- `docs/hashall-answers-3-4-10.md`
- `docs/hashall-answers-to-4questions.md`

## Settled Policy

### Target steady-state layout

Stash:
- `/stash/media/torrents/seeding/cross-seed`
- `/stash/media/torrents/orphans`

Pool:
- `/pool/media/torrents/seeding/cross-seed`
- `/pool/media/torrents/orphans`

Steady-state rules:
- `cross-seed-link` is removed in favor of `cross-seed`
- `orphaned_data` is removed in favor of `orphans`
- `orphans` live under `*/media/torrents/orphans`, not under `*/media/torrents/seeding/orphans`
- `/pool/data` is drained of torrent-related payloads

### Placement rule

For active seeding data:
- if any file in a payload has a hardlink into `/stash/media` consumer libraries, keep the whole sibling payload group on stash
- otherwise, rehome the whole sibling payload group to pool

### Sibling payload group

Placement decisions operate on the broader hashall sibling-group concept:
- non-duplicate payloads that mostly share inodes on the same filesystem
- or could share inodes if rehomed onto the same filesystem

This is broader than exact `payload_hash` equality and is the placement unit for stash-vs-pool decisions.

### Client authority

- RT is the operational authority
- qB remains online as a silent mirror and must stay in sync for any affected torrent that exists in qB
- path changes in one client require corresponding metadata updates in the other client

### Orphans

- each dataset keeps its own local `torrents/orphans` tree first
- later, stash orphans may be rehomed to pool and/or spare as space allows
- orphan moves should stay atomic and local to the dataset during the first pass

### Manual-review stop conditions

Auto-stop and require human review when:
- the same path/name exists with different file hashes
- stash and pool both have fully verified copies but placement signals disagree
- hardlink-anchor evidence is mixed or unclear
- a sibling payload group is incomplete or partially verified
- any other unexpected state appears during execution

## Cross-Repo Impact

Before any rename or save-path mutation:
- audit `~/dev` for references to `cross-seed-link`, `orphaned_data`, `torrents/orphans`, and canonical stash/pool torrent roots
- split findings into:
  - changes in this repo
  - follow-up changes required in other repos or docs under `~/dev`
- do not treat the filesystem rename as complete until path-sensitive code/docs are updated or explicitly queued as follow-up

## Phase Order

This is the least-friction order with the lowest churn:

1. Canonicalize names first
   - normalize `cross-seed-link -> cross-seed`
   - normalize `orphaned_data -> orphans`
   - update RT/qB save paths for affected live items
   - do not collapse duplicates in the same phase

2. Rebuild comparison inventory after normalization
   - reduce namespace noise before stash-vs-pool review

3. Drain `/pool/data`
   - route torrent-related payloads into canonical stash/pool homes
   - free headroom on `/pool`

4. Apply stash-vs-pool sibling-group placement rules
   - stash if hardlink-anchored into `/stash/media`
   - pool otherwise

5. Consolidate local dataset orphans
   - keep `*/torrents/orphans` local first
   - later rehome stash orphans outward as space allows

6. Review remaining stash/pool duplicates
   - do this only after names and `/pool/data` residue are mostly settled

## Execution Pattern

Every mutating phase should follow the same loop:

1. Sim code walk
   - inspect the exact code paths, planner logic, and metadata updates involved
   - identify logic traps before touching data

2. Dry-run
   - preview filesystem changes
   - preview RT/qB path mutations
   - preview stale code/doc path references where applicable

3. Tiny pilot
   - execute the smallest safe batch
   - prefer one family or one narrow path lane at a time

4. Code/fix loop
   - if the pilot exposes a logic error or missed edge case, fix it immediately
   - rerun the same dry-run and tiny pilot before widening

5. Widen only after the pilot becomes boring
   - no blind loops
   - reconcile after each batch

## Progress Tracker

Completed:
- Operator policy answers were captured and reconciled into this plan.
- Canonical docs were updated to carry this policy forward:
  - `docs/REQUIREMENTS.md`
  - `docs/project/PLAN.md`
  - `docs/operations/RUN-STATE.md`
  - `docs/next-agent.md`
- `payload orphan-sweep` gained staged controls:
  - `--order`
  - `--reserve-gib`
  - `--dataset`
- The `payload orphan-sweep` empty-dir `--limit` bug was fixed and regression-tested.
- A live `pool-data` orphan-sweep pilot removed current empty seeding dirs under `/pool/data/media/torrents/seeding`.
- The current worktree state after those doc/code updates is clean, so the next thread can start directly on the audit lane.

Pending:
- Audit `~/dev` for path-sensitive references before any tree normalization batch.
- Document the exact canonical stash/pool torrent layout in code-facing requirements.
- Plan the first rename-only normalization batch for `cross-seed-link` and `orphaned_data`.
- Rebuild inventory after normalization.
- Drain `/pool/data` in small verified batches.
- Apply stash-vs-pool sibling-group placement decisions.
- Rehome stash orphans outward as space allows.

## Immediate Next Steps

1. Audit `~/dev` for old path references and classify what must change in-repo vs elsewhere.
2. Map all current `cross-seed-link` and `orphaned_data` roots on stash and pool.
3. Sim the code and metadata flow for a rename-only batch.
4. Dry-run the first smallest normalization slice.
5. Pilot exactly one small rename/update batch.

## Thread Resume Note

If a future thread resumes from this plan:
- start with the `~/dev` path-reference audit
- do not mutate stash/pool tree names until that audit is classified
- treat the first rename batch as a path-normalization pilot only, not a dedupe/consolidation batch
