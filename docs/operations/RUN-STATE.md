# Operational Run State

Last updated: 2026-03-11

## Pool Migration Status

- Donor acquisition and offline attach are the shared backbone for both `REUSE` and `MOVE`.
- The current rsync-based donor transfer is still the data mover; qB is metadata-only.
- `REUSE` continues in small batches; each apply must finish with `stoppedup`/`stalledup`, no new downloads, and clean cleanup messages.
- `qb-zfs-relocate` has already proven the guarded live `pool-data -> pool-media` mover for pilot batches.
- `rehome` now has an explicit root-to-root planner for this domain:
  - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding`
  - shared-root sibling collisions are now surfaced and get synthesized unique destination views.
- `rehome apply` now uses the hardened `qb-zfs-relocate` backend for donor verification, offline fastresume patching, restart checks, and deferred cleanup.
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
  - `stalledUP=5145`
  - `uploading=5`
  - no active `stoppedDL`
  - no active `stoppedUP`
- The active qB problem lane is now repair-oriented:
  - this stoppedDL lane has now been cleared
  - one hardened live repair fixed `0fff0ce260a58b789f857f6ad085a5d03622b952`
  - the other six initially failed only because qB lacked write access to create missing sidecar files
  - after changing just those six payload directories from `root:root 755` to owner `1026:101`, qB fetched the missing sidecars and all six returned to `stalledUP 100%`
- `qb-start-seeding-gradual` halt at `2026-03-08 14:34` is explained historically:
  - `35` halted hashes were a direct subset of the old audited `49`
  - the daemon tripped on preexisting `missingFiles` rows in protected scope, not on a newly started torrent

## Known Gaps

1. Shared-root payload groups can now be planned; the new execution path has now proven both single-plan pilots and a curated mixed batch, but not yet a live `2-to-1 -> 2-to-2` case.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The next live gap is scaling from the first successful curated mixed batch to another curated batch from the remaining clean candidates.
5. `hashall payload siblings` read-only catalog bug is fixed in commit `74ea2b5`; use that command freely against the live catalog now.
6. `MOVE` still needs stronger fail-closed behavior around dirty preexisting targets and stalled offline verify paths.

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
