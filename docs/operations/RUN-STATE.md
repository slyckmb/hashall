# Operational Run State

Last updated: 2026-03-13

## Live Reality / Drift

- `hashall` is now `0.8.0`.
- New 2026-03-15 qB compatibility/cache hardening:
  - local cache implementation now lives in this repo:
    - `src/hashall/qb_cache.py`
    - `bin/qb-cache-agent.py`
    - `bin/qb-cache-daemon.py`
  - the cache now uses the shared qB client, not qbitui’s separate raw-API implementation
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
    - qbitui’s external dashboard/cache path has not been updated in this repo; treat that as separate follow-up work if cross-repo alignment is still wanted
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
