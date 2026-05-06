# Operational Run State

Last updated: 2026-05-06

## 2026-05-06 Phase 0 Baseline

Read-only baseline from the `cr/hashall-20260505-112759-codex` worktree:

- `~/.hashall/refresh.lock` was stale metadata only (`pid=3969561`, process not running) and was removed; `hashall rehome refresh-status` now reports `idle`.
- qB cache source of truth is the silo-owned cache:
  - `~/.cache/silo-qb/torrents-info.json`
  - `~/.cache/silo-qb/torrents-info.meta.json`
  - latest observed cache: `5200` items, qB `v5.1.4`, `consecutive_failures=0`
- RT cache source of truth is the silo-owned cache:
  - `~/.cache/silo-rt/torrents.json`
  - `~/.cache/silo-rt/torrents.meta.json`
  - latest observed cache: `5202` items, `consecutive_failures=0`
- Live cache counts now show the path-normalization live rows are clear:
  - qB `cross-seed-link`: `0`
  - RT `cross-seed-link`: `0`
  - qB `orphaned_data`: `0`
  - RT `orphaned_data`: `0`
  - qB paths under `/pool/data`: `0`
  - RT paths under `/pool/data`: `0`
- `scripts/pilot-normalization.sh --list` found no current safe normalization candidates.
- Capacity is no longer the immediate migration blocker:
  - `/pool/data`: about `3.6T` available
  - `/pool/media`: about `3.6T` available
- The five current qB `stoppedDL` rows are treated as waiting-for-seed-peers, not as the active repair lane:
  - `245f2bce6afaf96b0a48ad216366c4281fdd864f`
  - `e36553b12dc118d8c52575a1d6711532882ae1c3`
  - `127c38342cfedaf4016b8079be13c5f7883b9cfe`
  - `5caca88d29e64de495a47b53a466f7cadcb3ce02`
  - `96d896ca35f42d93e4a4bdee92e8ac90adc34b54`
- Non-blocking cache-daemon hygiene item:
  - `~/.cache/silo-qb/daemon.pid` points at a live silo daemon.
  - `torrents-info.meta.json` still reported an older non-running `daemon_pid`.
  - The cache itself is fresh, so do not restart the shared daemon while active leases exist; handle this in the silo/cache hygiene lane.

Interpretation:
- Treat older notes that cite live `cross-seed-link`, live `orphaned_data`, `/pool/data` qB/RT rows, or zero-capacity blockers as historical unless a new live read contradicts this baseline.
- Next best work lane is code/doc/cache cleanup, not another live path-normalization pilot.

## 2026-05-06 Phase 2B Save-Path Drift Policy

`client-drift audit` now watches same-hash qB/RT save-path drift as a first-class drift side:

- read-only live audit against silo caches:
  - qB rows: `5202`
  - RT rows: `5202`
  - common hashes: `5202`
  - qB-only: `0`
  - RT-only: `0`
  - same-hash path drift: `13`
- default audit behavior is fail-closed:
  - anchor scanning is disabled by default (`anchor_scan_max_files=0`)
  - drift rows are reported as `manual_review` until a selected dry-run/pilot policy enables bounded ARR hardlink-anchor evidence
- placement rule carried into tooling:
  - ARR library hardlink anchor present -> stash/data is the correct placement
  - no ARR library hardlink anchor found -> pool is the correct placement
  - incomplete or disabled anchor evidence -> manual review, no automatic side selection
  - qB `~noHL` from qbit_manage is advisory no-hardlink evidence, not proof; always confirm catalog/filesystem hardlink state before destructive moves, repoints, or cleanup

## 2026-05-06 Phase 2C Selected Drift Pilot Interface

`client-drift audit` now supports selected path-drift pilots:

- `--hash <prefix>` restricts report construction before path-drift anchor checks run.
- `--anchor-scan-max-files <N>` enables bounded ARR hardlink-anchor scanning for selected dry-run/pilot rows only.
- path-drift rows now include proposed target fields when policy evidence is complete:
  - `proposed_source_client`
  - `proposed_qb_save_path`
  - `proposed_rt_content_path`
  - `proposed_rt_repoint_target`
  - `proposed_rt_directory` compatibility alias only; do not use for new mutation tooling

Read-only selected live pilot:

```bash
python3 -m hashall.cli client-drift audit \
  --qb-cache-file ~/.cache/silo-qb/torrents-info.json \
  --rt-cache-file ~/.cache/silo-rt/torrents.json \
  --side path_drift \
  --hash 2d9004 \
  --anchor-scan-max-files 1000 \
  --limit 5 \
  --json-output
```

Result:

- selected rows: `1`
- hash: `2d9004e9af6618c192d965c8950189955326b3e2`
- qB side: pool
- RT side: stash/data
- anchor scan: incomplete (`library_scan_truncated=true`, `library_files_checked=1001`)
- action: `manual_review`

Interpretation:

- Phase 2C is safe for selected dry-run triage and target reporting.
- Phase 2D should replace or supplement filesystem anchor scans with catalog-backed hardlink-anchor evidence before any live repoint pilot.

## 2026-05-06 Phase 2D Catalog-Backed Anchor Evidence

`client-drift audit` now accepts an optional read-only catalog:

```bash
python3 -m hashall.cli client-drift audit \
  --qb-cache-file ~/.cache/silo-qb/torrents-info.json \
  --rt-cache-file ~/.cache/silo-rt/torrents.json \
  --side path_drift \
  --hash 2d9004 \
  --catalog ~/.hashall/catalog.db \
  --anchor-scan-max-files 0 \
  --limit 5 \
  --json-output
```

Catalog behavior:

- reads SQLite in `mode=ro`
- checks both legacy `files` and device tables shaped as `files_<id>`
- skips incompatible file tables that do not expose both `path` and `inode`
- treats matching payload inode(s) with ARR-library sibling paths as `has_arr_anchor=true`
- treats catalog payload rows without ARR-library siblings as `has_arr_anchor=false`
- falls back to the selected filesystem scan path only when catalog evidence is unavailable

Read-only selected live result for `2d9004`:

- selected rows: `1`
- action: `manual_review`
- blockers:
  - `catalog_payload_paths_missing`
  - `arr_anchor_scan_disabled`
  - `hardlink_anchor_evidence_required_for_placement`

Interpretation:

- Phase 2D is working, but this selected live hash is not yet catalog-proven because its qB/RT payload paths were not found in the current catalog.
- Phase 2E is needed before live repoint pilots: refresh or path-alias the catalog evidence for the 13 path-drift rows, then rerun selected catalog-backed audits until each row is either policy-proven or explicitly blocked.

## 2026-05-06 Phase 2E Plan Update: `~noHL` Evidence

Additional evidence to carry into 2E/B/C:

- qbit_manage may tag qB items with `~noHL` when it did not find ARR hardlinks.
- Treat `~noHL` as advisory evidence toward pool placement only.
- Never use `~noHL` alone for destructive actions:
  - no deletion
  - no live qB/RT repoint
  - no stash/pool cleanup
- Required confirmation before any destructive decision remains:
  - catalog inode evidence proving ARR hardlink anchors or their absence, or
  - selected bounded filesystem verification of the real paths, plus human review

Updated 2E execution target:

- produce a read-only evidence table for the 13 path-drift rows with:
  - qB/RT placement kind
  - qB `~noHL` presence
  - catalog anchor source/status/blockers
  - selected filesystem fallback status only when explicitly bounded
  - final classification: `policy_proven_stash`, `policy_proven_pool`, or `blocked_needs_evidence`

2E read-only execution result:

- command shape:
  - `client-drift audit --side path_drift --catalog ~/.hashall/catalog.db --anchor-scan-max-files 0 --json-output`
- qB rows: `5202`
- RT rows: `5202`
- same-hash path drift rows: `13`
- policy-proven stash: `0`
- policy-proven pool: `0`
- blocked needs evidence: `13`
- qB `~noHL` advisory rows: `4`
- common blocker set:
  - `catalog_payload_paths_missing`
  - `arr_anchor_scan_disabled`
  - `hardlink_anchor_evidence_required_for_placement`

2E interpretation:

- `~noHL` is now visible in the evidence report, but it did not unlock any row by itself.
- Current catalog coverage is insufficient for these 13 drift payload paths.
- Next follow-up should be 2F: produce a read-only catalog coverage/remap plan for the 13 qB/RT payload paths, then refresh/rescan only the missing roots or teach catalog lookup the safe `/data`/`/stash` alias mapping needed to find existing rows.

## 2026-05-06 Phase 2F Coverage + Filesystem Anchor Check

2F read-only coverage result:

- compatible catalog tables considered: `18`
- direct/alias catalog payload hits for the 13 drift rows: `0`
- all 13 candidate qB/RT paths exist on disk
- selected filesystem inode comparison scanned ARR library roots read-only:
  - ARR files scanned: `146604`
  - ARR-anchored rows: `8`
  - no ARR-anchor found: `5`
  - qB `~noHL` advisory rows: `4`

Policy classification from actual filesystem state:

- `policy_proven_stash`:
  - `1a06655541134463` Top Gun
  - `20555f704e0ae477` Bottle Shock
  - `2a4e075ecf0962ba` V for Vendetta
  - `4052607092357bfe` Twisters
  - `4f454ed3bdf830f0` Alien Resurrection
  - `5c86280a99d10071` Spider-Man Into the Spider-Verse
  - `c7845e03fe21e7fa` Twin Peaks S01
  - `e2a7eab3a5be76f7` Here 2024
- `policy_proven_pool_by_fs_no_arr_anchor`:
  - `29e2b889867a8fbb` Vigen Guroian (`~noHL`)
  - `2d9004e9af6618c1` West Wing S07
  - `2fb25fdf2ef20ae5` Novitiate (`~noHL`)
  - `97343f6005da2ed8` Cinderella
  - `a5a2b78798009b38` Wilding (`~noHL`)

Code follow-up completed during 2F:

- catalog anchor lookup now considers `files_fs_*` tables as well as legacy `files` and numeric `files_<id>` tables.

Edge case to keep out of the repoint lane:

- Some items may not be hardlinked into ARR libraries but arguably should be.
- Detect that by comparing torrent payload identity/name/path against ARR library metadata or import history, not by drift repair alone.
- Handling should be a separate `missing_arr_anchor_candidate` audit lane:
  - read-only match candidate to ARR item
  - verify bytes/path compatibility
  - decide whether to create/rebuild ARR hardlinks
  - only then revisit stash-vs-pool placement

## 2026-05-06 Phase 2G Dry-Run Repoint Plan

2G produced a read-only dry-run plan from the 2F filesystem-proven placement classes.

Artifact:

- `/tmp/hashall-20260505-112759-codex-2g-dryrun-repoint-plan.json`

Summary:

- rows planned: `13`
- mutates live state: `false`
- requires human review: `true`
- action buckets:
  - `dry_run_repoint_qb_to_rt_stash`: `1`
  - `dry_run_repoint_rt_to_qb_pool`: `2`
  - `dry_run_same_placement_canonical_choice_needed`: `7`
  - `blocked_rehome_to_pool_before_repoint`: `3`

Straightforward repoint-only candidates:

- `4f454ed3bdf830f0` Alien Resurrection
  - desired placement: stash
  - qB currently points at pool
  - RT already points at stash/data
  - dry-run action: repoint qB to RT stash save root
- `2d9004e9af6618c1` West Wing S07
  - desired placement: pool
  - qB already points at pool
  - RT points at stash/data
  - dry-run action: repoint RT to qB pool content path
- `97343f6005da2ed8` Cinderella
  - desired placement: pool
  - qB already points at pool
  - RT points at stash/data
  - dry-run action: repoint RT to qB pool content path

Same-placement canonical-choice blockers:

- `1a06655541134463` Top Gun
- `20555f704e0ae477` Bottle Shock
- `2a4e075ecf0962ba` V for Vendetta
- `4052607092357bfe` Twisters
- `5c86280a99d10071` Spider-Man Into the Spider-Verse
- `c7845e03fe21e7fa` Twin Peaks S01
- `e2a7eab3a5be76f7` Here 2024

These are policy-proven stash rows, but both qB and RT already point somewhere under stash/data. Do not repoint until choosing the canonical tree shape/root for each row.

Rehome-before-repoint blockers:

- `29e2b889867a8fbb` Vigen Guroian (`~noHL`)
- `2fb25fdf2ef20ae5` Novitiate (`~noHL`)
- `a5a2b78798009b38` Wilding (`~noHL`)

These are policy-proven pool candidates, but neither client currently points at pool. They need a pool rehome/materialization plan before qB/RT repoint.

2G interpretation:

- Do not apply all 13 as a single drift-repoint batch.
- The first live pilot candidate should be one of the three straightforward repoint-only rows, after human inspection of the exact target paths.
- Phase 2H, if needed, should turn the three straightforward dry-run candidates into explicit one-hash pilot commands with pre/post checks and rollback notes.

## 2026-05-06 Phase 2H One-Hash Pilot Command Plan

2H selected pilot candidate:

- hash: `2d9004e9af6618c192d965c8950189955326b3e2`
- name: `The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
- policy result: pool-proven by selected filesystem no-ARR-anchor evidence
- current qB path: `/pool/media/torrents/seeding/cross-seed/aither`
- current qB content: `/pool/media/torrents/seeding/cross-seed/aither/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
- current RT path: `/data/media/torrents/seeding/cross-seed/2d9004e9af6618c192d965c8950189955326b3e2/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`

Dry-run command executed:

```bash
python3 -m hashall.cli rt repoint \
  --hash 2d9004e9af6618c192d965c8950189955326b3e2 \
  --target-directory /pool/media/torrents/seeding/cross-seed/aither
```

Dry-run result:

- command is non-mutating without `--apply`
- `apply: False`
- no normalization surprise when targeting the qB save root directly

Apply command if human approves:

```bash
python3 -m hashall.cli rt repoint \
  --hash 2d9004e9af6618c192d965c8950189955326b3e2 \
  --target-directory /pool/media/torrents/seeding/cross-seed/aither \
  --apply
```

Required prechecks before apply:

- qB cache still shows:
  - `save_path=/pool/media/torrents/seeding/cross-seed/aither`
  - `content_path=/pool/media/torrents/seeding/cross-seed/aither/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
  - `state=stoppedUP`
  - `progress=1`
- RT cache still shows the old stash/data path and healthy complete state.
- both qB target save/content paths still exist.
- selected no-ARR-anchor evidence is still valid.

Expected postchecks after apply:

- refresh or wait for the RT cache update before declaring success.
- `client-drift audit --side path_drift --hash 2d9004e9` should clear or change to aligned.
- qB remains complete/seed-ready.
- RT remains complete/seed-ready.

Rollback note:

- if the RT repoint misbehaves, repoint RT back to:
  - `/data/media/torrents/seeding/cross-seed/2d9004e9af6618c192d965c8950189955326b3e2/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`

Decision point:

- human approval is required before running the `--apply` command.
- 2I is only needed if we want this exact pilot packaged into a reusable guarded script/manifest instead of running the existing `rt repoint` command manually.

## 2026-05-06 Phase B One-Hash Live RT Repoint Pilot

Phase B applied the Phase 2H pilot for:

- hash: `2d9004e9af6618c192d965c8950189955326b3e2`
- name: `The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
- policy result: pool-proven by selected filesystem no-ARR-anchor evidence
- action: repointed RT from the stale stash/data path to the qB pool save root

Applied command:

```bash
python3 -m hashall.cli rt repoint \
  --hash 2d9004e9af6618c192d965c8950189955326b3e2 \
  --target-directory /pool/media/torrents/seeding/cross-seed/aither \
  --apply
```

Apply result:

- completed RT actions: `d.stop`, `d.close`, `d.directory.set`, `d.save_full_session`, `session.save`, `d.open`, `d.start`
- live RT postcheck directory: `/pool/media/torrents/seeding/cross-seed/aither/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
- live RT postcheck complete: `1`
- qB postcheck remains complete at:
  - save path: `/pool/media/torrents/seeding/cross-seed/aither`
  - content path: `/pool/media/torrents/seeding/cross-seed/aither/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
  - state: `stoppedUP`
  - progress: `1.0`
- selected drift audit now reports `path_drift=0` and `drift_total=0` for `--hash 2d9004e9`

Residual notes:

- the old stash/data content directory still exists and should be handled by a later read-only residue/ownership audit, not deleted from this pilot.
- 2I was skipped by request; no reusable pilot wrapper was added.

Next recommended lanes:

- Phase C: read-only residue audit for the old stash/data path and related cleanup candidates.
- Phase D: continue path-drift repair with another one-hash pilot only after Phase C confirms no unexpected ownership/residue issue from this pilot.

## 2026-05-06 Phase C Read-Only Residue Audit

Phase C audited the old stash/data tree left behind by the Phase B pilot:

- old tree: `/data/media/torrents/seeding/cross-seed/2d9004e9af6618c192d965c8950189955326b3e2/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
- current pool tree: `/pool/media/torrents/seeding/cross-seed/aither/The.West.Wing.S07.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`

Read-only findings:

- old tree exists and contains `22` files / `75,287,462,464` bytes
- current pool tree exists and contains `22` files / `75,287,462,464` bytes
- old and pool trees are on different devices and do not share inodes
- old file link counts range from `9` to `10`
- pool file link counts range from `5` to `6`
- focused ARR-library same-inode check found `0` matches for the old tree
- catalog `payload orphan-audit` scoped to the old `2d9004...` prefix reports:
  - `true_orphans=0`
  - `alias_artifacts=0`
  - `scoped_unmanaged_payloads=0`
- catalog lookup found:
  - `0` payload rows under the old tree
  - `0` scanned file rows under the old tree in compatible `files*` tables
  - torrent instance `2d9004e9af6618c192d965c8950189955326b3e2` points to payload `16738` at the pool save path
- selected client-drift audit still reports `path_drift=0` for `--hash 2d9004e9`

Interpretation:

- the old stash/data tree is not qB-owned, not RT-owned, not catalog-payload-owned, and not ARR-hardlink-anchored by the focused check.
- it is a duplicate-looking cross-device residue candidate, not a deletion-approved path.
- because the old files have high non-ARR link counts, cleanup needs one more targeted ownership pass that maps the sibling hardlinks before any destructive action.

Phase C stopped before deletion, as intended.

Recommended C-2:

- map same-inode siblings for the old tree inside torrent seeding roots only, excluding ARR roots already checked
- identify whether those links are other cross-seed aliases, historical hash directories, or unmanaged residues
- produce an exact reviewed cleanup set if every old-tree inode has non-client, non-ARR sibling coverage
- do not delete directly from the report

Recommended D:

- after C-2 or human acceptance of the residue risk, continue path-drift repair with the next simple one-hash pilot.
- recommended candidate: `97343f6005da2ed8` if fresh prechecks still show it as pool-proven, complete, and repoint-only.

Recommended E:

- build a reusable read-only residue/ownership audit around this evidence pattern so future path-drift pilots automatically emit:
  - qB owner
  - RT owner
  - catalog payload owner
  - catalog file rows
  - ARR same-inode anchors
  - torrent-root same-inode siblings
  - deletion eligibility status, always defaulting to blocked until explicitly reviewed

## 2026-05-06 Phase 1 Evidence Safety Hardening

Deep branch review found two evidence semantics that needed hardening before more live path-drift pilots:

- catalog hardlink-anchor detection matched on `inode` without requiring filesystem identity in aggregate tables
- catalog "no ARR anchor found" was treated as proof of pool placement, even though absence from catalog is not the same as absence on disk

Phase 1 code changes:

- catalog positive ARR-anchor evidence now requires:
  - a same-table per-filesystem catalog table such as `files_fs_*` / `files_<id>`, or
  - an aggregate `files` table with `fs_uuid` or `device_id`
- aggregate catalog tables without filesystem identity now block with `catalog_table_lacks_filesystem_identity:<table>`
- matching in aggregate tables now uses the filesystem identity plus inode, not inode alone
- catalog negative evidence now blocks with `catalog_negative_anchor_requires_filesystem_confirmation`
- catalog-only negative evidence no longer selects pool or emits a repoint action

Verification:

- `pytest -q tests/test_client_drift.py tests/test_qbittorrent.py` -> `49 passed`
- `python3 -m py_compile src/hashall/client_drift.py src/hashall/cli.py src/hashall/qbittorrent.py scripts/pause_mirror_seeders.py` -> passed
- read-only live `client-drift audit --side path_drift --catalog ~/.hashall/catalog.db --anchor-scan-max-files 0 --json-output` now reports:
  - qB rows: `5202`
  - RT rows: `5202`
  - path drift: `12`
  - action counts: `manual_review=12`

Interpretation:

- The branch is safer for the stated cleanup goal: catalog positive evidence can still help when identity is sound, but catalog absence cannot drive placement by itself.
- The next live pilot must use actual bounded filesystem confirmation or a future catalog freshness/coverage proof before selecting the side to keep.

## 2026-05-06 Phase 2 Pilot Contract Hardening

Phase 2 hardened path-drift report fields so dry-run/pilot consumers do not confuse RT content paths with the safe `d.directory.set` target.

Code changes:

- path-drift placement rows now include:
  - `proposed_rt_content_path`
  - `proposed_rt_repoint_target`
- `proposed_rt_directory` remains for compatibility, but new code and operator docs should prefer `proposed_rt_repoint_target` for `rt repoint --target-directory`
- single-file RT rows now emit the parent directory as `proposed_rt_repoint_target`
- multi-file RT rows now emit the containing save root as `proposed_rt_repoint_target`
- CLI human output now labels the safer value as `rt_repoint=...`

Verification:

- `pytest -q tests/test_client_drift.py tests/test_qbittorrent.py` -> `50 passed`
- `python3 -m py_compile src/hashall/client_drift.py src/hashall/cli.py src/hashall/qbittorrent.py scripts/pause_mirror_seeders.py` -> passed
- `python3 scripts/check_doc_links.py` -> `BROKEN_LINKS=0`
- selected read-only `97343f...` path-drift audit with bounded filesystem scan reports:
  - action: `repoint_rt_to_qb_path`
  - blockers: `[]`
  - `proposed_rt_content_path=/pool/media/torrents/seeding/cross-seed/DigitalCore (API)/Cinderella.2021.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR.mkv`
  - `proposed_rt_repoint_target=/pool/media/torrents/seeding/cross-seed/DigitalCore (API)`

Interpretation:

- Phase 2 fixes the most important pilot-contract ambiguity for the next single-file live candidate.
- Phase 2B should update the remaining docs/tests to describe `proposed_rt_directory` as a compatibility alias only; new live pilot docs and automation must use `proposed_rt_repoint_target`.

## 2026-05-06 Phase 2B Compatibility Cleanup

Phase 2B retained `proposed_rt_directory` for older JSON consumers but demoted it from the operator contract.

Rules going forward:

- use `proposed_rt_repoint_target` as the only report field safe to pass to `rt repoint --target-directory`
- use `proposed_rt_content_path` for inspection and post-apply content existence checks
- treat `proposed_rt_directory` as a compatibility alias for older report readers, not as a mutation target

2B did not remove the alias because this branch still has humans and docs consuming historic JSON examples. Removing it should wait until all report consumers are updated.

## Big-Picture Seed Folder Cleanup TODO

Keep this list as the high-level operator target while working through the detailed waves.

1. Finish `cross-seed-link -> cross-seed`.
2. Finish `orphaned_data -> orphans`.
3. Repair the remaining broken live torrents.
4. Drain all torrent payloads out of `/pool/data`.
5. Enforce stash-vs-pool placement using the hardlink-anchor rule.
   - pool is correct when no sibling media file is hardlinked into ARR media libraries
   - stash/data is correct when any sibling media file is hardlinked into ARR media libraries
6. Remove steady-state duplicates between stash and pool.
7. De-hitchhike legacy N->1 payload trees into unique per-hash trees.
8. Keep qB and RT aligned after every live change.
   - same-hash qB/RT save-path drift is an active watch/fix class, not just membership drift
9. Clean stale residue and empty legacy paths after each wave.
10. Update code/docs/scripts in `hashall` and `~/dev` that still assume old paths.
11. Finish the repair / verification contract in tooling.
12. End with canonical stash/pool trees, zero live legacy names, zero torrent payloads on `/pool/data`, and per-hash unique payload trees.

## 2026-04-18 Torrent Tree Normalization Decisions

Canonical planning doc:
- `docs/operations/TORRENT-TREE-NORMALIZATION-PLAN-2026-04-18.md`

Settled operator decisions:
- canonical names are:
  - `cross-seed`
  - `orphans`
- legacy names to retire:
  - `cross-seed-link`
  - `orphaned_data`
- orphans live under `*/media/torrents/orphans`, not under `*/media/torrents/seeding/orphans`
- each dataset keeps its own local `torrents/orphans` first
- stash orphans may be rehomed to pool and/or spare later as space allows
- RT is the operational authority
- qB remains online as a silent mirror and must be kept in sync for affected torrents
- if any file in a payload has a hardlink into `/stash/media` libraries, keep the whole sibling payload group on stash
- otherwise, rehome the whole sibling payload group to pool
- `/pool/data` is not a final torrent-payload home and should drain to zero torrent payloads
- same-hash qB/RT save-path drift must be audited after cleanup waves; select the corrected side from the stash-vs-pool hardlink-anchor policy, not from client preference alone
- default drift audits should find save-path drift quickly and fail closed on placement; enable bounded hardlink-anchor scans only for selected dry-run/pilot rows or replace them with catalog-backed lookups

Execution policy:
- no blind bulk loops
- every mutating phase should use:
  - sim code walk
  - dry-run
  - tiny pilot
  - code/fix/code/fix loops before widening
- stop for manual review on:
  - same names with different hashes
  - conflicting verified stash/pool copies
  - mixed hardlink-anchor evidence
  - incomplete sibling groups
  - any unexpected state

Current progress:
- operator policy answers are now captured in repo docs
- `payload orphan-sweep` gained staged controls:
  - `--order`
  - `--reserve-gib`
  - `--dataset`
- live pilot work exposed and fixed an empty-dir `--limit` bug
- current `/pool/data/media/torrents/seeding` pilot state shows no remaining orphan-sweep candidates there after empty-dir cleanup
- canonical docs and continuation notes are now committed in-repo
- next lane is planning and auditing, not another blind mutation run
- immediate next action is the `~/dev` path-reference audit before any rename batch
- broad `~/dev` audit is now complete
- Docker-repo live path-setting scripts have been identified:
  - RT hooks:
    - `gluetun_qbit/rtorrent_vpn/rt_sync_imported_path.sh`
    - `gluetun_qbit/rtorrent_vpn/rt_set_label_path.sh`
    - `gluetun_qbit/rtorrent_vpn/rt_repair_legacy_path.sh`
  - qB-side active legacy-name consumers:
    - `qbit_manage/config.yml`
    - `qbit_manage/config-seeds.yml`
    - `qbit_manage/bin/promote_recycle_to_seeds.sh`
    - `qbit_manage/bin/check_pool_orphans.sh`
    - `gluetun_qbit/qbittorrent_vpn/bin/qb-to-rt-migrate.py`
- live legacy-name scope is now quantified:
  - `27` live RT rows on `cross-seed-link`
  - `27` live qB rows on `cross-seed-link`
  - `1` live RT row on `orphaned_data`
  - `1` live qB row on `orphaned_data`
- first concrete dry-run proved the qB/RT target mapping for a `cross-seed-link -> cross-seed` candidate, but also exposed a tooling gap:
  - RT target semantics are full content-directory based
  - qB target semantics are save-root based
  - `qb-zfs-relocate validate` is not suitable as a same-FS rename preflight
- qB and RT were both down during the first dry-run attempt and had to be recreated from the Docker compose stack before live dry-run work could continue
- a dedicated one-hash same-FS helper now exists:
  - `payload normalize-cross-seed-link`
- focused helper tests now pass:
  - `pytest -q tests/test_path_normalize.py`
- first live one-hash `cross-seed-link -> cross-seed` pilot succeeded for:
  - `b95856e0a29bf045e76a95f4ea3cacf6e4b02add`
- post-pilot live state:
  - qB canonical save path:
    - `/pool/media/torrents/seeding/cross-seed/FileList.io`
  - RT canonical directory:
    - `/pool/media/torrents/seeding/cross-seed/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
  - RT recovered from `error` back to `stalledUP`
- live legacy-name scope after the pilot:
  - `24` live RT rows on `cross-seed-link`
  - `24` live qB rows on `cross-seed-link`
  - `1` live RT row on `orphaned_data`
  - `1` live qB row on `orphaned_data`
- important follow-up:
  - the failed first pilot left a stale on-disk legacy residue under `/pool/media/torrents/seeding/cross-seed-link/...`
  - it is not referenced by qB or RT anymore and needs an explicit cleanup decision, not silent removal during helper apply
- additional live pilot coverage now exists:
  - `55a3df42dcf14d250117d811b52dca658fd05f73`
    - multi-file / RT content-directory case
  - `8779246eebcf9135f272d24cdff643887700ffe1`
    - single-file / RT root-directory case
- a hardened operator wrapper now exists:
  - `scripts/pilot-normalization.sh`
  - list/dry-run by default
  - refuses apply outside a worktree / `cr/` branch
  - filters safe apply candidates to stopped `/pool/media` rows
  - uses shared qB/RT cache reads for list, watch, post-check, and live legacy counts where possible
  - leaves the actual mutation to the direct `payload normalize-cross-seed-link` helper
  - prints post-check state, residue classification, and remaining live legacy counts
- first wrapper-driven live pilot succeeded for:
  - `5bf579e7c4c98daeb66c87da1f6068512f35c3cd`
  - qB canonical save path:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia`
  - RT canonical directory:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
  - wrapper watch timed out as `ambiguous_needs_review` because RT remained `checking` longer than the 120s budget
  - immediate follow-up state still showed both clients aligned on the canonical path
- live legacy-name scope after the wrapper pilot:
  - `21` live RT rows on `cross-seed-link`
  - `21` live qB rows on `cross-seed-link`
  - `1` live RT row on `orphaned_data`
  - `1` live qB row on `orphaned_data`
- wrapper auto-pick/cache-read hardening is now in place:
  - qB cache reads go through `bin/lib/qb-cache.sh`
  - RT status reads go through the shared RT cache snapshot
  - this avoids direct read-heavy qB/RT polling in the wrapper watch/list loops
- first cache-backed auto-pick pilot succeeded for:
  - `fad3310db364ee7a8e97d511a85cf4df1eab4813`
  - tracker root:
    - `/pool/media/torrents/seeding/cross-seed/FearNoPeer`
  - qB content path:
    - `/pool/media/torrents/seeding/cross-seed/FearNoPeer/The Last Stop in Yuma County 2023 1080p AMZN WEB-DL DDP5 1 H 264-BYNDR.mkv`
  - RT runtime directory converged to the same canonical root and reached `checkingUP`
- live legacy-name scope after the cache-backed auto-pick pilot:
  - `20` live RT rows on `cross-seed-link`
  - `20` live qB rows on `cross-seed-link`
  - `1` live RT row on `orphaned_data`
  - `1` live qB row on `orphaned_data`
- timeout hardening landed after the `DigitalCore (API)` retry:
  - RT XMLRPC can time out after qB has already moved
  - helper now treats RT timeout as ambiguous and waits for RT verification instead of immediately rolling qB back

Cross-repo requirement:
- before any tree-normalization batch, audit `~/dev` for path-sensitive code/docs referencing old names or old canonical roots
- plan updates in the owning repo/worktree rather than treating hashall-only changes as sufficient

## 2026-04-15 Full Refresh + Orphan GC Backlog

**Completed:**
- Full refresh run (all roots): stash, pool-media, pool-data, hotspare6tb
- 5254 payloads processed, 1 incomplete (scan gap in speakarr)
- 4 dedup link plans executed (cross-seed consolidation)
- **Quality gate PASS** (fix for false-FAIL bug confirmed working)

**Current state:**
- Orphan backlog: 2276 aged candidates (post-qB-shutdown, Feb 2026)
- Currently blocked by GC hardcoded limit (1000)
- **Can be unlocked via env vars**: `HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT=3000 HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION=0.5`
- Estimated space to free: ~250+ GB (qB leftover residue)
- **Action required**: Decide whether to RELOCATE (move to `/stash/media/orphaned_data/`) vs DELETE

**Code fixes (committed `506d0ae`):**
- Quality gate: upgraded `len(upgrade_queue)` → `total_upgrade_roots` (post-filter count)
- Orphan GC limits: now env-configurable (was hardcoded)
- Tests: regression suite for both fixes (121 tests green)

**Next steps:**
1. Run orphan GC with env overrides to free space
2. Scan unindexed payload (`speakarr/Command and Control`)
3. Decide on orphan relocation behavior (future enhancement)
4. Continue pool/data drain once space is freed

---

## 2026-04-03 Residual stash reuse follow-up

## 2026-04-03 Residual stash reuse follow-up

**Key outcome:**
- the `Bullet Train` residual reuse family is now fixed and no longer part of the ambiguous cleanup queue

**What changed in code:**
- `src/rehome/executor.py` now:
  - skips the expensive compare against the already-selected current target root
  - derives a per-torrent `target_payload_root` for wrapped single-entry reuse rows
  - constructs fallback wrapper views when reuse plans have empty `view_targets` but the torrent metadata requires a nested single-entry root

**Live execution result:**
- single-item run:
  - `python -m hashall.cli rehome auto --from stash --to pool-media --limit 1 --apply`
- family repaired:
  - `Bullet.Train.2022...`
- result:
  - `10/10` rows verified
  - `0` failures
  - qB patch applied successfully
  - stash cleanup intentionally deferred with `MANUAL_ACTION_REQUIRED`
- current source of truth:
  - `~/.logs/hashall/reports/rehome-relocate/20260403-010351-8b5c09e0c7c083bf`
  - `~/.logs/hashall/rehome/auto/20260403-010348.log`
- two more narrowed single-item reuse runs then completed successfully:
  - `The Muppet...`
    - report: `~/.logs/hashall/reports/rehome-relocate/20260403-012107-7b198aa544d1f641`
    - log: `~/.logs/hashall/rehome/auto/20260403-012104.log`
  - `Lego Masters...`
    - report: `~/.logs/hashall/reports/rehome-relocate/20260403-012850-ca30f78203851ebf`
    - log: `~/.logs/hashall/rehome/auto/20260403-012847.log`

**Operational interpretation:**
- do not restart the broad unattended pool-migration loop yet
- the right pattern now is narrow single-item stash reuse execution
- that narrowed queue is now exhausted; current dry-run result is:
  - `0 MOVE groups available (stash:0), taking top 0`
  - `No eligible candidates found.`

**Residual warning to keep in mind:**
- post-run reality still reports shared catalog grouping for the reused `Bullet Train`, `The Muppet...`, and `Lego Masters...` families
- this is a de-hitchhike/catalog-normalization follow-up, not a blocker for the successful moves

## 2026-04-02 Pool Migration Maintenance Loop

**New ops doc:**
- `docs/operations/POOL-MIGRATION-MAINTENANCE-LOOP-2026-04-02.md`

**New helper:**
- `bin/run-pool-migration-maintenance-loop.sh`

**Purpose:**
- continue the post-`pool/data -> pool/media` cleanup lane with minimal operator input
- recover the payload-sync tail if qB / RT are degraded
- prune a tiny reviewed set of stale `/pool/data` residue
- reconcile the catalog
- then auto-apply stash -> pool-media rounds only when the batch is all `REUSE`

**Current reviewed cleanup scope in the loop:**
- `/pool/data/cross-seed-link/SpeedCD/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
- `/pool/data/cross-seed-link/TorrentDay/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`

**Current observed live state:**
- both reviewed stale `How It's Made` roots are now gone from `/pool/data`
- qB is healthy
- RT is healthy
- space remains healthy:
  - `/pool/data`: about `3.7T` free
  - `/pool/media`: about `3.7T` free
  - `/stash/media`: about `12T` free

**Current migration residue posture:**
- only `10` torrent rows still save under `/pool/data`
- `379` torrent rows save under `/pool/media`
- `0` torrent rows save under `/stash`
- the remaining `/pool/data` set is a carve-out / residue set, not a bulk move queue

**Current observed loop progress:**
- payload-sync recovery succeeded
- stale residue cleanup succeeded for the reviewed `How It's Made` roots
- `/pool/data` reconcile scan ran
- the loop advanced into stash reuse rounds
- observed round state:
  - one stash reuse wave advanced into verify on `/pool/media`
  - a later dry-run surfaced another all-`REUSE` stash batch (`3` groups)
- the first unattended run then reached diminishing returns:
  - later rounds resurfaced the same `3` families because one torrent in each family ended verification as `dest_missing`
  - those residual hashes are:
    - `06a8867d184c6972956307c7eea48ce16669e17c` (`Bullet Train` family)
    - `2bf62b9780fa8c394a8a4d9a57ebb5b924309645` (`Muppet` family)
    - `7c404604a9a478b5d35f109c72935023bd454ef2` (`Lego Masters` family)
  - the loop script is now hardened to stop on `status=dest_missing` instead of treating that as a good enough round

**Important constraint:**
- qB must remain online while this loop runs
- `rehome apply` is still qB-backed in `hashall`
- `payload sync` now supports RT-backed sync and the maintenance wrapper defaults to RT mode

**Source of truth while the loop is live:**
- newest log under `~/.logs/hashall/pool-migration-loop/`

## 2026-04-02 RT Cache Alignment + Refresh Failure Recovery

**Cross-repo coordination hydrated from Docker repo:**
- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/agent-prompts/silo-rt-cache-hardening-prompt-2026-04-02.md`
- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/agent-prompts/hashall-rt-cache-alignment-prompt-2026-04-02.md`
- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/rt-arr-qb-path-handoff-2026-04-01.md`

**New docs in this repo:**
- `docs/operations/RT-CACHE-ALIGNMENT-2026-04-02.md`
- `docs/operations/RT-CACHE-AGENT-COMMS-2026-04-02.md`
- `docs/operations/REFRESH-RECOVERY-2026-04-02.md`

**RT cache alignment outcome:**
- `hashall rt state-audit` is now shared-cache-backed by default.
- Default read source:
  - `~/.cache/silo-rt/torrents.json`
  - `~/.cache/silo-rt/torrents.meta.json`
- Default behavior is fail-closed:
  - stale or degraded cache state is surfaced to operators
  - no silent fallback to live RT XMLRPC
- Live RT remains explicit-only for diagnostics:
  - `hashall rt state-audit --live`

**Already-compliant RT read paths:**
- `hashall content reclaim-report`
- `hashall rehome drift-audit`
- `hashall rt session-audit`
- `hashall rt repair-report`

**Still-intentional direct RT mutation paths:**
- `hashall rt repoint`
- `hashall rt recheck`
- `hashall rt session-reset`
- `hashall rt repair-apply`

**Overnight full refresh failure assessment:**
- The 4 scan phases completed.
- Failure was in the final step only:
  - `python -m hashall.cli payload sync --upgrade-missing`
- Logged failure shape:
  - qB auth reset during `test_connection()`
  - `ConnectionResetError(104, 'Connection reset by peer')`
  - raised as `RuntimeError: Failed to authenticate with qBittorrent`
- So the refresh did **not** need rescans; it needed stack recovery and a resumed payload sync.

**Hardening added:**
- `bin/run-hashall-upgrade-scans.sh` now:
  - probes qB and RT readiness before payload sync
  - restarts the whole `gluetun_qbit` stack if qB or RT is degraded
  - retries payload sync once after restart
  - supports `--payload-sync-only` so a failed overnight run can resume without rescanning
  - defaults the final payload sync step to `--source rt`

**Current recommended recovery command for this specific failure class:**
- `bin/run-hashall-upgrade-scans.sh --payload-sync-only`

**Recovery execution status:**
- The recovery path was exercised successfully on `2026-04-02`.
- Result:
  - stack restarted once
  - payload sync completed successfully
  - no scan rerun was required

## 2026-04-01 Refresh Defaults + Client Boundary

**Refresh / scan defaults updated:**
- `hashall scan` now defaults to scanning nested datasets.
- `hashall refresh` now carries nested dataset scanning through every scan step.
- `hashall refresh` dedupe now resolves and covers all device aliases represented by the refreshed roots, rather than only the configured top-level aliases.

**Current intended refresh coverage:**
- `/stash/media`
- `/pool/data`
- `/pool/media`
- `/mnt/hotspare6tb`
- destination root `/pool/media/torrents/seeding`

**Important config interpretation:**
- Broad `/pool/media` had previously been missing from refresh coverage.
- That meant older refresh runs could cover `/pool/media/torrents/seeding` while still missing other `/pool/media` content trees.
- `/pool/data` subfolders could also appear to be "ignored" when operators looked only at `payloads`, because `payload sync` only materializes qB torrent roots while scan truth lives in `files_*`.
- Nested dataset omission is now addressed by the new default scan behavior.

**Current recommended full refresh commands:**
- One-shot wrapper:
  - `python -m hashall.cli refresh --scan-hash-mode upgrade --drift-policy quick`
- Explicit helper script in repo:
  - `bin/run-hashall-upgrade-scans.sh`
- Explicit manual equivalent:
  - `python -m hashall.cli scan /stash/media --hash-mode upgrade --drift-policy quick`
  - `python -m hashall.cli scan /pool/data --hash-mode upgrade --drift-policy quick`
  - `python -m hashall.cli scan /pool/media --hash-mode upgrade --drift-policy quick`
  - `python -m hashall.cli scan /mnt/hotspare6tb --hash-mode upgrade --drift-policy quick`
  - `python -m hashall.cli payload sync --upgrade-missing`

**Current torrent-client boundary:**
- `hashall` already has first-class rt repair/audit commands.
- `hashall` is **not yet** torrent-client agnostic.
- qB is still a dependency for:
  - `refresh` end-state payload sync
  - torrent-backed payload materialization
  - `rehome apply`
  - `rehome followup`
  - current local piece verification that depends on qB `BT_backup`
- Canonical plan for removing that dependency is now documented in:
  - `docs/operations/TORRENT-CLIENT-AGNOSTIC-PLAN.md`

**ZFS scrub note:**
- `pool` scrub had already completed cleanly.
- `stash` scrub was canceled during this session because it had been run recently and was not needed while refresh / scan work was active.

## 2026-03-27 Dual-Client Drift Handoff

New dedicated handoff:
- `docs/operations/RT-QB-DRIFT-HANDOFF.md`

New default operating rule:
- treat seeded data as dual-client sensitive by default
- do not assume qB-only unless explicitly proven

Current sweep result:
- `4522` hashes found in both clients
- `55` hashes with real rt/qB path drift after normalization
- none of the still-remaining `/pool/data` migration items are drifted between rt and qB

Highest-priority cleanup bucket:
- `19` rows where qB is already on `/pool/media` but rt still points at an older path
- these should be repointed in rt before considering those migration items fully normalized

Important design instruction:
- migration, repair, and reclaim code should be updated to be dual-client sensitive going forward
- qB-only path protection is no longer sufficient for cleanup safety
- current code now reflects that in two concrete places:
  - `hashall content reclaim-report` protects live rt session roots as well as live qB payload roots
  - `hashall rehome drift-audit` reports `rt_drift_rows` so a qB-aligned plan can still surface rt path drift

## 2026-03-26 Live qB Failure Cluster + Carve-Out Recheck

**Current live qB failed-ish set:**
- There are currently `9` live qB items in a failed-ish state:
  - `6` `stoppedDL`
  - `3` `stalledDL`
- Current hashes:
  - `20555f704e0ae477dce28844c95c626fcf78a261` `Bottle.Shock...`
  - `e2ae560a5d51186e2160099aa56d63687a25def1` `River.Monsters.S06...`
  - `5c86280a99d1007104452b2f72d0d686e092e2f8` `Spider-Man.Into.the.Spider-Verse...`
  - `96d896ca35f42d93e4a4bdee92e8ac90adc34b54` `Transformers.Rise.of.the.Beasts...`
  - `7dafdd61e6b9d58d9721c12d8a3da2cde40fc776` `Queen - Queen II...`
  - `127c38342cfedaf4016b8079be13c5f7883b9cfe` `River Monsters S07...`
  - `5feb771c9b7f75fe09205204b367c88efa993031` `Spider-Man.Into.the.Spider-Verse...`
  - `5caca88d29e64de495a47b53a466f7cadcb3ce02` `The.Diary.of.a.Teenage.Girl...`
  - `c8f01321b9fe0697c19c9aa450b570b59548eb15` `The.Matrix.Reloaded...`

**Failure-shape assessment:**
- This cluster is mostly `/data/media/torrents/seeding/...` runtime drift and missing-content fallout,
  not evidence of a new pool migration planner bug.
- `6` rows are `stoppedDL 0%`; of those, `5` have a missing `content_path` while the parent
  `save_path` still exists.
- `3` rows are `stalledDL` but still have content on disk and are near complete:
  - `96d896...` progress `0.999907`
  - `127c383...` progress `0.999236`
  - `5caca88...` progress `0.984191`
- Several failed-ish rows still map back to complete `/stash/...` catalog payload roots, which is a
  strong sign of stale runtime / fastresume metadata rather than a cleanly modeled migrated state.

**Migration triage ranking:**
1. Repair-first before using related migration batches:
   - `20555...` `Bottle.Shock...`
   - `e2ae...` `River.Monsters.S06...`
   - `7daf...` `Queen - Queen II...`
   - `5feb...` `Spider-Man...`
   - `c8f013...` `The.Matrix.Reloaded...`
   These are `stoppedDL 0%` with missing content on disk and are the clearest stale-runtime /
   fastresume drift cases.
2. Repair if those payload families become migration-adjacent; otherwise do not let them block
   unrelated pool migration:
   - `5c862...` `Spider-Man...`
   This is also `stoppedDL 0%` with missing content, but it overlaps the same family as `5feb...`
   and should be handled as part of that family repair instead of as a separate migration blocker.
3. Monitor only; do not let these near-complete rows block general pool migration batching:
   - `96d896...` `Transformers.Rise.of.the.Beasts...`
   - `127c383...` `River Monsters S07...`
   - `5caca88...` `The.Diary.of.a.Teenage.Girl...`
   These are `stalledDL` with content present on disk and look more like settle / qB accounting
   drift than broken-missing content.

**Skip-check investigation:**
- Current qB tags / categories / names show `0` explicit `skip-check` / `skip_check` /
  `skipcheck` markers.
- The failed-ish cluster also does not show a skip-check signature in fastresume:
  - all inspected rows currently have `sequential_download=0`
- Current evidence points to stale or tainted qB + fastresume metadata, not to an explicit
  skip-check flag being set.

**Notable metadata drift examples:**
- `5feb771c...` `Spider-Man...`
  - runtime `save_path=/data/media/torrents/seeding/movies`
  - runtime `content_path=/incomplete_torrents/...`
  - fastresume `save_path=/incomplete_torrents`
  - fastresume `qBt-savePath=/data/media/torrents/seeding/movies`

## 2026-04-20 PD Repair Donor Search

- Investigated the current three near-complete qB `stoppedDL` rows:
  - `96d896ca35f42d93e4a4bdee92e8ac90adc34b54` `Transformers.Rise.of.the.Beasts...`
  - `127c38342cfedaf4016b8079be13c5f7883b9cfe` `River Monsters S07...`
  - `5caca88d29e64de495a47b53a466f7cadcb3ce02` `The.Diary.of.a.Teenage.Girl...`
- Hitchhiker check:
  - these three do **not** currently appear to be N->1 hitchhikers
  - no shared payload-root collision was found between them
  - no additional live qB/RT row was found pointing at the exact same payload tree for these hashes
- `96d896...` and `127c383...`:
  - qB cache and live qB API agree on their current state
  - qB still reports real remaining deficits after recheck:
    - `96d896...` `amount_left=1959802`
    - `127c383...` `amount_left=16777216`
  - the main media bytes are already correct
  - the visible sidecars are broken:
    - `96d896...` `.mkv.nfo=0`, `.txt=0`
    - `127c383...` `.nfo=0`
  - `/data` and `/stash` copies are the same inode families for the media payloads
  - `_qb-repair-v2` and `rtorrent` family copies are not better donors; they carry the same broken sidecars
  - broad search across obvious `/pool` and spare roots did not surface a better exact donor
  - classification: **no local exact donor found**
- `5caca8...`:
  - qB still reports a larger remaining deficit: `amount_left=388062872`
  - the main mkv and subtitle files are present
  - `Sample.mkv=0` and `.nfo=0`
  - `_qb-finish` family copies are not better donors; they have the same broken sidecars
  - classification: **no local exact donor found**
- Current operator conclusion for all three:
  - not a qB-cache/dashboard problem
  - not a hitchhiker problem
  - not likely fixable by switching to another visible local family copy
  - next lane is controlled redownload or deeper piece-level repair, not another blind recheck

## 2026-04-20 Next Cleanup Wave

- Mark these three hashes as manual-review holdouts:
  - `96d896...`
  - `127c383...`
  - `5caca8...`
- Current qB live read still shows:
  - `96d896...` `stoppedDL` `amount_left=1959802`
  - `127c383...` `stoppedDL` `amount_left=16777216`
  - `5caca8...` `stoppedDL` `amount_left=388062872`
- DocsPedia qB side is now clean:
  - `81ede24...` is `stoppedUP 1.0`
  - canonical qB path:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
- The next smallest actionable cleanup wave is the Dexter pair:
  - `245f2bce6afaf96b0a48ad216366c4281fdd864f`
    - qB `stoppedDL`
    - progress `0.9997485`
    - `amount_left=2097152`
    - current qB path under `_qb-repair-v2`
  - `e36553b12dc118d8c52575a1d6711532882ae1c3`
    - qB `stoppedDL`
    - progress `0.9996357`
    - `amount_left=2097152`
    - current qB path under canonical `cross-seed/TorrentLeech`
- Selected next wave:
  - Dexter pair repair

## 2026-04-20 Dexter Wave Outcome

- Wave 1 executed on:
  - `245f2bce6afaf96b0a48ad216366c4281fdd864f`
  - `e36553b12dc118d8c52575a1d6711532882ae1c3`
- qB and RT were both repointed/rechecked on canonical `/data/media/torrents/seeding/cross-seed/TorrentLeech/...` paths.
- Post-wave live state:
  - qB: both `stoppedDL`
  - RT: both `stalledDL`
  - both still have `2097152` bytes left
- Interpretation:
  - not a simple metadata/path-drift repair
  - exact payload trees match healthy sibling hashes, but torrent identities differ
  - move these two into manual-review / alternate-identity repair

## 2026-04-20 RT Cleanup Wave Outcome

- Wave 2 / Wave 3 result:
  - `691f3d9453c501ed0dff9ac7c85978389a332ab2` cleared from the RT bad-row set after recheck
  - it no longer needs RT cleanup
- Remaining RT-only bad rows with no qB owner:
  - `e04e524750c999ac22d994e5f5ebf8f5dd1d4c84`
  - `3e82f6f7a3a5adaebce5dfac35d8cc6c4fc5f9ad`
- Next interpretation:
  - these are RT-only review items, not qB mirror fixes
  - inspect each one for session residue vs real content trouble before mutating again

## 2026-04-20 RT-Only Review Wave Outcome

- Wave 4 executed on:
  - `e04e524750c999acfc9afd5c9a604e12fbaee0d8`
  - `3e82f6f7a3a5adae52d84a1074b290b42ccb5026`
- Both payload trees exist on disk at canonical `/pool/media/torrents/seeding/cross-seed/FileList.io/...` paths.
- Deeper diagnosis found that both are multi-file torrents but RT had `d.directory` set to the torrent root instead of the parent save root.
- Direct `rt recheck` was not enough.
- Revised fix used:
  - `python -m hashall.cli rt session-reset --hash <full_hash> --target-directory /pool/media/torrents/seeding/cross-seed/FileList.io --apply`
- Post-wave live state:
  - both moved from `stoppedDL` to active `checkingDL`
  - qB has no owner rows for either hash
- Interpretation:
  - this appears to be the correct RT-side fix
  - let the RT checks settle before any further mutation

## 2026-04-20 Orphan Rename Prep Wave Outcome

- Wave 5 executed as an audit / dry-run prep lane for `orphaned_data -> orphans`.
- On-disk state:
  - `/pool/media/torrents/orphaned_data` exists and is populated
  - `/pool/media/torrents/orphans` does not exist yet
  - `/stash/media/torrents/orphaned_data` exists but is empty
  - `/stash/media/torrents/seeding/orphaned_data` exists but is empty
- Current live blocker:
  - qB still has one live row under `/pool/media/torrents/orphaned_data/...`
  - `f37b9983d27409b4d17d30948ce38b4e021935fb`
  - state `stoppedUP`
- RT cache showed no current `orphaned_data` directory rows during this audit pass.
- First dry-run batch shape is now known:
  - `Aither (API)`
  - `Darkpeers (API)`
  - `DigitalCore (API)`
  - `DocsPedia`
  - `FearNoPeer`
- Code/config refs still hardcoding `orphaned_data` were reconfirmed in:
  - `src/hashall/orphan_sweep.py`
  - `src/hashall/cli.py`
  - `src/hashall/content_inventory.py`
  - `~/dev/sys/docker/qbit_manage/config*.yml`
  - `~/dev/sys/docker/qbit_manage/bin/promote_recycle_to_seeds.sh`
  - `~/dev/sys/docker/qbit_manage/bin/check_pool_orphans.sh`
- Operational rule:
  - do not run a broad orphan rename until the live qB row is moved off `orphaned_data`

## 2026-04-20 Live Orphan-Path Blocker Wave Outcome

- Wave 6 executed on the one live qB orphan-path row:
  - `f37b9983d27409b4d17d30948ce38b4e021935fb`
- qB save path was moved from:
  - `/pool/media/torrents/orphaned_data/FileList.io/_qb-unique-repair/f37b9983d27409b4d17d30948ce38b4e021935fb`
- to:
  - `/pool/media/torrents/orphans/FileList.io/_qb-unique-repair/f37b9983d27409b4d17d30948ce38b4e021935fb`
- Post-wave live state:
  - qB remained `stoppedUP`
  - qB now has no live `orphaned_data` rows
  - the old legacy file path is gone
- Operational result:
  - the orphan rename lane is no longer blocked by live qB state

## 2026-04-20 First Orphan Rename Batch Outcome

- Wave 7 executed on `/pool/media/torrents/orphaned_data` using same-filesystem atomic `mv`.
- Batch roots moved to `/pool/media/torrents/orphans`:
  - `Aither (API)`
  - `Darkpeers (API)`
  - `DigitalCore (API)`
  - `DocsPedia`
  - `FearNoPeer`
- Interrupted-rsync residue:
  - `Aither (API)` had a partial destination copy from the aborted rsync attempt
  - it was preserved as:
    - `/pool/media/torrents/orphans/.aborted-rsync-Aither (API)-20260420-1720`
  - then the full source tree was moved atomically into place
- Post-wave state:
  - the 5 batch roots are gone from `/pool/media/torrents/orphaned_data`
  - the 5 batch roots exist under `/pool/media/torrents/orphans`
  - qB still has no live `orphaned_data` rows
- Operational rule:
  - continue remaining orphan batches with same-device `mv`, not rsync

## 2026-04-20 Second Orphan Rename Batch Outcome

- Wave 8 executed as the next clean atomic-rename batch.
- Moved to `/pool/media/torrents/orphans`:
  - `It.Ends.With.Us.2024.MULTi.1080p.BluRay.x264-LYPSG`
  - `LinkedIn - Premiere Pro Guru: Fixing Video Color and Exposure Problems`
  - `OnlyEncodes (API)`
  - `PrivateHD`
- Stash side:
  - created canonical `/stash/media/torrents/orphans`
  - stash legacy orphan dirs remain empty
- New blocker:
  - `FileList.io` exists in both legacy and canonical trees
  - treat it as a merge case, not a blind top-level rename
- Operational rule:
  - keep using atomic `mv` for non-conflicting top-level roots
  - handle `FileList.io` in a planned sub-batch

## 2026-04-20 FileList.io Orphan Merge Outcome

- Wave 9 resolved the first merge case:
  - `/pool/media/torrents/orphaned_data/FileList.io`
- Method:
  - atomic `mv` for the six non-conflicting children
  - narrow inspection of the overlapping `_qb-unique-repair` subtree
  - cleanup of empty legacy directories after verification
- Result:
  - legacy `/pool/media/torrents/orphaned_data/FileList.io` is gone
  - canonical `/pool/media/torrents/orphans/FileList.io` remains
  - qB still has no live `orphaned_data` rows
- Operational rule:
  - use this same split / inspect / remove-empty pattern for future orphan merge cases
  - catalog payload remains incomplete and still points back to `/stash/...`
- `c8f01321...` `The.Matrix.Reloaded...`
  - runtime `save_path=/data/media/torrents/seeding/movies`
  - runtime `content_path` missing on disk
  - catalog payload row is effectively empty:
    - `payload_hash=NULL`
    - `file_count=0`
    - `total_bytes=0`
    - `status=incomplete`
  - this is the same donor-looking repair case now handled by the updated repair classifier

**Historical carve-outs vs current live state:**
- `Alien Romulus`
  - no current live qB match by name/save path
  - keep as historical special-case context, but do not treat it as the current live blocker
- `Shining Girls`
  - current live qB match exists on `/pool/media`:
    - `57c38fa86c83c211a6233c8302afde1bd14c6ace`
    - state `stoppedUP`
    - path `/pool/media/torrents/seeding/cross-seed/TorrentDay`
  - this is not part of the current failed-ish qB cluster, but it remains historical content-conflict context
- `West Wing`
  - no current live qB match by name/save path
  - keep as historical proving-lane context, not as the current live migration blocker

## 2026-03-26 Read-Only Duplicate Reclaim Report

**New tool:**
- `hashall content reclaim-report`
- Purpose:
  - use exact duplicate tree hashes from the `hashall` DB to produce a ranked `keep` / `purge`
    candidate report across filesystems
  - feed a later review/apply script instead of deleting blindly

**Current live result:**
- Example run:
  - `hashall content reclaim-report --db ~/.hashall/catalog.db --root /pool/data/seeds --root /pool/data/orphaned_data --root /pool/media/torrents/seeding --limit 10`
- Top-10 exact duplicate groups report `3,563,147,846,965` bytes of candidate reclaim.

**Important safety caveat:**
- This is a candidate feed, not a deletion plan.
- The current top groups include many duplicates entirely inside active `/pool/media` seeding trees,
  especially:
  - `_rehome-unique`
  - `cross-seed/*`
- So the immediate value is:
  - find high-value duplicate families quickly
  - feed an evaluation script that also checks qB liveliness / active ownership / policy
- The immediate value is **not**:
  - purge those reported paths directly

**Operational meaning:**
- Yes, the `hashall` DB is now good enough to generate duplicate-candidate feeds across
  filesystems.
- No, the current report alone is not sufficient to auto-delete.
- The next layer should enrich these candidate groups with:
  - live qB ownership
  - whether the path is the only currently seeded copy
  - whether the path is inside known active seeding or unique-view trees
  - operator policy for donor/archive trees

## 2026-03-26 Migration Pivot Sitrep

**Priority reset:**
- Repair/content follow-up work is paused at a good-enough stop point.
- Active priority is back on `pool/data -> pool/media` migration.

**Current blocker:**
- Live `df -h` now shows both target datasets full:
  - `/pool/data`: `0` available
  - `/pool/media`: `0` available
- This is the immediate reason migration cannot resume.

**Current migration-side catalog picture:**
- `26` qB rows still save under `/pool/data`
- `361` qB rows save under `/pool/media`
- `87` payload rows still root under `/pool/data`
- `242` payload rows root under `/pool/media`

**Historical carve-out notes need to be read carefully:**
- `Alien Romulus` and `West Wing` are not current live qB blockers by name/save path.
- `Shining.Girls...` still exists live on `/pool/media`, but it is not currently in the failed-ish qB set.
- Current live qB attention should be on the 9-item failed-ish cluster above, not on stale carve-out shorthand.

**Immediate next actions:**
1. Reclaim pool headroom.
2. Reassess the remaining clean migration candidates after reclaim, using the current 9-item failed-ish qB cluster instead of the older carve-out shorthand.
3. Generate the next carve-out-safe `pool/data -> pool/media` batch.

**Current next-safe batch artifact:**
- A fresh targeted batch plan is ready at:
  - `out/rehome-plan-pool-data-to-media-nextsafe-2026-03-26.json`
- It deliberately excludes:
  - the current failed-ish qB movie-family rows
  - `Alien Romulus`
  - `Shining Girls`
  - `Transformers.One`
- Included payloads:
  - `The.Substance.2024...` directory root
  - `The.Substance.2024...` single-file root
  - `The.Edge.of.Sleep.S01...`
  - `The Last Stop in Yuma County...`
  - `UEFA.Europa.Conference.League...`
- Dry-run status:
  - `hashall rehome apply out/rehome-plan-pool-data-to-media-nextsafe-2026-03-26.json --dryrun`
  - passed cleanly with `5` `MOVE` plans and no planner/executor surprises
- Batch size:
  - `34,821,012,982` bytes total (`~32.4 GiB`)
- Current blocker remains capacity:
  - live `df -h` still shows `0` available on both `/pool/data` and `/pool/media`
  - so this batch is ready but not yet safe to execute for real

## 2026-03-26 Non-qB Upgrade Scan Complete

**Completed work:**
- A non-qB upgrade scan completed in tmux session `hashall-nonqb-scan` to improve full-hash
  coverage for donor / duplicate-tree analysis.
- Command sequence:
  - `hashall scan /pool/data/orphaned_data --hash-mode upgrade --drift-policy quick`
  - `hashall scan /pool/data/seeds --hash-mode upgrade --drift-policy quick`
  - `hashall scan /pool/data/RecycleBin --hash-mode upgrade --drift-policy quick`
- Log:
  - `~/.logs/hashall/nonqb-scan-20260326.log`

**Why this is the right scan shape:**
- Quick hashes already existed for the major non-qB trees.
- The missing value was mostly SHA256 coverage, not basic filesystem discovery.
- This upgrade pass improves exact duplicate-tree / donor discovery without first redesigning the
  qB-scoped `payloads` model.

**Final coverage after completion:**
- `/pool/data/orphaned_data`
  - `19134` files
  - `2.49T`
  - quick-hash coverage: `19134/19134`
  - SHA256 coverage: `19134/19134`
- `/pool/data/seeds`
  - `1255` files
  - `3.70T`
  - quick-hash coverage: `1255/1255`
  - SHA256 coverage: `1255/1255`
- `/pool/data/RecycleBin`
  - `63` files
  - `690.4M`
  - quick-hash coverage: `63/63`
  - SHA256 coverage: `63/63`
- `/pool/data/cross-seed-link`
  - `1327/1327` files already had SHA256
- `/pool/data/cross-seed`
  - `14/14` files already had SHA256

**First inventory milestone after the scan:**
- `hashall content inventory` now provides a read-only report over canonical non-qB roots derived
  from `files_*`.
- Root discovery was then refined to stop treating broad container directories as single roots.
- Current live discovery across `orphaned_data`, `seeds`, and `RecycleBin` now finds `14030`
  canonical roots in about `1.3s` on the live catalog.
- Current live `hashall content duplicates` reports `23` exact duplicate groups at this refined
  root-discovery level.
- Representative discovered roots now visible to operators include:
  - `/pool/data/seeds/_qb-unique-repair/ce2445dd26a9f1db43057dceb91f928267060689/The.West.Wing.S02.1080p.AMZN.WEB-DL.DD+2.0.H.264-AJP69`
  - `/pool/data/seeds/_qbm_recycle/PrivateHD/River.Monsters.S04.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb`
  - `/pool/data/seeds/RecycleBin/public/Doraemon.1979.S01.ITA.SD.TvRip.AC3.XviD`
  - loose single-file roots under `/pool/data/orphaned_data/movies`
  - loose single-file roots under `/pool/data/orphaned_data/shows`
  - per-file roots under `/pool/data/orphaned_data/books/*`

**Immediate next implementation targets after this scan stage:**
1. Expand the new read-only `content` reporting into a durable non-qB content inventory layer.
2. Keep `content donors --torrent` wired into repair as a ranked planner input, but do not
   auto-select donors yet.
   - current known limitation: fully empty broken qB payload rows (`payload_hash=NULL`,
     `file_count=0`, `total_bytes=0`) can still evade generic donor ranking
3. Pivot priority back to `pool/data -> pool/media` migration once the durable inventory plan is
   documented.

## 2026-03-25 Repair Fastresume Root Corruption Audit

**Finding:**
- The external report at `/mnt/config/docker/.agent/worktrees/cr-docker-20260323-114236-codex/docs/hashall-bug-9a731a-fastresume-root-corruption-20260325.md`
  identified a real current bug in `hashall` repair logic.
- `src/hashall/qb_repair_payload_group.py` was anchoring repair to `broken_info.save_path`
  from the live qB runtime and could persist that path into fastresume.
- If qB runtime had already drifted to a bad root such as `/tmp`, repair could cement that bad
  root into:
  - `save_path`
  - `qBt-savePath`

**What was fixed:**
- Repair target-save-path selection is now anchored to catalog state rather than blindly trusting
  the broken torrent's current runtime save path.
- The repair path now logs:
  - old runtime save path
  - chosen target save path
  - reason for the choice
- This specifically closes the `/tmp` persistence path described in the external report.

**Scope assessment:**
- The confirmed bug was in the repair flow, not in the normal guarded rehome apply path.
- Rehome already chooses target paths from planner/output state rather than from the broken
  torrent's current runtime `save_path`.

**Validation:**
- `pytest -q tests/test_qb_repair_payload_group.py`
- result: `13 passed`

## 2026-03-25 Non-qB Tree Scan Coverage Audit

**Finding:**
- The `/pool/data` coverage gap is real, but it is primarily a product-model gap, not a failed
  scan.
- Current code and requirements define a payload as:
  - "the on-disk content tree a torrent points to"
- Current refresh behavior is therefore:
  1. `hashall scan` populates per-device `files_*` tables for scanned filesystems
  2. `hashall payload sync` connects to qB and materializes `payloads` only for qB torrent roots
- That explains the current mismatch:
  - `scan /pool/data` ran successfully
  - current catalog still shows:
    - `0` payload rows under `/pool/data/orphaned_data`
    - `17` under `/pool/data/cross-seed-link`
    - `6` under `/pool/data/cross-seed`
    - `43` under `/pool/data/media`
    - `21` under `/pool/data/seeds`
    - `87` total under `/pool/data`
  - only `26` `torrent_instances` currently point anywhere under `/pool/data`

**Assessment:**
- This does not match the operator intent of hashing as much content as possible for:
  - `cross-seed`
  - `jdupes`
  - `hashall`
  - pool-space analysis / reclaim planning
- But it does match the current qB-centric payload model in the requirements and code.

**Recommended remedy:**
- Do **not** silently redefine `payloads` to mean "all scanned content."
- Keep `payloads` as qB/torrent-root inventory.
- Add a second durable content-inventory layer for non-qB trees under managed scan roots.
  - inputs: `files_*` + selected managed roots
  - outputs: canonical non-qB content roots / content groups for archive, orphan, and donor trees
  - consumers:
    - cross-seed donor analysis
    - jdupes / dedup planning
    - reclaim / orphan policy analysis
    - future operator reporting
- If that broader inventory is not desired, then the requirements must explicitly state that
  non-qB managed-tree coverage is out of scope so operators do not assume whole-tree DB coverage.

**Intent clarification:**
- The operator goal is not just "scan more paths."
- The intended end state is:
  - hash folder trees broadly
  - find exact duplicate folder trees quickly
  - surface non-qB donor trees that may repair qB runtime / fastresume drift
  - compare archived/orphaned content against live qB payload families
- A broader non-qB inventory layer is therefore the preferred model; blind expansion of `payloads`
  is not.

## 2026-03-25 Pool Headroom Snapshot

**Current state:**
- `df -h` now shows the pool datasets effectively full again:
  - `/pool/data`: `27G` free
  - `/pool/media`: `27G` free

**Top-level `/pool/data` usage snapshot:**
- `/pool/data/orphaned_data`: `2.3T`
- `/pool/data/seeds`: `1.2T`
- `/pool/data/media`: `567G`
- `/pool/data/cross-seed-link`: `413G`
- `/pool/data/cross-seed`: `68G`
- `/pool/data/RecycleBin`: `690M`

**Largest immediate policy/reclaim candidates:**
1. `/pool/data/orphaned_data` (`2.3T`)
   - largest space opportunity by far
   - but still configured as `cross-seed` donor input today
   - subtrees:
     - `shows` `693G`
     - `movies` `609G`
     - `cross-seed` `463G`
     - `books` `213G`
     - `_flat` `139G`
2. `/pool/data/seeds` (`1.2T`)
   - likely highest-value next audit zone after orphan policy
   - notable subtrees:
     - `cross-seed` `458G`
     - `_qbm_recycle` `319G`
     - `_qb-unique-repair` `180G`
     - `RecycleBin` `140G`
3. `/pool/data/cross-seed-link` (`413G`)
   - should not be bulk-deleted blindly
   - current catalog/qB only see a small active subset there, but broader non-qB visibility is
     incomplete under the current model

**Recommended reclaim order:**
1. Decide orphan-donor policy first.
   - If orphaned data is no longer meant to feed `cross-seed`, remove it from `cross-seed`
     `dataDirs` and reclaim there first.
2. Audit `/pool/data/seeds` next, especially `_qbm_recycle`, `RecycleBin`, and
   `_qb-unique-repair`.
3. Only then consider broader cleanup under `/pool/data/cross-seed-link` / `cross-seed`, because
   current catalog coverage there is not enough to support blind deletion.

## 2026-03-21 Fastresume Rollback Fix

**Version:**
- `hashall=0.8.9`

**New fix in code:**
- hardened fastresume failure handling now restores fastresume backups when patching had already
  succeeded but a later post-patch step failed
- qB is then restarted after backup restore so runtime metadata can return to the pre-run source
  paths instead of remaining stranded on `/pool/media`

**Why this was needed:**
- the `0.8.8` live `West Wing` retry showed all five siblings in `missingFiles` on `/pool/media`
  even though the target files were gone
- fastresume backups from the failed patched run still existed, which confirmed rollback had not
  restored them automatically

**Validation:**
- focused fastresume rollback regressions passed

## 2026-03-21 qB Runtime Settle Fix

**Version:**
- `hashall=0.8.8`

**New fix in code:**
- hardened fastresume post-patch now waits for qB restart/auth settle before runtime verification
- runtime `save_path` verification now requires live qB API data and ignores cache-fallback reads
- if runtime `save_path` stays stale after a good fastresume patch, executor retries with an
  explicit `set_location()` nudge before failing
- post-patch qB accounting now waits to settle, but still fails fast for clear bad states
  (`pausedDL`, `stoppedDL`, `downloading`, nonzero `amount_left`)

**Why this was needed:**
- the prior `West Wing` pilot already proved copy, verify, view build, and sibling relocate
- the remaining failure was qB runtime handoff after restart, not another data-path problem

**Validation:**
- rehome regression pack: `81 passed`
- live dry-run of `out/rehome-plan-west-wing-s02-2026-03-21-v087.json` completed cleanly

## 2026-03-21 Content-Proofed Reuse + Shining Girls Conflict

**Version:**
- `hashall=0.8.7`

**New fix in code:**
- target-family reuse is now proven from live file content, not just file count / total bytes
- planner + executor compute a real payload hash from the current files before treating a target
  family as reusable
- same-size same-byte sibling roots that differ by content now block before apply instead of
  falling through to target-view preflight

**What this exposed:**
- `Shining.Girls...` on `/pool/media` is a real target-side content conflict
- `TorrentDay` and `Aither` sibling roots match by counts/bytes but differ by actual content
- this is a data repair problem, not another planner/apply bug

**Validation:**
- targeted rehome sim suite: `78 passed`
- `West Wing` fresh live dry-run on 2026-03-21 remains a clean `MOVE`
- `Shining Girls` live plan generation is expected to run longer now because it hashes the actual
  files to prove or reject reuse

## 2026-03-20 West Wing Rehome Root Cause + Current Dry-Run State

**Version:**
- `hashall=0.8.6`

**Root cause of the bad 2026-03-20 `West Wing S02` run:**
- planner chose `MOVE` from the absence of one canonical target root and ignored alternate sibling
  target views already present on `/pool/media`
- target-view preflight mutated existing target files instead of only comparing them
- rollback removed a pre-existing good `/pool/media` sibling view because it did not track which
  views were created by the current run

**Fixes now in code:**
- family-level target reuse before donor copy
- fail-fast alternate-sibling conflict detection before rsync
- read-only target-view preflight
- rollback only deletes target views created in the current run
- extra `failure-pre-rollback` and `failure-post-rollback` reality snapshots

**Fresh live dry-run on 2026-03-20 (`/pool/data/media/torrents/seeding` → `/pool/media/torrents/seeding`):**
- `Shining.Girls...` -> `REUSE`
- `The.West.Wing.S02...` -> `MOVE`
- `Alien Romulus` -> `MOVE`

**Important current reality for `West Wing`:**
- the old good `/pool/media` sibling donor is already gone from the earlier buggy run
- so the new live plan correctly reports:
  - `target_family_exact_views=0`
  - `target_family_conflicts=0`
- this is expected current reality, not another planner miss

**Recommended pilot after this fix set:**
- pilot the `Shining.Girls...` `REUSE` family first
- do **not** expect `West Wing` to be a reuse pilot until a good target-side donor exists again

## 2026-03-19 Migration Analysis

**Live counts (as of 2026-03-19):**
- Pool-data torrents remaining: `old_path_count=41` (up from 34 in 2026-03-13 docs)
- Pool-media torrents: `new_path_count=344`
- `/stash` torrents: `0`
- Migration seed-root-state: `in_progress`

**Current live split of the 41 pool-data torrents (confirmed from qB cache on 2026-03-19):**
- `8` under `/pool/data/media/torrents/seeding`
- `28` under `/pool/data/cross-seed-link`
- `5` under `/pool/data/cross-seed`
- state mix: `40 stalledUP`, `1 uploading`

**Wrapper warning — `bin/migrate-pool-data-to-media.sh` is not the full 41-torrent resume path:**
- The wrapper's default `SOURCE_ROOT` is `/pool/data/media/torrents/seeding`.
- A dry-run on 2026-03-19 selected only the `8` torrents under that exact root.
- It did **not** include the other `33` remaining `/pool/data` torrents under
  `/pool/data/cross-seed-link` and `/pool/data/cross-seed`.
- The wrapper dry-run also included `Alien Romulus`, which remains a deliberate repair/proving lane
  and should not be treated as a normal plain-migration batch item.
- Practical meaning: use the fresh `relocate-plan` flow to reason about the full `41`-torrent
  remainder; do not assume the wrapper resumes the whole lane as-is.

**Current special cases within the live 41-torrent remainder:**
- `Alien Romulus` (`1376e795...`) remains a real special-case/proving lane item:
  - still lives under `/pool/data/media/torrents/seeding/cross-seed/hawke-uno`
  - still tagged `~noHL`
  - still belongs to the mixed sibling family called out in the active project docs
  - status: **not resolved** for plain migration batching
- `Shining.Girls...` remains a known bad reuse candidate:
  - live pool-data hashes are `57316294...`, `0fff0ce2...`, and `4511c5f4...`
  - the two rows under `/pool/data/media/torrents/seeding` are exactly the ones the old wrapper
    would try to include
  - project continuity docs already say to exclude this group from future plain batches
  - status: **not resolved** for plain migration batching
- `The.West.Wing.S02...` appears as a multi-row family in the old wrapper dry-run:
  - hashes `62c3d90c...`, `cbe76a6e...`, `ce2445dd...`, `2179ba97...`, `71cdd51d...`
  - this is not a blocker by itself, but it confirms the wrapper is row/per-torrent oriented rather
    than a clean "unique payload family" batcher
  - status: **not a separate blocker**, but a reason to prefer `relocate-plan` over the wrapper
- `V for Vendetta` remains only a refresh follow-up anomaly, not an active migration blocker
  for the pool-data remainder

**Blockers — must resolve before resuming migration:**

1. **Stale rehome.lock** (`~/.hashall/rehome.lock`)
   - Lock is 5 days old (last written 2026-03-14 10:02)
   - Process is almost certainly dead; verify and remove:
     ```bash
     cat ~/.hashall/rehome.lock
     ps -p <pid-from-lock> || echo "process dead → safe to remove"
     rm ~/.hashall/rehome.lock
     ```

2. **640 consecutive qB API failures** in cache meta
   - Cache is fresh (`source=daemon_live`, updated `2026-03-19T15:32`)
   - Failure count may be a transient artifact from a qB restart; verify before trusting plan output:
     ```bash
     python3 -c "
     import json, pathlib
     m = pathlib.Path.home() / '.cache/hashall-qb/torrents-info.meta.json'
     d = json.loads(m.read_text())
     print('last_error:', d.get('last_error'))
     print('last_error_at:', d.get('last_error_at_iso'))
     print('consecutive_failures:', d.get('consecutive_failures'))
     print('source:', d.get('source'))
     "
     hashall qb status 2>&1 | head -5
     ```

3. **Catalog freshness** — confirm before running a new plan:
   ```bash
   hashall refresh --verbose 2>&1 | tail -20
   ```

**Cross-repo naming note:**
- The external dashboard/cache repo previously referenced in older notes as `qbitui` is now `silo`.
- Treat `silo` as canonical. Any `qbit-*` names in that repo are compatibility shims, not the preferred integration target.

**Phase 0 → Phase 1 resumption workflow:**
```bash
# Phase 0: clear blockers (operator)
rm ~/.hashall/rehome.lock        # only after confirming process dead
hashall qb status                # verify live API responds
hashall refresh --verbose        # confirm catalog fresh

# Phase 1: generate fresh plan
hashall rehome relocate-plan \
  --source-root /pool/data \
  --target-root /pool/media/torrents/seeding \
  --output out/rehome-plan-pool-data-to-media-2026-03-19.json \
  2>&1 | tee ~/.logs/hashall/rehome/relocate-plan-2026-03-19.log

# Phase 1: verify plan covers all 41 qB pool-data torrents
python3 -c "
import json, pathlib
cache = json.loads((pathlib.Path.home()/'.cache/hashall-qb/torrents-info.json').read_text())
torrents = cache if isinstance(cache, list) else cache.get('result', cache.get('torrents', []))
pool_data = [(t.get('hash',''), t.get('name','')[:60], t.get('state',''))
             for t in torrents if '/pool/data' in t.get('save_path','')]
plan = json.loads(pathlib.Path('out/rehome-plan-pool-data-to-media-2026-03-19.json').read_text())
plan_hashes = {h for p in plan.get('plans', []) for h in (p.get('affected_torrents') or [])}
print(f'qB pool-data torrents: {len(pool_data)}')
print(f'Plan covers: {len(plan_hashes)} hashes')
for hash_, name, state in pool_data:
    covered = '✓' if hash_ in plan_hashes else '✗ NOT IN PLAN'
    print(f'  {covered}  {state:15s}  {name}')
"
```

**Notes on 2026-03-18/19 code audit (may affect plan output):**
- `planner.py` bind-mount false-positive fix: may reclassify previously-BLOCKED candidates
- `planner.py` single-torrent unique-view fix: target paths change for 1-torrent payloads
- Both are LOW-risk corrections; executor logic unchanged

---

Last updated: 2026-03-13 (historical section below)

## Live Reality / Drift

- `hashall` is now `0.8.5` (see version history below for prior milestones).
- New 2026-03-15 qB compatibility/cache hardening:
  - local cache implementation now lives in this repo:
    - `src/hashall/qb_cache.py`
    - `bin/qb-cache-agent.py`
    - `bin/qb-cache-daemon.py`
  - the cache now uses the shared qB client, not silo’s legacy pre-refactor raw-API implementation
  - `src/hashall/qbittorrent.py` now detects and caches a qB server profile:
    - `app_version`
    - `webapi_version`
    - `qt_version`
    - `libtorrent_version`
  - state alias normalization is now centralized:
    - `pausedDL` / `stoppedDL` => `stoppedDL`
    - `pausedUP` / `stoppedUP` => `stoppedUP`
  - current cache root:
    - `~/.cache/hashall-qb/`
  - current read-heavy scripts using that cache:
    - `qb-checking-watch`
    - `qb-start-seeding-gradual`
    - `qb-path-watch`
    - PD triage/score/finder scripts
    - triage step scripts
    - `qb-repair-batch` list discovery reads
  - important limit:
    - silo’s external dashboard/cache path has not been updated in this repo; treat that as separate follow-up work if cross-repo alignment is still wanted
- Active docs are now intentionally minimal and stub-free:
  - canonical active docs:
    - `README.md`
    - `docs/README.md`
    - `docs/REQUIREMENTS.md`
    - `docs/architecture/SYSTEM.md`
    - `docs/tooling/CLI-OPERATIONS.md`
    - `docs/tooling/REHOME-RUNBOOK.md`
    - `docs/operations/RUN-STATE.md`
    - `docs/project/AGENT-PLAYBOOK.md`
    - `docs/project/PLAN.md`
  - continuity docs:
    - `docs/handoff.md`
    - `docs/ops-log.md`
    - `docs/next-agent.md`
    - `docs/NEXT-AGENT-PROMPT.md`
  - superseded material now lives in `docs/archive/2026-doc-consolidation/`
- Anchor the current migration/rehome model on this invariant:
  - each qB item needs its own correct payload tree on disk
  - that tree should normally be instantiated from donor content via hardlinks
  - `unique target` means unique per-item file structure, not mandatory duplicate physical copies
- New 2026-03-14 content-drift hardening:
  - `hashall scan` now has `--drift-policy metadata|quick|full`
  - `hashall refresh` / `rehome refresh` now thread through:
    - `--scan-hash-mode fast|full|upgrade`
    - `--drift-policy metadata|quick|full`
  - unchanged-file behavior is now explicit:
    - `metadata` trusts unchanged size+mtime
    - `quick` recomputes quick hashes on unchanged files and escalates to full hashing if drift is detected
    - `full` recomputes full hashes for unchanged files in scope
  - targeted validation:
    - `pytest tests/test_scan_hardlinks.py tests/test_scan_incremental.py tests/test_rehome_refresh_safety.py -q`
    - result: `36 passed`
- New 2026-03-13 duplicate-byte hardening:
  - `src/rehome/view_builder.py` now relinks preexisting identical destination files to the donor inode instead of silently accepting copied bytes
  - `bin/qb-repair-fresh.py` now normalizes existing identical targets the same way
  - this closes the known “successful run leaves new jdupes groups behind” leak in both the rehome path and the fresh repair-prep path
- New 2026-03-13 refresh / jdupes diagnosability hardening:
  - the previous `refresh --verbose` orchestration did not remain alive as a clear owner of the dedupe backlog after step 3.5
  - observed failure signature:
    - `refresh --verbose` run `pid=1386781` reached pool-media dedupe planning
    - `27` duplicate groups were surfaced
    - a failing group like `Cinderella.2021...` only appeared deep in jdupes group logs as `jdupes did not link files with matching SHA256`
  - hardening now added:
    - `hashall link execute` prints the jdupes log glob for the plan and a failed-action preview when link failures occur
    - `bin/db-refresh-step4_5-link-dedup.sh` now writes a structured per-device summary JSON and logs the plan status / failed-action preview after dry-run and apply
  - operator meaning:
    - a refresh/dedupe run should now end with an explicit step-3.5 summary artifact instead of forcing diagnosis from a raw shared log tail
  - latest refresh status:
    - `~/.logs/hashall/rehome/refresh/20260313-172217.log`
    - ended `OK`
    - one follow-up anomaly remains:
      - root `99/99` `V.for.Vendetta...` under `/pool/media/torrents/seeding/cross-seed/hawke-uno/...`
      - logged `files=0 bytes=0`
      - `Upgrade ended incomplete: groups=0`
    - this is an explicit backlog item, not a refresh-run failure
- New 2026-03-13 planner stale-no-op hardening:
  - `relocate-plan` now skips groups when all per-hash view targets already have `source_save_path == target_save_path`
  - this removes fully converged families from the live remainder even when source cleanup is still deferred
  - live proof:
    - `Brave.New.World.US.S01...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-114142-66eebb2df636b12a/`
    - refresh-seeded stale-no-op trimming dropped the older remainder from `31` (`refresh8`) to `29` (`refresh9`)
- New 2026-03-13 Twisters bridge hardening:
  - surviving target donors are now preferred for stale already-targeted rows
  - single-file unique targets preserve `root_dir/file` layout
  - mixed `reconcile_subset + patch_one` hardened manifests now work
  - validate/patch failures after `qb_stop` now restart qB before returning
  - reality snapshots now call this class `stale_runtime_and_fastresume_root`
  - live proof:
    - `Twisters.2024...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-112558-9962465e30b69544/`
    - `9/9` rows verified `exact_tree`
    - `reconcile_rows=8 patch_rows=1`
- New 2026-03-13 de-hitchhike invariant:
  - root-to-root relocation planning now defaults multi-hash groups to per-hash unique target roots
  - missing-file reconnect plans now do the same
  - stash->pool `rehome` view planning now also routes multi-hash groups into `_rehome-unique/<hash>` targets
  - successful attaches now remove an unused intermediate donor root when the full sibling group is covered in-plan
  - operator meaning:
    - newly constructed migrations/reconnects should stop manufacturing fresh N->1 hitchhiker targets
    - older shared-target groups remain visible as legacy debt until explicitly de-hitchhiked
    - the replacement form is a unique per-item payload tree backed by hardlinks, not a separate byte copy per item
  - targeted validation for this slice:
    - `pytest tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py tests/test_rehome_mapping.py tests/test_rehome_catalog_sync.py -q -k 'unique or payload_rows or preflight_existing_view_conflicts_logs_progress_for_missing_targets'`
    - `pytest tests/test_rehome_atomic_relocation.py -q -k cleanup_unused_target_donor_removes_intermediate_root`
    - result: `7 passed`
- Earlier live proof under the older pre-fix planner:
  - `Cinderella.2021...` completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260313-095751-578fffbfe4fc2f8c/`
  - qB ended healthy on `/pool/media/...`
  - its post snapshot still warned about one shared payload row because the run started before the de-hitchhike planner landed
- Current live remainder after the Twisters + Brave success is now seeded from live qB old-root rows:
  - `old_path_count=34`
  - `new_path_count=317`
  - qB health snapshot:
    - `stalledup=5152`
    - `stoppeddl=1` (`Alien Romulus`, real repair lane)
    - `stalleddl=2` (non-pool-data `/data/media/.../radarr` outliers)
  - next source-of-truth artifact:
    - `out/rehome-plan-pool-data-to-media-liveqb-20260313.json`
    - `seed_scope=live_qb_root`
    - `qbit_hashes=34`
    - `mapped_payloads=14`
    - `candidates=14`, `reuse=7`, `move=7`, `skipped=0`
    - `covered old-root hashes=34/34`
- New explicit next proving task:
  - use the `Alien Romulus` payload family as the next focused `rehome` / repair / `~noHL` engineering lane after the current cleanup + planner work
  - current observed live shape:
    - `14` sibling candidates
    - `7` `~noHL` siblings
    - one known incomplete row (`1376e795...`, `PD`, about `43.72%`) that remains repair-lane only
    - multiple healthy `/data/...` siblings that should be usable as donor candidates
  - engineering objective:
    - prove that `~noHL` siblings can be lifted to `pool-media`
    - ensure each resulting qB item gets its own correct payload tree there
    - keep those per-item trees hardlink-backed instead of creating redundant physical byte copies
  - do not treat this as a plain pool-data remainder batch item; it is a deliberate feature/proving task

- `hashall` is now `0.6.8`.
- Latest 2026-03-12 preflight feedback note:
  - `preflight_target_views` now emits bounded heartbeat lines during long existing-target scans:
    - `preflight_target_views_progress`
    - `preflight_target_views_view_done`
    - `preflight_target_views_complete`
  - this closes the quiet UX gap where a large healthy target tree could look stalled between `step=verify_target` and `step=build_views`
- Latest 2026-03-12 guarded target-view note:
  - `rehome` now runs `step=preflight_target_views` before `build_views` on guarded `REUSE` / donor-target paths
  - any preexisting destination view file is compared read-only against the source before new hardlinks are created
  - if one target-view path already contains different bytes, the whole plan now aborts before any sibling view mutation
  - this closes the `Novitiate...` partial-view-build risk
  - live proof:
    - `The.Long.Walk.2025...` `REUSE` completed cleanly after this change
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-214219-38c7f2c20c7af677/`
  - current live pool-data baseline after the Twisters rerun:
    - `old_path_count=34`
    - `new_path_count=317`
    - qB health snapshot:
      - `stalledup=5152`
      - `stoppeddl=1` (`Alien Romulus`, real repair lane)
      - `stalleddl=2` (outside the pool-data lane)
- Latest stale reconnect hardening on 2026-03-12:
  - `qb-missing-remediate` now builds guarded reconnect plans for `root_drift_after_rehome_reuse` rows when the mapped target payload exists under a different catalog `payload_hash`
  - that exact gap was proven live on `Peppermint...`:
    - `4` stale `/data/...` `missingFiles` rows
    - surviving payload already alive at `/pool/data/...`
    - previous behavior: `selected_plans=0`
    - current behavior: `selected_plans=1`, `verified=4`, `patched=4`
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-212329-4f2ac41db39d760f/`
  - resulting qB state:
    - `missingFiles=0`
    - `stoppedDL=1` (`Alien Romulus`, real repair lane)
    - `stoppedUP=4` (the reattached `Peppermint` rows left paused)
- `hashall` is now `0.4.181`.
- `rehome` now has a shared live-reality snapshot layer in `src/rehome/reality.py`.
- New proactive audit command:
  - `hashall rehome drift-audit --plan <plan.json> [--output <file>]`
- Each `rehome apply` run now writes live drift snapshots beside its hardened manifest:
  - `reality-pre.json`
  - `reality-post.json`
  - `reality-failure.json`
- Snapshot purpose:
  - compare qB runtime state, fastresume paths, catalog rows, and actual filesystem existence before trusting a plan
  - explain blocked/skipped rows in plain English instead of only raw qB state strings
- Latest verifier/reality follow-up on 2026-03-12:
  - `qb-libtorrent-verify.py` now treats instant-complete `exact_tree` results as healthy when libtorrent jumps directly to `seeding`/`stalledUP` without a visible `checking_files` transition
  - this closed the false-negative exposed by `David Khune - Wakanda - Native American Magic.epub`
  - `rehome` reality snapshots now classify plain source-only `MOVE` rows as `source_only` rather than `target_view_missing`
  - post-apply reality snapshots now downgrade short-lived target-side qB checking to:
    - row classification: `post_apply_settling`
    - group state: `settling_after_apply`
  - that means a clean apply no longer writes a misleading `blocked_qbit_transient` post snapshot just because qB is briefly checking the newly patched target
  - the `Wakanda` rerun completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260312-145812-6bb9bb5432f39cbb/`
- Latest proactive stale-sibling follow-up on 2026-03-12:
  - `rehome apply` now treats any plan file with a top-level `plans` list as a batch apply input, even when `batch=true` is absent
  - the reality layer now reports out-of-plan sibling coverage directly in each snapshot:
    - `payload_group_siblings`
    - `plan_rows`
    - `out_of_plan_siblings`
    - `group_warnings`
  - `hashall rehome drift-audit` now summarizes how many plans still have uncovered same-`payload_hash` siblings
  - executor logs those uncovered-sibling warnings during apply so later cleanup drift does not stay silent
- Current group-state outputs include:
  - `ready_catalog_reconcile`
  - `ready_repoint_or_reconcile`
  - `blocked_qbit_transient`
  - `blocked_incomplete`
  - `blocked_target_view_missing`
  - `mixed_attention_required`

## Pool Migration Status

- Donor acquisition and offline attach are the shared backbone for both `REUSE` and `MOVE`.
- The current rsync-based donor transfer is still the data mover; qB is metadata-only.
- `REUSE` continues in small batches; each apply must finish with `stoppedup`/`stalledup`, no new downloads, and clean cleanup messages.
- `qb-zfs-relocate` has already proven the guarded live `pool-data -> pool-media` mover for pilot batches.
- `qb-zfs-relocate` `v0.1.13` / `hashall 0.4.179` now include live-proven verifier fixes for both:
  - the `Mickey.17...` false-partial case
  - the `Wakanda` instant-complete false-negative case
  - qB source recheck completion now requires a real transition into/out of `checking*`
  - verify retries one time when quick/exact evidence is clean but libtorrent transiently reports `partial_match` in `downloading*`
  - verify also now promotes `exact_tree + verify_ratio=1.0 + no_recheck_transition + healthy upload state` to a successful result
- `rehome` now has an explicit root-to-root planner for this domain:
  - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding`
  - shared-root sibling collisions are now surfaced and get synthesized unique destination views.
- `rehome apply` now uses the hardened `qb-zfs-relocate` backend for donor verification, offline fastresume patching, restart checks, and deferred cleanup.
- Successful `MOVE` waves can now be drained safely after green apply:
  - `hashall rehome followup --cleanup` stages source roots into hidden `.rehome-cleanup-stage/<payload_hash>/...`
  - qB is observed on the target save paths before final delete
  - any qB regression restores the staged roots automatically
- Cross-device `REUSE` reruns now have a catalog-reconcile path:
  - if qB is already on the target save paths and offline verify passes, `rehome apply` logs `rehome_reconcile_only`
  - relocation validate/patch are skipped
  - catalog sync still runs and updates `torrent_instances` / target payload rows
- Mixed-state REUSE reruns now have a partial-reconcile path:
  - if a batch contains a subset of rows already repointed and verified, `rehome apply` logs `rehome_reconcile_subset`
  - the good subset is reconciled into the catalog
  - skipped/bad rows are left untouched instead of aborting the whole batch
- Non-reconcile `MOVE` runs now stop qB before patch-mode validate:
  - this avoids false `torrent_not_stopped` blocks after a successful copy + offline verify
  - the `Megalopolis.2024.REPACK...` live `MOVE` pilot proved this path on 2026-03-11

## Current `MOVE` Risk

- `MOVE` has been refactored to use the same offline fastresume attach constructor after donor acquisition.
- The new path now has a successful live pilot:
  - `Megalopolis.2024.REPACK...`
  - report dir `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
  - all three sibling views verified `exact_tree`
  - qB ended `stalledUP 100%` on `/pool/media/...`
  - source cleanup remained deferred/manual
- Long `MOVE` copy windows now stream rsync progress:
  - commit `21ea673`
  - new runs emit `copy_progress percent=... elapsed=... eta=...`
  - a long silent pause after `step=move_payload` on new runs is now abnormal
- Operational guard remains: scale `MOVE` in small batches even after the pilot; keep cleanup deferred until post-run observation is established.
- Do not treat `rehome auto` returning `0 MOVE groups` as the final answer for explicit root-to-root relocation anymore; use `rehome relocate-plan` for that case.
- The current safe model is unified:
  - use `rehome relocate-plan` or `rehome auto` for planning
  - use `rehome apply` for execution
  - keep `qb-zfs-relocate` available for direct wrapper-driven dataset migration or troubleshooting

## Refresh / Identity State

- The stale-root cleanup and stoppedDL repair lane are now reflected in refresh:
  - latest `hashall refresh --verbose` finished `OK`
  - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` returns `0`
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.
- Do not treat the prior `PARTIAL` refresh as the current truth forever; the stale-root qB cohort has since been remediated and refresh should be rerun after the remaining repair lane is reduced.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.
- `hashall rehome qb-missing-audit` now classifies stale-root `missingFiles` cohorts against qB, fastresume, and rehome history.
- Historical live audit result on 2026-03-08:
  - `49` `missingFiles` items mapped cleanly from old `/pool/data/...` roots to existing `/pool/media/...` payloads
  - tool classification: `root_drift_fastresume_stale`
  - interpretation: legacy stale-root drift, not current `qb-zfs-relocate` pilot mutations
- That stale-root `missingFiles` lane has now been remediated live.
- Current qB health snapshot:
  - `stalledUP=5144`
  - `uploading=1`
  - `stoppedUP=6`
  - `missingFiles=0`
  - no active `stoppedDL`
- The 2026-03-12 stale sibling-root drift cohort is now remediated:
  - original scope:
    - `Megalopolis...` (`4`)
    - `Cleverman.S02...` (`2`)
  - new reconnect CLI:
    - `hashall rehome qb-missing-remediate`
  - live result:
    - both payload groups were reattached successfully via guarded `REUSE`
    - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
  - the `6` current `stoppedUP` rows are the freshly reattached hashes intentionally kept paused after reconnect
- `qb-start-seeding-gradual` halt at `2026-03-08 14:34` is explained historically:
  - `35` halted hashes were a direct subset of the old audited `49`
  - the daemon tripped on preexisting `missingFiles` rows in protected scope, not on a newly started torrent

## Known Gaps

1. Shared-root payload groups can now be planned; the new execution path has now proven both single-plan pilots and a curated mixed batch, but not yet a live `2-to-1 -> 2-to-2` case.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The next live gap is scaling from the first successful curated mixed batch to another curated batch from the remaining clean candidates.
5. `hashall payload siblings` read-only catalog bug is fixed in commit `74ea2b5`; use that command freely against the live catalog now.
6. Cleanup is now hardened against stale sibling refs:
   - follow-up cleanup blocks when any same-`payload_hash` torrent row still points at a non-target device or old `/data`/`/stash` alias
   - this closes the cleanup hole that could strand stale sibling hashes after source removal
7. `Mickey.17...` is no longer a carve-out:
   - the original failure looked like bad source data because offline verify died around `71%` while qB still said `100%`
   - root cause was code, not content
   - direct source verify and a clean target-copy verify both proved `exact_tree`
   - rerun result on 2026-03-12: `MOVE` completed successfully and qB ended `stoppedUP 100%` on `/pool/media/...`
8. Staged follow-up cleanup is now proven live for pool-data and adjacent backlog groups:
   - one pilot payload plus six additional `/pool/data` groups completed `cleanup_result=done`
   - follow-up reconcile then converted the healthy catalog-only cleanup backlog into actionable groups
   - two final retries initially restored because of narrow source-side ownership/permission errors, then completed after targeted ownership fixes
   - post-cleanup qB remained healthy (`stalledUP=5147`, `uploading=4`)
   - same-pool migration waves no longer need to leave every green source payload behind

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## 2026-03-24 Current Must-Do vs Proposal Split

### Must Do

1. Let the live `hashall refresh --verbose` run finish before starting any other refresh.
   - A concurrent second refresh on 2026-03-23 failed with `sqlite3.OperationalError: database is locked`.
   - Current live owner was verified in tmux pane `%61`.
   - Treat parallel refresh as an operationally unsafe action.
2. After the live refresh completes, generate a fresh relocation plan for the active `/pool/data -> /pool/media/torrents/seeding` lane.
   - Do not trust older plan output after the in-flight refresh changes catalog freshness.
3. Keep the known carve-outs out of plain migration batches:
   - `Alien Romulus`
   - `Shining.Girls...`
4. Investigate why `hashall refresh` scanned `/pool/data` but the catalog does not represent the full `/pool/data` tree.
   - The completed 2026-03-22 refresh log explicitly ran `scan /pool/data`.
   - Current catalog counts show:
     - `0` payload rows under `/pool/data/orphaned_data`
     - `17` under `/pool/data/cross-seed-link`
     - `23` under `/pool/data/cross-seed`
     - `87` total under `/pool/data`
   - This does not match the operator expectation that all of `/pool/data` would be in the DB.
   - Important current finding:
     - `scan /pool/data` populates the per-device `files_*` tables.
     - `payloads` are only created when `build_payload()` is called for a specific root path.
     - In the refresh flow, those materialization calls are coming from `payload sync`, which iterates qB torrents rather than every scanned subtree.
   - Determine whether this is intended behavior, a documentation gap, or a real coverage bug.
5. Evaluate requirements and design gaps for non-qB tree scans, and propose a remedy.
   - Stated operator intent: hash as much content as possible, not only qB-backed roots.
   - Reason: `cross-seed`, `jdupes`, and `hashall` all benefit from a broader shared content inventory, including non-qB trees such as orphan/archive areas.
   - Review whether the current design is too qB-centric at payload-materialization time.
   - Produce a recommendation that covers:
     - whether non-qB subtrees under managed scan roots should become `payloads`
     - whether a separate content-index abstraction is needed
     - how orphan pruning and refresh semantics should change if broader coverage is intended
   - Treat this as a likely requirements/design gap unless non-qB trees are intentionally out of scope.
   - Compare intended behavior vs actual behavior for:
     - managed scan roots such as `/pool/data`
     - non-qB subtrees such as `/pool/data/orphaned_data`
     - downstream consumers: `cross-seed`, `jdupes`, `hashall` planning, and pool-space analysis
   - The remedy must name the ownership boundary:
     - broaden `payload` materialization beyond qB roots
     - or add a durable non-qB content inventory layer with clear refresh/prune semantics
   - If the current qB-centric behavior is intentional, document that requirement explicitly so operators do not assume whole-tree coverage.
6. Develop a concrete plan to increase headroom on `pool`.
   - Current state is now tighter again: about `27G` free on both `/pool/data` and `/pool/media`.
   - Recent relocation work is not improving reported free space enough to justify continuing blindly.
   - Produce ranked reclaim options with estimated GiB impact, dependency notes, and operational risk.
7. Re-validate the `West Wing` lane on current code before using it as a normal migration example if that lane is still pending.
   - Earlier bugs and rollback behavior changed the donor/view state enough that old assumptions are not trustworthy without a fresh check.
8. Review the external fastresume corruption report, investigate, and report findings.
   - Report path:
     - `/mnt/config/docker/.agent/worktrees/cr-docker-20260323-114236-codex/docs/hashall-bug-9a731a-fastresume-root-corruption-20260325.md`
   - Determine whether the report describes:
     - a current `hashall` bug still present in this branch
     - behavior already fixed by the recent fastresume / rollback / qB-settle work
     - or a cross-repo / deployment-specific integration issue outside this worktree
   - Produce a concrete finding with impact, affected code path, and required remediation if any.

### Proposals

1. Improve refresh lock-holder diagnostics further if `hashall refresh-status` still leaves operator ambiguity.
   - Current code now exposes:
     - `hashall refresh-status`
     - live holder PIDs/cmdlines
     - lock metadata vs stale-lock state
2. If cross-repo alignment work is reopened, update the external `silo` repo to follow the current `hashall` qB helper/cache contract.
   - Treat this as separate from required migration execution work in this repo.

## Immediate Checklist

1. The `West Wing S07` cross-device `REUSE` pilot is now proven end-to-end:
   - offline verify passed for all three siblings
   - `rehome_reconcile_only` fired on rerun
   - qB stayed `stalledUP 100%` on `/pool/media/...`
   - catalog now points all three torrents at device `141` / target save paths
2. The `Megalopolis.2024.REPACK...` live `MOVE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
   - copy to `/pool/media/...` completed
   - all three sibling views offline-verified `exact_tree`
   - validate passed after explicit `qb_stop phase=validate reason=prepare_for_patch`
   - qB ended `stalledUP 100%` on:
     - `/pool/media/torrents/seeding/cross-seed/Aither (API)`
     - `/pool/media/torrents/seeding/cross-seed/PrivateHD`
     - `/pool/media/torrents/seeding/_rehome-unique/6befda30838dbbee444769501bece3fdc5848a3e`
   - source cleanup remained deferred, manual, and explicit
3. First mixed-batch scale-up is now proven:
   - `mixed4` exposed a real bad REUSE candidate:
     - `Shining.Girls...` (`3` torrents) failed destination offline verify as `partial_match`
     - it is now an explicit exclusion, not a planner bug
   - curated replacement batch:
     - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
   - successful results:
     - `Longlegs...` REUSE completed via `rehome_reconcile_subset` with `8` good rows reconciled and `1` skipped `dest_missing` row left alone
     - `Brave.New.World.US.S01...` MOVE completed successfully
     - `Greenland.2020.Repack...` MOVE completed successfully
   - qB now shows all affected `Brave New World` and `Greenland` torrents as `stalledUP 100%` on `/pool/media/...`
4. Preserve the narrow ownership fix pattern for future sidecar fetches: if qB can read media files but cannot create missing sidecars, check for `root:root 755` payload directories first.
5. The next curated live batch is now also green:
   - plan: `out/rehome-plan-pool-data-to-media-next4c.json`
   - successful payload groups:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared post-apply summary:
     - `25 torrent(s) checked, all in acceptable state`
6. Current carve-outs from the clean `MOVE` lane:
   - `Magic.City.S01...`
     - failed after copy with `Target file count mismatch after move`
     - observed runtime stats: source `8 files / 106474639951 bytes`, target `9 files / 110028001871 bytes`
     - treat as dirty-target/preexisting-content case until code rejects this earlier
   - `Wilding.2023...`
     - copy completed and target verify passed
     - offline verify then stalled at `checking_files 0.00%` for `15m+`
     - treat as verifier-stall case until code adds stagnation detection
7. Audit conclusion from the recent failures:
  - no evidence of a broad fastresume patch corruption bug
  - the remaining code gaps are:
    - preexisting-target rejection/reporting for `MOVE`
    - offline-verify stagnation detection
    - better lock-holder diagnostics on `~/.hashall/rehome.lock`
9. Remaining follow-up backlog after the 2026-03-12 cleanup + reconcile wave:
   - only `1` tagged group remains in follow-up
   - payload `a1041c6049c66abe...` (`Longlegs...`) is still a real live failure because one member remains on `/pool/data/...` and reports `save_path_mismatch`
10. Remaining live remediation gap:
   - add a direct reconcile/remediate path for stale sibling-root drift groups so the `6` old `/data == /stash` hashes can be repointed onto their surviving `/pool/media/...` payload groups without another copy

## 2026-04-19 Normalization Loop Update

- `hashall=0.8.14`
- Multi-pass sim/dry-run loop completed for the current normalization helper and wrapper changes.
- New fixes from this pass:
  - qB read-only planning falls back to cached rows on auth/login failure.
  - normalization planning prefers shared RT cache rows before live XMLRPC.
  - transient qB/RT planning failures now become explicit non-ready plan issues instead of tracebacks.
  - empty qB path fields no longer derive the worktree cwd as an RT target.
  - wrapper candidate classification now falls back to RT path scope when qB path fields are blank.
- Verification:
  - `pytest -q tests/test_qbittorrent.py tests/test_path_normalize.py`
  - result: `30 passed`
- Current operational state:
  - direct helper dry-run is safe again, but qB login was still resetting during planning
  - RT cache freshness was `stale_error`
  - wrapper auto-pick correctly refused to select a live candidate under those conditions
- This means the next live normalization pilot should wait for healthy qB/RT cache/controller state rather than forcing apply during degraded reads.

## 2026-04-19 Normalization Recovery Update

- Controller recovery:
  - recreated `qbittorrent_vpn` and `rtorrent_vpn` from docker compose after both had died
  - qB/RT are healthy again and wrapper preflight is back to `qb=ok rt=ok rt_freshness=fresh`
- Semver / commit:
  - committed helper/wrapper outcome hardening as `10f54f9`
  - bumped `hashall` to `0.8.14`
- Remaining `cross-seed-link` lane no longer stops at `/pool/media` exhaustion:
  - wrapper now prefers `/pool/media` first, then advances to `/data/media` / `/stash/media`
  - repoint-only same-inode cases are now treated as safe instead of `target_content_already_exists`
- New live normalization results after controller recovery:
  - successful live pilots:
    - `5b13542670579f80881b496032cb95db09e352af`
    - `e04e524750c999acfc9afd5c9a604e12fbaee0d8`
    - `5c877f46f4d9fa0d8ea18bf72fe6711680d03cf6`
  - current live legacy scope after those pilots:
    - `16` qB rows on `cross-seed-link`
    - `16` RT rows on `cross-seed-link`
- New edge cases found and fixed after those pilots:
  - helper no longer derives RT runtime targets with the old custom logic; it now uses shared `derive_rt_target_directory(...)`
  - helper no longer upgrades arbitrary non-verifying states like RT `error` to `verified`
  - wrapper watch/post-check no longer relies only on cached per-hash RT rows; it now tries live qB/RT reads first and only falls back to cache if live reads fail
- Verification after the follow-up fixes:
  - `pytest -q tests/test_path_normalize.py tests/test_qbittorrent.py`
  - result: `34 passed`
  - `bash -n scripts/pilot-normalization.sh`
- Important nuance from the `5c877...` pilot:
  - the move itself succeeded
  - live qB/RT both converged to canonical `cross-seed` paths
  - the old watch implementation misreported `ambiguous_needs_review` because RT cache lagged behind live RT state
  - that observability bug is now fixed in the wrapper
