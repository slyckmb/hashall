# Handoff Notes

## Key Facts

- `hashall` package semver is now `0.4.178`.
- New stale-assumption hardening landed on 2026-03-12:
  - shared module: `src/rehome/reality.py`
  - new CLI: `hashall rehome drift-audit --plan <plan.json>`
  - every `rehome apply` run now writes `reality-pre.json`, `reality-post.json`, and `reality-failure.json` beside the hardened manifest
  - these snapshots compare live qB state, fastresume path fields, catalog rows, and filesystem existence instead of trusting any one source of truth
  - row classifications now include:
    - `aligned_target`
    - `catalog_drift_already_targeted`
    - `stale_runtime_and_fastresume_root`
    - `stale_runtime_root`
    - `stale_fastresume_root`
    - `target_view_missing`
    - `qbit_transient`
    - `incomplete_torrent`
    - `mixed_drift`
  - preflight failures now include plain-English guidance derived from the live snapshot instead of only raw qB state strings
  - targeted validation for this slice:
    - `pytest tests/test_rehome_reality.py tests/test_rehome_cli_followup.py tests/test_rehome_cli_lock.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_rehome_catalog_sync.py -q`
    - result: `40 passed`
- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.13`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.177`.
- New direct stale-root reconnect command landed on 2026-03-12:
  - CLI: `hashall rehome qb-missing-remediate`
  - purpose: reconnect `missingFiles` torrents that still point at dead `/data == /stash` roots to already-healthy surviving sibling payloads under `/pool/media/...`
  - live proof:
    - `Cleverman.S02...` (`2` hashes) remediated successfully
    - `Megalopolis...` (`4` hashes) remediated successfully
  - current post-run qB snapshot:
    - `stalledUP=5144`
    - `uploading=1`
    - `stoppedUP=6`
    - `missingFiles=0`
  - the `6` stoppedUP rows are the freshly reattached hashes left paused on purpose after reconnect
- `qb-repair-payload-group.sh` was hardened in commit `5d83419`:
  - wrapper: `bin/qb-repair-payload-group.sh`
  - core module: `src/hashall/qb_repair_payload_group.py`
  - script semver: `v0.2.0`
  - validates that `--good` and `--broken` share the same `payload_hash` before any apply step
  - uses dynamic catalog device/file-table resolution, full relative-path file matching, shared fastresume backup/journal logic, and per-run artifacts under `out/qb-repair-payload-group/<stamp>-<hash>/`
  - targeted validation now passes locally:
    - `pytest tests/test_fastresume.py tests/test_qb_repair_payload_group.py -q`
    - result: `8 passed`
- New `rehome` planning capability landed in commit `e572bf8`:
  - new CLI: `hashall rehome relocate-plan`
  - core planner: `src/rehome/normalize.py`
  - this can now generate `rehome apply` batch plans for explicit root-to-root relocations such as `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - shared-root sibling groups are now surfaced as one payload move plus synthesized unique destination views when sibling torrents would collide on the same target save path
  - this is the first planner step toward handling `2-to-1 -> 2-to-2` payload/view relocation inside `rehome`
- `rehome apply` now uses the hardened relocation backend for MOVE/REUSE attachment:
  - donor acquisition remains qB-metadata-only and copy-first
  - offline verify, validate, patch, restart checks, and deferred cleanup reuse the guarded `qb-zfs-relocate` contract
  - tests covering the merged path now pass locally:
    - `pytest tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py -q`
    - result: `47 passed`
  - cross-device `REUSE` reruns now support catalog-only catch-up after successful live repoint:
    - executor logs `rehome_reconcile_only`
    - offline verify still runs
    - validate/patch are skipped when qB is already on the target save paths
    - catalog sync then updates the target `payloads` row and `torrent_instances`
  - non-reconcile `MOVE` runs now explicitly stop qB before patch-mode validate:
    - this removes the false `torrent_not_stopped` blocker that appeared after successful copy + offline verify
    - the live `Megalopolis.2024.REPACK...` pilot proved the corrected path
  - staged follow-up cleanup is now available in `rehome`:
    - `hashall rehome followup --cleanup` now stages source roots into hidden `.rehome-cleanup-stage/<payload_hash>/...`
    - it observes qB on the target save paths before final delete
    - any qB regression restores the staged source roots automatically
  - small live `rehome` pilots are now green on both major paths:
    - `REUSE`: `The.West.Wing.S07...` cross-device reuse group completed and catalog-synced on rerun via `rehome_reconcile_only`
    - `MOVE`: `Megalopolis.2024.REPACK...` moved from `/pool/data/...` to `/pool/media/...`, verified `exact_tree`, patched, resumed, and left source cleanup deferred
- mixed-state reruns are now handled safely:
  - commit `85b91af` added partial reconcile support for batches where some rows are already repointed and verified while others were skipped
  - post-patch save-path verification now ignores rows that were not actually patched
  - this unblocked the live `Longlegs` mixed-batch rerun
- commit `21ea673` added streamed rsync progress for `rehome` MOVE copy windows:
  - long `MOVE` transfers now emit `copy_progress percent=... elapsed=... eta=...`
  - a long pause after `step=move_payload` is no longer expected on new runs
- commit `f3071ff` fixed a real false-negative verify path exposed by `Mickey.17...`:
  - source bytes and a clean target copy both verified `exact_tree`
  - bug 1: source recheck completion could mark `completed` before qB ever entered a real `checking*` state
  - bug 2: transient post-copy `partial_match` results were not retried when `rehome` supplied hardened manifest rows with `copy_status=pending`
  - live proof on 2026-03-12:
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-111522-36390ecee324f1af/`
    - `Mickey.17.2025.1080p.iT.WEB-DL.DDP5.1.Atmos.H.264-BYNDR.mkv` completed `MOVE` successfully and ended `stoppedUP 100%` on `/pool/media/...`
- The 2026-03-12 stale sibling-root drift lane is now remediated live:
  - original scope:
    - `Megalopolis...` (`4` hashes)
    - `Cleverman.S02...` (`2` hashes)
  - root cause in plain English:
    - healthy sibling torrents for those payloads already existed under newer `/pool/media/...` target views
    - the stale hashes were left behind still pointing at dead old `/data == /stash` views in both qB and `.fastresume`
  - live result:
    - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
    - qB no longer has an active `missingFiles` lane for this class
- Follow-up cleanup is now hardened against creating more of this class:
  - cleanup now checks for any surviving same-`payload_hash` torrent refs that still point at non-target devices or old `/data`/`/stash` aliases
  - staged cleanup will stay blocked until those stale sibling refs are reconciled
- New stale-root audit exists for missing qB items:
  - CLI: `hashall rehome qb-missing-audit`
  - the original audited live cohort was `49` `missingFiles` items classified as `root_drift_fastresume_stale`
  - that stale-root `missingFiles` lane has now been remediated live in waves using `qb-zfs-relocate`
  - the older `/pool/data -> /pool/media` lane is no longer the active blocker
  - the current `missingFiles` lane is the separate 6-item `/data == /stash` sibling-root drift class described above
- current qB state snapshot after the new sibling-root audit:
    - `stalledUP=5138`
    - `uploading=7`
    - `missingFiles=6`
  - the active qB problem lane is now these `6` stale sibling-root drift rows
- Guarded relocation coverage is current:
  - `tests/test_qb_zfs_relocate.py` previously passed locally for the guarded dataset relocation slice
  - `hashall rehome relocate-plan --help` works
  - `hashall rehome qb-missing-audit --help` works
- Live qB relocation already succeeded for `pool-data -> pool-media` via `qb-zfs-relocate`:
  - successful migrate runs are logged under `~/.logs/qb-zfs-relocate/`
  - cleanup completed successfully for prior successful pilot batches
- Treat the older 49-item `missingFiles` cohort as a legacy remediation lane, not proof of a current `qb-zfs-relocate` fastresume scribbler.

## Immediate Next Work

1. Hardened live repair succeeded and the sidecar-fetch lane is now clear.
   - commit `fe6b0fb` fixed qB API readiness checks after container restart
   - `0fff0ce260a58b789f857f6ad085a5d03622b952` repaired from sibling donor and now seeds normally again
   - live artifact: `out/qb-repair-payload-group/20260310-164254-0fff0ce260a5/repair-plan.json`
2. The remaining sidecar blockers were resolved operationally.
   - qB resume attempts initially failed with `Permission denied` creating missing `.nfo` / `.srt` files
   - root cause: the six payload directories were `root:root 755` while qB runs as uid `1026` gid `101`
   - minimal live fix: change ownership of just those six directories to `1026:101`, then resume the six torrents
   - result: qB fetched the missing sidecars and all six returned to `stalledUP 100%`
3. `hashall payload siblings` read-only bug is fixed in commit `74ea2b5`.
4. `hashall refresh --verbose` has now returned `OK` after the stale-root / stoppedDL cleanup work.
   - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
5. The `West Wing S07` cross-device `REUSE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-155600-8277eae774b3591b/`
   - all three siblings ended `stalledUP 100%` on `/pool/media/...`
   - catalog now shows:
     - `2d9004e9... -> payload_id 13703, device_id 141, save_path /pool/media/.../Aither (API)`
     - `8bf2aec2... -> payload_id 13703, device_id 141, save_path /pool/media/.../TorrentLeech`
     - `f18b8cd0... -> payload_id 13703, device_id 141, save_path /pool/media/.../_rehome-unique/...`
6. The `Megalopolis.2024.REPACK...` `MOVE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
   - all three sibling views verified `exact_tree`
   - qB ended `stalledUP 100%` on the target roots
   - catalog now shows:
     - `14e3deab... -> payload_id 13557, device_id 141, save_path /pool/media/.../Aither (API)`
     - `4da8ec78... -> payload_id 9704, device_id 141, save_path /pool/media/.../PrivateHD`
     - `6befda30... -> payload_id 13557, device_id 141, save_path /pool/media/.../_rehome-unique/...`
   - source removal stayed deferred and manual
7. The first mixed live scale-up is now green in curated form:
   - bad candidate excluded:
     - `Shining.Girls...` REUSE group from `mixed4`
     - reason: all `3` rows failed destination offline verify as `partial_match`, so this is a real bad reuse candidate, not a planner-only false positive
   - successful batch plan:
     - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
   - successful live results:
     - `Longlegs...` REUSE completed via `rehome_reconcile_subset`
       - `8` rows reconciled cleanly on `/pool/media/...`
       - `1` `dest_missing` row was left untouched on `/pool/data/...`
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-180840-a1041c6049c66abe/`
     - `Brave.New.World.US.S01...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-182010-66eebb2df636b12a/`
       - all `4` torrents ended `stalledUP 100%` on `/pool/media/...`
     - `Greenland.2020.Repack...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-183147-adf55dffe6443f6a/`
       - all `8` torrents ended `stalledUP 100%` on `/pool/media/...`
   - source cleanup remained deferred/manual for all three payload groups
8. Second curated live scale-up is now also green:
   - plan file: `out/rehome-plan-pool-data-to-media-next4c.json`
   - all four `MOVE` payload groups completed successfully:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared log ended with:
     - `✅ Summary: 25 torrent(s) checked, all in acceptable state`
9. Two `MOVE` carve-outs are now known and should stay out of the clean batch lane until separately investigated:
   - `Magic.City.S01...`
     - failed after copy with `Target file count mismatch after move`
     - observed runtime stats:
       - source: `8 files / 106474639951 bytes`
       - target: `9 files / 110028001871 bytes`
     - interpretation: dirty/preexisting target content, not a broad fastresume corruption signal
   - `Wilding.2023...`
     - copy completed and target verify passed
     - offline verify then sat at `checking_files 0.00%` for `15m+`
     - interpretation: verifier-control-path issue until re-tested, not proof of mover corruption
10. Deep audit conclusion on the recent failures:
    - there is no evidence of a broad errant fastresume scribbler in current `rehome` / `qb-zfs-relocate`
    - the recent failures have been:
      - stale-root drift already remediated
      - dirty/preexisting destination content (`Magic City`)
      - bad reuse candidate (`Shining.Girls`)
      - verifier stall behavior (`Wilding`)
11. Live staged cleanup is now proven on `/pool/data -> /pool/media` follow-up:
    - one pilot payload and six additional pool-data payload groups completed `cleanup_result=done`
    - follow-up reconcile then auto-healed the catalog-only backlog for healthy groups
    - two final cleanup retries initially restored because of source-side ownership/permission errors:
      - `/pool/data/cross-seed/PrivateHD`
      - `/stash/media/torrents/seeding/cross-seed/seedpool (API)/Stranger.Things.S03.1080p.NF.WEB-DL.DDP5.1.x264-NTG`
    - after a narrow ownership fix on those source paths, both cleanup retries completed `done`
12. Current follow-up backlog after the cleanup wave:
    - only `1` tagged group remains in follow-up:
      - payload `a1041c6049c66abe...` (`Longlegs...`)
      - reason: one live qB row still seeds from `/pool/data/...` and reports `save_path_mismatch`
    - everything else in the cleanup-required lane is now drained
13. Current qB health snapshot after cleanup + reconcile:
    - `stalledUP=5147`
    - `uploading=4`
14. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- `hashall rehome relocate-plan` is now the explicit planner for root-to-root relocation cases that `auto` does not surface cleanly.
- `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` remains the canonical proof path for the legacy `/pool/data` stale-root cohort.
- `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` is now the canonical proof path for the current 6-item sibling-root drift cohort.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
