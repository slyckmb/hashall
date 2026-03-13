# Ops Log Entry (Compact-Safe)

Canonical living state:
`docs/operations/RUN-STATE.md`

Latest stale-assumption hardening note (2026-03-13):

- `hashall` is now `0.6.11`.
- Anchor note:
  - the intended invariant is unique per-item qB payload trees, instantiated from donor payloads via hardlinks where possible
  - do not read `unique target` or `de-hitchhike` as “make redundant physical copies”
- New 2026-03-13 repo hygiene note:
  - active docs were reduced to a minimal canonical set
  - duplicate/stub docs were archived under `docs/archive/2026-doc-consolidation/`
  - active-tree compatibility stubs should not be reintroduced
- New 2026-03-13 hardlink-normalization note:
  - `rehome` view construction now relinks identical preexisting destination files to donor inodes
  - `qb-repair-fresh` now does the same during same-fs target preparation
  - this closes the main code paths that were preserving copied bytes instead of hardlink-backed per-item payload trees
- New 2026-03-13 planner stale-no-op hardening:
  - `relocate-plan` now skips groups when all per-hash view targets are already `source_save_path == target_save_path`
  - this closes the deferred-cleanup planner gap that kept resurfacing fully converged families like `Brave.New.World.US.S01...`
  - live proof:
    - `Brave.New.World.US.S01...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-114142-66eebb2df636b12a/`
    - the refresh-seeded remainder is no longer the active planner source once a live-qB-seeded plan exists
- New 2026-03-13 refresh/jdupes diagnosis note:
  - the last `refresh --verbose` completed its orchestration and left step 3.5 as backlog, not as a still-running refresh worker
  - the actionable failure in that run was buried in jdupes group output:
    - `Cinderella.2021...`
    - `err=jdupes did not link files with matching SHA256`
  - new diagnostics landed:
    - `hashall link execute` now prints the jdupes log glob and a failed-action preview
    - `bin/db-refresh-step4_5-link-dedup.sh` now writes a structured per-device summary JSON and logs per-plan dry-run/apply rc plus failed-action preview
- New 2026-03-13 Twisters bridge hardening:
  - planner now prefers surviving target donors for stale already-targeted rows
  - single-file unique targets keep `root_dir/file` layout
  - mixed `reconcile_subset + patch_one` manifests now work
  - qB is restarted automatically if validate/patch fails after `qb_stop`
  - reality snapshots now classify this lane as `stale_runtime_and_fastresume_root`
  - live proof:
    - `Twisters.2024...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-112558-9962465e30b69544/`
    - `9/9` verified `exact_tree`
    - `reconcile_rows=8 patch_rows=1`
- New de-hitchhike note:
  - root-to-root relocation planning now defaults multi-hash groups to per-hash unique target roots
  - missing-file reconnect plans now follow the same rule
  - stash->pool `rehome` view planning now also routes multi-hash groups into `_rehome-unique/<hash>` targets
  - successful attaches now remove an unused intermediate donor root when the full sibling group is covered in-plan
  - the goal is one correct payload tree per torrent item, with shared physical bytes via hardlinks when allowed
  - targeted validation:
    - `pytest tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py tests/test_rehome_mapping.py tests/test_rehome_catalog_sync.py -q -k 'unique or payload_rows or preflight_existing_view_conflicts_logs_progress_for_missing_targets'`
    - `pytest tests/test_rehome_atomic_relocation.py -q -k cleanup_unused_target_donor_removes_intermediate_root`
    - result: `7 passed`
- Live proof note:
  - `Cinderella.2021...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-095751-578fffbfe4fc2f8c/`
  - its post snapshot still warned about one shared payload row because the run started before the de-hitchhike planner landed
- New active remainder baseline:
  - `out/rehome-plan-pool-data-to-media-refresh6-20260313.json`
  - `out/rehome-plan-pool-data-to-media-refresh6-20260313-drift.json`
  - `plans=31`
  - `rows=189`
  - `attention_rows=167`
  - `plans_with_out_of_plan_siblings=11`
  - group states:
    - `23 ready_repoint_or_reconcile`
    - `5 blocked_qbit_sibling_gap`
    - `3 blocked_target_view_missing`
- Next clean live slice is prepared and dry-run green:
  - `out/rehome-plan-pool-data-to-media-twisters-only-20260313.json`
  - `out/rehome-plan-pool-data-to-media-twisters-only-20260313-drift.json`
  - `MOVE`
  - `affected_torrents=9`
  - `unique_view_targets=9`
- New queued proving task:
  - `Alien Romulus` sibling family
  - current observed scope:
    - `14` sibling candidates
    - `7` `~noHL` siblings
    - one known incomplete `PD` row (`1376e795...`)
  - use this group next to prove that rehome/repair can lift the `~noHL` siblings to `pool-media` as unique per-item payload trees backed by hardlinks where possible

- `hashall` is now `0.6.8`.
- New 2026-03-12 preflight feedback note:
  - `_preflight_existing_view_conflicts()` now emits heartbeat / completion lines during long existing-target scans
  - new log keys:
    - `preflight_target_views_progress`
    - `preflight_target_views_view_done`
    - `preflight_target_views_complete`
  - this closes the quiet `step=preflight_target_views` UX gap exposed during the `Snowfall...` live move
- New 2026-03-12 target-view preflight note:
  - `rehome` now probes preexisting target view paths before `build_views`
  - if an existing destination file differs from the source bytes, the plan aborts before creating any new hardlinks
  - this closes the `Novitiate...` partial-view-build risk that previously allowed one clean sibling view to be created before a later conflicting path exploded
  - live proof:
    - `The.Long.Walk.2025...` `REUSE` completed successfully with the new `step=preflight_target_views` phase
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-214219-38c7f2c20c7af677/`
  - current live migration baseline after the Twisters rerun:
    - `old_path_count=34`
    - `new_path_count=317`
    - qB health: `stalledup=5152`, `stoppeddl=1`, `stalleddl=2`
  - new live-qB-seeded remainder baseline:
    - `out/rehome-plan-pool-data-to-media-liveqb-20260313.json`
    - `seed_scope=live_qb_root`
    - `qbit_hashes=34`
    - `mapped_payloads=14`
    - `candidates=14`
    - `reuse=7`
    - `move=7`
    - `covered old-root hashes=34/34`
- New 2026-03-12 `qb-missing-remediate` note:
  - old `/data -> /pool/data` reuse-drift rows can now reconnect against an exact mapped target payload even when the surviving target catalog row has a different `payload_hash`
  - this fixed the `Peppermint...` gap where dry-run previously showed `selected_plans: 0`
  - live result:
    - `4` stale `missingFiles` rows reattached successfully
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-212329-4f2ac41db39d760f/`
    - source audit now returns `rows: 0` for `/data -> /pool/data`
- `hashall` is now `0.4.181`.
- New 2026-03-12 verifier/reality note:
  - the `Wakanda` ebook false-negative was code, not bad content
  - direct source verify proved `exact_tree` with `verify_ratio=1.0`
  - the bug was that instant-complete rechecks could skip `checking_files`, leaving `verify_reason=no_recheck_transition`
  - `qb-libtorrent-verify.py` now promotes those healthy instant-complete results
  - `rehome` reality snapshots also now classify a normal source-only `MOVE` row as `source_only` instead of `target_view_missing`
  - post-apply snapshots now classify healthy target-side qB checking as `post_apply_settling` / `settling_after_apply` instead of `blocked_qbit_transient`
  - `rehome apply` now accepts sliced batch JSON files that only contain `{ \"plans\": [...] }`
  - reality/drift output now surfaces out-of-plan sibling coverage before cleanup time
  - successful live rerun:
    - `~/.logs/hashall/reports/rehome-relocate/20260312-145812-6bb9bb5432f39cbb/`
  - targeted validation:
    - `pytest tests/test_rehome_cli_apply.py tests/test_rehome_reality.py tests/test_rehome_catalog_sync.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_qb_libtorrent_verify.py -q`
    - result: `46 passed`
- New shared reality/drift module:
  - `src/rehome/reality.py`
- New proactive audit command:
  - `hashall rehome drift-audit --plan <plan.json>`
- `rehome apply` now writes live state snapshots into each per-run artifact directory:
  - `reality-pre.json`
  - `reality-post.json`
  - `reality-failure.json`
- The snapshot compares:
  - qB runtime state
  - `.fastresume` path fields
  - catalog payload/torrent-instance rows
  - expected target views from the plan
  - actual source/target existence on disk
- Targeted validation passed locally:
  - `pytest tests/test_rehome_reality.py tests/test_rehome_cli_followup.py tests/test_rehome_cli_lock.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_rehome_catalog_sync.py -q`
  - result: `40 passed`

Latest critical operations note (2026-03-06):

- `qb-stoppeddl-bucket` now clean (`active=0 total_entries=0`) in live checks.
- `qb-stoppeddl-drain` empty-index error fixed:
  - commit `657eccc`
  - semver `v0.1.23`
  - behavior: valid empty bucket returns `selected=0` no-op.
- Current strategic ops shift:
  - stop treating `device_id` as durable identity;
  - implement `fs_uuid`-first identity path for payload/torrent/rehome flows.
- New repair path is active:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
- Live repair progress:
  - `214` identity actions applied on `~/.hashall/catalog.db` (including final `/pool/media` batch).
  - current repair dry-run reports `payload_candidates=0`, `torrent_candidates=0`, `unresolved=0`.
- Residual catalog risks:
  - parked negative `device_id` row remains in `devices` (`-905882091`).
  - ensure refresh step-2 continues scanning `/pool/media` to avoid reintroducing unknown device rows.
- New architecture WIP now active and uncommitted:
  - move physical `files_*` storage binding from volatile `device_id` to stable `fs_uuid` via `devices.files_table`.
  - keep `files_<device_id>` only as compatibility views.
  - migration: `src/hashall/migrations/0013_stable_files_table_binding.sql`.
- Rollout status:
  - blocker cleared, targeted suite green, migration workflow hardened with dry-run/apply/snapshot/report.
  - copied-DB rehearsal succeeded.
  - live `~/.hashall/catalog.db` migration completed with snapshot and post-apply preflight `ok=true`.

Latest tooling note (2026-03-08):

- Guarded qB dataset relocation workflow added:
  - `bin/qb-zfs-relocate.py` (`v0.1.4`)
  - `src/hashall/qb_zfs_relocate.py`
  - phases: `plan/copy/verify/validate/patch/resume/cleanup/rollback`
  - migrate now supports `--auto-cleanup=safe` with staged `rename -> observe -> delete`
  - resume observation now honors the configured soak window instead of short-circuiting immediately on first healthy check
  - pool-data wrapper default `PILOT_OBSERVE_SECONDS` is now `60`
  - cleanup now live-validates qB state, verify evidence, path safety, and overlap rules before any delete path
  - wrappers now write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
- Shared bencode/fastresume groundwork added:
  - `src/hashall/bencode.py`
  - strict full-consumption decode now backs fastresume mutation.
- Repo-local CLI bootstrap added:
  - `python3 -m hashall` now resolves from repo root via local bootstrap packages.
- Latest local validation for this tooling slice:
  - `pytest tests/test_qb_zfs_relocate.py -q`
  - result: `29 passed`
- Live relocation status:
  - successful migrate runs observed at `12:03` and `12:30` on 2026-03-08
  - both completed with `resume_ok=2` and `exit_code=0`
  - cleanup dry-runs against both successful manifests returned `blocked=0`, `dryrun=2`, `source_missing=0`
  - live cleanup has now completed for both successful manifests; four source payloads were removed from `/pool/data/media/torrents/seeding`
  - latest `v0.1.4` run at `14:33` completed with `resume_ok=2`, `cleaned=2`, `blocked=0`, and a full `60s` resume observe window

Latest rehome integration note (2026-03-08):

- `hashall` is now `0.4.164`.
- Commit `e572bf8` added explicit root-to-root relocation planning in `rehome`:
  - new CLI: `hashall rehome relocate-plan`
  - new core planner path in `src/rehome/normalize.py`
  - supports batch plans for explicit moves like `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - synthesizes unique destination sibling views under `_rehome-unique/<hash>` when a shared-root group would otherwise collide on the same target view
- Commits `d553f20` and `264ec25` closed the next execution gap:
  - new CLI: `hashall rehome qb-missing-audit`
  - `rehome apply` now routes donor verification / offline fastresume mutation through the guarded `qb-zfs-relocate` backend
  - `MOVE` source cleanup is now deferred instead of deleting source payloads immediately
- Commit `65eaa82` added a stale-root remediation step to `qb-zfs-relocate`:
  - source missing + destination already present now becomes `copy_status=reused_existing_dest`
  - this allows legacy root-drift items to reuse the already-good `/pool/media/...` payload instead of failing in copy
- Live audit result for the current qB `missingFiles` cohort:
  - `49` items currently classified by the tool as `root_drift_fastresume_stale`
  - evidence: old `/pool/data/...` qB + fastresume paths, mapped `/pool/media/...` payload present
  - interpretation: legacy stale-root path drift, not new `qb-zfs-relocate` corruption
- Latest live stale-root remediation pilot status:
  - refresh was not hung; it finished `PARTIAL` because payload sync hit `24` zero-file old-root upgrade entries from this same cohort
  - `qb-start-seeding-gradual` halt set of `35` hashes is a subset of the audited `49`
  - explicit dry-run pilot on `Stranger.Things.S02` (`3` hashes) reused existing destination payload and verified all `3` hashes as `exact_tree`
  - current uncommitted blocker: `validate` still rejects these rows with `torrent_not_complete` because qB reports stale `progress=0.0`
- Latest validation for this slice:
  - `pytest tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py -q`
  - result: `47 passed`
  - `hashall rehome relocate-plan --help`
  - `hashall rehome qb-missing-audit --help`
  - `pytest tests/test_qb_zfs_relocate.py -q`
  - result after commit `65eaa82`: `33 passed`

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/ops-log.md`

Latest repair/handoff note (2026-03-10):

- `hashall` is now `0.4.168`.
- Commit `5d83419` hardened payload-group repair:
  - `bin/qb-repair-payload-group.sh` is now a thin launcher over `src/hashall/qb_repair_payload_group.py`
  - validates `payload_hash` equality before apply
  - matches files by relative path, not basename
  - uses shared fastresume backup/journal logic instead of ad hoc in-place mutation
  - writes per-run artifacts under `out/qb-repair-payload-group/<stamp>-<hash>/`
  - targeted validation passed locally:
    - `pytest tests/test_fastresume.py tests/test_qb_repair_payload_group.py -q`
    - result: `8 passed`
- Live qB repair progress:
  - commit `fe6b0fb` fixed qB API readiness checks used by the repair restart path
  - `0fff0ce260a58b789f857f6ad085a5d03622b952` repaired successfully from donor `4511c5f4149223175792ca180eea5a41655abea4`
  - qB now reports that hash as healthy again
  - the former `6`-item sidecar blocker lane was resolved by a narrow ownership fix on the affected payload directories
  - qB then fetched the missing `.nfo` / `.srt` files from peers
  - current non-healthy qB lane is clear
  - current qB state snapshot:
    - `stalledUP=5145`
    - `uploading=5`
    - no active `stoppedDL`
    - no active `stoppedUP`
- Hardened repair artifacts:
  - initial dry-run artifact:

Latest sibling-root drift note (2026-03-12):

- `hashall` is now `0.4.176`.
- `hashall` is now `0.4.177`.
- New 2026-03-12 remediation/reconnect note:
  - `hashall rehome qb-missing-remediate` now exists for stale sibling-root `missingFiles` rows
  - it builds synthetic guarded `REUSE` plans against surviving `/pool/media/...` donor payloads
  - it now handles:
    - `root_drift_to_surviving_sibling_target`
    - `root_drift_fastresume_stale` rows that still have healthy sibling donors
  - live proof:
    - `Cleverman.S02...` (`2` hashes) succeeded
    - `Megalopolis...` (`4` hashes) succeeded
  - post-run live state:
    - `/data == /stash` stale-root audit returns `0`
    - qB now shows `missingFiles=0`
    - the six remediated hashes are `stoppedUP` by design
- Current qB snapshot is:
  - `stalledUP=5138`
  - `uploading=7`
  - `missingFiles=6`
- The updated `qb-missing-audit` now classifies all `6` current `missingFiles` rows as `root_drift_to_surviving_sibling_target`.
- Live proof:
  - `Megalopolis...` contributes `4` hashes
  - `Cleverman.S02...` contributes `2` hashes
  - all `6` still point at dead old `/data == /stash` roots in qB and `.fastresume`
  - healthy sibling target views already exist on `/pool/media/...`
- Preventive fix:
  - `rehome followup --cleanup` now blocks staged cleanup whenever any same-`payload_hash` sibling torrent row still points at a non-target device or old `/data`/`/stash` alias
  - this closes the historical gap that could leave stale sibling hashes behind after source cleanup
    - `out/qb-repair-payload-group/20260310-102047-0fff0ce260a5/repair-plan.json`
  - successful live apply artifact:
    - `out/qb-repair-payload-group/20260310-164254-0fff0ce260a5/repair-plan.json`
- Sidecar-fetch root cause and fix:
  - qB log showed `Permission denied` when creating the missing sidecars
  - affected payload directories were owned by `root:root` with mode `755`
  - qB runs as uid `1026` gid `101`
  - changing only those six directories to owner `1026:101` was sufficient for qB to fetch the sidecars and recover all six torrents
- Separate repo issue is no longer open:
  - commit `74ea2b5` fixed `hashall payload siblings` to open catalogs read-only

Latest rehome pilot note (2026-03-11):

- `hashall` is now `0.4.171`.
- Commit `4fd8781` fixed catalog catch-up for already-repointed cross-device `REUSE` reruns:
  - executor now detects `rehome_reconcile_only` after offline verify when qB is already on the target save paths
  - relocation validate/patch are skipped
  - catalog sync still runs and updates target `payloads` rows plus `torrent_instances`
- Commit `310b136` fixed patch-mode orchestration for non-reconcile `MOVE`:
  - `rehome apply` now explicitly stops qB before patch-mode validate
  - this removes the false `torrent_not_stopped` blocker after successful copy + offline verify
- Live `REUSE` pilot success:
  - `The.West.Wing.S07...`
  - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-155600-8277eae774b3591b/`
  - all `3` siblings offline-verified `exact_tree`
  - qB ended `stalledUP 100%` on `/pool/media/...`
  - catalog now points all `3` torrents at device `141` / target save paths
- Live `MOVE` pilot success:
  - `Megalopolis.2024.REPACK...`
  - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
  - copy completed from `/pool/data/...` to `/pool/media/...`
  - all `3` sibling views offline-verified `exact_tree`
  - qB ended `stalledUP 100%` on the target save paths
  - source cleanup remained deferred/manual
- Refresh / qB baseline after the repair lane clear:
  - `hashall refresh --verbose` returned `OK`
  - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` returned `0`
- Next prepared scale-up:
  - plan file: `out/rehome-plan-pool-data-to-media-mixed4.json`
  - dry-run already completed cleanly
  - contents:
    - `REUSE`: `Shining.Girls...` (`3` torrents)
    - `REUSE`: `Longlegs...` (`9` torrents)
    - `MOVE`: `Brave.New.World.US.S01...` (`4` torrents)
    - `MOVE`: `Greenland.2020.Repack...` (`8` torrents)

Latest mixed-batch note (2026-03-11):

- Commit `85b91af` fixed mixed-state rehome reruns:
  - post-patch save-path verification now ignores rows that were not actually patched
  - executor now supports `rehome_reconcile_subset` for batches where some rows are already repointed and verified while others were skipped
- `mixed4` surfaced one real bad candidate:
  - `Shining.Girls...` REUSE group (`0fff0ce2...`, `4511c5f4...`, `57316294...`)
  - all `3` rows failed destination offline verify as `partial_match`
  - this group should be excluded from future reuse batches until separately investigated/repaired
- Curated replacement batch:
  - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
- Live `mixed3` results:
  - `Longlegs...` REUSE:
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-180840-a1041c6049c66abe/`
    - `8` rows were already repointed/verified and reconciled via `rehome_reconcile_subset`
    - `1` row (`3a9b02d88bbecd94...`) remained `dest_missing` and was intentionally left on `/pool/data/...`
  - `Brave.New.World.US.S01...` MOVE:
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-182010-66eebb2df636b12a/`
    - all `4` torrents ended `stalledUP 100%` on `/pool/media/...`
  - `Greenland.2020.Repack...` MOVE:
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-183147-adf55dffe6443f6a/`
    - all `8` torrents ended `stalledUP 100%` on `/pool/media/...`
- Cleanup remained deferred/manual for all three successful payload groups.

Latest scale-up / audit note (2026-03-11):

- Commit `21ea673` improved MOVE observability:
  - `rehome` now streams rsync copy progress with elapsed/ETA during long `MOVE` copy windows
- Curated live batch `next4c` completed successfully:
  - plan file: `out/rehome-plan-pool-data-to-media-next4c.json`
  - successful payload groups:
    - `Brave.New.World.US.S01...`
    - `Greenland.2020.Repack...`
    - `Azrael...`
    - `Stranger.Things.S03...`
  - shared post-apply summary:
    - `25 torrent(s) checked, all in acceptable state`
- Two MOVE carve-outs were confirmed during this wave:
  - `Magic.City.S01...`
    - failed after copy with `Target file count mismatch after move`
    - runtime stats at failure:
      - source `8 files / 106474639951 bytes`
      - target `9 files / 110028001871 bytes`
    - interpretation: destination was already dirty/preexisting; not evidence of a general fastresume bug
  - `Wilding.2023...`
    - copy completed and target verify passed
    - offline verify then remained at `checking_files 0.00%` for `15m+`
    - interpretation: verifier-control-path issue until stagnation detection is added
- Deep audit conclusion for the recent failures:
  - no evidence of a broad errant fastresume edit path in current `rehome` / `qb-zfs-relocate`
  - observed failure classes were:
    - already-remediated stale-root drift
    - bad reuse candidate (`Shining.Girls`)
    - dirty/preexisting target content (`Magic City`)
    - verifier stall behavior (`Wilding`)
- Next code slice should harden:
  - fail-closed `MOVE` rejection on dirty preexisting targets
  - richer source/target count/byte mismatch reporting
  - offline verify stagnation detection
  - lock-holder diagnostics for `~/.hashall/rehome.lock`

Latest cleanup note (2026-03-12):

- The active operational gap is now source cleanup, not migrate correctness.
- Green `/pool/data -> /pool/media` `MOVE` waves are still leaving duplicate canonical payloads behind on `/pool/data/...`.
- Current code path:
  - `rehome apply` intentionally leaves source cleanup deferred
  - `rehome followup --cleanup` still needs the guarded staged-delete contract from `qb-zfs-relocate`
- Operational consequence:
  - repeated successful migration waves temporarily double-consume pool space on the same zpool
- Next code slice should port:
  - source-root rename into hidden staging
  - qB observe window on the target save paths
  - delete only after the observe window stays healthy
  - restore staged roots immediately if qB regresses

Latest staged follow-up cleanup note (2026-03-12):

- Commit `f960483` landed the staged safe cleanup path in `rehome followup`.
- Live cleanup pilot success:
  - payload `ab23b3ff...` (`English.Teacher...`)
  - `cleanup_attempted=1`, `cleanup_done=1`, `cleanup_failed=0`
- Live pool-data cleanup wave success:
  - six more `/pool/data` payload groups completed `cleanup_result=done`
  - no cleanup failures
  - qB post-cleanup health snapshot:
    - `stalledUP=5147`
    - `uploading=4`
- Remaining follow-up backlog after the cleanup wave:
  - `9` tagged groups remain
  - `4` are still `ok` but are non-pool-data or source-device-unknown cleanup candidates
  - `5` remain blocked by stale catalog/device state and need reconciliation before cleanup

Latest relocate bugfix note (2026-03-12):

- `hashall` is now `0.4.175`.
- `qb-zfs-relocate` is now `v0.1.12`.
- Commit `f3071ff` fixed and live-proved the `Mickey.17...` false-partial verify case.
  - source bytes were good; direct source verify passed `exact_tree`
  - a clean target copy also passed `exact_tree`
  - root causes:
    - qB source recheck completion detection was too permissive
    - transient exact-tree `partial_match` results were not retried when `rehome` supplied `copy_status=pending`
  - live proof report dir:
    - `~/.logs/hashall/reports/rehome-relocate/20260312-111522-36390ecee324f1af/`
  - final state:
    - `stoppedUP 100%` on `/pool/media/...`

Latest follow-up reconcile note (2026-03-12):

- Commit `2511ce2` added follow-up-side catalog reconcile for healthy rows:
  - target device is now inferred from the active candidate hashes, not every torrent sharing the payload hash
  - healthy rows can switch `torrent_instances.payload_id` to the already-correct target payload row before cleanup
  - canonical-target fallback handles sibling views that intentionally reuse one target payload row
- Live result:
  - cleanup backlog collapsed from `9` groups to `3`
  - `2` cleanup retries initially restored because of narrow source-side ownership/permission errors:
    - `/pool/data/cross-seed/PrivateHD`
    - `/stash/media/torrents/seeding/cross-seed/seedpool (API)/Stranger.Things.S03.1080p.NF.WEB-DL.DDP5.1.x264-NTG`
  - after a targeted ownership fix, both retries completed `cleanup_result=done`
- Current end-state:
  - follow-up now shows only `1` remaining failed group:
    - payload `a1041c6049c66abe...` (`Longlegs...`)
    - one live qB row still seeds from `/pool/data/...` and reports `save_path_mismatch`
