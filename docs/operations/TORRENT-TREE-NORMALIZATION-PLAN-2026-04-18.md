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

## 2026-04-18 Audit Findings

### Active pre-rename blockers in other repos

Docker repo:
- `gluetun_qbit/rtorrent_vpn/rt_sync_imported_path.sh`
  - mirrors qB imported-category paths into RT under `/data/media/torrents/seeding/*`
  - does not hardcode `cross-seed-link` or `orphaned_data`, but it is part of RT path authority and must be considered during live path changes
- `gluetun_qbit/rtorrent_vpn/rt_set_label_path.sh`
  - assigns RT label-based save paths under `/data/media/torrents/seeding/*`
  - same note: not a legacy-name blocker, but part of the RT path-setting surface
- `gluetun_qbit/rtorrent_vpn/rt_repair_legacy_path.sh`
  - legacy RT repair helper keyed to `/data/media/torrents/seeding/*`
- `qbit_manage/config.yml`
  - active `orphaned_dir: /data/media/torrents/seeding/orphaned_data`
- `qbit_manage/config-seeds.yml`
  - active `orphaned_dir: /pool/data/orphaned_data`
- `qbit_manage/bin/promote_recycle_to_seeds.sh`
  - active `ORPHANED_SRC_ROOT=/data/media/torrents/seeding/orphaned_data`
- `qbit_manage/bin/check_pool_orphans.sh`
  - still documents and targets `/pool/data/orphaned_data`
- `gluetun_qbit/qbittorrent_vpn/bin/qb-to-rt-migrate.py`
  - still carries `legacy_root = f\"{root}/cross-seed-link\"`

Other active repos under `~/dev`:
- `work/hiker/docker/cross-seed-v6/config.js`
  - still defaults `linkCategory` / `linkDir` to `cross-seed-link`
- `work/hiker/docker/qbit_manage/config.yml`
  - still references both `cross-seed-link` and `orphaned_data`
- `tools/traktor/config/tracker-registry.yml` and `tools/traktor/bin/tracker-ctl.sh`
  - still encode the active seeding root contract and must be reviewed before any broad root normalization

### Classification

Must change before `orphaned_data -> orphans`:
- `src/hashall/cli.py`
  - orphan-sweep help/output still says `orphaned_data`
- `src/hashall/orphan_sweep.py`
  - destination constant and legacy-name handling still target `/pool/media/torrents/orphaned_data`
- `src/hashall/content_inventory.py`
  - pool-data root classification still treats `orphaned_data` as the canonical non-qB root
- Docker repo `qbit_manage` configs/scripts listed above
- Hiker `qbit_manage` config

Must change before `cross-seed-link -> cross-seed`:
- `gluetun_qbit/qbittorrent_vpn/bin/qb-to-rt-migrate.py`
- `work/hiker/docker/cross-seed-v6/config.js`
- active hashall docs/tests that still frame `cross-seed-link` as a normal live root instead of an explicit legacy lane

Safe follow-up after live rename batches:
- historical handoffs, archived ops notes, and older forensic docs that should retain period-accurate path history
- broad usage docs that are not part of live automation or live path-setting

## 2026-04-18 Live Scope Snapshot

Legacy roots currently present on disk:
- stash
  - `/stash/media/torrents/seeding/cross-seed`
  - `/stash/media/torrents/seeding/cross-seed-link`
  - `/stash/media/torrents/orphaned_data`
  - `/stash/media/torrents/seeding/orphaned_data`
- pool-media
  - `/pool/media/torrents/seeding/cross-seed`
  - `/pool/media/torrents/seeding/cross-seed-link`
  - `/pool/media/torrents/orphaned_data`
- pool-data
  - `/pool/data/cross-seed`
  - `/pool/data/cross-seed-link`
  - `/pool/data/orphaned_data`
  - `/pool/data/seeds/cross-seed`

Live client rows still on legacy names:
- `cross-seed-link`
  - RT: `24`
  - qB: `24`
  - placement split:
    - `22` under `/pool/media/...`
    - `2` under `/data/media/...` (stash bind mount)
- `orphaned_data`
  - RT: `1`
  - qB: `1`
  - current live row is under `/pool/media/torrents/orphaned_data/...`

## 2026-04-18 Sim Walk / Dry-Run Findings

Tooling shape:
- `hashall rt repoint`
  - valid dry-run/apply surface for the RT side
- `bin/qb-zfs-relocate.py plan`
  - valid dry-run planner for the qB side of a selected hash
- `bin/qb-zfs-relocate.py validate`
  - not a good fit for same-filesystem rename preflight because it expects a copied destination payload before validation

Important path-shape nuance:
- qB uses the tracker save root for `save_path`
  - example: `/pool/media/torrents/seeding/cross-seed-link/FileList.io`
- RT live state may store the full content directory instead
  - example: `/pool/media/torrents/seeding/cross-seed-link/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
- Any dual-client normalization helper must derive RT and qB targets differently for the same hash

Dry-run evidence from the first concrete candidate:
- candidate hash:
  - `b95856e0a29bf045e76a95f4ea3cacf6e4b02add`
- RT dry-run:
  - `hashall rt repoint` works as expected, but the correct RT target is the full content-directory replacement, not the qB save root
- qB dry-run:
  - `bin/qb-zfs-relocate.py plan` built a clean one-row manifest for the same hash
  - `validate` then failed with:
    - `destination_payload_missing`
    - `offline_verify_failed`
  - this is expected for a same-FS rename plan and is a tooling-fit issue, not evidence that the mapping is wrong

Operational findings:
- both live clients were down when the first dry-run started:
  - `qbittorrent_vpn` exited
  - `rtorrent_vpn` exited
- `docker start` failed because both containers still pointed at a dead `gluetun` network namespace
- recovered by recreating them from the Docker repo compose file:
  - `docker compose -f /home/michael/dev/sys/docker/gluetun_qbit/docker-compose.yml up -d qbittorrent_vpn rtorrent_vpn`
- after recreate:
  - qB WebUI login succeeded
  - RT RPC answered normally

## 2026-04-18 One-Hash Helper + Pilot Outcome

Implemented in-repo helper:
- `python -m hashall.cli payload normalize-cross-seed-link --hash <HASH>`
- `--apply` executes a one-hash same-filesystem qB + RT normalization

What the helper now does:
- plans qB and RT targets separately
- requires a clean same-filesystem plan before apply
- pauses qB, moves qB with `setLocation`, repoints RT, then verifies both sides
- keeps qB stopped if the torrent was already stopped
- uses RT torrent metadata to distinguish:
  - the expected RT runtime directory
  - the normalized `d.directory.set` argument

Pilot hash:
- `b95856e0a29bf045e76a95f4ea3cacf6e4b02add`

Pilot result:
- qB final save path:
  - `/pool/media/torrents/seeding/cross-seed/FileList.io`
- RT final directory:
  - `/pool/media/torrents/seeding/cross-seed/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
- RT recovered from the failed first-pilot `error` state and settled back to `stalledUP`
- live legacy-name counts dropped by one on both sides:
  - RT `cross-seed-link`: `27 -> 26`
  - qB `cross-seed-link`: `27 -> 26`

Additional successful pilots:
- `55a3df42dcf14d250117d811b52dca658fd05f73`
  - multi-file / RT content-directory case under `DigitalCore (API)`
  - final qB save path:
    - `/pool/media/torrents/seeding/cross-seed/DigitalCore (API)`
  - final RT directory:
    - `/pool/media/torrents/seeding/cross-seed/DigitalCore (API)/Elemental.2023.1080p.BluRay.x265.10bit.DTS-HD.MA.7.1-UnKn0wnTORRENTLEECH`
- `8779246eebcf9135f272d24cdff643887700ffe1`
  - single-file / RT root-directory case under `Darkpeers (API)`
  - final qB save path:
    - `/pool/media/torrents/seeding/cross-seed/Darkpeers (API)`
  - final RT directory:
    - `/pool/media/torrents/seeding/cross-seed/Darkpeers (API)`

Legacy-name counts after 3 successful pilots total:
- RT `cross-seed-link`: `27 -> 24`
- qB `cross-seed-link`: `27 -> 24`

Operator wrapper now available:
- `scripts/pilot-normalization.sh`
- wrapper behavior:
  - no unrelated orphan cleanup or broad mutation side effects
  - dry-run/list by default
  - only `/pool/media` rows with stopped qB state are treated as safe apply candidates
  - apply is still one-hash-at-a-time and delegates the mutation to `payload normalize-cross-seed-link`
  - watch-only mode works for already-selected hashes
  - each run prints post-check state, residue classification, and remaining live legacy counts

First wrapper-driven live pilot:
- `5bf579e7c4c98daeb66c87da1f6068512f35c3cd`
  - qB final save path:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia`
  - RT final directory:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
  - wrapper watch hit `ambiguous_needs_review` because RT stayed in `checking` beyond the 120s watch budget
  - immediate post-watch verification still showed both clients on the canonical path

Legacy-name counts after the wrapper pilot:
- RT `cross-seed-link`: `27 -> 21`
- qB `cross-seed-link`: `27 -> 21`

Logic bugs rooted out during the pilot loop:
- qB wait/retry originally treated "torrent row still exists" as success even when the target path never matched
- RT apply originally used the wrong path shape for multi-file torrents, which produced a doubled runtime directory on the first failed pilot
- RT verification now accepts the aligned runtime form after repoint instead of assuming only one exact string shape
- RT timeout handling now treats post-mutation timeouts as ambiguous:
  - wait for RT verification before deciding failure
  - do not immediately roll qB back on RT timeout

Operational lesson from the `DigitalCore (API)` retry:
- RT SCGI / XMLRPC can stall long enough to trip the 20s request timeout even when the repoint eventually lands
- immediate qB rollback after that timeout is unsafe because it can create temporary split state
- the helper now waits through that ambiguity and only proceeds after RT verification recovers

Important residue note:
- the failed first pilot left a stale on-disk legacy directory at:
  - `/pool/media/torrents/seeding/cross-seed-link/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
- current shape:
  - it contains only a nested same-name directory, not the live payload tree
- current client state:
  - qB and RT both point at the canonical `cross-seed` path, not this legacy residue
- do not silently delete this residue as part of helper apply yet
  - carry it as an explicit cleanup decision / follow-up lane

Current blocker to widening the batch:
- the one-hash helper is now good enough for additional one-hash pilots
- broad rename batching is still blocked on:
  - cross-repo legacy-name consumers in Docker/Hiker/Traktor configs
  - explicit cleanup policy for stale legacy residue created by failed pilot attempts
- do not use the orphan rename as the first broad live batch:
  - too much active code/config still assumes `orphaned_data`

## 2026-04-19 Next Code Plan

Two new code issues are now explicitly in scope.

### Issue 1: normalization success is weaker than desired

Current state:
- `src/hashall/path_normalize.py` proves qB path convergence and RT path alignment
- helper success can still occur while RT is in `checking*`
- wrapper watch can surface that nuance, but the helper-level result does not model it strongly enough

Planned change:
1. add explicit normalization result semantics:
   - `path_converged`
   - `verifying`
   - `verified`
   - `ambiguous_needs_review`
   - `partial_state`
2. add shared RT/qB verification-state predicates in Python
3. require stronger helper-level post-apply verification:
   - qB canonical path match
   - RT canonical path match
   - RT leaves `checking*` before strongest success is returned
4. optionally support stricter recheck-complete gating as a higher-assurance mode
5. keep the wrapper aligned to the helper contract rather than inventing its own success rules

Execution order for issue 1:
1. sim/code walkthrough of helper return paths and current success conditions
2. dry-run against current canonical and legacy hashes
3. tiny pilot on one stopped `/pool/media` candidate
4. code/fix/test loop until helper status semantics are boring and deterministic

### Issue 2: legacy hitchhiker groups need first-class handling

Current state:
- repo terminology and requirements already recognize hitchhikers and `_rehome-unique/<hash>/...`
- rehome/link tooling already has inode-aware building blocks
- there is not yet a focused hashall lane that audits and de-hitchhikes existing legacy groups on demand

Planned change:
1. add explicit hitchhiker audit logic:
   - detect N->1 shared payload trees
   - measure inode/file overlap between hashes
   - classify safe shared-byte reuse vs incorrect shared payload-tree layout
2. add a dedicated de-hitchhike apply lane:
   - build per-hash unique payload trees using hardlinks where possible
   - route into `_rehome-unique/<hash>/...` where canonical tracker roots would collide
   - repoint affected qB/RT items to those unique payload roots
3. add strict stop conditions:
   - partial/inconsistent inode overlap
   - conflicting hashes at the same relative path
   - cross-filesystem hardlink impossibility
   - incomplete/partially verified torrents
   - ambiguous owner/donor relationships

Execution order for issue 2:
1. sim walkthrough on known inode-sharing / shared-root families
2. dry-run audit output only
3. tiny pilot split on one safe same-filesystem hitchhiker family
4. verify each affected hash gets its own payload tree while still reusing bytes via hardlinks where intended
5. only then widen to more groups

Sequencing decision:
- implement issue 1 first, because it hardens the active normalization lane already in use
- then implement hitchhiker audit
- then implement hitchhiker split/apply

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

## 2026-04-19 Multi-Pass Loop Findings

- Sim/code loop:
  - `payload normalize-cross-seed-link` now returns an explicit `outcome` field.
  - current modeled outcomes are:
    - `verified`
    - `verifying`
- Dry-run loop fixes landed:
  - qB read-only planning no longer crashes when login/reset happens before live `torrents/info`.
  - RT planning now prefers the shared RT cache before live XMLRPC.
  - planning now degrades to explicit issues instead of tracebacks:
    - `qb_info_unavailable:...`
    - `rt_status_unavailable:...`
  - empty qB save/content paths no longer collapse into the worktree cwd for RT target derivation.
- Wrapper loop fixes landed:
  - `scripts/pilot-normalization.sh` candidate classification now falls back to RT path scope when qB path fields are blank.
- Current operational blocker after the dry-run loops:
  - qB login was still resetting during direct helper planning.
  - RT shared cache reported `freshness=stale_error`.
  - wrapper dry-run stayed safe and refused auto-pick when no candidate met the stopped `/pool/media` policy with usable qB metadata.
- Current result:
  - sim loop: clean
  - dry-run loop: clean, no tracebacks
  - stricter outcome alignment now landed:
    - helper-level apply results can express:
      - `path_converged`
      - `verifying`
      - `verified`
      - `ambiguous_needs_review`
      - `partial_state`
    - wrapper now consumes helper outcomes and prints helper error/outcome after apply
    - wrapper now fails closed for `--pick-safe` / `--apply` when RT cache freshness is `stale_error`
    - wrapper now surfaces degraded plan issues before stopped-state gating
  - live pilot loop: not executed in this pass because the repaired wrapper correctly blocked auto-pick/apply under current controller/cache conditions
